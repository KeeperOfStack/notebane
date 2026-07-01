"""User playlist persistence — stored in the same SQLite DB as restore snapshots.

Playlists are keyed by Discord user_id so they follow the user across all
guilds running this bot container.

Tables added to /data/notebane.db:
  user_playlists   — one row per named playlist per user
  playlist_tracks  — one row per track, ordered by position (1-indexed)
"""

from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import asdict
from typing import TYPE_CHECKING

from notebane.restore_db import _conn  # reuse the same DB connection helper

if TYPE_CHECKING:
    from notebane.player import Track

log = logging.getLogger("notebane.playlist_db")

# ── Constants ─────────────────────────────────────────────────────────────────

MAX_PLAYLISTS_PER_USER = 25
MAX_TRACKS_PER_PLAYLIST = 500
MAX_NAME_LENGTH = 50
_NAME_RE = re.compile(r"^[\w\s\-]{1,50}$")  # alphanum, space, hyphen, underscore

# ── Schema ────────────────────────────────────────────────────────────────────

_DDL = """
CREATE TABLE IF NOT EXISTS user_playlists (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL,
    name        TEXT    NOT NULL COLLATE NOCASE,
    created_at  REAL    NOT NULL,
    updated_at  REAL    NOT NULL,
    UNIQUE (user_id, name)
);

CREATE TABLE IF NOT EXISTS playlist_tracks (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    playlist_id INTEGER NOT NULL REFERENCES user_playlists(id) ON DELETE CASCADE,
    position    INTEGER NOT NULL,
    title       TEXT    NOT NULL,
    url         TEXT    NOT NULL,
    webpage_url TEXT    NOT NULL,
    duration    INTEGER,
    thumbnail   TEXT,
    requester   TEXT    NOT NULL DEFAULT 'unknown',
    http_headers TEXT,
    UNIQUE (playlist_id, position)
);

CREATE INDEX IF NOT EXISTS idx_playlist_tracks_order
    ON playlist_tracks(playlist_id, position);
"""


def init_playlist_tables() -> None:
    """Create playlist tables if they don't exist. Called once on startup."""
    with _conn() as con:
        con.executescript(_DDL)
    log.info("playlist_db tables ready")


# ── Validation ────────────────────────────────────────────────────────────────

class PlaylistError(Exception):
    """Raised for user-facing playlist operation errors."""


def validate_name(name: str) -> str:
    """Normalise and validate a playlist name. Returns stripped name or raises PlaylistError."""
    name = name.strip()
    if not name:
        raise PlaylistError("Playlist name cannot be empty.")
    if len(name) > MAX_NAME_LENGTH:
        raise PlaylistError(f"Playlist name must be {MAX_NAME_LENGTH} characters or fewer.")
    if not _NAME_RE.match(name):
        raise PlaylistError("Playlist name can only contain letters, numbers, spaces, hyphens, and underscores.")
    return name


# ── Track serialisation helpers ───────────────────────────────────────────────

def _track_to_row(track: "Track", playlist_id: int, position: int) -> tuple:
    headers_json = json.dumps(track.http_headers) if track.http_headers else None
    return (
        playlist_id,
        position,
        track.title,
        track.url,
        track.webpage_url,
        track.duration,
        track.thumbnail,
        track.requester,
        headers_json,
    )


def _row_to_track(row: tuple) -> "Track":
    from notebane.player import Track
    _, _, _, title, url, webpage_url, duration, thumbnail, requester, headers_json = row
    http_headers = json.loads(headers_json) if headers_json else None
    return Track(
        title=title,
        url=url,
        webpage_url=webpage_url,
        duration=duration,
        thumbnail=thumbnail,
        requester=requester,
        http_headers=http_headers,
    )


# ── Public API ────────────────────────────────────────────────────────────────

def playlist_exists(user_id: int, name: str) -> bool:
    with _conn() as con:
        row = con.execute(
            "SELECT 1 FROM user_playlists WHERE user_id = ? AND name = ? COLLATE NOCASE",
            (user_id, name),
        ).fetchone()
    return row is not None


def get_playlist_id(user_id: int, name: str) -> int | None:
    with _conn() as con:
        row = con.execute(
            "SELECT id FROM user_playlists WHERE user_id = ? AND name = ? COLLATE NOCASE",
            (user_id, name),
        ).fetchone()
    return row[0] if row else None


def list_playlists(user_id: int) -> list[dict]:
    """Return [{id, name, track_count, updated_at}] for all user's playlists."""
    with _conn() as con:
        rows = con.execute(
            """
            SELECT p.id, p.name, COUNT(t.id) as track_count, p.updated_at
            FROM user_playlists p
            LEFT JOIN playlist_tracks t ON t.playlist_id = p.id
            WHERE p.user_id = ?
            GROUP BY p.id
            ORDER BY p.updated_at DESC
            """,
            (user_id,),
        ).fetchall()
    return [{"id": r[0], "name": r[1], "track_count": r[2], "updated_at": r[3]} for r in rows]


