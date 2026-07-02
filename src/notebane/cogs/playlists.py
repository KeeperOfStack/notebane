"""User playlist commands — /createlist, /listplaylist, /loadlist, /removelist, /editplaylist."""

from __future__ import annotations

import logging
import math
import time
from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands

from notebane.playlist_db import (
    MAX_TRACKS_PER_PLAYLIST,
    PlaylistError,
    create_playlist,
    delete_playlist,
    get_playlist,
    get_playlist_id,
    get_playlist_tracks_by_id,
    get_user_playlist_names,
    list_playlists,
    overwrite_playlist,
    playlist_exists,
    update_playlist_tracks,
    validate_name,
)
from notebane.player import GuildPlayer, GuildPlayerManager, Track
from notebane.ytdl import YTDLError, resolve

if TYPE_CHECKING:
    pass

log = logging.getLogger("notebane.playlists")

TRACKS_PER_EDITOR_PAGE = 25
EDITOR_TIMEOUT = 120  # seconds before the edit view disables itself


# ──────────────────────────────────────────────────────────────────────────────
# Shared: load a playlist into a player (append-or-start)
# ──────────────────────────────────────────────────────────────────────────────

async def _load_playlist_into_player(
    interaction: discord.Interaction,
    player: GuildPlayer,
    tracks: list[Track],
    playlist_name: str,
) -> None:
    """Append tracks to the player queue as unresolved stubs. Records a mutation for /undo.

    Stubs are enqueued instantly (no yt-dlp calls). Stream URLs are resolved
    JIT in the play loop just before each track plays.
    """
    from notebane.restore_db import clear_snapshot as _clear_restore
    from notebane.cookies import get_guild_cookiefile

    player.record_mutation()
    _clear_restore(player.guild_id, player.channel_id)
    player._cookiefile = get_guild_cookiefile(player.guild_id)

    # Build stubs from the saved Track objects (webpage_url is always stored)
    for t in tracks:
        stub = Track(
            title=t.title,
            url=t.webpage_url,        # placeholder — JIT resolve fills real stream URL
            webpage_url=t.webpage_url,
            duration=t.duration,
            thumbnail=t.thumbnail,
            requester=t.requester,
            resolved=False,
        )
        player.queue.put_nowait(stub)

    log.info("[guild=%d] Loaded %d stubs instantly for /loadlist '%s'", player.guild_id, len(tracks), playlist_name)


# ──────────────────────────────────────────────────────────────────────────────
# Overwrite confirmation view
# ──────────────────────────────────────────────────────────────────────────────

