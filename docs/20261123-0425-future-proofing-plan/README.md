# Future-proofing Plan

**Date:** 2026-11-23
**Status:** 📋 Planned: nothing in this document is built yet unless marked ✅.
**Context:** [Playback outage post-mortem](../20261123-0300-playback-outage-postmortem/README.md)

## Goal

Notebane depends on three things outside our control: **YouTube** (fights downloaders and changes often), **yt-dlp** (adapts to YouTube, ships nightly), and **Discord voice** (made DAVE end-to-end encryption mandatory in 2026). No self-hosted music bot is maintenance-free. The goal is to change what a breakage costs:

| | Before (Nov 2026 outage) | Target |
|---|---|---|
| Time to notice | Users complain; unknown how long it was broken | **Hours**, via an automatic alert to the owner |
| Time to diagnose | Hours of debugging across 4 stacked causes | **Minutes**: the alert names the failing stage |
| Typical fix | Code changes, rebuild, redeploy | **Bump one version** via a tested PR, or nothing (yt-dlp self-updates) |
| Bad release | Hard to undo | **One-line rollback** to a pinned image tag |

## Already done (2026-11-23)

- ✅ yt-dlp unpinned, upgraded at every container start, restarts itself when idle on a new release
- ✅ `davey==0.1.7` pinned, with a log warning if voice encryption isn't active
- ✅ Retry once with a fresh URL when a stream produces no audio
- ✅ `scripts/pipeline_steps.py` to check each playback stage by hand

---

## Workstream 1 — Playback canary + owner alerts

