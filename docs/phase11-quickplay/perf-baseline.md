# Perf Baseline & Manual Test Procedure — Phase 16

**As of:** 2026-07-01, live image `ghcr.io/keeperofstack/notebane:latest` @ digest set by commit `bf47675`.
**Stack:** yt-dlp `2026.06.29.234344` + yt-dlp-ejs `0.8.0` + Deno JS runtime, `notebane-notebane-1` on Kratos.

This document is the ground truth for how `/play` and `/playnext` are supposed to perform, and the step-by-step procedure to verify they do.

---

## What we measure and why

Time from `interaction.response.defer()` at the top of `/play` (or `/playnext`) until the first `player.queue.put(track)` — i.e. **the moment audio can actually start playing.** This is what the user feels as "how long until my song starts."

Two emission surfaces:

1. **Structured log line** — `play_latency kind=<kind> ms=<int>` in the container's JSON stdout. Grep-friendly. Persistent as long as the docker log driver keeps history (`json-file`, 10MB × 5 files = ~50MB retention in compose config).
2. **Prometheus gauge** — `notebane_play_latency_seconds{kind="..."}`. Always holds the most recent observation per kind. Only exposed if `METRICS_PORT` is set in `.env` (currently unset in prod compose — see docker-compose.prod.yml).

### The three measured kinds

| kind | Trigger | Path |
|---|---|---|
| `single` | `/play <single-video URL>` or `/play <search terms>` | Phase 13 fast path — one yt-dlp `extract_info` call |
| `playnext_single` | `/playnext <single-video URL>` or `/playnext <search terms>` | Phase 13 fast path, `insert_next` variant |
| `playlist_first` | `/play <playlist URL>` — first entry landing on queue | Phase 14 play-first — measured from top-level `defer()` through background task via `t_bg_start` kwarg |

**Deliberately not measured:**
- `/playnext <playlist URL>` — goes through `insert_next` bulk mode; time-to-first-audio is not meaningful (nothing plays until current track ends).
- Full-playlist background completion time. Would need a separate `record_play_latency('playlist_full', ...)` at the end of `_enqueue_playlist_bg`; not instrumented yet. If you want it, ask and I'll add it as a Phase 17 follow-up.

---

## Performance targets

| kind | Target (median of 3) | Rationale |
|---|---|---|
| `single` (URL) | **< 1500ms** | One yt-dlp resolve is ~1-1.5s on Kratos's link; anything above suggests network or yt-dlp regression. Was ~3-5s pre-phase-13 because of the double `_extract_playlist_sync` → `_extract_sync` call chain. |
| `single` (search) | **< 2000ms** | `ytsearch:` adds one extra HTTP round-trip vs. a direct video URL; slightly higher target. |
| `playnext_single` | **< 1500ms** | Same code path as `single`, just uses `player.insert_next([track])` instead of `queue.put`. |
| `playlist_first` (any size) | **< 2500ms** | Phase 14 makes this equal to a single-track resolve PLUS the flat-extract cost (~0.5-1s on top). |
| Full 200-entry playlist background resolve | **< 8000ms wall** (not currently instrumented — eyeball from `✅ playlist_title — N track(s) loaded` completion message timestamp minus the initial `/play` timestamp) | With `Semaphore(4)` and ~1s per entry, worst case is `ceil(200/4) × 1s = 50s`; realistic is ~15-30s due to variance. Target 8s is aspirational and assumes YouTube stays cooperative. |

**Regression tolerance:** ±500ms is normal variance from YouTube's own response times and Kratos's network. Only flag a genuine regression when three consecutive medians exceed the target by more than 500ms.

---

## Full manual test procedure

Run these in Discord against a real voice channel. Bot must be in the same guild as you. Ensure you're in a voice channel BEFORE running `/play` — the bot joins on demand.

### Prerequisites checklist

Before starting the runs, verify these once:

```bash
# 1. Confirm the container is running the latest image
docker inspect notebane-notebane-1 --format '{{.Image}}'
# Should return the sha256 digest that matches ghcr.io/keeperofstack/notebane:latest

# 2. Confirm bot is healthy and connected
docker ps --filter name=notebane --format 'Status: {{.Status}}'
# Should show "Up N minutes (healthy)"

docker logs notebane-notebane-1 --tail 20 | grep -E 'ready|Guild-synced'
# Should show "Notebane ready" and "Guild-synced commands to <your test guild>"

# 3. Verify metric-emitting code is loaded (grep for the new symbol)
docker exec notebane-notebane-1 python -c "from notebane.metrics import record_play_latency; print('OK', record_play_latency)"
# Should print: OK <function record_play_latency at 0x...>

# 4. Confirm yt-dlp version matches expectations
docker exec notebane-notebane-1 yt-dlp --version
# Should print: 2026.06.29.234344 (or newer if auto-updater has run since deploy)
```

