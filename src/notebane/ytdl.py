"""yt-dlp async resolver — extracts audio stream info without blocking the event loop."""

from __future__ import annotations

import asyncio
import logging
import re
import shutil
import tempfile
import threading
import time
from collections.abc import Mapping
from dataclasses import dataclass
from functools import partial
from pathlib import Path
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


class _DownloadCancelled(Exception):
    """Internal signal used to stop an in-flight yt-dlp download."""


@dataclass
class PreparedMedia:
    """A downloaded track kept in a private temporary directory."""

    path: str
    directory: str
    audio_codec: str | None

    def cleanup(self) -> None:
        shutil.rmtree(self.directory, ignore_errors=True)


@dataclass
class PreparedTrack:
    """Resolved track metadata and optional fully-downloaded media."""

    track: Track
    media: PreparedMedia | None


@dataclass(frozen=True)
class FastStream:
    """Short-lived direct media URL used only for quick-start playback."""

    url: str
    http_headers: dict[str, str] | None
    duration: int | None
    is_live: bool
    audio_codec: str | None
    video_codec: str | None
    format_id: str | None


FAST_STREAM_URL_MAX_AGE = 60.0


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


# YouTube auto-mix / radio list prefixes that yt-dlp expands even when
# noplaylist=True is set. When a URL contains both v= (a specific video)
# and one of these list prefixes, the user almost certainly right-clicked
# a video inside a mix — strip the list context so only that video plays.
# Use /playytmix to intentionally load the full mix.
_MIX_LIST_PREFIXES = re.compile(
    r"[?&]list=(RD|RDMM|RDCLAK|RDAMVM)[A-Za-z0-9_-]*",
    re.IGNORECASE,
)
_VIDEO_ID_PARAM = re.compile(r"[?&]v=([A-Za-z0-9_-]+)")


def strip_mix_context(url: str) -> str:
    """Strip YouTube auto-mix list context from a single-video URL.

    If the URL contains both a video ID (v=...) and a radio/mix list
    prefix (list=RD*, RDMM*, RDCLAK*, RDAMVM*), return a clean
    watch?v=ID URL. All other URLs are returned unchanged.

    This preserves normal playlist behaviour (list=PL*, list=OLAK*) and
    leaves non-YouTube URLs, search terms, and pure playlist URLs alone.
    """
    if not _MIX_LIST_PREFIXES.search(url):
        return url  # not a mix URL — pass through unchanged

    m = _VIDEO_ID_PARAM.search(url)
    if not m:
        return url  # mix list but no v= — leave as-is (shouldn't happen in practice)

    video_id = m.group(1)
    return f"https://www.youtube.com/watch?v={video_id}"


def _extract_sync(
    query: str,
    cookiefile: str | None = None,
    *,
    fast_stream: bool = False,
) -> dict[str, Any]:
    """Run yt-dlp synchronously (called in a thread executor).

    Cookie strategy (single tracks):
      1. Always try without cookies first — looks like a normal browser.
      2. Only retry with cookies if the error is age-restriction related.
      Normal videos never touch the cookie file.
    """
    opts = dict(YTDL_OPTS)
    if fast_stream:
        # The Android client currently yields a fast-start MP4/AAC stream on
        # the affected host; the durable audio-only copy is downloaded with
        # the normal best-audio selector in parallel.
        opts["format"] = "bestaudio/best"
        opts["extractor_args"] = {"youtube": {"player_client": ["android"]}}

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
        http_headers=info.get("http_headers") or None,
    )
    # Runtime-only marker; deliberately excluded from Track serialization.
    track.__dict__["_resolved_monotonic"] = time.monotonic()
    log.debug("Resolved %r → %s (%.0fs)", query, track.title, duration or 0)
    return track


def _resolve_fast_stream_sync(query: str, cookiefile: str | None) -> FastStream:
    info = _extract_sync(query, cookiefile, fast_stream=True)
    url = info.get("url")
    if not url:
        raise YTDLError("yt-dlp returned no fast-start stream URL.")
    duration = info.get("duration")
    return FastStream(
        url=url,
        http_headers=info.get("http_headers") or None,
        duration=int(duration) if duration is not None else None,
        is_live=bool(info.get("is_live")),
        audio_codec=info.get("acodec"),
        video_codec=info.get("vcodec"),
        format_id=str(info["format_id"]) if info.get("format_id") is not None else None,
    )


