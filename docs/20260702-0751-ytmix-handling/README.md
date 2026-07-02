# Notebane — YouTube Mix Handling

**Status:** Complete ✅  
**Date:** 2026-07-02

## What Changed

### Problem
Right-clicking a track inside a YouTube auto-mix gives a URL like:
```
https://www.youtube.com/watch?v=vQA6wIoSIlg&list=RDxUc7LISGQl8&index=4
```
The `list=RD...` prefix caused yt-dlp to expand the entire mix even though the user only wanted that one video. Regular playlists (`list=PL...`) were already handled correctly by `noplaylist=True`.

### Fix — `strip_mix_context()` in `ytdl.py`
Applied at the top of `/play` and `/playnext` before the playlist routing decision. Detects YouTube radio/mix list prefixes (`RD`, `RDMM`, `RDCLAK`, `RDAMVM`) alongside a `v=` param and returns a clean `watch?v=ID` URL. All other URLs pass through unchanged.

### New — `/playytmix`
Explicitly opts into full mix loading. Bypasses `strip_mix_context` entirely. Same playlist path as `/play` with full JIT stub loading and the ≥200 track warning.

## URL Behaviour Reference

| URL | `/play` | `/playytmix` |
|---|---|---|
| `watch?v=X&list=RDY` | Single video ✅ | Full mix ✅ |
| `watch?v=X&list=RDMMY` | Single video ✅ | Full mix ✅ |
| `watch?v=X&list=PLY&index=2` | Full playlist ✅ | Full playlist ✅ |
| `/playlist?list=PLY` | Full playlist ✅ | Full playlist ✅ |
| `youtu.be/X` | Single video ✅ | Single video ✅ |
| Search term | Single result ✅ | Single result ✅ |

## Files Changed

| File | Change |
|---|---|
| `src/notebane/ytdl.py` | Added `strip_mix_context()`, `_MIX_LIST_PREFIXES`, `_VIDEO_ID_PARAM` |
| `src/notebane/cogs/music.py` | Applied strip in `/play` + `/playnext`; added `/playytmix` command |
| `docs/commands.md` | Updated `/play`, `/playnext` descriptions; added `/playytmix`; updated Tips |
