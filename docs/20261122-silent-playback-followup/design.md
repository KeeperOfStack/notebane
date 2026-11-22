# Silent Playback — Investigation and Implementation Plan

**Goal:** Identify and fix the cause of zero audible audio in the user's redeployed Notebane candidate without guessing or masking the real failure layer.

**Architecture:** Trace one failed `/play` across the same container/runtime: command metadata extraction → fast URL resolution and finite-track preparation → FFmpeg source/decoded Opus → Discord `VoiceClient` audio callback/connection. Use the first failing boundary to select one TDD change. Keep provider failures separate from voice transport and preserve the documented cookie policy.

**Tech stack:** Python 3.12, `discord.py[voice]` 2.7.1, yt-dlp 2026.10.26, yt-dlp-ejs 0.8.0, Deno 2.7.4, and FFmpeg 8.1.3 in the inspected running image; pytest/Ruff.

**Current repo state:** `c8d0a81ef5ea0e96c84102dd7bd18dd9a12f01bf` is the running release on `main`; candidate branch `fix/reliable-playback-20261121` contains callback-thread marshalling, packet/callback instrumentation, regression tests, and follow-up docs. No follow-up image has been built, published, or deployed.

## Evidence and unknowns

### Confirmed
- The user reports no sound after redeploying the published image.
- The remote container `notebane` and cached `ghcr.io/keeperofstack/notebane:latest` both match OCI revision `c8d0a81ef5ea0e96c84102dd7bd18dd9a12f01bf`.
- As UID/GID 1000, the app imports yt-dlp `2026.10.26` from `/usr/local/lib/python3.12/site-packages/yt_dlp/__init__.py`; yt-dlp-ejs is `0.8.0`, Deno `2.7.4`, FFmpeg `8.1.3`.
- No `FFMPEG_OPTIONS`, `FFMPEG_BEFORE_OPTIONS`, or global `YTDL_COOKIEFILE` environment override is configured.
- The user's same-sample `/play` attempt at `08:59:28 UTC` was assigned to voice; at `08:59:32`, the fast-stream FFmpeg request returned HTTP 403 (exit code 8, no stderr). The player logged that it was recovering from local audio. It stopped/disconnected at `09:01:36`; no matching local-fallback error was seen in the filtered window.
- The user reports no audio despite the bot's green voice indicator and 200% individual volume. This does not establish whether the fallback source emitted frames or whether the user's Discord output device suppressed audio.
- A source observer is now implemented locally and logs read/Opus/byte counts plus after-callback error type and voice connection state; it omits media URLs and track/requester text. Its existing focused test now passes; no diagnostic image is yet built, published, or deployed.
- The pinned discord.py 2.7.1 player runs its `after` callback on the audio worker thread. A new test failed because `_after_play` directly touched `asyncio.Event` from that thread; completion handling is now marshalled with `loop.call_soon_threadsafe`. The live test's recovery warning shows the fallback path was reached, so this defect is not proven to be the complete silence root cause.
- The full local test suite passes: 93 tests. Ruff on changed Python files, compileall, and `git diff --check` pass. Pytest emits an existing `pytest-asyncio` loop-scope deprecation warning.
- The supplied runbook's essential Deno/EJS pieces are already present. The project pins EJS explicitly rather than installing `[default]`; the effect of other optional extras remains untested.
- `docs/phase11-quickplay/cookie-policy.md` is an enforceable contract; user cookies are used only for age-restricted singles and large-playlist coverage.

### Unknown
- Whether the local fallback for the user's exact `/play` actually produced nonzero PCM/Opus after the fast stream's HTTP 403.
- Whether the `VoiceClient` consumed/sent fallback packets and whether any other listener/device hears them.
- Whether a listener-side Discord output device, OS mixer, mute/deafen, or channel-volume state is the remaining cause.
- Whether the remaining `[default]` optional dependencies matter to this specific source; untested.

## Ranked, falsifiable hypotheses

