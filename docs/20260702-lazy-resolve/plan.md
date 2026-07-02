# Phase 6 — Lazy Stream Resolution (Instant Playlist Queuing)

**Goal:** Playlist tracks appear in the queue instantly (flat metadata only). Stream URLs are resolved just-in-time in the play loop, immediately before each track plays.

**Architecture:**
- `Track` gains a `resolved: bool` flag. Stub tracks have `url == webpage_url` and `resolved=False`.
- `_play_loop` detects an unresolved track and calls `resolve()` before opening FFmpeg.
- `_enqueue_playlist_bg` is replaced with `_enqueue_playlist_stubs` — dumps all flat entries as stubs in one synchronous pass (no yt-dlp calls, essentially instant).
- Pre-resolve: while a track plays, resolve the *next* unresolved track in the background so it's ready before it's needed.
- `/createlist` no longer needs `wait_for_bg_tasks` — stubs are in the queue immediately.
- `/loadlist` stub loader follows the same pattern.

**Constraints (must not change):**
- SEM_LIMIT=1 for pre-resolve (don't starve audio stream)
- No new packages
- Undo/redo/restore still work (stubs are valid Track objects)
- `/queue` embed shows stub tracks with title + duration (may be None until resolved)

---

## Phase 6 Task Breakdown

---

### Task 1 — Add `resolved` flag to `Track`

**File:** `src/notebane/player.py`

Add `resolved: bool = True` to the `Track` dataclass (default True so all existing single-track code paths are unaffected). Add a `make_stub` classmethod that constructs an unresolved Track from a flat entry dict.

```python
@dataclass
class Track:
    title: str
    url: str          # direct stream URL when resolved; webpage_url when stub
    webpage_url: str  # human-facing URL (always set)
    duration: int | None = None
    thumbnail: str | None = None
    requester: str = "unknown"
    http_headers: dict[str, str] | None = None
    resolved: bool = True   # False = stub; url not yet a stream URL

    @classmethod
    def make_stub(cls, entry: dict, requester: str = "unknown") -> "Track":
        """Build an unresolved Track from a yt-dlp flat playlist entry.

        entry keys used: webpage_url / url, title, duration, thumbnails/thumbnail.
        """
        webpage_url = entry.get("webpage_url") or entry.get("url") or ""
        title = entry.get("title") or entry.get("id") or "Unknown title"
        duration = entry.get("duration")
        thumbnail = (
            entry.get("thumbnail")
            or (entry.get("thumbnails") or [{}])[-1].get("url")
        )
        return cls(
            title=title,
            url=webpage_url,          # placeholder until resolved
            webpage_url=webpage_url,
            duration=duration,
            thumbnail=thumbnail,
            requester=requester,
            resolved=False,
        )
```

**Verify:** `python -c "from notebane.player import Track; t = Track.make_stub({'webpage_url':'https://youtu.be/x','title':'T'}); assert not t.resolved; print('ok')"` — prints `ok`.

**Commit:** `feat(player): add Track.resolved flag + make_stub classmethod`

---

### Task 2 — Play loop: resolve stub before playing

**File:** `src/notebane/player.py` — `_play_loop` method

After `track = await asyncio.wait_for(self.queue.get(), ...)`, before the FFmpeg block, add a JIT resolve step:

```python
# JIT-resolve stub tracks: fetch the real stream URL now.
if not track.resolved:
    try:
        from notebane.ytdl import resolve as ytdl_resolve
        cookiefile = getattr(self, "_cookiefile", None)
        track = await ytdl_resolve(
            track.webpage_url,
            requester=track.requester,
            cookiefile=cookiefile,
        )
    except Exception:
        log.exception(
            "[guild=%d] JIT resolve failed for %r — skipping",
            self.guild_id, track.webpage_url,
        )
        self.current = None
        continue
```

Also add `self._cookiefile: str | None = None` to `GuildPlayer.__init__` so the play loop can pass cookies (set by music cog when creating the player).

**Verify:** Existing single tracks still play (resolved=True skips the JIT block). No import cycle — `ytdl` does not import `player`.

**Commit:** `feat(player): JIT-resolve stub tracks in play loop`

---

### Task 3 — Pre-resolve: look-ahead resolver

**File:** `src/notebane/player.py` — add `_presolve_next` helper and call it from `_play_loop`

While a track is playing, kick off a single background resolve for the next unresolved track in the queue so it's ready by the time the current track finishes. This keeps SEM_LIMIT=1 intent (only one resolve at a time) while hiding latency.

```python
def _start_presolve(self) -> None:
    """Resolve the first unresolved stub in the queue in the background.

    Called once after playback starts on each track. Only one presolve
    runs at a time — if one is already running, does nothing.
    """
    # Don't double-spawn
    if any(getattr(t, "_is_presolve", False) for t in self._bg_tasks):
        return

    dq = list(self.queue._queue)  # type: ignore[attr-defined]
    for i, t in enumerate(dq):
        if not t.resolved:
            task = asyncio.get_event_loop().create_task(
                self._presolve_at(i, t)
            )
            task._is_presolve = True  # type: ignore[attr-defined]
            self._bg_tasks.add(task)
            task.add_done_callback(self._bg_tasks.discard)
            return

async def _presolve_at(self, idx: int, stub: Track) -> None:
    """Resolve `stub` and swap it back into the queue at `idx`."""
    try:
        from notebane.ytdl import resolve as ytdl_resolve
        resolved = await ytdl_resolve(
            stub.webpage_url,
            requester=stub.requester,
            cookiefile=getattr(self, "_cookiefile", None),
        )
        # Swap in-place if the stub is still at idx (not mutated by undo/skip)
        dq = self.queue._queue  # type: ignore[attr-defined]
        dq_list = list(dq)
        if idx < len(dq_list) and dq_list[idx].webpage_url == stub.webpage_url and not dq_list[idx].resolved:
            dq_list[idx] = resolved
            dq.clear()
            dq.extend(dq_list)
    except Exception:
        log.debug("[guild=%d] presolve failed for %r — play loop will JIT resolve", self.guild_id, stub.webpage_url)
```

In `_play_loop`, right after `self.voice_client.play(source, after=self._after_play)`, call:
```python
self._start_presolve()
```

**Commit:** `feat(player): pre-resolve next stub while current track plays`

---

### Task 4 — Replace `_enqueue_playlist_bg` with instant stub loader

**File:** `src/notebane/cogs/music.py`

Rename `_enqueue_playlist_bg` to `_enqueue_playlist_bg_LEGACY` (keep for reference during this task, delete in Task 5). Add a new synchronous helper:

```python
def _enqueue_playlist_stubs(
    self,
    player: GuildPlayer,
    entries: list[dict],
    requester: str,
    *,
    insert_next: bool = False,
) -> int:
    """Dump all flat playlist entries as unresolved stub Tracks instantly.

    No yt-dlp calls. Returns the number of tracks enqueued.
    """
    stubs = [Track.make_stub(e, requester=requester) for e in entries]
    if not stubs:
        return 0
    if insert_next:
        player.insert_next(stubs)
    else:
        for stub in stubs:
            player.queue.put_nowait(stub)
    return len(stubs)
```

Then in the `/play` playlist branch (around line 446), replace:
```python
_task = asyncio.get_event_loop().create_task(
    self._enqueue_playlist_bg(...)
)
player._bg_tasks.add(_task)
_task.add_done_callback(player._bg_tasks.discard)
```
with:
```python
count = self._enqueue_playlist_stubs(
    player, entries, requester=interaction.user.display_name
)
log.info("[guild=%d] Queued %d stubs instantly", player.guild_id, count)
```

Do the same replacement in the `/playnext` playlist branch (insert_next=True).

Also set `player._cookiefile = cookiefile` right after `player = await self._ensure_player(interaction)` in both `/play` and `/playnext`.

**Verify:** After `/play <playlist>`, the Discord response shows instantly. `docker logs notebane-notebane-1 | tail -5` shows "Queued N stubs instantly".

**Commit:** `feat(music): instant stub enqueue for playlists — drop _enqueue_playlist_bg`

---

### Task 5 — Remove legacy bg resolver + clean up `wait_for_bg_tasks`

**Files:** `src/notebane/cogs/music.py`, `src/notebane/cogs/playlists.py`, `src/notebane/player.py`

1. Delete `_enqueue_playlist_bg_LEGACY` from `music.py`
2. In `playlists.py` `/createlist`: remove the `if player._bg_tasks: wait_for_bg_tasks()` block and the ⏳ waiting message — stubs are in queue instantly, no wait needed
3. In `playlists.py` `_enqueue_playlist_stubs_from_saved` (the `/loadlist` bg loader): replace it with the same stub pattern — `Track.make_stub` from saved playlist rows (use `webpage_url` as the url, title/duration from DB)
4. `wait_for_bg_tasks` on `GuildPlayer` — keep it (pre-resolve tasks use `_bg_tasks`), but remove the `_bg_tasks` wait from `/createlist`

For `/loadlist` stub conversion, saved playlist rows are `SavedTrack` objects with `.webpage_url`, `.title`, `.duration_seconds`, `.thumbnail_url`. Build stubs:
```python
from notebane.player import Track
stubs = [
    Track(
        title=t.title,
        url=t.webpage_url,
        webpage_url=t.webpage_url,
        duration=t.duration_seconds,
        thumbnail=t.thumbnail_url,
        requester=requester,
        resolved=False,
    )
    for t in tracks
]
if insert_next:
    player.insert_next(stubs)
else:
    for stub in stubs:
        player.queue.put_nowait(stub)
```

**Commit:** `refactor: remove legacy bg resolver, instant stub load for loadlist too`

---

### Task 6 — `/queue` embed: handle unresolved stubs gracefully

**File:** `src/notebane/cogs/music.py` — `_queue_embed` function

Stub tracks have `resolved=False` and `duration` may be `None`. The embed already handles `None` duration via `track.duration_fmt()` (returns `"∞"`). But the display should optionally show a spinner for unresolved tracks.

In the track line format, add a `⟳` prefix when `not track.resolved`:

```python
status = "" if track.resolved else "⟳ "
line = f"`{i+1}.` {status}**[{title}]({track.webpage_url})** — `{track.duration_fmt()}`"
```

This gives users visual feedback that these tracks haven't had their stream URL fetched yet (they will be, just before play).

**Commit:** `feat(embeds): show ⟳ spinner for unresolved stub tracks in /queue`

---

### Task 7 — Deploy + smoke test

```bash
cd /media/chasm/projects/notebane
python -m py_compile src/notebane/player.py src/notebane/cogs/music.py src/notebane/cogs/playlists.py
docker compose build
docker compose stop notebane
docker compose up -d notebane
sleep 5
docker ps --filter name=notebane --format "{{.Names}} {{.Status}}"
docker logs notebane-notebane-1 --tail 20
```

**Manual test checklist:**
- [ ] `/play <263-track-playlist>` — response appears instantly, "263 tracks queued"
- [ ] Bot joins VC and begins playing track 1 within ~5s (JIT resolve)
- [ ] `/queue` shows all 263 tracks immediately, ⟳ on unresolved ones
- [ ] `/createlist testy` immediately after `/play` — saves all 263 (no wait message)
- [ ] `/playnext <playlist>` — inserts stubs at front instantly
- [ ] Track 2 plays cleanly after track 1 (pre-resolve worked)
- [ ] `/stop` then `/restore` — stubs restore correctly (webpage_url preserved)

**Commit:** `chore: deploy lazy-resolve (phase 6)`

---

## Key Design Decisions

| Decision | Rationale |
|---|---|
| `resolved=True` default | All existing single-track paths need zero changes |
| JIT resolve in play loop | Play loop is the only place that needs the stream URL — resolving earlier is waste |
| Pre-resolve look-ahead | Hides JIT latency — next track resolves while current plays |
| Stub swap in `_presolve_at` | Avoids redundant resolve() if play loop hits before presolve finishes (JIT handles it gracefully anyway) |
| Remove `wait_for_bg_tasks` from createlist | Not needed — stubs land in queue synchronously |
| Keep `wait_for_bg_tasks` method | Pre-resolve tasks still use `_bg_tasks`; undo/stop still cancel them |

## Files Changed

- `src/notebane/player.py` — Track.make_stub, resolved flag, _play_loop JIT, _start_presolve, _presolve_at, _cookiefile attr
- `src/notebane/cogs/music.py` — _enqueue_playlist_stubs (replaces _enqueue_playlist_bg), set player._cookiefile, queue embed spinner
- `src/notebane/cogs/playlists.py` — /createlist removes wait, /loadlist becomes instant stub load
