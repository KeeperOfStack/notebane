"""Unit tests for Phase 5 — all-bots-busy error + single-bot passthrough.

Tests the exact UX contract:
  - N=1 (or guild has 1 bot): never sees "all bots busy", uses existing errors
  - N≥2 (guild has ≥2 bots) and all occupied: sends the all-bots-busy message
  - Message wording is exactly right
All run offline — no Discord connection.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from notebane.bot_manager import BotManager
from notebane.routing import ALL_BUSY_MSG, resolve_players_for_channel


# ── helpers ───────────────────────────────────────────────────────────────────

def _env(*pairs: tuple[int, str, int]) -> dict[str, str]:
    env: dict[str, str] = {}
    for number, token, app_id in pairs:
        env[f"BOT_{number:02d}_TOKEN"] = token
        env[f"BOT_{number:02d}_ID"] = str(app_id)
    return env


def _make_pool_wired(*pairs: tuple[int, str, int], guild_ids: list[int] | None = None) -> BotManager:
    pool = BotManager.from_env(_env(*pairs))
    for entry in pool.bots:
        fake_bot = MagicMock()
        fake_players = MagicMock()
        fake_bot.players = fake_players
        fake_bot.bot_manager = pool
        if guild_ids is not None:
            fake_bot.guilds = [MagicMock(id=gid) for gid in guild_ids]
        entry.client = fake_bot
    return pool


def _make_bot(pool: BotManager) -> MagicMock:
    bot = MagicMock()
    bot.bot_manager = pool
    bot.players = pool.bots[0].client.players
    return bot


def _make_interaction() -> MagicMock:
    ix = MagicMock()
    ix.response = MagicMock()
    ix.response.is_done = MagicMock(return_value=False)
    ix.response.send_message = AsyncMock()
    ix.followup = MagicMock()
    ix.followup.send = AsyncMock()
    return ix


# ── single-bot passthrough: N=1 container ────────────────────────────────────

class TestSingleBotContainer:

    async def test_no_busy_error_single_bot_fresh_channel(self):
        """Single-bot pool never triggers all-bots-busy even on a new channel."""
        pool = _make_pool_wired((1, "tok-A", 111), guild_ids=[100])
        bot = _make_bot(pool)
        ix = _make_interaction()

        result = await resolve_players_for_channel(bot, ix, guild_id=100, channel_id=5001)

        assert result is not None
        ix.response.send_message.assert_not_called()
        ix.followup.send.assert_not_called()

    async def test_no_busy_error_single_bot_occupied(self):
        """Even when Bot 1 is already in another channel, the single-bot path
        never fires the busy message — caller gets the players manager back
        and it's up to the caller to handle the 'already busy' case."""
        pool = _make_pool_wired((1, "tok-A", 111), guild_ids=[100])
        pool.assign_bot_for_guild(100, 5001)   # occupy bot 1
        bot = _make_bot(pool)
        ix = _make_interaction()

        # Single-bot: guild_pool_is_single → True → passthrough, no busy error
        result = await resolve_players_for_channel(bot, ix, guild_id=100, channel_id=5002)

        assert result is not None
        ix.response.send_message.assert_not_called()


# ── single-bot passthrough: N>1 container, guild has 1 bot ───────────────────

class TestGuildSeesOneBotOfMany:

    async def test_no_busy_error_when_guild_has_one_of_three(self):
        """Container has 3 bots; guild 100 has only Bot 2 invited.
        Must behave as single-bot — no busy error."""
        pool = BotManager.from_env(_env(
            (1, "tok-A", 111), (2, "tok-B", 222), (3, "tok-C", 333)
        ))
        for i, entry in enumerate(pool.bots):
            client = MagicMock()
            client.players = MagicMock()
            client.bot_manager = pool
            # Only Bot 2 (index 1) is in guild 100
            client.guilds = [MagicMock(id=100)] if i == 1 else [MagicMock(id=200)]
            entry.client = client

        bot = MagicMock()
        bot.bot_manager = pool
        bot.players = pool.bots[0].client.players
        ix = _make_interaction()

        result = await resolve_players_for_channel(bot, ix, guild_id=100, channel_id=5001)

        assert result is pool.bots[1].client.players  # Bot 2's manager
        ix.response.send_message.assert_not_called()


# ── all-bots-busy: N≥2, guild has ≥2 bots, all occupied ─────────────────────

class TestAllBotsBusy:

    async def test_sends_busy_message_when_all_two_bots_occupied(self):
        pool = _make_pool_wired(
            (1, "tok-A", 111), (2, "tok-B", 222), guild_ids=[100]
        )
        pool.bots[0].voice_channel_id = 5001
        pool.bots[1].voice_channel_id = 5002
        bot = _make_bot(pool)
        ix = _make_interaction()

        result = await resolve_players_for_channel(bot, ix, guild_id=100, channel_id=5003)

        assert result is None
        ix.response.send_message.assert_called_once()
        sent_msg = ix.response.send_message.call_args[0][0]
        assert "All bots are busy" in sent_msg
        assert "admin" in sent_msg.lower()
        assert "join a channel" in sent_msg.lower()

    async def test_busy_message_exact_wording(self):
        """Verify ALL_BUSY_MSG constant is what actually gets sent."""
        pool = _make_pool_wired(
            (1, "tok-A", 111), (2, "tok-B", 222), guild_ids=[100]
        )
        pool.bots[0].voice_channel_id = 5001
        pool.bots[1].voice_channel_id = 5002
        bot = _make_bot(pool)
        ix = _make_interaction()

        await resolve_players_for_channel(bot, ix, guild_id=100, channel_id=5003)

        sent_msg = ix.response.send_message.call_args[0][0]
        assert sent_msg == ALL_BUSY_MSG

    async def test_not_busy_when_one_free(self):
        """Two bots, one occupied, one free — must assign the free one, no error."""
        pool = _make_pool_wired(
            (1, "tok-A", 111), (2, "tok-B", 222), guild_ids=[100]
        )
        pool.bots[0].voice_channel_id = 5001  # bot 1 busy
        bot = _make_bot(pool)
        ix = _make_interaction()

        result = await resolve_players_for_channel(bot, ix, guild_id=100, channel_id=5002)

        assert result is not None  # bot 2 assigned
        ix.response.send_message.assert_not_called()

    async def test_busy_released_then_assignable_again(self):
        """Release a channel then try again — no busy error the second time."""
        pool = _make_pool_wired(
            (1, "tok-A", 111), (2, "tok-B", 222), guild_ids=[100]
        )
        pool.bots[0].voice_channel_id = 5001
        pool.bots[1].voice_channel_id = 5002
        pool.release_bot(5001)   # free bot 1

        bot = _make_bot(pool)
        ix = _make_interaction()
        result = await resolve_players_for_channel(bot, ix, guild_id=100, channel_id=5003)

        assert result is pool.bots[0].client.players  # bot 1 reassigned
        ix.response.send_message.assert_not_called()

    async def test_busy_message_sent_ephemerally(self):
        """Verify the message is sent with ephemeral=True."""
        pool = _make_pool_wired(
            (1, "tok-A", 111), (2, "tok-B", 222), guild_ids=[100]
        )
        pool.bots[0].voice_channel_id = 5001
        pool.bots[1].voice_channel_id = 5002
        bot = _make_bot(pool)
        ix = _make_interaction()

        await resolve_players_for_channel(bot, ix, guild_id=100, channel_id=5003)

        _, kwargs = ix.response.send_message.call_args
        assert kwargs.get("ephemeral") is True
