import time

from riff.core.stream import StreamResolver


def test_pick_url_prefers_direct():
    info = {"url": "direct", "formats": [{"acodec": "opus", "url": "other"}]}
    assert StreamResolver._pick_url(info) == "direct"


def test_pick_url_best_audio_bitrate():
    info = {
        "formats": [
            {"acodec": "mp4a", "abr": 128, "url": "mid"},
            {"acodec": "none", "abr": 999, "url": "video-only"},
            {"acodec": "opus", "abr": 160, "url": "best"},
            {"acodec": "opus", "abr": 64, "url": "low"},
        ]
    }
    assert StreamResolver._pick_url(info) == "best"


def test_pick_url_requested_formats():
    info = {
        "requested_formats": [
            {"acodec": "none", "url": "video"},
            {"acodec": "opus", "url": "audio"},
        ]
    }
    assert StreamResolver._pick_url(info) == "audio"


def test_pick_url_empty():
    assert StreamResolver._pick_url(None) == ""
    assert StreamResolver._pick_url({}) == ""
    assert StreamResolver._pick_url({"formats": [{"acodec": "none", "url": "v"}]}) == ""


def test_cache_roundtrip(monkeypatch):
    r = StreamResolver()
    assert r.cached("x") is None
    with r._lock:
        r._cache["x"] = (time.monotonic(), "http://u")
    assert r.cached("x") == "http://u"
    # expired entries are dropped
    with r._lock:
        r._cache["y"] = (time.monotonic() - 10_000, "http://old")
    assert r.cached("y") is None
