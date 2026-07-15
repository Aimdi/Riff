"""All content pages of the app."""

from __future__ import annotations

import random

from gi.repository import Adw, Gtk

from ..core.models import Album, Artist, Playlist, Track
from ..util import run_async
from .widgets import (
    CardGrid,
    Carousel,
    CoverArt,
    TrackList,
    scroll_wrap,
    spinner_page,
    status_page,
)


class ContentPage(Gtk.Box):
    """Base: swaps between spinner / error / loaded content."""

    def __init__(self, window):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.window = window
        self._current: Gtk.Widget | None = None

    def show_widget(self, widget: Gtk.Widget) -> None:
        if self._current is not None:
            self.remove(self._current)
        self._current = widget
        self.append(widget)

    def show_loading(self) -> None:
        self.show_widget(spinner_page())

    def show_error(self, message: str, retry=None) -> None:
        page = status_page(
            "network-error-symbolic", "Couldn't load content", str(message)
        )
        if retry is not None:
            btn = Gtk.Button(label="Try Again")
            btn.add_css_class("pill")
            btn.add_css_class("suggested-action")
            btn.set_halign(Gtk.Align.CENTER)
            btn.connect("clicked", lambda *_: retry())
            page.set_child(btn)
        self.show_widget(page)

    def load_async(self, work, present) -> None:
        """Run `work()` in a thread, then `present(result)`; handles errors."""
        self.show_loading()

        def on_error(exc: Exception) -> None:
            self.show_error(exc, retry=lambda: self.load_async(work, present))

        run_async(work, present, on_error)


class HomePage(ContentPage):
    def __init__(self, window):
        super().__init__(window)
        self._loaded = False

    def refresh(self, force: bool = False) -> None:
        if self._loaded and not force:
            return
        self.load_async(lambda: self.window.api.home(limit=8), self._present)

    def _present(self, sections) -> None:
        self._loaded = True
        if not sections:
            self.show_widget(status_page(
                "emblem-music-symbolic", "Nothing here yet",
                "Could not load recommendations — try searching instead."))
            return
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        box.set_margin_top(18)
        box.set_margin_bottom(120)
        box.set_margin_start(18)
        box.set_margin_end(18)
        for section in sections:
            tracks = [i for i in section.items if isinstance(i, Track)]
            others = [i for i in section.items if not isinstance(i, Track)]
            if others:
                box.append(Carousel(section.title, others, self.window))
            elif tracks:
                title = Gtk.Label(label=section.title)
                title.add_css_class("title-3")
                title.set_xalign(0.0)
                box.append(title)
                tl = TrackList(self.window, radio_on_single=True)
                tl.set_tracks(tracks[:10])
                box.append(tl)
        self.show_widget(scroll_wrap(box))


class SearchPage(ContentPage):
    FILTERS = [
        ("songs", "Songs"),
        ("albums", "Albums"),
        ("artists", "Artists"),
        ("playlists", "Playlists"),
    ]

    def __init__(self, window):
        super().__init__(window)
        self._query = ""
        self._kind = "songs"
        self._search_seq = 0

        controls = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        controls.set_margin_top(12)
        controls.set_margin_start(18)
        controls.set_margin_end(18)

        self.entry = Gtk.SearchEntry()
        self.entry.set_placeholder_text("Search songs, albums, artists…")
        self.entry.connect("activate", self._on_search)
        self.entry.connect("search-changed", self._on_maybe_search)
        controls.append(self.entry)

        filter_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self._filter_buttons: dict[str, Gtk.ToggleButton] = {}
        group_first: Gtk.ToggleButton | None = None
        for key, label in self.FILTERS:
            btn = Gtk.ToggleButton(label=label)
            btn.add_css_class("pill")
            if group_first is None:
                group_first = btn
                btn.set_active(True)
            else:
                btn.set_group(group_first)
            btn.connect("toggled", self._on_filter, key)
            self._filter_buttons[key] = btn
            filter_box.append(btn)
        controls.append(filter_box)
        self.append(controls)

        self._results_area = ContentPage(window)
        self._results_area.set_vexpand(True)
        self.append(self._results_area)
        self._results_area.show_widget(status_page(
            "system-search-symbolic", "Search YouTube Music",
            "Find songs, albums, artists and playlists."))

    def focus(self) -> None:
        self.entry.grab_focus()

    def _on_filter(self, button: Gtk.ToggleButton, key: str) -> None:
        if button.get_active():
            self._kind = key
            if self._query:
                self._run_search()

    def _on_maybe_search(self, entry: Gtk.SearchEntry) -> None:
        # Only auto-search once the user pauses; GTK already debounces
        # search-changed (~150 ms). Require a few chars to avoid noise.
        text = entry.get_text().strip()
        if len(text) >= 3 and text != self._query:
            self._query = text
            self._run_search()

    def _on_search(self, entry: Gtk.SearchEntry) -> None:
        self._query = entry.get_text().strip()
        if self._query:
            self._run_search()

    def _run_search(self) -> None:
        query, kind = self._query, self._kind
        self._search_seq += 1
        seq = self._search_seq

        def present(results: dict) -> None:
            if seq != self._search_seq:
                return  # stale response
            self._present(results)

        self._results_area.load_async(
            lambda: self.window.api.search(query, kind), present
        )

    def _present(self, results: dict) -> None:
        area = self._results_area
        songs = results.get("songs") or []
        cards = (results.get("albums") or []) + (results.get("playlists") or []) \
            + (results.get("artists") or [])
        if self._kind == "songs" and songs:
            tl = TrackList(self.window, radio_on_single=True)
            tl.set_tracks(songs)
            box = _padded(tl)
            area.show_widget(scroll_wrap(box))
        elif cards:
            grid = CardGrid(cards, self.window)
            area.show_widget(scroll_wrap(_padded(grid)))
        else:
            area.show_widget(status_page(
                "edit-find-symbolic", "No results",
                f"Nothing found for “{self._query}”."))


