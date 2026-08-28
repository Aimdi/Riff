"""Full-screen Now Playing — Riff Mobile player on desktop."""

from __future__ import annotations

from gi.repository import Gtk, Pango

from ..core.models import Track, format_duration
from ..core.player import STATE_LOADING, STATE_PLAYING
from ..core.queue import REPEAT_ALL, REPEAT_ONE
from . import iconutil, images
from .widgets import CoverArt, build_track_menu, heart_button, set_heart_state


class FullPlayer(Gtk.Overlay):
    """Immersive player: art wash + large art (or lyrics), transport, queue."""

    def __init__(self, window):
        super().__init__()
        self.window = window
        self.service = window.service
        self._current: Track | None = None
        self._seeking = False
        self._lyrics_showing = False
        self._lyrics_seq = 0
        self._lyrics_lines: list[tuple[float, str]] = []
        self._lyrics_labels: list[Gtk.Label] = []
        self._lyrics_idx = -1
        self._lyrics_for = ""
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
        brand.add_css_class("riff-full-player-brand")
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

        # Art ↔ lyrics stage (mobile LyricsSwitch).
        self._stage = Gtk.Stack()
        self._stage.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        self._stage.set_transition_duration(180)
        self.art = CoverArt(280)
        self.art.set_halign(Gtk.Align.CENTER)
        self.art.add_css_class("riff-full-player-art")
        self._stage.add_named(self.art, "art")

        lyrics_scroll = Gtk.ScrolledWindow()
        lyrics_scroll.set_policy(
            Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        lyrics_scroll.set_size_request(280, 280)
        lyrics_scroll.add_css_class("riff-full-lyrics")
        self._lyrics_box = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL, spacing=2)
        self._lyrics_box.set_margin_start(8)
        self._lyrics_box.set_margin_end(8)
        self._lyrics_status = Gtk.Label(label="")
        self._lyrics_status.add_css_class("dim-label")
        self._lyrics_status.set_wrap(True)
        self._lyrics_status.set_justify(Gtk.Justification.CENTER)
        self._lyrics_box.append(self._lyrics_status)
        lyrics_scroll.set_child(self._lyrics_box)
        self._stage.add_named(lyrics_scroll, "lyrics")
        body.append(self._stage)

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

        # Primary actions only — sleep/speed/transcript live in More.
        switch = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        switch.set_halign(Gtk.Align.CENTER)
        switch.set_margin_top(12)
        self._queue_btn = Gtk.Button(label="Queue")
        self._queue_btn.add_css_class("pill")
        self._queue_btn.connect(
            "clicked", lambda *_: self.window._open_full_player_tab("queue"))
        switch.append(self._queue_btn)
        self._lyrics_btn = Gtk.ToggleButton(label="Lyrics")
        self._lyrics_btn.add_css_class("pill")
        self._lyrics_btn.connect("toggled", self._on_lyrics_toggle)
        switch.append(self._lyrics_btn)
        self._more_btn = Gtk.MenuButton(label="More")
        self._more_btn.add_css_class("pill")
        self._more_btn.set_menu_model(self._build_more_menu())
        self._install_player_actions()
        switch.append(self._more_btn)
        body.append(switch)

        # Keep sleep/speed widgets for label refresh (hidden; used by More).
        self._sleep_btn = self._more_btn
        self._speed_btn = self._more_btn
        self._transcript_btn = self._more_btn
        self._sleep_tick_id = None
        self._similar_host = Gtk.Box()  # unused; kept for API compatibility

        svc = self.service
        svc.track_listeners.append(self._on_track)
        svc.state_listeners.append(self._on_state)
        svc.position_listeners.append(self._on_position)
        svc.duration_listeners.append(self._on_duration)

        self._on_track(svc.current_track)
        self._start_sleep_ticker()

    def show_tab(self, name: str) -> None:
        """Sync chrome when the shell opens queue sheet or lyrics stage."""
        if name == "lyrics":
            if not self._lyrics_btn.get_active():
                self._lyrics_btn.set_active(True)
            return
        # Queue lives in the shell sheet — keep art stage visible.
        if self._lyrics_btn.get_active():
            self._lyrics_btn.set_active(False)

    def _on_lyrics_toggle(self, btn: Gtk.ToggleButton) -> None:
        self._lyrics_showing = bool(btn.get_active())
        if self._lyrics_showing:
            self._stage.set_visible_child_name("lyrics")
            self._ensure_lyrics()
        else:
            self._stage.set_visible_child_name("art")

    def _set_backdrop(self, url: str) -> None:
        if not url:
            self._backdrop.set_paintable(None)
            return

        def apply(texture) -> None:
            self._backdrop.set_paintable(texture)

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
        # Sleep state is shown via toast / More menu; keep ticker harmless.
        return

    def _on_track(self, track) -> None:
        self._current = track
        self._lyrics_seq += 1
        self._lyrics_lines = []
        self._lyrics_labels = []
        self._lyrics_idx = -1
        self._lyrics_for = ""
        if track is None:
            self._title.set_label("Not playing")
            self._artist.set_label("")
            self.art.set_url("")
            self._set_backdrop("")
            self.fav.set_sensitive(False)
            self._menu_btn.set_sensitive(False)
            self._clear_lyrics_body("Nothing is playing")
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
        if self._lyrics_showing:
            self._ensure_lyrics()

    def _on_transcript(self, *_a) -> None:
        track = self._current
        url = getattr(track, "transcript_url", "") if track else ""
        if not track or not url:
            self.window.toast("No transcript for this episode")
            return
        from .transcript import open_transcript
        open_transcript(
            self.window,
            url=url,
            type_=getattr(track, "transcript_type", "") or "",
            title=track.title or "",
        )

    def _build_more_menu(self):
        from gi.repository import Gio
        from ..core.sleep_timer import PRESETS_MINUTES

        menu = Gio.Menu()
        sleep = Gio.Menu()
        for mins in PRESETS_MINUTES:
            sleep.append(f"{mins} minutes", f"win.sleep-timer::{mins}")
        sleep.append("End of song", "win.sleep-timer::eos")
        sleep.append("Cancel", "win.sleep-timer::cancel")
        menu.append_submenu("Sleep timer", sleep)

        speed = Gio.Menu()
        for rate in self._SPEEDS:
            label = "1×" if rate == 1.0 else f"{rate:g}×"
            speed.append(label, f"fp.speed::{rate:g}")
        menu.append_submenu("Playback speed", speed)
        menu.append("Transcript", "fp.transcript")
        return menu

    _SPEEDS = (0.75, 1.0, 1.25, 1.5, 1.75, 2.0)

    def _install_player_actions(self) -> None:
        from gi.repository import Gio, GLib

        group = Gio.SimpleActionGroup()
        speed = Gio.SimpleAction.new("speed", GLib.VariantType.new("s"))
        speed.connect("activate", self._on_speed_action)
        group.add_action(speed)
        transcript = Gio.SimpleAction.new("transcript", None)
        transcript.connect("activate", lambda *_: self._on_transcript())
        group.add_action(transcript)
        self.insert_action_group("fp", group)

    def _on_speed_action(self, _action, param) -> None:
        try:
            rate = float(param.get_string())
        except (TypeError, ValueError, AttributeError):
            return
        self.service.set_playback_speed(rate)
        label = "1×" if abs(rate - 1.0) < 0.01 else f"{rate:g}×"
        self.window.toast(f"Speed · {label}")

    def _clear_lyrics_body(self, status: str = "") -> None:
        while child := self._lyrics_box.get_first_child():
            self._lyrics_box.remove(child)
        self._lyrics_status = Gtk.Label(label=status)
        self._lyrics_status.add_css_class("dim-label")
        self._lyrics_status.set_wrap(True)
        self._lyrics_status.set_justify(Gtk.Justification.CENTER)
        self._lyrics_box.append(self._lyrics_status)
        self._lyrics_labels = []
        self._lyrics_lines = []
        self._lyrics_idx = -1

    def _ensure_lyrics(self) -> None:
        track = self._current
        if track is None:
            self._clear_lyrics_body("Nothing is playing")
            return
        if track.video_id == self._lyrics_for and self._lyrics_lines:
            return
        self._lyrics_seq += 1
        seq = self._lyrics_seq
        self._clear_lyrics_body("Loading lyrics…")
        vid = track.video_id

        from ..util import run_async
        from ..core import lyrics as lyrics_mod
        from .. import config

        def work():
            source = str(config.settings.get("lyrics_source", "auto") or "auto")
            hit = lyrics_mod.fetch_lyrics_result(track, source=source)
            if hit is None:
                plain = self.window.api.lyrics(track.video_id)
                if plain:
                    return lyrics_mod.LyricsResult(
                        synced=[], plain=plain, source="youtube")
                return None
            return hit

        def done(hit) -> None:
            if seq != self._lyrics_seq:
                return
            self._lyrics_for = vid
            if hit is None:
                self._clear_lyrics_body("No lyrics found for this song.")
                return
            if hit.synced:
                self._show_synced(hit.synced)
            else:
                self._clear_lyrics_body(
                    hit.plain or "No lyrics found for this song.")

        run_async(work, done, lambda _e: self._clear_lyrics_body(
            "Couldn't fetch lyrics"), name="riff-fp-lyrics")

    def _show_synced(self, lines: list[tuple[float, str]]) -> None:
        while child := self._lyrics_box.get_first_child():
            self._lyrics_box.remove(child)
        self._lyrics_lines = lines
        self._lyrics_labels = []
        self._lyrics_idx = -1
        for _t, text in lines:
            lab = Gtk.Label(label=text or " ")
            lab.add_css_class("riff-full-lyrics-line")
            lab.set_wrap(True)
            lab.set_justify(Gtk.Justification.CENTER)
            lab.set_xalign(0.5)
            self._lyrics_box.append(lab)
            self._lyrics_labels.append(lab)

    def _highlight_lyrics(self, pos: float) -> None:
        if not self._lyrics_showing or not self._lyrics_lines:
            return
        idx = -1
        for i, (t, _text) in enumerate(self._lyrics_lines):
            if t <= pos:
                idx = i
            else:
                break
        if idx == self._lyrics_idx or idx < 0:
            return
        if 0 <= self._lyrics_idx < len(self._lyrics_labels):
            self._lyrics_labels[self._lyrics_idx].remove_css_class(
                "riff-full-lyrics-line-active")
        self._lyrics_idx = idx
        lab = self._lyrics_labels[idx]
        lab.add_css_class("riff-full-lyrics-line-active")

    def _on_state(self, state: str) -> None:
        playing = state in (STATE_PLAYING, STATE_LOADING)
        iconutil.set_button(
            self.play_btn,
            "media-playback-pause-symbolic" if playing
            else "media-playback-start-symbolic",
        )

    def _on_position(self, pos: float) -> None:
        if not self._seeking:
            self.seek.set_value(pos)
            self.pos_label.set_label(format_duration(pos))
        self._highlight_lyrics(float(pos or 0))

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
