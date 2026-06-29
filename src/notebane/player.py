"""GuildPlayer — per-(guild_id, channel_id) audio player.

Phase 2 scaffold: state machine, queue, voice client slot.
Audio pipeline (yt-dlp → FFmpegOpusAudio) added in Phase 3.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import discord

log = logging.getLogger("notebane.player")


@dataclass
class Track:
    """Represents a queued audio track (resolved in Phase 3)."""

    title: str
    url: str
    webpage_url: str
    duration: int | None = None  # seconds
    thumbnail: str | None = None
    requester: str = "unknown"


class GuildPlayer:
    """Manages playback for a single voice channel in a guild.

    Keyed by (guild_id, channel_id). Each instance owns:
    - its asyncio.Queue of Tracks
    - its discord.VoiceClient connection
    - its background play-loop task
    """

    def __init__(self, voice_client: discord.VoiceClient) -> None:
        self.voice_client = voice_client
        self.queue: asyncio.Queue[Track] = asyncio.Queue()
        self._play_task: asyncio.Task | None = None
        self.current: Track | None = None
        self.loop_track = False
        self.loop_queue = False

    @property
    def guild_id(self) -> int:
        return self.voice_client.guild.id

    @property
    def channel_id(self) -> int:
        return self.voice_client.channel.id

    @property
    def is_playing(self) -> bool:
        return self.voice_client.is_playing()

    @property
    def is_paused(self) -> bool:
        return self.voice_client.is_paused()

    @property
    def is_connected(self) -> bool:
        return self.voice_client.is_connected()

    async def start(self) -> None:
        """Start the background play-loop task (Phase 3 fills this in)."""
        if self._play_task is None or self._play_task.done():
            self._play_task = asyncio.get_event_loop().create_task(self._play_loop())

    async def _play_loop(self) -> None:
        """Placeholder — Phase 3 implements yt-dlp → FFmpegOpusAudio here."""
        log.debug("[guild=%d channel=%d] play loop started (stub)", self.guild_id, self.channel_id)
        # Phase 3 will: dequeue Track → resolve stream URL → create FFmpegOpusAudio → voice_client.play()

    async def stop(self) -> None:
        """Stop playback, clear queue, cancel task."""
        # Drain the queue
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
