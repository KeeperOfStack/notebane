# Multi-Bot Pool — Manual Smoke-Test Checklist

This document is for the admin running final validation before marking the
feature production-ready.  Three scenarios are covered.

---

## Prerequisites

1. You have two (or three) Discord bot applications created in the Developer Portal,
   each with its own token and application ID.
2. All bots have been invited to your test guild with the standard OAuth2 scopes
   (`bot`, `applications.commands`) and the **Connect + Speak** voice permissions.
3. The container is running with the multi-bot env vars set:
   ```
   BOT_01_TOKEN=...  BOT_01_ID=...
   BOT_02_TOKEN=...  BOT_02_ID=...
   ```
4. You have two Discord accounts (or devices) to simulate two different users in
   two different voice channels simultaneously.

---

## Scenario 1 — Single-bot mode (N=1 or guild has 1 bot invited)

**Goal:** Confirm the existing UX is completely unchanged.

| Step | Action | Expected |
|---|---|---|
| 1 | Start with only `BOT_01_TOKEN` + `BOT_01_ID` set | Container starts, Bot 1 logs in |
| 2 | `/join` in a voice channel | Bot 1 joins ✅ |
| 3 | `/play <song>` | Plays normally ✅ |
| 4 | `/leave` | Bot 1 leaves, queue cleared ✅ |
| 5 | `/play` while Bot 1 is already in a different channel | Same "already in another channel" error as before ✅ |
| 6 | Check logs | No "multi-bot" routing messages — single-bot path only ✅ |

---

## Scenario 2 — Two bots, concurrent voice channels

**Goal:** Confirm Bot 1 takes the first channel, Bot 2 takes the second.

| Step | Action | Expected |
|---|---|---|
| 1 | Start container with `BOT_01` + `BOT_02` | Both bots log "ready" in logs |
| 2 | User A joins Voice Channel 1, runs `/join` | Bot 1 joins Voice Channel 1 ✅ |
| 3 | User B joins Voice Channel 2, runs `/join` | Bot 2 joins Voice Channel 2 ✅ |
| 4 | User A runs `/play <song>` in VC 1 | Bot 1 plays in VC 1 ✅ |
| 5 | User B runs `/play <song>` in VC 2 | Bot 2 plays in VC 2 ✅ |
| 6 | User A runs `/skip` | Only VC 1 is affected ✅ |
| 7 | User A runs `/leave` | Bot 1 leaves VC 1; Bot 2 continues in VC 2 ✅ |
| 8 | User A joins Voice Channel 3, runs `/join` | Bot 1 (now free) rejoins as Bot 1 ✅ |
| 9 | User B runs `/leave` | Bot 2 leaves VC 2 ✅ |

---

## Scenario 3 — All bots busy (N=2, both occupied)

**Goal:** Confirm the correct "all bots busy" error with no crash.

| Step | Action | Expected |
|---|---|---|
| 1 | Both bots are in separate VCs (repeat Scenario 2 steps 1–5) | Bot 1 in VC 1, Bot 2 in VC 2 |
| 2 | User C joins Voice Channel 3, runs `/join` | ❌ "All bots are busy. Please ask an admin to add an additional bot, or join a channel that already has a bot in it." |
| 3 | User C tries `/play` | Same error ✅ |
| 4 | User A runs `/leave` (frees Bot 1) | Bot 1 released |
| 5 | User C runs `/join` again | Bot 1 now claims VC 3 ✅ |

---

## Scenario 4 — Per-guild filtering (N=3 container, guild invited 2)

**Goal:** Confirm a guild with 2 of 3 bots invited behaves as a 2-bot guild.

| Step | Action | Expected |
|---|---|---|
| 1 | Start with `BOT_01` + `BOT_02` + `BOT_03` in container | All 3 bots log ready |
| 2 | Invite only Bot 1 and Bot 2 to the test guild | Bot 3 is NOT in the guild |
| 3 | Fill both Bot 1 and Bot 2 channels | Both occupied |
| 4 | Third user tries `/join` | "All bots are busy" error ✅ |
| 5 | Check logs | Bot 3 was never assigned or mentioned for this guild ✅ |

---

## What to check in logs during each scenario

```bash
docker logs notebane -f --tail 50
```

Key log lines to watch for:

| Log message | Meaning |
|---|---|
| `Bot 1 ready \| user=... \| guilds=...` | Bot 1 connected |
| `Bot 2 ready \| user=... \| guilds=...` | Bot 2 connected |
| `Assigned Bot 1 to voice channel ... (guild ...)` | Bot 1 took a channel |
| `Assigned Bot 2 to voice channel ... (guild ...)` | Bot 2 took a channel |
| `Released Bot N from voice channel ...` | Bot freed on leave |
| `All N bots busy — guild=... channel=... rejected` | Busy error fired |

---

## Pass criteria

All four scenarios complete without:
- Any Python traceback in the logs
- Any "Internal error" or "bot client not initialised" messages
- Audio cutting out during concurrent playback
- Commands affecting the wrong bot's channel