If any of the four checks above fail, STOP and investigate before running trials — a stale image or missing dependency will invalidate the measurements.

### Suggested test playlists

Pick one URL per row of the results table below. If any URL 404s at test time (playlists get deleted), substitute a similar-size public playlist and note the swap.

| Purpose | Suggested URL | Notes |
|---|---|---|
| Single video URL | `https://www.youtube.com/watch?v=dQw4w9WgXcQ` | Short, no age gate, safe default |
| Single video URL (age-gated, requires `/ytlogin`) | `https://www.youtube.com/watch?v=oCNTYi9fHuo` | The Cribs — verified working post-Phase 10; skip if no cookies uploaded |
| Search term | `never gonna give you up` | Bare terms trigger `ytsearch:` prefix |
| Small playlist (~20) | `https://www.youtube.com/playlist?list=PLbpi6ZahtOH6Blw3RGYpWkSByi_T7Rygb` | Same as Phase 12 probe |
| Medium playlist (~200) | `https://www.youtube.com/playlist?list=PLMC9KNkIncKtPzgY-5rmhvj7fax8fdxoj` | Same as Phase 12 probe |

Different videos each trial (append `&index=N` on playlist URLs, or pick a different search query) to avoid YouTube-side caching artifacts skewing later runs.

### Trial protocol

For each row of the results table:

1. **Note the wall-clock time** you send the slash command. (Optional but useful for correlating logs.)
2. **Run the slash command** in your test guild. Wait for either the "Starting playback…" message or the queued embed.
3. **Wait 5 seconds** between trials to let yt-dlp's connection pool cycle and to avoid rate-limit clustering.
4. **After 3 trials of the same kind**, jump to a terminal and dump the latencies:
   ```bash
   docker logs notebane-notebane-1 --since 5m 2>&1 | grep play_latency | tail -20
   ```
   You'll see lines like:
   ```
   {"ts": "2026-07-01T03:35:12", "level": "INFO", "logger": "notebane.metrics", "msg": "play_latency kind=single ms=1234"}
   {"ts": "2026-07-01T03:35:24", "level": "INFO", "logger": "notebane.metrics", "msg": "play_latency kind=single ms=1180"}
   {"ts": "2026-07-01T03:35:35", "level": "INFO", "logger": "notebane.metrics", "msg": "play_latency kind=single ms=1301"}
   ```
5. **Median** the three `ms` values (middle value when sorted; not the arithmetic mean — median is robust against a single unusually slow YouTube response).
6. **Paste the median** into the appropriate row of the "Measured (fill in after real-user trials)" table below, along with the yt-dlp version at test time.

### Debugging tips if numbers look wrong

**All trials show identical or near-identical millisecond values:**
Something's off — real network latency has jitter. Check:
- Are you actually running against the new image? `docker inspect notebane-notebane-1 --format '{{.Image}}'` should match the latest GHCR digest.
- Is yt-dlp returning cached data? Restart the container: `docker restart notebane-notebane-1`.

**`kind=single` shows above 2500ms consistently:**
- Check YouTube-side latency: `docker exec notebane-notebane-1 time curl -s -o /dev/null https://www.youtube.com`. If that itself takes >1s, the target is not achievable regardless of code.
- Check that Deno + yt-dlp-ejs are still installed (Phase 10 dependency): `docker exec notebane-notebane-1 sh -c 'which deno && pip show yt-dlp-ejs | head -3'`. Missing either one means yt-dlp is falling back to slow paths.

**`kind=playlist_first` shows above 5000ms:**
- The flat-extract call is slow. Try `docker exec notebane-notebane-1 python -c "from notebane.ytdl import _extract_playlist_sync; import time; t=time.perf_counter(); r=_extract_playlist_sync('<your URL>'); print(f'{time.perf_counter()-t:.2f}s, {len(r)} entries')"` in isolation. If the flat-extract alone is >3s, the ceiling is on YouTube's side.

**No `play_latency` lines appear in logs:**
- The `LOG_FORMAT: json` env in compose funnels stdout as structured JSON. Try `docker logs notebane-notebane-1 --tail 100 2>&1 | grep -i 'latency\|record'`.
- Confirm the code shipped: `docker exec notebane-notebane-1 grep -n record_play_latency /app/src/notebane/cogs/music.py`. Should return 3-4 lines.

