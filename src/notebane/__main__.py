"""Notebane entrypoint."""

from __future__ import annotations

import asyncio
import json
import logging
import logging.handlers
import os
import sys
import time
from typing import TYPE_CHECKING

import discord
from discord.ext import commands

if TYPE_CHECKING:
    from notebane.bot_manager import BotManager

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
    """Main bot class with AutoSharding for 100+ guild scale.

    In single-bot deployments bot_number is always 1.
    In multi-bot pools each instance carries its own number for logging clarity.
    bot_manager is the shared BotManager pool; it is None only in legacy mode
    where BotManager could not be constructed (should not happen in practice).
    """

    def __init__(
        self,
        *,
        bot_number: int = 1,
        bot_manager: "BotManager | None" = None,
    ) -> None:
        intents = discord.Intents.default()
        intents.voice_states = True
        intents.message_content = True  # needed to read attachments in on_message

        shard_count: int | None = None
        sc_env = os.getenv("SHARD_COUNT", "").strip()
        if sc_env:
            try:
                shard_count = int(sc_env)
                log.info("Bot %d: using manual shard count: %d", bot_number, shard_count)
            except ValueError:
                log.warning(
                    "Bot %d: SHARD_COUNT=%r is not a valid integer — using auto",
                    bot_number, sc_env,
                )

        super().__init__(
            command_prefix=commands.when_mentioned,
            intents=intents,
            help_command=None,
            shard_count=shard_count,
        )

        self._bot_number = bot_number
        # Shared pool reference — used by Phase 3 routing in cogs.
        # All Notebane instances in a multi-bot deployment share the same
        # BotManager object so routing decisions are consistent across bots.
        self.bot_manager: BotManager | None = bot_manager

    async def setup_hook(self) -> None:
        from notebane.cookies import ensure_cookies_dir
        from notebane.metrics import start_metrics_server
        from notebane.player import GuildPlayerManager
        from notebane.ytdl_updater import start_ytdlp_updater
        from notebane.restore_db import init_db, purge_expired
        from notebane.playlist_db import init_playlist_tables

        self.players: GuildPlayerManager = GuildPlayerManager()

        ensure_cookies_dir()

        # Initialise the restore-snapshot DB and purge any expired rows on startup.
        init_db()
        purge_expired()
        init_playlist_tables()

        # Schedule hourly TTL purge
        async def _hourly_purge() -> None:
            while True:
                await asyncio.sleep(3600)
                try:
                    purge_expired()
                except Exception:
                    log.exception("Bot %d: restore_db hourly purge failed", self._bot_number)
        self._restore_purge_task = asyncio.create_task(_hourly_purge())

        await self.load_extension("notebane.cogs.core")
        await self.load_extension("notebane.cogs.voice")
        await self.load_extension("notebane.cogs.music")
        await self.load_extension("notebane.cogs.search")
        await self.load_extension("notebane.cogs.auth")
        await self.load_extension("notebane.cogs.playlists")

        # No global sync — we push commands guild-by-guild in on_ready and on_guild_join
        # so they appear instantly without the 1-hour global propagation delay.
        log.info("Bot %d: all cogs loaded", self._bot_number)

        # Metrics server: only Bot 1 runs it (it is the primary/favourite bot).
        # In multi-bot mode Bot 1 is always the first-assigned bot, so its
        # player count and guild stats reflect the most-active instance.
        if self._bot_number == 1:
            from notebane.metrics import start_metrics_server
            from notebane.ytdl_updater import start_ytdlp_updater
            self._metrics_task = await start_metrics_server(self, self.players)
            self._ytdlp_updater_task = await start_ytdlp_updater()
        else:
            self._metrics_task = None
            self._ytdlp_updater_task = None

    async def on_ready(self) -> None:
        # Only Bot 1 registers slash commands — pool bots (2-5) are invisible
        # audio workers. If all bots synced commands users would see duplicate
        # /play, /skip, etc. from every bot in the server member list.
        if self._bot_number == 1:
            for guild in self.guilds:
                try:
                    self.tree.copy_global_to(guild=guild)
                    await self.tree.sync(guild=guild)
                    log.info(
                        "Bot %d: guild-synced commands to %s (%d)",
                        self._bot_number, guild.name, guild.id,
                    )
                except Exception as exc:
                    log.warning(
                        "Bot %d: failed to guild-sync to %s (%d): %s",
                        self._bot_number, guild.name, guild.id, exc,
                    )
        else:
            # Pool bots: actively wipe any commands previously registered
            # (e.g. before this guard was added). Syncing an empty tree
            # removes all guild-scoped slash commands for this bot client.
            self.tree.clear_commands(guild=None)  # clear global tree
            for guild in self.guilds:
                try:
                    self.tree.clear_commands(guild=guild)
                    await self.tree.sync(guild=guild)
                    log.info(
                        "Bot %d: cleared commands from %s (%d)",
                        self._bot_number, guild.name, guild.id,
                    )
                except Exception as exc:
                    log.warning(
                        "Bot %d: failed to clear commands from %s (%d): %s",
                        self._bot_number, guild.name, guild.id, exc,
                    )

        log.info(
            "Bot %d ready | user=%s | guilds=%d | shards=%d",
            self._bot_number,
            self.user,
            len(self.guilds),
            self.shard_count or 1,
        )

    async def on_guild_join(self, guild: discord.Guild) -> None:
        """Push commands immediately when the bot is invited to a new server."""
        if self._bot_number != 1:
            # Pool bots don't register commands — Bot 1 owns the command tree.
            log.info("Bot %d: joined guild %s (%d) — skipping command sync (pool bot)", self._bot_number, guild.name, guild.id)
            return
        try:
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
            log.info(
                "Bot %d: guild-synced commands to new guild %s (%d)",
                self._bot_number, guild.name, guild.id,
            )
        except Exception as exc:
            log.warning(
                "Bot %d: failed to guild-sync on join to %s (%d): %s",
                self._bot_number, guild.name, guild.id, exc,
            )

    async def close(self) -> None:
        """Graceful shutdown — disconnect all voice clients before closing."""
        log.info(
            "Bot %d: shutdown initiated — disconnecting %d active player(s)…",
            self._bot_number, self.players.total,
        )
        players = list(self.players._players.values())
        if players:
            results = await asyncio.gather(
                *[p.disconnect() for p in players],
                return_exceptions=True,
            )
            for exc in results:
                if isinstance(exc, Exception):
                    log.warning(
                        "Bot %d: error disconnecting player during shutdown: %s",
                        self._bot_number, exc,
                    )
        log.info("Bot %d: all voice clients disconnected — closing gateway", self._bot_number)

        if task := getattr(self, "_ytdlp_updater_task", None):
            task.cancel()
        if task := getattr(self, "_restore_purge_task", None):
            task.cancel()
        if task := getattr(self, "_metrics_task", None):
            task.cancel()

        await super().close()


