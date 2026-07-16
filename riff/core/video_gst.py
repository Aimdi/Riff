"""Optional in-app video via GStreamer + gtk4paintablesink (Wayland-friendly).

Requires the ``gst-plugin-gtk4`` package (Arch: ``pacman -S gst-plugin-gtk4``).
When unavailable, the UI falls back to mpv's video window.
"""

from __future__ import annotations

import logging
import threading

log = logging.getLogger("riff.video_gst")

_GST_READY: bool | None = None


def gst_video_available() -> bool:
    """True when GStreamer playbin + gtk4paintablesink can be created."""
    global _GST_READY
    if _GST_READY is not None:
        return _GST_READY
    try:
        import gi

        gi.require_version("Gst", "1.0")
        from gi.repository import Gst

        if not Gst.is_initialized():
            Gst.init(None)
        playbin = Gst.ElementFactory.make("playbin", None)
        sink = Gst.ElementFactory.make("gtk4paintablesink", None)
        _GST_READY = playbin is not None and sink is not None
        if not _GST_READY:
            log.info("gtk4paintablesink missing — install gst-plugin-gtk4 for in-app video")
    except Exception:  # noqa: BLE001
        log.debug("GStreamer video unavailable", exc_info=True)
        _GST_READY = False
    return bool(_GST_READY)


class GstVideoPlayer:
    """Play a URI with audio+video into a GdkPaintable for Gtk.Picture."""

    def __init__(self, dispatcher=None):
        self._dispatch = dispatcher or (lambda fn, *a: fn(*a))
        self.on_eos = None
        self.on_error = None
        self.on_state = None  # "playing" | "paused" | "stopped"
        self._pipeline = None
        self._sink = None
        self._bus = None
        self._lock = threading.Lock()
        self._uri = ""
        self.paintable = None

    def play_uri(self, uri: str, *, mute_audio: bool = True) -> None:
        """Play ``uri`` into a GdkPaintable.

        ``mute_audio=True`` (default) silences GStreamer so mpv can own the
        soundtrack — YouTube often only offers separate DASH video tracks.
        Pass ``mute_audio=False`` when the URI is a progressive A+V file.
        """
        import gi

        gi.require_version("Gst", "1.0")
        from gi.repository import Gst

        if not Gst.is_initialized():
            Gst.init(None)

        self.stop()
        self._uri = uri
        playbin = Gst.ElementFactory.make("playbin", "riff-playbin")
        sink = Gst.ElementFactory.make("gtk4paintablesink", "riff-vsink")
        if playbin is None or sink is None:
            raise RuntimeError(
                "In-app video needs gst-plugin-gtk4 "
                "(sudo pacman -S gst-plugin-gtk4)"
            )
        playbin.set_property("video-sink", sink)
        if mute_audio:
            # Video-only (or dual-pipeline) mode: no second audio device fight.
            fakesink = Gst.ElementFactory.make("fakesink", "riff-asink")
            if fakesink is not None:
                fakesink.set_property("sync", True)
                playbin.set_property("audio-sink", fakesink)
            else:
                playbin.set_property("mute", True)
        else:
            try:
                playbin.set_property("mute", False)
            except Exception:  # noqa: BLE001
                pass
        playbin.set_property("uri", uri)
        try:
            playbin.set_property("buffer-size", 2 * 1024 * 1024)
        except Exception:  # noqa: BLE001
            pass

        self.paintable = sink.get_property("paintable")
        bus = playbin.get_bus()
        bus.add_signal_watch()
        bus.connect("message", self._on_bus)

        self._pipeline = playbin
        self._sink = sink
        self._bus = bus
        ret = playbin.set_state(Gst.State.PLAYING)
        if ret == Gst.StateChangeReturn.FAILURE:
            raise RuntimeError("GStreamer failed to start playback")
        self._emit_state("playing")

    def stop(self) -> None:
        with self._lock:
            pipe = self._pipeline
            bus = self._bus
            self._pipeline = None
            self._sink = None
            self._bus = None
            self.paintable = None
        if pipe is not None:
            try:
                import gi
                gi.require_version("Gst", "1.0")
                from gi.repository import Gst

                if bus is not None:
                    bus.remove_signal_watch()
                pipe.set_state(Gst.State.NULL)
            except Exception:  # noqa: BLE001
                pass
        self._emit_state("stopped")

    def set_paused(self, paused: bool) -> None:
        if self._pipeline is None:
            return
        import gi
        gi.require_version("Gst", "1.0")
        from gi.repository import Gst

        self._pipeline.set_state(
            Gst.State.PAUSED if paused else Gst.State.PLAYING)
        self._emit_state("paused" if paused else "playing")

    def seek(self, seconds: float) -> None:
        if self._pipeline is None:
            return
        import gi
        gi.require_version("Gst", "1.0")
        from gi.repository import Gst

        ns = max(0, int(float(seconds) * Gst.SECOND))
        self._pipeline.seek_simple(
            Gst.Format.TIME,
            Gst.SeekFlags.FLUSH | Gst.SeekFlags.KEY_UNIT,
            ns,
        )

    def position(self) -> float:
        if self._pipeline is None:
            return 0.0
        import gi
        gi.require_version("Gst", "1.0")
        from gi.repository import Gst

        ok, pos = self._pipeline.query_position(Gst.Format.TIME)
        return (pos / Gst.SECOND) if ok else 0.0

    def duration(self) -> float:
        if self._pipeline is None:
            return 0.0
        import gi
        gi.require_version("Gst", "1.0")
        from gi.repository import Gst

        ok, dur = self._pipeline.query_duration(Gst.Format.TIME)
        return (dur / Gst.SECOND) if ok else 0.0

    def _on_bus(self, _bus, message) -> None:
        import gi
        gi.require_version("Gst", "1.0")
        from gi.repository import Gst

        t = message.type
        if t == Gst.MessageType.EOS:
            self._emit_state("stopped")
            if self.on_eos:
                self._dispatch(self.on_eos)
        elif t == Gst.MessageType.ERROR:
            err, debug = message.parse_error()
            log.warning("GStreamer error: %s (%s)", err, debug)
            if self.on_error:
                self._dispatch(self.on_error, str(err))
            self._emit_state("stopped")

    def _emit_state(self, state: str) -> None:
        if self.on_state:
            self._dispatch(self.on_state, state)
