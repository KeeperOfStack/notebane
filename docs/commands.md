     1|# 📋 Notebane — Command Reference
     2|
     3|All commands are Discord slash commands. Type `/` in any channel to see them with autocomplete.
     4|
     5|---
     6|
     7|## 🔊 Voice
     8|
     9|| Command&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp; | Arguments | Description |
    10||---|---|---|
    11|| `/join` | `[channel]` | Join a voice channel. Defaults to your current VC. If `channel` is specified, joins that one directly. |
    12|| `/leave` | `[channel]` | Leave a voice channel and clear its queue. Defaults to your current VC. If the bot is in multiple channels, you must specify which one. |
    13|| `/players` | — | Show all active voice sessions in the current server — channel name, playback state, current track, and queue length. |
    14|
    15|---
    16|
    17|## ▶ Playback
    18|
    19|| Command&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp; | Arguments | Description |
    20||---|---|---|
    21|| `/play` | `query` | Play a song or playlist, or add to the queue. Accepts YouTube URLs, playlist URLs, SoundCloud, Bandcamp, or plain search terms. Auto-joins your VC. For playlists, tracks are added in order — playback starts immediately while the rest load in the background. Uses yt-dlp's internal API to maximise playlist coverage without authentication. **If you right-click a track inside a YouTube auto-mix and paste the long URL, only that single video plays** — use `/playytmix` to load the full mix. |
    22|| `/playnext` | `query` | Insert a song or playlist to play immediately after the current track. For playlists, the full playlist is inserted in order before whatever was next in the queue. Same mix-stripping behaviour as `/play`. |
    23|| `/playytmix` | `query` | Intentionally load a full YouTube auto-mix or radio playlist. Paste the long URL from right-clicking a track inside a YouTube mix — this loads every track YouTube makes available in the mix (~50–200 tracks). Use `/ytlogin` to unlock larger mixes. |
    24|| `/playytmixnext` | `query` | Insert a full YouTube auto-mix to play immediately after the current track. Same as `/playytmix` but inserts at the front of the queue. |
    25|| `/skip` | — | Skip the current track and advance to the next one in the queue. |
    26|| `/previous` | — | Go back to the previous track. Replays the last track that finished. History holds up to 20 tracks per session. |
    27|| `/stop` | — | Stop playback and clear the entire queue. Bot stays in the channel. |
    28|| `/pause` | — | Pause the current track. |
    29|| `/resume` | — | Resume a paused track. |
    30|
    31|---
    32|
    33|## 📋 Queue
    34|
    35|| Command&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp; | Arguments | Description |
    36||---|---|---|
    37|| `/queue` | `[page]` | Show the track queue, paginated at 10 tracks per page. Shows current track, upcoming tracks, and total count. Uses deferred response to avoid Discord's 3-second timeout. |
    38|| `/nowplaying` | — | Show what's currently playing with track title, requester, duration, and queue position. Each track also posts a **Now Playing** message automatically with ⏮/⏸/⏭/⏹ buttons for inline control. |
    39|| `/shuffle` | — | Shuffle all tracks in the queue randomly. The currently playing track is not affected. |
    40|| `/loop` | `track \| queue \| off` | Set loop mode. `track` repeats the current song, `queue` loops through all tracks, `off` disables looping. |
    41|| `/remove` | `position` | Remove a track from the queue by its position number (as shown in `/queue`). |
    42|| `/undo` | — | Undo the last change to the queue. Shows how many tracks were removed and how many remain. Supports up to 10 levels of undo per session. |
    43|| `/redo` | — | Redo the last undone queue change. |
    44|| `/restore` | — | Restore your queue from before the bot stopped or you disconnected. Pulls from the last saved snapshot. |
    45|
    46|---
    47|
    48|## 🔍 Search
    49|
    50|| Command&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp; | Arguments | Description |
    51||---|---|---|
    52|| `/search` | `query` | Search YouTube and pick from the top 5 results. Displays an interactive dropdown — select a track to add it to the queue. Times out after 60 seconds. |
    53|
    54|---
    55|
    56|## 💾 Playlists
    57|
    58|| Command&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp; | Arguments | Description |
    59||---|---|---|
    60|| `/createlist` | `name` | Save the current queue as a named personal playlist. Name can contain letters, numbers, spaces, hyphens, and underscores. Up to 25 playlists per user, 500 tracks per playlist. |
    61|| `/listplaylist` | — | List all your saved playlists — shows track count and a preview. Select one from the dropdown to load it directly. |
    62|| `/loadlist` | `name` | Load one of your saved playlists into the queue. Stubs are enqueued instantly; stream URLs resolve just-in-time as each track plays. Supports autocomplete. |
    63|| `/removelist` | `name` | Permanently delete one of your saved playlists. Prompts for confirmation before deleting. Supports autocomplete. |
    64|| `/editplaylist` | `name` | Open an interactive editor for a saved playlist — add tracks, remove by position, or move tracks up and down. Supports autocomplete. |
    65|
    66|---
    67|
    68|## 🤖 Bot
    69|
    70|| Command&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp; | Arguments | Description |
    71||---|---|---|
    72|| `/ytlogin` | `[browser]` | Link a YouTube account to this server for full playlist access and age-restricted content. Choose your browser (Chrome, Firefox, Edge, Brave, Safari) to get step-by-step export instructions, then upload the `cookies.txt` file as an attachment. Server-wide — all users benefit. |
    73|| `/ytlogout` | — | Remove the linked YouTube account from this server, reverting to default unauthenticated access. |
    74|| `/ytstatus` | — | Check whether a YouTube account is currently linked to this server. |
    75|| `/ping` | — | Check the bot's latency to Discord's gateway. |
    76|| `/status` | — | Show bot stats — number of guilds, active shards, latency, and active voice players. |
    77|| `/help` | — | Show a quick reference of all commands grouped by category. |
    78|
    79|---
    80|
    81|## 💡 Tips
    82|
    83|- `/play` accepts almost any audio source yt-dlp supports — YouTube, SoundCloud, Bandcamp, direct URLs, and plain search terms like `/play lofi hip hop`
    84|- For YouTube playlists, the bot uses yt-dlp's internal API (`youtubetab:skip=webpage`) to fetch ~2× more entries than unauthenticated HTML scraping. Tracks load in playlist order in the background while playback starts immediately
    85|- **Right-clicking a track inside a YouTube auto-mix** gives you a long URL with `list=RD...`. Pasting it into `/play` plays just that one video. Use `/playytmix` to load the whole mix
    86|- Every track auto-posts a **Now Playing** embed with ⏮ previous, ⏸ pause/resume, ⏭ skip, and ⏹ stop buttons — no command needed
    87|- If the bot is in multiple voice channels in your server, use `/leave #channel-name` to specify which one to disconnect
    88|- `/loop track` is great for repeating a single song; `/loop queue` cycles through your whole playlist
    89|- Queue positions shown in `/queue` are 1-based — use that number with `/remove`
    90|