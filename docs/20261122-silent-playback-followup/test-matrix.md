# Silent playback follow-up — test matrix

| Layer | Evidence required | Result so far |
|---|---|---|
| Deployment identity | Running image reference + image ID/digest; UID and package/runtime versions | Remote tmux readback: `latest` and running container both revision `c8d0a81`; service-UID yt-dlp `2026.10.26`, EJS `0.8.0`, Deno `2.7.4`, FFmpeg `8.1.3`. |
| yt-dlp metadata | Same URL/options as app; safe extractor/client/format fields; no signed URL | Earlier source-only extraction succeeded on the public sample. In the user's later `/play`, FFmpeg's fast stream input returned HTTP 403; local fallback was attempted. No source packet metrics exist in deployed `c8d0a81`. |
| Full local preparation | Non-empty completed file; complete FFmpeg decode to EOF, exit 0 | Existing synthetic WAV fixture passed. No real user's YouTube download verified. |
| Fast HTTP stream | Fresh URL, extractor headers, safe bounded-range results; exact FFmpeg options | Earlier source-only probe succeeded on the same public page. During the user's `/play` at 08:59:32 UTC, the fast FFmpeg input returned HTTP 403 (exit 8); the player then attempted local fallback. Exact fallback output remains unmeasured. |
| FFmpeg source output | FFmpeg process started; codec/output packet evidence; clean exit or captured error | Separate source-only probe decoded 3 s of nonzero PCM (288,000 samples; peak 15,250; RMS 3,931.7) and emitted 50 Opus packets. In the user's `/play`, fast input failed with 403; whether the local fallback emitted packets remains unknown. |
| Discord voice | Connected to intended channel; actual audio frames/voice callback; user confirms audible output | User reports no audio despite visible voice activity and 200% individual volume. Server logs show the fast-stream 403 and fallback attempt. The new local observer is not yet deployed; no independent listener result. |
| Queue/recovery | Simulated or real stream error leads to valid fallback; next queued track plays | Mock and synthetic fallback tests pass; real Discord path remains unverified. |
| Regression | Focused failing test then passing, full suite and touched-file Ruff | Source metrics test and callback-thread test pass; callback-thread test failed before the fix as expected. Full suite: 93 passed. Ruff on changed Python files, compileall, and `git diff --check` passed. Existing pytest-asyncio deprecation warning remains; no follow-up image build/publish/deploy. |

## Safe log collection boundary
Request only lines around one test attempt. Before sharing, redact all cookies, tokens, authorization headers, full URLs/query strings, and private user identifiers. Do not provide environment dumps or cookie files.

## Required live checks after root cause is fixed
1. Single finite YouTube track: command result, source start, FFmpeg decode/output, audible Discord sound.
2. Long finite track: full completion or a real mid-stream failure followed by recovery; no silent skip.
3. Queue continuation: a second item starts and is audible after the first finishes or recovers.
4. Capture the exact deployed image identity and the image's yt-dlp, yt-dlp-ejs, Deno, and FFmpeg versions.
