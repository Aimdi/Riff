"""In-app video surface shown above the player bar (NewPipe-style watch)."""

from __future__ import annotations

import logging

from gi.repository import Gtk

log = logging.getLogger("riff.video_panel")


class VideoPanel(Gtk.Box):
    """Black video area with a Gtk.Picture for GStreamer paintables."""

    def __init__(self, window):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.window = window
        self.add_css_class("riff-video-panel")
        self.set_vexpand(False)
        self.set_hexpand(True)
        self.set_visible(False)

        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        header.set_margin_start(10)
        header.set_margin_end(8)
        header.set_margin_top(4)
        header.set_margin_bottom(4)
        title = Gtk.Label(label="Video")
        title.add_css_class("heading")
        title.set_xalign(0.0)
        title.set_hexpand(True)
        header.append(title)
        self._hint = Gtk.Label(label="")
        self._hint.add_css_class("dim-label")
        self._hint.add_css_class("caption")
        header.append(self._hint)
        close = Gtk.Button(label="Hide")
        close.add_css_class("flat")
        close.add_css_class("pill")
        close.connect("clicked", lambda *_: window.set_video_mode(False))
        header.append(close)
        self.append(header)

        self.picture = Gtk.Picture()
        self.picture.set_content_fit(Gtk.ContentFit.CONTAIN)
        self.picture.set_size_request(-1, 220)
        self.picture.set_hexpand(True)
        self.picture.set_vexpand(True)
        frame = Gtk.Frame()
        frame.add_css_class("riff-video-frame")
        frame.set_child(self.picture)
        frame.set_hexpand(True)
        self.append(frame)

        self._placeholder = Gtk.Label(
            label="Loading video…\n(songs without a video stay audio-only)")
        self._placeholder.add_css_class("dim-label")
        self._placeholder.set_justify(Gtk.Justification.CENTER)
        self._placeholder.set_margin_top(40)
        self._placeholder.set_margin_bottom(40)
        self.picture.set_paintable(None)

    def set_open(self, open_: bool) -> None:
        self.set_visible(open_)

    def set_paintable(self, paintable) -> None:
        if paintable is None:
            self.picture.set_paintable(None)
            self._hint.set_label("")
            return
        self.picture.set_paintable(paintable)
        self._hint.set_label("Playing video")

    def set_status(self, text: str) -> None:
        self._hint.set_label(text)
