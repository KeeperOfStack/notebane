"""Tests for full-track local buffering before Discord playback."""

from __future__ import annotations

from pathlib import Path

import pytest

from notebane import ytdl
from notebane.player import Track, _stable_track


class _FakeYDL:
    def __init__(self, opts):
        self.opts = opts
        self.did_download = False

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def extract_info(self, _query, download=False):
        assert download is False
        return {
            "id": "test-id",
            "title": "Buffered test track",
            "webpage_url": "https://www.youtube.com/watch?v=test-id",
            "url": "https://media.example/expiring-stream-token",
            "duration": 120,
            "thumbnail": "https://img.example/thumbnail.jpg",
            "http_headers": {"User-Agent": "test-agent"},
            "acodec": "opus",
            "format_id": "251",
        }

    def process_ie_result(self, info, download=True):
        assert download is True
        self.did_download = True
        output = self.opts["outtmpl"]
        output = output.replace("%(extractor)s", "youtube")
        output = output.replace("%(id)s", "test-id")
        output = output.replace("%(ext)s", "webm")
        path = Path(output)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"test opus payload")
        result = dict(info)
        result["filepath"] = str(path)
        result["requested_downloads"] = [{"filepath": str(path), "acodec": "opus"}]
        return result

    def prepare_filename(self, _info):
        raise AssertionError("prepared filepath should be returned by yt-dlp")


@pytest.mark.asyncio
async def test_finite_track_is_buffered_to_local_file_without_retaining_stream_url(monkeypatch):
    fake = _FakeYDL
    monkeypatch.setattr(ytdl.yt_dlp, "YoutubeDL", fake)
    source = Track(
        title="stale title",
        url="https://www.youtube.com/watch?v=test-id",
        webpage_url="https://www.youtube.com/watch?v=test-id",
        duration=120,
        requester="tester",
        resolved=False,
    )

    prepared = await ytdl.prepare_track(source)

    assert prepared.track.title == "Buffered test track"
    assert prepared.track.url == source.webpage_url
    assert prepared.track.resolved is False
    assert prepared.track.http_headers is None
    assert prepared.media is not None
    assert Path(prepared.media.path).read_bytes() == b"test opus payload"
    assert prepared.media.audio_codec == "opus"
    directory = Path(prepared.media.directory)
    prepared.media.cleanup()
    assert not directory.exists()


@pytest.mark.asyncio
async def test_live_track_stays_streamed_and_is_not_downloaded(monkeypatch):
    class LiveYDL(_FakeYDL):
        def __init__(self, opts):
            super().__init__(opts)
            self.did_download = False

        def extract_info(self, _query, download=False):
            return {
                "id": "live-id",
                "title": "Live broadcast",
                "webpage_url": "https://www.youtube.com/watch?v=live-id",
                "url": "https://media.example/live-stream-token",
                "duration": None,
                "is_live": True,
                "http_headers": {"User-Agent": "test-agent"},
            }

    monkeypatch.setattr(ytdl.yt_dlp, "YoutubeDL", LiveYDL)
    source = Track(
        title="live",
        url="https://www.youtube.com/watch?v=live-id",
        webpage_url="https://www.youtube.com/watch?v=live-id",
        duration=None,
        requester="tester",
        resolved=False,
    )

    prepared = await ytdl.prepare_track(source)

    assert prepared.media is None
    assert prepared.track.duration is None
    assert prepared.track.resolved is True
    assert prepared.track.http_headers == {"User-Agent": "test-agent"}


@pytest.mark.asyncio
async def test_cancelling_buffer_download_removes_its_temporary_directory(monkeypatch):
    import asyncio
    import threading
    import time

    started = threading.Event()
    finished = threading.Event()
    roots = []

    class BlockingYDL(_FakeYDL):
        def __init__(self, opts):
            super().__init__(opts)
            roots.append(Path(opts["outtmpl"]).parent.parent)

        def __exit__(self, *_args):
            finished.set()
            return False

        def process_ie_result(self, _info, download=True):
            assert download is True
            started.set()
            while True:
                for hook in self.opts["progress_hooks"]:
                    hook({"status": "downloading"})
                time.sleep(0.005)

    monkeypatch.setattr(ytdl.yt_dlp, "YoutubeDL", BlockingYDL)
    source = Track(
        title="cancel me",
        url="https://www.youtube.com/watch?v=test-id",
        webpage_url="https://www.youtube.com/watch?v=test-id",
        duration=120,
        requester="tester",
        resolved=False,
    )
    task = asyncio.create_task(ytdl.prepare_track(source))
    assert await asyncio.to_thread(started.wait, 1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert await asyncio.to_thread(finished.wait, 1)
    for _ in range(100):
        if roots and not roots[0].exists():
            break
        await asyncio.sleep(0.01)
    assert roots and not roots[0].exists()


@pytest.mark.asyncio
async def test_recent_resolved_stream_is_reused_without_second_extraction(monkeypatch):
    import time

    track = Track(
        title="fresh",
        url="https://media.example/audio?signature=do-not-persist",
        webpage_url="https://www.youtube.com/watch?v=fresh01",
        duration=90,
        http_headers={"User-Agent": "player"},
        resolved=True,
    )
    track.__dict__["_resolved_monotonic"] = time.monotonic()

    def unexpected_extract(*_args):
        raise AssertionError("fresh resolved stream should be reused")

    monkeypatch.setattr(ytdl, "_resolve_fast_stream_sync", unexpected_extract)
    fast = await ytdl.resolve_fast_stream(track)

    assert fast.url == track.url
    assert fast.http_headers == track.http_headers
    assert fast.duration == track.duration
    stable = _stable_track(track)
    assert stable.url == track.webpage_url
    assert stable.http_headers is None
    assert not hasattr(stable, "_resolved_monotonic")


@pytest.mark.asyncio
async def test_stale_resolved_stream_is_refreshed_from_stable_page(monkeypatch):
    import time
    from unittest.mock import Mock

    track = Track(
        title="stale",
        url="https://media.example/audio?signature=expired",
        webpage_url="https://www.youtube.com/watch?v=stale01",
        duration=90,
        resolved=True,
    )
    track.__dict__["_resolved_monotonic"] = time.monotonic() - ytdl.FAST_STREAM_URL_MAX_AGE - 1
    fresh = ytdl.FastStream(
        url="https://media.example/audio?signature=fresh",
        http_headers=None,
        duration=90,
        is_live=False,
        audio_codec="opus",
        video_codec="none",
        format_id="251",
    )
    extract = Mock(return_value=fresh)
    monkeypatch.setattr(ytdl, "_resolve_fast_stream_sync", extract)

    result = await ytdl.resolve_fast_stream(track, cookiefile="cookies.txt")

    assert result is fresh
    extract.assert_called_once_with(track.webpage_url, "cookies.txt")


@pytest.mark.asyncio
async def test_resolve_marks_direct_url_freshness_without_persisting_it(monkeypatch):
    import time
    from unittest.mock import Mock

    monkeypatch.setattr(
        ytdl,
        "_extract_sync",
        Mock(return_value={
            "url": "https://media.example/audio?signature=short-lived",
            "webpage_url": "https://www.youtube.com/watch?v=resolved1",
            "title": "Resolved",
            "duration": 45,
            "http_headers": {"User-Agent": "test"},
        }),
    )

    track = await ytdl.resolve("https://www.youtube.com/watch?v=resolved1")

    freshness = getattr(track, "_resolved_monotonic", None)
    assert isinstance(freshness, float)
    assert time.monotonic() - freshness < 1
    assert _stable_track(track).url == track.webpage_url
