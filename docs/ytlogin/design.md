# Notebane — YouTube Auth Design (`/ytlogin`)

## Problem

yt-dlp's unauthenticated access to YouTube has two hard ceilings:

1. **Large playlists** — HTML scraping returns ~107 tracks; internal API (`youtubetab:skip=webpage`) returns ~222. Beyond that, YouTube requires a signed-in session. A 10,000-song playlist would return only a small fraction without auth.
2. **Age-restricted videos** — blocked entirely without auth. yt-dlp returns: `Sign in to confirm your age.`

**Confirmed tested:** `youtube.com/watch?v=7MBaEEODzU0` → hard fail without cookies.

---

## What YouTube Auth Actually Means for yt-dlp

yt-dlp dropped OAuth login in 2023. Username/password login is also unsupported for YouTube. The **only** supported auth method is:

> **`cookies.txt`** — a Netscape-format cookie file exported from a browser where the user is signed into YouTube.

yt-dlp reads the session cookies (`SID`, `SAPISID`, `__Secure-1PSID`, etc.) and uses them to authenticate requests exactly as a browser would. No API key needed, no rate limits.

---

## Cookie Lifetime

YouTube auth cookies are set with a **2-year expiry** from the time of login. In practice:

| Scenario | Lifetime |
|---|---|
| Normal use (active account) | ~2 years before forced re-auth |
| Google detects unusual usage (bot-like patterns) | Could invalidate earlier — weeks to months |
| Google security event on the account | Immediate invalidation |
| User logs out of that Google account manually | Immediate invalidation |

**Realistic expectation:** cookies from a dedicated bot account work for **6–18 months** before needing refresh, assuming normal usage patterns. A personal account used only for this tends to last longer.

**Recommendation:** use a **dedicated throwaway Google account** for the bot — not a personal account. If Google flags the IP for bot-like traffic, it won't touch the user's real account.

---

## Option Comparison

### Option A — Server-level cookies (admin only)

An admin drops a `cookies.txt` on the server and sets `YTDL_COOKIEFILE=/path/cookies.txt` in the bot's env. All users benefit automatically.

| | |
|---|---|
| **UX for users** | Transparent — no action required |
| **UX for admin** | One-time setup; re-export every ~6–18 months |
| **Smoothness** | ⭐⭐⭐⭐⭐ — zero friction for end users |
| **Risk** | One account used for all servers; Google sees all traffic from one identity |
| **Already wired** | ✅ `YTDL_COOKIEFILE` env var already exists in the bot |

**Implementation effort:** ~0 code changes. Just drop the file and set the env var.

---

### Option B — Per-user `/ytlogin` via OAuth device code flow (Discord-friendly)

Discord bots can't open browser windows, but **OAuth device code flow** works perfectly — it gives the user a short URL and a code to enter on their phone/browser, no redirect URI needed.

**Flow:**

```
User: /ytlogin
Bot:  ┌──────────────────────────────────────────────────┐
      │ 🔐 YouTube Login                                  │
      │                                                   │
      │ 1. Go to: https://accounts.google.com/device      │
      │ 2. Enter code: WXYZ-ABCD                          │
      │                                                   │
      │ Code expires in 30 minutes.                       │
      └──────────────────────────────────────────────────┘
      [ephemeral — only visible to you]

User completes login on phone/browser.

Bot:  ✅ Logged in as user@gmail.com. 
      Your session will be used for playlist and age-restricted content.
      [ephemeral]
```

**Technical reality check — this is blocked by yt-dlp:**

yt-dlp explicitly removed YouTube OAuth support in 2023. The extractor raises:
```
Login with OAuth is no longer supported.
```

Google deprecated the device code flow for YouTube Data API v3 consumer clients. The only path is cookies.

**Verdict:** ❌ Not feasible with yt-dlp as the auth layer.

---

### Option C — `/ytlogin` via bot-assisted cookie upload

Since OAuth is off the table, the next-smoothest user flow is helping users generate and upload their own `cookies.txt`:

**Flow:**

```
User: /ytlogin
Bot:  ┌──────────────────────────────────────────────────────┐
      │ 🔐 YouTube Login — How to connect your account        │
      │                                                       │
      │ 1. Install "Get cookies.txt LOCALLY" in Chrome/Brave  │
      │ 2. Go to youtube.com and sign in                      │
      │ 3. Click the extension → Export → save cookies.txt   │
      │ 4. Upload your cookies.txt file here:                 │
      │    (attach as a file to your next message)            │
      └──────────────────────────────────────────────────────┘
      [ephemeral]

User uploads cookies.txt as a Discord attachment.

Bot validates the file (checks for YouTube session cookies).

Bot:  ✅ Connected! Your session will be used for:
      • Full playlist access
      • Age-restricted content
      Expires in approximately 2 years (re-login if it stops working).
      [ephemeral]
```

**Per-user vs server-wide:**
- Simplest: store one cookies.txt per guild (server-level auth — anyone in the server benefits)
- Complex: store per Discord user ID (each user has their own session)

**Storage:** cookies.txt files go in a volume-mounted path like `/cookies/<guild_id>.txt`.

| | |
|---|---|
| **UX for users** | Medium friction — 3 steps, browser extension needed |
| **Smoothness** | ⭐⭐⭐ — doable but not seamless |
| **Credential lifetime** | 6–18 months realistically |
| **Implementation effort** | Moderate — `/ytlogin` command, Discord file attachment handling, cookie validation, path wiring to yt-dlp |

---

### Option D — Admin drops cookies + bot reloads without restart

Same as Option A but adds a `/ytcookies reload` admin command that hot-reloads the cookie file path without restarting the container. Useful for refresh cycles.

| | |
|---|---|
| **Smoothness** | ⭐⭐⭐⭐ for the admin; transparent for users |
| **Effort** | Small — one admin command + reload hook in ytdl.py |

---

## Recommendation

| Priority | Approach |
|---|---|
| **Now (zero effort)** | Option A — admin sets `YTDL_COOKIEFILE` in `.env`, exports cookies from a dedicated Google account. Works today. |
| **Later (low effort)** | Option D — add `/ytcookies reload` admin command for hot-swap without container restart |
| **If user self-service is needed** | Option C — `/ytlogin` with file attachment upload. Medium build, ~1 phase of work. |

OAuth device code flow (Option B) is off the table — yt-dlp does not support it for YouTube.

---

## Dedicated Account Setup Guide (for admin, Option A)

1. Create a new Google account (e.g. `notebane-bot@gmail.com`)
2. Sign into YouTube with it — watch a video or two to establish a non-bot session fingerprint
3. Install "Get cookies.txt LOCALLY" (Chrome/Brave/Edge) or equivalent
4. Export `cookies.txt` from youtube.com while signed in
5. Place on server: `/media/chasm/projects/notebane/cookies/youtube.txt`
6. Mount in docker-compose: `- ./cookies:/cookies:ro`
7. Set env: `YTDL_COOKIEFILE=/cookies/youtube.txt`
8. Redeploy: `docker compose -f docker-compose.prod.yml up -d --force-recreate`

**Refresh cycle:** check every 6 months. If playlist fetches start capping out again or age-restricted videos fail, re-export the cookie file and repeat steps 4–8.

---

## Open Questions

- [ ] Server-level vs per-user cookies? (server = simpler, per-user = privacy-respecting)
- [ ] Should `/ytlogin` validate the uploaded cookies.txt before accepting? (check for presence of `SAPISID` or `__Secure-1PSID`)
- [ ] Do we want a `/ytstatus` command to show whether auth is active and roughly when it might expire?
- [ ] Dedicated bot Google account vs personal account?
