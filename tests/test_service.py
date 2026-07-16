"""PlaybackService logic with a fake engine and synchronous async helper."""

import riff.core.service as service_mod
from riff.core.library import Library
from riff.core.models import Track
from riff.core.service import PlaybackService


class FakeEngine:
    def __init__(self):
        self.state = "stopped"
        self.position = 0.0
        self.duration = 0.0
        self.played = []
        self.volume = None
        self.on_state = None
        self.on_position = None
        self.on_duration = None
        self.on_track_ended = None
        self.on_error = None

    def play_uri(self, uri):
        self.played.append(uri)
        self.state = "playing"
        if self.on_state:
            self.on_state("playing")

    def stop(self):
        self.state = "stopped"

    def set_paused(self, paused):
        self.state = "paused" if paused else "playing"

    def toggle_pause(self):
        self.set_paused(self.state == "playing")

    def seek(self, seconds):
        self.position = seconds

    def set_volume(self, volume):
        self.volume = volume

    def shutdown(self):
        pass

    def end_current_track(self):
        """Simulate natural EOF."""
        if self.on_track_ended:
            self.on_track_ended()


class FakeResolver:
    def __init__(self):
        self.resolved = []
        self.fail_ids = set()

    def cached(self, video_id, *, video=False):
        return None

    def resolve(self, video_id, *, video=False):
        if video_id in self.fail_ids:
            raise RuntimeError("boom")
        self.resolved.append((video_id, video))
        return f"https://stream/{video_id}"


class FakeApi:
    def __init__(self, radio_tracks=None):
        self.radio_tracks = radio_tracks or []

    def radio(self, video_id, limit=25):
        return list(self.radio_tracks)


def sync_run_async(work, on_done=None, on_error=None, name=""):
    try:
        result = work()
    except Exception as exc:  # noqa: BLE001
        if on_error:
            on_error(exc)
        return None
    if on_done:
        on_done(result)
    return None


def make_service(monkeypatch, api=None, resolver=None):
    monkeypatch.setattr(service_mod, "run_async", sync_run_async)
    monkeypatch.setattr(service_mod.config.settings, "set", lambda *a: None)
    engine = FakeEngine()
    svc = PlaybackService(
        api or FakeApi(), Library(":memory:"), engine,
        resolver or FakeResolver())
    return svc, engine


def tracks(n):
    return [Track(video_id=f"v{i}", title=f"T{i}", duration=100) for i in range(n)]


def test_play_tracks_resolves_and_plays(monkeypatch):
    resolver = FakeResolver()
    svc, engine = make_service(monkeypatch, resolver=resolver)
    svc.play_tracks(tracks(3))
    # only the current track starts playing...
    assert engine.played == ["https://stream/v0"]
    # ...but the next one is prefetched
    assert resolver.resolved == [("v0", False), ("v1", False)]


def test_track_end_advances(monkeypatch):
    svc, engine = make_service(monkeypatch)
    svc.play_tracks(tracks(2))
    engine.played.clear()
    engine.end_current_track()
    assert svc.current_track.video_id == "v1"
    assert engine.played == ["https://stream/v1"]


def test_resolve_failure_skips_to_next(monkeypatch):
    resolver = FakeResolver()
    resolver.fail_ids.add("v0")
    errors = []
    svc, engine = make_service(monkeypatch, resolver=resolver)
    svc.error_listeners.append(errors.append)
    svc.play_tracks(tracks(2))
    assert svc.current_track.video_id == "v1"
    assert engine.played == ["https://stream/v1"]
    assert errors and "v0" not in engine.played


def test_queue_end_with_radio_continues(monkeypatch):
    radio = [Track(video_id="r1", title="R1"), Track(video_id="r2", title="R2")]
    svc, engine = make_service(monkeypatch, api=FakeApi(radio))
    svc.play_tracks(tracks(1))
    engine.end_current_track()
    assert svc.current_track.video_id == "r1"


def test_queue_end_without_radio_stops(monkeypatch):
    svc, engine = make_service(monkeypatch)
    monkeypatch.setattr(service_mod.config.settings, "get",
                        lambda key, default=None: False
                        if key == "autoplay_radio" else default)
    states = []
    svc.state_listeners.append(states.append)
    svc.play_tracks(tracks(1))
    engine.end_current_track()
    assert states[-1] == "stopped"


def test_history_recorded(monkeypatch):
    svc, engine = make_service(monkeypatch)
    svc.play_tracks(tracks(2))
    recent = svc.library.recent()
    assert [t.video_id for t in recent] == ["v0"]


def test_previous_restarts_when_past_5s(monkeypatch):
    svc, engine = make_service(monkeypatch)
    svc.play_tracks(tracks(2))
    svc.next()
    assert svc.current_track.video_id == "v1"
    engine.position = 30.0
    svc.previous()
    assert svc.current_track.video_id == "v1"
    assert engine.position == 0.0  # seek(0) called
    engine.position = 2.0
    svc.previous()
    assert svc.current_track.video_id == "v0"


def test_local_file_played_directly(monkeypatch, tmp_path):
    svc, engine = make_service(monkeypatch)
    f = tmp_path / "song.opus"
    f.write_bytes(b"x")
    t = Track(video_id="loc", title="Local", local_path=str(f))
    svc.play_tracks([t])
    assert engine.played == [str(f)]


def test_bad_listener_does_not_break_others(monkeypatch):
    svc, engine = make_service(monkeypatch)
    seen = []
    svc.track_listeners.append(lambda t: 1 / 0)
    svc.track_listeners.append(lambda t: seen.append(t))
    svc.play_tracks(tracks(1))
    assert seen
