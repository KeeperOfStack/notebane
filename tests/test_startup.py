"""Unit tests for Phase 2 — multi-bot startup / shutdown wiring.

All tests run offline (no Discord connection, no network).
They validate the contract between BotManager and the Notebane constructor,
and the graceful-shutdown / error-isolation behaviour of _run_bot.
"""

from __future__ import annotations

import asyncio
import sys
import types
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Pre-load heavy optional modules as mocks so that patch() can find them
# without needing real installs (yt-dlp, aiohttp, etc.)
# ---------------------------------------------------------------------------

def _ensure_mock_module(name: str) -> types.ModuleType:
    """Insert a bare MagicMock into sys.modules under *name* if not present."""
    if name not in sys.modules:
        sys.modules[name] = MagicMock()  # type: ignore[assignment]
    return sys.modules[name]  # type: ignore[return-value]

_ensure_mock_module("notebane.ytdl_updater")
_ensure_mock_module("notebane.ytdl_updater").start_ytdlp_updater = AsyncMock(return_value=None)


from notebane.bot_manager import BotEntry, BotManager
from notebane.__main__ import Notebane, _run_bot


# ── helpers ──────────────────────────────────────────────────────────────────

def _env(*pairs: tuple[int, str, int]) -> dict[str, str]:
    env: dict[str, str] = {}
    for number, token, app_id in pairs:
        env[f"BOT_{number:02d}_TOKEN"] = token
        env[f"BOT_{number:02d}_ID"] = str(app_id)
    return env


# ── BotManager ↔ Notebane wiring ─────────────────────────────────────────────

class TestBotManagerWiring:

    def test_bot_number_propagated(self):
        """Each Notebane instance must carry the number from its BotEntry."""
        pool = BotManager.from_env(_env((1, "tok-A", 111), (2, "tok-B", 222)))
        bots = []
        for entry in pool.bots:
            bot = Notebane(bot_number=entry.number, bot_manager=pool)
            entry.client = bot
            bots.append(bot)

        assert bots[0]._bot_number == 1
        assert bots[1]._bot_number == 2

    def test_bot_manager_reference_shared(self):
        """All Notebane instances must reference the same BotManager object."""
        pool = BotManager.from_env(_env((1, "tok-A", 111), (2, "tok-B", 222)))
        bots = []
        for entry in pool.bots:
            bot = Notebane(bot_number=entry.number, bot_manager=pool)
            entry.client = bot
            bots.append(bot)

        assert bots[0].bot_manager is pool
        assert bots[1].bot_manager is pool

    def test_entry_client_back_reference(self):
        """After wiring, each BotEntry.client must point to its Notebane."""
        pool = BotManager.from_env(_env((1, "tok-A", 111), (3, "tok-C", 333)))
        for entry in pool.bots:
            bot = Notebane(bot_number=entry.number, bot_manager=pool)
            entry.client = bot

        assert pool.bots[0].client._bot_number == 1
        assert pool.bots[1].client._bot_number == 3

    def test_single_bot_manager_is_none_fallback(self):
        """bot_manager=None (legacy path) must not crash Notebane.__init__."""
        bot = Notebane(bot_number=1, bot_manager=None)
        assert bot.bot_manager is None
        assert bot._bot_number == 1

    def test_pool_order_matches_bot_numbers(self):
        """BotManager always returns bots sorted by number — verify wiring preserves order."""
        pool = BotManager.from_env(_env((3, "tok-C", 333), (1, "tok-A", 111), (2, "tok-B", 222)))
        numbers = [b.number for b in pool.bots]
        assert numbers == [1, 2, 3]


# ── Metrics / updater — only Bot 1 ───────────────────────────────────────────

