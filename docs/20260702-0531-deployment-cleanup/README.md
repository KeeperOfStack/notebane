# Notebane — Deployment Cleanup

**Status:** Complete ✅
**Date:** 2026-07-02
**Phase:** Pre-deploy cleanup after full application review

---

## What Was Fixed

Three minor concerns found during a full code review before remote test deployment.

### 1. Debug log spam (`auth.py`)

`on_message` was logging every single message across every guild — a debug leftover from development that had no place in production. Stripped cleanly; all functional guards remain.

### 2. Health check false positive (`Dockerfile`)

The old health check always exited `0` (healthy) whether or not `METRICS_PORT` was set:

```sh
# old — always passed
curl ... || exit 0
```

Fixed to skip cleanly when metrics are disabled, and actually fail when they're enabled and the endpoint doesn't respond:

```sh
# new — honest
[ -z "${METRICS_PORT}" ] && exit 0; curl -fs http://127.0.0.1:${METRICS_PORT}/health
```

### 3. Resource limits removed (compose + deployment docs)

`deploy.resources` CPU/memory caps removed from `docker-compose.prod.yml` and the Portainer stack example after the full review confirmed the application is genuinely lightweight and well-built — pure asyncio, external FFmpeg subprocess, executor-offloaded yt-dlp, minimal SQLite I/O. Caps add bottleneck risk with no benefit on a well-architected app.

---

## Files Changed

| File | Change |
|---|---|
| `src/notebane/cogs/auth.py` | Removed 4 debug `log.info` calls from `on_message` |
| `Dockerfile` | Health check logic corrected |
| `docker-compose.prod.yml` | `deploy.resources` block removed |
| `docs/deployment.md` | Portainer stack example cleaned; prerequisites simplified |
| `docs/create-your-bot.md` | New: full bot creation + invite guide |
| `README.md` | Bot guide added as top Documentation link |
