"""Search cog — /search with interactive top-5 Select Menu."""

from __future__ import annotations

import asyncio
import logging
from functools import partial

import discord
from discord import app_commands
from discord.ext import commands
import yt_dlp

from notebane.cogs.voice import assert_user_in_voice, _connect_to_channel
from notebane.embeds import error as err_embed
from notebane.player import GuildPlayerManager
from notebane.ytdl import YTDL_OPTS, YTDLError

log = logging.getLogger("notebane.search")

MAX_RESULTS = 5


# ──────────────────────────────────────────────────────────────────────────────
# yt-dlp flat search (fast — no full extraction per result)
# ──────────────────────────────────────────────────────────────────────────────

def _search_sync(query: str, n: int = MAX_RESULTS) -> list[dict]:
    """Return up to n search result dicts (flat, no stream URL yet)."""
    opts = dict(YTDL_OPTS)
    opts["extract_flat"] = True   # fast: no per-video extraction
    opts["quiet"] = True
    opts["noplaylist"] = True

    search_query = f"ytsearch{n}:{query}"
    with yt_dlp.YoutubeDL(opts) as ydl:  # type: ignore[arg-type]
        info = ydl.extract_info(search_query, download=False)

    if info is None:
        return []
    entries = info.get("entries") or []
    return list(entries[:n])  # type: ignore[index]


async def _search_async(query: str, n: int = MAX_RESULTS) -> list[dict]:
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, partial(_search_sync, query, n))


# ──────────────────────────────────────────────────────────────────────────────
# Select Menu View
# ──────────────────────────────────────────────────────────────────────────────

def _fmt_duration(seconds: int | None) -> str:
    if seconds is None:
        return "∞"
    m, s = divmod(seconds, 60)
    h, m = divmod(m, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


class SearchSelect(discord.ui.Select):
    def __init__(
        self,
        results: list[dict],
        player_manager: GuildPlayerManager,
        requester: str,
    ) -> None:
        self.results = results
        self.player_manager = player_manager
        self.requester = requester

        options = []
        for i, r in enumerate(results):
            title = (r.get("title") or "Unknown")[:100]
            dur = _fmt_duration(r.get("duration"))
            uploader = (r.get("uploader") or r.get("channel") or "")[:50]
            label = title[:100]
            description = f"{uploader} • {dur}"[:100] if uploader else dur
            options.append(
                discord.SelectOption(
                    label=label,
                    description=description,
                    value=str(i),
                    emoji="🎵",
                )
            )

        super().__init__(
            placeholder="Choose a track to play…",
            min_values=1,
            max_values=1,
            options=options,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer()
        idx = int(self.values[0])
        chosen = self.results[idx]

        # Disable the menu so it can't be used again
        self.disabled = True
        await interaction.edit_original_response(
            content=f"🔍 Loading **{chosen.get('title', 'track')}**…",
            view=self.view,
        )

        # Resolve the full stream URL
        from notebane.ytdl import resolve
        try:
            track = await resolve(
                chosen.get("webpage_url") or chosen.get("url") or chosen.get("id", ""),
                requester=self.requester,
            )
        except YTDLError as exc:
            await interaction.edit_original_response(
                content=None, embed=err_embed(str(exc), title="Could not load track"), view=None
            )
            return

        # Get or create player
        if not interaction.guild or not interaction.guild_id:
            return

        channel = await assert_user_in_voice(interaction)
        if channel is None:
            return

        player = self.player_manager.get(interaction.guild_id, channel.id)
        if player is None:
            player = await _connect_to_channel(interaction, channel, self.player_manager)
            if player is None:
                return
            await player.start()

        await player.queue.put(track)
        queue_pos = player.queue.qsize()

        if player.current is not None:
            from notebane.cogs.music import _queued_embed
            await interaction.edit_original_response(
                content=None, embed=_queued_embed(track, queue_pos), view=None
            )
        else:
            await interaction.edit_original_response(
                content="▶️ Starting playback…", view=None
            )


class SearchView(discord.ui.View):
    def __init__(self, results: list[dict], player_manager: GuildPlayerManager, requester: str) -> None:
        super().__init__(timeout=60)
        self.add_item(SearchSelect(results, player_manager, requester))

    async def on_timeout(self) -> None:
        # Disable all items when the view expires
        for item in self.children:
            item.disabled = True  # type: ignore[union-attr]


# ──────────────────────────────────────────────────────────────────────────────
# Cog
# ──────────────────────────────────────────────────────────────────────────────

class SearchCog(commands.Cog, name="Search"):
    """YouTube search with interactive result picker."""

    def __init__(self, bot: commands.AutoShardedBot, players: GuildPlayerManager) -> None:
        self.bot = bot
        self.players = players

    @app_commands.command(name="search", description="Search YouTube and pick from the top 5 results.")
    @app_commands.describe(query="Search terms")
    async def search(self, interaction: discord.Interaction, query: str) -> None:
        await interaction.response.defer()

        if not interaction.guild:
            await interaction.followup.send(embed=err_embed("This command only works in a server."))
            return

        await interaction.edit_original_response(content=f"🔍 Searching for **{query}**…")

        try:
            results = await _search_async(query)
        except Exception as exc:
            log.exception("Search error for %r", query)
            await interaction.edit_original_response(
                content=None, embed=err_embed(str(exc), title="Search failed")
            )
            return

        if not results:
            await interaction.edit_original_response(
                content=None, embed=err_embed(f"No results found for **{query}**.")
            )
            return

        # Build result embed
        embed = discord.Embed(
            title=f"🔎 Search results for \"{query}\"",
            description="Pick a track from the menu below. Times out in 60 seconds.",
            colour=discord.Colour.blurple(),
        )
        for i, r in enumerate(results, 1):
            title = r.get("title") or "Unknown"
            url = r.get("webpage_url") or r.get("url") or ""
            uploader = r.get("uploader") or r.get("channel") or "Unknown"
            dur = _fmt_duration(r.get("duration"))
            embed.add_field(
                name=f"{i}. {title[:80]}",
                value=f"[{uploader}]({url}) • {dur}" if url else f"{uploader} • {dur}",
                inline=False,
            )

        view = SearchView(results, self.players, interaction.user.display_name)
        await interaction.edit_original_response(content=None, embed=embed, view=view)


async def setup(bot: commands.AutoShardedBot) -> None:
    if not hasattr(bot, "players"):
        from notebane.player import GuildPlayerManager
        bot.players = GuildPlayerManager()  # type: ignore[attr-defined]
    await bot.add_cog(SearchCog(bot, bot.players))  # type: ignore[attr-defined]
