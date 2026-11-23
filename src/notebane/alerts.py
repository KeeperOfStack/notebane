"""Owner alerts via a Discord webhook.

Set ALERT_WEBHOOK_URL to a channel webhook (Channel settings → Integrations →
Webhooks → New Webhook → Copy Webhook URL). No bot account is involved: the
bot simply POSTs a message to that URL. Unset = alerts disabled (log only).

Alerts are rate-limited per key (ALERT_RATE_LIMIT_MINUTES, default 60) so a
recurring problem produces one message an hour, not one per track. Sending
never raises and never blocks playback.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time

log = logging.getLogger("notebane.alerts")

COLORS = {"error": 0xE74C3C, "warning": 0xF1C40F, "ok": 0x2ECC71, "info": 0x3498DB}
ICONS = {"error": "🔴", "warning": "🟡", "ok": "✅", "info": "ℹ️"}

_last_sent: dict[str, float] = {}
_pending: set[asyncio.Task] = set()


def webhook_url() -> str:
    return os.getenv("ALERT_WEBHOOK_URL", "").strip()


def enabled() -> bool:
    return bool(webhook_url())


def _rate_limit_seconds() -> float:
    try:
        return max(0.0, float(os.getenv("ALERT_RATE_LIMIT_MINUTES", "60"))) * 60
    except ValueError:
        return 3600.0


def _should_send(key: str, force: bool) -> bool:
    now = time.monotonic()
    last = _last_sent.get(key)
    if not force and last is not None and now - last < _rate_limit_seconds():
        return False
    _last_sent[key] = now
    return True


def _payload(title: str, description: str, level: str) -> dict:
    return {
        "username": "Notebane Alerts",
        "allowed_mentions": {"parse": []},  # never ping anyone from log text
        "embeds": [{
            "title": f"{ICONS.get(level, '')} {title}"[:256],
            "description": description[:4000],
            "color": COLORS.get(level, COLORS["info"]),
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }],
    }


async def send(key: str, title: str, description: str, level: str = "error", *, force: bool = False) -> bool:
    """Post an alert now. Returns True if it was delivered.

    `key` groups alerts for rate limiting; `force` bypasses the limit (used
    for state changes like canary recovery, which are rare by nature).
    """
    url = webhook_url()
    if not url:
        return False
    if not _should_send(key, force):
        log.debug("alert %r rate-limited", key)
        return False
    try:
        import aiohttp  # type: ignore[import-untyped]

        timeout = aiohttp.ClientTimeout(total=10)
        async with (
            aiohttp.ClientSession(timeout=timeout) as session,
            session.post(url, json=_payload(title, description, level)) as resp,
        ):
            if resp.status >= 300:
                log.warning("alert webhook returned HTTP %d for %r", resp.status, key)
                return False
        return True
    except Exception as exc:  # noqa: BLE001 — alerts must never break the bot
        log.warning("alert webhook failed for %r: %s", key, exc)
        return False


def notify(key: str, title: str, description: str, level: str = "error", *, force: bool = False) -> None:
    """Fire-and-forget version of send() for code running on the event loop."""
    if not enabled():
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return  # not on the event loop (e.g. a voice thread) — skip quietly
    task = loop.create_task(send(key, title, description, level, force=force))
    _pending.add(task)
    task.add_done_callback(_pending.discard)
