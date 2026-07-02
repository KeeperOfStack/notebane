# 📋 Notebane — Command Reference

All commands are Discord slash commands. Type `/` in any channel to see them with autocomplete.

---

## 🔊 Voice

<table>
<thead>
<tr><th width="180">Command</th><th width="110">Arguments</th><th>Description</th></tr>
</thead>
<tbody>
<tr><td><code>/join</code></td><td><code>[channel]</code></td><td>Join a voice channel. Defaults to your current VC. If <code>channel</code> is specified, joins that one directly.</td></tr>
<tr><td><code>/leave</code></td><td><code>[channel]</code></td><td>Leave a voice channel and clear its queue. Defaults to your current VC. If the bot is in multiple channels, you must specify which one.</td></tr>
<tr><td><code>/players</code></td><td>—</td><td>Show all active voice sessions in the current server — channel name, playback state, current track, and queue length.</td></tr>
</tbody>
</table>

---

## ▶ Playback

<table>
<thead>
<tr><th width="180">Command</th><th width="110">Arguments</th><th>Description</th></tr>
</thead>
<tbody>
<tr><td><code>/play</code></td><td><code>query</code></td><td>Play a song or playlist, or add to the queue. Accepts YouTube URLs, playlist URLs, SoundCloud, Bandcamp, or plain search terms. Auto-joins your VC. Playback starts immediately while playlist tracks load in the background. <strong>If you right-click a track inside a YouTube auto-mix and paste the long URL, only that single video plays</strong> — use <code>/playytmix</code> to load the full mix.</td></tr>
<tr><td><code>/playnext</code></td><td><code>query</code></td><td>Insert a song or playlist to play immediately after the current track. For playlists, the full playlist is inserted in order before whatever was next in the queue. Same mix-stripping behaviour as <code>/play</code>.</td></tr>
<tr><td><code>/playytmix</code></td><td><code>query</code></td><td>Intentionally load a full YouTube auto-mix or radio playlist. Paste the long URL from right-clicking a track inside a YouTube mix — loads every track YouTube makes available (~50–200 tracks). Use <code>/ytlogin</code> to unlock larger mixes.</td></tr>
<tr><td><code>/playytmixnext</code></td><td><code>query</code></td><td>Insert a full YouTube auto-mix to play immediately after the current track. Same as <code>/playytmix</code> but inserts at the front of the queue.</td></tr>
<tr><td><code>/skip</code></td><td>—</td><td>Skip the current track and advance to the next one in the queue.</td></tr>
<tr><td><code>/previous</code></td><td>—</td><td>Go back to the previous track. Replays the last track that finished. History holds up to 20 tracks per session.</td></tr>
<tr><td><code>/stop</code></td><td>—</td><td>Stop playback and clear the entire queue. Bot stays in the channel.</td></tr>
<tr><td><code>/pause</code></td><td>—</td><td>Pause the current track.</td></tr>
<tr><td><code>/resume</code></td><td>—</td><td>Resume a paused track.</td></tr>
</tbody>
</table>

---

## 📋 Queue

<table>
<thead>
<tr><th width="180">Command</th><th width="110">Arguments</th><th>Description</th></tr>
</thead>
<tbody>
<tr><td><code>/queue</code></td><td><code>[page]</code></td><td>Show the track queue, paginated at 10 tracks per page. Shows current track, upcoming tracks, and total count.</td></tr>
<tr><td><code>/nowplaying</code></td><td>—</td><td>Show what's currently playing — title, requester, duration, and queue position. Each track also auto-posts a <strong>Now Playing</strong> message with ⏮/⏸/⏭/⏹ buttons for inline control.</td></tr>
<tr><td><code>/shuffle</code></td><td>—</td><td>Shuffle all tracks in the queue randomly. The currently playing track is not affected.</td></tr>
<tr><td><code>/loop</code></td><td><code>track | queue | off</code></td><td>Set loop mode. <code>track</code> repeats the current song, <code>queue</code> loops through all tracks, <code>off</code> disables looping.</td></tr>
<tr><td><code>/remove</code></td><td><code>position</code></td><td>Remove a track from the queue by its position number (as shown in <code>/queue</code>).</td></tr>
<tr><td><code>/undo</code></td><td>—</td><td>Undo the last change to the queue. Shows how many tracks were removed and how many remain. Supports up to 10 levels of undo per session.</td></tr>
<tr><td><code>/redo</code></td><td>—</td><td>Redo the last undone queue change.</td></tr>
<tr><td><code>/restore</code></td><td>—</td><td>Restore your queue from before the bot stopped or you disconnected. Pulls from the last saved snapshot.</td></tr>
</tbody>
</table>

