"""Right-hand Now Playing panel: art, full queue, and lyrics.

Single owner of the queue UI (drag-reorder, clear, remove). Shares one
OverlaySplitView flap with the player bar's queue / now / lyrics toggles.
"""

from __future__ import annotations

from gi.repository import Gdk, GObject, Gtk, Pango

from ..core import lyrics as lyrics_mod
from ..util import run_async
from . import iconutil
from .widgets import CoverArt, build_track_menu, heart_button, menu_dots_button, set_heart_state


class NowPlayingPanel(Gtk.Box):
    def __init__(self, window):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.window = window
        self.service = window.service
        self.set_size_request(300, -1)
        self.set_margin_top(12)
        self.set_margin_bottom(12)
        self.set_margin_start(12)
        self.set_margin_end(12)

        self._lyrics_seq = 0
        self._lyrics_lines: list[tuple[float, str]] = []
        self._lyrics_labels: list[Gtk.Label] = []
        self._lyrics_idx = -1
        self._lyrics_video_id = ""

        header = Gtk.Label(label="Now Playing")
        header.add_css_class("heading")
        header.add_css_class("dim-label")
        header.set_xalign(0.0)
        self.append(header)

        self.art = CoverArt(200)
        self.art.set_halign(Gtk.Align.CENTER)
        self.append(self.art)

        self.title_btn = Gtk.Button()
        self.title_btn.add_css_class("flat")
        self.title_btn.add_css_class("riff-now-link")
        self._title = Gtk.Label(label="Not playing")
        self._title.add_css_class("title-3")
        self._title.set_wrap(True)
        self._title.set_lines(2)
        self._title.set_ellipsize(Pango.EllipsizeMode.END)
        self._title.set_xalign(0.0)
        self.title_btn.set_child(self._title)
        self.title_btn.set_halign(Gtk.Align.START)
        self.title_btn.connect("clicked", lambda *_: self._open_album())
        self.append(self.title_btn)

        artist_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.artist_btn = Gtk.Button()
        self.artist_btn.add_css_class("flat")
        self.artist_btn.add_css_class("riff-now-link")
        self._artist = Gtk.Label(label="")
        self._artist.add_css_class("dim-label")
        self._artist.set_ellipsize(Pango.EllipsizeMode.END)
        self._artist.set_xalign(0.0)
        self.artist_btn.set_child(self._artist)
        self.artist_btn.connect("clicked", lambda *_: self._open_artist())
        self.artist_btn.set_hexpand(True)
        self.artist_btn.set_halign(Gtk.Align.START)
        artist_row.append(self.artist_btn)
        self.fav = heart_button(tooltip="Add to favorites")
        self.fav.connect("clicked", self._on_favorite)
        artist_row.append(self.fav)
        self.append(artist_row)

        # Queue | Lyrics switcher ---------------------------------------------
        switch = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        switch.set_halign(Gtk.Align.CENTER)
        self._queue_tab = Gtk.ToggleButton(label="Queue")
        self._queue_tab.add_css_class("pill")
        self._lyrics_tab = Gtk.ToggleButton(label="Lyrics")
        self._lyrics_tab.add_css_class("pill")
        self._lyrics_tab.set_group(self._queue_tab)
        self._queue_tab.set_active(True)
        switch.append(self._queue_tab)
        switch.append(self._lyrics_tab)
        self.append(switch)

        self._tabs = Gtk.Stack()
        self._tabs.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        self._tabs.set_vexpand(True)

        # -- Queue tab (full queue with drag-reorder) -------------------------
        queue_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        q_head = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        q_title = Gtk.Label(label="Up next")
        q_title.add_css_class("heading")
        q_title.set_xalign(0.0)
        q_title.set_hexpand(True)
        q_head.append(q_title)
        clear = Gtk.Button()
        iconutil.set_button(clear, "user-trash-symbolic")
        clear.add_css_class("flat")
        clear.set_tooltip_text("Clear queue")
        clear.connect("clicked", self._on_clear)
        q_head.append(clear)
        queue_box.append(q_head)

        self.queue_list = Gtk.ListBox()
        self.queue_list.set_selection_mode(Gtk.SelectionMode.NONE)
        self.queue_list.add_css_class("navigation-sidebar")
        self.queue_list.connect("row-activated", self._on_queue_activated)
        q_scroll = Gtk.ScrolledWindow()
        q_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        q_scroll.set_vexpand(True)
        q_scroll.set_child(self.queue_list)
        queue_box.append(q_scroll)

        # Similar under queue
        self._similar_label = Gtk.Label(label="Similar")
        self._similar_label.add_css_class("heading")
        self._similar_label.set_xalign(0.0)
        self._similar_label.set_margin_top(6)
        self._similar_label.set_visible(False)
        queue_box.append(self._similar_label)
        self.similar_list = Gtk.ListBox()
        self.similar_list.add_css_class("boxed-list")
        self.similar_list.connect("row-activated", self._on_similar)
        queue_box.append(self.similar_list)

        self._tabs.add_named(queue_box, "queue")

        # -- Lyrics tab -------------------------------------------------------
        lyrics_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self._lyrics_status = Gtk.Label(label="Play a song to see lyrics")
        self._lyrics_status.add_css_class("dim-label")
        self._lyrics_status.set_wrap(True)
        self._lyrics_status.set_margin_top(12)
        lyrics_box.append(self._lyrics_status)

        self._lyrics_list = Gtk.ListBox()
        self._lyrics_list.set_selection_mode(Gtk.SelectionMode.NONE)
        self._lyrics_list.connect(
            "row-activated",
            lambda _lb, row: self.service.seek(getattr(row, "timestamp", 0)),
        )
        self._lyrics_plain = Gtk.Label(label="")
        self._lyrics_plain.set_wrap(True)
        self._lyrics_plain.set_selectable(True)
        self._lyrics_plain.set_xalign(0.0)
        self._lyrics_plain.set_margin_start(8)
        self._lyrics_plain.set_margin_end(8)
        self._lyrics_plain.set_visible(False)

        lyrics_stack = Gtk.Stack()
        lyrics_stack.set_vexpand(True)
        ly_scroll = Gtk.ScrolledWindow()
        ly_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        ly_scroll.set_vexpand(True)
        ly_scroll.set_child(self._lyrics_list)
        plain_scroll = Gtk.ScrolledWindow()
        plain_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        plain_scroll.set_vexpand(True)
        plain_scroll.set_child(self._lyrics_plain)
        lyrics_stack.add_named(ly_scroll, "synced")
        lyrics_stack.add_named(plain_scroll, "plain")
        self._lyrics_stack = lyrics_stack
        lyrics_box.append(lyrics_stack)
        self._tabs.add_named(lyrics_box, "lyrics")

        self.append(self._tabs)

        self._queue_tab.connect(
            "toggled", lambda b: b.get_active() and self.show_tab("queue"))
        self._lyrics_tab.connect(
            "toggled", lambda b: b.get_active() and self.show_tab("lyrics"))

        self._similar_seq = 0
        self.service.track_listeners.append(self._on_track)
        self.service.queue_listeners.append(lambda: self.refresh_queue())
        self.service.position_listeners.append(self._on_position)
        self.refresh()

    # -- public API -----------------------------------------------------------

    def show_tab(self, name: str) -> None:
        """Show 'queue' or 'lyrics' tab."""
        if name not in ("queue", "lyrics"):
            return
        self._tabs.set_visible_child_name(name)
        if name == "queue":
            self._queue_tab.set_active(True)
        else:
            self._lyrics_tab.set_active(True)
            self._ensure_lyrics()

    def open_lyrics(self) -> None:
        self.show_tab("lyrics")

    def open_queue(self) -> None:
        self.show_tab("queue")

    # -- data -----------------------------------------------------------------

    def _on_track(self, _track) -> None:
        self.refresh()
        # Invalidate lyrics for the new track.
        self._lyrics_video_id = ""
        if self._tabs.get_visible_child_name() == "lyrics":
            self._ensure_lyrics()

    def refresh(self) -> None:
        track = self.service.current_track
        if track is None:
            self._title.set_label("Not playing")
            self._artist.set_label("")
            self.art.set_url("")
            self.fav.set_sensitive(False)
        else:
            self._title.set_label(track.title)
            self._artist.set_label(track.artist)
            self.art.set_url(track.thumbnail)
            self.fav.set_sensitive(True)
            set_heart_state(
                self.fav, self.window.library.is_favorite(track.video_id))
        self.refresh_queue()
        self._load_similar(track)

    def refresh_queue(self) -> None:
        self.queue_list.remove_all()
        queue = self.service.queue
        current = queue.current_index
        for i, track in enumerate(queue.tracks):
            row = Gtk.ListBoxRow()
            box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            box.set_margin_top(3)
            box.set_margin_bottom(3)
            box.set_margin_start(4)
            box.set_margin_end(4)

            if i == current:
                icon = iconutil.image("media-playback-start-symbolic")
                icon.add_css_class("accent")
                box.append(icon)
            else:
                num = Gtk.Label(label=str(i + 1))
                num.add_css_class("dim-label")
                num.add_css_class("caption")
                num.set_width_chars(2)
                box.append(num)

            art = CoverArt(32)
            art.set_url(track.thumbnail)
            box.append(art)

            text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
            text.set_valign(Gtk.Align.CENTER)
            text.set_hexpand(True)
            t = Gtk.Label(label=track.title)
            t.set_ellipsize(Pango.EllipsizeMode.END)
            t.set_xalign(0.0)
            if i == current:
                t.add_css_class("heading")
            a = Gtk.Label(label=track.artist)
            a.set_ellipsize(Pango.EllipsizeMode.END)
            a.set_xalign(0.0)
            a.add_css_class("dim-label")
            a.add_css_class("caption")
            text.append(t)
            text.append(a)
            box.append(text)

            menu_btn = menu_dots_button()
            menu, group = build_track_menu(self.window, track)
            menu_btn.set_menu_model(menu)
            row.insert_action_group("trk", group)
            box.append(menu_btn)

            remove = Gtk.Button()
            iconutil.set_button(remove, "window-close-symbolic")
            remove.add_css_class("flat")
            remove.set_valign(Gtk.Align.CENTER)
            remove.set_tooltip_text("Remove from queue")
            remove.connect("clicked", self._on_remove, i)
            box.append(remove)

            row.set_child(box)
            self._make_draggable(row, i)
            self.queue_list.append(row)

    def _make_draggable(self, row: Gtk.ListBoxRow, index: int) -> None:
        source = Gtk.DragSource()
        source.set_actions(Gdk.DragAction.MOVE)
        source.connect(
            "prepare",
            lambda _s, _x, _y, i=index: Gdk.ContentProvider.new_for_value(str(i)),
        )
        row.add_controller(source)
        target = Gtk.DropTarget.new(GObject.TYPE_STRING, Gdk.DragAction.MOVE)
        target.connect("drop", self._on_drop, index)
        row.add_controller(target)

    def _on_drop(self, _target, value, _x, _y, dest_index: int) -> bool:
        try:
            src_index = int(value)
        except (TypeError, ValueError):
            return False
        self.service.queue.move(src_index, dest_index)
        return True

    def _on_queue_activated(self, _lb, row: Gtk.ListBoxRow) -> None:
        self.service.play_from_queue(row.get_index())

    def _on_remove(self, _btn, index: int) -> None:
        self.service.queue.remove_at(index)

    def _on_clear(self, _btn) -> None:
        self.service.stop()
        self.service.queue.clear()

    # -- lyrics ---------------------------------------------------------------

    def _ensure_lyrics(self) -> None:
        track = self.service.current_track
        if track is None:
            self._lyrics_status.set_label("Nothing is playing")
            self._lyrics_status.set_visible(True)
            self._clear_lyrics_body()
            return
        if track.video_id == self._lyrics_video_id and (
            self._lyrics_lines or self._lyrics_plain.get_label()
        ):
            return
        self._lyrics_seq += 1
        seq = self._lyrics_seq
        self._lyrics_status.set_label("Loading lyrics…")
        self._lyrics_status.set_visible(True)
        self._clear_lyrics_body()
        vid = track.video_id

        def work():
            from .. import config
            source = str(config.settings.get("lyrics_source", "auto") or "auto")
            synced, plain = lyrics_mod.fetch_lyrics(track, source=source)
            if not synced and not plain:
                plain = self.window.api.lyrics(track.video_id)
            return synced, plain

        def done(result) -> None:
            if seq != self._lyrics_seq:
                return
            synced, plain = result
            self._lyrics_video_id = vid
            if synced:
                self._show_synced(synced)
            else:
                self._show_plain(plain or "No lyrics found for this song.")

        def fail(_exc) -> None:
            if seq != self._lyrics_seq:
                return
            self._lyrics_status.set_label("Couldn't fetch lyrics")
            self._lyrics_status.set_visible(True)

        run_async(work, done, fail, name="riff-np-lyrics")

    def _clear_lyrics_body(self) -> None:
        self._lyrics_list.remove_all()
        self._lyrics_labels = []
        self._lyrics_lines = []
        self._lyrics_idx = -1
        self._lyrics_plain.set_label("")
        self._lyrics_plain.set_visible(False)

    def _show_synced(self, lines: list[tuple[float, str]]) -> None:
        self._lyrics_status.set_visible(False)
        self._lyrics_stack.set_visible_child_name("synced")
        self._lyrics_lines = lines
        self._lyrics_labels = []
        self._lyrics_list.remove_all()
        for ts, text in lines:
            row = Gtk.ListBoxRow()
            row.timestamp = ts
            label = Gtk.Label(label=text or "♪")
            label.set_wrap(True)
            label.set_xalign(0.0)
            label.set_margin_top(3)
            label.set_margin_bottom(3)
            label.add_css_class("dim-label")
            row.set_child(label)
            self._lyrics_list.append(row)
            self._lyrics_labels.append(label)
        self._on_position(0.0)

    def _show_plain(self, text: str) -> None:
        self._lyrics_status.set_visible(False)
        self._lyrics_stack.set_visible_child_name("plain")
        self._lyrics_plain.set_label(text)
        self._lyrics_plain.set_visible(True)
        self._lyrics_lines = []
        self._lyrics_labels = []

    def _on_position(self, pos: float) -> None:
        if not self._lyrics_lines or self._tabs.get_visible_child_name() != "lyrics":
            return
        idx = lyrics_mod.line_index_at(self._lyrics_lines, pos)
        if idx == self._lyrics_idx:
            return
        if 0 <= self._lyrics_idx < len(self._lyrics_labels):
            self._lyrics_labels[self._lyrics_idx].remove_css_class(
                "riff-lyric-current")
            self._lyrics_labels[self._lyrics_idx].add_css_class("dim-label")
        self._lyrics_idx = idx
        if 0 <= idx < len(self._lyrics_labels):
            self._lyrics_labels[idx].remove_css_class("dim-label")
            self._lyrics_labels[idx].add_css_class("riff-lyric-current")
            row = self._lyrics_list.get_row_at_index(idx)
            scroller = self._lyrics_list.get_ancestor(Gtk.ScrolledWindow)
            if row is not None and scroller is not None:
                vadj = scroller.get_vadjustment()
                target = row.get_allocation().y
                vadj.set_value(max(0.0, target - vadj.get_page_size() / 2.5))

    # -- similar --------------------------------------------------------------

    def _load_similar(self, track) -> None:
        self._similar_seq += 1
        seq = self._similar_seq
        self.similar_list.remove_all()
        self._similar_label.set_visible(False)
        if track is None or not track.video_id or not self.get_mapped():
            return
        if not hasattr(self.service, "discovery"):
            return

        def work():
            return self.service.discovery.similar_songs(track, limit=6)

        def done(tracks) -> None:
            if seq != self._similar_seq or not tracks:
                return
            self._similar_label.set_visible(True)
            for t in tracks:
                row = Gtk.ListBoxRow()
                row.similar_track = t
                box = Gtk.Box(
                    orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
                box.set_margin_top(4)
                box.set_margin_bottom(4)
                box.set_margin_start(6)
                box.set_margin_end(6)
                art = CoverArt(36)
                art.set_url(t.thumbnail)
                box.append(art)
                text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
                text.set_valign(Gtk.Align.CENTER)
                text.set_hexpand(True)
                title = Gtk.Label(label=t.title)
                title.set_xalign(0.0)
                title.set_ellipsize(Pango.EllipsizeMode.END)
                title.set_max_width_chars(20)
                artist = Gtk.Label(label=t.artist)
                artist.set_xalign(0.0)
                artist.add_css_class("dim-label")
                artist.add_css_class("caption")
                artist.set_ellipsize(Pango.EllipsizeMode.END)
                text.append(title)
                text.append(artist)
                box.append(text)
                add = Gtk.Button()
                plus = Gtk.Label(label="＋")
                plus.add_css_class("riff-heart")
                add.set_child(plus)
                add.add_css_class("flat")
                add.set_tooltip_text("Add to queue")
                add.connect(
                    "clicked",
                    lambda _b, tr=t: (
                        self.service.add_to_queue(
                            [tr], source="discover_section"),
                        self.window.toast("Added to queue"),
                    ),
                )
                box.append(add)
                row.set_child(box)
                self.similar_list.append(row)

        run_async(work, done, lambda _e: None, name="riff-np-similar")

    def _on_similar(self, _lb, row) -> None:
        track = getattr(row, "similar_track", None)
        if track is not None:
            self.service.add_next([track], source="discover_section")
            self.window.toast(f"“{track.title}” playing next")

    def _on_favorite(self, _btn) -> None:
        track = self.service.current_track
        if track is None:
            return
        added = self.window.library.toggle_favorite(track)
        set_heart_state(self.fav, added)

        def undo() -> None:
            self.window.library.toggle_favorite(track)
            set_heart_state(
                self.fav, self.window.library.is_favorite(track.video_id))

        if added:
            self.window.toast(
                "Added to favorites", action_label="Undo", action=undo)
        else:
            self.window.toast(
                "Removed from favorites", action_label="Undo", action=undo)

    def _open_album(self) -> None:
        track = self.service.current_track
        if track is not None and track.album_id:
            self.window.open_album(track.album_id)

    def _open_artist(self) -> None:
        track = self.service.current_track
        if track is None:
            return
        for aid in track.artist_ids:
            if aid:
                self.window.open_artist(aid)
                return
