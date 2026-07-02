"""Unit tests for BotManager — Phase 1.

Tests run entirely offline (no Discord connection, no network).
"""

import pytest
from notebane.bot_manager import BotEntry, BotManager


# ── helpers ──────────────────────────────────────────────────────────────────

def _env(*pairs: tuple[int, str, int]) -> dict[str, str]:
    """Build a fake env dict from (number, token, app_id) tuples."""
    env: dict[str, str] = {}
    for number, token, app_id in pairs:
        env[f"BOT_{number:02d}_TOKEN"] = token
        env[f"BOT_{number:02d}_ID"] = str(app_id)
    return env


# ── from_env parsing ─────────────────────────────────────────────────────────

class TestFromEnv:

    def test_single_bot(self):
        pool = BotManager.from_env(_env((1, "tok-A", 111)))
        assert pool.count == 1
        assert pool.bots[0].number == 1
        assert pool.bots[0].token == "tok-A"
        assert pool.bots[0].application_id == 111

    def test_three_bots(self):
        pool = BotManager.from_env(_env((1, "tok-A", 111), (2, "tok-B", 222), (3, "tok-C", 333)))
        assert pool.count == 3
        # Must be sorted by number
        assert [b.number for b in pool.bots] == [1, 2, 3]

    def test_gaps_in_numbering(self):
        """Bots 1, 3, 5 — 2 and 4 are absent."""
        pool = BotManager.from_env(_env((1, "tok-A", 111), (3, "tok-C", 333), (5, "tok-E", 555)))
        assert pool.count == 3
        assert [b.number for b in pool.bots] == [1, 3, 5]

    def test_missing_id_skipped(self):
        """A slot with a TOKEN but no ID should be silently skipped."""
        env = _env((1, "tok-A", 111), (2, "tok-B", 222))
        del env["BOT_02_ID"]          # remove ID for bot 2
        pool = BotManager.from_env(env)
        assert pool.count == 1
        assert pool.bots[0].number == 1

    def test_missing_token_skipped(self):
        """A slot with an ID but no TOKEN should be silently skipped."""
        env = _env((1, "tok-A", 111), (2, "tok-B", 222))
        del env["BOT_02_TOKEN"]
        pool = BotManager.from_env(env)
        assert pool.count == 1

    def test_empty_token_skipped(self):
        env = _env((1, "tok-A", 111), (2, "", 222))
        pool = BotManager.from_env(env)
        assert pool.count == 1

    def test_invalid_id_skipped(self):
        env = _env((1, "tok-A", 111))
        env["BOT_02_TOKEN"] = "tok-B"
        env["BOT_02_ID"] = "not-a-number"
        pool = BotManager.from_env(env)
        assert pool.count == 1

    def test_legacy_fallback(self):
        """No BOT_NN_ vars → fall back to DISCORD_TOKEN."""
        env = {"DISCORD_TOKEN": "legacy-tok", "DISCORD_APPLICATION_ID": "999"}
        pool = BotManager.from_env(env)
        assert pool.count == 1
        assert pool.bots[0].number == 1
        assert pool.bots[0].token == "legacy-tok"
        assert pool.bots[0].application_id == 999

    def test_no_credentials_raises(self):
        with pytest.raises(RuntimeError, match="No bot credentials"):
            BotManager.from_env({})

    def test_unrelated_env_vars_ignored(self):
        env = _env((1, "tok-A", 111))
        env["DISCORD_TOKEN"] = "should-be-ignored"
        env["SOME_OTHER_VAR"] = "noise"
        pool = BotManager.from_env(env)
        assert pool.count == 1      # BOT_01 found, DISCORD_TOKEN not counted again


# ── Properties ───────────────────────────────────────────────────────────────

