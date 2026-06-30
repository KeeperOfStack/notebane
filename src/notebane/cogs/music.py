"""Music cog — /play, /skip, /stop, /pause, /resume, /shuffle, /loop, /nowplaying, /queue, /remove."""

from __future__ import annotations

import asyncio
import logging
import math
import random

import discord
from discord import app_commands
from discord.ext import commands

from notebane.cogs.voice import assert_user_in_voice, _connect_to_channel
from notebane.cookies import get_guild_cookiefile
from notebane.embeds import error as err_embed
from notebane.player import GuildPlayer, GuildPlayerManager, Track
from notebane.ytdl import YTDLError, resolve, resolve_playlist

log = logging.getLogger("notebane.music")

QUEUE_PAGE_SIZE = 10  # tracks per /queue page


# ──────────────────────────────────────────────────────────────────────────────
# Embed helpers
# ──────────────────────────────────────────────────────────────────────────────

def _now_playing_embed(track: Track, *, paused: bool = False) -> discord.Embed:
    status = "⏸ Paused" if paused else "🎵 Now Playing"
    embed = discord.Embed(
        title=status,
        description=f"**[{track.title}]({track.webpage_url})**",
        colour=discord.Colour.yellow() if paused else discord.Colour.green(),
    )
    embed.add_field(name="Duration", value=track.duration_fmt(), inline=True)
    embed.add_field(name="Requested by", value=track.requester, inline=True)
    if track.thumbnail:
        embed.set_thumbnail(url=track.thumbnail)
    return embed


