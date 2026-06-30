"""Per-guild YouTube cookie management.

Cookies are stored at {COOKIES_DIR}/{guild_id}.txt on disk.
The default cookies dir is /cookies inside the container, mounted as a host volume.
"""

from __future__ import annotations

import logging
import os

log = logging.getLogger("notebane.cookies")

# Configurable via env so tests / dev runs can override
COOKIES_DIR: str = os.getenv("YTDL_COOKIES_DIR", "/cookies")


def _guild_path(guild_id: int) -> str:
    return os.path.join(COOKIES_DIR, f"{guild_id}.txt")


def ensure_cookies_dir() -> None:
    """Create the cookies directory if it doesn't exist."""
    os.makedirs(COOKIES_DIR, exist_ok=True)


def get_guild_cookiefile(guild_id: int) -> str | None:
    """Return the path to the guild's cookie file, or None if not set."""
    path = _guild_path(guild_id)
    return path if os.path.isfile(path) else None


def save_guild_cookies(guild_id: int, content: str) -> None:
    """Write cookies.txt content to disk for a guild."""
    ensure_cookies_dir()
    path = _guild_path(guild_id)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    log.info("Saved cookies for guild %d → %s", guild_id, path)


def delete_guild_cookies(guild_id: int) -> bool:
    """Remove the cookie file for a guild. Returns True if a file was deleted."""
    path = _guild_path(guild_id)
    if os.path.isfile(path):
        os.remove(path)
        log.info("Deleted cookies for guild %d", guild_id)
        return True
    return False


# ─────────────────────────────────────────────────────────────────────────────
# Validation
# ─────────────────────────────────────────────────────────────────────────────

# These cookies confirm a signed-in YouTube session
_YT_AUTH_COOKIES = {
    "SAPISID",
    "__Secure-1PSID",
    "__Secure-3PSID",
    "SID",
    "LOGIN_INFO",
}

_YT_DOMAINS = {"youtube.com", "google.com", ".youtube.com", ".google.com"}


def validate_youtube_cookies(content: str) -> tuple[bool, str]:
    """Check that content is a valid Netscape cookies.txt with YouTube auth cookies.

    Returns:
        (True, "OK") on success.
        (False, reason) on failure.
    """
    lines = content.splitlines()

    # Must start with the Netscape cookie file header (or have it somewhere in first 5 lines)
    header_found = any(
        "Netscape HTTP Cookie File" in line or "HTTP Cookie File" in line
        for line in lines[:5]
    )
    if not header_found:
        return False, (
            "Not a valid Netscape cookies.txt file. "
            "Make sure you exported using the browser extension, not a random text file."
        )

    has_youtube = False
    has_auth = False

    for line in lines:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split("\t")
        if len(parts) < 7:
            continue
        domain = parts[0].lstrip(".")
        name = parts[5]
        if "youtube.com" in domain or "google.com" in domain:
            has_youtube = True
            if name in _YT_AUTH_COOKIES:
                has_auth = True

    if not has_youtube:
        return False, (
            "No YouTube cookies found in this file. "
            "Make sure you exported cookies from **youtube.com**, not another site."
        )
    if not has_auth:
        return False, (
            "YouTube cookies found but no auth cookies detected. "
            "Make sure you are **signed into YouTube** before exporting."
        )

    return True, "OK"
