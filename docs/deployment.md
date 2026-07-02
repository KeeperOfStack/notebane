# 🚀 Notebane — Deployment Guide

Three deployment methods, ordered from simplest to most configurable.

---

## Prerequisites

Before deploying you need:

1. **A Discord bot token and Application ID** — if you haven't created a bot yet, follow the [Create Your Own Bot](create-your-bot.md) guide first — it takes about 5 minutes.
2. **Docker** installed on your host

---

## Method 1: One-Shot Docker Run

No config files, no cloning. Paste this with your tokens filled in and you're running:

```bash
docker run -d \
  --name notebane \
  --restart unless-stopped \
  -e DISCORD_TOKEN=*** \
  -e APPLICATION_ID=your_application_id_here \
  -e PUID=1000 \
  -e PGID=1000 \
  -e LOG_FORMAT=json \
  -v ./cookies:/cookies \
  -v ./data:/data \
  --log-driver json-file \
  --log-opt max-size=10m \
  --log-opt max-file=3 \
  ghcr.io/keeperofstack/notebane:latest
```

### Verify it's running

```bash
docker logs notebane --tail=20
```

You should see:
```
{"level": "INFO", "msg": "Synced 18 slash commands"}
```

### Updating

```bash
docker stop notebane && docker rm notebane
docker pull ghcr.io/keeperofstack/notebane:latest
# Re-run the docker run command above
```

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
      - ./cookies:/cookies
      - ./data:/data
    logging:
      driver: "json-file"
      options:
        max-size: "10m"
        max-file: "5"
    stop_grace_period: 30s
```

### 4. Click **Deploy the stack**

### Updating in Portainer

1. Go to your stack → **Editor**
2. Click **Pull and redeploy**

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
LOG_LEVEL=INFO
# METRICS_PORT=9090
# YTDL_COOKIEFILE=/cookies/cookies.txt
```

### 3. Pull the latest image

```bash
docker pull ghcr.io/keeperofstack/notebane:latest
```

### 4. Start the container

```bash
docker compose -f docker-compose.prod.yml up -d
```

### 5. Verify it's running

```bash
docker compose -f docker-compose.prod.yml logs --tail=30
```

### Updating to a newer version

```bash
docker compose -f docker-compose.prod.yml down
docker pull ghcr.io/keeperofstack/notebane:latest
docker compose -f docker-compose.prod.yml up -d
```

---

## Environment Variables Reference

| Variable | Required | Default | Description |
|---|---|---|---|
| `DISCORD_TOKEN` | ✅ | — | Bot token from Discord Developer Portal |
| `APPLICATION_ID` | ✅ | — | Application ID from Discord Developer Portal |
| `PUID` | ❌ | `1000` | Host user ID to run the bot process as. Set to your Docker host user's UID (`id -u`) |
| `PGID` | ❌ | `1000` | Host group ID to run the bot process as. Set to your Docker host user's GID (`id -g`) |
| `LOG_LEVEL` | ❌ | `INFO` | Logging verbosity (`DEBUG`, `INFO`, `WARNING`) |
| `LOG_FORMAT` | ❌ | `json` | Log format (`json` or `text`) |
| `SHARD_COUNT` | ❌ | auto | Override Discord's shard count calculation |
| `METRICS_PORT` | ❌ | — | Expose Prometheus `/metrics` + `/health` on this port |
| `YTDL_COOKIEFILE` | ❌ | — | Path to Netscape cookies file for age-gated content |
| `FFMPEG_BEFORE_OPTIONS` | ❌ | — | Extra FFmpeg input flags |
| `FFMPEG_OPTIONS` | ❌ | — | Extra FFmpeg output flags |
