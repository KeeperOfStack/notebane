"""GuildPlayer — per-(guild_id, channel_id) audio player."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable
from collections import deque

import discord

if TYPE_CHECKING:
    pass

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
    def make_stub(cls, entry: dict, requester: str = "unknown") -> "Track":
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
        self.loop_track = False
        self.loop_queue = False
        self._on_track_start = on_track_start  # called with (player, track) on each start
        self._bg_tasks: set[asyncio.Task] = set()  # background enqueue tasks — cancelled on stop/disconnect
        self._cookiefile: str | None = None  # set by music cog; forwarded to JIT resolve

        # Undo/redo stacks — in-memory, session-scoped (cleared on bot restart by design)
        self._undo_stack: deque[list[Track]] = deque(maxlen=UNDO_DEPTH)
        self._redo_stack: deque[list[Track]] = deque(maxlen=UNDO_DEPTH)

        # Playback history — tracks appended as they finish; used by previous()
        self._history: deque[Track] = deque(maxlen=20)
        self._going_previous: bool = False  # signal: skip loop/history logic on this stop

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
        """Called by discord.py in a thread when a track finishes."""
        if error:
            log.error("[guild=%d] playback error: %s", self.guild_id, error)
        self._track_done.set()

    async def _play_loop(self) -> None:
        """Dequeue tracks and stream them one by one."""
        log.debug("[guild=%d channel=%d] play loop started", self.guild_id, self.channel_id)

        while self.is_connected:
            try:
                track = await asyncio.wait_for(self.queue.get(), timeout=300.0)
            except TimeoutError:
                # Idle for 5 minutes — disconnect
                log.info("[guild=%d channel=%d] idle timeout, disconnecting", self.guild_id, self.channel_id)
                await self.disconnect()
                return

            self.current = track
            self._track_done.clear()

            # JIT-resolve stub tracks: fetch the real stream URL now, just
            # before we hand it to FFmpeg. Stubs are created during instant
            # playlist loading (flat extract only — no per-track yt-dlp call).
            if not track.resolved:
                try:
                    from notebane.ytdl import resolve as ytdl_resolve
                    track = await ytdl_resolve(
                        track.webpage_url,
                        requester=track.requester,
                        cookiefile=self._cookiefile,
                    )
                    self.current = track
                except Exception:
                    log.exception(
                        "[guild=%d] JIT resolve failed for %r — skipping track",
                        self.guild_id, track.webpage_url,
                    )
                    self.current = None
                    continue

            log.info(
                "[guild=%d channel=%d] playing: %s (req: %s)",
                self.guild_id, self.channel_id, track.title, track.requester,
            )

            # Notify via callback (music cog sends the "now playing" embed)
            if self._on_track_start:
                try:
                    self._on_track_start(self, track)
                except Exception:
                    log.exception("on_track_start callback raised")

            # Record metric
            try:
                from notebane.metrics import record_track_played
                record_track_played()
            except Exception:
                pass

            try:
                # Build the before_options with any headers yt-dlp requires
                # (e.g. User-Agent for ANDROID_VR client URLs — without these
                # YouTube returns HTTP 403 and FFmpeg exits with code 8).
                before_opts = FFMPEG_BEFORE_OPTIONS
                if track.http_headers:
                    header_str = "".join(
                        f' -headers "{k}: {v}\\r\\n"'
                        for k, v in track.http_headers.items()
                    )
                    before_opts = before_opts + header_str
                source = discord.FFmpegOpusAudio(
                    track.url,
                    before_options=before_opts,
                    options=FFMPEG_OPTIONS,
                )
            except Exception:
                log.exception("[guild=%d] FFmpeg source creation failed for %r", self.guild_id, track.title)
                self.current = None
                continue

            self.voice_client.play(source, after=self._after_play)

            # Pre-resolve the next unresolved stub while this track plays,
            # so the JIT resolve in the next loop iteration is often a no-op.
            self._start_presolve()

            # Wait for this track to finish (or be stopped)
            await self._track_done.wait()

            # If previous() triggered this stop, skip all loop/history logic —
            # the queue has already been rebuilt with the previous track at front.
            if self._going_previous:
                self._going_previous = False
                self.current = None
                continue

            # Record finished track in history (for /previous)
            if track is not None:
                self._history.append(track)

            # Loop-track: re-queue same track at front
            if self.loop_track and self.current is not None:
                await self.queue.put(track)
            elif self.loop_queue and track is not None:
                # Loop-queue: re-add to end so the whole queue cycles
                await self.queue.put(track)

            self.current = None

        log.debug("[guild=%d channel=%d] play loop exited", self.guild_id, self.channel_id)

    async def skip(self) -> None:
        """Skip the current track."""
        if self.voice_client.is_playing() or self.voice_client.is_paused():
            self.voice_client.stop()   # triggers _after_play → _track_done.set()

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

    def _start_presolve(self) -> None:
        """Kick off a background resolve for the first unresolved stub in the queue.

        Called once after playback starts on each track. Hides JIT latency by
        resolving the next stub while the current track is still playing.
        Only one presolve runs at a time.
        """
        # Don't double-spawn
        if any(getattr(t, "_is_presolve", False) for t in self._bg_tasks):
            return
        dq = list(self.queue._queue)  # type: ignore[attr-defined]
        for i, t in enumerate(dq):
            if not t.resolved:
                task = asyncio.get_event_loop().create_task(self._presolve_at(i, t))
                task._is_presolve = True  # type: ignore[attr-defined]
                self._bg_tasks.add(task)
                task.add_done_callback(self._bg_tasks.discard)
                return

    async def _presolve_at(self, idx: int, stub: Track) -> None:
        """Resolve `stub` and swap it in-place at queue position `idx`.

        Safe to race with the play loop: if the loop JIT-resolves the same
        track first, the swap is a no-op (resolved flag already True).
        """
        try:
            from notebane.ytdl import resolve as ytdl_resolve
            resolved = await ytdl_resolve(
                stub.webpage_url,
                requester=stub.requester,
                cookiefile=self._cookiefile,
            )
            # Swap in-place only if the stub is still there and still unresolved
            dq = self.queue._queue  # type: ignore[attr-defined]
            dq_list = list(dq)
            if (
                idx < len(dq_list)
                and dq_list[idx].webpage_url == stub.webpage_url
                and not dq_list[idx].resolved
            ):
                dq_list[idx] = resolved
                dq.clear()
                dq.extend(dq_list)
                log.debug("[guild=%d] pre-resolved %r at pos %d", self.guild_id, stub.title, idx)
        except Exception:
            log.debug(
                "[guild=%d] presolve failed for %r — play loop will JIT resolve",
                self.guild_id, stub.webpage_url,
            )

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
