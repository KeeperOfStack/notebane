"""Music cog — /play and now-playing embeds."""

from __future__ import annotations

import asyncio
import logging

import discord
from discord import app_commands
from discord.ext import commands

from notebane.cogs.voice import assert_bot_perms, assert_user_in_voice
from notebane.player import GuildPlayer, GuildPlayerManager, Track
from notebane.ytdl import YTDLError, resolve

log = logging.getLogger("notebane.music")


def _now_playing_embed(track: Track) -> discord.Embed:
    """Build a 'now playing' embed for a track."""
    embed = discord.Embed(
        title="🎵 Now Playing",
        description=f"**[{track.title}]({track.webpage_url})**",
        colour=discord.Colour.green(),
    )
    embed.add_field(name="Duration", value=track.duration_fmt(), inline=True)
    embed.add_field(name="Requested by", value=track.requester, inline=True)
    if track.thumbnail:
        embed.set_thumbnail(url=track.thumbnail)
    return embed


def _queued_embed(track: Track, position: int) -> discord.Embed:
    """Build a 'added to queue' embed."""
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


class MusicCog(commands.Cog, name="Music"):
    """Audio playback commands."""

    def __init__(self, bot: commands.AutoShardedBot, players: GuildPlayerManager) -> None:
        self.bot = bot
        self.players = players
        # channel_id → discord.TextChannel for now-playing messages
        self._text_channels: dict[int, discord.TextChannel] = {}

    # ── Now-playing callback (called from play loop, non-async) ──────────────

    def _on_track_start(self, player: GuildPlayer, track: Track) -> None:
        """Schedule a now-playing embed to the originating text channel."""
        text_channel = self._text_channels.get(player.channel_id)
        if text_channel is None:
            return
        asyncio.get_event_loop().create_task(
            text_channel.send(embed=_now_playing_embed(track))
        )

    # ── /play ─────────────────────────────────────────────────────────────────

    @app_commands.command(name="play", description="Play a song or add it to the queue.")
    @app_commands.describe(query="YouTube URL, other URL, or search terms")
    async def play(self, interaction: discord.Interaction, query: str) -> None:
        await interaction.response.defer()

        if not interaction.guild or not interaction.guild_id:
            await interaction.followup.send("❌ This command only works in a server.")
            return

        # Ensure user is in a voice channel
        channel = await assert_user_in_voice(interaction)
        if channel is None:
            return

        # Auto-join if not already connected to this channel
        player = self.players.get(interaction.guild_id, channel.id)
        if player is None:
            # Check perms before joining
            if not await assert_bot_perms(interaction, channel):
                return
            try:
                vc = await channel.connect(timeout=10.0, reconnect=True)
            except discord.ClientException:
                await interaction.followup.send(
                    "❌ I'm already in another voice channel. Use `/leave` first."
                )
                return
            except TimeoutError:
                await interaction.followup.send("❌ Connection timed out. Try again.")
                return

            player = GuildPlayer(vc, on_track_start=self._on_track_start)
            self.players.set(player)
            await player.start()
            log.info("Auto-joined guild=%d channel=%s (%d)", interaction.guild_id, channel.name, channel.id)
        elif player._play_task is None or player._play_task.done():
            # Re-attach callback in case cog was reloaded
            player._on_track_start = self._on_track_start
            await player.start()

        # Remember this text channel for now-playing messages
        if isinstance(interaction.channel, discord.TextChannel):
            self._text_channels[channel.id] = interaction.channel

        # Resolve the track (runs yt-dlp in executor — non-blocking)
        await interaction.followup.send(f"🔍 Searching for `{query}`…")
        try:
            track = await resolve(
                query,
                requester=interaction.user.display_name,
            )
        except YTDLError as exc:
            await interaction.edit_original_response(content=f"❌ Could not find: `{query}`\n> {exc}")
            return
        except Exception as exc:
            log.exception("Unexpected resolve error for %r", query)
            await interaction.edit_original_response(content=f"❌ Unexpected error: {exc}")
            return

        # Enqueue
        await player.queue.put(track)
        queue_size = player.queue.qsize()

        if player.current is not None:
            # Something is already playing — show "queued" embed
            await interaction.edit_original_response(
                content=None,
                embed=_queued_embed(track, queue_size),
            )
        else:
            # Play loop will pick it up immediately and send now-playing via callback
            await interaction.edit_original_response(content="▶️ Starting playback…")


async def setup(bot: commands.AutoShardedBot) -> None:
    if not hasattr(bot, "players"):
        from notebane.player import GuildPlayerManager
        bot.players = GuildPlayerManager()  # type: ignore[attr-defined]
    await bot.add_cog(MusicCog(bot, bot.players))  # type: ignore[attr-defined]