# ──────────────────────────────────────────────────────────────────────────────
# Per-bot runner (used by multi-bot gather)
# ──────────────────────────────────────────────────────────────────────────────

async def _run_bot(bot: Notebane, token: str) -> None:
    """Start one bot instance and keep it running until closed or cancelled.

    The ``async with bot`` pattern ensures ``bot.close()`` is called even if
    the task is cancelled (e.g. on SIGTERM), giving every bot a clean shutdown.
    """
    async with bot:
        await bot.start(token)


# ──────────────────────────────────────────────────────────────────────────────
# Entrypoint
# ──────────────────────────────────────────────────────────────────────────────

async def main() -> None:
    setup_logging()
    _apply_env_overrides()

    from notebane.bot_manager import BotManager

    try:
        pool = BotManager.from_env()
    except RuntimeError as exc:
        log.error("%s", exc)
        sys.exit(1)

    # Build one Notebane instance per pool entry and inject the client reference
    # back into the BotEntry so BotManager can route commands to it (Phase 3+).
    bots: list[Notebane] = []
    for entry in pool.bots:
        bot = Notebane(bot_number=entry.number, bot_manager=pool)
        entry.client = bot
        bots.append(bot)

    if pool.is_single_bot:
        log.info("Single-bot mode — starting Bot 1")
    else:
        log.info("Multi-bot mode — starting pool of %d bots", pool.count)

    # Start all bots concurrently.
    # return_exceptions=True keeps the gather alive if one bot exits with an
    # error — the others continue serving.  On SIGTERM the gather task itself
    # is cancelled, which propagates CancelledError to every child task and
    # triggers each bot's close() via the async-with context manager.
    results = await asyncio.gather(
        *[_run_bot(entry.client, entry.token) for entry in pool.bots],
        return_exceptions=True,
    )

    # Log any unexpected errors from individual bots so they're not silently swallowed.
    for entry, result in zip(pool.bots, results):
        if isinstance(result, Exception) and not isinstance(result, (KeyboardInterrupt, SystemExit)):
            log.error("Bot %d exited with error: %s", entry.number, result)


if __name__ == "__main__":
    asyncio.run(main())