class NowPlayingView(discord.ui.View):
    """Persistent control buttons attached to the Now Playing message."""

    def __init__(self, player: "GuildPlayer") -> None:
        super().__init__(timeout=None)
        self.player = player

    @discord.ui.button(emoji="⏸", style=discord.ButtonStyle.secondary, custom_id="np_pause_resume")
    async def pause_resume(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if self.player.is_paused:
            self.player.resume()
            button.emoji = "⏸"
            await interaction.response.edit_message(
                embed=_now_playing_embed(self.player.current) if self.player.current else None,
                view=self,
            )
        elif self.player.is_playing:
            self.player.pause()
            button.emoji = "▶"
            await interaction.response.edit_message(
                embed=_now_playing_embed(self.player.current, paused=True) if self.player.current else None,
                view=self,
            )
        else:
            await interaction.response.defer()

    @discord.ui.button(emoji="⏭", style=discord.ButtonStyle.secondary, custom_id="np_skip")
    async def skip(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        title = self.player.current.title if self.player.current else "current track"
        await self.player.skip()
        await interaction.response.send_message(f"⏭ Skipped **{title}**.", ephemeral=True)

    @discord.ui.button(emoji="⏹", style=discord.ButtonStyle.danger, custom_id="np_stop")
    async def stop_btn(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self.player.stop()
        await interaction.response.send_message("⏹ Stopped and cleared the queue.", ephemeral=True)


def _queued_embed(track: Track, position: int) -> discord.Embed:
    embed = discord.Embed(
        title="➕ Added to Queue",
        description=f"**[{track.title}]({track.webpage_url})**",
        colour=discord.Colour.blurple(),
    )
    embed.add_field(name="Duration", value=track.duration_fmt(), inline=True)
    embed.add_field(name="Position", value=f"#{position}", inline=True)
    embed.add_field(name="Requested by", value=track.requester, inline=True)
    if track.thumbnail:
        embed.set_thumbnail(url=track.thumbnail)
    return embed


def _playlist_queued_embed(title: str, count: int, requester: str, *, next_up: bool = False) -> discord.Embed:
    action = "▶ Up Next" if next_up else "➕ Playlist Added"
    embed = discord.Embed(
        title=action,
        description=f"**{title}**",
        colour=discord.Colour.blurple(),
    )
    embed.add_field(name="Tracks", value=str(count), inline=True)
    embed.add_field(name="Requested by", value=requester, inline=True)
    if next_up:
        embed.set_footer(text="Playlist inserted after the current track")
    return embed


def _queue_embed(player: GuildPlayer, page: int = 1) -> discord.Embed:
    """Paginated queue listing."""
    tracks = player.queue_list()
    total = len(tracks)
    total_pages = max(1, math.ceil(total / QUEUE_PAGE_SIZE))
    page = max(1, min(page, total_pages))

    embed = discord.Embed(title="📋 Queue", colour=discord.Colour.blurple())

    # Current track
    if player.current:
        t = player.current
        loop_tag = " 🔁" if player.loop_track else ""
        embed.add_field(
            name=f"▶ Now Playing{loop_tag}",
            value=f"[{t.title}]({t.webpage_url}) `{t.duration_fmt()}`\n*Requested by {t.requester}*",
            inline=False,
        )
    else:
        embed.add_field(name="▶ Now Playing", value="Nothing", inline=False)

    # Queue page
    if total == 0:
        embed.add_field(name="Up Next", value="Queue is empty.", inline=False)
    else:
        start = (page - 1) * QUEUE_PAGE_SIZE
        end = start + QUEUE_PAGE_SIZE
        lines = []
        for i, t in enumerate(tracks[start:end], start=start + 1):
            lines.append(f"`{i}.` [{t.title}]({t.webpage_url}) `{t.duration_fmt()}` — *{t.requester}*")
        embed.add_field(name=f"Up Next (page {page}/{total_pages})", value="\n".join(lines), inline=False)

    loop_tag = " • 🔁 Queue loop ON" if player.loop_queue else ""
    embed.set_footer(text=f"{total} track{'s' if total != 1 else ''} in queue{loop_tag}")
    return embed


# ──────────────────────────────────────────────────────────────────────────────
# Guard helpers
# ──────────────────────────────────────────────────────────────────────────────

async def _get_player(
    interaction: discord.Interaction,
    players: GuildPlayerManager,
    *,
    require_playing: bool = False,
    deferred: bool = False,
) -> GuildPlayer | None:
    """Fetch the active player for this guild, sending an error if absent."""

    async def _send_error(msg: str) -> None:
        if deferred:
            await interaction.followup.send(msg, ephemeral=True)
        else:
            await interaction.response.send_message(msg, ephemeral=True)

    if not interaction.guild:
        await _send_error("❌ Server-only command.")
        return None
    player = players.get_any(interaction.guild.id)
    if player is None:
        await _send_error("❌ I'm not in a voice channel.")
        return None
    if require_playing and not (player.is_playing or player.is_paused):
        await _send_error("❌ Nothing is playing right now.")
        return None
    return player


# ──────────────────────────────────────────────────────────────────────────────
# Cog
# ──────────────────────────────────────────────────────────────────────────────

class MusicCog(commands.Cog, name="Music"):
    """Audio playback commands."""

    def __init__(self, bot: commands.AutoShardedBot, players: GuildPlayerManager) -> None:
        self.bot = bot
        self.players = players
        self._text_channels: dict[int, discord.TextChannel] = {}

    # ── Now-playing callback (non-async, schedules a task) ───────────────────

    def _on_track_start(self, player: GuildPlayer, track: Track) -> None:
        text_channel = self._text_channels.get(player.channel_id)
        if text_channel is None:
            return
        view = NowPlayingView(player)
        asyncio.get_event_loop().create_task(
            text_channel.send(embed=_now_playing_embed(track), view=view)
        )

    # ── Shared: ensure player is ready ────────────────────────────────────────

    async def _ensure_player(
        self, interaction: discord.Interaction
    ) -> GuildPlayer | None:
        """Assert user is in VC, auto-join if needed, return ready player."""
        if not interaction.guild or not interaction.guild_id:
            await interaction.followup.send("❌ This command only works in a server.")
            return None

        channel = await assert_user_in_voice(interaction)
        if channel is None:
            return None

        player = self.players.get(interaction.guild_id, channel.id)
        if player is None:
            player = await _connect_to_channel(
                interaction, channel, self.players, on_track_start=self._on_track_start
            )
            if player is None:
                return None
            await player.start()
        elif player._play_task is None or player._play_task.done():
            player._on_track_start = self._on_track_start
            await player.start()

        if isinstance(interaction.channel, discord.TextChannel):
            self._text_channels[channel.id] = interaction.channel

        return player

    # ── Shared: enqueue a playlist in background ───────────────────────────────

    async def _enqueue_playlist_bg(
        self,
        interaction: discord.Interaction,
        player: GuildPlayer,
        entries: list[dict],
        playlist_title: str,
        requester: str,
        *,
        insert_next: bool = False,
        cookiefile: str | None = None,
    ) -> None:
        """Resolve and enqueue all playlist entries concurrently in the background.

        Each entry is resolved individually (full stream URL) then either
        appended to the queue or collected for insert_next().
        """
        resolved: list[Track] = []
        failed = 0

        for entry in entries:
            webpage_url = entry.get("webpage_url") or entry.get("url") or ""
            if not webpage_url:
                failed += 1
                continue
            try:
                track = await resolve(webpage_url, requester=requester, cookiefile=cookiefile)
                if insert_next:
                    resolved.append(track)
                else:
                    await player.queue.put(track)
            except YTDLError:
                failed += 1
            except Exception:
                log.exception("Unexpected error resolving playlist entry %r", webpage_url)
                failed += 1

        if insert_next and resolved:
            player.insert_next(resolved)

        # Send a completion summary to the text channel
        ch = self._text_channels.get(player.channel_id)
        if ch:
            success_count = len(entries) - failed
            summary = f"✅ **{playlist_title}** — {success_count} track(s) loaded"
            if failed:
                summary += f" ({failed} failed)"
            await ch.send(summary)

    # ── /play ─────────────────────────────────────────────────────────────────

    @app_commands.command(name="play", description="Play a song or playlist, or add to the queue.")
    @app_commands.describe(query="YouTube URL, playlist URL, other URL, or search terms")
    async def play(self, interaction: discord.Interaction, query: str) -> None:
        await interaction.response.defer()

        player = await self._ensure_player(interaction)
        if player is None:
            return

        cookiefile = get_guild_cookiefile(interaction.guild_id) if interaction.guild_id else None

        await interaction.followup.send(f"🔍 Loading `{query}`…")

        try:
            entries = await resolve_playlist(query, cookiefile=cookiefile)
        except YTDLError as exc:
            from notebane.metrics import record_ytdl_error
            record_ytdl_error()
            await interaction.edit_original_response(
                content=None,
                embed=err_embed(f"Could not load: `{query}`\n> {exc}", title="Not Found"),
            )
            return

        if len(entries) > 1:
            # Playlist — acknowledge immediately, resolve in background
            playlist_title = entries[0].get("playlist_title") or entries[0].get("playlist") or query
            await interaction.edit_original_response(
                content=None,
                embed=_playlist_queued_embed(playlist_title, len(entries), interaction.user.display_name),
            )
            asyncio.get_event_loop().create_task(
                self._enqueue_playlist_bg(
                    interaction, player, entries, playlist_title,
                    requester=interaction.user.display_name,
                    cookiefile=cookiefile,
                )
            )
        else:
            # Single track — resolve fully before responding
            entry = entries[0] if entries else None
            url = (entry or {}).get("webpage_url") or (entry or {}).get("url") or query
            try:
                track = await resolve(url, requester=interaction.user.display_name, cookiefile=cookiefile)
            except YTDLError as exc:
                from notebane.metrics import record_ytdl_error
                record_ytdl_error()
                await interaction.edit_original_response(
                    content=None,
                    embed=err_embed(f"Could not find: `{query}`\n> {exc}", title="Not Found"),
                )
                return
            except Exception as exc:
                log.exception("Unexpected resolve error for %r", query)
                await interaction.edit_original_response(
                    content=None,
                    embed=err_embed(str(exc), title="Unexpected Error"),
                )
                return

            await player.queue.put(track)
            queue_size = player.queue.qsize()

            if player.current is not None:
                await interaction.edit_original_response(content=None, embed=_queued_embed(track, queue_size))
            else:
                await interaction.edit_original_response(content="▶️ Starting playback…")

    # ── /playnext ─────────────────────────────────────────────────────────────

    @app_commands.command(name="playnext", description="Insert a song or playlist to play after the current track.")
    @app_commands.describe(query="YouTube URL, playlist URL, or search terms")
    async def playnext(self, interaction: discord.Interaction, query: str) -> None:
        await interaction.response.defer()

        player = await self._ensure_player(interaction)
        if player is None:
            return

        cookiefile = get_guild_cookiefile(interaction.guild_id) if interaction.guild_id else None

        await interaction.followup.send(f"🔍 Loading `{query}`…")

        try:
            entries = await resolve_playlist(query, cookiefile=cookiefile)
        except YTDLError as exc:
            from notebane.metrics import record_ytdl_error
            record_ytdl_error()
            await interaction.edit_original_response(
                content=None,
                embed=err_embed(f"Could not load: `{query}`\n> {exc}", title="Not Found"),
            )
            return

        if len(entries) > 1:
            # Playlist — acknowledge immediately, resolve + insert in background
            playlist_title = entries[0].get("playlist_title") or entries[0].get("playlist") or query
            await interaction.edit_original_response(
                content=None,
                embed=_playlist_queued_embed(
                    playlist_title, len(entries), interaction.user.display_name, next_up=True
                ),
            )
            asyncio.get_event_loop().create_task(
                self._enqueue_playlist_bg(
                    interaction, player, entries, playlist_title,
                    requester=interaction.user.display_name,
                    insert_next=True,
                    cookiefile=cookiefile,
                )
            )
        else:
            # Single track
            entry = entries[0] if entries else None
            url = (entry or {}).get("webpage_url") or (entry or {}).get("url") or query
            try:
                track = await resolve(url, requester=interaction.user.display_name, cookiefile=cookiefile)
            except YTDLError as exc:
                from notebane.metrics import record_ytdl_error
                record_ytdl_error()
                await interaction.edit_original_response(
                    content=None,
                    embed=err_embed(f"Could not find: `{query}`\n> {exc}", title="Not Found"),
                )
                return
            except Exception as exc:
                log.exception("Unexpected resolve error for %r", query)
                await interaction.edit_original_response(
                    content=None,
                    embed=err_embed(str(exc), title="Unexpected Error"),
                )
                return

            player.insert_next([track])
            embed = discord.Embed(
                title="▶ Up Next",
                description=f"**[{track.title}]({track.webpage_url})**",
                colour=discord.Colour.blurple(),
            )
            embed.add_field(name="Duration", value=track.duration_fmt(), inline=True)
            embed.add_field(name="Requested by", value=track.requester, inline=True)
            embed.set_footer(text="Inserted after the current track")
            if track.thumbnail:
                embed.set_thumbnail(url=track.thumbnail)
            await interaction.edit_original_response(content=None, embed=embed)

    # ── /skip ─────────────────────────────────────────────────────────────────

    @app_commands.command(name="skip", description="Skip the current track.")
    async def skip(self, interaction: discord.Interaction) -> None:
        player = await _get_player(interaction, self.players, require_playing=True)
        if player is None:
            return
        title = player.current.title if player.current else "current track"
        await player.skip()
        await interaction.response.send_message(f"⏭ Skipped **{title}**.", ephemeral=True)

    # ── /stop ─────────────────────────────────────────────────────────────────

    @app_commands.command(name="stop", description="Stop playback and clear the queue.")
    async def stop(self, interaction: discord.Interaction) -> None:
        player = await _get_player(interaction, self.players)
        if player is None:
            return
        await player.stop()
        await interaction.response.send_message("⏹ Stopped and cleared the queue.", ephemeral=True)

    # ── /pause ────────────────────────────────────────────────────────────────

    @app_commands.command(name="pause", description="Pause playback.")
    async def pause(self, interaction: discord.Interaction) -> None:
        player = await _get_player(interaction, self.players, require_playing=True)
        if player is None:
            return
        if player.pause():
            await interaction.response.send_message("⏸ Paused.", ephemeral=True)
        else:
            await interaction.response.send_message("❌ Already paused.", ephemeral=True)

    # ── /resume ───────────────────────────────────────────────────────────────

    @app_commands.command(name="resume", description="Resume playback.")
    async def resume(self, interaction: discord.Interaction) -> None:
        player = await _get_player(interaction, self.players)
        if player is None:
            return
        if player.resume():
            await interaction.response.send_message("▶️ Resumed.", ephemeral=True)
        else:
            await interaction.response.send_message("❌ Not paused.", ephemeral=True)

    # ── /shuffle ──────────────────────────────────────────────────────────────

    @app_commands.command(name="shuffle", description="Shuffle the queue.")
    async def shuffle(self, interaction: discord.Interaction) -> None:
        player = await _get_player(interaction, self.players)
        if player is None:
            return
        tracks = player.queue_list()
        if len(tracks) < 2:
            await interaction.response.send_message("❌ Need at least 2 tracks in the queue to shuffle.", ephemeral=True)
            return
        random.shuffle(tracks)
        # Rebuild the queue with shuffled order
        while not player.queue.empty():
            try:
                player.queue.get_nowait()
            except asyncio.QueueEmpty:
                break
        for t in tracks:
            await player.queue.put(t)
        await interaction.response.send_message(f"🔀 Shuffled {len(tracks)} tracks.", ephemeral=True)

    # ── /loop ─────────────────────────────────────────────────────────────────

    @app_commands.command(name="loop", description="Toggle loop mode: track, queue, or off.")
    @app_commands.describe(mode="track = loop current song, queue = loop whole queue, off = disable")
    @app_commands.choices(mode=[
        app_commands.Choice(name="track", value="track"),
        app_commands.Choice(name="queue", value="queue"),
        app_commands.Choice(name="off", value="off"),
    ])
    async def loop(self, interaction: discord.Interaction, mode: str) -> None:
        player = await _get_player(interaction, self.players)
        if player is None:
            return
        if mode == "track":
            player.loop_track = True
            player.loop_queue = False
            await interaction.response.send_message("🔂 Looping current track.", ephemeral=True)
        elif mode == "queue":
            player.loop_queue = True
            player.loop_track = False
            await interaction.response.send_message("🔁 Looping queue.", ephemeral=True)
        else:
            player.loop_track = False
            player.loop_queue = False
            await interaction.response.send_message("➡️ Loop disabled.", ephemeral=True)

    # ── /nowplaying ───────────────────────────────────────────────────────────

    @app_commands.command(name="nowplaying", description="Show what's currently playing.")
    async def nowplaying(self, interaction: discord.Interaction) -> None:
        player = await _get_player(interaction, self.players, require_playing=True)
        if player is None:
            return
        if player.current is None:
            await interaction.response.send_message("❌ Nothing is playing right now.", ephemeral=True)
            return
        embed = _now_playing_embed(player.current, paused=player.is_paused)
        if player.loop_track:
            embed.set_footer(text="🔂 Track loop on")
        elif player.loop_queue:
            embed.set_footer(text="🔁 Queue loop on")
        await interaction.response.send_message(embed=embed)

    # ── /queue ────────────────────────────────────────────────────────────────

    @app_commands.command(name="queue", description="Show the track queue.")
    @app_commands.describe(page="Page number (default 1)")
    async def queue(self, interaction: discord.Interaction, page: int = 1) -> None:
        await interaction.response.defer()
        player = await _get_player(interaction, self.players, deferred=True)
        if player is None:
            return
        await interaction.followup.send(embed=_queue_embed(player, page))

    # ── /remove ───────────────────────────────────────────────────────────────

    @app_commands.command(name="remove", description="Remove a track from the queue by its position.")
    @app_commands.describe(position="Queue position number (see /queue)")
    async def remove(self, interaction: discord.Interaction, position: int) -> None:
        player = await _get_player(interaction, self.players)
        if player is None:
            return
        tracks = player.queue_list()
        if not tracks:
            await interaction.response.send_message("❌ The queue is empty.", ephemeral=True)
            return
        idx = position - 1
        if idx < 0 or idx >= len(tracks):
            await interaction.response.send_message(
                f"❌ Invalid position. Queue has {len(tracks)} track{'s' if len(tracks) != 1 else ''}.",
                ephemeral=True,
            )
            return
        removed = tracks.pop(idx)
        # Rebuild queue
        while not player.queue.empty():
            try:
                player.queue.get_nowait()
            except asyncio.QueueEmpty:
                break
        for t in tracks:
            await player.queue.put(t)
        await interaction.response.send_message(
            f"🗑️ Removed **{removed.title}** from the queue.", ephemeral=True
        )


async def setup(bot: commands.AutoShardedBot) -> None:
    if not hasattr(bot, "players"):
        from notebane.player import GuildPlayerManager
        bot.players = GuildPlayerManager()  # type: ignore[attr-defined]
    await bot.add_cog(MusicCog(bot, bot.players))  # type: ignore[attr-defined]
