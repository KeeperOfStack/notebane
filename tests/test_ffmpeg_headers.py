"""FFmpeg header passing and yt-dlp version comparison."""

import shlex

from notebane.player import FFMPEG_BEFORE_OPTIONS, build_before_options
from notebane.ytdl_updater import _vtuple


def _split(opts: str) -> list[str]:
    # discord.FFmpegOpusAudio runs shlex.split over before_options
    return shlex.split(opts)


def test_no_headers_leaves_options_unchanged():
    assert build_before_options(FFMPEG_BEFORE_OPTIONS, None) == FFMPEG_BEFORE_OPTIONS
    assert build_before_options(FFMPEG_BEFORE_OPTIONS, {}) == FFMPEG_BEFORE_OPTIONS


def test_all_headers_in_single_option_with_real_crlf():
    headers = {
        "User-Agent": "com.google.android.apps.youtube.vr.oculus/1.65.10 (Linux; U; Android 12L)",
        "Accept": "*/*",
        "Accept-Language": "en-us,en;q=0.5",
    }
    argv = _split(build_before_options(FFMPEG_BEFORE_OPTIONS, headers))
    # ffmpeg keeps only the last -headers, so there must be exactly one
    assert argv.count("-headers") == 1
    value = argv[argv.index("-headers") + 1]
    assert value == "".join(f"{k}: {v}\r\n" for k, v in headers.items())
    assert "\\r\\n" not in value  # no literal backslashes
    assert argv[: argv.index("-headers")] == _split(FFMPEG_BEFORE_OPTIONS)


def test_header_values_with_quotes_survive_shlex():
    headers = {"User-Agent": "Weird \"UA\" 'x' $HOME"}
    argv = _split(build_before_options("", headers))
    assert argv == ["-headers", "User-Agent: Weird \"UA\" 'x' $HOME\r\n"]


def test_vtuple_compares_module_and_pypi_formats():
    assert _vtuple("2026.06.29.234344") == _vtuple("2026.6.29.234344.dev0")
    assert _vtuple("2026.11.20.101010.dev0") > _vtuple("2026.06.29.234344")
    assert _vtuple("2026.06.29") < _vtuple("2026.06.29.234344")


def test_wait_until_available(monkeypatch):
    import asyncio
    import time

    from notebane import player
    from notebane.player import Track, wait_until_available

    slept: list[float] = []

    async def fake_sleep(d):
        slept.append(d)

    monkeypatch.setattr(player.asyncio, "sleep", fake_sleep)
    mk = lambda aa: Track(title="t", url="u", webpage_url="w", available_at=aa)  # noqa: E731

    asyncio.run(wait_until_available(mk(None)))
    asyncio.run(wait_until_available(mk(time.time() - 10)))
    assert slept == []

    asyncio.run(wait_until_available(mk(time.time() + 4)))
    assert len(slept) == 1 and 4 <= slept[0] <= 4.6

    asyncio.run(wait_until_available(mk(time.time() + 999)))
    assert slept[-1] == player.MAX_AVAILABILITY_WAIT
