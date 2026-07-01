# Phase 11 — Quick-Start Playback + Smart-Cookie Audit + Playlist Coverage Verify

> Mirror of `/media/chasm/projects/_cron/notebane/phase11-quickplay/plan.md` — keep in sync per project convention.

**Date:** 2026-06-30
**Goal:** Cut time-to-first-song from ~5s → <1.5s when nothing is playing, document confirmed smart-cookie behavior, and verify full-playlist coverage with hard evidence.

## TL;DR for reviewers

1. **Cookies are already smart** — bot tries unauthenticated first on every single track and every playlist; cookies only re-trigger on age-restriction error or playlist ≥200 entries. (`src/notebane/ytdl.py`, lines 77–180.) Phase 11 just writes this down as an enforceable contract.
2. **Full playlists are pulled** up to YouTube's unauthenticated ceiling (~222 via `youtubetab:skip=webpage`), then we re-fetch with cookies if available. Phase 12 produces evidence.
3. **Slow start is sequential resolve** — `_enqueue_playlist_bg` resolves entries one-at-a-time. Phase 13 + 11.4 fix it: fast path for single videos, play-first/resolve-rest for playlists with bounded concurrency.

## Phases

| # | Title | Type |
|---|---|---|
| 11 | Document smart-cookie policy | docs |
| 12 | Playlist coverage evidence | docs + one-off probe |
| 13 | Quick-play single-URL fast path | perf |
| 14 | Play-first + parallel resolve for playlists | perf |
| 15 | Pre-warm voice connection during resolve | perf |
| 16 | Measurement + sign-off | docs |

Full phase detail: see `plan.md` in the brain folder (path above) — identical content; this in-repo copy exists so contributors who don't have the Hermes brain still see the plan in `git`.
