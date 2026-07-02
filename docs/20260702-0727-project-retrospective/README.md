# Notebane — Project Retrospective & Developer Reference

**Date:** 2026-07-02  
**Status:** Production-ready — deployed and tested

This document is the canonical reference for anyone picking up Notebane development. It consolidates everything learned across all phases — what was built, what broke, how it was fixed, and what to watch out for.

---

## What Was Built

A lightweight, self-hosted Discord music bot with:

- Crystal-clear audio via yt-dlp + FFmpeg Opus passthrough (zero re-encoding)
- Instant playlist loading — 500-track playlists start playing in ~2.5s via JIT stub resolution
- Per-guild, per-voice-channel isolated players — multiple VCs per server simultaneously
- Full queue system — add, skip, previous, shuffle, loop, remove, undo, redo, restore
- User playlists — save, load, edit personal playlists (25 per user, 500 tracks each)
- Interactive Now Playing controls — ⏮/⏸/⏭/⏹ buttons on every track
- YouTube auth via per-guild `/ytlogin` cookie upload
- Auto-updating yt-dlp every 12 hours — container runs indefinitely without restart
- AutoSharding — supports 100+ concurrent servers from a single process
- PUID/PGID entrypoint — zero host-side permission setup required

---

## Phase History (abbreviated)

| Phases | What shipped |
|---|---|
| Phases 1–8 | Scaffold, voice, yt-dlp, FFmpeg, queue, Docker, GHCR |
| 9 | Playlist hardening, Now Playing ⏮/⏸/⏭/⏹ buttons |
| 10 | Per-guild YouTube auth (`/ytlogin`), Deno + yt-dlp-ejs solver |
| 11–12 | Smart-cookie policy, playlist coverage measurement |
| 13 | Single-URL fast path — 1 yt-dlp call instead of 2 |
| 14 | Parallel playlist resolve — first track in ~1s |
| 17–21 | Playback stability — zombie tasks, stop/disconnect, SEM_LIMIT, UX warnings |
| — | Undo/redo/restore with SQLite snapshot persistence |
| — | User playlists CRUD with interactive editor |
| — | JIT stub system — instant enqueue, resolve at play time |
| — | `/previous` + ⏮ button with 20-track session history |
| — | Deployment hardening — PUID/PGID, named volumes, health check fix |
| — | YouTube mix handling — `strip_mix_context()`, `/playytmix`, `/playytmixnext` |
| — | Undo message clarity — "Removed N tracks. Queue restored to M." |

---

## Architecture

### Audio path
```
/play command → yt-dlp (executor thread) → stream URL
             → FFmpeg subprocess → Opus frames
             → discord.py VoiceClient → Discord voice servers
```

### Player model
- One `GuildPlayer` per `(guild_id, channel_id)` — stored in `GuildPlayerManager`
- `_play_loop()` — asyncio task: dequeues stubs → JIT-resolves → streams → records history
- `_history` deque (maxlen=20) — powers `/previous`
- `_undo_stack` / `_redo_stack` deques (maxlen=10) — powers `/undo` / `/redo`
- `_bg_tasks` set — background loaders tracked and cancelled on stop/undo/redo

### Concurrency
- Pure asyncio — no threads in application code
- yt-dlp calls: `loop.run_in_executor(None, fn)` — offloaded to default thread pool
- `_after_play`: called from discord.py's thread — only `asyncio.Event.set()` here (thread-safe)
- SQLite: synchronous on event loop — acceptable for current query sizes

### Database
- Single file: `/data/notebane.db` (WAL mode)
- `restore_db.py` — queue snapshots, 7-day TTL
- `playlist_db.py` — user playlists + tracks (CASCADE delete)

---

## Critical Pitfalls

### YouTube / yt-dlp
| Pitfall | Fix |
|---|---|
| Deno installed but no audio | `yt-dlp-ejs` package also required — Deno is the runtime, ejs is the script |
| Cookies expire immediately | Must export from **private/incognito** window; close WITHOUT logging out |
| yt-dlp clobbers cookiefile | Store original at `.orig.txt`; restore to `.txt` before each yt-dlp call |
| "Sign in to confirm" not actionable | Pin to nightly yt-dlp — stable buries the real error |
| Playlist coverage low | Use `youtubetab:skip=webpage` — hits internal API, ~2× coverage |
| `list=RD*` URL loads entire mix in `/play` | Apply `strip_mix_context()` before routing — strips mix params when `v=` present; use `/playytmix` to load intentionally |

