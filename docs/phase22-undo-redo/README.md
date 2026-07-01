# Phase 22 — /undo, /redo, /restore

**Status:** Planning complete — implementation pending sign-off.

## Commands being added

- **`/undo`** — reverts the last queue mutation. Cannot undo an undo — only `/redo` can.
- **`/redo`** — re-applies the last undone action. Wiped on any new queue change.
- **`/restore`** — restores the queue from just before the bot stopped or left the VC. Per voice-channel.

## Files in this folder

| File | Purpose |
|---|---|
| `design.md` | Full architecture, data structures, mutation table, phase breakdown |
