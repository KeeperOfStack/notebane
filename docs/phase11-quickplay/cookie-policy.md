# Notebane — Smart Cookie Policy

**Status:** enforceable contract as of Phase 11 (2026-07-01).
**Scope:** `src/notebane/ytdl.py`. Any change to cookie behaviour outside these rules is a regression.

## Design intent

Cookies belong to a specific user, uploaded via `/ytlogin`. They are a **retry escape hatch**, never a default. The bot must always try YouTube the way a fresh visitor would first. Cookies are attached only when the unauthenticated attempt provably cannot succeed.

Reasons this matters:

- Sending a signed-in fingerprint on every request marks the bot's IP + cookie pair as a heavy consumer and increases the odds YouTube rotates the cookie or issues a challenge — which then breaks *every* guild that shares the account. Fewer signed-in requests → longer cookie lifetime.
- Public content should never depend on a specific user's account. If the anon path works, the code path is portable across guilds and outages.
- Age-gate and large-playlist auth are the two documented cases where the anon path demonstrably can't return the right answer. Everything else must not touch cookies.

## The two triggers (the only two)

### Trigger 1 — Age-restricted single video

Location: `_extract_sync()` in `src/notebane/ytdl.py`.

1. Always call `ydl.extract_info(query)` with no `cookiefile`.
2. On exception, check `_is_age_restricted_error(exc)`.
3. If **and only if** that returns `True` and a `cookiefile` was passed in, retry once with cookies attached.
4. Any other exception class → re-raise as `YTDLError`; no cookie retry.

Normal videos, private-but-not-age-gated videos, region-locked videos, deleted videos, and network errors all **fail without ever sending cookies**. This is deliberate — cookies won't fix any of those cases and sending them just burns the token.

### Trigger 2 — Large playlist coverage

Location: `_extract_playlist_sync()` in `src/notebane/ytdl.py`.

1. Always do the unauthenticated flat-extract first, with `extractor_args={"youtubetab": {"skip": ["webpage"]}}` (uses YouTube's internal API and returns ~222 entries max unauthenticated).
2. **If** `len(entries) >= LARGE_PLAYLIST_THRESHOLD` (200) **AND** a `cookiefile` was passed in, re-fetch with cookies.
3. Adopt the authenticated result **only** if it returned strictly more entries than the anon result. Otherwise stick with anon.

Playlists under 200 entries never touch the cookie file. Playlists at or above 200 spend one authenticated call to unlock the remaining tail (~500+ authenticated ceiling).

## Code-pointer table

| Rule | File | Lines | Symbol |
|---|---|---|---|
| Age-gate hint set | `src/notebane/ytdl.py` | 42–58 | `_AGE_RESTRICTION_HINTS` |
| Invalid-cookie hint set | `src/notebane/ytdl.py` | 60–66 | `_INVALID_COOKIES_HINTS` / `_is_invalid_cookies_error` |
| Age-gate classifier | `src/notebane/ytdl.py` | 69–70 | `_is_age_restricted_error` |
| Large-playlist threshold | `src/notebane/ytdl.py` | 73–74 | `LARGE_PLAYLIST_THRESHOLD = 200` |
| Anon-first single track | `src/notebane/ytdl.py` | 85–89 | `_extract_sync` first `extract_info` call |
| Age-gate cookie retry | `src/notebane/ytdl.py` | 92–111 | `if cookiefile and _is_age_restricted_error(exc)` |
| Anon-first playlist | `src/notebane/ytdl.py` | 166–167 | `_fetch({})` |
| Large-playlist cookie retry | `src/notebane/ytdl.py` | 170–178 | `if cookiefile and len(entries) >= LARGE_PLAYLIST_THRESHOLD` |

## Grep audit

If you added a new code path that touches cookies, this grep must still return only the callsites listed above:

```bash
grep -rn "cookiefile" src/notebane/
```

Expected (as of 2026-07-01) — the only lines that **attach** `cookiefile` to a yt-dlp options dict are exactly two:

1. `src/notebane/ytdl.py:95` — `opts_auth["cookiefile"] = cookiefile` (age-gate retry).
2. `src/notebane/ytdl.py:175` — `_fetch({"cookiefile": cookiefile})` (large-playlist retry).

Plus a single global-fallback in `src/notebane/__main__.py:87` — `_ytdl.YTDL_OPTS["cookiefile"] = cookiefile` — which is only set if the operator explicitly configures a `YTDL_COOKIEFILE` env var (bot-wide fallback for single-guild deployments; unset in the standard multi-guild `/ytlogin` mode).

All other `cookiefile` mentions in the tree are **plumbing** — function signatures, keyword argument passthroughs from `resolve` / `resolve_playlist` / `_enqueue_playlist_bg` down to the two attachment sites, and the `get_guild_cookiefile` lookup helper. They do not themselves send cookies to yt-dlp.

A third attachment site means someone added a new cookie codepath. Either update this document to add a third trigger with an explicit design justification, or remove the new codepath.

To audit just attachment sites specifically:

```bash
grep -rn 'cookiefile"\] *=\|cookiefile":' src/notebane/
```

That grep should return exactly the three lines listed above.

## Assertions to re-run manually

Until we have a fixture-based unit test, these hold today and must keep holding:

1. `_extract_sync("https://any-non-age-gated-url", cookiefile="/tmp/nonexistent")` — cookies never touched, because the anon call succeeds. Verify by pointing `cookiefile` at a garbage path; if it were attached on the first call, yt-dlp would raise on the missing file.
2. `_extract_playlist_sync("small-playlist-url", cookiefile="/tmp/nonexistent")` where the playlist has < 200 entries — same argument, cookies never touched.
3. `_extract_playlist_sync("large-playlist-url", cookiefile=None)` — returns whatever the anon ceiling provides; never raises purely because cookies are absent.
4. `_extract_sync("age-restricted-url", cookiefile=None)` — raises `YTDLError` with the `/ytlogin` hint, does NOT silently succeed with an image-only storyboard fallback.

## What this policy explicitly does NOT allow

- Attaching cookies to *every* request "just to be safe."
- Using cookies to bypass rate limits, region locks, or private-video errors.
- Preferring the authenticated playlist result when it returns the same or fewer entries than anon.
- Sending cookies during search queries (`ytsearch:...`). Search is always anon.
- Sending cookies for `/queue` inspection, metadata refresh, or any read-only operation that isn't `_extract_sync` / `_extract_playlist_sync`.

If a future feature genuinely needs a third trigger, it must land alongside an update to this document naming the new trigger, the failure mode it addresses, and the corresponding code-pointer row.
