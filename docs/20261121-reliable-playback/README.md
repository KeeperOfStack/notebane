# Reliable playback — hybrid fast start and local recovery

This task addresses long-track truncation and queue resilience while keeping first-audio start independent of the full-track download.

## Paired working notes
- Brain/worklog: `/media/chasm/projects/_cron/notebane/20261121-reliable-playback/`
- Design and acceptance details: [`design.md`](design.md)
- Command-oriented regression matrix: [`test-matrix.md`](test-matrix.md)

## Baseline symptoms
The old player streamed from a short-lived direct URL. Logs showed HTTP 403/reset events; the playback callback then advanced the queue without resuming the failed track. Ordinary `/play` could also queue an expiring media URL. This differs from Discord DNS/reconnect errors, which are a separate network boundary.

## Implemented path
- Keep queued/current/saved track state on stable page URLs; do not persist expiring media URLs or temporary-file paths.
- Start a low-latency yt-dlp/FFmpeg stream and concurrently prepare a complete finite-track local copy.
- If the fast stream errors, resume the local file from the emitted Opus-packet media offset. Live/unknown-duration sources stay on direct streaming rather than waiting for EOF.
- Reuse a recently resolved direct URL for at most 60 seconds; stale/restored tracks are re-resolved from their stable page URL.
- Detect whether the installed FFmpeg exposes bounded HTTP request options before passing them. The host FFmpeg 8.0.1 lacked those flags; the built image's FFmpeg 8.1.3 exposes them and the bounded request path was exercised.

## Verification — 2026-11-22
- `pytest tests/ -q --tb=short` — **91 passed** in the scratch Python 3.14 environment.
- Targeted Ruff checks on changed modules/tests passed. Repository CI's `ruff check src/` still reports 54 diagnostics in other source files; those findings were not changed here.
- `python -m compileall -q src tests` and `git diff --check` — passed.
- `docker build --tag notebane:reliable-playback-test .` — succeeded. Built image includes yt-dlp 2026.10.26 and FFmpeg 8.1.3.
- Container-local synthetic HTTP/FFmpeg probe — passed with bounded ranges and supplied headers: streamed 250 Opus packets, handed off at 5.0 seconds, decoded 153 fallback packets to EOF, and full fixture decode exited 0. This is a synthetic-media transport/handoff test, not a yt-dlp or Discord voice test.
- Live YouTube yt-dlp probe — blocked by YouTube bot verification. This environment has no configured `YTDL_COOKIEFILE` and the previous live Notebane container is not present. No cookies or signed media URLs were inspected or recorded.
- Real Discord slash-command/voice playback and long-track YouTube EOF remain unverified; use the published image as a user-run test candidate, not production sign-off.

## Release boundary
The user authorized pushing this candidate to `main` and updating `ghcr.io/keeperofstack/notebane:latest` so they can pull and test. This does not authorize restarting or redeploying the live service; the user will do that. The GitHub publish workflow runs on `main` and enables `latest` on the default branch.
