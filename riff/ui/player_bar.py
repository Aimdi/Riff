"""Bottom playback bar: now playing, transport controls, seek, volume."""

from __future__ import annotations

from gi.repository import Gdk, GLib, Gtk

from .. import config
from ..core.models import Track, format_duration
from ..core.player import STATE_LOADING, STATE_PLAYING
from ..core.queue import REPEAT_ALL, REPEAT_ONE
from . import iconutil
from .widgets import (
    CoverArt,
    FixedSquare,
    _ellipsized,
    build_track_menu,
    heart_button,
    menu_dots_button,
    set_heart_state,
)


def _one_line(text: str) -> str:
    """Collapse newlines/whitespace so metadata never wraps the bar taller."""
    return " ".join((text or "").split())


def _now_link(css: list[str], max_chars: int) -> tuple[Gtk.Button, Gtk.Label]:
    """Flat text button that looks like a label; used for clickable metadata."""
    btn = Gtk.Button()
    btn.add_css_class("flat")
    btn.add_css_class("riff-now-link")
    btn.set_halign(Gtk.Align.START)
    btn.set_valign(Gtk.Align.CENTER)
    btn.set_has_frame(False)
    btn.set_vexpand(False)
    label = _ellipsized("", css)
    label.set_max_width_chars(max_chars)
    label.set_width_chars(min(12, max_chars))
    label.set_single_line_mode(True)
    label.set_wrap(False)
    label.set_lines(1)
    btn.set_child(label)
    return btn, label


