"""All content pages of the app."""

from __future__ import annotations

import logging
import random

from gi.repository import Adw, Gtk

log = logging.getLogger("riff.pages")

from ..core.models import Album, Artist, Playlist, Track
from ..util import run_async
from . import iconutil
from .widgets import (
    CardGrid,
    Carousel,
    CoverArt,
    ForYouStrip,
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
    """Home feed: seamless “For you” picks on top, then YT Music sections."""

    def __init__(self, window):
        super().__init__(window)
        self._loaded = False
        self._box: Gtk.Box | None = None
        self._top: Gtk.Box | None = None
        self._for_you_host: Gtk.Box | None = None
        self._for_you_busy = False

    def refresh(self, force: bool = False) -> None:
        if self._loaded and not force:
            return
        self.load_async(lambda: self.window.api.home(limit=8), self._present)

    def _present(self, sections) -> None:
        self._loaded = True
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        box.set_margin_top(18)
        box.set_margin_bottom(120)
        box.set_margin_start(18)
        box.set_margin_end(18)

        # Top strip: For you (AI / smart picks) → followed releases → YT home.
        top = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        box.append(top)
        self._top = top
        self._box = box

        self._for_you_host = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        top.append(self._for_you_host)

        # Instant paint from cache, then refresh in the background.
        cached = self._cached_for_you()
        if cached:
            self.show_for_you(cached, source="ai")
        else:
            self._show_for_you_loading()
        self._ensure_for_you()

        if not sections and not cached:
            # Still show the page shell; For you may fill in shortly.
            pass

        for section in sections or []:
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

        if not sections and not cached:
            # Placeholder under For you if YT home is empty too.
            empty = status_page(
                "emblem-music-symbolic", "Loading your feed…",
                "Personal picks appear above as soon as they're ready.")
            box.append(empty)

        self.show_widget(scroll_wrap(box))
        self._load_followed_releases(top)

    def _cached_for_you(self) -> list[Track]:
        from .window import AI_MIX_PLAYLIST

        pid = self.window.library.find_playlist(AI_MIX_PLAYLIST)
        if pid is None:
            return []
        return self.window.library.playlist_tracks(pid)[:12]

    def _show_for_you_loading(self) -> None:
        host = self._for_you_host
        if host is None:
            return
        while child := host.get_first_child():
            host.remove(child)
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        row.set_margin_top(2)
        row.set_margin_bottom(2)
        title = Gtk.Label(label="For you")
        title.add_css_class("heading")
        row.append(title)
        spin = Gtk.Spinner()
        spin.set_size_request(16, 16)
        spin.start()
        row.append(spin)
        hint = Gtk.Label(label="Picking songs…")
        hint.add_css_class("dim-label")
        hint.add_css_class("caption")
        row.append(hint)
        host.append(row)

    def show_for_you(self, tracks: list[Track], *, source: str = "ai") -> None:
        """Paint a compact horizontal For you strip (not a full track list)."""
        host = self._for_you_host
        if host is None or not tracks:
            return
        while child := host.get_first_child():
            host.remove(child)

        subtitle = {
            "ai": "AI",
            "radio": "From your taste",
            "cache": "AI",
        }.get(source, "")
        host.append(ForYouStrip(
            "For you", tracks[:10], self.window, subtitle=subtitle))

    def _ensure_for_you(self) -> None:
        """Background: AI Mix if possible, else radio-based picks."""
        if self._for_you_busy:
            return
        self._for_you_busy = True

        # Prefer silent AI refresh when a provider is ready and mix is stale.
        if self.window.try_auto_for_you():
            # AI path will call on_for_you_ready when done.
            return

        self._load_radio_for_you(replace_cache=False)

    def _load_radio_for_you(self, *, replace_cache: bool) -> None:
        """Smart non-AI picks from YT radio around your taste."""
        win = self.window
        has_cache = bool(self._cached_for_you())
        self._for_you_busy = True

        def work():
            from ..core.suggestions import radio_for_you
            return radio_for_you(win.api, win.library, limit=12)

        def done(tracks: list[Track]) -> None:
            self._for_you_busy = False
            if not tracks or self._for_you_host is None:
                if not has_cache and self._for_you_host is not None:
                    while child := self._for_you_host.get_first_child():
                        self._for_you_host.remove(child)
                return
            if has_cache and not replace_cache and self._cached_for_you():
                return
            self.show_for_you(tracks, source="radio")

        def fail(_exc: Exception) -> None:
            self._for_you_busy = False
            if not has_cache and self._for_you_host is not None:
                while child := self._for_you_host.get_first_child():
                    self._for_you_host.remove(child)

        run_async(work, done, fail, name="riff-for-you")

    def on_for_you_ready(self, tracks: list[Track], *, source: str = "ai") -> None:
        """Called by the window after a background AI Mix finishes."""
        self._for_you_busy = False
        if tracks:
            self.show_for_you(tracks, source=source)
        elif not self._cached_for_you():
            # AI failed with nothing saved — fall back without re-entering AI.
            self._load_radio_for_you(replace_cache=True)

    def _load_followed_releases(self, top: Gtk.Box) -> None:
        """Append a 'new from your artists' carousel under For you."""
        follows = self.window.library.followed_artists()[:6]
        if not follows:
            return

        def work():
            items, seen = [], set()
            for browse_id, _name, _thumb in follows:
                try:
                    artist = self.window.api.artist(browse_id)
                except Exception:  # noqa: BLE001 — one artist must not kill all
                    continue
                for album in (artist.albums + artist.singles)[:2]:
                    if album.browse_id not in seen:
                        seen.add(album.browse_id)
                        items.append(album)
            return items

        def done(items) -> None:
            if items and top is self._top:
                top.append(Carousel(
                    "New from artists you follow", items, self.window))

        run_async(work, done, lambda _e: None, name="riff-follows")


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


class ExplorePage(ContentPage):
    """Public discovery without an account: charts and mood/genre playlists."""

    def __init__(self, window):
        super().__init__(window)
        self._loaded = False

    def refresh(self, force: bool = False) -> None:
        if self._loaded and not force:
            return

        def work():
            # Each source can fail independently (some endpoints behave
            # differently for authenticated accounts) — show whatever loads
            # and only fail the page when nothing at all came back.
            api = self.window.api
            problems = []
            try:
                categories = api.mood_categories()
            except Exception as exc:  # noqa: BLE001
                log.warning("mood categories failed", exc_info=True)
                categories = []
                problems.append(f"categories: {exc}")
            try:
                charts = api.charts()
            except Exception as exc:  # noqa: BLE001
                log.warning("charts failed", exc_info=True)
                charts = []
                problems.append(f"charts: {exc}")
            if not charts and not categories:
                raise RuntimeError("; ".join(problems) or "nothing returned")
            return charts, categories

        self.load_async(work, self._present)

    def _present(self, data) -> None:
        self._loaded = True
        charts, categories = data
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=20)
        if charts:
            title = Gtk.Label(label="Top songs worldwide")
            title.add_css_class("title-3")
            title.set_xalign(0.0)
            box.append(title)
            tl = TrackList(self.window, numbered=True, radio_on_single=True)
            tl.set_tracks(charts[:15])
            box.append(tl)
        for section, cats in categories:
            title = Gtk.Label(label=section)
            title.add_css_class("title-3")
            title.set_xalign(0.0)
            title.set_margin_top(8)
            box.append(title)
            flow = Gtk.FlowBox()
            flow.set_selection_mode(Gtk.SelectionMode.NONE)
            flow.set_max_children_per_line(10)
            flow.set_column_spacing(8)
            flow.set_row_spacing(8)
            for cat_title, params in cats:
                chip = Gtk.Button(label=cat_title)
                chip.add_css_class("pill")
                chip.connect("clicked", self._on_category, cat_title, params)
                flow.append(chip)
            box.append(flow)
        self.show_widget(scroll_wrap(_padded(box)))

    def _on_category(self, _btn, title: str, params: str) -> None:
        self.window.open_mood(title, params)


