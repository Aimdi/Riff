"""Full-screen Now Playing — Riff Mobile player on desktop."""

from __future__ import annotations

from gi.repository import Gtk, Pango

from ..core.models import Track, format_duration
from ..core.player import STATE_LOADING, STATE_PLAYING
from ..core.queue import REPEAT_ALL, REPEAT_ONE
from . import iconutil, images
from .widgets import CoverArt, build_track_menu, heart_button, set_heart_state


class FullPlayer(Gtk.Overlay):
    """Immersive player: art wash backdrop + large art, transport, queue/lyrics."""

    def __init__(self, window):
        super().__init__()
        self.window = window
        self.service = window.service
        self._current: Track | None = None
        self._seeking = False
        self.add_css_class("riff-full-player")

        # Backdrop -----------------------------------------------------------
        self._backdrop = Gtk.Picture()
        self._backdrop.set_content_fit(Gtk.ContentFit.COVER)
        self._backdrop.set_can_shrink(True)
        self._backdrop.add_css_class("riff-full-player-backdrop")
        self.set_child(self._backdrop)

        scrim = Gtk.Box()
        scrim.set_hexpand(True)
        scrim.set_vexpand(True)
        scrim.add_css_class("riff-full-player-scrim")
        self.add_overlay(scrim)

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        root.set_hexpand(True)
        root.set_vexpand(True)
        self.add_overlay(root)

        # Top chrome ----------------------------------------------------------
        top = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        top.add_css_class("riff-full-player-top")
        top.set_margin_top(10)
        top.set_margin_bottom(4)
        top.set_margin_start(12)
        top.set_margin_end(12)
        close = Gtk.Button(label="⌃")
        close.add_css_class("flat")
        close.add_css_class("circular")
        close.add_css_class("riff-heart")
        close.set_tooltip_text("Close player")
        close.connect("clicked", lambda *_: self.window.close_full_player())
        top.append(close)
        brand = Gtk.Label(label="Riff")
        brand.add_css_class("title-3")
        brand.set_hexpand(True)
        brand.set_xalign(0.5)
        top.append(brand)
        self._menu_btn = Gtk.MenuButton()
        self._menu_btn.set_child(iconutil.image("view-more-symbolic"))
        self._menu_btn.add_css_class("flat")
        self._menu_btn.set_tooltip_text("Song actions")
        self._menu_btn.set_sensitive(False)
        top.append(self._menu_btn)
        root.append(top)

        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.set_vexpand(True)
        body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        body.set_halign(Gtk.Align.CENTER)
        body.set_valign(Gtk.Align.CENTER)
        body.set_margin_start(28)
        body.set_margin_end(28)
        body.set_margin_top(8)
        body.set_margin_bottom(16)
        body.set_size_request(320, -1)
        scroll.set_child(body)
        root.append(scroll)

        self.art = CoverArt(280)
        self.art.set_halign(Gtk.Align.CENTER)
        self.art.add_css_class("riff-full-player-art")
        body.append(self.art)

        self._title = Gtk.Label(label="Not playing")
        self._title.add_css_class("title-1")
        self._title.set_wrap(True)
        self._title.set_justify(Gtk.Justification.CENTER)
        self._title.set_ellipsize(Pango.EllipsizeMode.END)
        self._title.set_lines(2)
        self._title.set_max_width_chars(36)
        body.append(self._title)

        self._artist = Gtk.Label(label="")
        self._artist.add_css_class("dim-label")
        self._artist.add_css_class("title-4")
        self._artist.set_ellipsize(Pango.EllipsizeMode.END)
        self._artist.set_max_width_chars(40)
        body.append(self._artist)

        seek_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        seek_row.set_hexpand(True)
        self.pos_label = Gtk.Label(label="0:00")
        self.pos_label.add_css_class("caption")
        self.pos_label.add_css_class("numeric")
        seek_row.append(self.pos_label)
        self.seek = Gtk.Scale.new_with_range(
            Gtk.Orientation.HORIZONTAL, 0, 100, 1)
        self.seek.set_hexpand(True)
        self.seek.set_draw_value(False)
        self.seek.connect("change-value", self._on_seek)
        seek_row.append(self.seek)
        self.dur_label = Gtk.Label(label="0:00")
        self.dur_label.add_css_class("caption")
        self.dur_label.add_css_class("numeric")
        seek_row.append(self.dur_label)
        body.append(seek_row)

        transport = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=18)
        transport.set_halign(Gtk.Align.CENTER)
        transport.set_margin_top(4)

        self.fav = heart_button(tooltip="Add to favorites")
        self.fav.connect("clicked", self._on_favorite)
        transport.append(self.fav)

        prev = Gtk.Button()
        iconutil.set_button(prev, "media-skip-backward-symbolic")
        prev.add_css_class("flat")
        prev.add_css_class("circular")
        prev.connect("clicked", lambda *_: self.service.previous())
        transport.append(prev)

        self.play_btn = Gtk.Button()
        iconutil.set_button(self.play_btn, "media-playback-start-symbolic")
        self.play_btn.add_css_class("pill")
        self.play_btn.add_css_class("suggested-action")
        self.play_btn.add_css_class("riff-full-play")
        self.play_btn.set_size_request(64, 64)
        self.play_btn.connect("clicked", lambda *_: self.service.toggle_pause())
        transport.append(self.play_btn)

        nxt = Gtk.Button()
        iconutil.set_button(nxt, "media-skip-forward-symbolic")
        nxt.add_css_class("flat")
        nxt.add_css_class("circular")
        nxt.connect("clicked", lambda *_: self.service.next())
        transport.append(nxt)

        self.repeat_btn = Gtk.Button()
        iconutil.set_button(self.repeat_btn, "media-playlist-repeat-symbolic")
        self.repeat_btn.add_css_class("flat")
        self.repeat_btn.add_css_class("circular")
        self.repeat_btn.set_tooltip_text("Repeat: off")
        self.repeat_btn.connect("clicked", self._on_repeat)
        transport.append(self.repeat_btn)
        body.append(transport)

        switch = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        switch.set_halign(Gtk.Align.CENTER)
        switch.set_margin_top(10)
        self._queue_tab = Gtk.ToggleButton(label="Queue")
        self._queue_tab.add_css_class("pill")
        self._lyrics_tab = Gtk.ToggleButton(label="Lyrics")
        self._lyrics_tab.add_css_class("pill")
        self._lyrics_tab.set_group(self._queue_tab)
        self._queue_tab.set_active(True)
        switch.append(self._queue_tab)
        switch.append(self._lyrics_tab)
        self._transcript_btn = Gtk.Button(label="Transcript")
        self._transcript_btn.add_css_class("pill")
        self._transcript_btn.set_visible(False)
        self._transcript_btn.connect("clicked", self._on_transcript)
        switch.append(self._transcript_btn)
        self._sleep_btn = Gtk.MenuButton(label="Sleep")
        self._sleep_btn.add_css_class("pill")
        self._sleep_btn.set_menu_model(self._build_sleep_menu())
        switch.append(self._sleep_btn)
        body.append(switch)
        self._sleep_tick_id = None

        self._similar_host = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self._similar_host.set_margin_top(8)
        body.append(self._similar_host)

        hint = Gtk.Label(label="Queue · lyrics · sleep · Esc closes")
        hint.add_css_class("caption")
        hint.add_css_class("dim-label")
        body.append(hint)

        svc = self.service
        svc.track_listeners.append(self._on_track)
        svc.state_listeners.append(self._on_state)
        svc.position_listeners.append(self._on_position)
        svc.duration_listeners.append(self._on_duration)

        self._tab_sync = False
        self._queue_tab.connect("toggled", self._on_queue_tab)
        self._lyrics_tab.connect("toggled", self._on_lyrics_tab)

        self._on_track(svc.current_track)
        self._start_sleep_ticker()

    def show_tab(self, name: str) -> None:
        self._tab_sync = True
        try:
            if name == "lyrics":
                self._lyrics_tab.set_active(True)
            else:
                self._queue_tab.set_active(True)
        finally:
            self._tab_sync = False

    def _on_queue_tab(self, btn: Gtk.ToggleButton) -> None:
        if self._tab_sync or not btn.get_active():
            return
        self.window._open_full_player_tab("queue")

    def _on_lyrics_tab(self, btn: Gtk.ToggleButton) -> None:
        if self._tab_sync or not btn.get_active():
            return
        self.window._open_full_player_tab("lyrics")

    def _set_backdrop(self, url: str) -> None:
        if not url:
            self._backdrop.set_paintable(None)
            return

        def apply(texture) -> None:
            self._backdrop.set_paintable(texture)

        # Soft wash (Vivi / Monochrome ambient canvas lite).
        images.load_blurred_texture(url, apply)

    def _start_sleep_ticker(self) -> None:
        from gi.repository import GLib

        if self._sleep_tick_id is not None:
            return

        def tick() -> bool:
            self._refresh_sleep_label()
            return True

        self._sleep_tick_id = GLib.timeout_add_seconds(1, tick)
        self._refresh_sleep_label()

    def _refresh_sleep_label(self) -> None:
        st = self.service.sleep_timer.state
        if not st.active:
            self._sleep_btn.set_label("Sleep")
            return
        left = self.service.sleep_timer.remaining_seconds()
        if left is None:
            self._sleep_btn.set_label("Sleep · EOS")
            return
        mins = int(left) // 60
        secs = int(left) % 60
        self._sleep_btn.set_label(f"Sleep · {mins}:{secs:02d}")

    def _on_track(self, track) -> None:
        self._current = track
        if track is None:
            self._title.set_label("Not playing")
            self._artist.set_label("")
            self.art.set_url("")
            self._set_backdrop("")
            self.fav.set_sensitive(False)
            self._menu_btn.set_sensitive(False)
            self._transcript_btn.set_visible(False)
            while child := self._similar_host.get_first_child():
                self._similar_host.remove(child)
            self.seek.set_value(0)
            self.pos_label.set_label("0:00")
            self.dur_label.set_label("0:00")
            return
        self.fav.set_sensitive(True)
        self._menu_btn.set_sensitive(True)
        self._title.set_label(track.title or "Unknown")
        self._artist.set_label(track.artist or "")
        self.art.set_url(track.thumbnail)
        self._set_backdrop(track.thumbnail or "")
        self.seek.set_range(0, max(track.duration, 1))
        self.dur_label.set_label(format_duration(track.duration))
        menu, group = build_track_menu(
            self.window, track, on_favorite=self._on_favorite)
        self._menu_btn.set_menu_model(menu)
        self._menu_btn.insert_action_group("trk", group)
        set_heart_state(
            self.fav,
            self.window.library.is_favorite(track.video_id)
            if track.video_id else False,
        )
        self._transcript_btn.set_visible(
            bool(getattr(track, "transcript_url", "") or ""))
        self._load_similar(track)

    def _on_transcript(self, *_a) -> None:
        track = self._current
        url = getattr(track, "transcript_url", "") if track else ""
        if not track or not url:
            return
        from .transcript import open_transcript
        open_transcript(
            self.window,
            url=url,
            type_=getattr(track, "transcript_type", "") or "",
            title=track.title or "",
        )

    def _build_sleep_menu(self):
        from gi.repository import Gio
        from ..core.sleep_timer import PRESETS_MINUTES

        menu = Gio.Menu()
        for mins in PRESETS_MINUTES:
            menu.append(f"{mins} minutes", f"win.sleep-timer::{mins}")
        menu.append("End of song", "win.sleep-timer::eos")
        menu.append("Cancel", "win.sleep-timer::cancel")
        return menu

    def _load_similar(self, track: Track) -> None:
        while child := self._similar_host.get_first_child():
            self._similar_host.remove(child)
        if not track or not track.video_id:
            return
        if (track.video_id or "").startswith(
                ("podcast_", "librivox_", "abs_", "cloud_")):
            return

        head = Gtk.Label(label="Similar")
        head.add_css_class("heading")
        head.set_xalign(0.0)
        self._similar_host.append(head)
        host = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        self._similar_host.append(host)
        loading = Gtk.Label(label="Finding similar…")
        loading.add_css_class("dim-label")
        host.append(loading)

        from ..util import run_async

        def work():
            return self.service.discovery.similar_songs(track, limit=6)

        def done(tracks: list[Track]) -> None:
            while child := host.get_first_child():
                host.remove(child)
            if not tracks:
                empty = Gtk.Label(label="No similar tracks yet")
                empty.add_css_class("dim-label")
                host.append(empty)
                return
            for t in tracks:
                row = Gtk.Button()
                row.add_css_class("flat")
                label = Gtk.Label(
                    label=f"{t.title} — {t.artist}",
                    xalign=0.0)
                label.set_ellipsize(Pango.EllipsizeMode.END)
                row.set_child(label)
                row.connect(
                    "clicked",
                    lambda _b, tr=t: self.service.play_track_with_radio(tr))
                host.append(row)

        run_async(work, done, lambda _e: None, name="riff-similar")

    def _on_state(self, state: str) -> None:
        playing = state in (STATE_PLAYING, STATE_LOADING)
        iconutil.set_button(
            self.play_btn,
            "media-playback-pause-symbolic" if playing
            else "media-playback-start-symbolic",
        )

    def _on_position(self, pos: float) -> None:
        if self._seeking:
            return
        self.seek.set_value(pos)
        self.pos_label.set_label(format_duration(pos))

    def _on_duration(self, dur: float) -> None:
        if dur > 0:
            self.seek.set_range(0, dur)
            self.dur_label.set_label(format_duration(dur))

    def _on_seek(self, _scale, _scroll, value) -> bool:
        self._seeking = True
        self.service.seek(float(value))
        self.pos_label.set_label(format_duration(value))

        def clear() -> bool:
            self._seeking = False
            return False

        from gi.repository import GLib
        GLib.timeout_add(120, clear)
        return False

    def _on_favorite(self, *_a) -> None:
        track = self._current
        if track is None or not track.video_id:
            return
        liked = self.window.library.toggle_favorite(track)
        set_heart_state(self.fav, liked)

    def _on_repeat(self, *_a) -> None:
        mode = self.service.queue.cycle_repeat()
        if mode == REPEAT_ONE:
            iconutil.set_button(
                self.repeat_btn, "media-playlist-repeat-song-symbolic")
            self.repeat_btn.add_css_class("accent")
        elif mode == REPEAT_ALL:
            iconutil.set_button(
                self.repeat_btn, "media-playlist-repeat-symbolic")
            self.repeat_btn.add_css_class("accent")
        else:
            iconutil.set_button(
                self.repeat_btn, "media-playlist-repeat-symbolic")
            self.repeat_btn.remove_css_class("accent")
        self.repeat_btn.set_tooltip_text(f"Repeat: {mode}")
