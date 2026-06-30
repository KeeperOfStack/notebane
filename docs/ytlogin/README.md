# Notebane — YouTube Authentication (`/ytlogin`)

## Overview

Per-guild YouTube authentication for unlocking age-restricted videos and playlists larger than ~222 entries.

**Status:** ⚠️ **Partially shipped — currently blocked.**

The upload pipeline, validation, per-guild storage, and smart retry logic all work. However, **cookies exported from a home browser are rejected by YouTube when replayed from the bot's server** because YouTube IP-binds session cookies. Diagnosed and documented 2026-06-30.

## What works

- `/ytlogin [browser]` — DMs per-browser export instructions
- Attachment upload listener — validates Netscape format and presence of YouTube auth cookies, then saves
- `/ytstatus`, `/ytlogout`
- Per-guild isolation at `/cookies/<guild_id>.txt`
- Smart gating — cookies never sent for normal requests; only on age-restriction retry or large-playlist re-fetch
- Cookie file preservation across yt-dlp calls (yt-dlp clobbers the cookiefile; we always restore from `.orig.txt`)
- Expiry-aware error messages

## What doesn't work

- **Playback of age-restricted videos** — YouTube returns `LOGIN_REQUIRED` from every player client even with valid cookies, because the session cookies were created on a different IP than the bot's egress IP.
- **Playlists >222 entries** — same root cause; auth required but server-side cookies aren't accepted.

## Root cause

YouTube IP-binds session cookies as anti-fraud. Cookies exported from your home browser (one IP) are treated as anonymous when sent from the Kratos server (different IP). Confirmed via direct request to `https://www.youtube.com/feed/library` using the uploaded cookie jar — YouTube returned the anonymous version of the page, with `LOGGED_IN":true` absent and the sign-in nudge present.

This is a known yt-dlp pitfall, documented in the yt-dlp wiki: cookies must come from a session created on the same machine/network as the one running yt-dlp.

## Path forward (pending decision)

1. **Server-side login via Playwright** — sign in to YouTube using a headless browser on Kratos itself; export cookies that are bound to the server's IP.
2. **Tailscale exit-node routing** — route the bot's outbound YouTube traffic through your home network so it matches the IP your cookies were created on.
3. **Persistent Chromium profile + `--cookies-from-browser`** — sign in once via VNC/X-forwarding, let yt-dlp read live cookies from a long-lived browser profile.
4. **PO-token provider plugin** — `bgutils-ytdlp-pot-provider` may bypass some age gates without full auth.
5. **Accept and document the limitation** — bot continues to work for non-age-restricted content and playlists ≤222 entries.

## Files

- [`README.md`](README.md) — this file
- [`design.md`](design.md) — original option analysis from research phase