class MoodPage(ContentPage):
    """Grid of public playlists for one mood/genre category."""

    def __init__(self, window, title: str, params: str):
        super().__init__(window)
        self.load_async(
            lambda: window.api.mood_playlists(params), self._present)
        self._title = title

    def _present(self, playlists) -> None:
        if not playlists:
            self.show_widget(status_page(
                "view-list-symbolic", self._title, "No playlists found here."))
            return
        grid = CardGrid(playlists, self.window)
        self.show_widget(scroll_wrap(_padded(grid)))


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
                tracks: list[Track], circular: bool = False,
                extra_button: Gtk.Widget | None = None) -> Gtk.Widget:
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
        # Match the player-bar queue icon; list-add is reserved for "Add".
        queue.set_child(_button_content("view-list-ordered-symbolic", "Queue"))
        queue.add_css_class("pill")
        queue.connect("clicked", lambda *_:
                      (self.window.service.add_to_queue(tracks),
                       self.window.toast("Added to queue")))
        buttons.append(queue)
        if extra_button is not None:
            buttons.append(extra_button)

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
    box.append(iconutil.image(icon))
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
            " · ".join(p for p in subtitle_parts if p), pl.tracks,
            extra_button=self._add_button(pl)))
        tl = TrackList(self.window)
        tl.set_tracks(pl.tracks)
        box.append(tl)
        self.show_widget(scroll_wrap(_padded(box)))

    def _add_button(self, pl: Playlist) -> Gtk.Button:
        """Snapshot this public playlist into a local one."""
        btn = Gtk.Button()
        btn.set_child(_button_content("list-add-symbolic", "Add"))
        btn.add_css_class("pill")
        btn.set_tooltip_text("Save a local copy of this playlist")

        def on_clicked(_b: Gtk.Button) -> None:
            if not pl.tracks:
                self.window.toast("No songs to add")
                return
            name = pl.title.strip() or "Playlist"
            lib = self.window.library
            pid = lib.create_playlist(name)
            lib.replace_playlist_tracks(pid, pl.tracks)
            self.window.reload_sidebar_playlists()
            n = len(pl.tracks)
            plural = "song" if n == 1 else "songs"
            self.window.toast(f"Added “{name}” · {n} {plural}")
            btn.set_sensitive(False)
            btn.set_child(_button_content("list-add-symbolic", "Added"))

        btn.connect("clicked", on_clicked)
        return btn


