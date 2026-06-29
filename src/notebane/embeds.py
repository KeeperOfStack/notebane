"""Shared embed builders used across all cogs."""

from __future__ import annotations

import discord


# ──────────────────────────────────────────────────────────────────────────────
# Generic helpers
# ──────────────────────────────────────────────────────────────────────────────

def error(description: str, *, title: str = "Error") -> discord.Embed:
    """Red error embed."""
    return discord.Embed(title=f"❌ {title}", description=description, colour=discord.Colour.red())


def success(description: str, *, title: str = "Done") -> discord.Embed:
    """Green success embed."""
    return discord.Embed(title=f"✅ {title}", description=description, colour=discord.Colour.green())


def info(description: str, *, title: str = "Info") -> discord.Embed:
    """Blurple info embed."""
    return discord.Embed(title=f"ℹ️ {title}", description=description, colour=discord.Colour.blurple())
