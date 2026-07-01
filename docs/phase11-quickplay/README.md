# Phase 11 Quick-Play — Complete Overview

**Status:** phases 11, 12, 13, 14, 16 shipped and deployed. Phase 15 deferred by design. Awaiting user validation of measurement table in `perf-baseline.md`.

**Live image:** `ghcr.io/keeperofstack/notebane:latest` (built from commit `bf47675`).
**Container:** `notebane-notebane-1` on Kratos, healthy.

## Reading this folder

| File | Purpose |
|---|---|
| `plan.md` | Original phase-by-phase plan written 2026-06-30. Kept as-is for historical reference. |
| `cookie-policy.md` | Phase 11 deliverable. Enforceable contract for when yt-dlp gets cookies attached; grep audit shows only 3 attachment sites in the whole tree. |
| `playlist-coverage-evidence.md` | Phase 12 deliverable. Live-container probe results — anon vs. authenticated entry counts across 4 public playlists. |
| `perf-baseline.md` | Phase 16 deliverable + manual test procedure. This is where you record measurements after running trials in Discord. |
| `README.md` | This file. Complete overview + operator's cheat sheet. |

## What changed for users of `/play` and `/playnext`

### Before this initiative

- `/play <single video URL>`: **~3-5 seconds** to first audio.
  - `resolve_playlist(query)` calls `_extract_playlist_sync()` — one yt-dlp call (~1.5s) → returns a 1-item list.
  - Then `resolve(entries[0].webpage_url)` calls `_extract_sync()` — another yt-dlp call (~1.5s).
  - Two calls where one would do.

- `/play <playlist URL>` (20 entries): **~20-40 seconds** for full queue.
  - `_enqueue_playlist_bg` looped sequentially: `for entry: await resolve(...)`.
  - First track played after ~1-2s (its own resolve) but the rest of the queue drip-fed at ~1-2s per entry.
  - A 200-entry playlist could take 3-6 minutes to fully load.

- Cookies attached to every request? **No** — this was already correct, just never written down. Phase 11 made it enforceable.

### After Phase 13 (fast path)

- `/play <single video URL>` or `/play <search terms>`: **~1-1.5 seconds** to first audio.
  - New `ytdl.looks_like_playlist(query)` regex classifier decides whether the query is a playlist URL. Cheap, no network.
  - Non-playlist queries skip `resolve_playlist()` entirely and go straight to `resolve()`. One yt-dlp call.
  - YouTube-Music album lists (`list=OLAK5uy_...`) and radio/mix lists (`list=RD...`) route to the playlist branch (correct — they expand into multiple entries).

### After Phase 14 (parallel resolve + play-first)

- `/play <playlist URL>` (20 entries): **~1-2 seconds** to first audio, **~5-10 seconds** for full queue.
  - `_enqueue_playlist_bg` now runs up to 4 concurrent yt-dlp resolves under `asyncio.Semaphore(4)`.
  - Results land in indexed slots (`list[Track | None]`); a cursor sweeps from index 0 and `queue.put`s the contiguous resolved prefix in original order.
  - Consequence: whichever entry finishes fastest doesn't jump the queue — order is preserved. But entry[0] triggers immediate playback the moment it lands, without waiting for other entries.

- `/play <playlist URL>` (200 entries): still **~1-2 seconds** to first audio; full queue in an estimated **~15-30 seconds** (measurement pending).

- `/playnext <playlist URL>`: unchanged semantically — still bulk-inserts in original order via `player.insert_next()`. But the underlying resolves now happen in parallel, so the completion summary arrives much sooner.

### After Phase 16 (measurement)

- Every `/play` and `/playnext` emits a structured log line: `play_latency kind=<X> ms=<N>`.
- Prometheus gauge `notebane_play_latency_seconds{kind}` holds the most recent observation per kind (only exposed if `METRICS_PORT` is set — currently unset in prod).
- `perf-baseline.md` documents targets, manual test procedure, regression policy.

## The two files that hold the critical behavior

### `src/notebane/ytdl.py`

- `looks_like_playlist(query)` — regex classifier. Any URL with `list=`, `/playlist?`, or `/playlists` path segment is a playlist; everything else is a single video or search term.
- `_extract_sync(query, cookiefile=None)` — resolves a single video. Cookies attached ONLY on age-gate error retry.
- `_extract_playlist_sync(url, cookiefile=None)` — flat-extract for playlists. Cookies attached ONLY when unauthenticated result has ≥ 200 entries AND authenticated result has strictly more.
- `LARGE_PLAYLIST_THRESHOLD = 200` — the "large" playlist cutoff.

### `src/notebane/cogs/music.py`

- `play()` — top-level `t_start = time.perf_counter()` bookend. Fast path branches on `looks_like_playlist(query)` before touching `resolve_playlist()`.
- `playnext()` — same shape, uses `player.insert_next([track])` instead of `player.queue.put`.
- `_enqueue_playlist_bg(...)` — parallel resolve with cursor-flush. Accepts `t_bg_start` kwarg from callers so `playlist_first` latency measures the full `defer()` → first-audio wall.

## Operator's cheat sheet

### Verifying a fresh deploy shipped correctly

```bash
# Confirm the container is on the new image
docker inspect notebane-notebane-1 --format '{{.Image}}'

# Confirm the new symbols are loaded
docker exec notebane-notebane-1 python -c "from notebane.ytdl import looks_like_playlist; from notebane.metrics import record_play_latency; print('OK')"

# Confirm bot is ready
docker logs notebane-notebane-1 --tail 20 | grep -E 'ready|Guild-synced'
```

### Watching latency in real time

```bash
docker logs -f notebane-notebane-1 2>&1 | grep --line-buffered play_latency
```

### Getting a quick histogram of recent runs

```bash
docker logs notebane-notebane-1 --since 1h 2>&1 \
  | grep play_latency \
  | grep -oE 'kind=[a-z_]+ ms=[0-9]+' \
  | sort | uniq -c | sort -rn | head -20
```

### If a user reports "my song is slow"

1. Ask when they ran it. `docker logs notebane-notebane-1 --since <N>m | grep -B2 -A2 <their user ID>` to correlate.
2. Look for the `play_latency` line immediately after. Compare against targets in `perf-baseline.md`.
3. Look for warnings above it — cookies-rotated, age-gated, 429, etc.
4. If the latency is above target but no warnings, check yt-dlp version — auto-updater may have moved us to a slower nightly. Roll back if needed.

## What's next (post-Phase-11 initiative)

1. **User validates the measurement table** in `perf-baseline.md` by running the trial protocol in Discord. Numbers get pasted back to me → I commit them as `docs(phase11): perf baseline measurements confirmed`.
2. **Phase 15 remains deferred** unless the measurements show `single` regressing above target specifically because of cold-VC joins.
3. **Optional Phase 17 candidates** (not scheduled, listed for future planning):
   - Full-playlist background completion time instrumentation (currently only `playlist_first` is measured).
   - Spotify URL support.
   - Pre-fetching the next-track stream URL while current plays (marginal — only saves ~200ms during track transitions).
