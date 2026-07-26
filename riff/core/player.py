"""Audio playback engine on top of libmpv (ctypes, no extra dependencies).

The engine is UI-agnostic: callbacks fire on an internal event thread and are
marshalled through the `dispatcher` callable (the app passes GLib.idle_add
semantics via riff.util._dispatch-style wrapper; tests use direct calls).
"""

from __future__ import annotations

import ctypes
import ctypes.util
import locale
import logging
import threading

log = logging.getLogger("riff.player")


def _ensure_c_numeric_locale() -> None:
    """libmpv refuses to initialize unless LC_NUMERIC is "C".

    GTK sets the process locale from the environment, so on e.g. German
    systems LC_NUMERIC becomes de_DE and mpv_create() returns NULL. Forcing
    LC_NUMERIC back to "C" is explicitly what mpv's docs ask clients to do,
    and it does not affect GTK's translations or date/number display.
    """
    try:
        locale.setlocale(locale.LC_NUMERIC, "C")
    except locale.Error:
        pass

# --- minimal libmpv binding -------------------------------------------------

MPV_EVENT_SHUTDOWN = 1
MPV_EVENT_START_FILE = 6
MPV_EVENT_END_FILE = 7
MPV_EVENT_FILE_LOADED = 8
MPV_EVENT_PLAYBACK_RESTART = 21
MPV_EVENT_PROPERTY_CHANGE = 22

MPV_END_FILE_REASON_EOF = 0
MPV_END_FILE_REASON_STOP = 2
MPV_END_FILE_REASON_QUIT = 3
MPV_END_FILE_REASON_ERROR = 4

MPV_FORMAT_STRING = 1
MPV_FORMAT_FLAG = 3
MPV_FORMAT_INT64 = 4
MPV_FORMAT_DOUBLE = 5


class _MpvEvent(ctypes.Structure):
    _fields_ = [
        ("event_id", ctypes.c_int),
        ("error", ctypes.c_int),
        ("reply_userdata", ctypes.c_uint64),
        ("data", ctypes.c_void_p),
    ]


class _MpvEventProperty(ctypes.Structure):
    _fields_ = [
        ("name", ctypes.c_char_p),
        ("format", ctypes.c_int),
        ("data", ctypes.c_void_p),
    ]


class _MpvEventEndFile(ctypes.Structure):
    _fields_ = [
        ("reason", ctypes.c_int),
        ("error", ctypes.c_int),
        ("playlist_entry_id", ctypes.c_int64),
    ]


def _load_libmpv() -> ctypes.CDLL:
    candidates = []
    found = ctypes.util.find_library("mpv")
    if found:
        candidates.append(found)
    candidates += ["libmpv.so.2", "libmpv.so.1", "libmpv.so"]
    last_err: Exception | None = None
    for name in candidates:
        try:
            return ctypes.CDLL(name)
        except OSError as exc:
            last_err = exc
    raise RuntimeError(
        "libmpv not found — install the 'mpv' package (pacman -S mpv)"
    ) from last_err


