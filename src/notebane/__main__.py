"""Notebane entrypoint."""

import asyncio
import json
import logging
import logging.handlers
import os
import sys
import time

import discord
from discord.ext import commands


log = logging.getLogger("notebane")


# ──────────────────────────────────────────────────────────────────────────────
# Structured JSON formatter (production)
# ──────────────────────────────────────────────────────────────────────────────

class JsonFormatter(logging.Formatter):
    """Emit one JSON object per log line — friendly to log aggregators."""

    def format(self, record: logging.LogRecord) -> str:
        doc = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(record.created)),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        if record.exc_info:
            doc["exc"] = self.formatException(record.exc_info)
        return json.dumps(doc, ensure_ascii=False)


def setup_logging() -> None:
    level_name = os.getenv("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    fmt = os.getenv("LOG_FORMAT", "json").lower()  # "json" | "text"

    handler = logging.StreamHandler(sys.stdout)
    if fmt == "json":
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(
            logging.Formatter(
                "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
                datefmt="%Y-%m-%dT%H:%M:%S",
            )
        )

    root = logging.getLogger()
    root.setLevel(level)
    root.handlers.clear()
    root.addHandler(handler)

    # Quieten noisy discord.py internal loggers unless debug requested
    if level > logging.DEBUG:
        logging.getLogger("discord").setLevel(logging.WARNING)
        logging.getLogger("discord.http").setLevel(logging.WARNING)


# ──────────────────────────────────────────────────────────────────────────────
# Env overrides
# ──────────────────────────────────────────────────────────────────────────────

def _apply_env_overrides() -> None:
    import notebane.player as _player
    import notebane.ytdl as _ytdl

    before = os.getenv("FFMPEG_BEFORE_OPTIONS", "").strip()
    if before:
        _player.FFMPEG_BEFORE_OPTIONS = before
        log.info("FFMPEG_BEFORE_OPTIONS overridden")

    extra = os.getenv("FFMPEG_OPTIONS", "").strip()
    if extra:
        _player.FFMPEG_OPTIONS = extra
        log.info("FFMPEG_OPTIONS overridden")

    cookiefile = os.getenv("YTDL_COOKIEFILE", "").strip()
    if cookiefile:
        if not os.path.isfile(cookiefile):
            log.warning("YTDL_COOKIEFILE=%r does not exist — cookies disabled", cookiefile)
        else:
            _ytdl.YTDL_OPTS["cookiefile"] = cookiefile
            log.info("yt-dlp cookiefile configured")


# ──────────────────────────────────────────────────────────────────────────────
# Bot
# ──────────────────────────────────────────────────────────────────────────────

class Notebane(commands.AutoShardedBot):
    """Main bot class with AutoSharding for 100+ guild scale."""

    def __init__(self) -> None:
        intents = discord.Intents.default()
        intents.voice_states = True

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
        from notebane.metrics import start_metrics_server
        from notebane.player import GuildPlayerManager
        from notebane.ytdl_updater import start_ytdlp_updater

        self.players: GuildPlayerManager = GuildPlayerManager()

        await self.load_extension("notebane.cogs.core")
        await self.load_extension("notebane.cogs.voice")
        await self.load_extension("notebane.cogs.music")
        await self.load_extension("notebane.cogs.search")

        synced = await self.tree.sync()
        log.info("Synced %d slash commands", len(synced))

        await start_metrics_server(self, self.players)
        self._ytdlp_updater_task = await start_ytdlp_updater()

    async def on_ready(self) -> None:
        log.info(
            "Notebane ready | user=%s | guilds=%d | shards=%d",
            self.user,
            len(self.guilds),
            self.shard_count or 1,
        )

    async def close(self) -> None:
        """Graceful shutdown — disconnect all voice clients before closing."""
        log.info("Shutdown initiated — disconnecting %d active player(s)…", self.players.total)
        players = list(self.players._players.values())
        if players:
            results = await asyncio.gather(
                *[p.disconnect() for p in players],
                return_exceptions=True,
            )
            for exc in results:
                if isinstance(exc, Exception):
                    log.warning("Error disconnecting player during shutdown: %s", exc)
        log.info("All voice clients disconnected — closing gateway")

        if task := getattr(self, "_ytdlp_updater_task", None):
            task.cancel()

        await super().close()


# ──────────────────────────────────────────────────────────────────────────────
# Entrypoint
# ──────────────────────────────────────────────────────────────────────────────

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
