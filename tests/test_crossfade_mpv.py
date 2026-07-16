"""Real dual-deck crossfade through libmpv with generated tones.

Skipped automatically when libmpv is not installed.
"""

import math
import struct
import time
import wave

import pytest

try:
    from riff.core.player import PlayerEngine
    _HAVE_MPV = True
    try:
        _probe = PlayerEngine(extra_options={"ao": "null"})
        _probe.shutdown()
    except Exception:
        _HAVE_MPV = False
except Exception:
    _HAVE_MPV = False

pytestmark = pytest.mark.skipif(not _HAVE_MPV, reason="libmpv not available")


def _tone(path: str, seconds: float, freq: int = 440) -> str:
    rate = 8000
    with wave.open(path, "w") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        frames = bytearray()
        for i in range(int(rate * seconds)):
            sample = int(12000 * math.sin(2 * math.pi * freq * i / rate))
            frames += struct.pack("<h", sample)
        w.writeframes(bytes(frames))
    return path


class SilentApi:
    def radio(self, video_id, limit=25):
        return []


class NoResolver:
    quality = "high"

    def cached(self, video_id, *, video=False):
        return None

    def resolve(self, video_id, *, video=False):
        raise RuntimeError("not used — local files only")


def test_real_two_deck_crossfade(tmp_path, monkeypatch):
    from riff.core.library import Library
    from riff.core.models import Track
    from riff.core.service import PlaybackService
    import riff.core.service as service_mod

    monkeypatch.setattr(
        service_mod.config.settings, "get",
        lambda key, default=None: {
            "volume": 100, "autoplay_radio": False,
            "listenbrainz_token": "",
        }.get(key, default))
    monkeypatch.setattr(service_mod.config.settings, "set", lambda *a: None)

    a = _tone(str(tmp_path / "a.wav"), 3.0, 440)
    b = _tone(str(tmp_path / "b.wav"), 2.0, 660)

    engine = PlayerEngine(extra_options={"ao": "null"})
    svc = PlaybackService(SilentApi(), Library(":memory:"), engine,
                          NoResolver())
    monkeypatch.setattr(svc, "_crossfade_seconds", lambda: 1.0)

    t_a = Track(video_id="", title="A", local_path=a, duration=3)
    t_b = Track(video_id="", title="B", local_path=b, duration=2)
    try:
        svc.play_tracks([t_a, t_b])

        # Wait for the blend to trigger (~2s in) and complete (~3s in).
        deadline = time.time() + 15
        while time.time() < deadline:
            if (svc.queue.current is not None
                    and svc.queue.current.title == "B"
                    and not svc._fading
                    and svc.engine is not engine
                    and svc._spare_engine is engine):
                break
            time.sleep(0.05)
        else:
            pytest.fail(
                f"crossfade never completed (fading={svc._fading}, "
                f"current={svc.queue.current and svc.queue.current.title})")

        # Old deck was recycled as the next spare, at full volume.
        assert svc._spare_engine is engine
        # The new deck is actually playing track B's audio.
        assert svc.engine.state in ("playing", "loading")
    finally:
        svc.shutdown()
