"""Core cog — /ping, /status, /help."""

from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands


class CoreCog(commands.Cog, name="Core"):
    """Basic bot commands."""

    def __init__(self, bot: commands.AutoShardedBot) -> None:
        self.bot = bot

    @app_commands.command(name="ping", description="Check bot latency.")
    async def ping(self, interaction: discord.Interaction) -> None:
        latency_ms = round(self.bot.latency * 1000)
        await interaction.response.send_message(
            f"🏓 Pong! Latency: **{latency_ms}ms**", ephemeral=True
        )

    @app_commands.command(name="status", description="Show bot shard and guild info.")
    async def status(self, interaction: discord.Interaction) -> None:
        embed = discord.Embed(title="🎵 Notebane Status", colour=discord.Colour.blurple())
        embed.add_field(name="Guilds", value=str(len(self.bot.guilds)), inline=True)
        embed.add_field(name="Shards", value=str(self.bot.shard_count or 1), inline=True)
        embed.add_field(name="Latency", value=f"{round(self.bot.latency * 1000)}ms", inline=True)
        players = getattr(self.bot, "players", None)
        if players is not None:
            embed.add_field(name="Active players", value=str(players.total), inline=True)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="help", description="Show all available commands.")
    async def help(self, interaction: discord.Interaction) -> None:
        embed = discord.Embed(
            title="🎵 Notebane — Command Reference",
            description="Crystal-clear music bot powered by yt-dlp. All commands are slash commands.",
            colour=discord.Colour.blurple(),
        )

        embed.add_field(
            name="🔊 Voice",
            value=(
                "`/join [channel]` — Join a voice channel (defaults to yours)\n"
                "`/leave [channel]` — Leave and clear that channel's queue\n"
                "`/players` — Show all active voice sessions in this server"
            ),
            inline=False,
        )

        embed.add_field(
            name="▶ Playback",
            value=(
                "`/play <query>` — Play a URL, playlist, or search YouTube; auto-joins your VC\n"
                "`/playnext <query>` — Insert a song or playlist after the current track\n"
                "`/search <query>` — Search and pick from top 5 results\n"
                "`/skip` — Skip the current track\n"
                "`/stop` — Stop playback and clear the queue\n"
                "`/pause` — Pause the current track\n"
                "`/resume` — Resume a paused track"
            ),
            inline=False,
        )

        embed.add_field(
            name="📋 Queue",
            value=(
                "`/queue [page]` — Show the track queue (10 per page)\n"
                "`/nowplaying` — Show what's currently playing\n"
                "`/shuffle` — Shuffle the queue\n"
                "`/loop track` — Loop the current track 🔂\n"
                "`/loop queue` — Loop the entire queue 🔁\n"
                "`/loop off` — Disable looping\n"
                "`/remove <position>` — Remove a track from the queue"
            ),
            inline=False,
        )

        embed.add_field(
            name="🤖 Bot",
            value=(
                "`/ping` — Check latency\n"
                "`/status` — Show shard, guild, and player counts\n"
                "`/help` — This message"
            ),
            inline=False,
        )

        embed.set_footer(text="Tip: /play accepts YouTube URLs, SoundCloud, Bandcamp, and plain search terms.")
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.AutoShardedBot) -> None:
    await bot.add_cog(CoreCog(bot))
