# User Playlists — Design

**Brain:** `/media/chasm/projects/_cron/notebane/20260701-1048-user-playlists/manifest.md`
**Status:** Planning complete — awaiting sign-off.

---

## Commands

| Command | Description |
|---|---|
| `/createlist <name>` | Save current queue as a named playlist. Tied to your Discord user ID — works across all guilds on this bot. |
| `/listplaylist` | List your playlists. Click one to load it. |
| `/loadlist <name>` | Load a playlist into the queue (replaces current queue, undoable). Autocomplete on name. |
| `/removelist <name>` | Delete a playlist (with confirmation). Autocomplete on name. |
| `/editplaylist <name>` | Open a paginated editor to add, remove, or reorder tracks. |

---

## Cross-guild by design

Playlists are keyed by `user_id` (Discord snowflake), not `guild_id`. The same user can load their playlist in any guild where this bot is running.

---

## /editplaylist — the hard one

**Approach: paginated ephemeral embed + modal text inputs**

Discord limits: 25 items per Select, 25 components per message, 5 inputs per Modal.
A playlist can be 500+ tracks — no single Discord primitive handles this natively.

**Solution:**

`/editplaylist <name>` sends an **ephemeral** paginated embed, 25 tracks per page:

```
🎵 My Playlist — Page 1/4 · Tracks 1–25 of 88

1. Song Title (3:42)
2. Another Song (4:15)
...
25. Track Name (2:58)

[◀ Prev]  [Next ▶]  [➕ Add]  [🗑 Remove]  [↕ Move]
```

- **➕ Add** → Modal: "URL or search term" → resolved, appended to end
- **🗑 Remove** → Modal: "Track number to remove" → type any number 1–N, no page navigation needed
- **↕ Move** → Modal: two inputs — "From position" and "To position"
- Changes save to DB **immediately** on each action
- 60-second idle timeout — buttons disable, prompt to re-run command

---

## Database schema (additions to notebane.db)

```sql
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
```

`/loadlist` re-resolves from `webpage_url` at load time (stream URLs expire in ~6h). The stored `url` is for reference only.

---

## Limits

| Constraint | Value | Reason |
|---|---|---|
| Max playlists per user | 25 | Matches Discord Select menu — /listplaylist fits one screen |
| Max tracks per playlist | 500 | Caps DB rows; large playlists can use /ytlogin for full coverage |
| Playlist name length | 1–50 chars | Fits Discord embed field |
| Name chars allowed | A-Z, a-z, 0-9, space, `-`, `_` | Autocomplete friendly |

---

## Phases

| Phase | Title | Type |
|---|---|---|
| 1 | `playlist_db.py` — schema migration + all CRUD functions | persistence |
| 2 | `/createlist`, `/listplaylist`, `/loadlist`, `/removelist` | commands |
| 3 | `/editplaylist` — paginated editor, Add/Remove/Move modals | UI |
| 4 | Deploy + manual tests | validation |