class _Mpv:
    """Raw handle wrapper."""

    def __init__(self, extra_options: dict[str, str] | None = None):
        _ensure_c_numeric_locale()
        lib = _load_libmpv()
        lib.mpv_create.restype = ctypes.c_void_p
        lib.mpv_wait_event.restype = ctypes.POINTER(_MpvEvent)
        lib.mpv_error_string.restype = ctypes.c_char_p
        self._lib = lib
        self.handle = ctypes.c_void_p(lib.mpv_create())
        if not self.handle:
            raise RuntimeError("mpv_create failed")

        options = {
            "video": "no",
            "audio-display": "no",
            "terminal": "no",
            "idle": "yes",
            "gapless-audio": "weak",
            "cache": "yes",
            "cache-secs": "30",
            "demuxer-max-bytes": "32MiB",
            # yt-dlp hands us direct URLs; keep mpv's own ytdl hook off.
            "ytdl": "no",
        }
        options.update(extra_options or {})
        for key, value in options.items():
            self._lib.mpv_set_option_string(
                self.handle, key.encode(), str(value).encode()
            )
        err = lib.mpv_initialize(self.handle)
        if err < 0:
            raise RuntimeError(f"mpv_initialize failed: {self.error_string(err)}")

    def error_string(self, code: int) -> str:
        return self._lib.mpv_error_string(code).decode("utf-8", "replace")

    def command(self, *args: str) -> int:
        c_args = (ctypes.c_char_p * (len(args) + 1))(
            *[a.encode("utf-8") for a in args], None
        )
        return self._lib.mpv_command(self.handle, c_args)

    def set_property(self, name: str, value) -> int:
        if isinstance(value, bool):
            value = "yes" if value else "no"
        return self._lib.mpv_set_property_string(
            self.handle, name.encode(), str(value).encode()
        )

    def get_double(self, name: str) -> float | None:
        out = ctypes.c_double()
        err = self._lib.mpv_get_property(
            self.handle, name.encode(), MPV_FORMAT_DOUBLE, ctypes.byref(out)
        )
        return out.value if err >= 0 else None

    def get_flag(self, name: str) -> bool | None:
        out = ctypes.c_int()
        err = self._lib.mpv_get_property(
            self.handle, name.encode(), MPV_FORMAT_FLAG, ctypes.byref(out)
        )
        return bool(out.value) if err >= 0 else None

    def observe_double(self, name: str, userdata: int = 0) -> None:
        self._lib.mpv_observe_property(
            self.handle, ctypes.c_uint64(userdata), name.encode(), MPV_FORMAT_DOUBLE
        )

    def observe_flag(self, name: str, userdata: int = 0) -> None:
        self._lib.mpv_observe_property(
            self.handle, ctypes.c_uint64(userdata), name.encode(), MPV_FORMAT_FLAG
        )

    def wait_event(self, timeout: float) -> _MpvEvent:
        return self._lib.mpv_wait_event(self.handle, ctypes.c_double(timeout)).contents

    def wakeup(self) -> None:
        self._lib.mpv_wakeup(self.handle)

    def destroy(self) -> None:
        if self.handle:
            self._lib.mpv_terminate_destroy(self.handle)
            self.handle = None


# --- public engine -----------------------------------------------------------

STATE_STOPPED = "stopped"
STATE_LOADING = "loading"
STATE_PLAYING = "playing"
STATE_PAUSED = "paused"