class OverwriteConfirmView(discord.ui.View):
    def __init__(self, user_id: int, name: str, tracks: list[Track]) -> None:
        super().__init__(timeout=60)
        self._user_id = user_id
        self._name = name
        self._tracks = tracks

    @discord.ui.button(label="Overwrite", style=discord.ButtonStyle.danger)
    async def overwrite(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if interaction.user.id != self._user_id:
            await interaction.response.send_message("❌ Not your confirmation.", ephemeral=True)
            return
        try:
            overwrite_playlist(self._user_id, self._name, self._tracks)
        except PlaylistError as e:
            await interaction.response.edit_message(content=f"❌ {e}", view=None)
            return
        self.stop()
        await interaction.response.edit_message(
            content=f"✅ Playlist **{self._name}** overwritten with {len(self._tracks)} track(s).",
            view=None,
        )

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if interaction.user.id != self._user_id:
            await interaction.response.send_message("❌ Not your confirmation.", ephemeral=True)
            return
        self.stop()
        await interaction.response.edit_message(content="Cancelled. No changes made.", view=None)


# ──────────────────────────────────────────────────────────────────────────────
# Delete confirmation view
# ──────────────────────────────────────────────────────────────────────────────

class DeleteConfirmView(discord.ui.View):
    def __init__(self, user_id: int, name: str) -> None:
        super().__init__(timeout=60)
        self._user_id = user_id
        self._name = name

    @discord.ui.button(label="Delete", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if interaction.user.id != self._user_id:
            await interaction.response.send_message("❌ Not your confirmation.", ephemeral=True)
            return
        deleted = delete_playlist(self._user_id, self._name)
        self.stop()
        if deleted:
            await interaction.response.edit_message(
                content=f"🗑️ Playlist **{self._name}** deleted.", view=None
            )
        else:
            await interaction.response.edit_message(
                content=f"❌ Playlist **{self._name}** not found.", view=None
            )

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if interaction.user.id != self._user_id:
            await interaction.response.send_message("❌ Not your confirmation.", ephemeral=True)
            return
        self.stop()
        await interaction.response.edit_message(content="Cancelled.", view=None)


# ──────────────────────────────────────────────────────────────────────────────
# /listplaylist — select menu view
# ──────────────────────────────────────────────────────────────────────────────

class PlaylistSelectView(discord.ui.View):
    """Presents a Select menu of the user's playlists. Selecting one loads it."""

    def __init__(
        self,
        user_id: int,
        playlists: list[dict],
        cog: "PlaylistCog",
    ) -> None:
        super().__init__(timeout=60)
        self._user_id = user_id
        self._cog = cog

        options = [
            discord.SelectOption(
                label=p["name"][:100],
                description=f"{p['track_count']} track{'s' if p['track_count'] != 1 else ''}",
                value=p["name"],
            )
            for p in playlists[:25]
        ]
        select = discord.ui.Select(
            placeholder="Choose a playlist to load…",
            options=options,
        )
        select.callback = self._on_select
        self.add_item(select)

    async def _on_select(self, interaction: discord.Interaction) -> None:
        if interaction.user.id != self._user_id:
            await interaction.response.send_message("❌ Not your menu.", ephemeral=True)
            return
        name = interaction.data["values"][0]  # type: ignore[index]
        await interaction.response.defer(ephemeral=True)
        await self._cog._do_load_playlist(interaction, name)
        self.stop()


# ──────────────────────────────────────────────────────────────────────────────
# /editplaylist — paginated embed editor
# ──────────────────────────────────────────────────────────────────────────────

class AddTrackModal(discord.ui.Modal, title="Add Track"):
    query = discord.ui.TextInput(
        label="YouTube URL or search terms",
        placeholder="e.g. https://youtube.com/watch?v=... or artist - song name",
        max_length=500,
    )

    def __init__(self, view: "PlaylistEditorView") -> None:
        super().__init__()
        self._view = view

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        from notebane.cookies import get_guild_cookiefile
        cookiefile = get_guild_cookiefile(interaction.guild_id) if interaction.guild_id else None
        try:
            track = await resolve(str(self.query.value), requester=interaction.user.display_name, cookiefile=cookiefile)
        except YTDLError as e:
            await interaction.followup.send(f"❌ Could not resolve: {e}", ephemeral=True)
            return
        self._view.tracks.append(track)
        update_playlist_tracks(self._view.playlist_id, self._view.tracks)
        await self._view.refresh(interaction)


class RemoveTrackModal(discord.ui.Modal, title="Remove Track"):
    position = discord.ui.TextInput(
        label="Track number to remove",
        placeholder="e.g. 47",
        max_length=6,
    )

    def __init__(self, view: "PlaylistEditorView") -> None:
        super().__init__()
        self._view = view

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            pos = int(str(self.position.value).strip())
        except ValueError:
            await interaction.response.send_message("❌ Enter a valid number.", ephemeral=True)
            return
        total = len(self._view.tracks)
        if pos < 1 or pos > total:
            await interaction.response.send_message(
                f"❌ Position must be between 1 and {total}.", ephemeral=True
            )
            return
        removed = self._view.tracks.pop(pos - 1)
        update_playlist_tracks(self._view.playlist_id, self._view.tracks)
        # Adjust page if needed
        max_page = max(1, math.ceil(len(self._view.tracks) / TRACKS_PER_EDITOR_PAGE))
        if self._view.page > max_page:
            self._view.page = max_page
        await interaction.response.defer(ephemeral=True)
        await self._view.refresh(interaction, note=f"🗑️ Removed **{removed.title}**.")


class MoveTrackModal(discord.ui.Modal, title="Move Track"):
    from_pos = discord.ui.TextInput(label="Move FROM position", placeholder="e.g. 12", max_length=6)
    to_pos = discord.ui.TextInput(label="Move TO position", placeholder="e.g. 3", max_length=6)

    def __init__(self, view: "PlaylistEditorView") -> None:
        super().__init__()
        self._view = view

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            frm = int(str(self.from_pos.value).strip())
            to = int(str(self.to_pos.value).strip())
        except ValueError:
            await interaction.response.send_message("❌ Enter valid numbers.", ephemeral=True)
            return
        total = len(self._view.tracks)
        if not (1 <= frm <= total) or not (1 <= to <= total):
            await interaction.response.send_message(
                f"❌ Positions must be between 1 and {total}.", ephemeral=True
            )
            return
        if frm == to:
            await interaction.response.send_message("❌ FROM and TO are the same position.", ephemeral=True)
            return
        track = self._view.tracks.pop(frm - 1)
        self._view.tracks.insert(to - 1, track)
        update_playlist_tracks(self._view.playlist_id, self._view.tracks)
        await interaction.response.defer(ephemeral=True)
        await self._view.refresh(interaction, note=f"↕️ Moved **{track.title}** to position {to}.")


class PlaylistEditorView(discord.ui.View):
    def __init__(
        self,
        user_id: int,
        playlist_id: int,
        playlist_name: str,
        tracks: list[Track],
    ) -> None:
        super().__init__(timeout=EDITOR_TIMEOUT)
        self.user_id = user_id
        self.playlist_id = playlist_id
        self.playlist_name = playlist_name
        self.tracks = tracks
        self.page = 1
        self._message: discord.Message | None = None

    def _build_embed(self, note: str = "") -> discord.Embed:
        total = len(self.tracks)
        total_pages = max(1, math.ceil(total / TRACKS_PER_EDITOR_PAGE))
        self.page = max(1, min(self.page, total_pages))

        start = (self.page - 1) * TRACKS_PER_EDITOR_PAGE
        end = min(start + TRACKS_PER_EDITOR_PAGE, total)

        embed = discord.Embed(
            title=f"✏️ {self.playlist_name}",
            colour=discord.Colour.blurple(),
        )

        if total == 0:
            embed.description = "*No tracks. Use ➕ Add to add some.*"
        else:
            lines = []
            for i, t in enumerate(self.tracks[start:end], start=start + 1):
                dur = t.duration_fmt() if t.duration is not None else "?"
                lines.append(f"`{i:>3}.` {t.title} `{dur}`")
            embed.description = "\n".join(lines)

        embed.set_footer(text=f"Page {self.page}/{total_pages} · Tracks {start+1}–{end} of {total}  |  Changes save immediately")

        if note:
            embed.add_field(name="Last action", value=note, inline=False)

        return embed

    async def refresh(self, interaction: discord.Interaction, note: str = "") -> None:
        embed = self._build_embed(note)
        self._update_buttons()
        if self._message:
            try:
                await self._message.edit(embed=embed, view=self)
                await interaction.followup.send("\u200b", ephemeral=True, delete_after=0)  # type: ignore[call-overload]
            except Exception:
                await interaction.followup.send(embed=embed, view=self, ephemeral=True)
        else:
            await interaction.followup.send(embed=embed, view=self, ephemeral=True)

    def _update_buttons(self) -> None:
        total_pages = max(1, math.ceil(len(self.tracks) / TRACKS_PER_EDITOR_PAGE))
        for item in self.children:
            if isinstance(item, discord.ui.Button):
                if item.custom_id == "ep_prev":
                    item.disabled = self.page <= 1
                elif item.custom_id == "ep_next":
                    item.disabled = self.page >= total_pages

    async def _check_user(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("❌ Not your editor.", ephemeral=True)
            return False
        return True

    async def on_timeout(self) -> None:
        for item in self.children:
            if hasattr(item, "disabled"):
                item.disabled = True  # type: ignore[union-attr]
        if self._message:
            try:
                await self._message.edit(
                    content="⏱️ Editor session expired. Run `/editplaylist` again.",
                    view=self,
                )
            except Exception:
                pass

    @discord.ui.button(emoji="◀", style=discord.ButtonStyle.secondary, custom_id="ep_prev", disabled=True)
    async def prev_page(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not await self._check_user(interaction):
            return
        self.page -= 1
        await interaction.response.defer(ephemeral=True)
        await self.refresh(interaction)

    @discord.ui.button(emoji="▶", style=discord.ButtonStyle.secondary, custom_id="ep_next")
    async def next_page(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not await self._check_user(interaction):
            return
        self.page += 1
        await interaction.response.defer(ephemeral=True)
        await self.refresh(interaction)

    @discord.ui.button(label="➕ Add", style=discord.ButtonStyle.success, custom_id="ep_add")
    async def add_track(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not await self._check_user(interaction):
            return
        if len(self.tracks) >= MAX_TRACKS_PER_PLAYLIST:
            await interaction.response.send_message(
                f"❌ Playlist is full ({MAX_TRACKS_PER_PLAYLIST} tracks max).", ephemeral=True
            )
            return
        await interaction.response.send_modal(AddTrackModal(self))

    @discord.ui.button(label="🗑 Remove", style=discord.ButtonStyle.danger, custom_id="ep_remove")
    async def remove_track(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not await self._check_user(interaction):
            return
        if not self.tracks:
            await interaction.response.send_message("❌ No tracks to remove.", ephemeral=True)
            return
        await interaction.response.send_modal(RemoveTrackModal(self))

    @discord.ui.button(label="↕ Move", style=discord.ButtonStyle.secondary, custom_id="ep_move")
    async def move_track(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not await self._check_user(interaction):
            return
        if len(self.tracks) < 2:
            await interaction.response.send_message("❌ Need at least 2 tracks to move.", ephemeral=True)
            return
        await interaction.response.send_modal(MoveTrackModal(self))


# ──────────────────────────────────────────────────────────────────────────────
# Cog
# ──────────────────────────────────────────────────────────────────────────────

class PlaylistCog(commands.Cog, name="Playlists"):
    def __init__(self, bot: commands.AutoShardedBot, players: GuildPlayerManager) -> None:
        self.bot = bot
        self.players = players

    # ── Autocomplete helper ───────────────────────────────────────────────────

    async def _playlist_name_autocomplete(
        self,
        interaction: discord.Interaction,
        current: str,
    ) -> list[app_commands.Choice[str]]:
        names = get_user_playlist_names(interaction.user.id)
        return [
            app_commands.Choice(name=n, value=n)
            for n in names
            if current.lower() in n.lower()
        ][:25]

    # ── Shared: ensure player + VC ────────────────────────────────────────────

    async def _get_or_join_player(
        self, interaction: discord.Interaction
    ) -> GuildPlayer | None:
        """Get the active player, or join the user's current VC if not connected."""
        from notebane.cogs.voice import assert_user_in_voice, _connect_to_channel
        from notebane.cogs.music import MusicCog

        if not interaction.guild or not interaction.guild_id:
            await interaction.followup.send("❌ Server-only command.", ephemeral=True)
            return None

        channel = await assert_user_in_voice(interaction)
        if channel is None:
            return None

        player = self.players.get(interaction.guild_id, channel.id)
        if player is not None and not player.is_connected:
            self.players.remove(interaction.guild_id, channel.id)
            player = None

        music_cog: MusicCog | None = self.bot.cogs.get("Music")  # type: ignore[assignment]
        on_track_start = music_cog._on_track_start if music_cog else None

        if player is None:
            player = await _connect_to_channel(
                interaction, channel, self.players, on_track_start=on_track_start
            )
            if player is None:
                return None
            await player.start()

        elif player._play_task is None or player._play_task.done():
            await player.start()

        if isinstance(interaction.channel, discord.TextChannel) and music_cog:
            music_cog._text_channels[channel.id] = interaction.channel

        return player

    # ── Shared: do the actual load ────────────────────────────────────────────

    async def _do_load_playlist(
        self, interaction: discord.Interaction, name: str
    ) -> None:
        tracks = get_playlist(interaction.user.id, name)
        if tracks is None:
            await interaction.followup.send(
                f"❌ No playlist named **{name}**. Check spelling or use `/listplaylist`.",
                ephemeral=True,
            )
            return
        if not tracks:
            await interaction.followup.send(f"❌ Playlist **{name}** is empty.", ephemeral=True)
            return

        player = await self._get_or_join_player(interaction)
        if player is None:
            return

        await _load_playlist_into_player(interaction, player, tracks, name)

        is_playing = player.is_playing or player.is_paused
        action = "▶ Loading" if not is_playing else "➕ Added to queue"
        embed = discord.Embed(
            title=f"{action}: {name}",
            description=f"**{len(tracks)}** track{'s' if len(tracks) != 1 else ''} — loading in background…",
            colour=discord.Colour.green() if not is_playing else discord.Colour.blurple(),
        )
        await interaction.followup.send(embed=embed, ephemeral=True)

    # ── /createlist ───────────────────────────────────────────────────────────

    @app_commands.command(name="createlist", description="Save the current queue as a named playlist.")
    @app_commands.describe(name="Name for your playlist (letters, numbers, spaces, hyphens, underscores)")
    async def createlist(self, interaction: discord.Interaction, name: str) -> None:
        await interaction.response.defer(ephemeral=True)

        try:
            name = validate_name(name)
        except PlaylistError as e:
            await interaction.followup.send(f"❌ {e}", ephemeral=True)
            return

        if not interaction.guild_id:
            await interaction.followup.send("❌ Server-only command.", ephemeral=True)
            return

        player = self.players.get_any(interaction.guild_id)
        if player is None:
            await interaction.followup.send("❌ I'm not in a voice channel.", ephemeral=True)
            return

        # Stubs are enqueued instantly — no need to wait for background loaders.
        tracks = player.queue_list()
        if player.current:
            tracks = [player.current] + tracks

        if not tracks:
            await interaction.followup.send("❌ Nothing in the queue to save.", ephemeral=True)
            return

        # Check for name collision
        if playlist_exists(interaction.user.id, name):
            view = OverwriteConfirmView(interaction.user.id, name, tracks)
            await interaction.followup.send(
                f"⚠️ A playlist named **{name}** already exists.\nOverwrite it with the current queue ({len(tracks)} track{'s' if len(tracks) != 1 else ''})?",
                view=view,
                ephemeral=True,
            )
            return

        try:
            create_playlist(interaction.user.id, name, tracks)
        except PlaylistError as e:
            await interaction.followup.send(f"❌ {e}", ephemeral=True)
            return

        embed = discord.Embed(
            title="💾 Playlist Saved",
            description=f"**{name}** — {len(tracks)} track{'s' if len(tracks) != 1 else ''}",
            colour=discord.Colour.green(),
        )
        embed.set_footer(text="Use /loadlist to play it anytime, from any server.")
        await interaction.followup.send(embed=embed, ephemeral=True)

    # ── /listplaylist ─────────────────────────────────────────────────────────

    @app_commands.command(name="listplaylist", description="List your saved playlists and load one.")
    async def listplaylist(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        playlists = list_playlists(interaction.user.id)
        if not playlists:
            await interaction.followup.send(
                "You have no saved playlists. Use `/createlist <name>` to save your current queue.",
                ephemeral=True,
            )
            return

        lines = []
        for p in playlists:
            import datetime
            age = datetime.datetime.fromtimestamp(p["updated_at"]).strftime("%Y-%m-%d")
            lines.append(f"**{p['name']}** — {p['track_count']} track{'s' if p['track_count'] != 1 else ''} · saved {age}")

        embed = discord.Embed(
            title=f"🎵 Your Playlists ({len(playlists)})",
            description="\n".join(lines),
            colour=discord.Colour.blurple(),
        )
        embed.set_footer(text="Select a playlist below to load it.")

        view = PlaylistSelectView(interaction.user.id, playlists, self)
        await interaction.followup.send(embed=embed, view=view, ephemeral=True)

    # ── /loadlist ─────────────────────────────────────────────────────────────

    @app_commands.command(name="loadlist", description="Load one of your saved playlists into the queue.")
    @app_commands.describe(name="Name of your playlist")
    @app_commands.autocomplete(name=_playlist_name_autocomplete)
    async def loadlist(self, interaction: discord.Interaction, name: str) -> None:
        await interaction.response.defer(ephemeral=True)
        await self._do_load_playlist(interaction, name)

    # ── /removelist ───────────────────────────────────────────────────────────

    @app_commands.command(name="removelist", description="Delete one of your saved playlists.")
    @app_commands.describe(name="Name of the playlist to delete")
    @app_commands.autocomplete(name=_playlist_name_autocomplete)
    async def removelist(self, interaction: discord.Interaction, name: str) -> None:
        if not playlist_exists(interaction.user.id, name):
            await interaction.response.send_message(
                f"❌ No playlist named **{name}**.", ephemeral=True
            )
            return
        view = DeleteConfirmView(interaction.user.id, name)
        tracks = get_playlist(interaction.user.id, name)
        count = len(tracks) if tracks else 0
        await interaction.response.send_message(
            f"Delete playlist **{name}** ({count} track{'s' if count != 1 else ''})? This cannot be undone.",
            view=view,
            ephemeral=True,
        )

    # ── /editplaylist ─────────────────────────────────────────────────────────

    @app_commands.command(name="editplaylist", description="Add, remove, or reorder tracks in a saved playlist.")
    @app_commands.describe(name="Name of the playlist to edit")
    @app_commands.autocomplete(name=_playlist_name_autocomplete)
    async def editplaylist(self, interaction: discord.Interaction, name: str) -> None:
        await interaction.response.defer(ephemeral=True)

        pid = get_playlist_id(interaction.user.id, name)
        if pid is None:
            await interaction.followup.send(
                f"❌ No playlist named **{name}**.", ephemeral=True
            )
            return

        tracks = get_playlist_tracks_by_id(pid)
        view = PlaylistEditorView(
            user_id=interaction.user.id,
            playlist_id=pid,
            playlist_name=name,
            tracks=tracks,
        )
        view._update_buttons()
        embed = view._build_embed()
        msg = await interaction.followup.send(embed=embed, view=view, ephemeral=True)
        # Store the message reference so the view can edit it on refresh
        if isinstance(msg, discord.WebhookMessage):
            view._message = msg  # type: ignore[assignment]


async def setup(bot: commands.AutoShardedBot) -> None:
    if not hasattr(bot, "players"):
        from notebane.player import GuildPlayerManager
        bot.players = GuildPlayerManager()  # type: ignore[attr-defined]
    await bot.add_cog(PlaylistCog(bot, bot.players))  # type: ignore[attr-defined]