class TestMetricsOnlyOnBot1:
    """Only Bot 1 should have metrics/updater tasks; others should have None.

    We test this by running setup_hook with all heavy deps patched.
    The lazy-imported modules (metrics, ytdl_updater) are patched at their
    source path since setup_hook does a local import.
    """

    @pytest.mark.asyncio
    async def test_bot1_starts_metrics(self):
        bot = Notebane(bot_number=1, bot_manager=None)
        mock_task = MagicMock()

        async def _fake_start_metrics(b, p):
            return mock_task

        async def _fake_start_updater():
            return mock_task

        with (
            patch("notebane.__main__.Notebane.load_extension", new=AsyncMock()),
            patch("notebane.cookies.ensure_cookies_dir"),
            patch("notebane.restore_db.init_db"),
            patch("notebane.restore_db.purge_expired"),
            patch("notebane.playlist_db.init_playlist_tables"),
            patch("notebane.player.GuildPlayerManager"),
            patch("notebane.metrics.start_metrics_server", _fake_start_metrics),
            patch("notebane.ytdl_updater.start_ytdlp_updater", _fake_start_updater),
        ):
            await bot.setup_hook()

        assert bot._metrics_task is mock_task
        assert bot._ytdlp_updater_task is mock_task

    @pytest.mark.asyncio
    async def test_bot2_skips_metrics(self):
        bot = Notebane(bot_number=2, bot_manager=None)
        metrics_called = False

        async def _should_not_call(*a, **kw):
            nonlocal metrics_called
            metrics_called = True
            return MagicMock()

        with (
            patch("notebane.__main__.Notebane.load_extension", new=AsyncMock()),
            patch("notebane.cookies.ensure_cookies_dir"),
            patch("notebane.restore_db.init_db"),
            patch("notebane.restore_db.purge_expired"),
            patch("notebane.playlist_db.init_playlist_tables"),
            patch("notebane.player.GuildPlayerManager"),
            patch("notebane.metrics.start_metrics_server", _should_not_call),
            patch("notebane.ytdl_updater.start_ytdlp_updater", _should_not_call),
        ):
            await bot.setup_hook()

        assert not metrics_called
        assert bot._metrics_task is None
        assert bot._ytdlp_updater_task is None


# ── _run_bot error isolation ──────────────────────────────────────────────────

class TestRunBotErrorIsolation:
    """_run_bot must not suppress errors — they surface as exceptions in gather results."""

    @pytest.mark.asyncio
    async def test_run_bot_propagates_exception(self):
        """If start() raises, _run_bot lets the exception out so gather can log it."""
        bot = MagicMock()
        bot.__aenter__ = AsyncMock(return_value=bot)
        bot.__aexit__ = AsyncMock(return_value=False)
        bot.start = AsyncMock(side_effect=RuntimeError("bad token"))

        with pytest.raises(RuntimeError, match="bad token"):
            await _run_bot(bot, "fake-token")

    @pytest.mark.asyncio
    async def test_run_bot_calls_close_on_cancel(self):
        """When the task is cancelled, __aexit__ (close) still runs."""
        close_called = False

        async def _fake_start(token):
            await asyncio.sleep(9999)  # will be cancelled

        async def _fake_aexit(self_mock, exc_type, exc, tb):
            nonlocal close_called
            close_called = True
            return False

        bot = MagicMock()
        bot.__aenter__ = AsyncMock(return_value=bot)
        bot.__aexit__ = _fake_aexit
        bot.start = _fake_start

        task = asyncio.create_task(_run_bot(bot, "fake-token"))
        await asyncio.sleep(0)   # let it enter the async-with
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        assert close_called, "__aexit__ (close) must be called on cancellation"

    @pytest.mark.asyncio
    async def test_gather_continues_when_one_bot_fails(self):
        """return_exceptions=True: one bot erroring must not kill the others."""
        async def _bad_run(bot, token):
            raise RuntimeError("bad token")

        completed = []

        async def _good_run(bot, token):
            completed.append(token)

        bot_a = MagicMock()
        bot_b = MagicMock()

        results = await asyncio.gather(
            _bad_run(bot_a, "bad"),
            _good_run(bot_b, "good"),
            return_exceptions=True,
        )

        assert isinstance(results[0], RuntimeError)
        assert results[1] is None
        assert "good" in completed
