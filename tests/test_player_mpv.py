"""Integration test of the libmpv binding using a locally generated tone.

Skipped automatically when libmpv is not installed.
"""

import locale
import math
import struct
import threading
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


@pytest.fixture
def tone_file(tmp_path):
    path = str(tmp_path / "tone.wav")
    rate = 8000
    seconds = 1.0
    with wave.open(path, "w") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        frames = bytearray()
        for i in range(int(rate * seconds)):
            sample = int(12000 * math.sin(2 * math.pi * 440 * i / rate))
            frames += struct.pack("<h", sample)
        w.writeframes(bytes(frames))
    return path


def test_playback_lifecycle(tone_file):
    engine = PlayerEngine(extra_options={"ao": "null"})
    playing = threading.Event()
    ended = threading.Event()
    durations = []
    positions = []

    engine.on_state = lambda s: playing.set() if s == "playing" else None
    engine.on_track_ended = lambda: ended.set()
    engine.on_duration = durations.append
    engine.on_position = positions.append

    engine.play_uri(tone_file)
    assert playing.wait(10), "engine never reached playing state"
    assert ended.wait(15), "track never ended naturally"
    assert durations and durations[-1] == pytest.approx(1.0, abs=0.2)
    assert positions, "no position updates received"
    engine.shutdown()


def test_engine_creation_under_comma_decimal_locale():
    """Regression: GTK sets the process locale from the environment; libmpv
    refuses to start when LC_NUMERIC uses decimal commas (e.g. de_DE)."""
    try:
        locale.setlocale(locale.LC_ALL, "de_DE.UTF-8")
    except locale.Error:
        pytest.skip("de_DE.UTF-8 locale not generated on this system")
    try:
        engine = PlayerEngine(extra_options={"ao": "null"})
        engine.shutdown()
    finally:
        locale.setlocale(locale.LC_ALL, "C")


def test_pause_and_seek(tone_file):
    engine = PlayerEngine(extra_options={"ao": "null"})
    playing = threading.Event()
    paused = threading.Event()

    def on_state(s):
        if s == "playing":
            playing.set()
        elif s == "paused":
            paused.set()

    engine.on_state = on_state
    engine.play_uri(tone_file)
    assert playing.wait(10)
    engine.set_paused(True)
    assert paused.wait(5), "pause state never reported"
    engine.seek(0.5)
    engine.set_volume(50)
    engine.stop()
    assert engine.state == "stopped"
    engine.shutdown()
