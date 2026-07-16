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
