# Notebane — YouTube Authentication (`/ytlogin`)

## Overview

Per-guild YouTube authentication for unlocking age-restricted videos and playlists larger than ~222 entries.

**Status:** ✅ Shipped. The cookie pipeline AND the JS runtime needed for stream-URL signature solving are both in place.

## Commands

- `/ytlogin [browser]` — DMs per-browser export instructions
- `/ytstatus` — show whether this server has cookies configured
- `/ytlogout` — remove this server's cookies

## How it works

- **Per-guild cookies** stored at `/cookies/<guild_id>.orig.txt` (immutable) and `/cookies/<guild_id>.txt` (working copy restored before each yt-dlp call).
- **Smart gating:** cookies are NOT sent for normal requests. They fire only when a single track fails with an age-restriction error, or when a playlist returns ≥200 entries (the unauthenticated ceiling).
- **JS runtime (Deno) baked into the image** for yt-dlp's signature/n-challenge solver — YouTube encrypts every stream URL with a JavaScript challenge that must be executed to derive the playable audio URL.
- **Expiry-aware errors:** if a cookied retry fails with another age-restriction error, the bot tells the user to re-run `/ytlogin`.

## The "Sign in to confirm your age" red herring

Until 2026-06-30, this error message led to multiple wrong diagnoses:
- "Cookies are clobbered" — true, fixed via `.orig.txt` preservation (`9ae936c`)
- "YouTube IP-binds cookies" — **false**; auth was actually working
- "Wrong player_client" — false; no client returned formats

**Real cause:** the Alpine container had no JavaScript runtime, so yt-dlp could not execute YouTube's signature/n-challenge. With cookies sending correctly and the user logged in, YouTube still returned only image storyboards because the challenge wasn't solved. `apk add deno` in the Dockerfile fixed it (`b423cb1`).

The `-F` (`--list-formats`) flag is the fastest diagnostic — it surfaces the explicit `Signature solving failed` warning that the regular error message hides.

## Files

- [`README.md`](README.md) — this file
- [`design.md`](design.md) — original option analysis (`/ytlogin` design space)
