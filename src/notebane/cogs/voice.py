"""Voice cog — /join, /leave, /players, voice state helpers."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Callable

import discord
from discord import app_commands
from discord.ext import commands

if TYPE_CHECKING:
    from notebane.player import GuildPlayer, GuildPlayerManager

log = logging.getLogger("notebane.voice")


# ──────────────────────────────────────────────────────────────────────────────
# Shared voice-state helpers (used by music cog too)
# ──────────────────────────────────────────────────────────────────────────────

async def assert_user_in_voice(interaction: discord.Interaction) -> discord.VoiceChannel | None:
    """Check that the invoking user is in a voice channel.

    Returns the VoiceChannel, or sends an ephemeral error and returns None.
    Does NOT send a response if interaction.response is already done.
    """
    member = interaction.guild and interaction.guild.get_member(interaction.user.id)
    if not member or not member.voice or not member.voice.channel:
        msg = "❌ You need to be in a voice channel first."
        if not interaction.response.is_done():
            await interaction.response.send_message(msg, ephemeral=True)
        else:
            await interaction.followup.send(msg, ephemeral=True)
        return None
    channel = member.voice.channel
    if not isinstance(channel, discord.VoiceChannel):
        msg = "❌ Stage channels are not supported."
        if not interaction.response.is_done():
            await interaction.response.send_message(msg, ephemeral=True)
        else:
            await interaction.followup.send(msg, ephemeral=True)
        return None
    return channel


async def assert_bot_perms(
    interaction: discord.Interaction, channel: discord.VoiceChannel
) -> bool:
    """Check the bot has Connect + Speak permissions in the target channel."""
    me = interaction.guild and interaction.guild.me
    if not me:
        return False
    perms = channel.permissions_for(me)
    if not perms.connect:
        msg = f"❌ I don't have permission to join **{channel.name}**."
        if not interaction.response.is_done():
            await interaction.response.send_message(msg, ephemeral=True)
        else:
            await interaction.followup.send(msg, ephemeral=True)
        return False
    if not perms.speak:
        msg = f"❌ I don't have permission to speak in **{channel.name}**."
        if not interaction.response.is_done():
            await interaction.response.send_message(msg, ephemeral=True)
        else:
            await interaction.followup.send(msg, ephemeral=True)
        return False
    return True


async def _connect_to_channel(
    interaction: discord.Interaction,
    channel: discord.VoiceChannel,
    players: GuildPlayerManager,
    *,
    on_track_start: Callable | None = None,
) -> GuildPlayer | None:
    """Connect the bot to a voice channel and register a GuildPlayer.

    Returns the new GuildPlayer, or None on failure (error already sent).
    Caller must have deferred the interaction before calling this.
    """
    from notebane.player import GuildPlayer

    # Already in this exact channel?
    existing = players.get(channel.guild.id, channel.id)
    if existing and existing.is_connected:
        await interaction.followup.send(f"✅ Already in **{channel.name}**.", ephemeral=True)
        return existing

    # Check perms
    if not await assert_bot_perms(interaction, channel):
        return None

    try:
        vc = await channel.connect(timeout=10.0, reconnect=True)
    except discord.ClientException as exc:
        log.warning("Join failed for guild=%d channel=%d: %s", channel.guild.id, channel.id, exc)
        await interaction.followup.send(
            "❌ Failed to connect — I may already be in another channel.\n"
            "Use `/leave` first if you want me to switch.",
            ephemeral=True,
        )
        return None
    except TimeoutError:
        await interaction.followup.send("❌ Connection timed out. Try again.", ephemeral=True)
        return None

    player = GuildPlayer(vc, on_track_start=on_track_start)
    players.set(player)
    log.info("Joined guild=%d channel=%s (%d)", channel.guild.id, channel.name, channel.id)
    return player


# ──────────────────────────────────────────────────────────────────────────────
# Cog
# ──────────────────────────────────────────────────────────────────────────────

class VoiceCog(commands.Cog, name="Voice"):
    """Join/leave voice channel commands."""

    def __init__(self, bot: commands.AutoShardedBot, players: GuildPlayerManager) -> None:
        self.bot = bot
        self.players = players

    # ── /join ─────────────────────────────────────────────────────────────────

    @app_commands.command(name="join", description="Join a voice channel.")
    @app_commands.describe(channel="Voice channel to join (defaults to your current channel)")
    async def join(
        self,
        interaction: discord.Interaction,
        channel: discord.VoiceChannel | None = None,
    ) -> None:
        await interaction.response.defer(ephemeral=True)

        if not interaction.guild_id or not interaction.guild:
            await interaction.followup.send("❌ This command only works in a server.", ephemeral=True)
            return

        # Resolve target channel: explicit arg → user's current VC → error
        target: discord.VoiceChannel | None = channel
        if target is None:
            target = await assert_user_in_voice(interaction)
            if target is None:
                return

        player = await _connect_to_channel(interaction, target, self.players)
        if player is None:
            return  # error already sent

        await interaction.followup.send(f"✅ Joined **{target.name}**.", ephemeral=True)

    # ── /leave ────────────────────────────────────────────────────────────────

    @app_commands.command(name="leave", description="Leave a voice channel and clear its queue.")
    @app_commands.describe(channel="Channel to leave (defaults to your current channel; use 'all' via /players)")
    async def leave(
        self,
        interaction: discord.Interaction,
        channel: discord.VoiceChannel | None = None,
    ) -> None:
        await interaction.response.defer(ephemeral=True)

        if not interaction.guild:
            await interaction.followup.send("❌ This command only works in a server.", ephemeral=True)
            return

        # Resolve: explicit channel → user's current VC → any active player
        target_id: int | None = None
        if channel is not None:
            target_id = channel.id
        else:
            member = interaction.guild.get_member(interaction.user.id)
            if member and member.voice and isinstance(member.voice.channel, discord.VoiceChannel):
                target_id = member.voice.channel.id

        if target_id is not None:
            player = self.players.get(interaction.guild.id, target_id)
            if player is None:
                await interaction.followup.send(
                    "❌ I'm not playing in that channel.", ephemeral=True
                )
                return
        else:
            # Fall back: only one active player → leave it; multiple → ask user to specify
            all_players = self.players.all_for_guild(interaction.guild.id)
            if not all_players:
                await interaction.followup.send("❌ I'm not in any voice channel.", ephemeral=True)
                return
            if len(all_players) > 1:
                names = ", ".join(f"**{p.voice_client.channel.name}**" for p in all_players)
                await interaction.followup.send(
                    f"❌ I'm in multiple channels ({names}).\n"
                    "Use `/leave <channel>` to specify which one.",
                    ephemeral=True,
                )
                return
            player = all_players[0]

        channel_name = player.voice_client.channel.name
        guild_id = player.guild_id
        channel_id = player.channel_id

        await player.disconnect()
        self.players.remove(guild_id, channel_id)

        log.info("Left guild=%d channel=%s (%d)", guild_id, channel_name, channel_id)
        await interaction.followup.send(
            f"👋 Left **{channel_name}** and cleared its queue.", ephemeral=True
        )

    # ── /players ──────────────────────────────────────────────────────────────

    @app_commands.command(name="players", description="Show all active voice sessions in this server.")
    async def players_cmd(self, interaction: discord.Interaction) -> None:
        if not interaction.guild:
            await interaction.response.send_message("❌ Server-only command.", ephemeral=True)
            return

        all_players = self.players.all_for_guild(interaction.guild.id)
        if not all_players:
            await interaction.response.send_message("No active voice sessions.", ephemeral=True)
            return

        embed = discord.Embed(
            title=f"🎶 Active Voice Sessions — {len(all_players)} channel{'s' if len(all_players) != 1 else ''}",
            colour=discord.Colour.blurple(),
        )
        for p in all_players:
            vc_name = p.voice_client.channel.name
            state = "⏸ Paused" if p.is_paused else ("▶ Playing" if p.is_playing else "⏹ Idle")
            now = f"[{p.current.title}]({p.current.webpage_url})" if p.current else "Nothing"
            queue_len = p.queue.qsize()
            loop = " 🔂" if p.loop_track else (" 🔁" if p.loop_queue else "")
            embed.add_field(
                name=f"#{vc_name}{loop}",
                value=f"{state}\n**Now:** {now}\n**Queue:** {queue_len} track{'s' if queue_len != 1 else ''} remaining",
                inline=False,
            )

        await interaction.response.send_message(embed=embed)

    # ── Voice state update (auto-leave when alone) ────────────────────────────

    @commands.Cog.listener()
    async def on_voice_state_update(
        self,
        member: discord.Member,
        before: discord.VoiceState,
        after: discord.VoiceState,
    ) -> None:
        """Auto-leave when the bot is the only one remaining in a VC."""
        if member.bot:
            return
        if before.channel is None:
            return

        guild = before.channel.guild
        player = self.players.get(guild.id, before.channel.id)
        if player is None:
            return

        remaining = [m for m in before.channel.members if not m.bot]
        if len(remaining) == 0:
            log.info(
                "Auto-leave: no users left in guild=%d channel=%d",
                guild.id,
                before.channel.id,
            )
            await player.disconnect()
            self.players.remove(guild.id, before.channel.id)


async def setup(bot: commands.AutoShardedBot) -> None:
    if not hasattr(bot, "players"):
        from notebane.player import GuildPlayerManager
        bot.players = GuildPlayerManager()  # type: ignore[attr-defined]
    await bot.add_cog(VoiceCog(bot, bot.players))  # type: ignore[attr-defined]
