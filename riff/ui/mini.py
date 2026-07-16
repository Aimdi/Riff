"""Mini player — a compact window with art and transport controls.

On KDE, right-click its titlebar → More Actions → Keep Above for
always-on-top (Wayland doesn't let apps set that themselves).
"""

from __future__ import annotations

from gi.repository import Gtk

from ..core.player import STATE_LOADING, STATE_PLAYING
from .widgets import CoverArt, _ellipsized


class MiniPlayer(Gtk.Window):
    def __init__(self, main_window):
        super().__init__(application=main_window.get_application())
        self.main_window = main_window
        self.service = main_window.service
        self.set_title("Riff")
        self.set_default_size(360, 104)
        self.set_resizable(False)

        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        box.set_margin_top(10)
        box.set_margin_bottom(10)
        box.set_margin_start(10)
        box.set_margin_end(10)

        self.art = CoverArt(80)
        box.append(self.art)

        middle = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        middle.set_valign(Gtk.Align.CENTER)
        middle.set_hexpand(True)
        self.title_label = _ellipsized("Not playing", ["heading"])
        self.title_label.set_max_width_chars(22)
        self.artist_label = _ellipsized("", ["dim-label", "caption"])
        middle.append(self.title_label)
        middle.append(self.artist_label)

        controls = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=2)
        prev = Gtk.Button.new_from_icon_name("media-skip-backward-symbolic")
        prev.add_css_class("flat")
        prev.connect("clicked", lambda *_: self.service.previous())
        controls.append(prev)
        self.play_btn = Gtk.Button.new_from_icon_name(
            "media-playback-start-symbolic")
        self.play_btn.add_css_class("flat")
        self.play_btn.connect("clicked", lambda *_: self.service.toggle_pause())
        controls.append(self.play_btn)
        nxt = Gtk.Button.new_from_icon_name("media-skip-forward-symbolic")
        nxt.add_css_class("flat")
        nxt.connect("clicked", lambda *_: self.service.next())
        controls.append(nxt)
        middle.append(controls)
        box.append(middle)

        restore = Gtk.Button.new_from_icon_name("view-restore-symbolic")
        restore.add_css_class("flat")
        restore.set_valign(Gtk.Align.CENTER)
        restore.set_tooltip_text("Back to full window")
        restore.connect("clicked", lambda *_: self._restore())
        box.append(restore)

        self.set_child(box)

        self._on_track_cb = self._on_track
        self._on_state_cb = self._on_state
        self.service.track_listeners.append(self._on_track_cb)
        self.service.state_listeners.append(self._on_state_cb)
        self.connect("close-request", lambda *_: (self._restore(), False)[1])
        self._on_track(self.service.current_track)
        self._on_state(self.service.state)

    def _restore(self) -> None:
        for listeners, cb in (
                (self.service.track_listeners, self._on_track_cb),
                (self.service.state_listeners, self._on_state_cb)):
            if cb in listeners:
                listeners.remove(cb)
        self.main_window.set_visible(True)
        self.main_window.present()
        self.destroy()

    def _on_track(self, track) -> None:
        if track is None:
            self.title_label.set_label("Not playing")
            self.artist_label.set_label("")
            self.art.set_url("")
        else:
            self.title_label.set_label(track.title)
            self.artist_label.set_label(track.artist)
            self.art.set_url(track.thumbnail)

    def _on_state(self, state: str) -> None:
        icon = ("media-playback-pause-symbolic"
                if state in (STATE_PLAYING, STATE_LOADING)
                else "media-playback-start-symbolic")
        self.play_btn.set_icon_name(icon)
