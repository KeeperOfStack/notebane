#!/usr/bin/env python3
"""Run the bot's playback pipeline one step at a time, inside the container.

Every step uses the bot's real code/config (notebane.ytdl.YTDL_OPTS,
notebane.player.FFMPEG_BEFORE_OPTIONS, discord.py's FFmpegOpusAudio arg
builder), so what you see here is exactly what the bot does.

    docker exec -it <container> sh
    cd /app
    python scripts/pipeline_steps.py env
    python scripts/pipeline_steps.py resolve "https://www.youtube.com/watch?v=..."
    python scripts/pipeline_steps.py argv                 # exact ffmpeg argv the bot runs
    python scripts/pipeline_steps.py curl                 # hit the stream URL directly
    python scripts/pipeline_steps.py ffmpeg               # run the bot's ffmpeg cmd for 5s
    python scripts/pipeline_steps.py ytdlp-download       # let yt-dlp fetch it itself

`resolve` saves its result to /tmp/nb_track.json; later steps read it.
Stream URLs expire after a few hours, so re-run `resolve` if things go stale.
Add --verbose to `resolve` for yt-dlp's full debug log (client, JS runtime, etc.).
"""

from __future__ import annotations

import argparse
import json
import os
import shlex
import shutil
import subprocess
import sys

sys.path.insert(0, os.environ.get("PYTHONPATH", "/app/src").split(os.pathsep)[0])

STATE = "/tmp/nb_track.json"


def _run(cmd: list[str], **kw) -> int:
    print("\n$ " + shlex.join(cmd), flush=True)
    return subprocess.run(cmd, **kw).returncode


def _load() -> dict:
    if not os.path.exists(STATE):
        sys.exit(f"{STATE} not found. Run the `resolve` step first.")
    with open(STATE) as f:
        return json.load(f)


# ── step: env ────────────────────────────────────────────────────────────────
def cmd_env(_: argparse.Namespace) -> None:
    import yt_dlp

    print("python        :", sys.executable, sys.version.split()[0])
    print("yt-dlp module :", yt_dlp.version.__version__, "->", os.path.dirname(yt_dlp.__file__))
    print("yt-dlp CLI    :", shutil.which("yt-dlp"))
    try:
        import yt_dlp_ejs  # type: ignore
        print("yt-dlp-ejs    :", getattr(yt_dlp_ejs, "__version__", "?"), "->", yt_dlp_ejs.__file__)
    except Exception as e:
        print("yt-dlp-ejs    : NOT importable:", e)
    import discord
    print("discord.py    :", discord.__version__)
    for exe in ("deno", "ffmpeg"):
        print(f"{exe:<14}:", shutil.which(exe) or "NOT FOUND")
    print("uid/gid       :", os.getuid(), os.getgid(), " HOME =", os.environ.get("HOME"))

    _run(["deno", "--version"])
    _run(["sh", "-c", "ffmpeg -hide_banner -version | head -1"])
    # Is there a second copy (e.g. a --user install left by the auto-updater) shadowing /usr/local?
    _run([sys.executable, "-m", "pip", "list", "--user"])
    # What PyPI has right now. Compare with the version above.
    _run([sys.executable, "-m", "pip", "index", "versions", "yt-dlp"])
    _run([sys.executable, "-m", "pip", "index", "versions", "yt-dlp", "--pre"])
    _run([sys.executable, "-m", "pip", "index", "versions", "yt-dlp-ejs"])


# ── step: resolve ────────────────────────────────────────────────────────────
def cmd_resolve(a: argparse.Namespace) -> None:
    import yt_dlp
    from notebane.ytdl import YTDL_OPTS

    opts = dict(YTDL_OPTS)
    if a.cookies:
        opts["cookiefile"] = a.cookies
    if a.verbose:
        opts.update(quiet=False, no_warnings=False, verbose=True)
    if a.client:
        opts["extractor_args"] = {"youtube": {"player_client": a.client.split(",")}}

    print("yt-dlp", yt_dlp.version.__version__, "opts:", json.dumps(opts, indent=2))
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(a.url, download=False)
    if info and info.get("_type") == "playlist":
        info = (info.get("entries") or [None])[0]
    if not info:
        sys.exit("no info returned")

    url = info.get("url") or info.get("webpage_url")
    out = {
        "query": a.url,
        "title": info.get("title"),
        "format_id": info.get("format_id"),
        "ext": info.get("ext"),
        "url": url,
        "http_headers": info.get("http_headers") or {},
        "available_at": info.get("available_at"),
        "cookies": a.cookies,
    }
    with open(STATE, "w") as f:
        json.dump(out, f, indent=2)

    import re
    c = re.search(r"[?&]c=([^&]+)", url or "")
    print("\ntitle        :", out["title"])
    print("format       :", out["format_id"], out["ext"])
    print("client (c=)  :", c.group(1) if c else "?")
    print("http_headers :", json.dumps(out["http_headers"], indent=2))
    import time
    aa = out["available_at"]
    print("available_at :", aa, f"(URL returns 403 for another {aa - time.time():.1f}s)" if aa else "")
    print("saved ->", STATE)


