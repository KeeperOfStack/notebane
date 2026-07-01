# User Playlists

**Status:** Planning complete — awaiting sign-off.

## Commands

- **`/createlist <name>`** — save current queue as your named playlist (cross-guild, tied to your user ID)
- **`/listplaylist`** — list your playlists; click one to load it
- **`/loadlist <name>`** — load a playlist into the queue (replaces queue, undoable)
- **`/removelist <name>`** — delete a playlist (with confirmation)
- **`/editplaylist <name>`** — paginated editor: add, remove, reorder tracks with modal inputs

## Files

| File | Purpose |
|---|---|
| `design.md` | Full architecture, DB schema, editplaylist design rationale, limits, phases |
