# Silent playback follow-up

**Status:** A confirmed callback-thread-safety defect is fixed locally: the discord.py audio-thread completion callback is now marshalled to the asyncio event loop. Packet/callback diagnostics are also local. This is a verified player-lifecycle fix, but it is **not yet proven to be the cause of the silent playback**. No follow-up image has been built, published, or deployed; live audibility remains unverified.

**Current code:** running image is `c8d0a81` on `main`; candidate branch `fix/reliable-playback-20261121` contains callback-thread marshalling, source/callback counters, regression tests, and follow-up docs. No follow-up image build/publish/deployment has occurred.
**Operational notes:** private investigation notes are maintained outside this repository.
**Design and test plan:** [design.md](design.md), [test-matrix.md](test-matrix.md).
**Prior release record:** [20261121 reliable playback](../20261121-reliable-playback/README.md).

## Evidence so far
- The agent host has no local Notebane container. Read-only inspection of the authorized remote service confirmed that the running container and cached `ghcr.io/keeperofstack/notebane:latest` both match revision `c8d0a81ef5ea0e96c84102dd7bd18dd9a12f01bf`.
- As service UID/GID 1000, the imported yt-dlp is `2026.10.26` from `/usr/local/lib/python3.12/site-packages/yt_dlp/__init__.py`; yt-dlp-ejs is `0.8.0`, Deno `2.7.4`, FFmpeg `8.1.3`. No `FFMPEG_OPTIONS`, `FFMPEG_BEFORE_OPTIONS`, or global `YTDL_COOKIEFILE` override is set; no secret values were read.
- During the user's test of the same public sample at `2026-11-22 08:59:28 UTC`, Bot 1 joined voice; at `08:59:32`, FFmpeg's fast-stream input returned HTTP 403 (exit code 8, no stderr), and the player logged recovery to local audio. At `09:01:36`, the player stopped/disconnected. No local-fallback error appeared in the filtered logs, but the deployed image has no source packet counters, so fallback output remains unverified.
- The screenshot shows the user and Notebane in a voice channel with a green outline around the bot; the user reports no audible sound even at 200% individual volume. The indicator/connection does not prove audio was audible to the listener.
- The diagnostic source wrapper and after-callback log are now implemented locally; it records source read count, Opus packet count, bytes, Opus mode, callback error type, and voice-connected state without logging titles or media URLs. Focused tests pass; no follow-up image was built/published or deployed.
- The pinned discord.py 2.7.1 audio player invokes its completion callback on the audio worker thread. A regression test failed before the fix because `_after_play` ran on that worker thread; `_play_source` now uses `loop.call_soon_threadsafe` to run completion handling on the asyncio loop. The live log already showed the fallback warning was reached, so this defect is not yet proven to explain the user's silence.

## Plan
1. **Identify deployment and correlate attempt — Done with gaps.** The running `latest` image is `c8d0a81`. The user's 08:59 UTC test showed a fast-stream HTTP 403 followed by local fallback; the bot appeared active in voice but the user heard nothing. The fallback's source metrics are unavailable in the deployed image.
2. **Locate the failing boundary — In progress.** The user's same-sample `/play` hit a fast-stream HTTP 403 and switched to local-file recovery; the bot appeared active in voice but the listener heard nothing. The deployed image has no packet counters, so whether fallback frames were read/sent is unknown. Next discriminate client-output versus server fallback/delivery.
3. **Apply one evidence-backed fix — Partial.** Fixed the confirmed callback-thread-safety defect with a RED/GREEN test. It is not established as the root cause of the silent output; do not claim audio is fixed from unit tests.
4. **Verify and push source** — full tests/lint/compile/whitespace checks pass locally; push the source branch only. Do not publish a diagnostic image or update `latest` without separate approval and verification.
5. **Live acceptance** — user redeploys and confirms audible output on a long track and a subsequent queued track.

## Acceptance
- Failure layer is demonstrated by logs or a reproducible probe, not inferred from the silence report.
- Media decode/stream emits audio successfully, and actual Discord voice output is audible.
- A long-track/queue case completes or recovers, with errors visible rather than silently masked.
- Automated tests pass; any published candidate is read back and verified.

## Current limitation
The local callback fix and source/callback diagnostic code are not in the running image. The exact audio failure boundary remains open: fast stream returned 403 and fallback was attempted, but fallback packet counts and listener-side delivery are unknown. No new image has been built, published, or deployed.
