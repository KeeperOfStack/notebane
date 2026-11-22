"""GuildPlayer — per-(guild_id, channel_id) audio player."""

from __future__ import annotations

import asyncio
import logging
import re
import shlex
import subprocess
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from functools import lru_cache
from typing import TYPE_CHECKING

import discord

if TYPE_CHECKING:
    from notebane.ytdl import FastStream, PreparedMedia, PreparedTrack

log = logging.getLogger("notebane.player")

# FFmpeg flags — reconnect on dropped streams
FFMPEG_BEFORE_OPTIONS = (
    "-reconnect 1 "
    "-reconnect_streamed 1 "
    "-reconnect_delay_max 5"
)
FFMPEG_OPTIONS = "-vn"

# Undo/redo history depth per voice session
UNDO_DEPTH = 10


@dataclass
class Track:
    """Represents a queued audio track."""

    title: str
    url: str          # direct stream URL when resolved; webpage_url placeholder when stub
    webpage_url: str  # human-facing URL (always set)
    duration: int | None = None   # seconds; None for livestreams
    thumbnail: str | None = None
    requester: str = "unknown"
    http_headers: dict[str, str] | None = None  # headers yt-dlp says to send (User-Agent etc.)
    resolved: bool = True  # False = stub; url is not yet a real stream URL

    def duration_fmt(self) -> str:
        """Return HH:MM:SS or MM:SS string, or '∞' for streams."""
        if self.duration is None:
            return "∞"
        m, s = divmod(self.duration, 60)
        h, m = divmod(m, 60)
        return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"

    @classmethod
    def make_stub(cls, entry: dict, requester: str = "unknown") -> Track:
        """Build an unresolved Track from a yt-dlp flat playlist entry.

        Uses only metadata available from flat extraction (no yt-dlp resolve call).
        The real stream URL will be fetched JIT in the play loop before FFmpeg opens.
        """
        webpage_url = entry.get("webpage_url") or entry.get("url") or ""
        title = entry.get("title") or entry.get("id") or "Unknown title"
        duration = entry.get("duration")
        thumbnail = (
            entry.get("thumbnail")
            or ((entry.get("thumbnails") or [{}])[-1].get("url"))
        )
        return cls(
            title=title,
            url=webpage_url,       # placeholder — overwritten by JIT resolve
            webpage_url=webpage_url,
            duration=duration,
            thumbnail=thumbnail,
            requester=requester,
            resolved=False,
        )


# Callback signature: called when a new track starts playing
NowPlayingCallback = Callable[["GuildPlayer", Track], None]


class _ElapsedAudioSource(discord.AudioSource):
    """Count emitted 20 ms Opus packets so a local fallback can seek accurately."""

    def __init__(self, source: discord.AudioSource) -> None:
        self.source = source
        self.packet_count = 0

    def read(self) -> bytes:
        packet = self.source.read()
        if packet:
            self.packet_count += 1
        return packet

    def is_opus(self) -> bool:
        return self.source.is_opus()

    def cleanup(self) -> None:
        cleanup = getattr(self.source, "cleanup", None)
        if cleanup is not None:
            cleanup()

    @property
    def _current_error(self) -> Exception | None:
        return getattr(self.source, "_current_error", None)

    @property
    def elapsed_seconds(self) -> float:
        return self.packet_count * 0.02


class _ObservedAudioSource(discord.AudioSource):
    """Count source reads and packets for diagnosing silent voice playback."""

    def __init__(self, source: discord.AudioSource) -> None:
        self.source = source
        self.reads = 0
        self.opus_packets = 0
        self.bytes_read = 0
        self._is_opus: bool | None = None

    def read(self) -> bytes:
        self.reads += 1
        packet = self.source.read()
        if packet:
            self.bytes_read += len(packet)
            if self.is_opus():
                self.opus_packets += 1
        return packet

    def is_opus(self) -> bool:
        if self._is_opus is None:
            self._is_opus = bool(self.source.is_opus())
        return self._is_opus

    def cleanup(self) -> None:
        cleanup = getattr(self.source, "cleanup", None)
        if cleanup is not None:
            cleanup()


