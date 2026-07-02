"""Unit tests for Phase 3 — voice-channel affinity routing.

Tests cover routing.py behaviour: single-bot passthrough, multi-bot
get/assign, all-bots-busy error, release, and get_all_players_for_guild.
All run offline — no Discord connection.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from notebane.bot_manager import BotEntry, BotManager
from notebane.routing import (
    ALL_BUSY_MSG,
    get_all_players_for_guild,
    get_players_for_channel,
    release_channel,
    resolve_players_for_channel,
)


# ── helpers ───────────────────────────────────────────────────────────────────

def _env(*pairs: tuple[int, str, int]) -> dict[str, str]:
    env: dict[str, str] = {}
    for number, token, app_id in pairs:
        env[f"BOT_{number:02d}_TOKEN"] = token
        env[f"BOT_{number:02d}_ID"] = str(app_id)
    return env


def _make_pool(*pairs: tuple[int, str, int]) -> BotManager:
    pool = BotManager.from_env(_env(*pairs))
    for entry in pool.bots:
        fake_bot = MagicMock()
        fake_players = MagicMock()
        fake_bot.players = fake_players
        fake_bot.bot_manager = pool
        entry.client = fake_bot
    return pool


def _make_bot(pool: BotManager | None) -> MagicMock:
    """A fake Notebane bot that references pool."""
    bot = MagicMock()
    bot.bot_manager = pool
    if pool is not None:
        bot.players = pool.bots[0].client.players
    else:
        bot.players = MagicMock()
    return bot


def _make_interaction(bot: MagicMock, guild_id: int = 1) -> MagicMock:
    interaction = MagicMock()
    interaction.client = bot
    interaction.guild = MagicMock()
    interaction.guild.id = guild_id
    interaction.response = MagicMock()
    interaction.response.is_done = MagicMock(return_value=False)
    interaction.response.send_message = AsyncMock()
    interaction.followup = MagicMock()
    interaction.followup.send = AsyncMock()
    return interaction


# ── single-bot passthrough ────────────────────────────────────────────────────

class TestSingleBotPassthrough:

    def test_get_players_for_channel_single_bot(self):
        pool = _make_pool((1, "tok-A", 111))
        bot = _make_bot(pool)
        result = get_players_for_channel(bot, channel_id=9001)
        assert result is bot.players

    def test_get_players_no_manager(self):
        """bot.bot_manager=None → always return bot.players."""
        bot = _make_bot(None)
        assert get_players_for_channel(bot, channel_id=9001) is bot.players

    async def test_resolve_players_single_bot(self):
        pool = _make_pool((1, "tok-A", 111))
        bot = _make_bot(pool)
        interaction = _make_interaction(bot)
        result = await resolve_players_for_channel(bot, interaction, guild_id=1, channel_id=9001)
        assert result is bot.players
        interaction.response.send_message.assert_not_called()

    def test_release_channel_single_bot_noop(self):
        pool = _make_pool((1, "tok-A", 111))
        bot = _make_bot(pool)
        release_channel(bot, channel_id=9001)   # should not raise

    def test_release_channel_no_manager_noop(self):
        bot = _make_bot(None)
        release_channel(bot, channel_id=9001)   # should not raise


# ── multi-bot routing ─────────────────────────────────────────────────────────

class TestMultiBotRouting:

    def _pool3(self) -> BotManager:
        return _make_pool((1, "tok-A", 111), (2, "tok-B", 222), (3, "tok-C", 333))

    async def test_resolve_assigns_bot1_to_new_channel(self):
        pool = self._pool3()
        bot = _make_bot(pool)
        interaction = _make_interaction(bot)

        result = await resolve_players_for_channel(bot, interaction, guild_id=1, channel_id=5001)

        assert result is pool.bots[0].client.players  # Bot 1
        assert pool.bots[0].voice_channel_id == 5001

    async def test_resolve_routes_to_existing_bot(self):
        pool = self._pool3()
        bot = _make_bot(pool)
        # Pre-assign bot 2 to channel 5002
        pool.assign_bot(5001)   # Bot 1 → 5001
        pool.assign_bot(5002)   # Bot 2 → 5002

        interaction = _make_interaction(bot)
        result = await resolve_players_for_channel(bot, interaction, guild_id=1, channel_id=5002)

        assert result is pool.bots[1].client.players  # Bot 2

    async def test_resolve_all_busy_sends_error(self):
        pool = _make_pool((1, "tok-A", 111), (2, "tok-B", 222))
        bot = _make_bot(pool)
        pool.assign_bot(5001)
        pool.assign_bot(5002)

        interaction = _make_interaction(bot)
        result = await resolve_players_for_channel(bot, interaction, guild_id=1, channel_id=5003)

        assert result is None
        sent = interaction.response.send_message.call_args[0][0]
        assert "All bots are busy" in sent
        assert "admin" in sent.lower()

    def test_release_frees_bot_for_reassignment(self):
        pool = self._pool3()
        bot = _make_bot(pool)
        pool.assign_bot(5001)
        assert pool.bots[0].voice_channel_id == 5001

        release_channel(bot, 5001)

        assert pool.bots[0].voice_channel_id is None

    async def test_resolve_bot1_preferred_after_release(self):
        pool = _make_pool((1, "tok-A", 111), (2, "tok-B", 222))
        bot = _make_bot(pool)
        pool.assign_bot(5001)   # Bot 1 → 5001
        pool.assign_bot(5002)   # Bot 2 → 5002
        release_channel(bot, 5001)  # free Bot 1

        interaction = _make_interaction(bot)
        result = await resolve_players_for_channel(bot, interaction, guild_id=1, channel_id=5003)

        assert result is pool.bots[0].client.players  # Bot 1 again

    def test_get_players_for_channel_returns_assigned_bot_players(self):
        pool = self._pool3()
        bot = _make_bot(pool)
        pool.assign_bot(5001)   # Bot 1

        result = get_players_for_channel(bot, channel_id=5001)
        assert result is pool.bots[0].client.players

    def test_get_players_for_channel_unassigned_returns_none(self):
        pool = self._pool3()
        bot = _make_bot(pool)

        assert get_players_for_channel(bot, channel_id=9999) is None


# ── get_all_players_for_guild ─────────────────────────────────────────────────

class TestGetAllPlayersForGuild:

    def test_single_bot_returns_one_manager(self):
        pool = _make_pool((1, "tok-A", 111))
        bot = _make_bot(pool)
        result = get_all_players_for_guild(bot, guild_id=1)
        assert result == [bot.players]

    def test_multi_bot_returns_managers_with_active_sessions(self):
        pool = _make_pool((1, "tok-A", 111), (2, "tok-B", 222))
        bot = _make_bot(pool)

        # Set up bot 1 to have an active session, bot 2 has none
        pool.bots[0].client.players.all_for_guild = MagicMock(return_value=["player-a"])
        pool.bots[1].client.players.all_for_guild = MagicMock(return_value=[])

        result = get_all_players_for_guild(bot, guild_id=1)
        assert len(result) == 1
        assert result[0] is pool.bots[0].client.players

    def test_multi_bot_no_manager_returns_bot_players(self):
        bot = _make_bot(None)
        result = get_all_players_for_guild(bot, guild_id=1)
        assert result == [bot.players]
