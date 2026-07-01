#!/usr/bin/env python3
"""Phase 12 probe — measure playlist entry counts anon vs authenticated.

Run inside the live container so yt-dlp / yt-dlp-ejs / Deno versions match
production:

    docker exec notebane-notebane-1 python /app/scripts/probe_playlist_coverage.py

Prints a markdown table to stdout. One-off diagnostic; not shipped as a
runtime component.
"""
from __future__ import annotations

import os
import sys
import time
import shutil
import tempfile

# Ensure we can import the app's own ytdl module (installed as `notebane`).
sys.path.insert(0, "/app/src")

from notebane.ytdl import _extract_playlist_sync, LARGE_PLAYLIST_THRESHOLD  # noqa: E402
import yt_dlp  # noqa: E402


PLAYLISTS = [
    # (label, url, expected-size-bucket)
    ("small (<100)",  "https://www.youtube.com/playlist?list=PLbpi6ZahtOH6Blw3RGYpWkSByi_T7Rygb", "~25"),
    ("medium (~200)", "https://www.youtube.com/playlist?list=PLMC9KNkIncKtPzgY-5rmhvj7fax8fdxoj", "~200"),
    ("large (500+)",  "https://www.youtube.com/playlist?list=PLw-VjHDlEOgs658kAHR_LAaILBXb-s6Q5", "500+"),
    ("huge (1000+ radio)", "https://www.youtube.com/playlist?list=PLcirGkCPmbmFeQ1sm4wFciF03D_EroIfr", "1000+"),
    ("huge2 (megamix)", "https://www.youtube.com/playlist?list=PL9tY0BWXOZFvxjSDTe3XLGyeb8fu6QUII", "1000+"),
]


def find_any_cookiefile() -> str | None:
    """Copy the first available guild cookies file into a temp path so
    the probe doesn't stomp on the live one (yt-dlp overwrites)."""
    cookies_dir = "/cookies"
    if not os.path.isdir(cookies_dir):
        return None
    for name in sorted(os.listdir(cookies_dir)):
        if name.endswith(".orig.txt"):
            src = os.path.join(cookies_dir, name)
            tmp = tempfile.NamedTemporaryFile(prefix="probe_cookies_", suffix=".txt", delete=False)
            tmp.close()
            shutil.copy(src, tmp.name)
            return tmp.name
    return None


def probe(url: str, cookiefile: str | None) -> tuple[int, float]:
    t0 = time.perf_counter()
    entries = _extract_playlist_sync(url, cookiefile=cookiefile)
    dt = time.perf_counter() - t0
    return len(entries), dt


def main() -> int:
    cookiefile = find_any_cookiefile()
    print(f"yt-dlp version:      {getattr(yt_dlp, 'version', None) and yt_dlp.version.__version__ or 'unknown'}")
    print(f"cookiefile:          {'present (' + cookiefile + ')' if cookiefile else 'NONE — auth column will be skipped'}")
    print(f"LARGE threshold:     {LARGE_PLAYLIST_THRESHOLD}")
    print(f"timestamp (UTC):     {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}")
    print()
    print("| Bucket | Anon entries | Anon time | Auth entries | Auth time | Delta |")
    print("|---|---|---|---|---|---|")
    for label, url, _hint in PLAYLISTS:
        try:
            anon_n, anon_t = probe(url, cookiefile=None)
        except Exception as exc:
            print(f"| {label} | ERROR: {exc} | | | | |")
            continue
        auth_n: str | int = "—"
        auth_t: str = "—"
        delta: str | int = "—"
        if cookiefile:
            try:
                auth_n, auth_t_f = probe(url, cookiefile=cookiefile)
                auth_t = f"{auth_t_f:.1f}s"
                delta = auth_n - anon_n
            except Exception as exc:
                auth_n = f"ERR: {exc}"
        print(f"| {label} | {anon_n} | {anon_t:.1f}s | {auth_n} | {auth_t} | {delta} |")

    if cookiefile:
        try:
            os.unlink(cookiefile)
        except Exception:
            pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