async def resolve_fast_stream(
    track: Track,
    cookiefile: str | None = None,
    loop: asyncio.AbstractEventLoop | None = None,
) -> FastStream:
    """Resolve a just-in-time low-latency stream without persisting its URL."""
    query = track.webpage_url or track.url
    if not query:
        raise YTDLError("Track has no source URL.")

    resolved_at = getattr(track, "_resolved_monotonic", None)
    age = time.monotonic() - resolved_at if isinstance(resolved_at, (int, float)) else None
    if (
        track.resolved
        and track.url
        and track.url != query
        and age is not None
        and 0 <= age <= FAST_STREAM_URL_MAX_AGE
    ):
        return FastStream(
            url=track.url,
            http_headers=track.http_headers,
            duration=track.duration,
            is_live=track.duration is None,
            audio_codec=None,
            video_codec=None,
            format_id=None,
        )

    ev = loop or asyncio.get_running_loop()
    try:
        return await ev.run_in_executor(
            None, partial(_resolve_fast_stream_sync, query, cookiefile)
        )
    except YTDLError:
        raise
    except Exception as exc:
        raise YTDLError(_safe_error(exc)) from exc


def _safe_error(exc: Exception) -> str:
    """Avoid leaking expiring media URLs from downloader errors into logs/chat."""
    return re.sub(r"https?://\S+", "<URL redacted>", str(exc))


