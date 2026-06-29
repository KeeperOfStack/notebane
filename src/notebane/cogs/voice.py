"""Voice cog — /join, /leave, voice state helpers."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands

if TYPE_CHECKING:
    from notebane.player import GuildPlayerManager

log = logging.getLogger("notebane.voice")


# ──────────────────────────────────────────────────────────────────────────────
# Shared voice-state helpers (used by this cog and future music cog)
# ──────────────────────────────────────────────────────────────────────────────

async def assert_user_in_voice(interaction: discord.Interaction) -> discord.VoiceChannel | None:
    """Check that the invoking user is in a voice channel.

    Returns the VoiceChannel, or sends an ephemeral error and returns None.
    """
    member = interaction.guild and interaction.guild.get_member(interaction.user.id)
    if not member or not member.voice or not member.voice.channel:
        await interaction.response.send_message(
            "❌ You need to be in a voice channel first.", ephemeral=True
        )
        return None
    channel = member.voice.channel
    if not isinstance(channel, discord.VoiceChannel):
        await interaction.response.send_message(
            "❌ Stage channels are not supported.", ephemeral=True
        )
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
        await interaction.response.send_message(
            f"❌ I don't have permission to join **{channel.name}**.", ephemeral=True
        )
        return False
    if not perms.speak:
        await interaction.response.send_message(
            f"❌ I don't have permission to speak in **{channel.name}**.", ephemeral=True
        )
        return False
    return True


# ──────────────────────────────────────────────────────────────────────────────
# Cog
# ──────────────────────────────────────────────────────────────────────────────

class VoiceCog(commands.Cog, name="Voice"):
    """Join/leave voice channel commands."""

    def __init__(self, bot: commands.AutoShardedBot, players: GuildPlayerManager) -> None:
        self.bot = bot
        self.players = players

    # ── /join ─────────────────────────────────────────────────────────────────

    @app_commands.command(name="join", description="Join your current voice channel.")
    async def join(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)

        if not interaction.guild_id or not interaction.guild:
            await interaction.followup.send("❌ This command only works in a server.", ephemeral=True)
            return

        channel = await assert_user_in_voice(interaction)
        if channel is None:
            return

        if not await assert_bot_perms(interaction, channel):
            return

        # Already in the right channel?
        existing = self.players.get(interaction.guild_id, channel.id)
        if existing and existing.is_connected:
            await interaction.followup.send(
                f"✅ Already in **{channel.name}**.", ephemeral=True
            )
            return

        # Connect
        try:
            vc = await channel.connect(timeout=10.0, reconnect=True)
        except discord.ClientException as exc:
            log.warning("Join failed for guild=%d channel=%d: %s", interaction.guild_id, channel.id, exc)
            await interaction.followup.send(
                "❌ Failed to connect — I may already be in another channel in this server.\n"
                "Use `/leave` first if you want me to switch.", ephemeral=True
            )
            return
        except TimeoutError:
            await interaction.followup.send(
                "❌ Connection timed out. Try again.", ephemeral=True
            )
            return

        from notebane.player import GuildPlayer
        player = GuildPlayer(vc)
        self.players.set(player)
        log.info("Joined guild=%d channel=%s (%d)", interaction.guild_id, channel.name, channel.id)

        await interaction.followup.send(
            f"✅ Joined **{channel.name}**.", ephemeral=True
        )

    # ── /leave ────────────────────────────────────────────────────────────────

    @app_commands.command(name="leave", description="Leave the voice channel and clear the queue.")
    async def leave(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)

        if not interaction.guild:
            await interaction.followup.send("❌ This command only works in a server.", ephemeral=True)
            return

        # Find any player for this guild
        player = self.players.get_any(interaction.guild.id)
        if player is None:
            await interaction.followup.send("❌ I'm not in a voice channel.", ephemeral=True)
            return

        channel_name = player.voice_client.channel.name
        guild_id = player.guild_id
        channel_id = player.channel_id

        await player.disconnect()
        self.players.remove(guild_id, channel_id)

        log.info("Left guild=%d channel=%s (%d)", guild_id, channel_name, channel_id)
        await interaction.followup.send(
            f"👋 Left **{channel_name}** and cleared the queue.", ephemeral=True
        )

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

        # A member left a channel
        if before.channel is None:
            return

        guild = before.channel.guild
        player = self.players.get(guild.id, before.channel.id)
        if player is None:
            return

        # Count non-bot members remaining
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
    # GuildPlayerManager is stored on the bot instance so cogs can share it
    if not hasattr(bot, "players"):
        from notebane.player import GuildPlayerManager
        bot.players = GuildPlayerManager()  # type: ignore[attr-defined]
    await bot.add_cog(VoiceCog(bot, bot.players))  # type: ignore[attr-defined]
