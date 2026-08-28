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

    def set_audio_filter(self, filter_graph):
        self.af = filter_graph or ""

    def set_speed(self, speed, *, keep_pitch=True):
        self.speed = float(speed)
        self.keep_pitch = bool(keep_pitch)

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
        self.invalidated = []

    def cached(self, video_id, *, video=False):
        return None

    def invalidate(self, video_id):
        self.invalidated.append(video_id)

    def resolve(self, video_id, *, video=False):
        if video_id in self.fail_ids:
            raise RuntimeError("boom")
        self.resolved.append((video_id, video))
        # Video mode resolves audio first, then may request a video URL.
        kind = "video" if video else "audio"
        return f"https://stream/{kind}/{video_id}"


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
    assert engine.played == ["https://stream/audio/v0"]
    # ...but the next one is prefetched
    assert resolver.resolved == [("v0", False), ("v1", False)]


def test_track_end_advances(monkeypatch):
    svc, engine = make_service(monkeypatch)
    svc.play_tracks(tracks(2))
    engine.played.clear()
    engine.end_current_track()
    assert svc.current_track.video_id == "v1"
    assert engine.played == ["https://stream/audio/v1"]


def test_resolve_failure_skips_to_next(monkeypatch):
    resolver = FakeResolver()
    resolver.fail_ids.add("v0")
    errors = []
    svc, engine = make_service(monkeypatch, resolver=resolver)
    svc.error_listeners.append(errors.append)
    svc.play_tracks(tracks(2))
    assert svc.current_track.video_id == "v1"
    assert engine.played == ["https://stream/audio/v1"]
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


class FakeGstVideoPlayer:
    def __init__(self, dispatcher=None):
        self.played = []
        self.paintable = object()
        self.on_eos = None
        self.on_error = None

    def play_uri(self, uri, *, mute_audio=True):
        self.played.append(uri)

    def stop(self):
        pass

    def position(self):
        return 0.0

    def seek(self, _seconds):
        pass


def test_video_mode_starts_audio_before_video_resolve(monkeypatch):
    """Metric: track_change_audio_start — audio play must not wait on video yt-dlp."""
    events = []

    class TimingResolver(FakeResolver):
        def resolve(self, video_id, *, video=False):
            events.append("video_resolve" if video else "audio_resolve")
            return super().resolve(video_id, video=video)

    class TimingEngine(FakeEngine):
        def play_uri(self, uri):
            events.append("play_uri")
            super().play_uri(uri)

    monkeypatch.setattr(service_mod, "run_async", sync_run_async)
    monkeypatch.setattr(service_mod.config.settings, "set", lambda *a: None)
    monkeypatch.setattr(service_mod, "gst_video_available", lambda: True)
    monkeypatch.setattr(service_mod, "GstVideoPlayer", FakeGstVideoPlayer)

    engine = TimingEngine()
    resolver = TimingResolver()
    svc = PlaybackService(FakeApi(), Library(":memory:"), engine, resolver)
    svc.video_mode = True
    svc.play_tracks(tracks(1))

    assert engine.played == ["https://stream/audio/v0"]
    assert svc._video is not None
    assert svc._video.played == ["https://stream/video/v0"]
    assert events.index("play_uri") < events.index("video_resolve")
    assert events.index("audio_resolve") < events.index("play_uri")


def test_video_resolve_failure_keeps_audio_playing(monkeypatch):
    class VideoFailResolver(FakeResolver):
        def resolve(self, video_id, *, video=False):
            if video:
                raise RuntimeError("no video")
            return super().resolve(video_id, video=video)

    monkeypatch.setattr(service_mod, "run_async", sync_run_async)
    monkeypatch.setattr(service_mod.config.settings, "set", lambda *a: None)
    monkeypatch.setattr(service_mod, "gst_video_available", lambda: True)
    monkeypatch.setattr(service_mod, "GstVideoPlayer", FakeGstVideoPlayer)

    engine = FakeEngine()
    svc = PlaybackService(
        FakeApi(), Library(":memory:"), engine, VideoFailResolver())
    svc.video_mode = True
    svc.play_tracks(tracks(1))

    assert engine.played == ["https://stream/audio/v0"]
    assert not svc._using_gst_video


def test_video_mode_audio_start_ms_not_blocked_by_video(monkeypatch):
    """Baseline→result: audio start stays near audio-resolve cost, not audio+video."""
    import threading
    import time

    from riff.util import run_async as real_run_async

    play_at: dict = {}
    played = threading.Event()
    video_done = threading.Event()
    video_delay_s = 0.25

    class SlowVideoResolver(FakeResolver):
        def resolve(self, video_id, *, video=False):
            if video:
                time.sleep(video_delay_s)
                video_done.set()
            return super().resolve(video_id, video=video)

    class TimingEngine(FakeEngine):
        def play_uri(self, uri):
            play_at["t"] = time.perf_counter()
            played.set()
            super().play_uri(uri)

    monkeypatch.setattr(service_mod, "run_async", real_run_async)
    monkeypatch.setattr(service_mod.config.settings, "set", lambda *a: None)
    monkeypatch.setattr(service_mod, "gst_video_available", lambda: True)
    monkeypatch.setattr(service_mod, "GstVideoPlayer", FakeGstVideoPlayer)

    engine = TimingEngine()
    svc = PlaybackService(
        FakeApi(), Library(":memory:"), engine, SlowVideoResolver())
    svc.video_mode = True

    t0 = time.perf_counter()
    svc.play_tracks(tracks(1))
    assert played.wait(2.0), "audio did not start"
    audio_start_ms = (play_at["t"] - t0) * 1000
    # Before: ~250ms+ (audio+video). After: << video delay.
    assert audio_start_ms < video_delay_s * 1000 * 0.6
    assert video_done.wait(2.0), "video resolve did not finish"
    assert engine.played == ["https://stream/audio/v0"]
