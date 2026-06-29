"""Automatic yt-dlp updater — runs every 12 hours inside the bot process.

No container restart or image rebuild required. Uses pip to upgrade yt-dlp
in-place so all subsequent YoutubeDL() calls pick up the new version
automatically (yt-dlp is imported fresh per call in ytdl.py).
"""

import asyncio
import logging
import sys

import yt_dlp

log = logging.getLogger("notebane.updater")

UPDATE_INTERVAL = 12 * 60 * 60  # 12 hours in seconds


def _current_version() -> str:
    return yt_dlp.version.__version__  # type: ignore[attr-defined]


async def _run_upgrade() -> None:
    """Run `pip install --upgrade yt-dlp` as a subprocess."""
    before = _current_version()
    log.info("yt-dlp auto-update starting (current: %s)", before)

    proc = await asyncio.create_subprocess_exec(
        sys.executable, "-m", "pip", "install", "--upgrade", "--quiet", "yt-dlp",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()

    if proc.returncode != 0:
        log.warning(
            "yt-dlp upgrade failed (exit %d): %s",
            proc.returncode,
            stderr.decode().strip(),
        )
        return

    # Reload the version attribute so the log reflects the new version
    import importlib
    import yt_dlp.version as _ver
    importlib.reload(_ver)
    after = _current_version()

    if after != before:
        log.info("yt-dlp updated %s → %s", before, after)
    else:
        log.info("yt-dlp already up to date (%s)", after)


async def start_ytdlp_updater() -> asyncio.Task:
    """Start the background update loop. Returns the Task so it can be cancelled on shutdown."""

    async def _loop() -> None:
        # Run once immediately at startup, then every 12 hours
        await _run_upgrade()
        while True:
            await asyncio.sleep(UPDATE_INTERVAL)
            await _run_upgrade()

    task = asyncio.get_event_loop().create_task(_loop(), name="ytdlp-updater")
    log.info("yt-dlp auto-updater scheduled (interval: every 12 h)")
    return task
