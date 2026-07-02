# 🚀 Notebane — Deployment Guide

Three deployment methods, ordered from simplest to most configurable.

---

## Prerequisites

Before deploying you need:

1. **A Discord bot token and Application ID** — if you haven't created a bot yet, follow the [Create Your Own Bot](create-your-bot.md) guide first — it takes about 5 minutes.
2. **Docker** installed on your host

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

### Verify it's running

```bash
docker logs notebane --tail=20
```

You should see:
```
{"level": "INFO", "msg": "Notebane ready | ..."}
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

Edit `.env` and fill in your values:

```env
DISCORD_TOKEN=your_token_here
APPLICATION_ID=your_application_id_here

# Optional
PUID=1000
PGID=1000
LOG_LEVEL=INFO
# METRICS_PORT=9090
```

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

## Environment Variables Reference

| Variable | Required | Default | Description |
|---|---|---|---|
| `DISCORD_TOKEN` | ✅ | — | Bot token from Discord Developer Portal |
| `APPLICATION_ID` | ✅ | — | Application ID from Discord Developer Portal |
| `PUID` | ❌ | `1000` | Host user ID to run as. Run `id -u` on your host to find it |
| `PGID` | ❌ | `1000` | Host group ID to run as. Run `id -g` on your host to find it |
| `LOG_LEVEL` | ❌ | `INFO` | Logging verbosity (`DEBUG`, `INFO`, `WARNING`) |
| `LOG_FORMAT` | ❌ | `json` | Log format (`json` or `text`) |
| `SHARD_COUNT` | ❌ | auto | Override Discord's shard count calculation |
| `METRICS_PORT` | ❌ | — | Expose Prometheus `/metrics` + `/health` on this port |
| `YTDL_COOKIEFILE` | ❌ | — | Path to Netscape cookies file for age-gated content |
| `FFMPEG_BEFORE_OPTIONS` | ❌ | — | Extra FFmpeg input flags |
| `FFMPEG_OPTIONS` | ❌ | — | Extra FFmpeg output flags |
