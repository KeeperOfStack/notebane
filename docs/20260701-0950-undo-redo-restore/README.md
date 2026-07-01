# /undo, /redo, /restore

**Status:** Planning complete — awaiting sign-off.

## What this adds

- **`/undo`** — revert the last queue change (10-deep, in-memory)
- **`/redo`** — re-apply the last undo (10-deep, in-memory)  
- **`/restore`** — recover your full queue after disconnect, bot restart, PC reboot, or next day (persistent SQLite, 7-day TTL, per voice channel)

## Files

| File | Purpose |
|---|---|
| `design.md` | Full architecture, schema, mutation table, phase plan |
