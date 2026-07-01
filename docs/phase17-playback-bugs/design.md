# Phase 17 — Playback Stability Bugs: Stop / Disconnect / Choppy / Zombie

**Status:** Planning complete — implementation pending user sign-off.
**Brain:** `/media/chasm/projects/_cron/notebane/phase17-playback-bugs/manifest.md`

## Summary of what broke and why

Three distinct bugs in the current code, all triggered together by a `/playnext <big playlist>`:

| Phase | Symptom | Root cause | Fix |
|---|---|---|---|
| 17 | Old playlist songs play after `/stop` (zombie) | Background enqueue task is never cancelled when stop runs | Track all bg tasks in player; cancel them all on stop/disconnect |
| 18 | Bot doesn't leave VC after `/stop` | `player.stop()` doesn't call `voice_client.disconnect()` | `/stop` → `player.disconnect()` + remove from manager |
| 19 | Audio choppy/stuttery while playlist loads | SEM_LIMIT=4 parallel yt-dlp+deno processes saturate CPU/network | Lower SEM_LIMIT 4→1 |
| 20 | Playlist coverage ceiling not communicated | No warning when at ~222-entry unauthenticated limit | Add UX warning message |

## Detailed design

See `manifest.md` in the brain folder for the full root-cause analysis and code locations.

### Phase 18 — `/stop` must disconnect

`player.stop()` drains queue + stops FFmpeg but does NOT call `voice_client.disconnect()`.
Command `/stop` calls `player.stop()`. Should call `player.disconnect()` instead.
Additionally: after disconnect, remove the player from `GuildPlayerManager` so the next `/play` gets a clean slate.

**Code change:**
- `src/notebane/cogs/music.py` — `/stop` command: call `await player.disconnect()` instead of `await player.stop()`; then call `self.players.remove(player.guild_id, player.channel_id)`.
- Same for the `NowPlayingView.stop_btn` button.

### Phase 17 — Zombie bg task cancellation

`_enqueue_playlist_bg` is spawned as a fire-and-forget `create_task(...)` with no reference.
When `stop()` runs, the bg task keeps putting tracks into the queue.

**Code change in `player.py`:**
```python
self._bg_tasks: set[asyncio.Task] = set()
```

**Code change in `cogs/music.py`:**
```python
task = asyncio.get_event_loop().create_task(self._enqueue_playlist_bg(...))
player._bg_tasks.add(task)
task.add_done_callback(player._bg_tasks.discard)
```

**Code change in `player.stop()` / `player.disconnect()`:**
```python
for t in list(self._bg_tasks):
    t.cancel()
self._bg_tasks.clear()
```

### Phase 19 — SEM_LIMIT 4→1

```python
# src/notebane/cogs/music.py line 260
SEM_LIMIT = 1   # was 4; one resolve at a time so audio is never starved
```

One yt-dlp call at a time in the background. Audio pipeline always gets first priority on CPU/network.
Playlist loading is sequential (roughly 1-2s per track) but the playing song is unaffected.

### 17d — UX warning at ceiling

After flat-extract completes, if `len(entries) >= 200`:
```python
if len(entries) >= 200 and not cookiefile:
    # warn in completion message
```

## Phases

| Phase | Title | Type |
|---|---|---|
| 17 | Zombie bg task cancellation | bug fix |
| 18 | Stop → disconnect + remove from manager | bug fix |
| 19 | SEM_LIMIT 4→1 (no audio starvation) | perf/stability |
| 20 | Large playlist UX warning | UX |
| 21 | Manual tests + deploy | validation |
