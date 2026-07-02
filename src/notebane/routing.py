"""Multi-bot routing helpers.

This module is the single place that knows how to:

  1. Resolve which bot / GuildPlayerManager owns a given voice channel.
  2. Send the correct "all bots busy" error when every bot is occupied.
  3. Release a bot assignment when a player disconnects.

Single-bot passthrough
----------------------
When ``bot.bot_manager is None`` OR ``bot.bot_manager.is_single_bot`` is True,
every function in this module falls back to the single-bot path — identical UX
to the pre-Phase-2 application, zero multi-bot code paths active.

Multi-bot routing contract
---------------------------
Each ``Notebane`` instance has its own ``self.players: GuildPlayerManager``.
A ``BotEntry.client`` is the ``Notebane`` instance for that bot.
The BotManager stores which bot (by ``voice_channel_id``) owns each channel.

To issue a command in a voice channel:
  1. Call ``resolve_players_for_channel(bot, guild_id, channel_id)``
     → returns the GuildPlayerManager of the bot assigned to that channel.
     If no bot is assigned, assigns one (Bot 1 first) and returns its manager.
     If all bots are busy, sends the "busy" error and returns None.
  2. Use the returned manager for all player operations.
  3. When the player disconnects, call ``release_channel(bot, channel_id)``.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import discord
    from notebane.__main__ import Notebane
    from notebane.player import GuildPlayerManager

from typing import Any

log = logging.getLogger("notebane.routing")

ALL_BUSY_MSG = (
    "❌ All bots are busy. "
    "Please ask an admin to add an additional bot, "
    "or join a channel that already has a bot in it."
)


async def _send(interaction: "discord.Interaction", msg: str) -> None:
    """Send an ephemeral message whether or not the interaction is deferred."""
    if not interaction.response.is_done():
        await interaction.response.send_message(msg, ephemeral=True)
    else:
        await interaction.followup.send(msg, ephemeral=True)


def get_players_for_channel(
    bot: Any,
    channel_id: int,
) -> "GuildPlayerManager | None":
    """Return the GuildPlayerManager for the bot already in *channel_id*.

    Does NOT assign a new bot — only looks up an existing assignment.
    Returns ``bot.players`` in single-bot mode (always the one manager).
    Returns None in multi-bot mode when no bot is assigned to the channel.
    """
    mgr = bot.bot_manager
    if mgr is None or mgr.is_single_bot:
        return bot.players

    entry = mgr.get_bot_for_channel(channel_id)
    if entry is None or entry.client is None:
        return None
    return entry.client.players  # type: ignore[union-attr]


async def resolve_players_for_channel(
    bot: Any,
    interaction: "discord.Interaction",
    guild_id: int,
    channel_id: int,
) -> "GuildPlayerManager | None":
    """Return the GuildPlayerManager that should handle *channel_id*.

    Single-bot: returns ``bot.players`` immediately.
    Multi-bot:
      - If a bot is already in the channel → return its manager.
      - If a free bot exists → assign it (Bot 1 first) → return its manager.
      - All bots busy → send the "all bots busy" error → return None.

    Sends an ephemeral error and returns None on failure.
    """
    mgr = bot.bot_manager
    if mgr is None or mgr.is_single_bot:
        return bot.players

    entry = mgr.get_or_assign_bot_for_channel(guild_id, channel_id)
    if entry is None:
        # All bots occupied
        await _send(interaction, ALL_BUSY_MSG)
        log.warning(
            "All %d bots busy — guild=%d channel=%d rejected",
            mgr.count, guild_id, channel_id,
        )
        return None

    if entry.client is None:
        # Should not happen after Phase 2 wiring, but guard defensively.
        log.error("BotEntry number=%d has no client wired (Phase 2 bug)", entry.number)
        await _send(interaction, "❌ Internal error: bot client not initialised.")
        return None

    log.debug(
        "Routing guild=%d channel=%d → Bot %d",
        guild_id, channel_id, entry.number,
    )
    return entry.client.players  # type: ignore[union-attr]


def release_channel(bot: Any, channel_id: int) -> None:
    """Release the bot assignment for *channel_id* (call on disconnect/leave).

    No-op in single-bot mode.
    """
    mgr = bot.bot_manager
    if mgr is None or mgr.is_single_bot:
        return
    mgr.release_bot(channel_id)


def get_all_players_for_guild(
    bot: Any,
    guild_id: int,
) -> "list[GuildPlayerManager]":
    """Return all GuildPlayerManagers that have active sessions in *guild_id*.

    Single-bot: returns [bot.players].
    Multi-bot: walks every BotEntry and collects managers that have at least
    one player in the guild.
    """
    mgr = bot.bot_manager
    if mgr is None or mgr.is_single_bot:
        return [bot.players]

    result = []
    for entry in mgr.bots:
        if entry.client is not None:
            pm = entry.client.players  # type: ignore[union-attr]
            if pm.all_for_guild(guild_id):
                result.append(pm)
    return result