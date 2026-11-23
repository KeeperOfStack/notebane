"""yt-dlp freshness watcher — runs every 12 hours inside the bot process.

How yt-dlp stays current:
  * entrypoint.sh runs ``pip install --pre -U "yt-dlp[default]"`` as root on
    every container start, so each (re)start loads the newest nightly.
    (The bot itself runs as an unprivileged user and cannot write to
    site-packages, and an already-imported yt_dlp can't be swapped in-process.)
  * This watcher checks PyPI every 12 h. When a newer yt-dlp is published and
    no bot is playing anywhere, it asks the bot to shut down cleanly so the
    Docker restart policy brings it back up on the new version.

Set YTDL_AUTO_UPDATE=0 to disable both the entrypoint update and this watcher.
Set YTDL_AUTO_RESTART=0 to keep the watcher logging-only (no restarts).
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import sys
from typing import Awaitable, Callable

import yt_dlp

log = logging.getLogger("notebane.updater")

UPDATE_INTERVAL = 12 * 60 * 60  # 12 hours in seconds
IDLE_POLL_INTERVAL = 5 * 60     # while an update is pending, re-check idleness every 5 min


def _enabled(name: str) -> bool:
    return os.getenv(name, "1").strip().lower() not in ("0", "false", "no", "off")


def _current_version() -> str:
    return yt_dlp.version.__version__  # type: ignore[attr-defined]


def _vtuple(version: str) -> tuple[int, ...]:
    """'2026.06.29.234344' and '2026.6.29.234344.dev0' → (2026, 6, 29, 234344)."""
    return tuple(int(x) for x in re.findall(r"\d+", version.split(".dev")[0]))


async def _latest_version() -> str | None:
    """Newest yt-dlp on PyPI, nightlies included (the image installs with --pre)."""
    proc = await asyncio.create_subprocess_exec(
        sys.executable, "-m", "pip", "index", "versions", "yt-dlp", "--pre",
        "--disable-pip-version-check",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    if proc.returncode != 0:
        log.warning("yt-dlp version check failed (exit %d): %s", proc.returncode, stderr.decode().strip())
        return None
    m = re.search(r"yt-dlp \(([^)]+)\)", stdout.decode())
    return m.group(1) if m else None


async def check_for_update() -> str | None:
    """Return the newer PyPI version if one exists, else None."""
    current = _current_version()
    latest = await _latest_version()
    if latest is None:
        return None
    if _vtuple(latest) > _vtuple(current):
        log.info("yt-dlp update available: %s → %s", current, latest)
        return latest
    log.info("yt-dlp is current (%s)", current)
    return None


async def start_ytdlp_updater(
    is_idle: Callable[[], bool] | None = None,
    request_restart: Callable[[], Awaitable[None]] | None = None,
) -> asyncio.Task | None:
    """Start the background watcher. Returns the Task so it can be cancelled on shutdown."""
    if not _enabled("YTDL_AUTO_UPDATE"):
        log.info("yt-dlp auto-update disabled (YTDL_AUTO_UPDATE=0) — running %s", _current_version())
        return None

    can_restart = _enabled("YTDL_AUTO_RESTART") and is_idle is not None and request_restart is not None

    async def _loop() -> None:
        log.info("yt-dlp loaded: %s", _current_version())
        while True:
            await asyncio.sleep(UPDATE_INTERVAL)
            try:
                newer = await check_for_update()
            except Exception:
                log.exception("yt-dlp update check crashed")
                continue
            if not newer:
                continue
            if not can_restart:
                log.warning("yt-dlp %s is available — restart the container to load it", newer)
                continue
            while not is_idle():  # type: ignore[misc]
                log.info("yt-dlp %s pending — waiting for all playback to stop before restarting", newer)
                await asyncio.sleep(IDLE_POLL_INTERVAL)
            log.warning("Restarting to load yt-dlp %s (container restart policy brings the bot back)", newer)
            from notebane import alerts
            await alerts.send(
                "ytdlp-restart",
                f"Restarting to load yt-dlp {newer}",
                f"Updating from `{_current_version()}`. The container restart policy brings the bot back "
                "in a few seconds; if it doesn't, check the restart policy (`unless-stopped`).",
                "info",
                force=True,
            )
            await request_restart()  # type: ignore[misc]
            return

    task = asyncio.get_event_loop().create_task(_loop(), name="ytdlp-updater")
    log.info("yt-dlp update watcher scheduled (every 12 h, auto-restart=%s)", can_restart)
    return task
