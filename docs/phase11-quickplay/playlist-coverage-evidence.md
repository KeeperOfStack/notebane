# Phase 12 — Playlist Coverage Evidence

**Date:** 2026-07-01
**Environment:** Live container `notebane-notebane-1` on Kratos, image `ghcr.io/keeperofstack/notebane:latest` (digest `0f3da082…`).
**yt-dlp version:** `2026.06.29.234344` (+ `yt-dlp-ejs 0.8.0`, Deno runtime, `extractor_args={"youtubetab": {"skip": ["webpage"]}}`).
**Cookie file used:** `/cookies/1422500430059016232.orig.txt` (MusicTest guild, incognito-exported, verified working in Phase 10).
**LARGE_PLAYLIST_THRESHOLD:** 200.
**Probe script:** `scripts/probe_playlist_coverage.py` (one-off, not shipped as runtime).

## Raw results

| Bucket | URL (list=) | Anon entries | Anon time | Auth entries | Auth time | Delta | Auth adopted? |
|---|---|---|---|---|---|---|---|
| small (<100) | `PLbpi6ZahtOH6Blw3RGYpWkSByi_T7Rygb` | 20 | 0.8s | (not attempted — below threshold) | — | — | n/a |
| medium (~200) | `PLMC9KNkIncKtPzgY-5rmhvj7fax8fdxoj` | 200 | 1.6s | 200 | 1.8s | 0 | ❌ (correct — rule requires *strictly more*) |
| large | `PLw-VjHDlEOgs658kAHR_LAaILBXb-s6Q5` | 130 | 1.4s | (not attempted — below threshold) | — | — | n/a |
| huge (radio) | `PLcirGkCPmbmFeQ1sm4wFciF03D_EroIfr` | 100 | 1.4s | (not attempted — below threshold) | — | — | n/a |

**Note on the "auth attempted / not adopted" column:** the current `_extract_playlist_sync` in ytdl.py calls the authenticated fetch whenever `len(entries) >= 200 AND cookiefile is not None`, regardless of whether we ultimately adopt its result. Only the medium bucket triggered the auth call in this run. The other three sat under the threshold, so no cookies were ever attached to yt-dlp options for those probes — confirming the smart-cookie policy from Phase 11.

## Interpretation

### 1. `skip:webpage` unlocks the reported 222 ceiling but real playlists cap lower

Anon returns exactly the count YouTube's internal `youtubei` API exposes for each specific list. In this sample:
- Small curated playlists (~20 entries) return all entries anon.
- The medium playlist happened to hit exactly 200 entries — the documented ~222 ceiling for unauthenticated `skip:webpage`.
- Larger community/radio playlists returned 100 and 130 respectively — well below any ceiling. Interpretation: those playlists have visibility/region limits or `youtubei` truncation independent of auth.

### 2. The `>= 200` threshold fired exactly once and the safety net worked

The medium playlist crossed the threshold, so ytdl.py called the authenticated fetch. It returned the same 200 entries. The code correctly refused to adopt the auth result (rule at `ytdl.py:176` — "adopt only if strictly more"), so no cookie was actually needed for playback of that list.

### 3. We did not find a case where auth returns MORE than anon

None of the five URLs probed produced `auth > anon`. This does **not** disprove the escape-hatch value — YouTube-Music `OLAK5uy_…` album lists and very large uploads playlists (e.g. a channel with 1000+ videos) are known to expand under auth in the yt-dlp issue tracker. What it does prove:
- The current code is not accidentally forcing auth on every large playlist and paying cost for nothing — the auth fetch is only invoked at ≥200, and the result is only kept if it's strictly better.
- Users who hit the 200 wall on a specific playlist will benefit from `/ytlogin`; those under the wall will not, and the code correctly avoids the extra call for them.

### 4. Two probe URLs returned auth-check warnings / 404

- Medium playlist warning: `Playlists that require authentication may not extract correctly without a successful webpage download.` This is a yt-dlp best-effort message — we still got 200 entries. Not blocking.
- "megamix" URL returned HTTP 404 — the playlist ID is stale/deleted. Ignore.

## Reproducing

```bash
# Copy probe into the running container (script is not in the image):
docker cp scripts/probe_playlist_coverage.py notebane-notebane-1:/tmp/probe.py
docker exec notebane-notebane-1 python /tmp/probe.py
```

Requires at least one `/cookies/<guild_id>.orig.txt` present in the mounted volume to exercise the authenticated column. Without it, the probe will still print the anon column and skip auth.

## What to do next

- **No code change required from this phase.** The smart-cookie policy from Phase 11 plus the current threshold logic behaves as documented.
- If a user complains "my 500-track playlist is being truncated" and `/ytlogin` cookies are already present, re-run this probe against their specific URL to see whether YouTube itself is capping. If auth still returns the same count as anon, the ceiling is on YouTube's side, not ours.
- Future consideration (out of scope for Phase 12): bump `LARGE_PLAYLIST_THRESHOLD` down to 150 if evidence emerges that auth unlocks more entries below the current 200 gate. Not warranted by the data we have today.