def _padded(child: Gtk.Widget) -> Gtk.Box:
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
    box.set_margin_top(12)
    box.set_margin_bottom(120)
    box.set_margin_start(18)
    box.set_margin_end(18)
    box.append(child)
    return box


class _DetailPage(ContentPage):
    """Shared layout for album and playlist pages."""

    def _header(self, thumbnail: str, title: str, subtitle: str,
                tracks: list[Track], circular: bool = False) -> Gtk.Widget:
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=20)
        art = CoverArt(180, circular=circular)
        art.set_url(thumbnail)
        art.set_valign(Gtk.Align.START)
        box.append(art)

        info = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        info.set_valign(Gtk.Align.CENTER)
        t = Gtk.Label(label=title)
        t.add_css_class("title-1")
        t.set_xalign(0.0)
        t.set_wrap(True)
        info.append(t)
        if subtitle:
            s = Gtk.Label(label=subtitle)
            s.add_css_class("dim-label")
            s.set_xalign(0.0)
            s.set_wrap(True)
            info.append(s)

        buttons = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        buttons.set_margin_top(10)
        play = Gtk.Button()
        play.set_child(_button_content("media-playback-start-symbolic", "Play"))
        play.add_css_class("pill")
        play.add_css_class("suggested-action")
        play.connect("clicked", lambda *_:
                     self.window.service.play_tracks(tracks) if tracks else None)
        buttons.append(play)

        shuffle = Gtk.Button()
        shuffle.set_child(_button_content(
            "media-playlist-shuffle-symbolic", "Shuffle"))
        shuffle.add_css_class("pill")
        shuffle.connect("clicked", lambda *_: self._play_shuffled(tracks))
        buttons.append(shuffle)

        queue = Gtk.Button()
        queue.set_child(_button_content("list-add-symbolic", "Queue"))
        queue.add_css_class("pill")
        queue.connect("clicked", lambda *_:
                      (self.window.service.add_to_queue(tracks),
                       self.window.toast("Added to queue")))
        buttons.append(queue)

        info.append(buttons)
        box.append(info)
        return box

    def _play_shuffled(self, tracks: list[Track]) -> None:
        if not tracks:
            return
        svc = self.window.service
        svc.play_tracks(tracks, start=random.randrange(len(tracks)))
        # If shuffle was already on, set_tracks built a shuffled order.
        if not svc.queue.shuffle:
            svc.queue.set_shuffle(True)


def _button_content(icon: str, label: str) -> Gtk.Box:
    box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
    box.append(Gtk.Image.new_from_icon_name(icon))
    box.append(Gtk.Label(label=label))
    return box


class AlbumPage(_DetailPage):
    def __init__(self, window, browse_id: str):
        super().__init__(window)
        self.load_async(lambda: window.api.album(browse_id), self._present)

    def _present(self, album: Album) -> None:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=20)
        subtitle_parts = [album.artist, album.year,
                          f"{len(album.tracks)} songs" if album.tracks else ""]
        box.append(self._header(
            album.thumbnail, album.title,
            " · ".join(p for p in subtitle_parts if p), album.tracks))
        tl = TrackList(self.window, numbered=True, show_art=False)
        tl.set_tracks(album.tracks)
        box.append(tl)
        self.show_widget(scroll_wrap(_padded(box)))


class PlaylistPage(_DetailPage):
    def __init__(self, window, playlist_id: str):
        super().__init__(window)
        self.load_async(lambda: window.api.playlist(playlist_id), self._present)

    def _present(self, pl: Playlist) -> None:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=20)
        subtitle_parts = [pl.author, f"{pl.track_count or len(pl.tracks)} songs"]
        box.append(self._header(
            pl.thumbnail, pl.title,
            " · ".join(p for p in subtitle_parts if p), pl.tracks))
        tl = TrackList(self.window)
        tl.set_tracks(pl.tracks)
        box.append(tl)
        self.show_widget(scroll_wrap(_padded(box)))