class PlayerEngine:
    """High-level playback control with simple callbacks.

    Callbacks (all optional, set as attributes):
      on_state(state: str)
      on_position(seconds: float)
      on_duration(seconds: float)
      on_track_ended()            # natural end of file -> advance the queue
      on_error(message: str)
    """

    def __init__(self, dispatcher=None, extra_options: dict | None = None):
        self._dispatch = dispatcher or (lambda fn, *a: fn(*a))
        self._extra_options = dict(extra_options) if extra_options else None
        self._mpv = _Mpv(extra_options)
        self.on_state = None
        self.on_position = None
        self.on_duration = None
        self.on_track_ended = None
        self.on_error = None

        self.state = STATE_STOPPED
        self.position = 0.0
        self.duration = 0.0
        self._loading = False
        self._stop_requested = False
        self._shutdown = threading.Event()

        self._mpv.observe_double("time-pos")
        self._mpv.observe_double("duration")
        self._mpv.observe_flag("pause")
        self._mpv.observe_flag("core-idle")

        self._thread = threading.Thread(
            target=self._event_loop, name="riff-mpv-events", daemon=True
        )
        self._thread.start()

    # -- controls ----------------------------------------------------------

    def play_uri(self, uri: str) -> None:
        self._loading = True
        self._stop_requested = False
        self._set_state(STATE_LOADING)
        self._mpv.set_property("pause", False)
        err = self._mpv.command("loadfile", uri, "replace")
        if err < 0:
            self._emit_error(f"Could not start playback: {self._mpv.error_string(err)}")

    def stop(self) -> None:
        self._stop_requested = True
        self._mpv.command("stop")
        self.position = 0.0
        self._set_state(STATE_STOPPED)

    def set_paused(self, paused: bool) -> None:
        self._mpv.set_property("pause", paused)

    def toggle_pause(self) -> None:
        if self.state == STATE_PLAYING:
            self.set_paused(True)
        elif self.state == STATE_PAUSED:
            self.set_paused(False)

    def seek(self, seconds: float) -> None:
        self._mpv.command("seek", f"{max(0.0, seconds):.3f}", "absolute")

    def set_volume(self, volume: int) -> None:
        self._mpv.set_property("volume", max(0, min(130, int(volume))))

    def set_audio_filter(self, filter_graph: str) -> None:
        """Set mpv ``af`` chain (empty clears). Used for EQ / loudnorm."""
        try:
            self._mpv.set_property("af", filter_graph or "")
        except Exception:  # noqa: BLE001
            pass

    def set_speed(self, speed: float, *, keep_pitch: bool = True) -> None:
        """Playback rate (Meld tempo). ``keep_pitch`` uses mpv pitch correction."""
        speed = max(0.5, min(2.5, float(speed)))
        try:
            self._mpv.set_property(
                "audio-pitch-correction", "yes" if keep_pitch else "no")
            self._mpv.set_property("speed", speed)
        except Exception:  # noqa: BLE001
            pass

    def shutdown(self) -> None:
        self._shutdown.set()
        self._mpv.wakeup()
        self._thread.join(timeout=2)
        self._mpv.destroy()

    # -- events ------------------------------------------------------------

    def _event_loop(self) -> None:
        while not self._shutdown.is_set():
            try:
                event = self._mpv.wait_event(0.5)
            except Exception:  # handle destroyed under us
                return
            eid = event.event_id
            if eid == 0:  # MPV_EVENT_NONE (timeout)
                continue
            if eid == MPV_EVENT_SHUTDOWN:
                return
            if eid == MPV_EVENT_PROPERTY_CHANGE:
                self._on_property(event)
            elif eid == MPV_EVENT_FILE_LOADED:
                self._loading = False
                paused = self._mpv.get_flag("pause")
                self._set_state(STATE_PAUSED if paused else STATE_PLAYING)
            elif eid == MPV_EVENT_END_FILE:
                self._on_end_file(event)

    def _on_property(self, event: _MpvEvent) -> None:
        prop = ctypes.cast(event.data, ctypes.POINTER(_MpvEventProperty)).contents
        name = (prop.name or b"").decode()
        if prop.format == MPV_FORMAT_DOUBLE and prop.data:
            value = ctypes.cast(prop.data, ctypes.POINTER(ctypes.c_double)).contents.value
            if name == "time-pos":
                self.position = value
                if self.on_position:
                    self._dispatch(self.on_position, value)
            elif name == "duration":
                self.duration = value
                if self.on_duration:
                    self._dispatch(self.on_duration, value)
        elif prop.format == MPV_FORMAT_FLAG and prop.data:
            value = bool(ctypes.cast(prop.data, ctypes.POINTER(ctypes.c_int)).contents.value)
            if name == "pause" and not self._loading and self.state != STATE_STOPPED:
                self._set_state(STATE_PAUSED if value else STATE_PLAYING)

    def _on_end_file(self, event: _MpvEvent) -> None:
        reason = MPV_END_FILE_REASON_STOP
        if event.data:
            end = ctypes.cast(event.data, ctypes.POINTER(_MpvEventEndFile)).contents
            reason = end.reason
        if reason == MPV_END_FILE_REASON_EOF:
            self._set_state(STATE_STOPPED)
            if self.on_track_ended:
                self._dispatch(self.on_track_ended)
        elif reason == MPV_END_FILE_REASON_ERROR:
            self._set_state(STATE_STOPPED)
            self._emit_error("Playback failed — the stream may have expired")
        elif not self._stop_requested and reason == MPV_END_FILE_REASON_QUIT:
            self._set_state(STATE_STOPPED)

    def _set_state(self, state: str) -> None:
        if state == self.state:
            return
        self.state = state
        if self.on_state:
            self._dispatch(self.on_state, state)

    def _emit_error(self, message: str) -> None:
        log.warning("%s", message)
        if self.on_error:
            self._dispatch(self.on_error, message)