class TestProperties:

    def test_is_single_bot_true(self):
        pool = BotManager.from_env(_env((1, "tok-A", 111)))
        assert pool.is_single_bot is True

    def test_is_single_bot_false(self):
        pool = BotManager.from_env(_env((1, "tok-A", 111), (2, "tok-B", 222)))
        assert pool.is_single_bot is False

    def test_bots_returns_copy(self):
        """Mutating the returned list must not affect the internal list."""
        pool = BotManager.from_env(_env((1, "tok-A", 111)))
        bots = pool.bots
        bots.clear()
        assert pool.count == 1


# ── Routing ──────────────────────────────────────────────────────────────────

class TestRouting:

    def _pool3(self) -> BotManager:
        return BotManager.from_env(_env((1, "tok-A", 111), (2, "tok-B", 222), (3, "tok-C", 333)))

    def test_get_bot_for_channel_none_when_free(self):
        pool = self._pool3()
        assert pool.get_bot_for_channel(999) is None

    def test_assign_picks_bot1_first(self):
        pool = self._pool3()
        bot = pool.assign_bot(voice_channel_id=1001)
        assert bot is not None
        assert bot.number == 1
        assert bot.voice_channel_id == 1001

    def test_assign_falls_through_when_bot1_busy(self):
        pool = self._pool3()
        pool.assign_bot(1001)           # Bot 1 → channel 1001
        bot = pool.assign_bot(1002)     # Bot 2 should be next
        assert bot is not None
        assert bot.number == 2
        assert bot.voice_channel_id == 1002

    def test_assign_fills_all_three(self):
        pool = self._pool3()
        b1 = pool.assign_bot(1001)
        b2 = pool.assign_bot(1002)
        b3 = pool.assign_bot(1003)
        assert b1 is not None and b1.number == 1
        assert b2 is not None and b2.number == 2
        assert b3 is not None and b3.number == 3

    def test_assign_returns_none_when_all_busy(self):
        pool = self._pool3()
        pool.assign_bot(1001)
        pool.assign_bot(1002)
        pool.assign_bot(1003)
        assert pool.all_busy is True
        assert pool.assign_bot(1004) is None

    def test_get_bot_for_channel_after_assign(self):
        pool = self._pool3()
        pool.assign_bot(1001)
        found = pool.get_bot_for_channel(1001)
        assert found is not None
        assert found.number == 1

    def test_release_frees_bot(self):
        pool = self._pool3()
        pool.assign_bot(1001)
        pool.release_bot(1001)
        assert pool.get_bot_for_channel(1001) is None
        # Bot 1 should be free again and claimable
        bot = pool.assign_bot(1002)
        assert bot is not None and bot.number == 1

    def test_release_nonexistent_channel_returns_none(self):
        pool = self._pool3()
        assert pool.release_bot(9999) is None

    def test_all_busy_false_when_free(self):
        pool = self._pool3()
        assert pool.all_busy is False

    def test_free_bots_and_occupied_bots(self):
        pool = self._pool3()
        pool.assign_bot(1001)
        free = pool.free_bots()
        occupied = pool.occupied_bots()
        assert len(free) == 2
        assert len(occupied) == 1
        assert occupied[0].number == 1


# ── Single-bot passthrough flag ───────────────────────────────────────────────

class TestSingleBotPassthrough:

    def test_assign_still_works_for_single_bot(self):
        pool = BotManager.from_env(_env((1, "tok-A", 111)))
        bot = pool.assign_bot(1001)
        assert bot is not None
        assert bot.number == 1

    def test_all_busy_single_bot(self):
        pool = BotManager.from_env(_env((1, "tok-A", 111)))
        pool.assign_bot(1001)
        assert pool.all_busy is True
        assert pool.assign_bot(1002) is None


# ── BotEntry directly ────────────────────────────────────────────────────────

class TestBotEntry:

    def test_is_free_when_no_channel(self):
        b = BotEntry(number=1, token="tok", application_id=123)
        assert b.is_free is True

    def test_is_free_false_when_assigned(self):
        b = BotEntry(number=1, token="tok", application_id=123, voice_channel_id=500)
        assert b.is_free is False
