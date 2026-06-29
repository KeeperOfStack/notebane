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
- ⚡ **Low latency** — direct stream-to-voice pipeline, no intermediate disk writes

---

## 📖 Documentation

- [🚀 Deployment Guide](docs/deployment.md) — Docker Compose and Portainer stack setup
- [📋 Command Reference](docs/commands.md) — all slash commands and what they do
- [🏛️ Design & Architecture](docs/notebane/design.md) — full design, phase breakdown, internals

---

## 🚀 Quick Start

```bash
git clone https://github.com/KeeperOfStack/notebane.git
cd notebane
cp .env.example .env
# Edit .env — add your DISCORD_TOKEN and APPLICATION_ID
docker compose -f docker-compose.prod.yml up -d
```

See the full [Deployment Guide](docs/deployment.md) for Portainer and advanced options.

---

## 🏛️ Architecture

```
Discord Gateway (shards)
        │
        ▼
  Bot Process (discord.py AutoSharding)
        │
  ┌─────┴──────┐
  │  Per-Guild │  ← fully isolated player per voice channel
  │  Player    │
  │  Manager   │
  └─────┬──────┘
        │ yt-dlp stream URL
        ▼
   FFmpeg → Discord Voice (Opus)
```

---

## 🛠️ Tech Stack

| Layer | Choice | Why |
|---|---|---|
| Bot framework | `discord.py` 2.x | Best voice support, slash commands, AutoSharding |
| Audio fetcher | `yt-dlp` | Most maintained, widest source support |
| Audio encoder | FFmpeg (Opus) | Zero re-encode, lossless Discord passthrough |
| Container | Alpine Linux | < 200MB image |
| Orchestration | Docker Compose | Simple single-node deploy |

---

## 📋 Development Phases

| Phase | Description | Status |
|---|---|---|
| 1 | Project scaffold, Docker, CI | ✅ Complete |
| 2 | Core bot: join/leave, slash commands | ✅ Complete |
| 3 | Audio pipeline: yt-dlp → FFmpeg → voice | ✅ Complete |
| 4 | Queue system (add, skip, shuffle, loop) | ✅ Complete |
| 5 | Multi-VC isolation per guild | ✅ Complete |
| 6 | Sharding & scalability hardening | ✅ Complete |
| 7 | Polish: embeds, error handling, /help | ✅ Complete |
| 8 | Production hardening, GHCR publish | ✅ Complete |

---

## ⚖️ Licensing & Commercial Use

This project is **dual-licensed**.

### Open Source (AGPLv3)
Free to fork, modify, and use — provided any derivative works or hosted services are also open-sourced under AGPLv3.

### Commercial License
For proprietary or closed-source use, a commercial license is required. **[Open a GitHub Issue](../../issues/new?title=Commercial+License+Inquiry)** with the title "Commercial License Inquiry" to inquire.
