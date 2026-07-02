# 🎵 Notebane

**A lightweight, high-fidelity Discord music bot powered by yt-dlp — built for massive multi-server scale.**

[![CI](https://github.com/KeeperOfStack/notebane/actions/workflows/ci.yml/badge.svg)](https://github.com/KeeperOfStack/notebane/actions/workflows/ci.yml)
[![License: AGPL v3](https://img.shields.io/badge/License-AGPL%20v3-blue.svg)](LICENSE)
[![Docker](https://img.shields.io/badge/image-ghcr.io-blue)](https://ghcr.io/keeperofstack/notebane)

---

## ✨ Features

- 🔊 **Crystal-clear audio** — highest quality stream selection via yt-dlp + FFmpeg Opus passthrough
- 🏗️ **Ultra-lightweight Docker image** — Alpine-based, < 200MB
- 🌐 **Massively scalable** — AutoSharding supports 100s+ of concurrent servers
- 🎚️ **Multi-VC per server** — each voice channel gets its own isolated player session
- 🎵 **Full queue system** — add, skip, shuffle, loop, remove tracks
- 📋 **Slash commands** — fully Discord application-command native
- ⚡ **Fast start** — single-URL `/play` under 1.5s, playlist first-track under 2.5s (see [perf baseline](docs/phase11-quickplay/perf-baseline.md))
- 🧠 **Smart cookies** — YouTube cookies only sent on age-gate retries or ≥200-entry playlists, never on public content (see [cookie policy](docs/phase11-quickplay/cookie-policy.md))
- 🎛️ **Now Playing controls** — interactive ⏸/⏭/⏹ buttons on every track start message
- 📃 **Playlist support** — full YouTube playlist loading via yt-dlp internal API (~2× more tracks than unauthenticated HTML scraping), with parallel background resolve for fast queue loading

---

## 📖 Documentation

- [🤖 Create Your Own Bot](docs/create-your-bot.md) — step-by-step: create a Discord app, get your token, and invite it to your servers
- [🚀 Deployment Guide](docs/deployment.md) — Docker run, Portainer, and Compose setup
- [📋 Command Reference](docs/commands.md) — all slash commands and what they do
- [🏛️ Design & Architecture](docs/notebane/design.md) — full design, phase breakdown, internals
- [🔐 YouTube Login (`/ytlogin`)](docs/ytlogin/README.md) — per-guild cookie upload for age-restricted content
- [⚡ Quick-Play & Cookie Policy](docs/phase11-quickplay/README.md) — Phase 11 perf initiative: fast paths, parallel resolve, smart-cookie contract, and latency baseline

---

## 🚀 Quick Start

**1. Create persistent volumes:**

```bash
docker volume create notebane_data
docker volume create notebane_cookies
```

**2. Run the container:**

```bash
docker run -d \
  --name notebane \
  --restart unless-stopped \
  -e DISCORD_TOKEN=*** \
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

See the full [Deployment Guide](docs/deployment.md) for Portainer, Compose, and bind mount options.

---

## ⚖️ Licensing & Commercial Use

This project is **dual-licensed**.

### Open Source (AGPLv3)
Free to fork, modify, and use — provided any derivative works or hosted services are also open-sourced under AGPLv3.

### Commercial License
For proprietary or closed-source use, a commercial license is required. **[Open a GitHub Issue](../../issues/new?title=Commercial+License+Inquiry)** with the title "Commercial License Inquiry" to inquire.

---

## 🔒 Privately Hosted Bot

This bot is privately hosted. To add it to your server, visit:

**[keeperofstack.github.io/notebane](https://keeperofstack.github.io/notebane/)**