class ArtistPage(_DetailPage):
    def __init__(self, window, channel_id: str):
        super().__init__(window)
        self.load_async(lambda: window.api.artist(channel_id), self._present)

    def _present(self, artist: Artist) -> None:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        box.append(self._header(
            artist.thumbnail, artist.name, "Artist",
            artist.songs, circular=True,
            extra_button=self._follow_button(artist)))
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

    def _follow_button(self, artist: Artist) -> Gtk.ToggleButton:
        btn = Gtk.ToggleButton()
        btn.add_css_class("pill")
        library = self.window.library
        btn.set_active(library.is_followed(artist.browse_id))
        btn.set_label("Following" if btn.get_active() else "Follow")

        def on_toggled(b: Gtk.ToggleButton) -> None:
            if b.get_active():
                library.follow_artist(
                    artist.browse_id, artist.name, artist.thumbnail)
                self.window.toast(
                    f"Following {artist.name} — new releases appear on Home")
            else:
                library.unfollow_artist(artist.browse_id)
                self.window.toast(f"Unfollowed {artist.name}")
            b.set_label("Following" if b.get_active() else "Follow")

        btn.connect("toggled", on_toggled)
        return btn


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
            "dislikes": lib.dislikes,
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
                "dislikes": ("action-unavailable-symbolic", "Nothing blocked",
                             "Use a song's menu → “Never Play This” to keep it "
                             "out of radio and AI Mix."),
            }[self.kind]
            self.show_widget(status_page(icon, title, desc))
            return
        tl = TrackList(self.window)
        tl.set_tracks(tracks)
        self.show_widget(scroll_wrap(_padded(tl)))


