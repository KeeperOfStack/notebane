# Notebane — YouTube Authentication (`/ytlogin`)

## Overview

Per-guild YouTube authentication for unlocking age-restricted videos and playlists larger than ~222 entries.

**Status:** ✅ Shipped. Pipeline + JS runtime + correct export procedure all in place.

## Commands

- `/ytlogin [browser]` — DMs per-browser export instructions (incognito-window required)
- `/ytstatus` — show whether this server has cookies configured
- `/ytlogout` — remove this server's cookies

## How to export cookies (critical)

You **must** use a private/incognito window. YouTube rotates session cookies on any normal browser window that's actively using youtube.com, which invalidates exported cookies within minutes.

1. Enable your cookie-export extension to run in private/incognito mode (browser-specific extension setting).
2. Open a **fresh incognito window** and sign in to YouTube there.
3. Export `cookies.txt` from the extension.
4. **Close the window WITHOUT logging out.** Logging out invalidates the session immediately; just closing the window leaves the cookies valid.
5. Upload `cookies.txt` as an attachment in any channel the bot can read.

## How it works

- **Per-guild cookies** stored at `/cookies/<guild_id>.orig.txt` (immutable source) and `/cookies/<guild_id>.txt` (working copy restored before each yt-dlp call — yt-dlp overwrites whatever cookiefile it's given).
- **Smart gating:** cookies are NOT sent for normal requests. They fire only on age-restriction retry or playlists ≥200 entries.
- **JS runtime (Deno) baked into the image** for yt-dlp's signature/n-challenge solver. Required to derive playable audio URLs.
- **yt-dlp nightly (`2026.6.29+`)** pinned so the explicit "cookies are no longer valid — likely been rotated" error reaches users when their export went stale. Stable releases buried this under a misleading "Sign in to confirm your age" message.
- **Volume `cookies/` is gitignored.** Never commit real cookies — the directory is in `.gitignore`.

## Diagnostic chain (for future debugging)

When `/play` on an age-restricted video fails with the auth error message, the actual cause is **one of**:

| Cause | Surface symptom (stable yt-dlp) | Real symptom (nightly yt-dlp) |
|---|---|---|
| No JS runtime | "Sign in to confirm your age" | `Signature solving failed: install a JS runtime` |
| Cookies clobbered by yt-dlp | "Sign in to confirm your age" | (varies) |
| Cookies exported from regular window | "Sign in to confirm your age" | `The provided YouTube account cookies are no longer valid. They have likely been rotated` |
| Cookies expired (months/years old) | "Sign in to confirm your age" | "Cookies have expired" |

Always run `yt-dlp -F` directly in the container as a first diagnostic — it surfaces the real warnings the regular extraction call buries.

## Files

- [`README.md`](README.md) — this file
- [`design.md`](design.md) — original option analysis
