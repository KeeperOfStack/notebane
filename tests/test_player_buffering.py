"""Player integration tests for buffered playback lifecycle."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import discord
import pytest

from notebane import player as player_module
from notebane import ytdl
from notebane.player import GuildPlayer, Track


class _VoiceClient:
    def __init__(self):
        self.guild = SimpleNamespace(id=101)
        self.channel = SimpleNamespace(id=202)
        self.connected = True
        self.playing = False
        self.paused = False
        self.started = asyncio.Event()
        self.source = None
        self.after = None
        self.play_count = 0

    def is_connected(self):
        return self.connected

    def is_playing(self):
        return self.playing

    def is_paused(self):
        return self.paused

    def play(self, source, *, after):
        self.source = source
        self.after = after
        self.play_count += 1
        self.playing = True
        self.started.set()

    def finish(self, error=None):
        self.playing = False
        self.after(error)

    def stop(self):
        self.finish()

    async def disconnect(self, force=False):
        self.connected = False


@pytest.mark.asyncio
async def test_finite_track_uses_local_opus_file_and_cleans_it_after_playback(monkeypatch, tmp_path):
    voice = _VoiceClient()
    player = GuildPlayer(voice)
    track = Track(
        title="Buffered track",
        url="https://www.youtube.com/watch?v=buffered",
        webpage_url="https://www.youtube.com/watch?v=buffered",
        duration=120,
        requester="tester",
        resolved=False,
    )
    media_path = tmp_path / "track.webm"
    media_path.write_bytes(b"opus")
    media = SimpleNamespace(
        path=str(media_path),
        audio_codec="opus",
        cleanup=Mock(),
    )
    monkeypatch.setattr(ytdl, "resolve", AsyncMock(return_value=track))
    monkeypatch.setattr(
        ytdl,
        "prepare_track",
        AsyncMock(return_value=ytdl.PreparedTrack(track, media)),
        raising=False,
    )
    monkeypatch.setattr(
        ytdl,
        "resolve_fast_stream",
        AsyncMock(side_effect=ytdl.YTDLError("fast stream unavailable")),
        raising=False,
    )
    source = object()
    ffmpeg = Mock(return_value=source)
    monkeypatch.setattr(discord, "FFmpegOpusAudio", ffmpeg)
    monkeypatch.setattr("notebane.restore_db.save_snapshot", Mock())

    await player.queue.put(track)
    await player.start()
    await asyncio.wait_for(voice.started.wait(), timeout=1)

    ffmpeg.assert_called_once()
    assert ffmpeg.call_args.args[0] == str(media_path)
    assert ffmpeg.call_args.kwargs["codec"] == "copy"
    assert "before_options" not in ffmpeg.call_args.kwargs
    assert voice.source is source

    voice.finish()
    await asyncio.sleep(0.02)
    await player.stop()
    media.cleanup.assert_called_once()


@pytest.mark.asyncio
async def test_livestream_keeps_existing_direct_stream_path(monkeypatch):
    voice = _VoiceClient()
    player = GuildPlayer(voice)
    live = Track(
        title="Live",
        url="https://media.example/live-token",
        webpage_url="https://www.youtube.com/watch?v=live",
        duration=None,
        requester="tester",
        http_headers={"User-Agent": "test"},
        resolved=True,
    )
    media = SimpleNamespace(path="", audio_codec=None, cleanup=Mock())
    monkeypatch.setattr(
        ytdl,
        "prepare_track",
        AsyncMock(return_value=ytdl.PreparedTrack(live, None)),
        raising=False,
    )
    monkeypatch.setattr(
        ytdl,
        "resolve_fast_stream",
        AsyncMock(side_effect=ytdl.YTDLError("fast stream unavailable")),
        raising=False,
    )
    source = object()
    ffmpeg = Mock(return_value=source)
    monkeypatch.setattr(discord, "FFmpegOpusAudio", ffmpeg)
    monkeypatch.setattr("notebane.restore_db.save_snapshot", Mock())

    await player.queue.put(live)
    await player.start()
    await asyncio.wait_for(voice.started.wait(), timeout=1)

    assert ffmpeg.call_args.args[0] == live.url
    assert "before_options" in ffmpeg.call_args.kwargs
    assert "test" in ffmpeg.call_args.kwargs["before_options"]
    assert "codec" not in ffmpeg.call_args.kwargs

    voice.finish()
    await asyncio.sleep(0.02)
    await player.stop()
    media.cleanup.assert_not_called()


@pytest.mark.asyncio
async def test_next_finite_track_is_prefetched_once_while_current_plays(monkeypatch, tmp_path):
    voice = _VoiceClient()
    player = GuildPlayer(voice)
    first = Track("first", "https://youtube.com/watch?v=first01", "https://youtube.com/watch?v=first01", 60, resolved=True)
    second = Track("second", "https://youtube.com/watch?v=second1", "https://youtube.com/watch?v=second1", 60, resolved=True)
    third = Track("third", "https://youtube.com/watch?v=third001", "https://youtube.com/watch?v=third001", 60, resolved=True)
    fourth = Track("fourth", "https://youtube.com/watch?v=fourth01", "https://youtube.com/watch?v=fourth01", 60, resolved=True)
    media1 = SimpleNamespace(path=str(tmp_path / "first.webm"), audio_codec="opus", cleanup=Mock())
    media2 = SimpleNamespace(path=str(tmp_path / "second.webm"), audio_codec="opus", cleanup=Mock())
    media3 = SimpleNamespace(path=str(tmp_path / "third.webm"), audio_codec="opus", cleanup=Mock())
    media4 = SimpleNamespace(path=str(tmp_path / "fourth.webm"), audio_codec="opus", cleanup=Mock())
    (tmp_path / "first.webm").write_bytes(b"one")
    (tmp_path / "second.webm").write_bytes(b"two")
    (tmp_path / "third.webm").write_bytes(b"three")
    (tmp_path / "fourth.webm").write_bytes(b"four")

    async def prepare(track, **_kwargs):
        media = media1 if track is first else media2 if track is second else media3 if track is third else media4
        return ytdl.PreparedTrack(track, media)

    prepare_mock = AsyncMock(side_effect=prepare)
    fast_stream = SimpleNamespace(url="https://media.example/fast", http_headers=None)
    monkeypatch.setattr(ytdl, "prepare_track", prepare_mock, raising=False)
    monkeypatch.setattr(
        ytdl, "resolve_fast_stream", AsyncMock(return_value=fast_stream), raising=False
    )
    monkeypatch.setattr(discord, "FFmpegOpusAudio", Mock(side_effect=[object(), object(), object()]))
    monkeypatch.setattr("notebane.restore_db.save_snapshot", Mock())

    await player.queue.put(first)
    await player.queue.put(second)
    await player.queue.put(third)
    await player.queue.put(fourth)
    await player.start()
    await asyncio.wait_for(voice.started.wait(), timeout=1)
    await asyncio.sleep(0.02)

    assert prepare_mock.await_count == 2
    assert prepare_mock.await_args_list[1].args[0] is second

    voice.started.clear()
    voice.finish()
    await asyncio.wait_for(voice.started.wait(), timeout=1)
    assert voice.play_count == 2
    await asyncio.sleep(0.02)
    assert prepare_mock.await_count == 3
    assert prepare_mock.await_args_list[2].args[0] is third

    voice.started.clear()
    voice.finish()
    await asyncio.wait_for(voice.started.wait(), timeout=1)
    assert voice.play_count == 3
    await asyncio.sleep(0.02)
    assert prepare_mock.await_count == 4
    assert prepare_mock.await_args_list[3].args[0] is fourth

    await asyncio.sleep(0.02)
    await player.stop()
    media1.cleanup.assert_called_once()
    media2.cleanup.assert_called_once()
    media3.cleanup.assert_called_once()
    media4.cleanup.assert_called_once()


@pytest.mark.asyncio
async def test_playback_error_is_not_recorded_as_success_and_queue_advances(monkeypatch, tmp_path):
    voice = _VoiceClient()
    player = GuildPlayer(voice)
    first = Track("broken", "https://youtube.com/watch?v=broken01", "https://youtube.com/watch?v=broken01", 60, resolved=True)
    second = Track("next", "https://youtube.com/watch?v=next0001", "https://youtube.com/watch?v=next0001", 60, resolved=True)
    media1 = SimpleNamespace(path=str(tmp_path / "broken.webm"), audio_codec="opus", cleanup=Mock())
    media2 = SimpleNamespace(path=str(tmp_path / "next.webm"), audio_codec="opus", cleanup=Mock())
    (tmp_path / "broken.webm").write_bytes(b"first")
    (tmp_path / "next.webm").write_bytes(b"second")

    async def prepare(track, **_kwargs):
        return ytdl.PreparedTrack(track, media1 if track is first else media2)

    monkeypatch.setattr(ytdl, "prepare_track", AsyncMock(side_effect=prepare), raising=False)
    fast_stream = SimpleNamespace(url="https://media.example/fast", http_headers=None)
    monkeypatch.setattr(
        ytdl, "resolve_fast_stream", AsyncMock(return_value=fast_stream), raising=False
    )
    monkeypatch.setattr(discord, "FFmpegOpusAudio", Mock(side_effect=[object(), object(), object()]))
    monkeypatch.setattr("notebane.restore_db.save_snapshot", Mock())

    await player.queue.put(first)
    await player.queue.put(second)
    await player.start()
    await asyncio.wait_for(voice.started.wait(), timeout=1)
    await asyncio.sleep(0.02)

    voice.started.clear()
    voice.finish(RuntimeError("simulated fast-stream interruption"))
    await asyncio.wait_for(voice.started.wait(), timeout=1)
    assert voice.play_count == 2  # local fallback for the first track
    voice.started.clear()
    voice.finish(RuntimeError("simulated local-file failure"))
    await asyncio.wait_for(voice.started.wait(), timeout=1)

    assert voice.play_count == 3
    assert player.current is not None
    assert player.current.title == second.title
    assert player.current.url == second.webpage_url
    assert player.current.resolved is False
    assert list(player._history) == []
    media1.cleanup.assert_called_once()

    voice.finish()
    await asyncio.sleep(0.02)
    await player.stop()
    media2.cleanup.assert_called_once()


@pytest.mark.asyncio
async def test_fast_stream_starts_before_spool_and_resumes_from_spool_after_error(monkeypatch, tmp_path):
    voice = _VoiceClient()
    player = GuildPlayer(voice)
    track = Track(
        title="Hybrid track",
        url="https://www.youtube.com/watch?v=hybrid01",
        webpage_url="https://www.youtube.com/watch?v=hybrid01",
        duration=120,
        requester="tester",
    )
    media_path = tmp_path / "hybrid.webm"
    media_path.write_bytes(b"complete-opus-file")
    media = SimpleNamespace(path=str(media_path), audio_codec="opus", cleanup=Mock())
    fast_source = SimpleNamespace(
        url="https://media.example/fast-stream",
        http_headers={"User-Agent": "test"},
        is_live=False,
    )
    spool_ready = asyncio.Event()

    async def prepare(_track, **_kwargs):
        await spool_ready.wait()
        return ytdl.PreparedTrack(track, media)

    monkeypatch.setattr(ytdl, "prepare_track", AsyncMock(side_effect=prepare), raising=False)
    monkeypatch.setattr(ytdl, "resolve_fast_stream", AsyncMock(return_value=fast_source), raising=False)
    stream_audio = Mock()
    stream_audio.read.side_effect = [b"packet"] * 3
    stream_audio.is_opus.return_value = True
    local_audio = object()
    ffmpeg = Mock(side_effect=[stream_audio, local_audio])
    monkeypatch.setattr(discord, "FFmpegOpusAudio", ffmpeg)
    monkeypatch.setattr("notebane.restore_db.save_snapshot", Mock())

    await player.queue.put(track)
    await player.start()
    await asyncio.wait_for(voice.started.wait(), timeout=1)

    assert voice.play_count == 1
    assert voice.source is not media
    assert not spool_ready.is_set()
    for _ in range(3):
        voice.source.read()

    voice.started.clear()
    voice.finish(RuntimeError("simulated CDN interruption"))
    spool_ready.set()
    await asyncio.wait_for(voice.started.wait(), timeout=1)

    assert voice.play_count == 2
    assert ffmpeg.call_args_list[1].args[0] == str(media_path)
    assert "-ss 0.060" in ffmpeg.call_args_list[1].kwargs["before_options"]

    voice.finish()
    await asyncio.sleep(0.02)
    await player.stop()
    media.cleanup.assert_called_once()


def test_playback_error_logs_redacted_url(caplog):
    player = GuildPlayer(_VoiceClient())

    with caplog.at_level("ERROR", logger="notebane.player"):
        player._after_play(RuntimeError("403 https://cdn.example/audio?signature=secret-token"))

    assert "secret-token" not in caplog.text
    assert "<URL redacted>" in caplog.text


def test_stream_options_omit_unsupported_http_range_flags(monkeypatch):
    monkeypatch.setattr(player_module, "_ffmpeg_supports_bounded_http", lambda: False, raising=False)

    options = player_module._stream_before_options({"User-Agent": "test-agent"})

    assert "-request_size" not in options
    assert "-initial_request_size" not in options
    assert "User-Agent: test-agent" in options


def test_stream_options_enable_complete_bounded_http_support(monkeypatch):
    monkeypatch.setattr(player_module, "_ffmpeg_supports_bounded_http", lambda: True, raising=False)

    options = player_module._stream_before_options(None)

    assert "-request_size 1048576" in options
    assert "-initial_request_size 1048576" in options
    assert "-multiple_requests 1" in options
    assert "-short_seek_size 1048576" in options
