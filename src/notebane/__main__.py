"""Notebane entrypoint."""

import asyncio
import logging
import os
import sys

import discord
from discord.ext import commands


log = logging.getLogger("notebane")


def setup_logging() -> None:
    level = os.getenv("LOG_LEVEL", "INFO").upper()
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
        stream=sys.stdout,
    )


class Notebane(commands.AutoShardedBot):
    """Main bot class with AutoSharding for 100+ guild scale."""

    def __init__(self) -> None:
        intents = discord.Intents.default()
        intents.voice_states = True
        super().__init__(
            command_prefix=commands.when_mentioned,
            intents=intents,
            help_command=None,
        )

    async def setup_hook(self) -> None:
        # Shared player manager — stored on bot so all cogs can access it
        from notebane.player import GuildPlayerManager
        self.players: GuildPlayerManager = GuildPlayerManager()

        # Load cog extensions
        await self.load_extension("notebane.cogs.core")
        await self.load_extension("notebane.cogs.voice")
        await self.load_extension("notebane.cogs.music")
        # Sync slash commands globally
        synced = await self.tree.sync()
        log.info("Synced %d slash commands", len(synced))

    async def on_ready(self) -> None:
        log.info(
            "Notebane ready | user=%s | guilds=%d | shards=%d",
            self.user,
            len(self.guilds),
            self.shard_count or 1,
        )


async def main() -> None:
    setup_logging()

    token = os.getenv("DISCORD_TOKEN")
    if not token:
        log.error("DISCORD_TOKEN environment variable is not set")
        sys.exit(1)

    async with Notebane() as bot:
        await bot.start(token)


if __name__ == "__main__":
    asyncio.run(main())