@lru_cache(maxsize=1)
def _ffmpeg_supports_bounded_http() -> bool:
    """Return whether the installed FFmpeg exposes bounded HTTP request flags."""
    try:
        result = subprocess.run(
            ["ffmpeg", "-hide_banner", "-h", "protocol=http"],
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    output = result.stdout + result.stderr
    return (
        result.returncode == 0
        and "-request_size" in output
        and "-initial_request_size" in output
    )


def _stream_before_options(headers: dict[str, str] | None) -> str:
    """Build FFmpeg input flags, adding bounded HTTP flags when supported."""
    flags = [
        "-reconnect", "1",
        "-reconnect_streamed", "1",
        "-reconnect_delay_max", "5",
    ]
    if _ffmpeg_supports_bounded_http():
        flags.extend((
            "-multiple_requests", "1",
            "-request_size", "1048576",
            "-initial_request_size", "1048576",
            "-short_seek_size", "1048576",
        ))
    if headers:
        header_blob = "".join(f"{key}: {value}\r\n" for key, value in headers.items())
        flags.extend(("-headers", shlex.quote(header_blob)))
    return " ".join(flags)


def _local_seek_options(seconds: float) -> str:
    return f"-ss {max(0.0, seconds):.3f}"


def _stable_track(track: Track) -> Track:
    """Keep expiring media URLs out of player state and restore snapshots."""
    page_url = track.webpage_url or track.url
    return Track(
        title=track.title,
        url=page_url,
        webpage_url=page_url,
        duration=track.duration,
        thumbnail=track.thumbnail,
        requester=track.requester,
        http_headers=None,
        resolved=False,
    )


def _local_source(media: PreparedMedia, seek_seconds: float | None = None) -> discord.AudioSource:
    codec = "copy" if (media.audio_codec or "").lower() in {"opus", "libopus"} else None
    kwargs = {"options": FFMPEG_OPTIONS, "codec": codec}
    if seek_seconds is not None and seek_seconds > 0:
        kwargs["before_options"] = _local_seek_options(seek_seconds)
    return discord.FFmpegOpusAudio(media.path, **kwargs)


def _direct_source(track: Track) -> discord.AudioSource:
    before_options = FFMPEG_BEFORE_OPTIONS
    if track.http_headers:
        header_blob = "".join(f"{key}: {value}\r\n" for key, value in track.http_headers.items())
        before_options += " -headers " + shlex.quote(header_blob)
    return discord.FFmpegOpusAudio(
        track.url,
        before_options=before_options,
        options=FFMPEG_OPTIONS,
    )


def _fast_source(stream: FastStream) -> _ElapsedAudioSource:
    source = discord.FFmpegOpusAudio(
        stream.url,
        before_options=_stream_before_options(stream.http_headers),
        options=FFMPEG_OPTIONS,
    )
    return _ElapsedAudioSource(source)


class GuildPlayer:
    """Manages playback for a single voice channel in a guild.

    Keyed by (guild_id, channel_id). Each instance owns:
    - its asyncio.Queue of Tracks
    - its discord.VoiceClient connection
    - its background play-loop task
    """

    def __init__(
        self,
        voice_client: discord.VoiceClient,
        on_track_start: NowPlayingCallback | None = None,
    ) -> None:
        self.voice_client = voice_client
        self.queue: asyncio.Queue[Track] = asyncio.Queue()
        self._play_task: asyncio.Task | None = None
        self._track_done = asyncio.Event()
        self.current: Track | None = None
        self._last_play_error: Exception | None = None
        self._audio_source_metrics: _ObservedAudioSource | None = None
        self.loop_track = False
        self.loop_queue = False
        self._on_track_start = on_track_start  # called with (player, track) on each start
        self._bg_tasks: set[asyncio.Task] = set()  # background enqueue tasks — cancelled on stop/disconnect
        self._cookiefile: str | None = None  # set by music cog; forwarded to JIT resolve
        self._prefetch_task: asyncio.Task | None = None
        self._prefetch_track: Track | None = None

        # Undo/redo stacks — in-memory, session-scoped (cleared on bot restart by design)
        self._undo_stack: deque[list[Track]] = deque(maxlen=UNDO_DEPTH)
        self._redo_stack: deque[list[Track]] = deque(maxlen=UNDO_DEPTH)

        # Playback history — tracks appended as they finish; used by previous()
        self._history: deque[Track] = deque(maxlen=20)
        self._going_previous: bool = False  # signal: skip loop/history logic on this stop
        self._going_restart: bool = False   # signal: replay current track from beginning

    # ── Properties ────────────────────────────────────────────────────────────

    @property
    def guild_id(self) -> int:
        return self.voice_client.guild.id

    @property
    def channel_id(self) -> int:
        return self.voice_client.channel.id  # type: ignore[union-attr]

    @property
    def is_playing(self) -> bool:
        return self.voice_client.is_playing()

    @property
    def is_paused(self) -> bool:
        return self.voice_client.is_paused()

    @property
    def is_connected(self) -> bool:
        return self.voice_client.is_connected()

    # ── Lifecycle ──────────────────────────────────────────────────────────────

    async def start(self) -> None:
        """Ensure the background play-loop is running."""
        if self._play_task is None or self._play_task.done():
            self._play_task = asyncio.get_event_loop().create_task(self._play_loop())

    def _after_play(self, error: Exception | None) -> None:
        """Handle audio-player completion on the asyncio event loop."""
        self._last_play_error = error
        if error:
            safe_message = re.sub(r"https?://\S+", "<URL redacted>", str(error))
            log.error("[guild=%d] playback error: %s", self.guild_id, safe_message)
        metrics = self._audio_source_metrics
        self._audio_source_metrics = None
        if metrics is not None:
            connected = self.voice_client.is_connected()
            opus_state = metrics._is_opus
            log.info(
                "[guild=%d] audio_source_complete: reads=%d opus_packets=%d bytes=%d "
                "is_opus=%s callback_error=%s voice_connected=%s",
                self.guild_id,
                metrics.reads,
                metrics.opus_packets,
                metrics.bytes_read,
                str(opus_state) if opus_state is not None else "unknown",
                type(error).__name__ if error is not None else "none",
                connected,
            )
        self._track_done.set()

    async def _play_loop(self) -> None:
        """Start a fast stream immediately and spool finite audio for recovery."""
        log.debug("[guild=%d channel=%d] play loop started", self.guild_id, self.channel_id)

        while self.is_connected:
            try:
                queued_track = await asyncio.wait_for(self.queue.get(), timeout=300.0)
            except TimeoutError:
                log.info("[guild=%d channel=%d] idle timeout, disconnecting", self.guild_id, self.channel_id)
                await self.disconnect()
                return

            track = _stable_track(queued_track)
            self.current = track
            media = None
            preparation_task = None
            try:
                prepared, preparation_task = await self._claim_preparation(queued_track)

                if prepared is not None and prepared.media is not None:
                    media = prepared.media
                    track = _stable_track(prepared.track)
                    self.current = track
                    await self._announce_track(track)
                    error = await self._play_source(_local_source(media))
                elif prepared is not None:
                    # Live sources cannot be fully spooled; use their resolved
                    # direct URL and preserve the existing streaming behavior.
                    await self._announce_track(track)
                    error = await self._play_source(_direct_source(prepared.track))
                else:
                    from notebane.ytdl import YTDLError, resolve_fast_stream

                    try:
                        fast_stream = await resolve_fast_stream(
                            queued_track, cookiefile=self._cookiefile
                        )
                        fast_audio = _fast_source(fast_stream)
                    except (YTDLError, discord.ClientException, OSError) as fast_exc:
                        log.warning(
                            "[guild=%d] fast-stream setup failed (%s); waiting for local preparation",
                            self.guild_id,
                            type(fast_exc).__name__,
                        )
                        if preparation_task is None:
                            raise RuntimeError("no preparation task is available for fallback")
                        prepared = await preparation_task
                        preparation_task = None
                        if prepared.media is not None:
                            media = prepared.media
                            track = _stable_track(prepared.track)
                            self.current = track
                            await self._announce_track(track)
                            error = await self._play_source(_local_source(media))
                        else:
                            await self._announce_track(track)
                            error = await self._play_source(_direct_source(prepared.track))
                    else:
                        await self._announce_track(track)
                        error = await self._play_source(fast_audio)
                        if error is not None:
                            log.warning(
                                "[guild=%d] fast stream for %r failed; recovering from local audio",
                                self.guild_id,
                                track.title,
                            )
                            if preparation_task is None:
                                log.error("[guild=%d] no local preparation task is available", self.guild_id)
                            else:
                                try:
                                    prepared = await preparation_task
                                    preparation_task = None
                                except asyncio.CancelledError:
                                    raise
                                except Exception:
                                    log.exception(
                                        "[guild=%d] local recovery download failed for %r",
                                        self.guild_id,
                                        track.title,
                                    )
                                else:
                                    if prepared.media is not None:
                                        media = prepared.media
                                        track = _stable_track(prepared.track)
                                        self.current = track
                                        error = await self._play_source(
                                            _local_source(media, fast_audio.elapsed_seconds)
                                        )
                                    else:
                                        log.error(
                                            "[guild=%d] no finite local fallback for %r",
                                            self.guild_id,
                                            track.title,
                                        )

                if error is not None:
                    log.error(
                        "[guild=%d] track %r ended with a playback error; not recording it as completed",
                        self.guild_id,
                        track.title,
                    )
                    self.current = None
                    continue

                if self._going_previous:
                    self._going_previous = False
                    self.current = None
                    continue

                if self._going_restart:
                    self._going_restart = False
                    rest = self.queue_list()
                    self._replace_queue([track] + rest)
                    self.current = None
                    continue

                self._history.append(track)
                if (self.loop_track and self.current is not None) or self.loop_queue:
                    await self.queue.put(track)
                self.current = None
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception(
                    "[guild=%d] track preparation/playback failed for %r; advancing queue",
                    self.guild_id,
                    track.title,
                )
                self.current = None
            finally:
                await self._dispose_preparation(preparation_task, keep_media=media)
                if media is not None:
                    media.cleanup()

        log.debug("[guild=%d channel=%d] play loop exited", self.guild_id, self.channel_id)

    async def skip(self) -> None:
        """Skip the current track."""
        if self.voice_client.is_playing() or self.voice_client.is_paused():
            self.voice_client.stop()   # triggers _after_play → _track_done.set()

    async def restart(self) -> bool:
        """Restart the current track from the beginning.

        Sets _going_restart so the play loop re-queues the same track at the
        front without recording it in history.  Returns True if a track was
        restarted, False if nothing is playing.
        """
        if self.current is None:
            return False
        self._going_restart = True
        if self.voice_client.is_playing() or self.voice_client.is_paused():
            self.voice_client.stop()  # triggers _after_play → _track_done.set()
        return True

    async def previous(self) -> Track | None:
        """Go back to the previous track.

        Pops the last entry from history, places it at the front of the queue
        (followed by the current track, then the existing queue), sets the
        _going_previous flag so the play loop skips its normal history/loop
        bookkeeping on this stop, then stops the current track.

        Returns the track that will play next, or None if history is empty.
        """
        if not self._history:
            return None

        prev_track = self._history.pop()

        # Rebuild queue: [prev, current, ...rest]
        rest = self.queue_list()
        new_queue: list[Track] = [prev_track]
        if self.current is not None:
            new_queue.append(self.current)
        new_queue.extend(rest)
        self._replace_queue(new_queue)

        self._going_previous = True
        if self.voice_client.is_playing() or self.voice_client.is_paused():
            self.voice_client.stop()  # triggers _after_play → _track_done.set()

        return prev_track

    def pause(self) -> bool:
        """Pause playback. Returns True if paused, False if nothing was playing."""
        if self.voice_client.is_playing():
            self.voice_client.pause()
            return True
        return False

    def resume(self) -> bool:
        """Resume playback. Returns True if resumed, False if nothing was paused."""
        if self.voice_client.is_paused():
            self.voice_client.resume()
            return True
        return False

    def queue_list(self) -> list[Track]:
        """Snapshot of the queue as a list (index 0 = next up)."""
        return list(self.queue._queue)  # type: ignore[attr-defined]

    # ── Undo / Redo ───────────────────────────────────────────────────────────

    def record_mutation(self) -> None:
        """Snapshot the current queue before a mutation. Clears the redo stack.

        Must be called BEFORE any operation that changes the queue so that
        /undo can restore the pre-change state.
        """
        self._undo_stack.append(self.queue_list())
        self._redo_stack.clear()

    def _replace_queue(self, tracks: list[Track]) -> None:
        """Atomically replace the entire queue with `tracks`."""
        while not self.queue.empty():
            try:
                self.queue.get_nowait()
            except asyncio.QueueEmpty:
                break
        for t in tracks:
            self.queue.put_nowait(t)

    def undo(self) -> list[Track] | None:
        """Revert the queue to its state before the last mutation.

        Pushes the current queue onto the redo stack.
        Cancels any still-running background playlist loaders so they
        cannot re-populate the queue after the undo.
        Returns the restored queue snapshot, or None if nothing to undo.
        """
        if not self._undo_stack:
            return None
        # Cancel in-flight playlist loaders before replacing the queue.
        for t in list(self._bg_tasks):
            t.cancel()
        self._bg_tasks.clear()
        self._redo_stack.append(self.queue_list())
        prev = self._undo_stack.pop()
        self._replace_queue(prev)
        return prev

    def redo(self) -> list[Track] | None:
        """Re-apply the last undone mutation.

        Pushes the current queue onto the undo stack so the redo is itself
        undoable. Cancels any still-running background playlist loaders.
        Returns the restored queue snapshot, or None if nothing to redo.
        """
        if not self._redo_stack:
            return None
        # Cancel in-flight playlist loaders before replacing the queue.
        for t in list(self._bg_tasks):
            t.cancel()
        self._bg_tasks.clear()
        self._undo_stack.append(self.queue_list())
        nxt = self._redo_stack.pop()
        self._replace_queue(nxt)
        return nxt

    async def wait_for_bg_tasks(self) -> None:
        """Wait for all in-flight background playlist loaders to complete.

        Used by /createlist so it can snapshot the queue only AFTER every
        enqueued track has been resolved and added to asyncio.Queue.
        Safe to call with no running tasks — returns immediately.
        """
        if not self._bg_tasks:
            return
        # Copy the set — tasks may add/remove themselves while we await
        pending = list(self._bg_tasks)
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)

    async def _prepare_track(self, track: Track) -> PreparedTrack:
        from notebane.ytdl import prepare_track
        return await prepare_track(track, cookiefile=self._cookiefile)

    async def _claim_preparation(
        self, track: Track
    ) -> tuple[PreparedTrack | None, asyncio.Task[PreparedTrack] | None]:
        """Claim a matching prefetch, without delaying the fast-stream path."""
        from notebane.ytdl import YTDLError

        task = self._prefetch_task
        target = self._prefetch_track
        self._prefetch_task = None
        self._prefetch_track = None

        if task is not None and target is track:
            if not task.done():
                return None, task
            try:
                return task.result(), None
            except asyncio.CancelledError:
                current = asyncio.current_task()
                if current is not None and current.cancelling():
                    raise
                log.warning("[guild=%d] completed audio prefetch was cancelled; retrying", self.guild_id)
            except YTDLError:
                log.exception("[guild=%d] completed audio prefetch failed; retrying", self.guild_id)
        elif task is not None:
            if not task.done():
                task.cancel()
            try:
                stale = await task
            except asyncio.CancelledError:
                current = asyncio.current_task()
                if current is not None and current.cancelling():
                    raise
                stale = None
            except YTDLError:
                stale = None
            if stale is not None and stale.media is not None:
                stale.media.cleanup()

        task = asyncio.get_running_loop().create_task(self._prepare_track(track))
        return None, task

    async def _announce_track(self, track: Track) -> None:
        log.info(
            "[guild=%d channel=%d] playing: %s (req: %s)",
            self.guild_id, self.channel_id, track.title, track.requester,
        )
        if self._on_track_start:
            try:
                self._on_track_start(self, track)
            except Exception:
                log.exception("on_track_start callback raised")
        try:
            from notebane.metrics import record_track_played
            record_track_played()
        except Exception as exc:  # noqa: BLE001 - metrics must never interrupt audio playback
            log.debug("Track-play metric unavailable: %s", exc)

    async def _play_source(self, source: discord.AudioSource) -> Exception | None:
        self._track_done.clear()
        self._last_play_error = None
        source_has_reader = callable(getattr(source, "read", None))
        source_has_opus_flag = callable(getattr(source, "is_opus", None))
        observed_source = _ObservedAudioSource(source) if source_has_reader and source_has_opus_flag else None
        self._audio_source_metrics = observed_source
        play_source = observed_source if observed_source is not None else source
        loop = asyncio.get_running_loop()

        def _after_from_audio_thread(error: Exception | None) -> None:
            loop.call_soon_threadsafe(self._after_play, error)

        try:
            self.voice_client.play(play_source, after=_after_from_audio_thread)
        except Exception:
            self._audio_source_metrics = None
            cleanup = getattr(play_source, "cleanup", None)
            if cleanup is not None:
                try:
                    cleanup()
                except Exception:
                    log.debug("[guild=%d] audio source cleanup failed after play startup error", self.guild_id, exc_info=True)
            raise
        self._start_audio_prefetch()
        await self._track_done.wait()
        return self._last_play_error

    async def _dispose_preparation(
        self, task: asyncio.Task[PreparedTrack] | None, keep_media: PreparedMedia | None = None
    ) -> None:
        from notebane.ytdl import YTDLError

        if task is None:
            return
        if not task.done():
            task.cancel()
        try:
            result = await task
        except asyncio.CancelledError:
            current = asyncio.current_task()
            if current is not None and current.cancelling():
                raise
            return
        except YTDLError:
            return
        if result.media is not None and result.media is not keep_media:
            result.media.cleanup()

    @staticmethod
    def _cleanup_prefetch_result(task: asyncio.Task) -> None:
        from notebane.ytdl import YTDLError

        try:
            result = task.result()
        except (asyncio.CancelledError, YTDLError):
            return
        if result.media is not None:
            result.media.cleanup()

    def _start_audio_prefetch(self) -> None:
        """Download at most the next finite queued track while this one plays."""
        queued = self.queue_list()
        if not queued or queued[0].duration is None:
            return
        target = queued[0]
        existing = self._prefetch_task
        if existing is not None:
            if self._prefetch_track is target:
                return
            if not existing.done():
                return
            existing.add_done_callback(self._cleanup_prefetch_result)

        self._prefetch_track = target
        self._prefetch_task = asyncio.get_running_loop().create_task(self._prepare_track(target))

    async def _cancel_audio_prefetch(self) -> None:
        from notebane.ytdl import YTDLError

        task = self._prefetch_task
        self._prefetch_task = None
        self._prefetch_track = None
        if task is None:
            return
        if not task.done():
            task.cancel()
        try:
            result = await task
        except asyncio.CancelledError:
            current = asyncio.current_task()
            if current is not None and current.cancelling():
                raise
            return
        except YTDLError:
            return
        if result.media is not None:
            result.media.cleanup()

    def insert_at(self, pos: int, track: Track) -> None:
        """Insert a single track at queue position `pos` (0 = front).

        Uses put_nowait + deque rotate so asyncio.Queue internals (maxsize,
        waiters) are respected — unlike raw ._queue.insert() which bypasses
        all of that and fails to wake a blocked queue.get() waiter.
        """
        self.queue.put_nowait(track)
        # put_nowait appended to the right; rotate to move it to `pos`
        dq = self.queue._queue  # type: ignore[attr-defined]
        # The newly-appended item is at dq[-1].  We need to move it to dq[pos].
        # Rotate right by (len-1 - pos) brings it to position pos from the left.
        n = len(dq)
        steps = n - 1 - min(pos, n - 1)
        dq.rotate(steps)

    def insert_next(self, tracks: list[Track]) -> None:
        """Insert one or more tracks immediately after the current song.

        Prepends `tracks` (in order) to the front of the queue, pushing
        everything else back. Used by /playnext.
        """
        current_queue = self.queue_list()
        # Rebuild: new tracks first, then whatever was already queued
        while not self.queue.empty():
            try:
                self.queue.get_nowait()
            except asyncio.QueueEmpty:
                break
        for t in tracks + current_queue:
            self.queue.put_nowait(t)

    async def stop(self) -> None:
        """Stop playback and clear the queue."""
        self.loop_track = False
        self.loop_queue = False

        await self._cancel_audio_prefetch()

        # Snapshot queue + current track BEFORE draining — powers /restore.
        # Import here to avoid circular import at module level.
        try:
            from notebane.restore_db import save_snapshot
            _snap_queue = self.queue_list()
            _snap_current = self.current
            if _snap_queue or _snap_current:
                save_snapshot(self.guild_id, self.channel_id, _snap_current, _snap_queue)
        except Exception:
            log.exception("[guild=%d] Failed to save restore snapshot", self.guild_id)

        # Cancel any background enqueue tasks (playlist loaders) so they
        # don't keep stuffing tracks back into the now-empty queue.
        for t in list(self._bg_tasks):
            t.cancel()
        self._bg_tasks.clear()

        # Drain queue
        while not self.queue.empty():
            try:
                self.queue.get_nowait()
            except asyncio.QueueEmpty:
                break

        if self.voice_client.is_playing() or self.voice_client.is_paused():
            self.voice_client.stop()

        if self._play_task and not self._play_task.done():
            self._play_task.cancel()
            try:
                await self._play_task
            except asyncio.CancelledError:
                pass

        self.current = None
        log.info("[guild=%d channel=%d] player stopped", self.guild_id, self.channel_id)

    async def disconnect(self) -> None:
        """Stop + disconnect voice client."""
        await self.stop()
        if self.voice_client.is_connected():
            await self.voice_client.disconnect(force=False)
        log.info("[guild=%d channel=%d] disconnected", self.guild_id, self.channel_id)


class GuildPlayerManager:
    """Tracks all active GuildPlayer instances across all guilds/channels.

    Lookup key: (guild_id, channel_id)
    """

    def __init__(self) -> None:
        self._players: dict[tuple[int, int], GuildPlayer] = {}

    def get(self, guild_id: int, channel_id: int) -> GuildPlayer | None:
        return self._players.get((guild_id, channel_id))

    def get_any(self, guild_id: int) -> GuildPlayer | None:
        """Return the first active player for a guild (any channel)."""
        for (gid, _), player in self._players.items():
            if gid == guild_id:
                return player
        return None

    def set(self, player: GuildPlayer) -> None:
        key = (player.guild_id, player.channel_id)
        self._players[key] = player

    def remove(self, guild_id: int, channel_id: int) -> GuildPlayer | None:
        return self._players.pop((guild_id, channel_id), None)

    def all_for_guild(self, guild_id: int) -> list[GuildPlayer]:
        return [p for (gid, _), p in self._players.items() if gid == guild_id]

    @property
    def total(self) -> int:
        return len(self._players)
