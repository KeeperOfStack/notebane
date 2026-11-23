"""Playback canary — the bot periodically plays a few seconds of known videos
through its real pipeline, from its own network, and alerts the owner when
that stops working.

Pipeline under test (same functions the player uses):
    notebane.ytdl.resolve() → wait_until_available() → FFmpeg reads ~3s of audio

Env:
    CANARY_INTERVAL_HOURS   default 6; 0 disables the canary
    CANARY_URLS             comma-separated videos to test (defaults below)
    CANARY_FAIL_HEALTH      1 = /health returns 503 while the canary is failing

Only Bot 1 runs it. Results go to the log, Prometheus metrics (if
METRICS_PORT is set), the /canary endpoint, and the alert webhook.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import shlex
import time
from dataclasses import asdict, dataclass, field

log = logging.getLogger("notebane.canary")

# Long-lived, unlikely to be removed or region-locked.
DEFAULT_URLS = (
    "https://www.youtube.com/watch?v=jNQXAC9IVRw",  # "Me at the zoo" — first YouTube video
    "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
)
STARTUP_DELAY = 120       # seconds after startup before the first run
FFMPEG_TIMEOUT = 60       # seconds per FFmpeg check
SAMPLE_SECONDS = 3


@dataclass
class UrlResult:
    url: str
    ok: bool
    stage: str            # "ok" | "resolve" | "http 403" | "http <code>" | "ffmpeg" | "timeout"
    detail: str = ""
    client: str | None = None
    seconds: float = 0.0


@dataclass
class CanaryResult:
    ok: bool
    at: float
    ytdlp_version: str
    passed: int
    total: int
    results: list[UrlResult] = field(default_factory=list)

    @property
    def failed_stage(self) -> str | None:
        bad = [r.stage for r in self.results if not r.ok]
        return bad[0] if bad else None


# Last result, read by /canary and /health.
last_result: CanaryResult | None = None


def _interval_hours() -> float:
    try:
        return float(os.getenv("CANARY_INTERVAL_HOURS", "6"))
    except ValueError:
        log.warning("CANARY_INTERVAL_HOURS is not a number — using 6")
        return 6.0


def _urls() -> list[str]:
    raw = os.getenv("CANARY_URLS", "").strip()
    if not raw:
        return list(DEFAULT_URLS)
    return [u.strip() for u in raw.split(",") if u.strip()]


def fail_health() -> bool:
    return os.getenv("CANARY_FAIL_HEALTH", "0").strip().lower() in ("1", "true", "yes", "on")


def _ytdlp_version() -> str:
    try:
        import yt_dlp
        return yt_dlp.version.__version__  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001
        return "unknown"


def _classify_ffmpeg_error(stderr: str) -> str:
    m = re.search(r"HTTP error (\d{3})", stderr) or re.search(r"Server returned (\d{3})", stderr)
    return f"http {m.group(1)}" if m else "ffmpeg"


async def check_url(url: str) -> UrlResult:
    """Resolve one URL and pull a few seconds of audio exactly like the player."""
    from notebane import player
    from notebane.ytdl import resolve

    t0 = time.monotonic()
    try:
        track = await resolve(url, requester="canary")
    except Exception as exc:  # noqa: BLE001
        return UrlResult(url, False, "resolve", str(exc)[:300], seconds=time.monotonic() - t0)

    c = re.search(r"[?&]c=([^&]+)", track.url or "")
    client = c.group(1) if c else None

    await player.wait_until_available(track)
    argv = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin",
        *shlex.split(player.build_before_options(player.FFMPEG_BEFORE_OPTIONS, track.http_headers)),
        "-i", track.url, "-t", str(SAMPLE_SECONDS), "-vn", "-f", "null", "-",
    ]
    try:
        proc = await asyncio.create_subprocess_exec(
            *argv, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE,
        )
        try:
            _, err = await asyncio.wait_for(proc.communicate(), timeout=FFMPEG_TIMEOUT)
        except TimeoutError:
            proc.kill()
            await proc.wait()
            return UrlResult(url, False, "timeout", f"FFmpeg ran > {FFMPEG_TIMEOUT}s", client, time.monotonic() - t0)
    except Exception as exc:  # noqa: BLE001
        return UrlResult(url, False, "ffmpeg", str(exc)[:300], client, time.monotonic() - t0)

    if proc.returncode != 0:
        stderr = err.decode(errors="ignore")
        last = (stderr.strip().splitlines() or [""])[-1]
        # Strip the (long, signed) stream URL out of the message
        last = re.sub(r"https?://\S+", "<url>", last)[:300]
        return UrlResult(url, False, _classify_ffmpeg_error(stderr), last, client, time.monotonic() - t0)
    return UrlResult(url, True, "ok", "", client, time.monotonic() - t0)


async def run_once() -> CanaryResult:
    """Check every canary URL. The canary passes if at least one URL passes
    (a single video can be taken down; all of them failing means we're broken)."""
    results = [await check_url(u) for u in _urls()]
    passed = sum(r.ok for r in results)
    res = CanaryResult(
        ok=passed > 0, at=time.time(), ytdlp_version=_ytdlp_version(),
        passed=passed, total=len(results), results=results,
    )
    for r in results:
        log.log(
            logging.INFO if r.ok else logging.WARNING,
            "canary %s %s stage=%s client=%s %.1fs %s",
            "PASS" if r.ok else "FAIL", r.url, r.stage, r.client, r.seconds, r.detail,
        )
    _record_metrics(res)
    return res


def _record_metrics(res: CanaryResult) -> None:
    try:
        from notebane.metrics import record_canary
        record_canary(res.ok, res.at)
    except Exception:
        log.debug("canary metrics not recorded", exc_info=True)


def _describe(res: CanaryResult) -> str:
    lines = [f"**{res.passed}/{res.total}** test videos passed · yt-dlp `{res.ytdlp_version}`"]
    for r in res.results:
        mark = "✅" if r.ok else "❌"
        extra = f" — {r.detail}" if r.detail and not r.ok else ""
        lines.append(f"{mark} <{r.url}> · stage `{r.stage}` · client `{r.client or '?'}`{extra}")
    return "\n".join(lines)


async def _alert_on_change(prev: CanaryResult | None, res: CanaryResult) -> None:
    from notebane import alerts

    if prev is None:
        # First run after startup: confirms the webhook works and shows status.
        if res.ok:
            await alerts.send("canary", "Notebane started — playback canary passing", _describe(res), "ok", force=True)
        else:
            await alerts.send("canary", "Notebane canary failing after startup", _describe(res), "error", force=True)
    elif prev.ok and not res.ok:
        await alerts.send("canary", f"Notebane canary failing — stage `{res.failed_stage}`", _describe(res), "error", force=True)
    elif not prev.ok and res.ok:
        await alerts.send("canary", "Notebane canary recovered", _describe(res), "ok", force=True)
    elif not res.ok:
        # Still failing: remind at most once per rate-limit window.
        await alerts.send("canary", f"Notebane canary still failing — stage `{res.failed_stage}`", _describe(res), "error")


async def start_canary() -> asyncio.Task | None:
    """Start the periodic canary. Returns the Task (cancel on shutdown) or None if disabled."""
    hours = _interval_hours()
    if hours <= 0:
        log.info("playback canary disabled (CANARY_INTERVAL_HOURS=%s)", hours)
        return None

    async def _loop() -> None:
        global last_result
        await asyncio.sleep(STARTUP_DELAY)
        while True:
            try:
                res = await run_once()
                prev, last_result = last_result, res
                await _alert_on_change(prev, res)
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("canary run crashed")
            await asyncio.sleep(hours * 3600)

    task = asyncio.get_event_loop().create_task(_loop(), name="playback-canary")
    log.info("playback canary scheduled (every %sh, %d URL(s))", hours, len(_urls()))
    return task


def status() -> dict:
    """JSON-friendly snapshot for the /canary endpoint."""
    if last_result is None:
        return {"status": "pending" if _interval_hours() > 0 else "disabled"}
    d = asdict(last_result)
    d["status"] = "ok" if last_result.ok else "failing"
    return d
