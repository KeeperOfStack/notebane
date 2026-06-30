"""yt-dlp async resolver — extracts audio stream info without blocking the event loop."""

from __future__ import annotations

import asyncio
import logging
from functools import partial
from typing import Any

import yt_dlp

from notebane.player import Track

log = logging.getLogger("notebane.ytdl")

# ──────────────────────────────────────────────────────────────────────────────
# yt-dlp options
# Prefer native Opus in WebM — zero re-encode on Discord voice.
# Fall back to best available audio if Opus isn't offered.
# ──────────────────────────────────────────────────────────────────────────────
YTDL_OPTS: dict[str, Any] = {
    "format": "bestaudio[ext=webm]/bestaudio/best",
    "outtmpl": "%(extractor)s-%(id)s-%(title)s.%(ext)s",
    "restrictfilenames": True,
    "noplaylist": True,        # single video by default; /playlist command (future) opts in
    "nocheckcertificate": True,
    "ignoreerrors": False,
    "logtostderr": False,
    "quiet": True,
    "no_warnings": True,
    "default_search": "ytsearch",   # bare search terms → YouTube search
    "source_address": "0.0.0.0",    # bind to all interfaces (IPv4 preference)
    "extract_flat": False,
}

# FFmpeg input options — reconnect on stream drop
FFMPEG_BEFORE_OPTIONS = (
    "-reconnect 1 "
    "-reconnect_streamed 1 "
    "-reconnect_delay_max 5"
)
# Prefer Opus output; let FFmpeg copy when source is already Opus
FFMPEG_OPTIONS = "-vn"


class YTDLError(Exception):
    """Raised when yt-dlp fails to extract info."""


def _extract_sync(query: str, cookiefile: str | None = None) -> dict[str, Any]:
    """Run yt-dlp synchronously (called in a thread executor)."""
    opts = dict(YTDL_OPTS)
    if cookiefile:
        opts["cookiefile"] = cookiefile

    with yt_dlp.YoutubeDL(opts) as ydl:  # type: ignore[arg-type]
        info = ydl.extract_info(query, download=False)

    if info is None:
        raise YTDLError(f"No results for: {query!r}")

    # Playlist → pick first entry
    if info.get("_type") == "playlist":
        entries = info.get("entries") or []
        if not entries:
            raise YTDLError("Playlist had no entries.")
        info = entries[0]  # type: ignore[index]

    return info  # type: ignore[return-value]


def _extract_playlist_sync(url: str, cookiefile: str | None = None) -> list[dict[str, Any]]:
    """Flat-extract a playlist URL without resolving stream URLs (fast).

    Returns a list of entry dicts, each containing at minimum:
      - 'title': track title
      - 'url' or 'webpage_url': the video page URL (NOT a stream URL)

    For single videos, returns a one-item list.
    """
    opts = dict(YTDL_OPTS)
    opts["noplaylist"] = False      # allow playlists
    opts["extract_flat"] = True     # don't resolve individual stream URLs
    if cookiefile:
        opts["cookiefile"] = cookiefile

    with yt_dlp.YoutubeDL(opts) as ydl:  # type: ignore[arg-type]
        info = ydl.extract_info(url, download=False)

    if info is None:
        return []

    if info.get("_type") == "playlist":
        entries = info.get("entries") or []
        return [e for e in entries if e]  # type: ignore[return-value]

    # Single video
    return [info]  # type: ignore[return-value]


async def resolve_playlist(
    url: str,
    cookiefile: str | None = None,
    loop: asyncio.AbstractEventLoop | None = None,
) -> list[dict[str, Any]]:
    """Async wrapper around _extract_playlist_sync.

    Returns flat entry dicts — callers must call resolve() on each entry's
    webpage_url to get a fully resolved Track with a stream URL.
    """
    ev = loop or asyncio.get_event_loop()
    from functools import partial
    try:
        entries: list[dict[str, Any]] = await ev.run_in_executor(
            None, partial(_extract_playlist_sync, url, cookiefile)
        )
    except Exception as exc:
        raise YTDLError(f"yt-dlp playlist error: {exc}") from exc
    return entries


async def resolve(
    query: str,
    requester: str = "unknown",
    cookiefile: str | None = None,
    loop: asyncio.AbstractEventLoop | None = None,
) -> Track:
    """Resolve a URL or search query to a Track asynchronously.

    Runs yt-dlp in a thread executor so the event loop stays unblocked.
    """
    ev = loop or asyncio.get_event_loop()
    try:
        info: dict[str, Any] = await ev.run_in_executor(
            None, partial(_extract_sync, query, cookiefile)
        )
    except YTDLError:
        raise
    except Exception as exc:
        raise YTDLError(f"yt-dlp error: {exc}") from exc

    # Pick the direct stream URL
    url = info.get("url") or info.get("webpage_url")
    if not url:
        raise YTDLError("yt-dlp returned no stream URL.")

    # Duration in seconds (may be None for livestreams)
    duration: int | None = info.get("duration")

    track = Track(
        title=info.get("title") or "Unknown title",
        url=url,
        webpage_url=info.get("webpage_url") or query,
        duration=duration,
        thumbnail=info.get("thumbnail"),
        requester=requester,
    )
    log.debug("Resolved %r → %s (%.0fs)", query, track.title, duration or 0)
    return track
