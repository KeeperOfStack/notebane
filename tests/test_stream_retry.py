"""Retry-once behaviour when a stream produces no audio (e.g. intermittent YouTube 403)."""

import asyncio
from unittest.mock import patch

import notebane.player as player_mod
from notebane.player import GuildPlayer, Track


class FakeSource:
    """Stands in for discord.FFmpegOpusAudio: yields `n` packets then ends."""

    def __init__(self, n: int) -> None:
        self._left = n

    def read(self) -> bytes:
        if self._left <= 0:
            return b""
        self._left -= 1
        return b"\x00" * 10

    def is_opus(self) -> bool:
        return True

    def cleanup(self) -> None:
        pass


class FakeVoiceClient:
    """Plays a source to completion synchronously, then reports disconnected
    once `plays_allowed` plays have happened so the play loop exits."""

    def __init__(self, plays_allowed: int, on_play=None) -> None:
        self.plays = 0
        self.plays_allowed = plays_allowed
        self.on_play = on_play

    class _G:
        id = 1

    class _C:
        id = 2

    guild = _G()
    channel = _C()

    def is_connected(self) -> bool:
        return self.plays < self.plays_allowed

    def is_playing(self) -> bool:
        return False

    def is_paused(self) -> bool:
        return False

    def play(self, source, after) -> None:
        self.plays += 1
        if self.on_play:
            self.on_play(self.plays)
        while source.read():
            pass
        after(None)

    def stop(self) -> None:
        pass


def _track(url: str) -> Track:
    return Track(title="t", url=url, webpage_url="https://youtu.be/x")


def _run(packets_per_attempt: list[int], on_play=None, plays_allowed: int | None = None):
    attempts = iter(packets_per_attempt)
    urls: list[str] = []

    def fake_ffmpeg(url, **kw):
        urls.append(url)
        return FakeSource(next(attempts))

    resolves: list[str] = []

    async def fake_resolve(q, requester="unknown", cookiefile=None, loop=None):
        resolves.append(q)
        return _track(f"fresh-{len(resolves)}")

    vc = FakeVoiceClient(plays_allowed or len(packets_per_attempt), on_play)
    gp = GuildPlayer(vc)  # type: ignore[arg-type]

    async def go():
        await gp.queue.put(_track("first"))
        await gp._play_loop()

    with patch.object(player_mod.discord, "FFmpegOpusAudio", side_effect=fake_ffmpeg), \
         patch("notebane.ytdl.resolve", side_effect=fake_resolve):
        asyncio.run(go())
    return urls, resolves, gp


def test_no_audio_retries_once_with_fresh_url():
    urls, resolves, _ = _run([0, 50])
    assert urls == ["first", "fresh-1"]
    assert resolves == ["https://youtu.be/x"]


def test_gives_up_after_one_retry():
    urls, resolves, _ = _run([0, 0])
    assert urls == ["first", "fresh-1"]
    assert len(resolves) == 1


def test_no_retry_when_audio_played():
    urls, resolves, _ = _run([50])
    assert urls == ["first"]
    assert resolves == []


def test_no_retry_when_user_skipped():
    holder: dict = {}

    def skip_on_first_play(n):
        if n == 1:
            holder["gp"]._interrupted = True  # what skip()/stop() set

    # Capture the player instance before play() fires.
    orig_init = GuildPlayer.__init__

    def init_capture(self, *a, **kw):
        orig_init(self, *a, **kw)
        holder["gp"] = self

    with patch.object(GuildPlayer, "__init__", init_capture):
        urls, resolves, _ = _run([0], on_play=skip_on_first_play, plays_allowed=1)
    assert urls == ["first"]
    assert resolves == []