class StatsPage(ContentPage):
    """Listening statistics from the local history database."""

    def refresh(self) -> None:
        lib = self.window.library

        def work():
            return (lib.stats_overview(), lib.most_played(10),
                    lib.top_artists(10), lib.plays_by_day(14))

        self.load_async(work, self._present)

    def _present(self, data) -> None:
        overview, top_songs, top_artists, days = data
        if not overview["plays"]:
            self.show_widget(status_page(
                "riff-stats-symbolic", "No stats yet",
                "Play some music and your listening trends appear here."))
            return
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=22)

        # overview numbers
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        row.set_homogeneous(True)
        hours = overview["seconds"] / 3600
        for value, label in (
                (f"{overview['plays']}", "plays"),
                (f"{overview['songs']}", "different songs"),
                (f"{hours:.1f} h", "listened")):
            card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
            card.add_css_class("card")
            card.set_margin_top(2)
            v = Gtk.Label(label=value)
            v.add_css_class("title-1")
            v.set_margin_top(14)
            n = Gtk.Label(label=label)
            n.add_css_class("dim-label")
            n.set_margin_bottom(14)
            card.append(v)
            card.append(n)
            row.append(card)
        box.append(row)

        # last 14 days
        title = Gtk.Label(label="Last 14 days")
        title.add_css_class("title-3")
        title.set_xalign(0.0)
        box.append(title)
        maximum = max((c for _d, c in days), default=0) or 1
        day_list = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        for day, count in days:
            line = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
            d = Gtk.Label(label=day[5:])  # MM-DD
            d.add_css_class("numeric")
            d.add_css_class("dim-label")
            line.append(d)
            bar = Gtk.LevelBar.new_for_interval(0, maximum)
            bar.set_value(count)
            bar.set_hexpand(True)
            bar.set_valign(Gtk.Align.CENTER)
            line.append(bar)
            c = Gtk.Label(label=str(count))
            c.add_css_class("numeric")
            c.set_width_chars(4)
            line.append(c)
            day_list.append(line)
        box.append(day_list)

        # top songs
        if top_songs:
            t = Gtk.Label(label="Top songs")
            t.add_css_class("title-3")
            t.set_xalign(0.0)
            box.append(t)
            tl = TrackList(self.window, numbered=True, radio_on_single=True)
            tl.set_tracks([track for track, _plays in top_songs])
            box.append(tl)

        # top artists
        if top_artists:
            t = Gtk.Label(label="Top artists")
            t.add_css_class("title-3")
            t.set_xalign(0.0)
            box.append(t)
            lb = Gtk.ListBox()
            lb.add_css_class("boxed-list")
            lb.set_selection_mode(Gtk.SelectionMode.NONE)
            for i, (name, plays) in enumerate(top_artists, 1):
                row_a = Adw.ActionRow()
                row_a.set_title(f"{i}.  {name}")
                row_a.set_subtitle(f"{plays} plays")
                lb.append(row_a)
            box.append(lb)

        self.show_widget(scroll_wrap(_padded(box)))


class LocalFilesPage(ContentPage):
    """Music files from a local folder (Settings → local music folder)."""

    def refresh(self) -> None:
        from .. import config
        from ..core import localfiles

        folder = str(config.settings.get("local_music_dir", "~/Music"))
        self.load_async(lambda: (folder, localfiles.scan(folder)),
                        self._present)

    def _present(self, data) -> None:
        folder, tracks = data
        if not tracks:
            self.show_widget(status_page(
                "folder-music-symbolic", "No local music found",
                f"No audio files in {folder}. Change the folder in Settings — "
                "files named “Artist - Title.mp3” get proper artist tags."))
            return
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        play = Gtk.Button()
        play.set_child(_button_content("media-playback-start-symbolic",
                                       f"Play All ({len(tracks)})"))
        play.add_css_class("pill")
        play.add_css_class("suggested-action")
        play.set_halign(Gtk.Align.START)
        play.connect("clicked",
                     lambda *_: self.window.service.play_tracks(tracks))
        box.append(play)
        tl = TrackList(self.window, show_art=False)
        tl.set_tracks(tracks)
        box.append(tl)
        self.show_widget(scroll_wrap(_padded(box)))