1. **The live fast-stream request failed with HTTP 403; local fallback output is unverified.** A separate source-only probe for the same public page earlier produced nonzero PCM/Opus. Prediction: the deployed source counters show whether the fallback yielded packets or a callback error.
2. **Listener-side output path suppresses otherwise valid Discord audio.** The user sees a green indicator but hears nothing at 200% per-user volume. Prediction: another listener/client hears the same playback, or Discord/OS output-device state differs.
3. **Voice-client sending/transport path is faulty despite successful source reads.** Prediction: source metrics show many Opus packets and a clean callback but no listener hears them; voice/transport-specific diagnostics then become necessary.
4. **Wrong/stale deployment/runtime.** Disproved for the inspected state: the remote container and cached `latest` both match revision `c8d0a81`; service UID dependencies match the release.

Do not choose among these from the symptom alone.

## Ordered tasks

### Task 1 — Correlate one live attempt (done with gaps)

Remote inspection established the running image/runtime and a successful 3-second source-only decode for the public sample. The user's same-sample Discord test at `08:59:28 UTC` showed the bot in voice with a green outline but no audible sound. Logs at `08:59:32` show the fast-stream FFmpeg input returned HTTP 403 (exit 8), followed by the player's local-audio fallback path; it stopped/disconnected at `09:01:36`.

### Task 2 — Measure the fallback and voice-client boundary (in progress)

The user's same-sample `/play` hit HTTP 403 on the fast stream and initiated local fallback; the user saw the bot in voice with a green outline but heard nothing. Local source/callback instrumentation passes tests but remains undeployed. A separate regression test verifies completion handling is marshalled from discord.py's audio thread to the event loop. First compare another listener/client on the current bot. If no one hears it, request explicit approval before publishing a separate diagnostic tag; collect source counters from a short play stopped after a few seconds.

### Task 3 — TDD fix or rollback (partial)

- Add a test that fails for the observed error boundary and passes only for the corrected behavior.
- Run the focused test and confirm the failure is the expected one before implementation.
- Make the minimal fix; do not bundle dependency upgrades or unrelated lint cleanup.
- Roll back `c8d0a81` only if a differential test or live trace proves the new code caused silence. Preserve data and use a revert commit rather than resetting published history.
- Confirmed and fixed the callback-thread-safety defect with a failing test first. This improves completion/fallback coordination but is not demonstrated to resolve audible silence.

### Task 4 — Verify and push source candidate; image release gated

Run at minimum:

```bash
PYTHONPATH=src python -m pytest tests/ -q --tb=short
ruff check <changed Python files>
python -m compileall -q src tests
git diff --check
docker build --tag notebane:silent-playback-fix .
```

Current local result: focused callback/metrics tests pass (2); full suite passes (93); Ruff, compileall, and `git diff --check` pass. Push the source branch only. The diagnostic image remains a separate approval gate; do not publish `latest` or deploy.

### Task 5 — Live acceptance

User redeploys; verify one normal finite track, one long track that exercises recovery, and a second queued track. Require actual audible Discord output and successful queue continuation. The agent does not restart or replace the user's service.

## Acceptance criteria

- Exact failure boundary established from the user's deployment, not inferred from local-host bot verification.
- A finite track has a complete valid local media file and FFmpeg reaches EOF with exit 0, or the direct source yields valid audio packets.
- Real Discord voice is audible; a Now Playing message or `VoiceClient.is_playing()` alone does not count.
- Long-track failure recovers or is surfaced clearly; a subsequent queued item plays.
- Automated tests pass; a published artifact is verified by digest.

## Rollback and release safety

- Previous stable anchor: `8d6e58fade4607c41144c2f38ce1fbab2eb6d368`.
- Current test release: `c8d0a81ef5ea0e96c84102dd7bd18dd9a12f01bf` (`main`, GHCR `latest`).
- No rollback is warranted from the current evidence alone. Do not force-push or reset a published branch.
- No production deployment is performed from this session.

## Documentation and test references

- Current cookie contract: `../phase11-quickplay/cookie-policy.md`.
- Prior playback design/test report: `../20261121-reliable-playback/`.
- Private paired operational notes are maintained outside this repository.