class ArtistPage(_DetailPage):
    def __init__(self, window, channel_id: str):
        super().__init__(window)
        self.load_async(lambda: window.api.artist(channel_id), self._present)

    def _present(self, artist: Artist) -> None:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        box.append(self._header(
            artist.thumbnail, artist.name, "Artist",
            artist.songs, circular=True))
        if artist.songs:
            title = Gtk.Label(label="Top Songs")
            title.add_css_class("title-3")
            title.set_xalign(0.0)
            box.append(title)
            tl = TrackList(self.window, radio_on_single=True)
            tl.set_tracks(artist.songs[:10])
            box.append(tl)
        if artist.albums:
            box.append(Carousel("Albums", artist.albums, self.window))
        if artist.singles:
            box.append(Carousel("Singles & EPs", artist.singles, self.window))
        self.show_widget(scroll_wrap(_padded(box)))


class LibraryPage(ContentPage):
    """Favorites / History / Downloads, backed by the local database."""

    def __init__(self, window, kind: str):
        super().__init__(window)
        self.kind = kind  # "favorites" | "history" | "downloads"

    def refresh(self) -> None:
        lib = self.window.library
        fetch = {
            "favorites": lib.favorites,
            "history": lib.recent,
            "downloads": lib.downloads,
        }[self.kind]
        self.load_async(fetch, self._present)

    def _present(self, tracks: list[Track]) -> None:
        if not tracks:
            icon, title, desc = {
                "favorites": ("emblem-favorite-symbolic", "No favorites yet",
                              "Songs you favorite appear here."),
                "history": ("document-open-recent-symbolic", "No history yet",
                            "Songs you play appear here."),
                "downloads": ("folder-download-symbolic", "No downloads yet",
                              "Use a song's menu to download it for offline listening."),
            }[self.kind]
            self.show_widget(status_page(icon, title, desc))
            return
        tl = TrackList(self.window)
        tl.set_tracks(tracks)
        self.show_widget(scroll_wrap(_padded(tl)))


class PlaylistsPage(ContentPage):
    """Local playlists list + create button."""

    def __init__(self, window):
        super().__init__(window)

    def refresh(self) -> None:
        self.load_async(self.window.library.playlists, self._present)

    def _present(self, playlists: list[tuple[int, str, int]]) -> None:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)

        new_btn = Gtk.Button()
        new_btn.set_child(_button_content("list-add-symbolic", "New Playlist"))
        new_btn.add_css_class("pill")
        new_btn.set_halign(Gtk.Align.START)
        new_btn.connect("clicked", lambda *_: self._create_dialog())
        box.append(new_btn)

        if playlists:
            listbox = Gtk.ListBox()
            listbox.add_css_class("boxed-list")
            listbox.set_selection_mode(Gtk.SelectionMode.NONE)
            for pid, name, count in playlists:
                row = Adw.ActionRow()
                row.set_title(name)
                row.set_subtitle(f"{count} songs")
                row.set_activatable(True)
                icon = Gtk.Image.new_from_icon_name("view-list-symbolic")
                row.add_prefix(icon)
                delete = Gtk.Button.new_from_icon_name("user-trash-symbolic")
                delete.add_css_class("flat")
                delete.set_valign(Gtk.Align.CENTER)
                delete.connect("clicked", self._on_delete, pid)
                row.add_suffix(delete)
                row.connect("activated", self._on_open, pid, name)
                listbox.append(row)
            box.append(listbox)
        else:
            box.append(status_page(
                "view-list-symbolic", "No playlists yet",
                "Create a playlist and add songs from any song menu."))
        self.show_widget(scroll_wrap(_padded(box)))

    def _create_dialog(self) -> None:
        self.window.prompt_text(
            "New Playlist", "Name",
            lambda name: (self.window.library.create_playlist(name),
                          self.refresh()))

    def _on_delete(self, _btn, pid: int) -> None:
        self.window.library.delete_playlist(pid)
        self.refresh()

    def _on_open(self, _row, pid: int, name: str) -> None:
        self.window.open_local_playlist(pid, name)


class LocalPlaylistPage(ContentPage):
    def __init__(self, window, playlist_id: int, name: str):
        super().__init__(window)
        self.playlist_id = playlist_id
        self.name = name
        self.refresh()

    def refresh(self) -> None:
        self.load_async(
            lambda: self.window.library.playlist_tracks(self.playlist_id),
            self._present)

    def _present(self, tracks: list[Track]) -> None:
        if not tracks:
            self.show_widget(status_page(
                "view-list-symbolic", self.name,
                "This playlist is empty — add songs from any song menu."))
            return
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        play = Gtk.Button()
        play.set_child(_button_content("media-playback-start-symbolic", "Play All"))
        play.add_css_class("pill")
        play.add_css_class("suggested-action")
        play.set_halign(Gtk.Align.START)
        play.connect("clicked",
                     lambda *_: self.window.service.play_tracks(tracks))
        box.append(play)
        tl = TrackList(self.window)
        tl.set_tracks(tracks)
        box.append(tl)
        self.show_widget(scroll_wrap(_padded(box)))
