"""Auth cog — /ytlogin, /ytlogout, /ytstatus."""

from __future__ import annotations

import logging

import discord
from discord import app_commands
from discord.ext import commands

from notebane.cookies import (
    delete_guild_cookies,
    get_guild_cookiefile,
    save_guild_cookies,
    validate_youtube_cookies,
)

log = logging.getLogger("notebane.auth")

# ─────────────────────────────────────────────────────────────────────────────
# Browser instructions (shown inside /ytlogin)
# ─────────────────────────────────────────────────────────────────────────────

_BROWSER_INSTRUCTIONS = {
    "chrome": (
        "**Google Chrome**\n"
        "1. Install [Get cookies.txt LOCALLY](https://chromewebstore.google.com/detail/get-cookiestxt-locally/cclelndahbckbenkjhflpdbgdldlbecc) from the Chrome Web Store\n"
        "2. Go to **youtube.com** and sign in\n"
        "3. Click the extension icon → **Export** → save as `cookies.txt`"
    ),
    "firefox": (
        "**Mozilla Firefox**\n"
        "1. Install [cookies.txt](https://addons.mozilla.org/firefox/addon/cookies-txt/) from Firefox Add-ons\n"
        "2. Go to **youtube.com** and sign in\n"
        "3. Click the extension icon → **Current Site** → save as `cookies.txt`"
    ),
    "edge": (
        "**Microsoft Edge**\n"
        "1. Install [Get cookies.txt LOCALLY](https://microsoftedge.microsoft.com/addons/detail/get-cookiestxt-locally/helleheikkohajgapgfgebkpcmagfmna) from the Edge Add-ons store\n"
        "2. Go to **youtube.com** and sign in\n"
        "3. Click the extension icon → **Export** → save as `cookies.txt`"
    ),
    "brave": (
        "**Brave Browser**\n"
        "1. Install [Get cookies.txt LOCALLY](https://chromewebstore.google.com/detail/get-cookiestxt-locally/cclelndahbckbenkjhflpdbgdldlbecc) from the Chrome Web Store (works in Brave)\n"
        "2. Go to **youtube.com** and sign in\n"
        "3. Click the extension icon → **Export** → save as `cookies.txt`"
    ),
    "safari": (
        "**Safari** (Mac only)\n"
        "1. Install [Cookie-Editor](https://apps.apple.com/app/cookie-editor/id1672011808) from the Mac App Store\n"
        "2. Go to **youtube.com** and sign in\n"
        "3. Open Cookie-Editor → click **Export** → choose **Netscape** format → save as `cookies.txt`"
    ),
}

_BROWSER_CHOICES = [
    app_commands.Choice(name="Chrome", value="chrome"),
    app_commands.Choice(name="Firefox", value="firefox"),
    app_commands.Choice(name="Edge", value="edge"),
    app_commands.Choice(name="Brave", value="brave"),
    app_commands.Choice(name="Safari", value="safari"),
]


def _instructions_embed(browser: str) -> discord.Embed:
    instructions = _BROWSER_INSTRUCTIONS.get(browser, _BROWSER_INSTRUCTIONS["chrome"])
    embed = discord.Embed(
        title="🔐 YouTube Login — Export Your Cookies",
        colour=discord.Colour.blurple(),
    )
    embed.add_field(name=f"Step-by-step for {browser.title()}", value=instructions, inline=False)
    embed.add_field(
        name="Step 4 — Upload here",
        value=(
            "Once you have `cookies.txt`, **reply to this message** (or send a new message in this channel) "
            "with the file **attached**.\n\n"
            "The bot will validate and save it automatically."
        ),
        inline=False,
    )
    embed.set_footer(text=(
        "🔒 Your cookies are stored only on this server's bot. "
        "They are never shared. Use a dedicated Google account if you prefer."
    ))
    return embed


# ─────────────────────────────────────────────────────────────────────────────
# Cog
# ─────────────────────────────────────────────────────────────────────────────

