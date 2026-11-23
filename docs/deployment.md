# 🚀 Notebane — Deployment Guide

Three deployment methods, ordered from simplest to most configurable.

---

## Prerequisites

Before deploying you need:

1. **A Discord bot token and Application ID** — if you haven't created a bot yet, follow the [Create Your Own Bot](create-your-bot.md) guide first — it takes about 5 minutes.
2. **Docker** installed on your host

---

## Single Bot vs. Bot Pool

Notebane supports running **1 to 5 bots in parallel** inside a single container. Each voice channel in a guild gets its own bot, enabling simultaneous playback in multiple channels.

| Mode | When to use |
|---|---|
| **Single bot** | One voice channel at a time per server — the classic setup |
| **Bot pool (2-5)** | Multiple voice channels playing simultaneously in the same server |

### Bot 1 is the primary — the others are silent workers

In a pool, **Bot 1 (Notebane) is the only bot that registers slash commands and responds to users.** Bots 2-5 (Maestro, Cadenza, Capriccio, Calypso) are invisible audio workers — they join voice channels automatically when Bot 1 is already busy, but they never appear in the `/` command menu and users never interact with them directly.

| Bot | Role |
|---|---|
| **Bot 1 — Notebane** | Primary: registers all slash commands (`/play`, `/skip`, etc.), handles all user interaction |
| **Bot 2 — Maestro** | Audio worker: joins a 2nd simultaneous voice channel |
| **Bot 3 — Cadenza** | Audio worker: joins a 3rd simultaneous voice channel |
| **Bot 4 — Capriccio** | Audio worker: joins a 4th simultaneous voice channel |
| **Bot 5 — Calypso** | Audio worker: joins a 5th simultaneous voice channel |

This means you only need to invite as many bots as you want simultaneous voice channels. Inviting just Bot 1 gives you the classic single-bot experience with no behaviour change.

