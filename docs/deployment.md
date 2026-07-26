# 🚀 Notebane — Deployment Guide

Three deployment methods, ordered from simplest to most configurable.

> **Auto-updates included** — every method below includes [Watchtower](https://containrrr.dev/watchtower/), a companion container that polls GHCR every 5 minutes and automatically pulls + recreates Notebane when a new image is published. Slash commands and interactive buttons are always re-synced on restart — no one needs to kick and reinvite the bot.

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

Handled automatically by Watchtower — no action needed.

To manually force an update:

```bash
docker stop notebane && docker rm notebane
docker pull ghcr.io/keeperofstack/notebane:latest
# Re-run the docker run command above
```

> If you want auto-updates for a `docker run` deployment, add a Watchtower container alongside it:
> ```bash
> docker run -d \
>   --name notebane-watchtower \
>   --restart unless-stopped \
>   -e WATCHTOWER_POLL_INTERVAL=300 \
>   -e WATCHTOWER_CLEANUP=true \
>   -e WATCHTOWER_LABEL_ENABLE=true \
>   -e WATCHTOWER_NO_STARTUP_MESSAGE=true \
>   -v /var/run/docker.sock:/var/run/docker.sock \
>   containrrr/watchtower:latest
> ```
> Then add `--label com.centurylinklabs.watchtower.enable=true` to your `docker run` command for notebane.

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
    volumes:
      - notebane_cookies:/cookies
      - notebane_data:/data
    logging:
      driver: "json-file"
      options:
        max-size: "10m"
        max-file: "5"
    stop_grace_period: 30s
    labels:
      - "com.centurylinklabs.watchtower.enable=true"

  watchtower:
    image: containrrr/watchtower:latest
    container_name: notebane-watchtower
    restart: unless-stopped
    environment:
      WATCHTOWER_POLL_INTERVAL: 300
      WATCHTOWER_CLEANUP: "true"
      WATCHTOWER_INCLUDE_STOPPED: "false"
      WATCHTOWER_LABEL_ENABLE: "true"
      WATCHTOWER_NO_STARTUP_MESSAGE: "true"
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock

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
    volumes:
      - notebane_cookies:/cookies
      - notebane_data:/data
    logging:
      driver: "json-file"
      options:
        max-size: "10m"
        max-file: "5"
    stop_grace_period: 30s
    labels:
      - "com.centurylinklabs.watchtower.enable=true"

  watchtower:
    image: containrrr/watchtower:latest
    container_name: notebane-watchtower
    restart: unless-stopped
    environment:
      WATCHTOWER_POLL_INTERVAL: 300
      WATCHTOWER_CLEANUP: "true"
      WATCHTOWER_INCLUDE_STOPPED: "false"
      WATCHTOWER_LABEL_ENABLE: "true"
      WATCHTOWER_NO_STARTUP_MESSAGE: "true"
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock

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

Handled automatically by Watchtower — no action needed.

To manually force an update:

```bash
docker compose -f docker-compose.prod.yml pull
docker compose -f docker-compose.prod.yml up -d --force-recreate
```

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
| `METRICS_PORT` | ❌ | — | Expose Prometheus `/metrics` + `/health` on this port |
| `YTDL_COOKIEFILE` | ❌ | — | Path to Netscape cookies file for age-gated content |
| `FFMPEG_BEFORE_OPTIONS` | ❌ | — | Extra FFmpeg input flags |
| `FFMPEG_OPTIONS` | ❌ | — | Extra FFmpeg output flags |
