"""Bottom playback bar: now playing, transport controls, seek, volume."""

from __future__ import annotations

from gi.repository import GLib, Gtk

from .. import config
from ..core.models import format_duration
from ..core.player import STATE_LOADING, STATE_PLAYING
from ..core.queue import REPEAT_ALL, REPEAT_ONE
from .widgets import (
    CoverArt,
    _ellipsized,
    build_track_menu,
    heart_button,
    menu_dots_button,
    set_heart_state,
)


class PlayerBar(Gtk.Box):
    def __init__(self, window):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.window = window
        self.service = window.service
        self._seeking = False

        self.add_css_class("riff-player-bar")

        # -- seek row ------------------------------------------------------
        seek_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        seek_row.set_margin_start(12)
        seek_row.set_margin_end(12)
        seek_row.set_margin_top(4)
        self.pos_label = Gtk.Label(label="0:00")
        self.pos_label.add_css_class("numeric")
        self.pos_label.add_css_class("caption")
        seek_row.append(self.pos_label)

        self.seek_scale = Gtk.Scale.new_with_range(
            Gtk.Orientation.HORIZONTAL, 0, 100, 1)
        self.seek_scale.set_hexpand(True)
        self.seek_scale.set_draw_value(False)
        self.seek_scale.connect("change-value", self._on_seek)
        seek_row.append(self.seek_scale)

        self.dur_label = Gtk.Label(label="0:00")
        self.dur_label.add_css_class("numeric")
        self.dur_label.add_css_class("caption")
        seek_row.append(self.dur_label)
        self.append(seek_row)

        # -- main row ------------------------------------------------------
        row = Gtk.CenterBox()
        row.set_margin_start(12)
        row.set_margin_end(12)
        row.set_margin_top(2)
        row.set_margin_bottom(8)

        # left: now playing
        now = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        self.art = CoverArt(52)
        now.append(self.art)
        text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        text.set_valign(Gtk.Align.CENTER)
        self.title_label = _ellipsized("Not playing", ["heading"])
        self.title_label.set_max_width_chars(28)
        self.artist_label = _ellipsized("", ["dim-label", "caption"])
        self.artist_label.set_max_width_chars(30)
        text.append(self.title_label)
        text.append(self.artist_label)
        now.append(text)
        self.fav_button = heart_button(tooltip="Add to favorites")
        self.fav_button.connect("clicked", self._on_favorite)
        now.append(self.fav_button)

        # Full song menu for whatever is playing right now — favoriting,
        # playlists, download, radio must never depend on finding the song
        # in a list somewhere.
        self.track_menu_btn = menu_dots_button(tooltip="Song actions")
        self.track_menu_btn.set_sensitive(False)
        now.append(self.track_menu_btn)
        row.set_start_widget(now)

        # center: transport
        transport = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        transport.set_valign(Gtk.Align.CENTER)

        self.shuffle_btn = Gtk.ToggleButton()
        self.shuffle_btn.set_icon_name("media-playlist-shuffle-symbolic")
        self.shuffle_btn.add_css_class("flat")
        self.shuffle_btn.set_tooltip_text("Shuffle")
        self.shuffle_btn.connect("toggled", self._on_shuffle)
        transport.append(self.shuffle_btn)

        prev = Gtk.Button.new_from_icon_name("media-skip-backward-symbolic")
        prev.add_css_class("flat")
        prev.connect("clicked", lambda *_: self.service.previous())
        transport.append(prev)

        self.play_btn = Gtk.Button.new_from_icon_name(
            "media-playback-start-symbolic")
        self.play_btn.add_css_class("pill")
        self.play_btn.add_css_class("suggested-action")
        self.play_btn.set_size_request(52, 52)
        self.play_btn.connect("clicked", lambda *_: self.service.toggle_pause())
        transport.append(self.play_btn)

        nxt = Gtk.Button.new_from_icon_name("media-skip-forward-symbolic")
        nxt.add_css_class("flat")
        nxt.connect("clicked", lambda *_: self.service.next())
        transport.append(nxt)

        self.repeat_btn = Gtk.Button.new_from_icon_name(
            "media-playlist-repeat-symbolic")
        self.repeat_btn.add_css_class("flat")
        self.repeat_btn.set_tooltip_text("Repeat: off")
        self.repeat_btn.connect("clicked", self._on_repeat)
        transport.append(self.repeat_btn)
        row.set_center_widget(transport)

        # right: volume + queue
        right = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        right.set_valign(Gtk.Align.CENTER)

        self.volume = Gtk.ScaleButton.new(
            0, 100, 5,
            ["audio-volume-muted-symbolic", "audio-volume-high-symbolic",
             "audio-volume-low-symbolic", "audio-volume-medium-symbolic"])
        self.volume.set_value(float(config.settings.get("volume", 100)))
        self.volume.connect("value-changed",
                            lambda _b, v: self.service.set_volume(int(v)))
        right.append(self.volume)

        self.queue_btn = Gtk.ToggleButton()
        self.queue_btn.set_icon_name("view-list-ordered-symbolic")
        self.queue_btn.add_css_class("flat")
        self.queue_btn.set_tooltip_text("Show queue")
        right.append(self.queue_btn)
        row.set_end_widget(right)

        self.append(row)

        # -- wire service --------------------------------------------------
        svc = self.service
        svc.track_listeners.append(self._on_track)
        svc.state_listeners.append(self._on_state)
        svc.position_listeners.append(self._on_position)
        svc.duration_listeners.append(self._on_duration)
        self._on_track(None)

    # -- service events ----------------------------------------------------

    def _on_track(self, track) -> None:
        if track is None:
            self.title_label.set_label("Not playing")
            self.artist_label.set_label("")
            self.art.set_url("")
            self.seek_scale.set_value(0)
            self.pos_label.set_label("0:00")
            self.dur_label.set_label("0:00")
            self.fav_button.set_sensitive(False)
            self.track_menu_btn.set_sensitive(False)
            return
        self.fav_button.set_sensitive(True)
        self.track_menu_btn.set_sensitive(True)
        menu, group = build_track_menu(self.window, track,
                                       on_favorite=self._on_favorite)
        self.track_menu_btn.set_menu_model(menu)
        self.track_menu_btn.insert_action_group("trk", group)
        self.title_label.set_label(track.title)
        self.artist_label.set_label(track.artist)
        self.art.set_url(track.thumbnail)
        self.seek_scale.set_range(0, max(track.duration, 1))
        self.seek_scale.set_value(0)
        self.dur_label.set_label(format_duration(track.duration))
        self._update_fav_icon()

    def _on_state(self, state: str) -> None:
        icon = ("media-playback-pause-symbolic"
                if state in (STATE_PLAYING, STATE_LOADING)
                else "media-playback-start-symbolic")
        self.play_btn.set_icon_name(icon)

    def _on_position(self, pos: float) -> None:
        if self._seeking:
            return
        self.seek_scale.set_value(pos)
        self.pos_label.set_label(format_duration(pos))

    def _on_duration(self, dur: float) -> None:
        if dur and dur > 0:
            self.seek_scale.set_range(0, dur)
            self.dur_label.set_label(format_duration(dur))

    # -- user input ----------------------------------------------------------

    def _on_seek(self, _scale, _scroll, value: float) -> bool:
        self._seeking = True
        self.service.seek(value)
        self.pos_label.set_label(format_duration(value))
        # brief guard so the scale doesn't jump back before mpv reports
        GLib.timeout_add(300, self._end_seek)
        return False

    def _end_seek(self) -> bool:
        self._seeking = False
        return False  # do not repeat

    def _on_shuffle(self, btn: Gtk.ToggleButton) -> None:
        self.service.queue.set_shuffle(btn.get_active())

    def _on_repeat(self, _btn) -> None:
        mode = self.service.queue.cycle_repeat()
        icons = {
            REPEAT_ONE: "media-playlist-repeat-song-symbolic",
            REPEAT_ALL: "media-playlist-repeat-symbolic",
        }
        self.repeat_btn.set_icon_name(
            icons.get(mode, "media-playlist-repeat-symbolic"))
        if mode == REPEAT_ALL:
            self.repeat_btn.add_css_class("accent")
        elif mode == REPEAT_ONE:
            self.repeat_btn.add_css_class("accent")
        else:
            self.repeat_btn.remove_css_class("accent")
        self.repeat_btn.set_tooltip_text(f"Repeat: {mode}")

    def _on_favorite(self, _btn=None) -> None:
        track = self.service.current_track
        if track is None:
            return
        added = self.window.library.toggle_favorite(track)
        self.window.toast(
            "Added to favorites" if added else "Removed from favorites")
        self._update_fav_icon()

    def _update_fav_icon(self) -> None:
        track = self.service.current_track
        is_fav = track is not None and self.window.library.is_favorite(track.video_id)
        set_heart_state(self.fav_button, is_fav)
