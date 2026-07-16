import time

from riff.core.stream import StreamResolver


def test_pick_audio_url_prefers_direct():
    info = {"url": "direct", "vcodec": "none", "acodec": "opus",
            "formats": [{"acodec": "opus", "url": "other", "vcodec": "none"}]}
    assert StreamResolver._pick_audio_url(info) == "direct"


def test_pick_audio_url_best_audio_bitrate():
    info = {
        "formats": [
            {"acodec": "mp4a", "abr": 128, "url": "mid", "vcodec": "none"},
            {"acodec": "none", "abr": 999, "url": "video-only", "vcodec": "avc1"},
            {"acodec": "opus", "abr": 160, "url": "best", "vcodec": "none"},
            {"acodec": "opus", "abr": 64, "url": "low", "vcodec": "none"},
        ]
    }
    assert StreamResolver._pick_audio_url(info) == "best"


def test_pick_audio_url_requested_formats():
    info = {
        "requested_formats": [
            {"acodec": "none", "url": "video", "vcodec": "avc1"},
            {"acodec": "opus", "url": "audio", "vcodec": "none"},
        ]
    }
    assert StreamResolver._pick_audio_url(info) == "audio"


def test_pick_audio_url_empty():
    assert StreamResolver._pick_audio_url(None) == ""
    assert StreamResolver._pick_audio_url({}) == ""
    assert StreamResolver._pick_audio_url(
        {"formats": [{"acodec": "none", "url": "v", "vcodec": "avc1"}]}
    ) == ""


def test_pick_video_url_prefers_muxed():
    info = {
        "formats": [
            {"acodec": "opus", "vcodec": "none", "url": "audio-only", "height": 0},
            {"acodec": "mp4a", "vcodec": "avc1", "url": "muxed-480", "height": 480},
            {"acodec": "mp4a", "vcodec": "avc1", "url": "muxed-720", "height": 720},
        ]
    }
    assert StreamResolver._pick_video_url(info) == "muxed-720"


def test_cache_roundtrip(monkeypatch):
    r = StreamResolver()
    assert r.cached("x") is None
    with r._lock:
        r._cache[("x", "audio")] = (time.monotonic(), "http://u")
    assert r.cached("x") == "http://u"
    # expired entries are dropped
    with r._lock:
        r._cache[("y", "audio")] = (time.monotonic() - 10_000, "http://old")
    assert r.cached("y") is None


def _fake_yt_dlp(monkeypatch, behaviors):
    """Install a fake yt_dlp whose extract_info pops one behavior per call.

    A behavior is either an Exception to raise or an info dict to return.
    Returns the list that records the extractor_args of every call.
    """
    import sys
    import types

    calls = []

    class FakeYDL:
        def __init__(self, opts):
            self.opts = opts

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def extract_info(self, url, download=False):
            calls.append((self.opts.get("extractor_args"), url))
            action = behaviors.pop(0)
            if isinstance(action, Exception):
                raise action
            return action

    fake = types.ModuleType("yt_dlp")
    fake.YoutubeDL = FakeYDL
    monkeypatch.setitem(sys.modules, "yt_dlp", fake)
    return calls


def test_resolve_falls_back_to_next_client_set(monkeypatch):
    good = {"url": "http://ok", "vcodec": "none", "acodec": "opus"}
    calls = _fake_yt_dlp(monkeypatch, [RuntimeError("po token required"), good])
    r = StreamResolver()
    assert r.resolve("abc") == "http://ok"
    assert len(calls) == 2
    # first attempt uses yt-dlp defaults (no pinned player_client)
    assert calls[0][0] is None
    assert calls[1][0] == {"youtube": {"player_client": ["android", "web"]}}
    # audio resolves through music.youtube.com
    assert calls[0][1].startswith("https://music.youtube.com/watch?v=")


def test_resolve_skips_empty_results(monkeypatch):
    good = {"url": "http://ok2", "vcodec": "none", "acodec": "opus"}
    calls = _fake_yt_dlp(monkeypatch, [{}, good])
    r = StreamResolver()
    assert r.resolve("abc") == "http://ok2"
    assert len(calls) == 2


def test_resolve_total_failure_mentions_ytdlp_update(monkeypatch):
    _fake_yt_dlp(monkeypatch, [RuntimeError("boom 1"), RuntimeError("boom 2"),
                               RuntimeError("boom 3")])
    r = StreamResolver()
    try:
        r.resolve("abc")
        raise AssertionError("expected RuntimeError")
    except RuntimeError as exc:
        assert "yt-dlp" in str(exc)
        assert "boom 3" in str(exc)


def test_resolve_video_uses_watch_page(monkeypatch):
    good = {"url": "http://v", "vcodec": "avc1", "acodec": "mp4a"}
    calls = _fake_yt_dlp(monkeypatch, [good])
    r = StreamResolver()
    assert r.resolve("abc", video=True) == "http://v"
    assert calls[0][1].startswith("https://www.youtube.com/watch?v=")
