"""Crossfade: dual-deck blend, engine swap, cancellation."""

from test_service import (
    FakeApi,
    FakeEngine,
    FakeResolver,
    make_service,
    tracks,
)


class CachedResolver(FakeResolver):
    """Prefetched streams: cached() hits so a crossfade can start."""

    def cached(self, video_id, *, video=False):
        return f"https://stream/audio/{video_id}"


def make_fading_service(monkeypatch, fade=5.0):
    import riff.core.service as service_mod

    svc, engine = make_service(monkeypatch, api=FakeApi(),
                               resolver=CachedResolver())
    # Independent of whatever the container's real settings.json holds.
    monkeypatch.setattr(
        service_mod.config.settings, "get",
        lambda key, default=None: {"volume": 100}.get(key, default))
    monkeypatch.setattr(svc, "_crossfade_seconds", lambda: fade)
    spare = FakeEngine()
    svc._spare_engine = spare
    return svc, engine, spare


def test_crossfade_swaps_decks_and_blends(monkeypatch):
    svc, engine, spare = make_fading_service(monkeypatch)
    svc.play_tracks(tracks(3))
    engine.duration = 100.0

    events = []
    svc.track_listeners.append(lambda t: events.append(t and t.video_id))

    # Not yet in the fade window: nothing happens.
    engine.position = 90.0
    svc._on_engine_position(90.0)
    assert svc.engine is engine and not svc._fading

    # Entering the last 5 seconds starts the blend.
    engine.position = 96.0
    svc._on_engine_position(96.0)
    assert svc._fading
    assert svc.engine is spare, "incoming deck must become the engine"
    assert spare.played == ["https://stream/audio/v1"]
    assert spare.volume == 0  # starts silent
    assert svc.queue.current.video_id == "v1"
    assert events[-1] == "v1"  # UI told immediately

    # Old deck's position events drive the blend (equal-power).
    engine.on_position(98.5)  # halfway through the fade
    assert 0 < spare.volume < 100
    assert 0 < engine.volume < 100

    # Old track ends -> blend completes.
    engine.end_current_track()
    assert not svc._fading
    assert engine.state == "stopped"
    assert spare.volume == 100
    assert svc._spare_engine is engine  # old deck recycled as next spare


def test_no_crossfade_without_prefetched_stream(monkeypatch):
    svc, engine, spare = make_fading_service(monkeypatch)
    svc.resolver = FakeResolver()  # cached() always misses
    svc.play_tracks(tracks(2))
    engine.duration = 100.0
    svc._on_engine_position(97.0)
    assert not svc._fading
    assert svc.engine is engine


def test_no_crossfade_when_disabled_or_short(monkeypatch):
    svc, engine, spare = make_fading_service(monkeypatch, fade=0.0)
    svc.play_tracks(tracks(2))
    engine.duration = 100.0
    svc._on_engine_position(99.0)
    assert not svc._fading

    svc2, engine2, _ = make_fading_service(monkeypatch, fade=5.0)
    svc2.play_tracks(tracks(2))
    engine2.duration = 10.0  # shorter than fade*2.5 — skip blending
    svc2._on_engine_position(9.0)
    assert not svc2._fading


def test_manual_skip_cancels_fade(monkeypatch):
    svc, engine, spare = make_fading_service(monkeypatch)
    svc.play_tracks(tracks(3))
    engine.duration = 100.0
    engine.position = 96.0
    svc._on_engine_position(96.0)
    assert svc._fading

    svc.next()  # user skips mid-blend
    assert not svc._fading
    assert engine.state == "stopped"
    # active deck plays the new current track at full volume
    assert svc.engine.volume == 100
    assert svc.queue.current.video_id == "v2"


def test_track_end_without_fade_still_advances(monkeypatch):
    svc, engine, spare = make_fading_service(monkeypatch, fade=0.0)
    svc.play_tracks(tracks(2))
    engine.end_current_track()
    assert svc.queue.current.video_id == "v1"


def test_play_and_skip_feed_the_taste_model(monkeypatch):
    """Phase-1 acceptance: affinity reflects listens and skips, with the
    right source attribution."""
    from riff.core import taste

    svc, engine, _spare = make_fading_service(monkeypatch, fade=0.0)
    ts = tracks(3)
    for i, t in enumerate(ts):
        t.artists = [f"Artist {i}"]

    svc.play_tracks(ts)  # source defaults to user_click
    # listen most of track 0, then natural end
    engine.duration = 100.0
    engine.position = 99.0
    engine.end_current_track()
    # quick-skip track 1
    engine.position = 3.0
    svc.next()
    rows = svc.library.events_for_artist(taste.artist_key("Artist 0"))
    assert [r[0] for r in rows] == ["play"]
    assert rows[0][1] == 1.0  # natural end -> full listen
    assert rows[0][2] == "user_click"
    rows1 = svc.library.events_for_artist(taste.artist_key("Artist 1"))
    assert rows1[0][1] is not None and rows1[0][1] < 0.1
    assert svc.library.artist_affinity(taste.artist_key("Artist 0")) > 0
    assert svc.library.artist_affinity(taste.artist_key("Artist 1")) < 0


def test_radio_added_tracks_are_source_tagged(monkeypatch):
    svc, engine, _spare = make_fading_service(monkeypatch, fade=0.0)
    svc.play_tracks(tracks(1))
    svc._tag_sources(tracks(3)[1:], "radio")
    assert svc._track_sources["v1"] == "radio"
    # first-seen source wins (v0 was user_click)
    assert svc._track_sources["v0"] == "user_click"
