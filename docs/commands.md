# 📋 Notebane — Command Reference

All commands are Discord slash commands. Type `/` in any channel to see them with autocomplete.

---

## 🔊 Voice

| Command | Arguments | Description |
|---|---|---|
| `/join` | `[channel]` | Join a voice channel. Defaults to your current VC. If `channel` is specified, joins that one directly. |
| `/leave` | `[channel]` | Leave a voice channel and clear its queue. Defaults to your current VC. If the bot is in multiple channels, you must specify which one. |
| `/players` | — | Show all active voice sessions in the current server — channel name, playback state, current track, and queue length. |

---

## ▶ Playback

| Command | Arguments | Description |
|---|---|---|
| `/play` | `query` | Play a song or playlist, or add to the queue. Accepts YouTube URLs, playlist URLs, SoundCloud, Bandcamp, or plain search terms. Auto-joins your VC. For playlists, tracks are added in order — playback starts immediately while the rest load in the background. Uses yt-dlp's internal API to maximise playlist coverage without authentication. **If you right-click a track inside a YouTube auto-mix and paste the long URL, only that single video plays** — use `/playytmix` to load the full mix. |
| `/playnext` | `query` | Insert a song or playlist to play immediately after the current track. For playlists, the full playlist is inserted in order before whatever was next in the queue. Same mix-stripping behaviour as `/play`. |
| `/playytmix` | `query` | Intentionally load a full YouTube auto-mix or radio playlist. Paste the long URL from right-clicking a track inside a YouTube mix — this loads every track YouTube makes available in the mix (~50–200 tracks). Use `/ytlogin` to unlock larger mixes. |
| `/skip` | — | Skip the current track and advance to the next one in the queue. |
| `/previous` | — | Go back to the previous track. Replays the last track that finished. History holds up to 20 tracks per session. |
| `/stop` | — | Stop playback and clear the entire queue. Bot stays in the channel. |
| `/pause` | — | Pause the current track. |
| `/resume` | — | Resume a paused track. |

---

## 📋 Queue

| Command | Arguments | Description |
|---|---|---|
| `/queue` | `[page]` | Show the track queue, paginated at 10 tracks per page. Shows current track, upcoming tracks, and total count. Uses deferred response to avoid Discord's 3-second timeout. |
| `/nowplaying` | — | Show what's currently playing with track title, requester, duration, and queue position. Each track also posts a **Now Playing** message automatically with ⏸/⏭/⏹ buttons for inline control. |
| `/shuffle` | — | Shuffle all tracks in the queue randomly. The currently playing track is not affected. |
| `/loop` | `track \| queue \| off` | Set loop mode. `track` repeats the current song, `queue` loops through all tracks, `off` disables looping. |
| `/remove` | `position` | Remove a track from the queue by its position number (as shown in `/queue`). |
| `/undo` | — | Undo the last change to the queue — restores it to how it was before the most recent add, remove, shuffle, or skip. |
| `/redo` | — | Redo the last undone queue change. |
| `/restore` | — | Restore your queue from before the bot stopped or you disconnected. Pulls from the last saved snapshot. |

---

## 🔍 Search

| Command | Arguments | Description |
|---|---|---|
| `/search` | `query` | Search YouTube and pick from the top 5 results. Displays an interactive dropdown — select a track to add it to the queue. Times out after 60 seconds. |

---

## 💾 Playlists

| Command | Arguments | Description |
|---|---|---|
| `/createlist` | `name` | Save the current queue as a named personal playlist. Name can contain letters, numbers, spaces, hyphens, and underscores. Up to 25 playlists per user, 500 tracks per playlist. |
| `/listplaylist` | — | List all your saved playlists — shows track count and a preview. Select one from the dropdown to load it directly. |
| `/loadlist` | `name` | Load one of your saved playlists into the queue. Stubs are enqueued instantly; stream URLs resolve just-in-time as each track plays. Supports autocomplete. |
| `/removelist` | `name` | Permanently delete one of your saved playlists. Prompts for confirmation before deleting. Supports autocomplete. |
| `/editplaylist` | `name` | Open an interactive editor for a saved playlist — add tracks, remove by position, or move tracks up and down. Supports autocomplete. |

---

## 🤖 Bot

| Command | Arguments | Description |
|---|---|---|
| `/ytlogin` | `[browser]` | Link a YouTube account to this server for full playlist access and age-restricted content. Choose your browser (Chrome, Firefox, Edge, Brave, Safari) to get step-by-step export instructions, then upload the `cookies.txt` file as an attachment. Server-wide — all users benefit. |
| `/ytlogout` | — | Remove the linked YouTube account from this server, reverting to default unauthenticated access. |
| `/ytstatus` | — | Check whether a YouTube account is currently linked to this server. |
| `/ping` | — | Check the bot's latency to Discord's gateway. |
| `/status` | — | Show bot stats — number of guilds, active shards, latency, and active voice players. |
| `/help` | — | Show a quick reference of all commands grouped by category. |

---

## 💡 Tips

- `/play` accepts almost any audio source yt-dlp supports — YouTube, SoundCloud, Bandcamp, direct URLs, and plain search terms like `/play lofi hip hop`
- For YouTube playlists, the bot uses yt-dlp's internal API (`youtubetab:skip=webpage`) to fetch ~2× more entries than unauthenticated HTML scraping. Tracks load in playlist order in the background while playback starts immediately
- **Right-clicking a track inside a YouTube auto-mix** gives you a long URL with `list=RD...`. Pasting it into `/play` plays just that one video. Use `/playytmix` to load the whole mix
- Every track auto-posts a **Now Playing** embed with ⏮ previous, ⏸ pause/resume, ⏭ skip, and ⏹ stop buttons — no command needed
- If the bot is in multiple voice channels in your server, use `/leave #channel-name` to specify which one to disconnect
- `/loop track` is great for repeating a single song; `/loop queue` cycles through your whole playlist
- Queue positions shown in `/queue` are 1-based — use that number with `/remove`
