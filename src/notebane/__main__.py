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


def _apply_env_overrides() -> None:
    """Apply environment variable overrides to runtime constants."""
    import notebane.player as _player
    import notebane.ytdl as _ytdl

    # FFmpeg options overrides
    before = os.getenv("FFMPEG_BEFORE_OPTIONS", "").strip()
    if before:
        _player.FFMPEG_BEFORE_OPTIONS = before
        log.info("FFMPEG_BEFORE_OPTIONS overridden: %s", before)

    extra = os.getenv("FFMPEG_OPTIONS", "").strip()
    if extra:
        _player.FFMPEG_OPTIONS = extra
        log.info("FFMPEG_OPTIONS overridden: %s", extra)

    # yt-dlp cookie file
    cookiefile = os.getenv("YTDL_COOKIEFILE", "").strip()
    if cookiefile:
        if not os.path.isfile(cookiefile):
            log.warning("YTDL_COOKIEFILE=%r does not exist — cookies disabled", cookiefile)
        else:
            _ytdl.YTDL_OPTS["cookiefile"] = cookiefile
            log.info("yt-dlp cookiefile: %s", cookiefile)


class Notebane(commands.AutoShardedBot):
    """Main bot class with AutoSharding for 100+ guild scale."""

    def __init__(self) -> None:
        intents = discord.Intents.default()
        intents.voice_states = True

        # Optional manual shard count override
        shard_count: int | None = None
        sc_env = os.getenv("SHARD_COUNT", "").strip()
        if sc_env:
            try:
                shard_count = int(sc_env)
                log.info("Using manual shard count: %d", shard_count)
            except ValueError:
                log.warning("SHARD_COUNT=%r is not a valid integer — using auto", sc_env)

        super().__init__(
            command_prefix=commands.when_mentioned,
            intents=intents,
            help_command=None,
            shard_count=shard_count,
        )

    async def setup_hook(self) -> None:
        from notebane.player import GuildPlayerManager
        from notebane.metrics import start_metrics_server

        # Shared player manager
        self.players: GuildPlayerManager = GuildPlayerManager()

        # Load cog extensions
        await self.load_extension("notebane.cogs.core")
        await self.load_extension("notebane.cogs.voice")
        await self.load_extension("notebane.cogs.music")
        await self.load_extension("notebane.cogs.search")

        # Sync slash commands globally
        synced = await self.tree.sync()
        log.info("Synced %d slash commands", len(synced))

        # Start optional metrics server (no-op if METRICS_PORT not set)
        await start_metrics_server(self, self.players)

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

    _apply_env_overrides()

    async with Notebane() as bot:
        await bot.start(token)


if __name__ == "__main__":
    asyncio.run(main())
