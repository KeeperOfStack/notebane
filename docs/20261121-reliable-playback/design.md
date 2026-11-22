# Playback resilience design

## Root cause
The old playback path handed FFmpeg an expiring direct media URL and treated every audio-player completion callback—including HTTP 403/reset errors—as normal track completion. The queue advanced without refreshing the stable webpage URL or recovering the remaining audio. Single `/play` entries could wait in the queue with stale direct URLs. The Discord DNS/reconnect errors in earlier logs are separate from media HTTP failures.

## Chosen architecture

1. Store stable webpage URLs in queue/current/restore state; do not retain signed media URLs in persistent snapshots.
2. At track start, claim an in-flight preparation for the same queue item or start a background finite-track preparation. Resolve a fast stream from the queued track. A direct URL from ordinary `/play` is reused only while its runtime monotonic age is at most 60 seconds; otherwise resolve from the page URL.
3. Start FFmpeg fast-stream playback without waiting for the full spool. Prepare one local copy of the current finite track while it plays. Prefetch is bounded to one upcoming finite item; no whole-queue download.
4. If the fast source reports an error and the spool completes, clean up that source and start the local source at the elapsed media-time offset estimated from emitted 20-ms Opus packets. Report unrecovered errors and do not count them as natural completion.
5. Live or unknown-duration media does not enter an unbounded full-download wait; it uses direct streaming. If it errors, there is no finite local fallback.
6. Cleanup temporary media on normal end, skip/stop/cancel, and error paths. Keep temporary media and runtime URL freshness out of serialized Track state. Redact URLs in playback error logs.
7. Build FFmpeg HTTP options conditionally from `ffmpeg -hide_banner -h protocol=http`: pass bounded request size only when both required options are present, along with persistent connections and short-seek behavior. This avoids passing unsupported options to older FFmpeg builds.

## Evidence and tradeoffs
Earlier live probes showed that the Android extractor profile could return a 360p MP4/AAC stream much faster than the default audio-only Opus selection, but those were different formats and not a controlled comparison. The implementation therefore preserves a separate complete best-audio spool and does not claim codec/quality parity or sub-second end-to-end startup.

On 2026-11-22 the local Docker image built successfully with FFmpeg 8.1.3. A container-local synthetic HTTP/WAV probe exercised the actual FFmpeg options, request headers, 250-packet streaming, a 5-second handoff, 153 packets of local fallback to EOF, and a full-file FFmpeg decode with exit 0. The host's FFmpeg 8.0.1 lacked `request_size`/`initial_request_size`, which led to runtime option detection.

A fresh live YouTube probe could not pass yt-dlp extraction because YouTube returned a bot-verification challenge. No `YTDL_COOKIEFILE` was configured in this test environment and no Notebane container was available. Therefore no live YouTube download, full-track decode, real Discord voice output, or slash-command manual test is claimed.

## Compatibility and scope
- Track source routes: `/play`, `/playnext`, `/playytmix`, `/playytmixnext`, search selection, saved playlist load, and restore.
- Player controls: skip, previous, stop, pause/resume, shuffle, loop, remove, undo/redo, queue/now-playing and disconnect cleanup.
- Persistent playlists and restore snapshots must contain stable page URLs/metadata only.
- Current automated coverage includes the existing suite and focused mocked preparation/player tests; it does not replace live Discord testing.

## Acceptance and release gate
- Unit suite: 91 passed in the scratch environment; changed Python files pass targeted Ruff checks.
- Docker image builds locally and the FFmpeg bounded-stream/seek-fallback fixture passes in that image.
- Repository-wide CI lint remains red: `ruff check src/` reports 54 diagnostics in other source files. The publish workflow does not depend on CI in this repository, but this lint state must be disclosed.
- Live YouTube and Discord acceptance remains open because the provider challenge requires the user's configured cookies/runtime. The user explicitly requested a `main`/GHCR `latest` test candidate to perform that validation; publishing is not the same as production acceptance or deployment.

## Rollback anchor
Baseline: `8d6e58fade4607c41144c2f38ce1fbab2eb6d368`. Preserve unrelated working-tree changes; do not reset/clean the repository. Production container restart is not part of this change.