def create_playlist(user_id: int, name: str, tracks: list["Track"]) -> int:
    """Create a new playlist. Raises PlaylistError if name taken or limits exceeded.
    Returns the new playlist_id.
    """
    name = validate_name(name)
    if playlist_exists(user_id, name):
        raise PlaylistError(f'A playlist named "{name}" already exists.')
    existing = list_playlists(user_id)
    if len(existing) >= MAX_PLAYLISTS_PER_USER:
        raise PlaylistError(
            f"You've reached the limit of {MAX_PLAYLISTS_PER_USER} playlists. "
            "Remove one before creating a new one."
        )
    if len(tracks) > MAX_TRACKS_PER_PLAYLIST:
        raise PlaylistError(
            f"Playlist too large — maximum {MAX_TRACKS_PER_PLAYLIST} tracks. "
            f"Your queue has {len(tracks)}."
        )
    now = time.time()
    with _conn() as con:
        cur = con.execute(
            "INSERT INTO user_playlists (user_id, name, created_at, updated_at) VALUES (?, ?, ?, ?)",
            (user_id, name, now, now),
        )
        playlist_id: int = cur.lastrowid  # type: ignore[assignment]
        con.executemany(
            "INSERT INTO playlist_tracks (playlist_id, position, title, url, webpage_url, duration, thumbnail, requester, http_headers) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [_track_to_row(t, playlist_id, i + 1) for i, t in enumerate(tracks)],
        )
    log.info("playlist_db: created playlist %r (id=%d) for user=%d tracks=%d", name, playlist_id, user_id, len(tracks))
    return playlist_id


def overwrite_playlist(user_id: int, name: str, tracks: list["Track"]) -> int:
    """Overwrite an existing playlist's tracks. Creates it if it doesn't exist.
    Returns the playlist_id.
    """
    name = validate_name(name)
    if len(tracks) > MAX_TRACKS_PER_PLAYLIST:
        raise PlaylistError(f"Playlist too large — maximum {MAX_TRACKS_PER_PLAYLIST} tracks.")
    now = time.time()
    with _conn() as con:
        # Upsert the playlist row
        con.execute(
            """
            INSERT INTO user_playlists (user_id, name, created_at, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(user_id, name) DO UPDATE SET updated_at = excluded.updated_at
            """,
            (user_id, name, now, now),
        )
        row = con.execute(
            "SELECT id FROM user_playlists WHERE user_id = ? AND name = ? COLLATE NOCASE",
            (user_id, name),
        ).fetchone()
        playlist_id = row[0]
        con.execute("DELETE FROM playlist_tracks WHERE playlist_id = ?", (playlist_id,))
        con.executemany(
            "INSERT INTO playlist_tracks (playlist_id, position, title, url, webpage_url, duration, thumbnail, requester, http_headers) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [_track_to_row(t, playlist_id, i + 1) for i, t in enumerate(tracks)],
        )
    log.info("playlist_db: overwrote playlist %r (id=%d) for user=%d tracks=%d", name, playlist_id, user_id, len(tracks))
    return playlist_id


def get_playlist(user_id: int, name: str) -> list["Track"] | None:
    """Return the ordered track list for a playlist, or None if not found."""
    with _conn() as con:
        pid_row = con.execute(
            "SELECT id FROM user_playlists WHERE user_id = ? AND name = ? COLLATE NOCASE",
            (user_id, name),
        ).fetchone()
        if pid_row is None:
            return None
        rows = con.execute(
            "SELECT id, playlist_id, position, title, url, webpage_url, duration, thumbnail, requester, http_headers "
            "FROM playlist_tracks WHERE playlist_id = ? ORDER BY position",
            (pid_row[0],),
        ).fetchall()
    return [_row_to_track(r) for r in rows]


def delete_playlist(user_id: int, name: str) -> bool:
    """Delete a playlist by name. Returns True if deleted, False if not found."""
    with _conn() as con:
        cur = con.execute(
            "DELETE FROM user_playlists WHERE user_id = ? AND name = ? COLLATE NOCASE",
            (user_id, name),
        )
    return cur.rowcount > 0


def update_playlist_tracks(playlist_id: int, tracks: list["Track"]) -> None:
    """Full replace of all tracks in a playlist (used by editplaylist after mutations)."""
    if len(tracks) > MAX_TRACKS_PER_PLAYLIST:
        raise PlaylistError(f"Playlist too large — maximum {MAX_TRACKS_PER_PLAYLIST} tracks.")
    now = time.time()
    with _conn() as con:
        con.execute("DELETE FROM playlist_tracks WHERE playlist_id = ?", (playlist_id,))
        con.executemany(
            "INSERT INTO playlist_tracks (playlist_id, position, title, url, webpage_url, duration, thumbnail, requester, http_headers) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [_track_to_row(t, playlist_id, i + 1) for i, t in enumerate(tracks)],
        )
        con.execute("UPDATE user_playlists SET updated_at = ? WHERE id = ?", (now, playlist_id))


def get_playlist_tracks_by_id(playlist_id: int) -> list["Track"]:
    """Load tracks for a known playlist_id (used by editplaylist)."""
    with _conn() as con:
        rows = con.execute(
            "SELECT id, playlist_id, position, title, url, webpage_url, duration, thumbnail, requester, http_headers "
            "FROM playlist_tracks WHERE playlist_id = ? ORDER BY position",
            (playlist_id,),
        ).fetchall()
    return [_row_to_track(r) for r in rows]


def get_user_playlist_names(user_id: int) -> list[str]:
    """Return just the names of all playlists for autocomplete."""
    with _conn() as con:
        rows = con.execute(
            "SELECT name FROM user_playlists WHERE user_id = ? ORDER BY name COLLATE NOCASE",
            (user_id,),
        ).fetchall()
    return [r[0] for r in rows]
