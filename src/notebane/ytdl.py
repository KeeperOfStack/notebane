"""yt-dlp async resolver — extracts audio stream info without blocking the event loop."""

from __future__ import annotations

import asyncio
import logging
import re
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


# Phrases in yt-dlp error messages that indicate age-restriction
_AGE_RESTRICTION_HINTS = (
    "sign in to confirm your age",
    "age-restricted",
    "age restricted",
    "inappropriate for some users",
)

# Phrases that indicate the cookies were invalidated by YouTube (rotated)
_INVALID_COOKIES_HINTS = (
    "cookies are no longer valid",
    "cookies have likely been rotated",
)


def _is_invalid_cookies_error(exc: Exception) -> bool:
    return any(hint in str(exc).lower() for hint in _INVALID_COOKIES_HINTS)


def _is_age_restricted_error(exc: Exception) -> bool:
    return any(hint in str(exc).lower() for hint in _AGE_RESTRICTION_HINTS)


# How many flat entries before we consider a playlist "large" and use cookies
LARGE_PLAYLIST_THRESHOLD = 200


# Playlist-URL detection — cheap, no network. Used by /play and /playnext
# to bypass the flat-extract step for single videos and bare search queries.
#
# Matches:
#   - Any URL with `list=` query param (regular playlists, radios, mixes)
#   - Any URL with `/playlist?` path (album/artist pages)
#   - `youtube.com/@handle/playlists`, `/user/.../playlists`
#
# Does NOT match:
#   - Single video URLs (youtu.be/*, watch?v=*)
#   - Bare search queries (no scheme)
#   - Music.youtube.com watch URLs without list=
_PLAYLIST_HINTS = re.compile(
    r"([?&]list=[A-Za-z0-9_-]+|/playlist\?|/playlists(?:/|$|\?))",
    re.IGNORECASE,
)


def looks_like_playlist(query: str) -> bool:
    """Return True if the query is clearly a playlist URL.

    Cheap, no network. Callers use this to skip the flat-extract step
    for single videos and search terms, cutting one yt-dlp call
    (~1–2s) off the `/play` critical path.

    Both regular playlists (`list=PL...`) and YouTube-Music album lists
    (`list=OLAK5uy_...`) route to the playlist path. Radio/Mix lists
    (`list=RD...`) also route through — technically single-video-seeded
    but yt-dlp will expand them and that's what the user asked for by
    pasting the URL.
    """
    return bool(_PLAYLIST_HINTS.search(query))


def _extract_sync(query: str, cookiefile: str | None = None) -> dict[str, Any]:
    """Run yt-dlp synchronously (called in a thread executor).

    Cookie strategy (single tracks):
      1. Always try without cookies first — looks like a normal browser.
      2. Only retry with cookies if the error is age-restriction related.
      Normal videos never touch the cookie file.
    """
    opts = dict(YTDL_OPTS)

    with yt_dlp.YoutubeDL(opts) as ydl:  # type: ignore[arg-type]
        try:
            info = ydl.extract_info(query, download=False)
        except Exception as exc:
            # Age-gated? Retry with cookies if available.
            if cookiefile and _is_age_restricted_error(exc):
                log.info("Age-restricted video — retrying with cookies")
                opts_auth = dict(opts)
                opts_auth["cookiefile"] = cookiefile
                with yt_dlp.YoutubeDL(opts_auth) as ydl_auth:  # type: ignore[arg-type]
                    try:
                        info = ydl_auth.extract_info(query, download=False)
                    except Exception as exc2:
                        if _is_invalid_cookies_error(exc2):
                            raise YTDLError(
                                "Your YouTube cookies have been **rotated by YouTube** and are no longer valid. "
                                "Re-export them using a **private/incognito window** and **close the window without logging out** — "
                                "then re-upload via `/ytlogin`. See the `/ytlogin` instructions for details."
                            ) from exc2
                        if _is_age_restricted_error(exc2):
                            raise YTDLError(
                                "Age-restricted content — your cookies may have expired or been rotated. "
                                "Re-export from a **private/incognito window** (without logging out afterward) and run `/ytlogin` again."
                            ) from exc2
                        raise YTDLError(str(exc2)) from exc2
            elif _is_age_restricted_error(exc):
                raise YTDLError(
                    "Age-restricted content — upload cookies via `/ytlogin` to access this video."
                ) from exc
            else:
                raise YTDLError(str(exc)) from exc

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

    Cookie strategy (playlists):
      1. Always fetch without cookies first.
      2. If entry count >= LARGE_PLAYLIST_THRESHOLD AND cookies are available,
         re-fetch with cookies to get the full authenticated list.
      Small/normal playlists never touch the cookie file.
    """
    def _fetch(extra_opts: dict[str, Any]) -> list[dict[str, Any]]:
        opts = dict(YTDL_OPTS)
        opts["noplaylist"] = False      # allow playlists
        opts["extract_flat"] = True     # don't resolve individual stream URLs
        opts["ignoreerrors"] = True     # skip unavailable entries rather than aborting
        # skip=webpage uses YouTube's internal API endpoint instead of HTML scraping,
        # which returns significantly more entries for large playlists without auth.
        opts["extractor_args"] = {"youtubetab": {"skip": ["webpage"]}}
        opts.update(extra_opts)

        with yt_dlp.YoutubeDL(opts) as ydl:  # type: ignore[arg-type]
            info = ydl.extract_info(url, download=False)

        if info is None:
            return []
        if info.get("_type") == "playlist":
            return [e for e in (info.get("entries") or []) if e]  # type: ignore[return-value]
        return [info]  # type: ignore[return-value]

    # Step 1 — unauthenticated fetch (always)
    entries = _fetch({})

    # Step 2 — if we hit the unauthenticated ceiling and have cookies, go again
    if cookiefile and len(entries) >= LARGE_PLAYLIST_THRESHOLD:
        log.info(
            "Playlist hit %d entries (≥%d threshold) — re-fetching with cookies",
            len(entries), LARGE_PLAYLIST_THRESHOLD,
        )
        auth_entries = _fetch({"cookiefile": cookiefile})
        if len(auth_entries) > len(entries):
            log.info("Authenticated fetch returned %d entries (was %d)", len(auth_entries), len(entries))
            return auth_entries

    return entries


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
