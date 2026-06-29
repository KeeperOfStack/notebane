# Notebane — Design & Implementation Plan

## Goals & Hard Requirements

| Requirement | Approach |
|---|---|
| Ultra-lightweight Docker image | Alpine Linux base, multi-stage build, no dev deps in final image |
| Crystal-clear audio | yt-dlp best audio format → FFmpeg `-c:a copy` Opus passthrough, no re-encoding |
| 100+ simultaneous servers | discord.py AutoSharding; stateless players; future: Redis + horizontal workers |
| Multiple VCs per server | `guild_id + channel_id` keyed player map; fully isolated FFmpegPCMAudio sources |
| Slash commands | discord.py app_commands tree, synced on startup |

---

## Architecture

### Sharding (Scale Answer)

> **Yes, 100s of servers is absolutely possible.** Discord allows a single bot token to operate across thousands of guilds via sharding. Each shard handles a slice of guilds. `discord.py` AutoSharding manages this automatically for a single process. For 10,000+ guilds, you split into multiple processes each with explicit shard IDs — but one process handles hundreds easily.

```
Discord Gateway
   ├─ Shard 0 → guilds [0, 2, 4, ...]
   ├─ Shard 1 → guilds [1, 3, 5, ...]
   └─ Shard N → ...

Each shard is a websocket connection. All run in the same asyncio event loop.
AutoSharding: bot.run() with shard_count=None → discord picks for you.
```

### Multi-VC per Guild

Each `(guild_id, channel_id)` tuple maps to an independent `GuildPlayer` object:
- Own `asyncio.Queue` of tracks
- Own `VoiceClient` connection
- Own playback task
- Fully isolated — one VC can be paused while another plays

```python
self.players: dict[tuple[int, int], GuildPlayer] = {}
```

### Audio Pipeline (Zero Re-encode)

```
yt-dlp resolve URL (best audio, prefer opus/webm)
         │
         ▼
FFmpeg stdin stream → discord.py FFmpegOpusAudio
         │
         ▼
Discord Voice (Opus packets, 48kHz, 128kbps)
```

Key flags:
- `yt-dlp --format bestaudio[ext=webm]/bestaudio` → gets native Opus when available
- `FFmpegOpusAudio(url, bitrate=128)` — Discord caps at 128kbps for standard, 256kbps for boosted servers
- `-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5` on FFmpeg → handles stream hiccups

### Docker Image Strategy

**Multi-stage Alpine build:**

```dockerfile
# Stage 1: builder — install Python deps with pip
FROM python:3.12-alpine AS builder
RUN pip install --prefix=/install discord.py yt-dlp

# Stage 2: final — minimal runtime only
FROM python:3.12-alpine
# Install FFmpeg from Alpine package (not static binary — smaller)
RUN apk add --no-cache ffmpeg
COPY --from=builder /install /usr/local
COPY src/ /app/src/
```

Target: **< 200MB** final image. No gcc, no build tools, no cache in final layer.

---

## Phase Breakdown

### Phase 1 — Scaffold & Docker ✅ In Progress
- `src/` Python package structure
- `Dockerfile` (multi-stage Alpine)
- `docker-compose.yml` with `.env` support
- `.env.example` — `DISCORD_TOKEN`, `APPLICATION_ID`, `LOG_LEVEL`
- `requirements.txt` pinned
- GitHub Actions CI: lint (ruff), Docker build check
- Repo README updated

### Phase 2 — Core Bot Shell
- `AutoShardedBot` subclass with startup logging
- Slash command tree with `/ping`, `/join`, `/leave`
- Guild voice state validation helpers
- `on_ready` shard count log
- `/status` command showing shard info + active players count

### Phase 3 — Audio Pipeline
- `GuildPlayer` class: queue, voice client, play loop
- yt-dlp info extraction (async executor to avoid blocking event loop)
- `YTDLSource` wrapping `FFmpegOpusAudio`
- `/play <url|search>` command
- Stream reconnect flags on FFmpeg
- Format selection: `bestaudio[ext=webm]/bestaudio/best`

### Phase 4 — Queue System
- `/queue` — show current queue (paginated embed)
- `/skip` — skip current track
- `/stop` — stop and clear queue
- `/pause` / `/resume`
- `/shuffle` — randomize queue
- `/loop` — toggle track/queue loop
- `/nowplaying` — rich embed with progress bar (estimated)
- `/remove <index>` — remove specific queue entry

### Phase 5 — Multi-VC Isolation
- `(guild_id, channel_id)` keyed player map
- `/join` targets specific channel or author's current channel
- Cleanup on bot disconnect / VC empty events
- `VoiceStateUpdate` handler: auto-leave when alone in VC
- Stress test: multiple VCs in same guild simultaneously

### Phase 6 — Sharding & Scale Hardening
- Verify AutoSharding works correctly
- Add `SHARD_COUNT` env override for manual control
- `GUILD_LIMIT` env for rate-limit headroom
- yt-dlp cookie support (`YTDL_COOKIEFILE` env) for age-restricted content
- Configurable `FFMPEG_BEFORE_OPTIONS` and `FFMPEG_OPTIONS` env overrides
- Prometheus metrics endpoint (optional, `/metrics`)

### Phase 7 — Polish & UX
- Rich embeds for all responses (thumbnails, colors, footers)
- Error handling: private channel, bot lacks perms, invalid URL, region lock
- `/help` command with categorized command list
- Ephemeral error replies (only visible to caller)
- Rate limit backoff on yt-dlp extraction failures
- Search: `/play <search terms>` → yt-dlp `ytsearch:` → show top 5 choices

### Phase 8 — Production Hardening
- Health check endpoint (tiny HTTP server or Docker HEALTHCHECK)
- Graceful shutdown: drain queues, disconnect VCs
- Log structured JSON to stdout (for log aggregators)
- Docker image published to GHCR
- `docker-compose.prod.yml` with restart policies, log limits
- Resource limits in compose (CPU/memory caps)
- README quick-start verified end-to-end

---

## Environment Variables

| Variable | Required | Default | Description |
|---|---|---|---|
| `DISCORD_TOKEN` | ✅ | — | Bot token from Discord Developer Portal |
| `APPLICATION_ID` | ✅ | — | App ID for slash command sync |
| `LOG_LEVEL` | ❌ | `INFO` | Python log level |
| `SHARD_COUNT` | ❌ | auto | Override shard count |
| `YTDL_COOKIEFILE` | ❌ | — | Path to Netscape cookies file |
| `FFMPEG_BEFORE_OPTIONS` | ❌ | reconnect flags | Extra FFmpeg input options |
| `FFMPEG_OPTIONS` | ❌ | — | Extra FFmpeg output options |

---

## Key Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Bot framework | discord.py 2.x | Best voice + slash command support; well-maintained |
| Audio fetcher | yt-dlp | Most maintained fork; widest source support |
| Audio format | Opus passthrough preferred | Zero re-encode = best quality + lowest CPU |
| Container base | Alpine | Smallest footprint; FFmpeg available via apk |
| State | In-memory only (Phase 1–7) | Simplest; stateless = easy horizontal scale |
| Persistent queue (future) | Redis | Phase 8+ if needed — no premature complexity |
| Commands | Slash commands only | Modern Discord UX; no prefix ambiguity |

---

## Open Questions

- [ ] Do we want Spotify link support? (requires spotify API → yt-dlp search fallback)
- [ ] Do we want SoundCloud / Bandcamp? (yt-dlp supports both, just need testing)
- [ ] Public bot (verified) or self-hosted only? (affects Phase 6 shard limits)
- [ ] Cookie injection for YouTube age-gating / geo-locked content?
