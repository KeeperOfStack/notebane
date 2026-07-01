# Perf Baseline — Phase 16

**As of:** 2026-07-01, after commits shipping phases 13 + 14 + measurement.
**Bot version:** post-`bc8be87` (fast path) + this phase's commit (parallel resolve + metrics).

## What we measure

Time from `interaction.response.defer()` at the top of `/play` (or `/playnext`) until the first `player.queue.put(track)` — i.e. the moment audio actually can start playing. Emitted two ways:

1. Structured log line: `play_latency kind=<kind> ms=<int>` (grep-friendly in the container's json logs).
2. Prometheus gauge `notebane_play_latency_seconds{kind="..."}` — always holds the most recent observation per kind. Scrape via the metrics port (unset by default).

### Kinds

| kind | Path |
|---|---|
| `single` | `/play <single-video URL or search term>` — fast path |
| `playnext_single` | `/playnext <single-video URL or search term>` — fast path |
| `playlist_first` | `/play <playlist URL>` — measured from `defer()` to first playlist entry landing on the queue (i.e. playback can start) |

`/playnext` with a playlist URL is NOT instrumented for `playlist_first` (it goes through `insert_next` bulk mode; time-to-first-audio isn't meaningful for that path).

## Design targets (from plan.md)

| Kind | Target | Notes |
|---|---|---|
| `single` (URL or search) | **< 1.5s** | Was ~3-5s pre-phase-13 because of the double yt-dlp call. |
| `playlist_first` (first track) | **< 2.5s** | Was blocked until sequential resolve reached entry[0]. Parallel resolve + cursor flush lands entry[0] as soon as it resolves. |
| Full 200-entry playlist background resolve | **< 8s** at Semaphore(4) | Sequential was ~200 × 1s = 200s. Parallel should be ~50s worst case; expected ~15-30s. |

## Reading the numbers

Live containers on Kratos log to stdout in JSON. To collect a batch:

```bash
docker logs notebane-notebane-1 --since 10m 2>&1 | grep play_latency
```

Median across 3 trials at each kind is the number worth quoting. Include the yt-dlp version (`docker exec notebane-notebane-1 yt-dlp --version`) alongside — perf can regress if yt-dlp adds latency for its own reasons and it's not our fault.

## Measured (fill in after real-user trials)

| Kind | Trial 1 | Trial 2 | Trial 3 | Median | Meets target? |
|---|---|---|---|---|---|
| single (URL) | — | — | — | — | — |
| single (search) | — | — | — | — | — |
| playnext_single | — | — | — | — | — |
| playlist_first (10 entries) | — | — | — | — | — |
| playlist_first (200 entries) | — | — | — | — | — |

Populate the table by running `/play` in Discord 3× per row (against different videos to avoid YouTube caching effects), then tailing `docker logs` for the `play_latency` lines.

## Regression policy

If any median in the table exceeds its target after a code change, the change owner is responsible for either:
- Restoring the target with a follow-up commit before merging further work, or
- Documenting the regression here with a justification (e.g. "YouTube added a new challenge in yt-dlp 2026.07.05 that adds 400ms to every resolve — acceptable, no bot-side fix available").

## What we deliberately did NOT do (Phase 15 deferred)

Pre-warming the VC join concurrently with yt-dlp resolve was scoped in the original plan but skipped. Reasoning:

- Fresh-VC join is ~500-800ms; already-in-VC case is ~0ms. Only a first-play-since-idle would benefit.
- The reordering touches interaction-response ordering, error paths, and `asyncio.gather` cancellation semantics — non-trivial for a marginal win once phase 13 already eliminated the dominant 1-2s call.
- Revisit if metrics show `single` regularly landing above 1.5s specifically because of the VC handshake.
