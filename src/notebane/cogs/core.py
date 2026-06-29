"""Core cog — ping, status, invite scaffold."""

import discord
from discord import app_commands
from discord.ext import commands


class CoreCog(commands.Cog, name="Core"):
    """Basic bot commands (ping, status)."""

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
        # Show active player count if available
        players = getattr(self.bot, "players", None)
        if players is not None:
            embed.add_field(name="Active players", value=str(players.total), inline=True)
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.AutoShardedBot) -> None:
    await bot.add_cog(CoreCog(bot))