class PlaylistsPage(ContentPage):
    """Local playlists + folders (Spotify-style)."""

    def __init__(self, window):
        super().__init__(window)

    def refresh(self) -> None:
        def work():
            tree = self.window.library.playlist_tree()
            covers = {}
            for item in tree:
                if item["kind"] == "playlist":
                    tracks = self.window.library.playlist_tracks(item["id"])
                    covers[item["id"]] = tracks[0].thumbnail if tracks else ""
                else:
                    for pid, _n, _c in item["playlists"]:
                        tracks = self.window.library.playlist_tracks(pid)
                        covers[pid] = tracks[0].thumbnail if tracks else ""
            return tree, covers

        self.load_async(work, self._present)

    def _present(self, data) -> None:
        tree, covers = data
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)

        actions = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        new_btn = Gtk.Button()
        new_btn.set_child(_button_content("list-add-symbolic", "New Playlist"))
        new_btn.add_css_class("pill")
        new_btn.connect("clicked", lambda *_: self._create_playlist())
        actions.append(new_btn)
        folder_btn = Gtk.Button()
        folder_btn.set_child(
            _button_content("folder-music-symbolic", "New Folder"))
        folder_btn.add_css_class("pill")
        folder_btn.connect("clicked", lambda *_: self._create_folder())
        actions.append(folder_btn)
        box.append(actions)

        if not tree:
            box.append(status_page(
                "view-list-symbolic", "No playlists yet",
                "Create a playlist or a folder to organize them."))
            self.show_widget(scroll_wrap(_padded(box)))
            return

        for item in tree:
            if item["kind"] == "folder":
                box.append(self._folder_block(item, covers))
            else:
                listbox = Gtk.ListBox()
                listbox.add_css_class("boxed-list")
                listbox.set_selection_mode(Gtk.SelectionMode.NONE)
                listbox.append(self._playlist_row(
                    item["id"], item["name"], item["count"], covers))
                box.append(listbox)

        self.show_widget(scroll_wrap(_padded(box)))

    def _folder_block(self, item: dict, covers: dict) -> Gtk.Widget:
        from gi.repository import Gdk, GObject

        block = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        ficon = item.get("icon") or "folder-music-symbolic"
        icon_btn = Gtk.Button()
        icon_btn.add_css_class("flat")
        icon_btn.set_tooltip_text("Change folder icon")
        icon_btn.set_child(iconutil.image(ficon, size=22))
        icon_btn.connect(
            "clicked",
            lambda *_: self.window.choose_folder_icon(item["id"], ficon))
        header.append(icon_btn)
        title = Gtk.Label(label=item["name"])
        title.add_css_class("title-3")
        title.set_xalign(0.0)
        title.set_hexpand(True)
        header.append(title)
        rename = Gtk.Button()
        iconutil.set_button(rename, "document-edit-symbolic")
        rename.add_css_class("flat")
        rename.set_tooltip_text("Rename folder")
        rename.connect("clicked", self._on_rename_folder, item["id"])
        header.append(rename)
        delete = Gtk.Button()
        iconutil.set_button(delete, "user-trash-symbolic")
        delete.add_css_class("flat")
        delete.set_tooltip_text("Delete folder (playlists stay)")
        delete.connect("clicked", self._on_delete_folder, item["id"])
        header.append(delete)
        block.append(header)

        listbox = Gtk.ListBox()
        listbox.add_css_class("boxed-list")
        listbox.set_selection_mode(Gtk.SelectionMode.NONE)
        # Drop playlists onto the folder's list area.
        drop = Gtk.DropTarget.new(GObject.TYPE_STRING, Gdk.DragAction.MOVE)
        drop.connect(
            "drop",
            lambda _t, value, _x, _y, fid=item["id"]:
                self.window._on_playlist_dropped(value, fid))
        listbox.add_controller(drop)
        if item["playlists"]:
            for pid, name, count in item["playlists"]:
                listbox.append(self._playlist_row(pid, name, count, covers))
        else:
            empty = Adw.ActionRow()
            empty.set_title("Empty folder")
            empty.set_subtitle(
                "Drag a playlist here, or use Move to folder on a playlist")
            empty.set_sensitive(False)
            listbox.append(empty)
        block.append(listbox)
        return block

    def _playlist_row(self, pid: int, name: str, count: int,
                      covers: dict) -> Adw.ActionRow:
        from gi.repository import Gdk

        row = Adw.ActionRow()
        row.set_title(name)
        row.set_subtitle(f"{count} songs · drag to a folder")
        row.set_activatable(True)
        art = CoverArt(44, icon="view-list-symbolic")
        art.set_url(covers.get(pid, ""))
        art.set_valign(Gtk.Align.CENTER)
        row.add_prefix(art)
        # Drag playlist onto a folder.
        source = Gtk.DragSource()
        source.set_actions(Gdk.DragAction.MOVE)
        source.connect(
            "prepare",
            lambda _s, _x, _y, p=pid:
                Gdk.ContentProvider.new_for_value(f"playlist:{p}"))
        row.add_controller(source)
        move = Gtk.Button()
        iconutil.set_button(move, "folder-music-symbolic")
        move.add_css_class("flat")
        move.set_valign(Gtk.Align.CENTER)
        move.set_tooltip_text("Move to folder")
        move.connect(
            "clicked",
            lambda *_: self.window.choose_folder_for(pid))
        row.add_suffix(move)
        rename = Gtk.Button()
        iconutil.set_button(rename, "document-edit-symbolic")
        rename.add_css_class("flat")
        rename.set_valign(Gtk.Align.CENTER)
        rename.set_tooltip_text("Rename")
        rename.connect("clicked", self._on_rename, pid)
        row.add_suffix(rename)
        delete = Gtk.Button()
        iconutil.set_button(delete, "user-trash-symbolic")
        delete.add_css_class("flat")
        delete.set_valign(Gtk.Align.CENTER)
        delete.set_tooltip_text("Delete")
        delete.connect("clicked", self._on_delete, pid)
        row.add_suffix(delete)
        row.connect("activated", self._on_open, pid, name)
        return row

    def _create_playlist(self) -> None:
        self.window.prompt_text(
            "New Playlist", "Name",
            lambda name: (self.window.library.create_playlist(name),
                          self.refresh(),
                          self.window.reload_sidebar_playlists()))

    def _create_folder(self) -> None:
        self.window.prompt_text(
            "New Folder", "Name",
            lambda name: (self.window.library.create_folder(name),
                          self.refresh(),
                          self.window.reload_sidebar_playlists()))

    def _on_rename(self, _btn, pid: int) -> None:
        self.window.prompt_text(
            "Rename Playlist", "New name",
            lambda name: (self.window.library.rename_playlist(pid, name),
                          self.refresh(),
                          self.window.reload_sidebar_playlists()),
            accept_label="Rename")

    def _on_rename_folder(self, _btn, folder_id: int) -> None:
        self.window.prompt_text(
            "Rename Folder", "New name",
            lambda name: (self.window.library.rename_folder(folder_id, name),
                          self.refresh(),
                          self.window.reload_sidebar_playlists()),
            accept_label="Rename")

    def _on_delete(self, _btn, pid: int) -> None:
        self.window.library.delete_playlist(pid)
        self.refresh()
        self.window.reload_sidebar_playlists()

    def _on_delete_folder(self, _btn, folder_id: int) -> None:
        self.window.library.delete_folder(folder_id)
        self.refresh()
        self.window.reload_sidebar_playlists()

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
