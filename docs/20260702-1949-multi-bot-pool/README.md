# Multi-Bot Pool — Overview

**Status:** Planning  
**Branch:** `feature/multi-bot-pool` (not yet created)

## What this adds

Notebane can now run **N Discord bots in parallel** inside a single container. Each voice channel in the guild gets its own bot. The admin configures a pool by adding numbered token pairs to their `.env` / Compose file:

```
BOT_01_TOKEN=...
BOT_01_ID=...
BOT_02_TOKEN=...
BOT_02_ID=...
# add as many as needed
```

The container auto-detects how many bots are configured and handles everything else automatically.

## Key behaviors

| Scenario | Behavior |
|---|---|
| Only 1 bot configured | Identical UX to the classic single-bot Notebane |
| User runs a command | Routed to the bot already in their voice channel |
| No bot in user's channel | Least-occupied bot joins (Bot 1 preferred) |
| All bots busy (N≥2) | "All bots are busy…" error with admin guidance |
| User not in a voice channel | Same error as current single-bot |

## Bot 1 preference

Bot 1 is always assigned first when it is free. It will occupy the most voice channels.

## Phases

See [`design.md`](./design.md) for full phase breakdown.

## Related files

- `docker-compose.example.yml` — template with 1/2/3-bot slots (Phase 6)
- `src/bot_manager.py` — central pool class (Phase 1)