> **Adding bots to a server:** Each bot needs its own OAuth2 invite. See the [Adding Pool Bots to Your Server](#adding-pool-bots-to-your-server) section below.

---

## Volumes

Notebane needs two persistent volumes — one for the database (queue snapshots + user playlists) and one for YouTube cookies uploaded via `/ytlogin`. Both survive container restarts and redeployments.

### Option A — Named Docker Volumes (recommended)

Docker manages the storage for you. No folders to create, no permissions to set.

**Method 2 (Portainer) and Method 3 (Compose) create these volumes automatically on first deploy.** For Method 1 (docker run), you need to create them first:

```bash
docker volume create notebane_data
docker volume create notebane_cookies
```

### Option B — Local Bind Mounts

If you'd prefer the files to live in a folder you can see and browse directly:

```bash
mkdir -p ./data ./cookies
```

Replace the volume references in whichever method you use below:

```
- notebane_cookies:/cookies   →   - ./cookies:/cookies
- notebane_data:/data         →   - ./data:/data
```

---

## Method 1: One-Shot Docker Run

No config files, no cloning. Paste this with your tokens filled in and you're running:

```bash
docker volume create notebane_data
docker volume create notebane_cookies

docker run -d \
  --name notebane \
  --restart unless-stopped \
  -e DISCORD_TOKEN=your_token_here \
  -e APPLICATION_ID=your_application_id_here \
  -e PUID=1000 \
  -e PGID=1000 \
  -e LOG_FORMAT=json \
  -v notebane_cookies:/cookies \
  -v notebane_data:/data \
  --log-driver json-file \
  --log-opt max-size=10m \
  --log-opt max-file=3 \
  ghcr.io/keeperofstack/notebane:latest
```

> Set `PUID` and `PGID` to your host user's IDs. Run `id -u` and `id -g` to find them. Defaults (`1000`/`1000`) work for most single-user Linux setups.

> **Recommended:** add `-e ALERT_WEBHOOK_URL=https://discord.com/api/webhooks/...` so the bot can tell you when playback breaks. See [Owner Alerts & Playback Canary](#owner-alerts--playback-canary).

**Running a bot pool with docker run:** Add each bot as an additional `-e` pair:

```bash
docker run -d \
  --name notebane \
  --restart unless-stopped \
  -e BOT_01_TOKEN=notebane_token \
  -e BOT_01_ID=notebane_app_id \
  -e BOT_02_TOKEN=maestro_token \
  -e BOT_02_ID=maestro_app_id \
  -e BOT_03_TOKEN=cadenza_token \
  -e BOT_03_ID=cadenza_app_id \
  -e PUID=1000 \
  -e PGID=1000 \
  ...
```

### Verify it's running

```bash
docker logs notebane --tail=20
```

You should see:
```
{"level": "INFO", "msg": "BotManager initialised with N bot(s): [1, 2, ...]"}
{"level": "INFO", "msg": "Bot 1 ready | user=Notebane#2678 | guilds=... | shards=1"}
```

### Updating

```bash
docker stop notebane && docker rm notebane
docker pull ghcr.io/keeperofstack/notebane:latest
# Re-run the docker run command above
```

> Named volumes persist across container removal and redeployments — your database and cookies are safe.

---

## Method 2: Portainer Stack

### 1. Open Portainer → **Stacks** → **Add Stack**

### 2. Name it `notebane`

### 3. Paste the following into the Web Editor:

**Single bot:**

```yaml
services:
  notebane:
    image: ghcr.io/keeperofstack/notebane:latest
    container_name: notebane
    restart: unless-stopped
    environment:
      DISCORD_TOKEN: your_token_here
      APPLICATION_ID: your_application_id_here
      PUID: 1000
      PGID: 1000
      LOG_FORMAT: json
      # ALERT_WEBHOOK_URL: https://discord.com/api/webhooks/...   # recommended — see "Owner Alerts"
    volumes:
      - notebane_cookies:/cookies
      - notebane_data:/data
    logging:
      driver: "json-file"
      options:
        max-size: "10m"
        max-file: "5"
    stop_grace_period: 30s

volumes:
  notebane_cookies:
  notebane_data:
```

**Bot pool (example with 5 bots):**

```yaml
services:
  notebane:
    image: ghcr.io/keeperofstack/notebane:latest
    container_name: notebane
    restart: unless-stopped
    environment:
      BOT_01_TOKEN: notebane_token_here
      BOT_01_ID: notebane_app_id_here
      BOT_02_TOKEN: maestro_token_here
      BOT_02_ID: maestro_app_id_here
      BOT_03_TOKEN: cadenza_token_here
      BOT_03_ID: cadenza_app_id_here
      BOT_04_TOKEN: capriccio_token_here
      BOT_04_ID: capriccio_app_id_here
      BOT_05_TOKEN: calypso_token_here
      BOT_05_ID: calypso_app_id_here
      PUID: 1000
      PGID: 1000
      LOG_FORMAT: json
      # ALERT_WEBHOOK_URL: https://discord.com/api/webhooks/...   # recommended — see "Owner Alerts"
    volumes:
      - notebane_cookies:/cookies
      - notebane_data:/data
    logging:
      driver: "json-file"
      options:
        max-size: "10m"
        max-file: "5"
    stop_grace_period: 30s

volumes:
  notebane_cookies:
  notebane_data:
```

> Set `PUID`/`PGID` to your host user's IDs (`id -u` / `id -g`). Defaults work for most setups.

### 4. Click **Deploy the stack**

### Updating in Portainer

1. Go to your stack → **Editor**
2. Click **Pull and redeploy**

> Your data is stored in named Docker volumes and survives every redeploy.

---

## Method 3: Docker Compose

Best for self-hosters who want full control and an `.env` file for secrets.

### 1. Clone the repo

```bash
git clone https://github.com/KeeperOfStack/notebane.git
cd notebane
```

### 2. Create your `.env` file

```bash
cp .env.example .env
```

**Single bot** — edit `.env` and fill in:

```env
DISCORD_TOKEN=your_token_here
APPLICATION_ID=your_application_id_here

# Optional
PUID=1000
PGID=1000
LOG_LEVEL=INFO
# ALERT_WEBHOOK_URL=https://discord.com/api/webhooks/...   # recommended — see "Owner Alerts"
```

**Bot pool** — use numbered pairs instead:

```env
BOT_01_TOKEN=notebane_token_here
BOT_01_ID=notebane_app_id_here
BOT_02_TOKEN=maestro_token_here
BOT_02_ID=maestro_app_id_here
BOT_03_TOKEN=cadenza_token_here
BOT_03_ID=cadenza_app_id_here
BOT_04_TOKEN=capriccio_token_here
BOT_04_ID=capriccio_app_id_here
BOT_05_TOKEN=calypso_token_here
BOT_05_ID=calypso_app_id_here

# Optional
PUID=1000
PGID=1000
LOG_LEVEL=INFO
# ALERT_WEBHOOK_URL=https://discord.com/api/webhooks/...   # recommended — see "Owner Alerts"
```

> You can run any number of bots from 1 to 5. Just include the pairs you need — gaps are skipped automatically.

### 3. Start the container

```bash
docker compose -f docker-compose.prod.yml up -d
```

### 4. Verify it's running

```bash
docker compose -f docker-compose.prod.yml logs --tail=30
```

### Updating to a newer version

```bash
docker compose -f docker-compose.prod.yml pull
docker compose -f docker-compose.prod.yml up -d --force-recreate
```

> Data in named volumes is never touched by `pull` or `up` — it persists automatically.

---

## Adding Pool Bots to Your Server

Each bot in the pool is a separate Discord application and must be invited to your server individually. Without this, the container will start all bots but only the ones in your server will handle commands.

**The easiest way** is to use the official invite page at [keeperofstack.github.io/notebane](https://keeperofstack.github.io/notebane/) — enter the invite password and you'll see invite links for all 5 bots in order.

See the [Bot 1 is the primary](#bot-1-is-the-primary--the-others-are-silent-workers) section above for a full breakdown of each bot's role. Remember: you only need to invite as many bots as you want simultaneous channels.

> **Permissions required for each bot:** `Connect`, `Speak`, `View Channels`, `Send Messages`, `Embed Links`, `Read Message History`, `Use Application Commands`.

---

## Environment Variables Reference

| Variable | Required | Default | Description |
|---|---|---|---|
| `DISCORD_TOKEN` | ✅ (single-bot) | — | Legacy single-bot token. Use `BOT_01_TOKEN` instead for pool deployments |
| `APPLICATION_ID` | ✅ (single-bot) | — | Legacy single-bot application ID |
| `BOT_01_TOKEN` | ✅ (pool) | — | Token for Bot 1 (Notebane) |
| `BOT_01_ID` | ✅ (pool) | — | Application ID for Bot 1 |
| `BOT_02_TOKEN` … `BOT_05_TOKEN` | ❌ | — | Tokens for pool bots 2-5 |
| `BOT_02_ID` … `BOT_05_ID` | ❌ | — | Application IDs for pool bots 2-5 |
| `PUID` | ❌ | `1000` | Host user ID to run as. Run `id -u` on your host to find it |
| `PGID` | ❌ | `1000` | Host group ID to run as. Run `id -g` on your host to find it |
| `LOG_LEVEL` | ❌ | `INFO` | Logging verbosity (`DEBUG`, `INFO`, `WARNING`) |
| `LOG_FORMAT` | ❌ | `json` | Log format (`json` or `text`) |
| `SHARD_COUNT` | ❌ | auto | Override Discord's shard count calculation |
| `METRICS_PORT` | ❌ | — | Expose Prometheus `/metrics`, `/health` and `/canary` on this port |
| `ALERT_WEBHOOK_URL` | ❌ (recommended) | — | Discord channel webhook for owner alerts (playback canary, silent voice, skipped tracks, yt-dlp restarts). See [Owner Alerts](#owner-alerts--playback-canary) |
| `ALERT_RATE_LIMIT_MINUTES` | ❌ | `60` | Minimum minutes between repeats of the same alert |
| `CANARY_INTERVAL_HOURS` | ❌ | `6` | How often Bot 1 self-tests playback. `0` disables the canary |
| `CANARY_URLS` | ❌ | 2 stable videos | Comma-separated videos the canary plays |
| `CANARY_FAIL_HEALTH` | ❌ | `0` | `1` = `/health` returns 503 while the canary is failing (for external monitors) |
| `YTDL_AUTO_UPDATE` | ❌ | `1` | Upgrade yt-dlp on every container start and check for new versions every 12 h. `0` = never |
| `YTDL_AUTO_RESTART` | ❌ | `1` | When a newer yt-dlp is out and nothing is playing, restart to load it (needs `restart: unless-stopped`). `0` = log only |
| `YTDL_COOKIEFILE` | ❌ | — | Path to Netscape cookies file for age-gated content |
| `FFMPEG_BEFORE_OPTIONS` | ❌ | — | Extra FFmpeg input flags |
| `FFMPEG_OPTIONS` | ❌ | — | Extra FFmpeg output flags |

---

## Owner Alerts & Playback Canary

Notebane can tell **you** (the person running it) when playback breaks, instead of you finding out from users. YouTube, yt-dlp and Discord's voice protocol all change without notice; this turns "broken for weeks" into "you get a message within hours, naming what failed".

### How it works

- **Same bot, same container.** Nothing extra to run. Bot 1 (your primary bot) does the checks inside the existing Notebane container, on your server's own network. That matters because YouTube treats home/server IPs differently from cloud test runners.
- **Playback canary.** About 2 minutes after startup and then every 6 hours, Bot 1 plays ~3 seconds of a couple of well-known YouTube videos through the exact pipeline the player uses (yt-dlp → wait for the stream to become valid → FFmpeg). It doesn't join a voice channel and nobody hears it.
- **Alerts are posted by a Discord webhook**, not a bot. A webhook is a URL that posts messages into one channel. You don't need to create another bot or give anything new permissions.

### What you'll be alerted about

| Alert | When |
|---|---|
| ✅ *Notebane started — playback canary passing* | First canary run after each start (confirms alerts work) |
| 🔴 *Notebane canary failing — stage `…`* | Canary goes from passing to failing; names the stage (`resolve`, `http 403`, `ffmpeg`, `timeout`) |
| 🔴 *…still failing* | Reminder while it stays broken (rate-limited) |
| ✅ *Notebane canary recovered* | Canary passes again |
| 🔴 *Voice encryption not active* | Bot is "speaking" but Discord's E2EE (DAVE) isn't active, so listeners hear nothing |
| 🟡 *Track skipped — no audio after retry* | A track failed twice (usually YouTube refusing the stream) |
| ℹ️ *Restarting to load yt-dlp …* | The auto-updater is restarting the bot for a new yt-dlp |

The same alert repeats at most once an hour (`ALERT_RATE_LIMIT_MINUTES`). Alerts never contain tokens or cookies, and never @mention anyone.

### Setup (about 2 minutes)

1. In your Discord server, create a **private** text channel, e.g. `#notebane-alerts`.
2. **Edit Channel → Integrations → Webhooks → New Webhook.** Name it (e.g. *Notebane Alerts*), then **Copy Webhook URL**.
3. Add it to the container's environment:
   - **docker run:** `-e ALERT_WEBHOOK_URL=https://discord.com/api/webhooks/...`
   - **Portainer / compose:** `ALERT_WEBHOOK_URL: https://discord.com/api/webhooks/...` under `environment:`
   - **.env:** `ALERT_WEBHOOK_URL=https://discord.com/api/webhooks/...`
4. Recreate the container (a plain restart doesn't pick up new environment variables).
5. Within ~2 minutes you should see **✅ Notebane started — playback canary passing** in the channel.

> 🔒 Treat the webhook URL like a password: anyone who has it can post into that channel. If it leaks, delete the webhook in Discord and create a new one.

### Checking status yourself

- **Logs:** `docker logs notebane 2>&1 | grep canary` shows `canary PASS` / `canary FAIL … stage=…` lines.
- **HTTP** (if `METRICS_PORT` is set): `curl http://localhost:9090/canary` returns the last result as JSON. Prometheus gets `notebane_canary_ok`, `notebane_canary_failures_total` and `notebane_canary_last_run_timestamp_seconds`.
- **External monitor:** set `CANARY_FAIL_HEALTH=1` and point your uptime monitor at `/health`. It returns 503 while the canary is failing.
- **Manual deep-dive:** `scripts/pipeline_steps.py` runs each playback stage by hand. See the [outage post-mortem](20261123-0300-playback-outage-postmortem/README.md#isolating-the-pipeline).

---

## Image Tags, Updates & Rollback

Images are published to `ghcr.io/keeperofstack/notebane` **only after lint, tests and a build check pass**.

| Tag | Moves? | Use it for |
|---|---|---|
| `:latest` | Every merge to `main` | Following development; simplest setup |
| `:1.5.0` / `:1.5` | Only on a release tag | **Recommended for production**: you choose when to upgrade |
| `:sha-51fbcda` | Never | Rolling back to an exact known-good build |

**Rolling back:** change `image:` (or the `docker run` tag) to the last good `:sha-…` or version tag and recreate the container. Your volumes are untouched.

**yt-dlp is the exception:** whatever tag you run, the container upgrades yt-dlp to the newest release on start (and restarts itself when idle if a newer one ships), because YouTube breaks old versions within weeks. Set `YTDL_AUTO_UPDATE=0` to freeze it, e.g. while debugging. Maintainers: see [Releasing & Dependency Updates](releasing.md).

---

## Optional: Automatic Updates with Watchtower

If you'd prefer the container to update itself automatically when a new image is published to GHCR, you can add [Watchtower](https://containrrr.dev/watchtower/) as a companion container.

When Notebane restarts after an update, Bot 1 automatically re-syncs all slash commands to every server it's in — so new or removed commands and buttons are always up to date with no user action needed.

> **Note:** Watchtower recreates the container when it detects a new image, which means a brief disconnection for anyone currently listening. If uninterrupted uptime matters more than staying current, stick with manual pulls.

### With Docker Compose (add to your compose file)

Add the following service alongside your `notebane` service, and add the label to the `notebane` service:

```yaml
services:
  notebane:
    image: ghcr.io/keeperofstack/notebane:latest
    # ... your existing config ...
    labels:
      - "com.centurylinklabs.watchtower.enable=true"

  watchtower:
    image: containrrr/watchtower:latest
    container_name: notebane-watchtower
    restart: unless-stopped
    environment:
      WATCHTOWER_POLL_INTERVAL: 300      # check every 5 minutes
      WATCHTOWER_CLEANUP: "true"         # remove old images after update
      WATCHTOWER_INCLUDE_STOPPED: "false"
      WATCHTOWER_LABEL_ENABLE: "true"    # only watch labelled containers
      WATCHTOWER_NO_STARTUP_MESSAGE: "true"
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock
```

### With Docker Run (two separate commands)

```bash
# Run notebane with the watchtower label
docker run -d \
  --name notebane \
  --restart unless-stopped \
  --label com.centurylinklabs.watchtower.enable=true \
  -e DISCORD_TOKEN=your_token_here \
  -e APPLICATION_ID=your_application_id_here \
  -v notebane_cookies:/cookies \
  -v notebane_data:/data \
  ghcr.io/keeperofstack/notebane:latest

# Run watchtower alongside it
docker run -d \
  --name notebane-watchtower \
  --restart unless-stopped \
  -e WATCHTOWER_POLL_INTERVAL=300 \
  -e WATCHTOWER_CLEANUP=true \
  -e WATCHTOWER_LABEL_ENABLE=true \
  -e WATCHTOWER_NO_STARTUP_MESSAGE=true \
  -v /var/run/docker.sock:/var/run/docker.sock \
  containrrr/watchtower:latest
```

### With Portainer

Add the `watchtower` service block and the `labels` entry to your stack YAML as shown in the Compose example above, then click **Pull and redeploy** once to get Watchtower running — after that it handles everything automatically.

