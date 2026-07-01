# Phase 17 — Playback Stability Manual Test Protocol

**Target:** `notebane-notebane-1` on Kratos, latest image.

These are the tests BananaDragon runs in Discord to confirm each fix landed correctly. Run them in order — each test builds on the last.

---

## Prerequisites (run once before starting)

```bash
# 1. Container is running and healthy
docker ps --filter name=notebane --format 'Status: {{.Status}}'
# Expected: "Up N minutes (healthy)"

# 2. Watch logs in a separate terminal for the whole session
docker logs -f notebane-notebane-1 | grep -E 'play_latency|ERROR|bg_task|disconnect|stop|zombie'
```

---

## Test 1 — `/stop` disconnects the bot from VC

**Setup:** Join a voice channel. Run `/play <any single song URL>`. Wait for the bot to join and start playing.

**Steps:**
1. Run `/stop` (or click the ⏹ stop button on the Now Playing embed).

**Expected:**
- Bot sends "⏹ Stopped and cleared the queue."
- **Bot leaves the voice channel immediately.** ← THIS IS THE FIX

**Failure (pre-fix):** Bot says "Stopped" but stays in the VC.

---

## Test 2 — Queue is truly clear after `/stop`

**Setup:** Continuation of Test 1 (or fresh start).

**Steps:**
1. Play a single song.
2. Add another song with `/play <second single URL>` (queue should show 1 track queued).
3. Run `/stop`.
4. Run `/queue`.

**Expected:**
- Bot is not in VC.
- `/queue` says "I'm not in a voice channel" (or "Nothing queued" if it doesn't require VC).

---

## Test 3 — No zombie playlist after `/stop` (THE BIG ONE)

**Setup:** Join VC. Have a song already playing.

**Steps:**
1. Run `/play <single song URL>`. Let it start playing.
2. Run `/playnext https://youtube.com/playlist?list=PL35D5A8D7557E59E0` (the big playlist). Wait for the "Playlist Added" embed.
3. Immediately run `/stop`.
4. Wait 5 seconds.
5. Run `/play <a completely different single song URL>` — something distinct you'll recognise.
6. Let it play to completion (or skip with `/skip`).
7. After it finishes — does ANYTHING else start playing automatically?

**Expected:**
- Only your single song plays.
- After it ends: silence. Bot stays in VC idle (or disconnects on idle timeout).
- The playlist songs from step 2 **never play**.

**Failure (pre-fix):** After your single song, the bot starts playing songs from the big playlist that was "stopped".

---

## Test 4 — Adding a playlist doesn't make the current song choppy

**Setup:** Play a single song. Let it run for 30+ seconds so it's streaming smoothly.

**Steps:**
1. While a song is actively playing with clean audio, run `/play https://youtube.com/playlist?list=PL35D5A8D7557E59E0`.
2. Listen carefully to the currently playing song for the next 60 seconds.
3. Also check logs: `docker logs notebane-notebane-1 --since 3m | grep -E 'ERROR|playback error'`

**Expected:**
- Currently playing song plays cleanly throughout. Zero stuttering or glitches.
- Playlist loads silently in the background.
- Eventually: "✅ **playlist title** — N track(s) loaded" appears in Discord.

**Failure (pre-fix):** Song becomes choppy within seconds of adding the playlist.

---

## Test 5 — `/stop` during active playlist load still kills loading

**Setup:** Song playing. Add big playlist.

**Steps:**
1. Play a song.
2. Add the big playlist with `/play`.
3. While the "Loading…" message is up (within first 10 seconds), run `/stop`.
4. Watch Discord — no more "track(s) loaded" message should arrive.
5. Bot should leave VC.

**Expected:**
- Background loading stops dead.
- No more completion messages.
- No songs play after stop.

---

## Test 6 — Fresh `/play` after stop works normally

**Setup:** Just ran `/stop` (bot not in VC).

**Steps:**
1. Join a voice channel.
2. Run `/play <single song URL>`.
3. Measure time from command → bot in VC + audio playing.

**Expected:**
- Load time < 3 seconds.
- Audio plays cleanly, no choppy start.

**Failure (pre-fix):** Very long load time after a previous stop.

---

## Reporting back

After each test, paste:
1. Pass ✅ or Fail ❌
2. What you saw/heard
3. This log snippet: `docker logs notebane-notebane-1 --since 5m | tail -30`
