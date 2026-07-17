"""Right-hand Now Playing panel: big artwork, song links, up next.

Shares the right OverlaySplitView with the queue panel (a Gtk.Stack picks
which one is visible) — like Spotify's now-playing sidebar.
"""

from __future__ import annotations

from gi.repository import Gtk, Pango

from .widgets import CoverArt, heart_button, set_heart_state


class NowPlayingPanel(Gtk.Box):
    def __init__(self, window):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        self.window = window
        self.service = window.service
        self.set_size_request(300, -1)
        self.set_margin_top(14)
        self.set_margin_bottom(14)
        self.set_margin_start(14)
        self.set_margin_end(14)

        header = Gtk.Label(label="Now Playing")
        header.add_css_class("heading")
        header.add_css_class("dim-label")
        header.set_xalign(0.0)
        self.append(header)

        self.art = CoverArt(272)
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
        self.title_btn.connect(
            "clicked", lambda *_: self._open_album())
        self.append(self.title_btn)

        artist_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL,
                             spacing=6)
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

        lists = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)

        up_next_label = Gtk.Label(label="Up next")
        up_next_label.add_css_class("heading")
        up_next_label.set_xalign(0.0)
        up_next_label.set_margin_top(6)
        lists.append(up_next_label)

        self.up_next = Gtk.ListBox()
        self.up_next.add_css_class("boxed-list")
        self.up_next.connect("row-activated", self._on_up_next)
        lists.append(self.up_next)

        # Similar songs for the current track (spec §3.4): every listening
        # moment is a discovery opportunity. Loaded lazily per track.
        self._similar_label = Gtk.Label(label="Similar")
        self._similar_label.add_css_class("heading")
        self._similar_label.set_xalign(0.0)
        self._similar_label.set_margin_top(6)
        self._similar_label.set_visible(False)
        lists.append(self._similar_label)
        self.similar_list = Gtk.ListBox()
        self.similar_list.add_css_class("boxed-list")
        self.similar_list.connect("row-activated", self._on_similar)
        lists.append(self.similar_list)

        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.set_vexpand(True)
        scroll.set_child(lists)
        self.append(scroll)

        self._similar_seq = 0
        self.service.track_listeners.append(lambda _t: self.refresh())
        self.service.queue_listeners.append(self.refresh)
        self.refresh()

    # -- data ---------------------------------------------------------------

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

        self._load_similar(track)

        self.up_next.remove_all()
        queue = self.service.queue
        start = queue.current_index + 1
        for offset, t in enumerate(queue.tracks[start:start + 8]):
            row = Gtk.ListBoxRow()
            row.order_index = start + offset
            box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
            box.set_margin_top(4)
            box.set_margin_bottom(4)
            box.set_margin_start(6)
            box.set_margin_end(6)
            art = CoverArt(36)
            art.set_url(t.thumbnail)
            box.append(art)
            text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
            text.set_valign(Gtk.Align.CENTER)
            title = Gtk.Label(label=t.title)
            title.set_xalign(0.0)
            title.set_ellipsize(Pango.EllipsizeMode.END)
            title.set_max_width_chars(24)
            artist = Gtk.Label(label=t.artist)
            artist.set_xalign(0.0)
            artist.add_css_class("dim-label")
            artist.add_css_class("caption")
            artist.set_ellipsize(Pango.EllipsizeMode.END)
            artist.set_max_width_chars(26)
            text.append(title)
            text.append(artist)
            box.append(text)
            row.set_child(box)
            self.up_next.append(row)

    def _load_similar(self, track) -> None:
        """Lazily fill the Similar section for the current song. Only
        loads while the panel is actually shown; stale results (user
        skipped on) are dropped by sequence check."""
        self._similar_seq += 1
        seq = self._similar_seq
        self.similar_list.remove_all()
        self._similar_label.set_visible(False)
        if track is None or not track.video_id or not self.get_mapped():
            return
        from ..util import run_async

        def work():
            return self.service.discovery.similar_songs(track, limit=6)

        def done(tracks) -> None:
            if seq != self._similar_seq or not tracks:
                return
            self._similar_label.set_visible(True)
            for t in tracks:
                row = Gtk.ListBoxRow()
                row.similar_track = t
                box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL,
                              spacing=10)
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
                artist.set_max_width_chars(22)
                text.append(title)
                text.append(artist)
                box.append(text)
                add = Gtk.Button()
                plus = Gtk.Label(label="＋")
                plus.add_css_class("riff-heart")
                add.set_child(plus)
                add.add_css_class("flat")
                add.set_valign(Gtk.Align.CENTER)
                add.set_tooltip_text("Add to queue")
                add.connect(
                    "clicked",
                    lambda _b, tr=t: (self.service.add_to_queue(
                        [tr], source="discover_section"),
                        self.window.toast("Added to queue")))
                box.append(add)
                row.set_child(box)
                self.similar_list.append(row)

        run_async(work, done, lambda _e: None, name="riff-np-similar")

    # -- interactions ---------------------------------------------------------

    def _on_similar(self, _lb, row) -> None:
        track = getattr(row, "similar_track", None)
        if track is not None:
            self.service.add_next([track], source="discover_section")
            self.window.toast(f"“{track.title}” playing next")

    def _on_up_next(self, _lb, row) -> None:
        self.service.play_from_queue(row.order_index)

    def _on_favorite(self, _btn) -> None:
        track = self.service.current_track
        if track is None:
            return
        added = self.window.library.toggle_favorite(track)
        set_heart_state(self.fav, added)
        self.window.toast(
            "Added to favorites" if added else "Removed from favorites")

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
