# Playback regression matrix

Label evidence as **automated unit**, **mocked player/command interaction**, **local FFmpeg fixture**, **live yt-dlp/FFmpeg integration**, or **live Discord**. Do not present a mocked interaction as manual Discord testing.

## Current verification
- Full automated suite: **91 passed** (`pytest tests/ -q --tb=short`). Includes finite-track preparation/player lifecycle, simulated fast-stream error and local seek fallback, URL redaction, and routing return-contract assertions.
- Changed Python modules and tests pass targeted Ruff. Exact repository CI lint command `ruff check src/` reports 54 diagnostics outside the touched modules; it remains unresolved and should be distinguished from these targeted checks.
- Compile check and whitespace check pass.
- Local Docker image built with yt-dlp 2026.10.26 and FFmpeg 8.1.3.
- Container-local synthetic HTTP/WAV FFmpeg fixture: custom header forwarded; request ranges bounded to 1 MiB; 250 stream packets read; fallback starts at 5.0 seconds and produces 153 packets through EOF; complete fixture decode exits 0.
- Live YouTube probe is blocked by the unauthenticated bot-verification response. No cookies file was configured in the agent environment. No live full-track download/decode was established.

## Track routes and controls — still require live command sign-off
- `/play` single URL/search result; playlist queue; `/playnext`; `/playytmix`; `/playytmixnext`; search selection.
- Saved playlist load and `/restore` must re-resolve from stable page URLs; temp paths and signed media URLs must never enter persistence.
- `/pause` and `/resume`; `/skip`; `/previous` and restart; `/stop`/leave/disconnect; loop track/queue/off; shuffle/remove/undo/redo; queue, now-playing and buttons.
- Saved playlist create/list/load/remove/edit operations.
- Real slash-command interactions and Discord voice audio remain **not run** in this environment.

## Provider and failure verification — still open
- YouTube fresh extraction and full finite-track download with the user's configured cookies/runtime.
- Full-track FFmpeg decode to expected duration/EOF, format/codec/bitrate check, and long-track timing.
- Mid-stream YouTube reset/403 followed by a real voice callback handoff to the local file; verify no skip/truncation and subsequent queued tracks continue.
- Live/infinite media behavior against a real provider.
- Multiple successive real queue items and cleanup after stop/skip/cancel/disconnect.

## Release boundary
The user requested a `main` push and GHCR `latest` image specifically to test in their deployment. A successful build/publish does not close the live-provider or Discord acceptance items; it only supplies a test candidate. The user will pull/redeploy, and the agent must not claim the running service was updated.
