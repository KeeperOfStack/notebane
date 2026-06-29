# Notebane — Developer Docs

This folder contains the technical design and implementation notes for the Notebane Discord music bot.

## Files

- [`design.md`](design.md) — Architecture, phase breakdown, stack decisions, API contracts
- This `README.md` — orientation for new contributors

## Project Overview

Notebane is a self-hosted Discord music bot with these hard requirements:
- **Ultra-lightweight Docker image** (Alpine, target < 200MB)
- **Crystal-clear audio** (highest quality yt-dlp stream → FFmpeg Opus passthrough)
- **100+ concurrent guilds** (Discord AutoSharding, stateless player sessions)
- **Multiple simultaneous voice channels per guild** (per-VC player isolation)

## Key Conventions

- All player state lives in-memory per shard — stateless for easy horizontal scaling
- No disk writes for audio — direct stream URL → FFmpeg → Discord voice
- Slash commands only (no prefix commands)
- All config via environment variables — no hardcoded tokens

## Brain Folder

Hermes session brain: `/media/chasm/projects/_cron/notebane-20260629/`
