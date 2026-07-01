# Phase 22 — /undo, /redo, /restore

**Status:** Planning complete — implementation pending sign-off.
**Brain:** `/media/chasm/projects/_cron/notebane/phase22-undo-redo/manifest.md`

---

## What this adds

| Command | What it does |
|---|---|
| `/undo` | Reverts the last queue change (add song, add playlist, remove, shuffle, playnext). Cannot undo an undo — only `/redo` can reverse an undo. |
| `/redo` | Re-applies the last undone action. Redo stack is wiped the moment you make any new queue change. |
| `/restore` | Restores the queue to exactly what it was the moment the bot stopped or you left the VC. Per voice-channel — different VC = independent history. |

---

## Design decisions

### No database required
All state is in-memory on the `GuildPlayer` object. Queue history only matters during a session; nobody expects undo to survive a bot restart. Container stays Alpine-lightweight with zero new dependencies.

### Memory budget
- Undo/redo: 10 snapshots × up to 500 tracks × ~200 bytes/Track = ~1MB per active session at absolute max. Typical (20-track queue) is ~20KB.
- Restore: one snapshot per `(guild_id, channel_id)` pair = ~100KB typical.
- At 1,000 simultaneous sessions: ~1GB absolute ceiling, ~20MB typical.

### Undo depth
`UNDO_DEPTH = 10` — a `deque(maxlen=10)` automatically drops the oldest entry when full. Both undo and redo stacks share this depth limit.

---

## Data structures added to `GuildPlayer`

```python
from collections import deque

UNDO_DEPTH = 10

# In __init__:
self._undo_stack: deque[list[Track]] = deque(maxlen=UNDO_DEPTH)
self._redo_stack: deque[list[Track]] = deque(maxlen=UNDO_DEPTH)
self._restore_snapshot: list[Track] | None = None   # queue at stop/disconnect
self._restore_current: Track | None = None           # current track at stop/disconnect
```

---

## What triggers a mutation snapshot

`record_mutation()` is called BEFORE the queue changes, automatically clears the redo stack:

| Operation | Snapshot taken? |
|---|---|
| `/play` single track | ✅ |
| `/play` playlist (before bg task starts) | ✅ |
| `/playnext` single track | ✅ |
| `/playnext` playlist (before bg task starts) | ✅ |
| `/remove` | ✅ |
| `/shuffle` | ✅ |
| `/skip` | ❌ (not a queue mutation — advances play) |
| `/stop` | ❌ (triggers restore snapshot instead) |
| `/undo` itself | ❌ (pushes to redo, not undo) |
| `/redo` itself | ✅ (redo is re-applied via undo stack so it's undoable) |

---

## Phases

| Phase | Title | Type |
|---|---|---|
| 22 | Add data structures + `record_mutation()` + `_replace_queue()` + restore snapshot to `player.py` | core |
| 23 | Hook `record_mutation()` into all mutating paths in `music.py` | wiring |
| 24 | `/undo`, `/redo`, `/restore` slash commands + embeds | commands |
| 25 | Deploy + manual tests | validation |
