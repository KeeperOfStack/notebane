# 🚀 Notebane — Deployment Guide

Two supported methods: **Docker Compose** (recommended) and **Portainer Stack**.

---

## Prerequisites

Before deploying you need:

1. **A Discord bot token** — from [discord.com/developers/applications](https://discord.com/developers/applications) → your app → **Bot** tab → **Reset Token**
2. **Your Application ID** — same page → **General Information** → Application ID
3. **Docker** installed on your host

---

## Method 1: Docker Compose

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
DISCORD_TOKEN=your_bot_token_here
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

You should see:
```
{"level": "INFO", "msg": "Synced 17 slash commands"}
```

### Updating to a newer version

```bash
docker compose -f docker-compose.prod.yml down
docker pull ghcr.io/keeperofstack/notebane:latest
docker compose -f docker-compose.prod.yml up -d
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
    restart: unless-stopped
    env_file:
      - stack.env
    environment:
      LOG_FORMAT: json
    logging:
      driver: "json-file"
      options:
        max-size: "10m"
        max-file: "5"
    stop_grace_period: 30s
    deploy:
      resources:
        limits:
          cpus: "2.0"
          memory: 1G
        reservations:
          cpus: "0.25"
          memory: 256M
```

### 4. Scroll down to **Environment variables** and add:

| Key | Value |
|---|---|
| `DISCORD_TOKEN` | your bot token |
| `APPLICATION_ID` | your application ID |
| `LOG_FORMAT` | `json` |

### 5. Click **Deploy the stack**

### Updating in Portainer

1. Go to your stack → **Editor**
2. Click **Pull and redeploy**

---

## Environment Variables Reference

| Variable | Required | Default | Description |
|---|---|---|---|
| `DISCORD_TOKEN` | ✅ | — | Bot token from Discord Developer Portal |
| `APPLICATION_ID` | ✅ | — | Application ID from Discord Developer Portal |
| `LOG_LEVEL` | ❌ | `INFO` | Logging verbosity (`DEBUG`, `INFO`, `WARNING`) |
| `LOG_FORMAT` | ❌ | `json` | Log format (`json` or `text`) |
| `SHARD_COUNT` | ❌ | auto | Override Discord's shard count calculation |
| `METRICS_PORT` | ❌ | — | Expose Prometheus `/metrics` + `/health` on this port |
| `YTDL_COOKIEFILE` | ❌ | — | Path to Netscape cookies file for age-gated content |
| `FFMPEG_BEFORE_OPTIONS` | ❌ | — | Extra FFmpeg input flags |
| `FFMPEG_OPTIONS` | ❌ | — | Extra FFmpeg output flags |