def _prepare_sync(
    query: str,
    requester: str,
    cookiefile: str | None,
    directory: str,
    cancelled: threading.Event,
) -> PreparedTrack:
    """Resolve and fully download a finite track in a worker thread."""
    root = Path(directory)

    def make_track(info: Mapping[str, Any], *, buffered: bool) -> Track:
        page_url = info.get("webpage_url") or info.get("original_url") or query
        duration = info.get("duration")
        return Track(
            title=info.get("title") or "Unknown title",
            # Never persist a signed CDN URL for buffered tracks. Restore will
            # resolve the stable page URL again when playback resumes.
            url=page_url if buffered else (info.get("url") or page_url),
            webpage_url=page_url,
            duration=int(duration) if duration is not None else None,
            thumbnail=info.get("thumbnail"),
            requester=requester,
            http_headers=None if buffered else (info.get("http_headers") or None),
            resolved=not buffered,
        )

    def progress_hook(_status: dict[str, Any]) -> None:
        if cancelled.is_set():
            raise _DownloadCancelled("track download cancelled")

    def attempt(auth_cookiefile: str | None) -> PreparedTrack:
        out_dir = root / ("authenticated" if auth_cookiefile else "public")
        out_dir.mkdir(parents=True, exist_ok=True)
        opts = dict(YTDL_OPTS)
        opts.update({
            "outtmpl": str(out_dir / "%(extractor)s-%(id)s.%(ext)s"),
            "cachedir": False,
            "noplaylist": True,
            "socket_timeout": 20,
            "retries": 5,
            "fragment_retries": 5,
            "progress_hooks": [progress_hook],
        })
        if auth_cookiefile:
            opts["cookiefile"] = auth_cookiefile

        with yt_dlp.YoutubeDL(opts) as ydl:  # type: ignore[arg-type]
            info = ydl.extract_info(query, download=False)
            if info is None:
                raise YTDLError("yt-dlp found no media for this source.")
            if info.get("_type") == "playlist":
                entries = iter(info.get("entries") or ())
                info = next(entries, None)
                if info is None:
                    raise YTDLError("Playlist had no entries.")

            if cancelled.is_set():
                raise _DownloadCancelled("track download cancelled")

            # Do not wait forever downloading a livestream. It remains on the
            # existing direct-stream path; finite tracks are buffered locally.
            if info.get("is_live") or info.get("duration") is None:
                return PreparedTrack(make_track(info, buffered=False), None)

            downloaded = ydl.process_ie_result(info, download=True)
            if cancelled.is_set():
                raise _DownloadCancelled("track download cancelled")
            info = downloaded or info

            requested = info.get("requested_downloads") or []
            candidates = [info.get("filepath"), info.get("_filename")]
            candidates.extend(item.get("filepath") for item in requested if item)
            try:
                candidates.append(ydl.prepare_filename(info))
            except Exception as exc:  # noqa: BLE001 - fall back to inspecting the isolated output directory
                log.debug("Could not infer yt-dlp output filename: %s", _safe_error(exc))
            path = next(
                (Path(candidate) for candidate in candidates
                 if candidate and Path(candidate).is_file()),
                None,
            )
            if path is None:
                completed = [
                    item for item in out_dir.rglob("*")
                    if item.is_file() and not item.name.endswith((".part", ".ytdl"))
                ]
                path = completed[0] if len(completed) == 1 else None
            if path is None or path.stat().st_size == 0:
                raise YTDLError("yt-dlp finished without a complete audio file.")

            audio_codec = next(
                (item.get("acodec") for item in requested if item and item.get("acodec")),
                info.get("acodec"),
            )
            track = make_track(info, buffered=True)
            return PreparedTrack(
                track,
                PreparedMedia(str(path), str(root), audio_codec),
            )

    try:
        try:
            result = attempt(None)
        except Exception as exc:
            if cancelled.is_set():
                raise _DownloadCancelled("track download cancelled") from exc
            if _is_age_restricted_error(exc):
                if not cookiefile:
                    raise YTDLError(
                        "Age-restricted content — upload cookies via `/ytlogin` to access this video."
                    ) from exc
                log.info("Age-restricted video — retrying buffered download with cookies")
                try:
                    result = attempt(cookiefile)
                except Exception as retry_exc:
                    if cancelled.is_set():
                        raise _DownloadCancelled("track download cancelled") from retry_exc
                    if _is_invalid_cookies_error(retry_exc):
                        raise YTDLError(
                            "Your YouTube cookies have been rotated and are no longer valid. "
                            "Re-export them and upload via `/ytlogin`."
                        ) from retry_exc
                    if _is_age_restricted_error(retry_exc):
                        raise YTDLError(
                            "Age-restricted content — your cookies may have expired or been rotated. "
                            "Upload fresh cookies with `/ytlogin`."
                        ) from retry_exc
                    raise YTDLError(_safe_error(retry_exc)) from retry_exc
            elif isinstance(exc, YTDLError):
                raise
            else:
                raise YTDLError(_safe_error(exc)) from exc

        if cancelled.is_set():
            if result.media:
                result.media.cleanup()
            raise _DownloadCancelled("track download cancelled")
        if result.media is None:
            shutil.rmtree(root, ignore_errors=True)
        return result
    except BaseException:
        shutil.rmtree(root, ignore_errors=True)
        raise


def _cleanup_abandoned_download(future: asyncio.Future[PreparedTrack]) -> None:
    """Release a finished download if its awaiting playback task was cancelled."""
    try:
        result = future.result()
    except (asyncio.CancelledError, _DownloadCancelled, YTDLError):
        return
    if result.media:
        result.media.cleanup()


async def prepare_track(
    track: Track,
    cookiefile: str | None = None,
    loop: asyncio.AbstractEventLoop | None = None,
) -> PreparedTrack:
    """Refresh a track just before use and buffer finite audio to local disk.

    Streams with unknown duration remain live; finite tracks are fully
    downloaded before FFmpeg starts, so playback no longer reads from a
    short-lived YouTube CDN URL mid-track.
    """
    query = track.webpage_url or track.url
    if not query:
        raise YTDLError("Track has no source URL.")
    ev = loop or asyncio.get_running_loop()
    directory = tempfile.mkdtemp(prefix="notebane-track-")
    cancelled = threading.Event()
    worker = ev.run_in_executor(
        None,
        partial(_prepare_sync, query, track.requester, cookiefile, directory, cancelled),
    )
    try:
        return await asyncio.shield(worker)
    except asyncio.CancelledError:
        cancelled.set()
        worker.add_done_callback(_cleanup_abandoned_download)
        raise