class AuthCog(commands.Cog, name="Auth"):
    """YouTube account linking commands."""

    def __init__(self, bot: commands.AutoShardedBot) -> None:
        self.bot = bot
        # Track which guilds are in the middle of a /ytlogin flow (waiting for attachment)
        self._pending: set[tuple[int, int]] = set()  # (guild_id, user_id)

    # ── /ytlogin ─────────────────────────────────────────────────────────────

    @app_commands.command(name="ytlogin", description="Link a YouTube account to unlock large playlists and age-restricted content.")
    @app_commands.describe(browser="Which browser you'll use to export cookies")
    @app_commands.choices(browser=_BROWSER_CHOICES)
    async def ytlogin(self, interaction: discord.Interaction, browser: str = "chrome") -> None:
        if not interaction.guild:
            await interaction.response.send_message("❌ Server-only command.", ephemeral=True)
            return

        key = (interaction.guild.id, interaction.user.id)
        self._pending.add(key)

        embed = _instructions_embed(browser)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ── /ytlogout ────────────────────────────────────────────────────────────

    @app_commands.command(name="ytlogout", description="Remove the linked YouTube account from this server.")
    async def ytlogout(self, interaction: discord.Interaction) -> None:
        if not interaction.guild:
            await interaction.response.send_message("❌ Server-only command.", ephemeral=True)
            return

        removed = delete_guild_cookies(interaction.guild.id)
        if removed:
            await interaction.response.send_message(
                "✅ YouTube account unlinked. The bot will use default (unauthenticated) access.",
                ephemeral=True,
            )
        else:
            await interaction.response.send_message(
                "ℹ️ No YouTube account was linked to this server.",
                ephemeral=True,
            )

    # ── /ytstatus ────────────────────────────────────────────────────────────

    @app_commands.command(name="ytstatus", description="Check whether a YouTube account is linked to this server.")
    async def ytstatus(self, interaction: discord.Interaction) -> None:
        if not interaction.guild:
            await interaction.response.send_message("❌ Server-only command.", ephemeral=True)
            return

        cookiefile = get_guild_cookiefile(interaction.guild.id)
        if cookiefile:
            embed = discord.Embed(
                title="🔐 YouTube — Linked",
                description=(
                    "✅ A YouTube account is linked to this server.\n"
                    "Large playlists and age-restricted content are unlocked.\n\n"
                    "Use `/ytlogout` to remove it."
                ),
                colour=discord.Colour.green(),
            )
        else:
            embed = discord.Embed(
                title="🔓 YouTube — Not Linked",
                description=(
                    "No YouTube account is linked. The bot uses unauthenticated access "
                    "(up to ~222 tracks per playlist).\n\n"
                    "Use `/ytlogin` to link an account."
                ),
                colour=discord.Colour.greyple(),
            )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ── Attachment listener ───────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        """Watch for cookies.txt attachments from users who ran /ytlogin."""
        if message.author.bot:
            return
        if not message.guild:
            return
        if not message.attachments:
            return

        key = (message.guild.id, message.author.id)
        if key not in self._pending:
            return

        # Find a .txt attachment
        txt_attachments = [a for a in message.attachments if a.filename.endswith(".txt")]
        if not txt_attachments:
            return  # not our file yet — keep waiting

        attachment = txt_attachments[0]

        # Size guard — a real cookies.txt is rarely over 500KB
        if attachment.size > 512_000:
            self._pending.discard(key)
            await message.reply(
                "❌ That file is too large to be a valid cookies.txt (max 500KB).",
                mention_author=False,
            )
            return

        try:
            raw = await attachment.read()
            content = raw.decode("utf-8")
        except Exception as exc:
            log.warning("Failed to read cookie attachment: %s", exc)
            self._pending.discard(key)
            await message.reply("❌ Could not read that file. Make sure it's a text file.", mention_author=False)
            return

        # Validate
        ok, reason = validate_youtube_cookies(content)
        if not ok:
            self._pending.discard(key)
            await message.reply(f"❌ Invalid cookies file: {reason}", mention_author=False)
            return

        # Save
        save_guild_cookies(message.guild.id, content)
        self._pending.discard(key)

        embed = discord.Embed(
            title="✅ YouTube Account Linked",
            description=(
                "Your cookies have been saved for this server.\n\n"
                "**Unlocked:**\n"
                "• Full large playlist access\n"
                "• Age-restricted content\n\n"
                "Use `/ytlogout` to remove at any time."
            ),
            colour=discord.Colour.green(),
        )
        embed.set_footer(text="Cookies expire ~2 years from when you exported them. Re-run /ytlogin if playback stops working.")
        await message.reply(embed=embed, mention_author=False)


async def setup(bot: commands.AutoShardedBot) -> None:
    await bot.add_cog(AuthCog(bot))