---

## 🔍 Search

<table>
<thead>
<tr><th width="180">Command</th><th width="110">Arguments</th><th>Description</th></tr>
</thead>
<tbody>
<tr><td><code>/search</code></td><td><code>query</code></td><td>Search YouTube and pick from the top 5 results. Displays an interactive dropdown — select a track to add it to the queue. Times out after 60 seconds.</td></tr>
</tbody>
</table>

---

## 💾 Playlists

<table>
<thead>
<tr><th width="180">Command</th><th width="110">Arguments</th><th>Description</th></tr>
</thead>
<tbody>
<tr><td><code>/createlist</code></td><td><code>name</code></td><td>Save the current queue as a named personal playlist. Name can contain letters, numbers, spaces, hyphens, and underscores. Up to 25 playlists per user, 500 tracks per playlist.</td></tr>
<tr><td><code>/listplaylist</code></td><td>—</td><td>List all your saved playlists — shows track count and a preview. Select one from the dropdown to load it directly.</td></tr>
<tr><td><code>/loadlist</code></td><td><code>name</code></td><td>Load one of your saved playlists into the queue. Tracks are enqueued instantly; stream URLs resolve just-in-time as each track plays. Supports autocomplete.</td></tr>
<tr><td><code>/removelist</code></td><td><code>name</code></td><td>Permanently delete one of your saved playlists. Prompts for confirmation before deleting. Supports autocomplete.</td></tr>
<tr><td><code>/editplaylist</code></td><td><code>name</code></td><td>Open an interactive editor for a saved playlist — add tracks, remove by position, or move tracks up and down. Supports autocomplete.</td></tr>
</tbody>
</table>

---

## 🤖 Bot

<table>
<thead>
<tr><th width="180">Command</th><th width="110">Arguments</th><th>Description</th></tr>
</thead>
<tbody>
<tr><td><code>/ytlogin</code></td><td><code>[browser]</code></td><td>Link a YouTube account to this server for full playlist access and age-restricted content. Choose your browser (Chrome, Firefox, Edge, Brave, Safari) to get step-by-step export instructions, then upload the <code>cookies.txt</code> file as an attachment. Server-wide — all users benefit.</td></tr>
<tr><td><code>/ytlogout</code></td><td>—</td><td>Remove the linked YouTube account from this server, reverting to default unauthenticated access.</td></tr>
<tr><td><code>/ytstatus</code></td><td>—</td><td>Check whether a YouTube account is currently linked to this server.</td></tr>
<tr><td><code>/ping</code></td><td>—</td><td>Check the bot's latency to Discord's gateway.</td></tr>
<tr><td><code>/status</code></td><td>—</td><td>Show bot stats — number of guilds, active shards, latency, and active voice players.</td></tr>
<tr><td><code>/help</code></td><td>—</td><td>Show a quick reference of all commands grouped by category.</td></tr>
</tbody>
</table>

---

## 💡 Tips

- `/play` accepts almost any audio source yt-dlp supports — YouTube, SoundCloud, Bandcamp, direct URLs, and plain search terms like `/play lofi hip hop`
- For YouTube playlists, the bot uses yt-dlp's internal API to fetch ~2× more entries than unauthenticated HTML scraping. Tracks load in playlist order while playback starts immediately
- **Right-clicking a track inside a YouTube auto-mix** gives you a long URL with `list=RD...`. Pasting it into `/play` plays just that one video. Use `/playytmix` to load the whole mix
- Every track auto-posts a **Now Playing** embed with ⏮ previous, ⏸ pause/resume, ⏭ skip, and ⏹ stop buttons — no command needed
- If the bot is in multiple voice channels in your server, use `/leave #channel-name` to specify which one to disconnect
- `/loop track` is great for repeating a single song; `/loop queue` cycles through your whole playlist
- Queue positions shown in `/queue` are 1-based — use that number with `/remove`
