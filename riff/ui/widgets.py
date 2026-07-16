"""Reusable widgets: cover art, track rows, media cards, carousels."""

from __future__ import annotations

from gi.repository import Gio, Gtk, Pango

from ..core.models import Album, Artist, Playlist, Track
from . import images


class CoverArt(Gtk.Frame):
    """Square cover image with rounded corners and a placeholder icon."""

    def __init__(self, size: int = 48, icon: str = "audio-x-generic-symbolic",
                 circular: bool = False):
        super().__init__()
        self.size = size
        self._url = ""
        self.add_css_class("riff-cover")
        if circular:
            self.add_css_class("riff-cover-circular")
        self.set_size_request(size, size)
        self._picture = Gtk.Picture()
        self._picture.set_size_request(size, size)
        try:
            self._picture.set_content_fit(Gtk.ContentFit.COVER)
        except AttributeError:
            pass
        self._placeholder = Gtk.Image.new_from_icon_name(icon)
        self._placeholder.set_pixel_size(max(16, size // 3))
        self._placeholder.add_css_class("dim-label")
        self.set_child(self._placeholder)

    def set_url(self, url: str) -> None:
        if url == self._url:
            return
        self._url = url
        if not url:
            self.set_child(self._placeholder)
            return

        def apply(texture) -> None:
            if texture is not None and self._url == url:
                self._picture.set_paintable(texture)
                self.set_child(self._picture)

        images.load_texture(url, max(self.size * 2, 96), apply)


def _ellipsized(text: str, css: list[str] | None = None, align_start: bool = True) -> Gtk.Label:
    label = Gtk.Label(label=text)
    label.set_ellipsize(Pango.EllipsizeMode.END)
    if align_start:
        label.set_xalign(0.0)
    for c in css or []:
        label.add_css_class(c)
    return label


class TrackRow(Gtk.ListBoxRow):
    """One track in a list: art, title/artist, duration, context menu."""

    def __init__(self, track: Track, window, index: int | None = None,
                 show_art: bool = True):
        super().__init__()
        self.track = track
        self._window = window
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        box.set_margin_top(6)
        box.set_margin_bottom(6)
        box.set_margin_start(10)
        box.set_margin_end(6)

        if index is not None:
            num = Gtk.Label(label=str(index + 1))
            num.add_css_class("dim-label")
            num.add_css_class("numeric")
            num.set_width_chars(3)
            box.append(num)
        if show_art:
            art = CoverArt(44)
            art.set_url(track.thumbnail)
            box.append(art)

        text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        text.set_valign(Gtk.Align.CENTER)
        text.set_hexpand(True)
        text.append(_ellipsized(track.title, ["heading"]))
        subtitle = track.artist or track.album
        if subtitle:
            text.append(_ellipsized(subtitle, ["dim-label", "caption"]))
        box.append(text)

        if track.duration:
            dur = Gtk.Label(label=track.duration_text)
            dur.add_css_class("dim-label")
            dur.add_css_class("numeric")
            box.append(dur)

        self._fav_btn = Gtk.Button.new_from_icon_name("emblem-favorite-symbolic")
        self._fav_btn.add_css_class("flat")
        self._fav_btn.set_valign(Gtk.Align.CENTER)
        self._fav_btn.set_tooltip_text("Favorite")
        if window.library.is_favorite(track.video_id):
            self._fav_btn.add_css_class("accent")
        self._fav_btn.connect("clicked", lambda *_: self._toggle_favorite())
        box.append(self._fav_btn)

        menu_btn = Gtk.MenuButton()
        menu_btn.set_icon_name("view-more-symbolic")
        menu_btn.add_css_class("flat")
        menu_btn.set_valign(Gtk.Align.CENTER)
        menu_btn.set_tooltip_text("More actions")
        menu_btn.set_menu_model(self._build_menu())
        self._install_actions()
        box.append(menu_btn)

        self.set_child(box)

    # -- context menu ----------------------------------------------------------

    def _build_menu(self) -> Gio.Menu:
        menu = Gio.Menu()
        sec1 = Gio.Menu()
        sec1.append("Play Next", "row.play-next")
        sec1.append("Add to Queue", "row.add-queue")
        sec1.append("Start Radio", "row.radio")
        menu.append_section(None, sec1)

        sec2 = Gio.Menu()
        fav = "Remove from Favorites" if self._window.library.is_favorite(
            self.track.video_id) else "Add to Favorites"
        sec2.append(fav, "row.favorite")
        sec2.append("Add to Playlist…", "row.add-playlist")
        sec2.append("Download", "row.download")
        menu.append_section(None, sec2)

        sec3 = Gio.Menu()
        if self.track.album_id:
            sec3.append("Go to Album", "row.go-album")
        if any(self.track.artist_ids):
            sec3.append("Go to Artist", "row.go-artist")
        if sec3.get_n_items():
            menu.append_section(None, sec3)
        return menu

    def _install_actions(self) -> None:
        group = Gio.SimpleActionGroup()
        actions = {
            "play-next": lambda: self._window.service.add_next([self.track]),
            "add-queue": lambda: self._window.service.add_to_queue([self.track]),
            "radio": lambda: self._window.service.play_track_with_radio(self.track),
            "favorite": self._toggle_favorite,
            "add-playlist": lambda: self._window.choose_playlist_for(self.track),
            "download": lambda: self._window.download_track(self.track),
            "go-album": lambda: self._window.open_album(self.track.album_id),
            "go-artist": self._go_artist,
        }
        for name, cb in actions.items():
            action = Gio.SimpleAction.new(name, None)
            action.connect("activate", lambda _a, _p, cb=cb: cb())
            group.add_action(action)
        self.insert_action_group("row", group)

    def _toggle_favorite(self) -> None:
        added = self._window.library.toggle_favorite(self.track)
        if added:
            self._fav_btn.add_css_class("accent")
        else:
            self._fav_btn.remove_css_class("accent")
        self._window.toast("Added to favorites" if added else "Removed from favorites")

    def _go_artist(self) -> None:
        for aid in self.track.artist_ids:
            if aid:
                self._window.open_artist(aid)
                return


class TrackList(Gtk.ListBox):
    """A list of TrackRows; activating a row plays the list from that row."""

    def __init__(self, window, numbered: bool = False, show_art: bool = True,
                 radio_on_single: bool = False):
        super().__init__()
        self._window = window
        self._numbered = numbered
        self._show_art = show_art
        self._radio_on_single = radio_on_single
        self.tracks: list[Track] = []
        self.add_css_class("boxed-list")
        self.set_selection_mode(Gtk.SelectionMode.NONE)
        self.connect("row-activated", self._on_activated)

    def set_tracks(self, tracks: list[Track]) -> None:
        self.remove_all()
        self.tracks = list(tracks)
        for i, t in enumerate(tracks):
            self.append(TrackRow(t, self._window,
                                 index=i if self._numbered else None,
                                 show_art=self._show_art))

    def _on_activated(self, _list, row: TrackRow) -> None:
        idx = self.tracks.index(row.track) if row.track in self.tracks else 0
        if self._radio_on_single:
            self._window.service.play_track_with_radio(row.track)
        else:
            self._window.service.play_tracks(self.tracks, start=idx)


class MediaCard(Gtk.FlowBoxChild):
    """Square card for albums / playlists / artists in grids and carousels."""

    def __init__(self, item, window, size: int = 160):
        super().__init__()
        self.item = item
        self._window = window

        button = Gtk.Button()
        button.add_css_class("flat")
        button.add_css_class("riff-card")
        button.connect("clicked", self._on_clicked)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        box.set_size_request(size, -1)

        circular = isinstance(item, Artist)
        icon = {
            Album: "media-optical-symbolic",
            Playlist: "view-list-symbolic",
            Artist: "avatar-default-symbolic",
        }.get(type(item), "audio-x-generic-symbolic")
        art = CoverArt(size, icon=icon, circular=circular)
        art.set_url(getattr(item, "thumbnail", ""))
        box.append(art)

        title = getattr(item, "title", "") or getattr(item, "name", "")
        title_label = _ellipsized(title, ["heading"])
        title_label.set_max_width_chars(18)
        box.append(title_label)

        subtitle = self._subtitle()
        if subtitle:
            sub = _ellipsized(subtitle, ["dim-label", "caption"])
            sub.set_max_width_chars(20)
            box.append(sub)

        button.set_child(box)
        self.set_child(button)

    def _subtitle(self) -> str:
        item = self.item
        if isinstance(item, Album):
            parts = [item.artist, item.year]
            return " · ".join(p for p in parts if p)
        if isinstance(item, Playlist):
            return item.author
        if isinstance(item, Artist):
            return "Artist"
        if isinstance(item, Track):
            return item.artist
        return ""

    def _on_clicked(self, _btn) -> None:
        item = self.item
        if isinstance(item, Album):
            self._window.open_album(item.browse_id)
        elif isinstance(item, Playlist):
            self._window.open_playlist(item.playlist_id)
        elif isinstance(item, Artist):
            if item.browse_id:
                self._window.open_artist(item.browse_id)
        elif isinstance(item, Track):
            self._window.service.play_track_with_radio(item)


class Carousel(Gtk.Box):
    """Titled horizontal scroller of MediaCards."""

    def __init__(self, title: str, items: list, window, card_size: int = 160):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        header = Gtk.Label(label=title)
        header.add_css_class("title-3")
        header.set_xalign(0.0)
        header.set_margin_start(4)
        self.append(header)

        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.NEVER)
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        for item in items:
            card = MediaCard(item, window, size=card_size)
            # FlowBoxChild works fine standalone inside a Box.
            row.append(card)
        scroller.set_child(row)
        self.append(scroller)


class CardGrid(Gtk.FlowBox):
    def __init__(self, items: list, window, size: int = 160):
        super().__init__()
        self.set_valign(Gtk.Align.START)
        self.set_selection_mode(Gtk.SelectionMode.NONE)
        self.set_max_children_per_line(8)
        self.set_column_spacing(12)
        self.set_row_spacing(16)
        self.set_homogeneous(True)
        for item in items:
            self.append(MediaCard(item, window, size=size))


def status_page(icon: str, title: str, description: str = "") -> Gtk.Widget:
    from gi.repository import Adw

    page = Adw.StatusPage()
    page.set_icon_name(icon)
    page.set_title(title)
    if description:
        page.set_description(description)
    page.set_vexpand(True)
    return page


def spinner_page() -> Gtk.Widget:
    spinner = Gtk.Spinner()
    spinner.set_size_request(40, 40)
    spinner.start()
    spinner.set_halign(Gtk.Align.CENTER)
    spinner.set_valign(Gtk.Align.CENTER)
    spinner.set_vexpand(True)
    return spinner


def scroll_wrap(child: Gtk.Widget) -> Gtk.ScrolledWindow:
    sw = Gtk.ScrolledWindow()
    sw.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
    sw.set_vexpand(True)
    sw.set_child(child)
    return sw
