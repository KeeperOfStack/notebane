# Phase 17 — Playback Stability

**Status:** Planning complete. Implementation pending sign-off.

## What broke and why

Three bugs, all triggered together by `/playnext <large playlist>`:

1. **Choppy audio** — 4 simultaneous yt-dlp+deno background workers saturate CPU/network, starving the live audio stream.
2. **`/stop` doesn't leave VC** — `player.stop()` never calls `voice_client.disconnect()`.
3. **Zombie playlist songs after stop** — the background enqueue task is never cancelled; it keeps stuffing tracks into the queue even after stop runs.

## Files in this folder

| File | Purpose |
|---|---|
| `design.md` | Root-cause analysis, fix design, all code change locations |
| `manual-tests.md` | Operator test protocol — 6 tests, copy-paste steps, expected outcomes |