---

## Measured (fill in after real-user trials)

Populate this table by running the trial protocol above. Include the trial's yt-dlp version from `docker exec notebane-notebane-1 yt-dlp --version`.

**Session date:** _(fill in)_
**yt-dlp version at test time:** _(fill in)_
**Test guild:** _(fill in: Dragonsburg or MusicTest)_
**Bot voice-channel state before first `/play`:** _(cold — bot not in VC / warm — bot already in VC)_

| Kind | Query used | Trial 1 (ms) | Trial 2 (ms) | Trial 3 (ms) | Median | Target | Meets? |
|---|---|---|---|---|---|---|---|
| `single` (URL) | | | | | | < 1500 | |
| `single` (search) | | | | | | < 2000 | |
| `playnext_single` | | | | | | < 1500 | |
| `playlist_first` (small ~20) | | | | | | < 2500 | |
| `playlist_first` (medium ~200) | | | | | | < 2500 | |

Also worth capturing informally (not table-tracked yet):

- **Full 200-entry background load wall time**: from the "🔍 Loading `<url>`…" message to the "✅ `<title>` — N track(s) loaded" completion message. Record here: _(fill in)_ seconds.
- **Any 429 / rate-limit warnings in logs during the 200-entry run?** `docker logs notebane-notebane-1 --since 5m | grep -iE '429|rate.limit'` → _(fill in)_

---

## Interpreting the results

### If all rows meet target

- Ship the table into this doc, commit as `docs(phase11): perf baseline measurements confirmed`, and Phase 11 is fully done.
- These numbers become the regression baseline: any future change that pushes a median more than +500ms over target needs justification in a follow-up commit or a doc note.

### If `single` misses target but `playlist_first` hits

- Something specific to the fast-path branch is slow — likely `_ensure_player` cold-start (fresh VC join adds 500-800ms). Phase 15 (VC pre-warm) becomes justified; unpause and implement.

### If `playlist_first` misses target but `single` hits

- The flat-extract call is dominating. Check whether the playlist URL used goes through `youtubetab:skip=webpage` correctly. If YouTube has changed the API and the fast path there is no longer fast, we may need a Phase 17 to precompute the first entry from a different signal (e.g. use the first entry's video ID directly from a URL parse instead of round-tripping through yt-dlp).

### If both miss target

- Most likely a shared dependency regressed. Check yt-dlp version — has it auto-updated to a version with slower resolution? Roll back with `docker exec notebane-notebane-1 pip install yt-dlp==2026.06.29.234344 --force-reinstall` and re-test.

---

## Regression policy

Any code change that lands on `main` after this baseline is set MUST NOT push any measured median more than +500ms over its target without explicit justification. The change owner is responsible for:

1. **Re-running the manual test procedure** on the new image before considering the change "done."
2. **Recording the new measurements** in a new date-stamped section below this one (do NOT overwrite the baseline — history matters).
3. If a regression is legitimate (upstream change we can't avoid), **updating the targets** and adding a comment naming the upstream cause.

---

## Cross-references

- `docs/phase11-quickplay/plan.md` — full phase-by-phase plan.
- `docs/phase11-quickplay/cookie-policy.md` — Phase 11 smart-cookie contract (informs which triggers cost cookies).
- `docs/phase11-quickplay/playlist-coverage-evidence.md` — Phase 12 anon-vs-auth entry-count measurements.
- `src/notebane/metrics.py` — `record_play_latency()` implementation.
- `src/notebane/cogs/music.py::play` — top-level `t_start = time.perf_counter()` and fast-path record call.
- `src/notebane/cogs/music.py::playnext` — same, `playnext_single` kind.
- `src/notebane/cogs/music.py::_enqueue_playlist_bg` — accepts `t_bg_start` kwarg; emits `playlist_first` when cursor advances past index 0 for the first time.

## What we deliberately did NOT do (Phase 15 deferred)

Pre-warming the VC join concurrently with yt-dlp resolve was scoped in the original plan but skipped. Reasoning:

- Fresh-VC join is ~500-800ms; already-in-VC case is ~0ms. Only a first-play-since-idle would benefit.
- The reordering touches interaction-response ordering, error paths, and `asyncio.gather` cancellation semantics — non-trivial for a marginal win once Phase 13 already eliminated the dominant 1-2s call from the critical path.
- Revisit if metrics show `single` regularly landing above 1.5s specifically because of the VC handshake. If the "cold VC + fresh yt-dlp" combo starts appearing in reports, unblock Phase 15.
