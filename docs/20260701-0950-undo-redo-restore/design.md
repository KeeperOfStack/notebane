# /undo, /redo, /restore — Design

**Brain:** `/media/chasm/projects/_cron/notebane/20260701-0950-undo-redo-restore/manifest.md`
**Status:** ✅ Complete — shipped `31d3dd0`, `8ec3cbc`. User tested.

---

## Commands

| Command | Behaviour |
|---|---|
| `/undo` | Reverts the last queue mutation. Cannot undo an undo — only `/redo` can. Depth: 10. |
| `/redo` | Re-applies the last undone action. Redo stack wiped on any new queue mutation. Depth: 10. |
| `/restore` | Restores the queue (+ current track at pos 0) from the last stop/disconnect snapshot. Persistent across bot restarts for 7 days. Scoped per voice channel. |

---

## Persistence design

**Undo/redo:** pure in-memory (`deque(maxlen=10)` on `GuildPlayer`). Session-scoped — intentionally lost on restart.

**Restore:** SQLite at `/data/notebane.db` (host: `./data/notebane.db`, bind-mounted). Uses Python stdlib `sqlite3` — no new packages, container stays Alpine-lightweight.

**Schema:**
```sql
CREATE TABLE IF NOT EXISTS restore_snapshots (
    guild_id    INTEGER NOT NULL,
    channel_id  INTEGER NOT NULL,
    saved_at    REAL NOT NULL,
    current_track TEXT,
    queue       TEXT NOT NULL,
    PRIMARY KEY (guild_id, channel_id)
);
```

**TTL:** 7 days. Purged on startup and hourly. Also cleared immediately when the user starts a new queue in that VC (first `/play` or `/playnext` after rejoining).

---

## What triggers a mutation snapshot (undo/redo)

| Operation | Snapshot? | Notes |
|---|---|---|
| `/play` single | ✅ | Before `queue.put` |
| `/play` playlist | ✅ | Before bg task starts |
| `/playnext` single | ✅ | Before `insert_next` |
| `/playnext` playlist | ✅ | Before bg task starts |
| `/remove` | ✅ | Before removal |
| `/shuffle` | ✅ | Before reorder |
| `/redo` | ✅ | Re-apply is itself undoable |
| `/skip` | ❌ | Advances play, no queue change |
| `/stop` | ❌ | Triggers restore snapshot instead |
| `/undo` | ❌ | Pushes to redo, not undo |

---

## Phases

| Phase | Title | Type |
|---|---|---|
| 1 | `restore_db.py` — SQLite schema, save/load/clear/purge, TTL startup hook | persistence |
| 2 | `player.py` — undo/redo stacks, `record_mutation()`, `_replace_queue()`, restore snapshot in `stop()`/`disconnect()` | core |
| 3 | `music.py` — hook `record_mutation()` into all mutating paths; clear restore on first new play | wiring |
| 4 | `/undo`, `/redo`, `/restore` slash commands + response embeds | commands |
| 5 | `docker-compose` volume mount for `/data` | infra |
| 6 | Deploy + manual tests | validation |
