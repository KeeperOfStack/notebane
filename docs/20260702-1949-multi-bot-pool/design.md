# Multi-Bot Pool — Design

## Environment variable schema

```
BOT_01_TOKEN=<discord bot token>
BOT_01_ID=<discord application id>
BOT_02_TOKEN=...
BOT_02_ID=...
...
BOT_NN_TOKEN=...
BOT_NN_ID=...
```

Gaps in numbering are silently skipped (01, 02, 04 → 3 bots). Numbering starts at 01. Maximum is uncapped — admin decides.

## BotManager class (src/bot_manager.py)

```
BotManager
  .bots: List[BotEntry]          # ordered by number (Bot 1 first)
  .channel_assignments: Dict[voice_channel_id, BotEntry]
  .load_pool(env) -> List[BotEntry]
  .get_bot_for_user(member) -> BotEntry | None
  .assign_bot(voice_channel) -> BotEntry | None  # Bot 1 priority
  .release_bot(voice_channel)
```

`BotEntry`:
```
  number: int          # 1, 2, 3 …
  token: str
  application_id: int
  client: discord.Client
  voice_channel_id: int | None   # None = free
```

## Routing algorithm (per command)

```
1. Is user in a voice channel?
   NO  → existing "not in a voice channel" error
   YES →
     2. Is a bot already in that voice channel?
        YES → route command to that bot
        NO  →
          3. Is any bot free?
             YES → assign_bot() (Bot 1 priority) → join channel → route
             NO  →
               4. N == 1?
                  YES → existing "bot is busy" / generic error
                  NO  → "All bots are busy. Please ask an admin to add an
                         additional bot, or join a channel with a bot already in it."
```

## Single-bot passthrough

When `len(bots) == 1`, the BotManager short-circuits: every command goes directly to Bot 1, no assignment tracking runs, and all existing error messages are used verbatim.

## Bot 1 priority

`assign_bot()` iterates `self.bots` in order (already sorted by number). The first free bot wins. Since Bot 1 is index 0, it is always preferred.

## asyncio multi-client startup

```python
async def start_all():
    await asyncio.gather(*[bot.client.start(bot.token) for bot in bots])
```

SIGTERM handler calls `client.close()` on all clients before process exit.

## Docker Compose env pattern

```yaml
environment:
  - BOT_01_TOKEN=${BOT_01_TOKEN}
  - BOT_01_ID=${BOT_01_ID}
  # Add more pairs as needed:
  # - BOT_02_TOKEN=${BOT_02_TOKEN}
  # - BOT_02_ID=${BOT_02_ID}
```

## Phase Breakdown

### Phase 1 — Env-var pool parser + BotManager scaffold ✅
- `src/notebane/bot_manager.py` — BotManager + BotEntry, fully offline
- `tests/test_bot_manager.py` — 27 unit tests, all passing
- Commit: 8d36159

### Phase 2 — Multi-client startup + graceful shutdown
- Instantiate `discord.Client` per BotEntry
- `asyncio.gather` all `client.start()` calls
- SIGTERM → `client.close()` all clients
- Existing single-bot entrypoint becomes a BotManager wrapper

### Phase 3 — Voice-channel affinity routing
- Each command handler calls `BotManager.get_bot_for_user(member)`
- If bot found → delegate to that bot's handler
- If not → `assign_bot()` → join → delegate
- If user not in VC → existing error

### Phase 4 — Bot 1 priority assignment
- `assign_bot()` sorted iteration (already guaranteed by Phase 1 sort)
- Verify with unit test: Bot 1 picked first, Bot 2 only when Bot 1 is occupied

### Phase 5 — All-bots-busy error + single-bot passthrough
- `len(bots) == 1` guard at BotManager init (disables multi-bot paths)
- `assign_bot()` returns `None` when all occupied
- Handler checks `None` + `len(bots) >= 2` → all-bots-busy message

### Phase 6 — Docker Compose env schema + docs
- `docker-compose.example.yml` with 1/2/3-bot commented slots
- README updated
- Existing `docker-compose.yml` gains commented-out BOT_02 / BOT_03 lines

### Phase 7 — Integration tests + validation
- Offline unit tests for all BotManager paths
- Manual smoke-test checklist (single bot, two bots, all-busy scenario)
