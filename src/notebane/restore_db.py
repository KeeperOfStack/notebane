"""Persistent restore-snapshot store — SQLite backed.

One row per (guild_id, channel_id), always the most recent snapshot.
Survives bot restarts. TTL = 7 days.

DB location: /data/notebane.db inside the container.
The /data directory is bind-mounted from the host so data persists
across image rebuilds and force-recreates.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import time
from contextlib import contextmanager
from dataclasses import asdict
from typing import TYPE_CHECKING, Generator

if TYPE_CHECKING:
    from notebane.player import Track

log = logging.getLogger("notebane.restore_db")

# ── Configuration ─────────────────────────────────────────────────────────────

DB_PATH = os.environ.get("NOTEBANE_DB_PATH", "/data/notebane.db")
TTL_SECONDS = int(os.environ.get("NOTEBANE_RESTORE_TTL", str(7 * 24 * 3600)))  # 7 days

# ── Schema ────────────────────────────────────────────────────────────────────

_DDL = """
CREATE TABLE IF NOT EXISTS restore_snapshots (
    guild_id      INTEGER NOT NULL,
    channel_id    INTEGER NOT NULL,
    saved_at      REAL    NOT NULL,
    current_track TEXT,
    queue         TEXT    NOT NULL,
    PRIMARY KEY (guild_id, channel_id)
);
"""

# ── Connection helper ─────────────────────────────────────────────────────────

@contextmanager
def _conn() -> Generator[sqlite3.Connection, None, None]:
    """Open a short-lived connection to the DB, ensure WAL mode."""
    os.makedirs(os.path.dirname(DB_PATH) if os.path.dirname(DB_PATH) else ".", exist_ok=True)
    con = sqlite3.connect(DB_PATH, timeout=10)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA foreign_keys=ON")
    try:
        yield con
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


def init_db() -> None:
    """Create the schema if it doesn't exist. Call once on startup."""
    with _conn() as con:
        con.executescript(_DDL)
    log.info("restore_db initialised at %s", DB_PATH)


# ── Track serialisation ───────────────────────────────────────────────────────

def _track_to_json(track: "Track") -> str:
    return json.dumps(asdict(track))


def _track_from_json(s: str) -> "Track":
    from notebane.player import Track
    return Track(**json.loads(s))


def _queue_to_json(tracks: list["Track"]) -> str:
    return json.dumps([asdict(t) for t in tracks])


def _queue_from_json(s: str) -> list["Track"]:
    from notebane.player import Track
    return [Track(**d) for d in json.loads(s)]


# ── Public API ────────────────────────────────────────────────────────────────

def save_snapshot(
    guild_id: int,
    channel_id: int,
    current_track: "Track | None",
    queue: list["Track"],
) -> None:
    """Upsert a restore snapshot. Called from player.stop() / player.disconnect()."""
    current_json = _track_to_json(current_track) if current_track else None
    queue_json = _queue_to_json(queue)
    with _conn() as con:
        con.execute(
            """
            INSERT INTO restore_snapshots (guild_id, channel_id, saved_at, current_track, queue)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(guild_id, channel_id) DO UPDATE SET
                saved_at      = excluded.saved_at,
                current_track = excluded.current_track,
                queue         = excluded.queue
            """,
            (guild_id, channel_id, time.time(), current_json, queue_json),
        )
    log.info(
        "restore_db: saved snapshot guild=%d channel=%d tracks=%d",
        guild_id, channel_id, len(queue) + (1 if current_track else 0),
    )


def load_snapshot(
    guild_id: int,
    channel_id: int,
) -> tuple["Track | None", list["Track"]] | None:
    """Return (current_track, queue) or None if no valid snapshot exists."""
    with _conn() as con:
        row = con.execute(
            """
            SELECT current_track, queue, saved_at
            FROM restore_snapshots
            WHERE guild_id = ? AND channel_id = ?
            """,
            (guild_id, channel_id),
        ).fetchone()

    if row is None:
        return None

    current_json, queue_json, saved_at = row

    # Reject if expired
    if time.time() - saved_at > TTL_SECONDS:
        clear_snapshot(guild_id, channel_id)
        return None

    try:
        current = _track_from_json(current_json) if current_json else None
        queue = _queue_from_json(queue_json)
    except Exception:
        log.exception("restore_db: failed to deserialise snapshot guild=%d channel=%d", guild_id, channel_id)
        clear_snapshot(guild_id, channel_id)
        return None

    log.info(
        "restore_db: loaded snapshot guild=%d channel=%d tracks=%d saved_ago=%.0fs",
        guild_id, channel_id, len(queue) + (1 if current else 0), time.time() - saved_at,
    )
    return current, queue


def clear_snapshot(guild_id: int, channel_id: int) -> None:
    """Delete the snapshot for this VC. Called when user starts a new queue."""
    with _conn() as con:
        con.execute(
            "DELETE FROM restore_snapshots WHERE guild_id = ? AND channel_id = ?",
            (guild_id, channel_id),
        )
    log.debug("restore_db: cleared snapshot guild=%d channel=%d", guild_id, channel_id)


def purge_expired(max_age_seconds: int = TTL_SECONDS) -> int:
    """Delete all snapshots older than max_age_seconds. Returns count deleted."""
    cutoff = time.time() - max_age_seconds
    with _conn() as con:
        cur = con.execute(
            "DELETE FROM restore_snapshots WHERE saved_at < ?",
            (cutoff,),
        )
        deleted = cur.rowcount
    if deleted:
        log.info("restore_db: purged %d expired snapshot(s)", deleted)
    return deleted
