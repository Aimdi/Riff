"""Podcast progress rules + library Continue + resume seek."""

from riff.core import podcast_progress as pp
from riff.core.library import Library
from riff.core.models import Track
from riff.core.podcast import PodcastEpisode
import riff.core.service as service_mod
from riff.core.service import PlaybackService
from tests.test_service import FakeApi, FakeEngine, FakeResolver, sync_run_async


def test_finish_and_persist_rules():
    assert not pp.should_persist(10_000, 3_600_000)
    assert pp.should_persist(20_000, 3_600_000)
    assert pp.is_finished(3_590_000, 3_600_000)  # last 20s
    assert pp.is_finished(3_530_000, 3_600_000)  # ≥98%
    assert not pp.should_persist(3_590_000, 3_600_000)
    assert pp.resume_seconds(90_000, 3_600_000) == 90.0
    assert pp.resume_seconds(3_000, 3_600_000) is None
    assert pp.resume_seconds(3_590_000, 3_600_000) is None


def test_library_save_clear_and_continue_order():
    lib = Library(":memory:")
    try:
        lib.save_podcast_progress(
            "podcast_aaa",
            title="Old",
            artist="Show",
            stream_url="https://cdn.example.com/a.mp3",
            position_ms=30_000,
            duration_ms=600_000,
        )
        lib.save_podcast_progress(
            "podcast_bbb",
            title="New",
            artist="Show",
            stream_url="https://cdn.example.com/b.mp3",
            position_ms=60_000,
            duration_ms=600_000,
        )
        # Barely started — ignored
        lib.save_podcast_progress(
            "podcast_ccc",
            title="Skip",
            stream_url="https://cdn.example.com/c.mp3",
            position_ms=5_000,
            duration_ms=600_000,
        )
        rows = lib.in_progress_podcasts()
        assert [r["episode_id"] for r in rows] == ["podcast_bbb", "podcast_aaa"]
        assert lib.podcast_progress("podcast_ccc") is None

        # Near end clears
        lib.save_podcast_progress(
            "podcast_aaa",
            title="Old",
            stream_url="https://cdn.example.com/a.mp3",
            position_ms=595_000,
            duration_ms=600_000,
        )
        assert lib.podcast_progress("podcast_aaa") is None
        lib.clear_podcast_progress("podcast_bbb")
        assert lib.in_progress_podcasts() == []
    finally:
        lib.close()


def test_track_from_progress():
    track = pp.track_from_progress({
        "episode_id": "podcast_xyz",
        "title": "Ep",
        "artist": "Show",
        "artwork": "https://art",
        "stream_url": "https://cdn.example.com/x.mp3",
        "position_ms": 120_000,
        "duration_ms": 600_000,
    })
    assert track is not None
    assert track.video_id == "podcast_xyz"
    assert track.stream_url.endswith("x.mp3")
    assert track.duration == 600


def test_playback_resume_seek(monkeypatch):
    monkeypatch.setattr(service_mod, "run_async", sync_run_async)
    monkeypatch.setattr(service_mod.config.settings, "set", lambda *a: None)
    lib = Library(":memory:")
    ep = PodcastEpisode(
        guid="resume-1",
        title="Long Ep",
        stream_url="https://cdn.example.com/long.mp3",
        show_title="Show",
        duration_sec=3600,
    )
    lib.save_podcast_progress(
        ep.episode_id,
        title=ep.title,
        artist=ep.show_title,
        stream_url=ep.stream_url,
        position_ms=125_000,
        duration_ms=3_600_000,
    )
    engine = FakeEngine()
    engine.duration = 3600.0
    svc = PlaybackService(FakeApi(), lib, engine, FakeResolver())
    svc.play_tracks([ep.to_track()], start=0, source="podcast")
    assert engine.played == ["https://cdn.example.com/long.mp3"]
    assert engine.position == 125.0


def test_position_tick_saves_progress(monkeypatch):
    monkeypatch.setattr(service_mod, "run_async", sync_run_async)
    monkeypatch.setattr(service_mod.config.settings, "set", lambda *a: None)
    lib = Library(":memory:")
    engine = FakeEngine()
    engine.duration = 600.0
    svc = PlaybackService(FakeApi(), lib, engine, FakeResolver())
    track = Track(
        video_id="podcast_tick",
        title="Ep",
        artists=["Show"],
        duration=600,
        stream_url="https://cdn.example.com/t.mp3",
    )
    svc.play_tracks([track], start=0, source="podcast")
    svc._last_podcast_save_ts = 0.0
    svc._maybe_save_podcast_progress(45.0)
    row = lib.podcast_progress("podcast_tick")
    assert row is not None
    assert row["position_ms"] == 45_000
    # Finish clears
    svc._last_podcast_save_ts = 0.0
    svc._maybe_save_podcast_progress(595.0)
    assert lib.podcast_progress("podcast_tick") is None
