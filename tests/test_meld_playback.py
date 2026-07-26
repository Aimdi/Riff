"""Meld-inspired playback: SponsorBlock, skip-silence, recover, queue dupes."""

import riff.core.service as service_mod
from riff.core import audio_fx, sponsorblock
from riff.core.models import Track
from riff.core.stream import StreamResolver, extract_youtube_video_id
from tests.test_service import FakeResolver, make_service, tracks


def test_skip_silence_in_af():
    af = audio_fx.build_af(eq_preset="flat", skip_silence=True)
    assert "silenceremove" in af
    both = audio_fx.build_af(
        eq_preset="bass", normalize=True, skip_silence=True)
    assert "equalizer" in both and "loudnorm" in both
    assert "silenceremove" in both


def test_sponsorblock_parse_and_segment_at():
    payload = [{
        "videoID": "dQw4w9WgXcQ",
        "segments": [
            {
                "category": "intro",
                "actionType": "skip",
                "segment": [0.0, 12.5],
            },
            {
                "category": "sponsor",
                "actionType": "skip",
                "segment": [100.0, 130.0],
            },
            {
                "category": "poi_highlight",
                "actionType": "poi",
                "segment": [40.0, 41.0],
            },
        ],
    }]
    segs = sponsorblock.parse_segments_payload(payload, "dQw4w9WgXcQ")
    assert len(segs) == 2
    assert segs[0].category == "intro"
    assert sponsorblock.segment_at(segs, 5.0).category == "intro"
    assert sponsorblock.segment_at(segs, 12.3) is not None
    assert sponsorblock.segment_at(segs, 12.4) is None
    assert sponsorblock.segment_at(segs, 110.0).label == "sponsor"


def test_extract_youtube_video_id():
    assert extract_youtube_video_id("dQw4w9WgXcQ") == "dQw4w9WgXcQ"
    assert extract_youtube_video_id(
        "https://music.youtube.com/watch?v=dQw4w9WgXcQ&list=RD") == "dQw4w9WgXcQ"
    assert extract_youtube_video_id("https://youtu.be/dQw4w9WgXcQ") == "dQw4w9WgXcQ"
    assert extract_youtube_video_id("podcast_123") is None
    assert not sponsorblock.is_eligible_video_id("podcast_ep1")


def test_stream_invalidate():
    import time

    r = StreamResolver()
    with r._lock:
        r._cache[("abc", "audio")] = (time.monotonic(), "http://a")
        r._cache[("abc", "video")] = (time.monotonic(), "http://v")
        r._cache[("other", "audio")] = (time.monotonic(), "http://o")
    r.invalidate("abc")
    assert r.cached("abc") is None
    assert r.cached("abc", video=True) is None
    assert r.cached("other") == "http://o"


def test_prevent_queue_duplicates(monkeypatch):
    svc, _engine = make_service(monkeypatch)
    monkeypatch.setattr(
        service_mod.config.settings, "get",
        lambda key, default=None: (
            True if key == "prevent_queue_duplicates"
            else {"volume": 100, "autoplay_radio": False}.get(key, default)))
    svc.play_tracks(tracks(2))
    svc.add_to_queue([Track(video_id="v0", title="dup"),
                      Track(video_id="v9", title="fresh")])
    ids = [t.video_id for t in svc.queue.tracks]
    assert ids.count("v0") == 1
    assert "v9" in ids


def test_resolve_failure_recovers_then_skips(monkeypatch):
    resolver = FakeResolver()
    resolver.fail_ids.add("v0")
    svc, engine = make_service(monkeypatch, resolver=resolver)
    monkeypatch.setattr(
        service_mod.config.settings, "get",
        lambda key, default=None: (
            True if key in ("auto_skip_on_error",) else
            {"volume": 100, "autoplay_radio": False,
             "eq_preset": "flat", "normalize_volume": False,
             "skip_silence": False, "playback_speed": 1.0,
             "keep_pitch": True, "sponsorblock": False,
             "prevent_queue_duplicates": True}.get(key, default)))
    svc.play_tracks(tracks(2))
    assert "v0" in resolver.invalidated
    assert svc.current_track.video_id == "v1"
    assert engine.played[-1] == "https://stream/audio/v1"


def test_playback_speed_applied(monkeypatch):
    svc, engine = make_service(monkeypatch)
    stored = {"playback_speed": 1.0, "keep_pitch": True}
    real_get = service_mod.config.settings.get

    def get(key, default=None):
        if key in stored:
            return stored[key]
        return real_get(key, default)

    monkeypatch.setattr(service_mod.config.settings, "get", get)
    monkeypatch.setattr(
        service_mod.config.settings, "set",
        lambda key, value: stored.__setitem__(key, value))
    svc.set_playback_speed(1.5)
    assert engine.speed == 1.5
    assert engine.keep_pitch is True
    assert stored["playback_speed"] == 1.5


def test_sponsorblock_seeks_segment(monkeypatch):
    svc, engine = make_service(monkeypatch)
    svc.play_tracks(tracks(1))
    from riff.core.sponsorblock import Segment
    svc._sb_segments = [Segment("intro", 0.0, 15.0)]
    svc._sb_for = "v0"
    monkeypatch.setattr(
        service_mod.config.settings, "get",
        lambda key, default=None: (
            True if key in ("sponsorblock", "sponsorblock_toast")
            else {"volume": 100}.get(key, default)))
    toasts = []
    svc.error_listeners.append(toasts.append)
    engine.duration = 200.0
    svc._maybe_skip_sponsorblock(3.0)
    assert engine.position == 15.0
    assert any("intro" in t for t in toasts)
