"""Unit tests for Phase 8 — per-guild bot pool filtering.

Tests BotManager.bots_for_guild(), guild_pool_is_single(),
guild_pool_all_busy(), and assign_bot_for_guild().
All run offline — no Discord connection.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from notebane.bot_manager import BotEntry, BotManager


# ── helpers ───────────────────────────────────────────────────────────────────

def _env(*pairs: tuple[int, str, int]) -> dict[str, str]:
    env: dict[str, str] = {}
    for number, token, app_id in pairs:
        env[f"BOT_{number:02d}_TOKEN"] = token
        env[f"BOT_{number:02d}_ID"] = str(app_id)
    return env


def _pool3() -> BotManager:
    return BotManager.from_env(_env((1, "tok-A", 111), (2, "tok-B", 222), (3, "tok-C", 333)))


def _wire_guild(pool: BotManager, guild_ids_per_bot: list[list[int]]) -> None:
    """Attach fake clients to each bot with the given guild membership lists."""
    for entry, guild_ids in zip(pool.bots, guild_ids_per_bot):
        client = MagicMock()
        client.guilds = [MagicMock(id=gid) for gid in guild_ids]
        entry.client = client


# ── bots_for_guild ────────────────────────────────────────────────────────────

class TestBotsForGuild:

    def test_no_clients_wired_returns_full_pool(self):
        """Before on_ready, no clients are wired — return full pool (startup safety)."""
        pool = _pool3()
        result = pool.bots_for_guild(guild_id=999)
        assert len(result) == 3

    def test_all_bots_in_guild(self):
        pool = _pool3()
        _wire_guild(pool, [[100, 200], [100, 200], [100, 200]])
        result = pool.bots_for_guild(guild_id=100)
        assert len(result) == 3
        assert [b.number for b in result] == [1, 2, 3]

    def test_partial_subset(self):
        """Only bots 1 and 3 are in guild 100; bot 2 is in guild 200 only."""
        pool = _pool3()
        _wire_guild(pool, [[100], [200], [100]])
        result = pool.bots_for_guild(guild_id=100)
        assert [b.number for b in result] == [1, 3]

    def test_no_bot_in_guild_falls_back_to_full_pool(self):
        """Defensive: if no bot is in the guild, return full pool (avoid silent failure)."""
        pool = _pool3()
        _wire_guild(pool, [[200], [200], [200]])
        result = pool.bots_for_guild(guild_id=999)
        assert len(result) == 3

    def test_single_bot_in_guild(self):
        pool = _pool3()
        _wire_guild(pool, [[100], [200], [300]])
        result = pool.bots_for_guild(guild_id=100)
        assert len(result) == 1
        assert result[0].number == 1

    def test_bot1_always_first_in_filtered_result(self):
        """Even in filtered results, Bot 1 must appear before Bot 3."""
        pool = _pool3()
        _wire_guild(pool, [[100], [200], [100]])   # Bots 1 and 3 in guild 100
        result = pool.bots_for_guild(guild_id=100)
        assert result[0].number == 1
        assert result[1].number == 3


# ── guild_pool_is_single ──────────────────────────────────────────────────────

class TestGuildPoolIsSingle:

    def test_true_when_one_bot_in_guild(self):
        pool = _pool3()
        _wire_guild(pool, [[100], [200], [300]])
        assert pool.guild_pool_is_single(100) is True

    def test_false_when_two_bots_in_guild(self):
        pool = _pool3()
        _wire_guild(pool, [[100], [100], [200]])
        assert pool.guild_pool_is_single(100) is False

    def test_true_for_actual_single_bot_pool(self):
        pool = BotManager.from_env(_env((1, "tok-A", 111)))
        _wire_guild(pool, [[100]])
        assert pool.guild_pool_is_single(100) is True


# ── guild_pool_all_busy ───────────────────────────────────────────────────────

class TestGuildPoolAllBusy:

    def test_false_when_bots_free(self):
        pool = _pool3()
        _wire_guild(pool, [[100], [100], [100]])
        assert pool.guild_pool_all_busy(100) is False

    def test_true_when_all_guild_bots_busy(self):
        pool = _pool3()
        _wire_guild(pool, [[100], [100], [200]])  # bots 1 & 2 in guild 100
        pool.bots[0].voice_channel_id = 5001
        pool.bots[1].voice_channel_id = 5002
        assert pool.guild_pool_all_busy(100) is True

    def test_only_guild_bots_count_towards_busy(self):
        """Bot 3 is busy but not in guild 100 — guild 100 should NOT see all-busy."""
        pool = _pool3()
        _wire_guild(pool, [[100], [100], [200]])  # bot 3 only in guild 200
        pool.bots[2].voice_channel_id = 5003       # bot 3 busy
        assert pool.guild_pool_all_busy(100) is False


# ── assign_bot_for_guild ──────────────────────────────────────────────────────

class TestAssignBotForGuild:

    def test_assigns_bot1_first(self):
        pool = _pool3()
        _wire_guild(pool, [[100], [100], [100]])
        entry = pool.assign_bot_for_guild(guild_id=100, channel_id=5001)
        assert entry is not None
        assert entry.number == 1

    def test_skips_bot_not_in_guild(self):
        """Bot 1 is in guild 200 only; guild 100 sees only Bot 2."""
        pool = _pool3()
        _wire_guild(pool, [[200], [100], [200]])
        entry = pool.assign_bot_for_guild(guild_id=100, channel_id=5001)
        assert entry is not None
        assert entry.number == 2

    def test_returns_none_when_guild_pool_all_busy(self):
        pool = _pool3()
        _wire_guild(pool, [[100], [100], [200]])   # bots 1 & 2 in guild 100
        pool.assign_bot_for_guild(100, 5001)
        pool.assign_bot_for_guild(100, 5002)
        assert pool.assign_bot_for_guild(100, 5003) is None

    def test_bot3_not_counted_when_only_bots12_in_guild(self):
        """Even though Bot 3 is free, it's not in guild 100 — must not be assigned."""
        pool = _pool3()
        _wire_guild(pool, [[100], [100], [200]])
        pool.bots[0].voice_channel_id = 5001  # bot 1 busy
        pool.bots[1].voice_channel_id = 5002  # bot 2 busy
        # Bot 3 is free but not in guild 100
        result = pool.assign_bot_for_guild(100, 5003)
        assert result is None
        assert pool.bots[2].voice_channel_id is None  # bot 3 untouched


# ── get_or_assign_bot_for_channel uses guild-scoped pool ──────────────────────

class TestGetOrAssignUsesGuildPool:

    def test_does_not_assign_bot_outside_guild(self):
        """get_or_assign_bot_for_channel must use assign_bot_for_guild, not assign_bot."""
        pool = _pool3()
        _wire_guild(pool, [[200], [100], [200]])  # only bot 2 in guild 100
        entry = pool.get_or_assign_bot_for_channel(guild_id=100, channel_id=5001)
        assert entry is not None
        assert entry.number == 2  # NOT bot 1 (not in guild 100)
