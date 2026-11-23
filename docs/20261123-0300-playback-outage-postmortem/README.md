# Playback Outage — Post-mortem

**Date:** 2026-11-23
**Status:** ✅ Resolved: fixes merged in [PR #2](https://github.com/KeeperOfStack/notebane/pull/2) (`51fbcda`) and published as `ghcr.io/keeperofstack/notebane:latest`. A retry-on-no-audio follow-up was written the same day (see [Fix 5](#fix-5--retry-once-when-a-stream-produces-no-audio)).
**Impact:** No song could be heard on any server. Commands, embeds and buttons all looked normal.

Times are UTC (bot logs). Discord client logs are local time, UTC-7.

---

## TL;DR

Four separate problems, stacked. Each one hid the next:

| # | Symptom | Root cause | Fix |
|---|---|---|---|
| 1 | FFmpeg `HTTP error 403 Forbidden` on every track | YouTube now rejects a freshly issued stream URL for a few seconds. yt-dlp gives the time it becomes valid as `available_at`, and the bot handed the URL to FFmpeg before then | Wait until `available_at` before starting FFmpeg |
| 2 | `No trailing CRLF found in HTTP header` | The bot sent one `-headers` option per header. FFmpeg only keeps the last one, and the escaping produced literal `\r\n` text, so the User-Agent was never sent | All headers in one `-headers` value with real CRLFs |
| 3 | yt-dlp stuck at `2026.06.29` for 5 months, logging "already up to date" | Exact pin in `requirements.txt`. The 12h auto-updater ran without `--pre`, couldn't write to site-packages, and never reloaded the module | Unpin, upgrade at container start, restart when idle on a new release |
| 4 | Bot shows green "speaking" ring but **nobody hears anything** | `davey` 0.2.0 (Discord DAVE E2EE voice library) never reports `ready`, so discord.py sent **unencrypted** audio and Discord clients silently dropped it | Pin `davey==0.1.7`, warn in logs if encryption isn't active |

Plus a one-off production 403 after the fix shipped, which led to **Fix 5**: retry once with a fresh URL when a stream produces no audio.

---

## Timeline

| Time (UTC) | Event |
|---|---|
| 08:48 | Production container starts. Updater logs `yt-dlp already up to date (2026.06.29.234344)` (5 months old). |
| 08:56 | `/play` in Dragonsburg → FFmpeg `403 Forbidden`. URL shows `c=ANDROID_VR`. Log also shows `No trailing CRLF found in HTTP header`. |
| ~09:30 | Code review finds the header bug (#2) and the frozen yt-dlp (#3). Wrote `scripts/pipeline_steps.py` to run each pipeline stage by hand. |
| ~10:00 | Test container on newest yt-dlp nightly with correct headers **still 403s**, even with plain `curl`. So #2 and #3 are real but not the whole story. |
| 10:03 | `yt-dlp -v` downloads the same video fine and logs `Sleeping 4.00 seconds as required by the site`. Timing test: the URL returns **403 before `available_at`, 206 after**. Root cause #1 found. |
| 10:06 | Test bot (Frog-Maestro) up with fixes #1–#3. |
| 10:08 / 10:12 | Plays succeed in the logs (FFmpeg runs the full track, exit 0) but **no sound** in Discord. |
| 10:17 | Encoded output checked: mean −26 dB / peak −9.6 dB, so the audio isn't silent. DAVE handshake completes. Added a diagnostic log of the DAVE send state. |
| 10:26 | Diagnostic shows `can_encrypt: False, ready: False, status: active, enc attempts: 0`. The Discord client log shows it **did** join the MLS group and registered the bot's audio SSRC. Root cause #4: frames sent unencrypted. |
| 10:28 | Swapped davey 0.2.0 → 0.1.7 in the container. |
| 10:32 | `can_encrypt: True, ready: True`. **Audio heard.** |
| 10:40 | PR #2 opened. CI Docker build passes (lint was already failing on `main`). |
| 10:43 | PR #2 squash-merged; publish workflow pushes `:latest`. |
| 10:53 | Production pulls new image, yt-dlp upgrades to `2026.11.22` at start. |
| 10:59 | One production 403 on the first play after start. Not reproducible: the bot's exact sequence then succeeded 5/5 in the production container. |
| 11:08 | Same track plays fine in production, with sound. |
| 11:13 | Retry-once (Fix 5) written and verified against a real 403 in a container. |

---

## How each failure was found

### Isolating the pipeline

Playback is a chain: **yt-dlp resolve → stream URL → FFmpeg → Opus packets → discord.py → DAVE encryption → UDP → Discord client**. The bot's logs only showed the end result, so the first step was a tool that runs each link by itself, using the bot's real config:

```sh
docker exec -it <container> sh
cd /app
python scripts/pipeline_steps.py env                 # versions, PyPI latest, deno/ffmpeg
python scripts/pipeline_steps.py resolve "<url>" -v  # yt-dlp with the bot's YTDL_OPTS
python scripts/pipeline_steps.py argv                # exact ffmpeg argv the bot builds
python scripts/pipeline_steps.py curl [--no-wait]    # hit the stream URL directly
python scripts/pipeline_steps.py ffmpeg [--no-wait]  # bot's ffmpeg command, 5s to a file
python scripts/pipeline_steps.py ytdlp-download -v   # yt-dlp fetches it itself (control)
```

`argv` builds the FFmpeg command with discord.py's own `FFmpegOpusAudio` code (its process spawn is intercepted), so it shows byte for byte what the bot runs.

### #2 Headers: found by reading the code, confirmed with `argv`

`argv` printed `'-headers', 'User-Agent: …\\r\\n', '-headers', 'Accept: …\\r\\n', …`. That's several `-headers` options, and the `\\r\\n` is literal backslash text, not line breaks. FFmpeg keeps only the last `-headers` and warns about the missing CRLF, so the User-Agent never reached YouTube.

### #3 Frozen yt-dlp: found from the startup log

`current: 2026.06.29` in November is a red flag. YouTube changes break old yt-dlp within weeks. The `env` step showed PyPI had `2026.11.22`. The updater's "already up to date" was wrong for three reasons: no `--pre` (the image uses nightlies), the bot user can't write to `/usr/local`, and an already-imported module isn't reloaded anyway. A container recreate also restores the pinned version.

### #1 `available_at`: found by comparing with yt-dlp's own download

With #2 and #3 fixed, `curl` still got 403. `ytdlp-download -v` (yt-dlp downloading the same video itself) **worked**, and its log said `Sleeping 4.00 seconds as required by the site`. The resolved info has an `available_at` unix timestamp. Fetching the same URL at intervals:

```
t+0s: 403   t+3s: 206   t+6s: 206   t+10s: 206
```

The bot resolved and opened FFmpeg about 2.4s later, inside the 403 window.

### #4 Silent DAVE audio: found by correlating bot and client logs

Everything on the bot side looked healthy, so we compared both ends:

- **Encoded audio** had normal loudness (`volumedetect`).
- **FFmpeg** ran the full track duration and exited 0.
- **DAVE handshake** completed: bot logged opcodes 25–29 and "MLS commit processed".
- **Discord client** (`%APPDATA%\discord\logs\renderer_js.log`) logged `Received MLS welcome for transition ID 0` and `Creating user: <bot id> with audio SSRC: 2828`. The client joined the encrypted group and was receiving the bot's packets.
- **Bot diagnostic** (davey session state 5s into the track) showed `ready: False` → discord.py's `can_encrypt` is False → `_get_voice_packet` sends raw Opus, and davey's `attempts: 0` confirms nothing was encrypted.

Since 2026-03-01 Discord requires DAVE end-to-end encryption in normal voice channels, and clients drop frames that aren't encrypted. discord.py 2.7.1 requires `davey>=0.1.0`, so the build pulled 0.2.0. Downgrading to 0.1.7 fixed it immediately. We found no upstream bug report; the evidence is the before/after above.

---

## Fixes

### Fix 1 — Wait for `available_at`
`src/notebane/player.py`: `wait_until_available()` sleeps until `available_at + 0.5s` (capped at 30s) before FFmpeg starts. `Track.available_at` is populated in `ytdl.resolve()`. It defaults to `None`, so old restore snapshots still load. Side effect: `play_latency` rises ~3–5s; the Now Playing message still posts first.

### Fix 2 — One `-headers` option with real CRLFs
`player.py`: `build_before_options()` joins all yt-dlp headers into one block and `shlex.quote`s it, because discord.py runs `shlex.split` over `before_options`.

### Fix 3 — yt-dlp stays current
- `requirements.txt`: `yt-dlp[default]` (unpinned; pulls the matching `yt-dlp-ejs`).
- `entrypoint.sh`: as root, `pip install --pre -U "yt-dlp[default]"` on every start (non-fatal, 120s timeout).
- `ytdl_updater.py`: checks PyPI every 12h. When newer **and no bot is playing**, it closes all bots and exits with code 75, and the Docker restart policy brings it back on the new version.
- New env vars: `YTDL_AUTO_UPDATE=0` (off entirely), `YTDL_AUTO_RESTART=0` (log only).

### Fix 4 — davey pin + encryption guard
- `requirements.txt`: `davey==0.1.7`, with a comment explaining why.
- `player.py`: `_check_voice_encryption()` logs a **WARNING** 5s into each track if DAVE is required but `can_encrypt` is False: `DAVE not ready — audio is being sent unencrypted…`

### Fix 5 — Retry once when a stream produces no audio
After the fix shipped, production saw one 403 on its first play after start that we couldn't reproduce (possibly YouTube refusing one URL, or the first signature-cache build). discord.py only reports FFmpeg failures if the process has already exited when the stream ends, which is a race, so nothing reached the logs.
- `player.py`: `CountingSource` wraps the audio source and counts packets sent. If a track sent **0 packets** and the user didn't skip or stop it, the bot gets a fresh URL, waits for it, and plays once more. It logs `no audio … retrying` (WARNING), then `retry succeeded` (INFO) or `no audio … after retry — skipping` (ERROR).
- Verified in a container: a too-fresh URL got a real 403 and 0 packets, the retry produced 250 packets, and the bot logged success.

### Supporting changes
- `.gitattributes`: `*.sh` always LF. A CRLF `entrypoint.sh` from a Windows checkout made the container fail with `exec /entrypoint.sh: no such file or directory`.
- `.gitignore`: `.env.*` (except `.env.example`), so test tokens can't be committed.
- `docker-compose.test.yml`: single-bot debug compose.
- Tests: `tests/test_ffmpeg_headers.py`, `tests/test_stream_retry.py`.

---

## Lessons

1. **Silent failure was the real outage.** Each bug was a few lines to fix; the time went into finding them. Nothing alerted anyone, and "playing" looked fine in both the logs and the UI.
2. **"Auto-update" wasn't.** The 2026-07-02 retrospective lists "Auto-updating yt-dlp every 12 hours", but it never worked. Untested automation is worse than none, because it creates false confidence.
3. **Loose transitive ranges are a time bomb.** `davey>=0.1.0` let a breaking release in on a routine rebuild.
4. **Compare against a known-good path.** yt-dlp's own download (#1) and the Discord client's own log (#4) each pinpointed a cause that the bot's logs couldn't.
5. **Both ends of the voice connection matter.** Bot-side metrics can all be green while the receiver discards everything.

Follow-up work to stop this happening again: [Future-proofing plan](../20261123-0425-future-proofing-plan/README.md).
