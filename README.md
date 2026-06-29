# 🎵 Notebane

**A lightweight, high-fidelity Discord music bot powered by yt-dlp — built for massive multi-server scale.**

[![Docker](https://img.shields.io/badge/Docker-ultra--lightweight-blue)](https://hub.docker.com)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Status: In Development](https://img.shields.io/badge/Status-In%20Development-orange)]()

---

## ✨ Features

- 🔊 **Crystal-clear audio** — highest quality stream selection via yt-dlp + FFmpeg Opus passthrough
- 🏗️ **Ultra-lightweight Docker image** — Alpine-based, < 200MB target
- 🌐 **Massively scalable** — stateless shard architecture supports 100s+ of concurrent servers
- 🎚️ **Multi-VC per server** — each voice channel gets its own isolated player session
- 🎵 **Queue system** — add, skip, shuffle, loop, and manage full playlists
- 📋 **Slash commands** — fully Discord application-command native
- ⚡ **Low latency** — direct stream-to-voice pipeline, no intermediate disk writes

---

## 🚀 Quick Start

```bash
git clone https://github.com/KeeperOfStack/notebane.git
cd notebane
cp .env.example .env
# Edit .env — add your DISCORD_TOKEN and APPLICATION_ID
docker compose up -d
```

---

## 🏛️ Architecture

```
Discord Gateway (shards)
        │
        ▼
  Bot Process (discord.py + sharding)
        │
  ┌─────┴──────┐
  │  Per-Guild │  ← fully isolated player per server
  │  Player    │
  │  Manager   │
  └─────┬──────┘
        │ yt-dlp stream URL
        ▼
   FFmpeg → Discord Voice (Opus)
```

Notebane uses **AutoSharding** so a single process scales across thousands of guilds. For planet-scale deployment (1000s of servers), a future phase adds **Redis-backed session state** and horizontal worker scaling.

---

## 📖 Documentation

- [`docs/notebane/design.md`](docs/notebane/design.md) — full design, architecture, phase breakdown
- [`docs/notebane/README.md`](docs/notebane/README.md) — developer guide

---

## 🛠️ Tech Stack

| Layer | Choice | Why |
|---|---|---|
| Bot framework | `discord.py` 2.x | Best voice support, slash commands |
| Audio fetcher | `yt-dlp` | Most maintained, widest source support |
| Audio encoder | FFmpeg (Opus) | Lossless Discord passthrough |
| Container | Alpine Linux | < 200MB image target |
| Orchestration | Docker Compose | Simple single-node deploy |

---

## 📋 Development Phases

| Phase | Description | Status |
|---|---|---|
| 1 | Project scaffold, Docker, CI skeleton | 🔄 In Progress |
| 2 | Core bot: join/leave, slash commands | ⏳ Pending |
| 3 | Audio pipeline: yt-dlp → FFmpeg → voice | ⏳ Pending |
| 4 | Queue system (add, skip, shuffle, loop) | ⏳ Pending |
| 5 | Multi-VC isolation per guild | ⏳ Pending |
| 6 | Sharding & 100+ server scalability | ⏳ Pending |
| 7 | Polish: embeds, error handling, help | ⏳ Pending |
| 8 | Production hardening, health checks | ⏳ Pending |

---

## 📄 License

MIT — see [LICENSE](LICENSE).