### Docker / Deployment
| Pitfall | Fix |
|---|---|
| Permission denied on `/cookies` or `/data` | Use PUID/PGID entrypoint — `su-exec` + `shadow` package on Alpine |
| `docker run` volumes not created | Named volumes must be pre-created with `docker volume create`; compose auto-creates |
| `external: true` in Portainer | Causes deploy failure if volumes don't exist; omit it — let Portainer create them |
| Health check always passes | Old `|| exit 0` pattern; now honest skip when `METRICS_PORT` unset |
| Resource limits cause stutter | Removed — FFmpeg is external, Python is async; limits only hurt |

### Python / asyncio
| Pitfall | Fix |
|---|---|
| `record_mutation()` called after mutation | Must be called BEFORE; undo restores to pre-call state |
| Queue rebuild blocking | Drain with `get_nowait()` loop, then `put_nowait()` to refill |
| Stale bg loaders after undo/redo | Cancel all `_bg_tasks` before replacing queue |
| `_after_play` thread safety | Only `Event.set()` — no awaits, no queue ops from that callback |
| Undo "X tracks restored" is misleading | Shows the restored snapshot size, not what was removed; show "Removed N, restored to M" |

### CI / Lint
| Pitfall | Fix |
|---|---|
| `import time` in `playlists.py` | Unused — removed |
| `from dataclasses import asdict` in `playlist_db.py` | Unused — removed |
| Debug `log.info` in `auth.py` `on_message` | Fired on every message — removed before production |

---

## Key Files

| File | Purpose |
|---|---|
| `src/notebane/__main__.py` | Bot lifecycle, logging setup, shutdown |
| `src/notebane/player.py` | GuildPlayer, play loop, history, undo/redo |
| `src/notebane/ytdl.py` | Async yt-dlp wrapper (executor-offloaded) |
| `src/notebane/ytdl_updater.py` | 12h auto-upgrade loop |
| `src/notebane/cookies.py` | Per-guild cookie file CRUD + validation |
| `src/notebane/restore_db.py` | SQLite queue snapshot persistence |
| `src/notebane/playlist_db.py` | SQLite user playlist persistence |
| `src/notebane/metrics.py` | Optional Prometheus `/metrics` + `/health` |
| `src/notebane/cogs/music.py` | All playback + queue commands + NowPlayingView |
| `src/notebane/cogs/voice.py` | Voice connection commands + helpers |
| `src/notebane/cogs/playlists.py` | User playlist commands + interactive editor |
| `src/notebane/cogs/search.py` | `/search` interactive dropdown |
| `src/notebane/cogs/auth.py` | `/ytlogin` + cookie attachment listener |
| `src/notebane/cogs/core.py` | `/ping` `/status` `/help` |
| `entrypoint.sh` | PUID/PGID remapping → su-exec privilege drop |
| `Dockerfile` | Two-stage Alpine build |
| `docker-compose.prod.yml` | Production compose — named volumes, GHCR image |

---

## Future Development

### Near-term
- **`asyncio.to_thread()` for SQLite** — current sync calls are fine but executor-wrapping would be cleaner at scale
- **Phase 15 — pre-warm voice connection** — deferred; revisit if `/play` latency regresses
- **Queue auto-restore on rejoin** — `restore_db` already saves snapshots; could load automatically when bot joins a VC

### Features
- **Web dashboard** — live queue view, player controls, guild stats
- **Spotify URL support** — resolve Spotify → YouTube via title+artist search
- **Lyrics integration** — `/lyrics` via a lyrics API
- **Audio effects** — bass boost, speed, nightcore via FFmpeg filter chain
- **Radio mode** — continuous play from seed track via YouTube recommendations
- **Per-user queue slots** — optional isolation mode

### Infrastructure
- **Semver tagging** — currently pins to `:latest`; tag releases for reproducible deploys
- **Backup script** — `docker volume` export for `notebane_data` (SQLite + cookies)
