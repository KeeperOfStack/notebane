"""BotManager — dynamic pool of numbered Discord bot clients.

Reads BOT_NN_TOKEN / BOT_NN_ID pairs from the environment (e.g.
BOT_01_TOKEN, BOT_01_ID, BOT_02_TOKEN, BOT_02_ID …) and manages
which bot is assigned to which voice channel.

Design rules enforced here:
  - Bot 1 is always the lowest-numbered configured bot.
  - Bot 1 is always preferred when assigning to a new channel.
  - When only one bot is configured, is_single_bot == True and
    all multi-bot paths are suppressed by callers.
  - No Discord clients are created in this module — callers inject
    them after pool construction so this module stays unit-testable.
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field
from typing import Any

log = logging.getLogger("notebane.bot_manager")

# Matches BOT_01_TOKEN, BOT_02_TOKEN, BOT_123_TOKEN …
_TOKEN_RE = re.compile(r"^BOT_(\d+)_TOKEN$")


@dataclass
class BotEntry:
    """Represents one bot in the pool.

    ``client`` is set to a discord.py client instance by the caller
    after the pool is constructed; it is None until then.
    ``voice_channel_id`` is None when the bot is free, or the ID of
    the voice channel it is currently occupying.
    """

    number: int                     # 1, 2, 3 … (from env var suffix)
    token: str                      # DISCORD bot token
    application_id: int             # Discord application/bot user ID
    client: Any = field(default=None, repr=False)   # discord.Client | None
    voice_channel_id: int | None = None             # None == free

    @property
    def is_free(self) -> bool:
        return self.voice_channel_id is None


class BotManager:
    """Manage a pool of N bots, routing voice-channel assignments.

    Usage
    -----
    pool = BotManager.from_env()          # parse env vars
    # caller injects clients:
    for entry in pool.bots:
        entry.client = make_discord_client()
    # routing:
    bot = pool.get_bot_for_channel(channel_id)   # bot already there, or None
    bot = pool.assign_bot(channel_id)            # claim a free bot (Bot 1 first)
    pool.release_bot(channel_id)                 # mark bot as free again
    """

    def __init__(self, bots: list[BotEntry]) -> None:
        if not bots:
            raise ValueError("BotManager requires at least one bot entry.")
        # Always sorted by number — Bot 1 is index 0, preferred on assignment.
        self._bots: list[BotEntry] = sorted(bots, key=lambda b: b.number)
        log.info(
            "BotManager initialised with %d bot(s): %s",
            len(self._bots),
            [b.number for b in self._bots],
        )

    # ── Properties ──────────────────────────────────────────────────────────

    @property
    def bots(self) -> list[BotEntry]:
        """Ordered list of all bots (Bot 1 first)."""
        return list(self._bots)

    @property
    def is_single_bot(self) -> bool:
        """True when only one bot is configured — callers suppress multi-bot UX."""
        return len(self._bots) == 1

    @property
    def count(self) -> int:
        return len(self._bots)

    # ── Construction ─────────────────────────────────────────────────────────

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> "BotManager":
        """Parse BOT_NN_TOKEN / BOT_NN_ID pairs from *env* (defaults to os.environ).

        Rules:
          - Both TOKEN and ID must be present for a slot to be included.
          - Gaps in numbering are silently skipped.
          - Numbering must start at 01 but can have any gaps (01, 03 = 2 bots).
          - If no valid pairs are found, falls back to the legacy
            DISCORD_TOKEN / DISCORD_APPLICATION_ID pair as Bot 1.
          - If neither multi-bot nor legacy vars exist, raises RuntimeError.
        """
        if env is None:
            env = dict(os.environ)

        entries: list[BotEntry] = []
        for key, token in env.items():
            m = _TOKEN_RE.match(key)
            if not m:
                continue
            number = int(m.group(1))
            id_key = f"BOT_{m.group(1)}_ID"
            app_id_str = env.get(id_key, "").strip()
            token = token.strip()
            if not token:
                log.warning("Skipping BOT_%02d: TOKEN is empty", number)
                continue
            if not app_id_str:
                log.warning("Skipping BOT_%02d: %s is missing or empty", number, id_key)
                continue
            try:
                app_id = int(app_id_str)
            except ValueError:
                log.warning("Skipping BOT_%02d: %s=%r is not an integer", number, id_key, app_id_str)
                continue
            entries.append(BotEntry(number=number, token=token, application_id=app_id))

        if entries:
            return cls(entries)

        # Legacy single-bot fallback
        legacy_token = env.get("DISCORD_TOKEN", "").strip()
        legacy_id_str = env.get("DISCORD_APPLICATION_ID", "").strip()
        if legacy_token:
            legacy_id = int(legacy_id_str) if legacy_id_str.isdigit() else 0
            log.info("No BOT_NN_* vars found — falling back to legacy DISCORD_TOKEN (Bot 1)")
            return cls([BotEntry(number=1, token=legacy_token, application_id=legacy_id)])

        raise RuntimeError(
            "No bot credentials found in environment. "
            "Set BOT_01_TOKEN + BOT_01_ID (and optionally BOT_02_TOKEN + BOT_02_ID …), "
            "or the legacy DISCORD_TOKEN variable."
        )

    # ── Routing ──────────────────────────────────────────────────────────────

    def get_bot_for_channel(self, voice_channel_id: int) -> BotEntry | None:
        """Return the bot currently assigned to *voice_channel_id*, or None."""
        for bot in self._bots:
            if bot.voice_channel_id == voice_channel_id:
                return bot
        return None

    def assign_bot(self, voice_channel_id: int) -> BotEntry | None:
        """Assign the next free bot to *voice_channel_id* and return it.

        Bot 1 (index 0) is always tried first. Returns None if all bots
        are occupied.
        """
        for bot in self._bots:          # sorted by number — Bot 1 is first
            if bot.is_free:
                bot.voice_channel_id = voice_channel_id
                log.info("Assigned Bot %d to voice channel %d", bot.number, voice_channel_id)
                return bot
        log.warning("All %d bot(s) are occupied — cannot assign to channel %d", len(self._bots), voice_channel_id)
        return None

    def release_bot(self, voice_channel_id: int) -> BotEntry | None:
        """Release the bot that was assigned to *voice_channel_id*.

        Returns the released BotEntry, or None if no bot was found there.
        """
        bot = self.get_bot_for_channel(voice_channel_id)
        if bot is not None:
            log.info("Released Bot %d from voice channel %d", bot.number, voice_channel_id)
            bot.voice_channel_id = None
        return bot

    def free_bots(self) -> list[BotEntry]:
        """Return all bots that are currently free (in Bot 1-first order)."""
        return [b for b in self._bots if b.is_free]

    def occupied_bots(self) -> list[BotEntry]:
        """Return all bots that are currently assigned to a channel."""
        return [b for b in self._bots if not b.is_free]

    @property
    def all_busy(self) -> bool:
        """True when every bot in the pool is occupied."""
        return all(not b.is_free for b in self._bots)
