"""GuildPlayer — per-(guild_id, channel_id) audio player."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable

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


@dataclass
class Track:
    """Represents a queued audio track."""

    title: str
    url: str          # direct stream URL (from yt-dlp)
    webpage_url: str  # human-facing URL (for embeds)
    duration: int | None = None   # seconds; None for livestreams
    thumbnail: str | None = None
    requester: str = "unknown"

    def duration_fmt(self) -> str:
        """Return HH:MM:SS or MM:SS string, or '∞' for streams."""
        if self.duration is None:
            return "∞"
        m, s = divmod(self.duration, 60)
        h, m = divmod(m, 60)
        return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


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

            try:
                source = discord.FFmpegOpusAudio(
                    track.url,
                    before_options=FFMPEG_BEFORE_OPTIONS,
                    options=FFMPEG_OPTIONS,
                )
            except Exception:
                log.exception("[guild=%d] FFmpeg source creation failed for %r", self.guild_id, track.title)
                self.current = None
                continue

            self.voice_client.play(source, after=self._after_play)

            # Wait for this track to finish (or be stopped)
            await self._track_done.wait()

            # Loop-track: re-queue same track at front
            if self.loop_track and self.current is not None:
                await self.queue.put(track)

            self.current = None

        log.debug("[guild=%d channel=%d] play loop exited", self.guild_id, self.channel_id)

    async def skip(self) -> None:
        """Skip the current track."""
        if self.voice_client.is_playing() or self.voice_client.is_paused():
            self.voice_client.stop()   # triggers _after_play → _track_done.set()

    async def stop(self) -> None:
        """Stop playback and clear the queue."""
        self.loop_track = False
        self.loop_queue = False

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
