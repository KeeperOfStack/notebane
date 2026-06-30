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

- [🚀 Deployment Guide](docs/deployment.md) — Docker run, Portainer, and Compose setup
- [📋 Command Reference](docs/commands.md) — all slash commands and what they do
- [🏛️ Design & Architecture](docs/notebane/design.md) — full design, phase breakdown, internals

---

## 🚀 Quick Start

```bash
docker run -d \
  --name notebane \
  --restart unless-stopped \
  -e DISCORD_TOKEN=*** \
  -e APPLICATION_ID=your_application_id_here \
  -e LOG_FORMAT=json \
  --log-driver json-file \
  --log-opt max-size=10m \
  --log-opt max-file=3 \
  ghcr.io/keeperofstack/notebane:latest
```

See the full [Deployment Guide](docs/deployment.md) for Portainer and advanced options.

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