# ── step: argv ───────────────────────────────────────────────────────────────
def _bot_argv(t: dict) -> list[str]:
    """Build ffmpeg argv exactly like player.py + discord.FFmpegOpusAudio do."""
    import discord.player as dp
    from notebane.player import FFMPEG_BEFORE_OPTIONS, FFMPEG_OPTIONS, build_before_options

    before_opts = build_before_options(FFMPEG_BEFORE_OPTIONS, t["http_headers"] or None)

    captured: list[str] = []

    class _Stop(Exception):
        pass

    def fake_spawn(self, args, **kw):
        captured.extend(args)
        raise _Stop

    orig = dp.FFmpegAudio._spawn_process
    dp.FFmpegAudio._spawn_process = fake_spawn
    dp.AudioSource.__del__ = lambda self: None  # silence cleanup on half-built object
    try:
        dp.FFmpegOpusAudio(t["url"], before_options=before_opts, options=FFMPEG_OPTIONS)
    except _Stop:
        pass
    finally:
        dp.FFmpegAudio._spawn_process = orig
    return captured


def _wait(t: dict, honour: bool) -> None:
    import time
    aa = t.get("available_at")
    left = (aa - time.time() + 0.5) if aa else 0
    if left > 0 and honour:
        print(f"waiting {left:.1f}s for available_at (as the bot does)")
        time.sleep(left)
    elif left > 0:
        print(f"NOT waiting: URL is still {left:.1f}s before available_at, expect 403")


def _show(argv: list[str]) -> None:
    for i, arg in enumerate(argv):
        print(f"  [{i:2}] {arg!r}" if len(arg) < 160 else f"  [{i:2}] {arg[:150]!r}...")


def cmd_argv(_: argparse.Namespace) -> None:
    t = _load()
    argv = _bot_argv(t)
    print("ffmpeg argv as the bot runs it (repr shows real CR/LF vs literal backslashes):")
    _show(argv)
    n = argv.count("-headers")
    if n > 1:
        print(f"\nNOTE: {n} separate -headers options. ffmpeg keeps only the LAST one,"
              " so earlier ones are dropped.")
    print("\nCopy-paste version:\n" + shlex.join(argv))


# ── step: curl ───────────────────────────────────────────────────────────────
def cmd_curl(a: argparse.Namespace) -> None:
    t = _load()
    _wait(t, not a.no_wait)
    base = ["curl", "-sS", "-o", "/dev/null", "-r", "0-65535", "--max-time", "15",
            "-w", "HTTP %{http_code}  bytes=%{size_download}\n"]
    _run(base + [t["url"]])
    hdrs = [x for k, v in t["http_headers"].items() for x in ("-H", f"{k}: {v}")]
    _run(base + hdrs + [t["url"]])


# ── step: ffmpeg ─────────────────────────────────────────────────────────────
def cmd_ffmpeg(a: argparse.Namespace) -> None:
    t = _load()
    _wait(t, not a.no_wait)
    argv = _bot_argv(t)
    argv = [x for x in argv if x != "pipe:1"]
    # More logging, cap length, write to file instead of discord's pipe.
    argv[argv.index("-loglevel") + 1] = "info"
    argv = argv[:1] + ["-y"] + argv[1:] + ["-t", str(a.seconds), "/tmp/nb_test.ogg"]
    rc = _run(argv)
    print(f"\nffmpeg exit code: {rc}")
    if rc == 0 and os.path.exists("/tmp/nb_test.ogg"):
        print("output:", os.path.getsize("/tmp/nb_test.ogg"), "bytes -> /tmp/nb_test.ogg")


# ── step: ytdlp-download ─────────────────────────────────────────────────────
def cmd_ytdlp_download(a: argparse.Namespace) -> None:
    t = _load()
    from notebane.ytdl import YTDL_OPTS
    cmd = ["yt-dlp", "-f", YTDL_OPTS["format"], "--no-playlist", "--source-address", "0.0.0.0",
           "--no-check-certificates", "-o", "/tmp/nb_direct.%(ext)s", "--force-overwrites"]
    if t.get("cookies"):
        cmd += ["--cookies", t["cookies"]]
    if a.verbose:
        cmd.append("-v")
    rc = _run(cmd + [t["query"]])
    print(f"\nyt-dlp exit code: {rc}")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="step", required=True)
    sub.add_parser("env", help="versions, PyPI latest, JS runtime").set_defaults(fn=cmd_env)
    r = sub.add_parser("resolve", help="yt-dlp extract_info with the bot's YTDL_OPTS")
    r.add_argument("url")
    r.add_argument("--cookies", help="cookies.txt path (bot only uses these for age-gated videos)")
    r.add_argument("--client", help="override player_client, e.g. web,tv,ios (experiment)")
    r.add_argument("-v", "--verbose", action="store_true")
    r.set_defaults(fn=cmd_resolve)
    sub.add_parser("argv", help="print the exact ffmpeg argv the bot builds").set_defaults(fn=cmd_argv)
    c = sub.add_parser("curl", help="GET the stream URL with and without yt-dlp's headers")
    c.add_argument("--no-wait", action="store_true", help="skip the available_at wait (shows the 403)")
    c.set_defaults(fn=cmd_curl)
    f = sub.add_parser("ffmpeg", help="run the bot's ffmpeg command for a few seconds")
    f.add_argument("--seconds", type=int, default=5)
    f.add_argument("--no-wait", action="store_true", help="skip the available_at wait (shows the 403)")
    f.set_defaults(fn=cmd_ffmpeg)
    d = sub.add_parser("ytdlp-download", help="yt-dlp downloads the track itself (no ffmpeg)")
    d.add_argument("-v", "--verbose", action="store_true")
    d.set_defaults(fn=cmd_ytdlp_download)
    a = p.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
