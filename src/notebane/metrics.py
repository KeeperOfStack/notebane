"""Optional Prometheus /metrics HTTP endpoint.

Starts only when METRICS_PORT env var is set. The aiohttp server runs
in the same asyncio event loop as the bot — no extra threads needed.

Metrics exposed:
  notebane_guilds_total          Gauge   — number of guilds the bot is in
  notebane_shards_total          Gauge   — number of active shards
  notebane_active_players_total  Gauge   — voice channels currently playing
  notebane_tracks_played_total   Counter — cumulative tracks played since start
  notebane_latency_seconds       Gauge   — Discord websocket latency (seconds)
  notebane_ytdl_errors_total     Counter — cumulative yt-dlp resolution errors
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import TYPE_CHECKING

from prometheus_client import (  # type: ignore[import-untyped]
    CONTENT_TYPE_LATEST,
    Counter,
    Gauge,
    generate_latest,
)

if TYPE_CHECKING:
    from discord.ext.commands import AutoShardedBot
    from notebane.player import GuildPlayerManager

log = logging.getLogger("notebane.metrics")

# ──────────────────────────────────────────────────────────────────────────────
# Metric definitions (module-level singletons)
# ──────────────────────────────────────────────────────────────────────────────

GUILDS = Gauge("notebane_guilds_total", "Number of guilds the bot is in")
SHARDS = Gauge("notebane_shards_total", "Number of active shards")
ACTIVE_PLAYERS = Gauge("notebane_active_players_total", "Voice channels currently playing audio")
TRACKS_PLAYED = Counter("notebane_tracks_played_total", "Cumulative tracks played since start")
LATENCY = Gauge("notebane_latency_seconds", "Discord websocket latency in seconds")
YTDL_ERRORS = Counter("notebane_ytdl_errors_total", "Cumulative yt-dlp resolution errors")


def record_track_played() -> None:
    """Call this each time a track starts playing."""
    TRACKS_PLAYED.inc()


def record_ytdl_error() -> None:
    """Call this each time yt-dlp fails to resolve a query."""
    YTDL_ERRORS.inc()


async def start_metrics_server(
    bot: AutoShardedBot,
    players: GuildPlayerManager,
) -> asyncio.Task | None:
    """Start the aiohttp /metrics server if METRICS_PORT is configured.

    Returns the background asyncio Task, or None if metrics are disabled.
    Both /metrics (Prometheus scrape) and /health (liveness probe) are served.
    """
    port_str = os.getenv("METRICS_PORT", "").strip()
    if not port_str:
        log.debug("METRICS_PORT not set — metrics server disabled")
        return None

    try:
        port = int(port_str)
    except ValueError:
        log.warning("METRICS_PORT=%r is not a valid integer — metrics disabled", port_str)
        return None

    try:
        from aiohttp import web  # type: ignore[import-untyped]
    except ImportError:
        log.warning("aiohttp not installed — metrics server disabled")
        return None

    async def handle_metrics(request: web.Request) -> web.Response:
        # Refresh live gauges on every scrape
        GUILDS.set(len(bot.guilds))
        SHARDS.set(bot.shard_count or 1)
        ACTIVE_PLAYERS.set(players.total)
        LATENCY.set(bot.latency)
        data = generate_latest()
        return web.Response(body=data, content_type=CONTENT_TYPE_LATEST)

    async def handle_health(_request: web.Request) -> web.Response:
        return web.Response(text="ok")

    async def _serve() -> None:
        app = web.Application()
        app.router.add_get("/metrics", handle_metrics)
        app.router.add_get("/health", handle_health)

        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "0.0.0.0", port)
        await site.start()
        log.info("Metrics server listening on :%d  — /metrics  /health", port)

        try:
            await asyncio.Event().wait()  # run until cancelled
        finally:
            await runner.cleanup()

    task = asyncio.get_event_loop().create_task(_serve())
    return task