**Status:** ✅ Implemented 2026-11-23: `src/notebane/canary.py`, `src/notebane/alerts.py`. Setup steps are in the [deployment guide](../deployment.md#owner-alerts--playback-canary).

### What it is

A **self-test the bot runs on its own server every few hours**, plus **alerts posted to a Discord channel** for you when something breaks. It does what you'd do by hand: play a known song and check that audio comes out.

### Why it has to run on the bot's own server

YouTube treats datacenter IPs (GitHub Actions, cloud VMs) differently from home connections. A test in GitHub could fail when production is fine, or pass when production is broken. The only reliable test runs from the same network as the bot.

### How it works

1. **On a schedule** (default every 6h, plus ~2 min after startup), Bot 1 runs the real playback pipeline against 2–3 stable videos:
   `resolve()` → wait for `available_at` → FFmpeg pulls ~3s of audio.
   It uses the same functions the player uses, so it tests real behaviour, not a copy.
2. **Records the result**: pass/fail, which stage failed (`resolve` / `HTTP 403` / `ffmpeg`), the yt-dlp version, and which YouTube client was used.
3. **Exposes it**:
   - Prometheus metrics (`notebane_canary_ok`, `notebane_canary_failures_total`) if `METRICS_PORT` is set
   - last result in the `/health` endpoint
4. **Alerts you** through a Discord webhook when:
   - the canary goes from passing to failing (and again when it recovers)
   - the bot logs `DAVE not ready` (silent-audio protection)
   - a track is skipped because it produced no audio even after the retry
   - the yt-dlp updater restarts the bot for a new version (informational)

   Alerts are rate-limited (the same alert at most once an hour) and never include tokens or cookies.

### Example alert

> 🔴 **Notebane canary failing**: stage `http 403`, yt-dlp `2026.11.22`, client `TVHTML5`, 3/3 test videos failed. Last success 6h ago.

### How the updates reach you: no extra bot needed

Alerts use a **Discord webhook**, which is a URL that posts messages into a channel. No bot account, token or code on Discord's side.

**Setup (2 minutes):**
1. In your Discord server, pick or create a private channel (e.g. `#notebane-alerts`).
2. **Channel settings → Integrations → Webhooks → New Webhook**. Name it (e.g. "Notebane Alerts"), optionally give it an avatar.
3. **Copy Webhook URL.**
4. Add it to the bot's environment and recreate the container:
   ```env
   ALERT_WEBHOOK_URL=https://discord.com/api/webhooks/…
   CANARY_INTERVAL_HOURS=6        # 0 disables the canary
   # CANARY_URLS=https://youtu.be/…,https://youtu.be/…   # optional override
   ```

Treat the webhook URL like a password: anyone who has it can post into that channel. If it leaks, delete the webhook and make a new one.

### Done when

- Canary runs on schedule and on startup; only Bot 1 runs it
- Metrics and `/health` show the last result
- Webhook alerts fire on state changes, DAVE warnings, retry-exhausted skips and update restarts, and are rate-limited
- Env vars documented in `.env.example` and `docs/deployment.md`; unit tests cover alerting and rate limiting

---

## Workstream 2 — Locked dependencies, update PRs, gated releases

**Status:** 🚧 In progress.

### What it is

Make every dependency change **deliberate and tested**, except yt-dlp, which keeps auto-updating on purpose. Make the published image trustworthy.

### Why

The davey break wasn't caused by anything we changed: discord.py allows `davey>=0.1.0`, so a routine rebuild pulled a new, broken release. Today any rebuild can silently change a dozen packages. Two more weak spots:
- CI lint has been failing on `main` for a while, so a red check means nothing.
- `:latest` is published on every push to `main` even if tests fail.

### Pieces

1. **Lockfile**: generate a hash-pinned `requirements.lock` (pip-tools or uv) from `requirements.txt` for everything **except** yt-dlp / yt-dlp-ejs. The Docker build installs from the lock, so the same commit always builds the same image. yt-dlp is still installed unpinned and upgraded at container start.
2. **Automated update PRs (Renovate)**: a bot opens grouped PRs weekly for Python packages, GitHub Actions and the base image. Each runs CI. You review and merge, or ignore it, and nothing changes. PRs touching `discord.py` or `davey` get a `needs-voice-test` label: play a track on the test bot and check for no `DAVE not ready` warning before merging.
   - *Renovate* is a free GitHub app; enabling it on the repo is a one-time click plus a `renovate.json` config file. Dependabot (built into GitHub) is the fallback.
3. **Make CI meaningful**:
   - fix the ~60 existing ruff lint findings (behaviour-neutral)
   - add a pytest job
   - fix or explicitly mark the 8 tests already failing on `main` (`test_routing`, `test_startup`, `test_ux_guarantees`)
   - move workflow actions off deprecated Node 20
4. **Gate publishing**: `:latest` is pushed only after lint, tests and the Docker build pass. `:sha-<commit>` tags are kept for every build.
5. **Versioned releases + rollback**:
   - tag releases (`v1.4.0`) → versioned images (`:1.4.0`, `:1.4`)
   - recommended production setup: run a version tag, or let Watchtower follow only tagged releases
   - rollback = change the tag back and recreate the container

### Done when

- Docker build uses the lockfile; CI is green on `main` and blocks failures
- Publish waits for CI; Renovate config is merged and producing PRs
- `docs/deployment.md` explains the release and rollback flow

---

## Workstream 3 — Optional: offload YouTube + voice to Lavalink

Only if Workstreams 1–2 are in place and breakages still cost real time.

**Lavalink** is a separate audio server (Java, one extra container). Its community-maintained YouTube plugin's whole job is keeping up with YouTube, and it handles audio encoding and the Discord voice connection itself. The bot would drive it from Python through a client library (e.g. wavelink) instead of running yt-dlp and FFmpeg.

- **Pros:** YouTube fixes and voice-protocol changes come from projects focused on exactly that; less custom code in `player.py`.
- **Cons:** another service to run and monitor; `player.py` would be rewritten; check Lavalink's DAVE support status before committing to it.

Decision deferred. Revisit after a few months of canary data.

---

## Order and effort

| Step | Workstream | Owner action needed | Rough size |
|---|---|---|---|
| 1 | Canary + webhook alerts | Create the webhook, set `ALERT_WEBHOOK_URL` | Medium (one PR) |
| 2 | Lockfile + gated publish + CI fixes | Review PR | Medium (one PR) |
| 3 | Renovate | Install the Renovate GitHub app once | Small |
| 4 | Versioned releases in production | Switch production to a version tag | Small |
| 5 | Lavalink evaluation | Decide | Large, optional |

Steps 1 and 2 are independent and can run in parallel.

## Routine after this is in place

- **Weekly (5 min):** skim and merge Renovate PRs that passed CI; voice-test those labelled `needs-voice-test`.
- **When an alert fires:** read the failing stage in the alert → run `scripts/pipeline_steps.py` in the container if needed → usually the fix is a yt-dlp release (automatic) or one version bump.
- **Nothing to do** when yt-dlp ships a release: the bot upgrades and restarts itself when idle.
