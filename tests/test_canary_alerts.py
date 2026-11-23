"""Playback canary state-change alerting and webhook alert behaviour."""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from notebane import alerts, canary
from notebane.canary import CanaryResult, UrlResult


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    alerts._last_sent.clear()
    canary.last_result = None
    monkeypatch.delenv("ALERT_WEBHOOK_URL", raising=False)
    monkeypatch.delenv("CANARY_INTERVAL_HOURS", raising=False)
    monkeypatch.delenv("CANARY_URLS", raising=False)
    yield


def _res(ok: bool, stage: str = "ok") -> CanaryResult:
    r = UrlResult("https://youtu.be/x", ok, stage if not ok else "ok", client="TVHTML5")
    return CanaryResult(ok=ok, at=0, ytdlp_version="2026.11.22", passed=int(ok), total=1, results=[r])


# ── alerts ───────────────────────────────────────────────────────────────────

def test_alerts_disabled_without_webhook():
    assert not alerts.enabled()
    assert asyncio.run(alerts.send("k", "t", "d")) is False


def test_rate_limit_and_force(monkeypatch):
    monkeypatch.setenv("ALERT_RATE_LIMIT_MINUTES", "60")
    assert alerts._should_send("k", force=False) is True
    assert alerts._should_send("k", force=False) is False   # within window
    assert alerts._should_send("other", force=False) is True  # separate key
    assert alerts._should_send("k", force=True) is True     # state changes bypass


def test_payload_never_pings_and_is_truncated():
    p = alerts._payload("x" * 500, "@everyone " + "y" * 5000, "error")
    assert p["allowed_mentions"] == {"parse": []}
    emb = p["embeds"][0]
    assert len(emb["title"]) <= 256 and len(emb["description"]) <= 4000
    assert emb["color"] == alerts.COLORS["error"]


# ── canary state changes ─────────────────────────────────────────────────────

def _alert_calls(prev, cur):
    sent = AsyncMock(return_value=True)
    with patch.object(alerts, "send", sent):
        asyncio.run(canary._alert_on_change(prev, cur))
    return sent.call_args_list


def test_first_run_always_reports():
    (call,) = _alert_calls(None, _res(True))
    assert "passing" in call.args[1] and call.args[3] == "ok" and call.kwargs["force"]
    (call,) = _alert_calls(None, _res(False, "http 403"))
    assert call.args[3] == "error"


def test_ok_to_fail_and_recovery_are_forced():
    (call,) = _alert_calls(_res(True), _res(False, "http 403"))
    assert "http 403" in call.args[1] and call.kwargs["force"]
    (call,) = _alert_calls(_res(False, "http 403"), _res(True))
    assert "recovered" in call.args[1] and call.kwargs["force"]


def test_still_failing_is_rate_limited_reminder():
    (call,) = _alert_calls(_res(False, "resolve"), _res(False, "resolve"))
    assert "still failing" in call.args[1] and not call.kwargs.get("force")


def test_still_ok_sends_nothing():
    assert _alert_calls(_res(True), _res(True)) == []


# ── config / helpers ─────────────────────────────────────────────────────────

def test_canary_disabled_at_zero(monkeypatch):
    monkeypatch.setenv("CANARY_INTERVAL_HOURS", "0")
    assert asyncio.run(canary.start_canary()) is None
    assert canary.status() == {"status": "disabled"}


def test_custom_urls(monkeypatch):
    monkeypatch.setenv("CANARY_URLS", " https://a , https://b ,,")
    assert canary._urls() == ["https://a", "https://b"]


def test_classify_ffmpeg_error():
    assert canary._classify_ffmpeg_error("[https @ 0x1] HTTP error 403 Forbidden") == "http 403"
    assert canary._classify_ffmpeg_error("Server returned 404 Not Found") == "http 404"
    assert canary._classify_ffmpeg_error("Invalid data found") == "ffmpeg"


def test_run_once_passes_if_any_url_passes(monkeypatch):
    monkeypatch.setenv("CANARY_URLS", "https://good,https://bad")

    async def fake_check(url):
        return UrlResult(url, url == "https://good", "ok" if url == "https://good" else "http 403")

    with patch.object(canary, "check_url", fake_check):
        res = asyncio.run(canary.run_once())
    assert res.ok and res.passed == 1 and res.total == 2
    assert res.failed_stage == "http 403"