class PlayerBar(Gtk.Box):
    def __init__(self, window):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.window = window
        self.service = window.service
        self._seeking = False
        self._current: Track | None = None

        self.add_css_class("riff-player-bar")
        # Never grow with tall album art or multi-line titles.
        self.set_vexpand(False)
        self.set_valign(Gtk.Align.END)

        # -- seek row ------------------------------------------------------
        seek_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        seek_row.set_vexpand(False)
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
        row.set_vexpand(False)
        row.set_margin_start(12)
        row.set_margin_end(12)
        row.set_margin_top(2)
        row.set_margin_bottom(8)

        # left: now playing (title → album/single, artist → artist page)
        now = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        now.set_vexpand(False)
        now.set_valign(Gtk.Align.CENTER)
        # Cover art slot — swaps to live video when video mode is on.
        self._art_size = 52
        self.art_stack = Gtk.Stack()
        self.art_stack.set_size_request(self._art_size, self._art_size)
        self.art_stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        self.art_stack.set_transition_duration(150)

        self.art = CoverArt(self._art_size)
        self.art_btn = Gtk.Button()
        self.art_btn.add_css_class("flat")
        self.art_btn.add_css_class("riff-cover-link")
        self.art_btn.set_has_frame(False)
        self.art_btn.set_valign(Gtk.Align.CENTER)
        self.art_btn.set_vexpand(False)
        self.art_btn.set_child(self.art)
        self.art_btn.set_tooltip_text("Go to album")
        self.art_btn.connect("clicked", self._on_title_clicked)
        self.art_stack.add_named(self.art_btn, "art")

        self.video_picture = Gtk.Picture()
        self.video_picture.set_content_fit(Gtk.ContentFit.COVER)
        self.video_picture.set_size_request(self._art_size, self._art_size)
        self.video_picture.set_can_shrink(True)
        # Hard-clamp the slot: a live video paintable reports the full video
        # resolution as its natural size, which would blow the bar up to
        # video size — FixedSquare crops it into the cover-art square.
        video_frame = FixedSquare(self._art_size)
        video_frame.add_css_class("riff-cover")
        video_frame.set_halign(Gtk.Align.CENTER)
        video_frame.set_valign(Gtk.Align.CENTER)
        video_frame.set_child(self.video_picture)
        self.art_stack.add_named(video_frame, "video")
        self.art_stack.set_visible_child_name("art")

        art_box = Gtk.Overlay()
        art_box.set_size_request(self._art_size, self._art_size)
        art_box.set_child(self.art_stack)

        self.video_btn = Gtk.ToggleButton()
        self.video_btn.add_css_class("circular")
        self.video_btn.add_css_class("riff-video-toggle")
        self.video_btn.set_halign(Gtk.Align.END)
        self.video_btn.set_valign(Gtk.Align.END)
        self.video_btn.set_margin_end(2)
        self.video_btn.set_margin_bottom(2)
        self.video_btn.set_tooltip_text(
            "Show video here (replaces the cover art)")
        vid_icon = Gtk.Label(label="▶")
        vid_icon.add_css_class("caption")
        self.video_btn.set_child(vid_icon)
        self.video_btn.set_sensitive(False)
        self.video_btn.connect("toggled", self._on_video_toggled)
        art_box.add_overlay(self.video_btn)
        now.append(art_box)
        self._art_box = art_box

        text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        text.set_valign(Gtk.Align.CENTER)
        text.set_vexpand(False)
        text.set_hexpand(False)
        text.set_size_request(160, -1)
        self.title_btn, self.title_label = _now_link(["heading"], 28)
        self.title_btn.set_tooltip_text("Go to album")
        self.title_btn.connect("clicked", self._on_title_clicked)
        self.artist_btn, self.artist_label = _now_link(
            ["dim-label", "caption"], 30)
        self.artist_btn.set_tooltip_text("Go to artist")
        self.artist_btn.connect("clicked", self._on_artist_clicked)
        text.append(self.title_btn)
        text.append(self.artist_btn)
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
        iconutil.set_button(self.shuffle_btn, "media-playlist-shuffle-symbolic")
        self.shuffle_btn.add_css_class("flat")
        self.shuffle_btn.set_tooltip_text("Shuffle")
        self.shuffle_btn.connect("toggled", self._on_shuffle)
        transport.append(self.shuffle_btn)

        prev = Gtk.Button()
        iconutil.set_button(prev, "media-skip-backward-symbolic")
        prev.add_css_class("flat")
        prev.connect("clicked", lambda *_: self.service.previous())
        transport.append(prev)

        self.play_btn = Gtk.Button()
        iconutil.set_button(self.play_btn, "media-playback-start-symbolic")
        self.play_btn.add_css_class("pill")
        self.play_btn.add_css_class("suggested-action")
        self.play_btn.set_size_request(52, 52)
        self.play_btn.connect("clicked", lambda *_: self.service.toggle_pause())
        transport.append(self.play_btn)

        nxt = Gtk.Button()
        iconutil.set_button(nxt, "media-skip-forward-symbolic")
        nxt.add_css_class("flat")
        nxt.connect("clicked", lambda *_: self.service.next())
        transport.append(nxt)

        self.repeat_btn = Gtk.Button()
        iconutil.set_button(self.repeat_btn, "media-playlist-repeat-symbolic")
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
        iconutil.set_button(self.queue_btn, "view-list-ordered-symbolic")
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
        self._current = track
        if track is None:
            self.title_label.set_label("Not playing")
            self.artist_label.set_label("")
            self.art.set_url("")
            self.seek_scale.set_value(0)
            self.pos_label.set_label("0:00")
            self.dur_label.set_label("0:00")
            self.fav_button.set_sensitive(False)
            self.track_menu_btn.set_sensitive(False)
            self.video_btn.set_sensitive(False)
            self._set_link_active(self.title_btn, False)
            self._set_link_active(self.artist_btn, False)
            self._set_link_active(self.art_btn, False)
            return
        self.fav_button.set_sensitive(True)
        self.track_menu_btn.set_sensitive(True)
        # Any YT id can try video mode (music-only tracks fall back to audio).
        self.video_btn.set_sensitive(bool(track.video_id))
        menu, group = build_track_menu(self.window, track,
                                       on_favorite=self._on_favorite)
        self.track_menu_btn.set_menu_model(menu)
        self.track_menu_btn.insert_action_group("trk", group)
        title = _one_line(track.title) or "Unknown"
        artist = _one_line(track.artist)
        self.title_label.set_label(title)
        self.artist_label.set_label(artist)
        self.art.set_url(track.thumbnail)
        self.seek_scale.set_range(0, max(track.duration, 1))
        self.seek_scale.set_value(0)
        self.dur_label.set_label(format_duration(track.duration))
        self._update_fav_icon()
        has_album = bool(track.album_id)
        has_artist = any(track.artist_ids)
        self._set_link_active(self.title_btn, has_album)
        self._set_link_active(self.art_btn, has_album)
        self._set_link_active(self.artist_btn, has_artist)
        # Full text in tooltips — labels stay single-line so the bar height is fixed.
        album_hint = "Go to album" if has_album else "Album page not available"
        artist_hint = "Go to artist" if has_artist else "Artist page not available"
        self.title_btn.set_tooltip_text(f"{title}\n{album_hint}")
        self.art_btn.set_tooltip_text(f"{title}\n{album_hint}")
        self.artist_btn.set_tooltip_text(
            f"{artist}\n{artist_hint}" if artist else artist_hint)

    @staticmethod
    def _set_link_active(btn: Gtk.Button, active: bool) -> None:
        """Pointer cursor + hover accent when a navigation target exists."""
        if active:
            btn.add_css_class("riff-now-link-active")
            try:
                btn.set_cursor(Gdk.Cursor.new_from_name("pointer"))
            except Exception:  # noqa: BLE001
                pass
        else:
            btn.remove_css_class("riff-now-link-active")
            try:
                btn.set_cursor(None)
            except Exception:  # noqa: BLE001
                pass

    def _on_title_clicked(self, _btn=None) -> None:
        track = self._current
        if track is None:
            return
        if track.album_id:
            self.window.open_album(track.album_id)
        else:
            self.window.toast("Album page not available for this track")

    def _on_video_toggled(self, btn: Gtk.ToggleButton) -> None:
        if self._current is None or not self._current.video_id:
            btn.set_active(False)
            return
        # Avoid feedback loop when service updates the toggle.
        if getattr(self, "_video_sync", False):
            return
        self.window.set_video_mode(btn.get_active())

    def set_video_active(self, active: bool) -> None:
        self._video_sync = True
        try:
            self.video_btn.set_active(bool(active))
        finally:
            self._video_sync = False
        if not active:
            self.set_video_paintable(None)

    def set_video_paintable(self, paintable) -> None:
        """Show live video in the cover-art slot (or restore the thumbnail)."""
        if paintable is None:
            self.video_picture.set_paintable(None)
            self.art_stack.set_visible_child_name("art")
            return
        self.video_picture.set_paintable(paintable)
        self.art_stack.set_visible_child_name("video")

    def _on_artist_clicked(self, _btn=None) -> None:
        track = self._current
        if track is None:
            return
        for aid in track.artist_ids:
            if aid:
                self.window.open_artist(aid)
                return
        self.window.toast("Artist page not available for this track")

    def _on_state(self, state: str) -> None:
        icon = ("media-playback-pause-symbolic"
                if state in (STATE_PLAYING, STATE_LOADING)
                else "media-playback-start-symbolic")
        iconutil.set_button(self.play_btn, icon)

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
        iconutil.set_button(
            self.repeat_btn,
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
