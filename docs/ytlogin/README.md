# Notebane — YouTube Authentication (`/ytlogin`)

## Overview

This document covers the per-guild YouTube authentication feature — enabling full playlist access (beyond the ~222-track unauthenticated ceiling) and age-restricted video playback.

**Status:** ✅ Shipped (Phase 10). Live in production.

## Commands

- `/ytlogin [browser]` — DMs per-browser instructions for exporting `cookies.txt`. Drop the exported file in any channel the bot can read; it is validated and saved automatically.
- `/ytstatus` — show whether this server has cookies configured.
- `/ytlogout` — remove this server's cookies.

## How it works

- **Per-guild:** one upload benefits everyone in that server. Stored at `/cookies/<guild_id>.txt` (working copy) and `/cookies/<guild_id>.orig.txt` (immutable source — yt-dlp never sees this path).
- **Smart gating:** cookies are NOT used for ordinary requests. They fire only when:
  - A single track returns an age-restriction error → automatic retry with cookies.
  - A playlist returns ≥200 entries (the unauthenticated ceiling) → re-fetch with cookies to get the full list.
- **Default mode:** unauthenticated 222-track playlist ceiling, no cookies sent, looks like a normal browser to YouTube.
- **Cookie preservation:** yt-dlp overwrites whichever file it's given with a stripped-down copy. The original upload is preserved as `.orig.txt`; a fresh working copy is restored before each yt-dlp call.
- **Expiry handling:** when a cookied retry fails with another age-restriction error, the bot surfaces *"your cookies may have expired — run `/ytlogin` to upload fresh cookies"*.

## Files

- [`README.md`](README.md) — this file
- [`design.md`](design.md) — full option analysis, UX flows, cookie lifetime research
