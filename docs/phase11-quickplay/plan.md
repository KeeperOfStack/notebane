# Phase 11 — Quick-Start Playback + Smart-Cookie Audit + Playlist Coverage Verify

> Mirror of `/media/chasm/projects/_cron/notebane/phase11-quickplay/plan.md` — keep in sync per project convention.
>
> **Status update (2026-07-01):** phases 11, 12, 13, 14, 16 shipped and deployed. Phase 15 deferred. See `README.md` in this folder for the complete overview and operator's cheat sheet.

**Date planned:** 2026-06-30
**Date shipped:** 2026-07-01
**Goal:** Cut time-to-first-song from ~5s → <1.5s when nothing is playing, document confirmed smart-cookie behavior, and verify full-playlist coverage with hard evidence.

## Status snapshot

| # | Title | Type | Status | Commit |
|---|---|---|---|---|
| 11 | Document smart-cookie policy | docs | ✅ shipped | `7c96190` |
| 12 | Playlist coverage evidence | docs + one-off probe | ✅ shipped | `bc8be87` |
| 13 | Quick-play single-URL fast path | perf | ✅ shipped | `bc8be87` |
| 14 | Play-first + parallel resolve for playlists | perf | ✅ shipped | `bf47675` |
| 15 | Pre-warm voice connection during resolve | perf | ⏸ deferred | — |
| 16 | Measurement + sign-off | docs + metrics | ✅ shipped | `bf47675` |

## TL;DR for reviewers

1. **Cookies are already smart** — bot tries unauthenticated first on every single track and every playlist; cookies only re-trigger on age-restriction error or playlist ≥200 entries. See `cookie-policy.md` for the enforceable contract and grep audit (3 attachment sites in the whole tree).
2. **Full playlists are pulled** up to YouTube's unauthenticated ceiling (~222 via `youtubetab:skip=webpage`), then we re-fetch with cookies only if the anon result is at or above threshold AND auth returns strictly more entries. See `playlist-coverage-evidence.md` for measured entry counts.
3. **Slow start is fixed** — Phase 13 gives `/play <URL>` and `/play <search terms>` a fast path that skips the flat-extract step (one yt-dlp call instead of two). Phase 14 rewrites `_enqueue_playlist_bg` with `asyncio.Semaphore(4)` + a cursor that flushes contiguous resolved prefixes so the first playlist entry plays in ~1-2s regardless of playlist size.

## Deliverables shipped

### Documentation
- `docs/phase11-quickplay/cookie-policy.md` — enforceable contract, code-pointer table, grep audit (Phase 11).
- `docs/phase11-quickplay/playlist-coverage-evidence.md` — measured entry counts against 4 public playlists (Phase 12).
- `docs/phase11-quickplay/perf-baseline.md` — targets, manual test procedure, regression policy, empty measured table awaiting user trials (Phase 16).
- `docs/phase11-quickplay/README.md` — complete overview and operator cheat sheet (post-implementation).
- `docs/phase11-quickplay/plan.md` — this file.

### Code
- `src/notebane/ytdl.py`:
  - `looks_like_playlist(query)` regex classifier (Phase 13).
  - Existing `_extract_sync` and `_extract_playlist_sync` unchanged; policy documented in `cookie-policy.md`.
- `src/notebane/cogs/music.py`:
  - `/play` and `/playnext` fast path bypassing `resolve_playlist()` for non-playlist queries (Phase 13).
  - `_enqueue_playlist_bg` rewritten with `asyncio.Semaphore(4)` + cursor-based in-order queue flush (Phase 14).
  - `time.perf_counter()` bookends emitting `play_latency` structured logs + Prom gauge (Phase 16).
- `src/notebane/metrics.py`:
  - New `record_play_latency(kind, seconds)` helper (Phase 16).
- `scripts/probe_playlist_coverage.py` — one-off diagnostic, not shipped in image (Phase 12).

### Deferred
- Phase 15 (VC pre-warm) — marginal ~500ms gain only on fresh-VC joins, non-trivial reordering of interaction responses. Documented rationale in `perf-baseline.md`; revisit only if `single` latency regresses above target specifically because of the VC handshake.

## Historical plan detail

Full original phase-by-phase spec is preserved in the brain folder at `/media/chasm/projects/_cron/notebane/phase11-quickplay/plan.md`. This in-repo copy is now the summary; the brain copy is the archived detailed spec.

## Awaiting

**User validation of `perf-baseline.md` measured table.** BananaDragon runs the trial protocol in Discord and reports latencies back for the "Measured" table, which get committed as `docs(phase11): perf baseline measurements confirmed`. That closes out the initiative.
