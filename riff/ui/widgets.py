"""Reusable widgets: cover art, track rows, media cards, carousels."""

from __future__ import annotations

from gi.repository import Gio, Gtk, Pango

from ..core.models import Album, Artist, Playlist, Track
from . import iconutil, images


class FixedSquare(Gtk.Frame):
    """Container that measures exactly ``size``×``size``.

    ``set_size_request`` only raises the *minimum* — a child like
    Gtk.Picture holding a large texture or a live video paintable still
    reports the full media size as its natural size, and boxes hand out
    natural size when space allows. Overriding measure is the only hard
    clamp; content-fit COVER then crops the child into the square.
    """

    def __init__(self, size: int):
        super().__init__()
        self.size = size
        try:
            self.set_overflow(Gtk.Overflow.HIDDEN)
        except AttributeError:
            pass

    def do_measure(self, orientation, for_size):
        return (self.size, self.size, -1, -1)


class CoverArt(FixedSquare):
    """Square cover image with rounded corners and a placeholder icon.

    Sized strictly to ``size``×``size``. YouTube often serves large or 16:9
    video thumbnails; without clamping, Gtk.Picture grows to the texture's
    natural size and blows out layouts (especially the player bar).
    """

    def __init__(self, size: int = 48, icon: str = "audio-x-generic-symbolic",
                 circular: bool = False):
        super().__init__(size)
        self._url = ""
        self.add_css_class("riff-cover")
        if circular:
            self.add_css_class("riff-cover-circular")
        self.set_size_request(size, size)
        self.set_hexpand(False)
        self.set_vexpand(False)
        self.set_halign(Gtk.Align.CENTER)
        self.set_valign(Gtk.Align.CENTER)
        self._picture = Gtk.Picture()
        self._configure_picture(self._picture)
        self._placeholder = iconutil.image(icon, size=max(16, size // 3))
        self._placeholder.add_css_class("dim-label")
        self.set_child(self._placeholder)

    def _configure_picture(self, picture: Gtk.Picture) -> None:
        picture.set_size_request(self.size, self.size)
        picture.set_hexpand(False)
        picture.set_vexpand(False)
        # Critical: without can_shrink, Picture sizes to the full texture.
        try:
            picture.set_can_shrink(True)
        except AttributeError:
            pass
        try:
            picture.set_content_fit(Gtk.ContentFit.COVER)
        except AttributeError:
            try:
                picture.set_keep_aspect_ratio(False)
            except AttributeError:
                pass

    def set_url(self, url: str) -> None:
        if url == self._url:
            return
        self._url = url
        if not url:
            self.set_child(self._placeholder)
            return

        def apply(texture) -> None:
            if texture is not None and self._url == url:
                self._configure_picture(self._picture)
                self._picture.set_paintable(texture)
                self.set_child(self._picture)

        images.load_texture(url, max(self.size * 2, 96), apply)

    def set_urls(self, urls: list[str]) -> None:
        """Cover from several tracks: 2×2 collage when 4 distinct images
        exist (auto-generated playlist covers), else the first cover."""
        urls = [u for u in urls if u]
        marker = "collage:" + "|".join(urls[:4])
        if marker == self._url:
            return
        if len({u for u in urls}) < 4:
            self.set_url(urls[0] if urls else "")
            return
        self._url = marker

        def apply(texture) -> None:
            if texture is not None and self._url == marker:
                self._configure_picture(self._picture)
                self._picture.set_paintable(texture)
                self.set_child(self._picture)

        images.load_collage(urls, max(self.size * 2, 96), apply)


def heart_button(is_favorite: bool = False, tooltip: str = "Favorite") -> Gtk.Button:
    """Favorite button drawn with a text glyph.

    Icon-theme lookups proved unreliable across desktops (KDE's Breeze lacks
    emblem-favorite-symbolic and friends), so the heart is a plain font
    character — it renders everywhere, unconditionally.
    """
    btn = Gtk.Button()
    label = Gtk.Label(label="♥")
    label.add_css_class("riff-heart")
    btn.set_child(label)
    btn.add_css_class("flat")
    btn.set_valign(Gtk.Align.CENTER)
    btn.set_tooltip_text(tooltip)
    set_heart_state(btn, is_favorite)
    return btn


def set_heart_state(btn: Gtk.Button, is_favorite: bool) -> None:
    if is_favorite:
        btn.add_css_class("accent")
        btn.remove_css_class("dim-label")
    else:
        btn.remove_css_class("accent")
        btn.add_css_class("dim-label")


def menu_dots_button(tooltip: str = "More actions") -> Gtk.MenuButton:
    """Overflow menu button with a glyph child — same rationale as the heart."""
    btn = Gtk.MenuButton()
    label = Gtk.Label(label="⋮")
    label.add_css_class("riff-heart")
    btn.set_child(label)
    btn.add_css_class("flat")
    btn.set_valign(Gtk.Align.CENTER)
    btn.set_tooltip_text(tooltip)
    return btn


def _ellipsized(text: str, css: list[str] | None = None, align_start: bool = True) -> Gtk.Label:
    label = Gtk.Label(label=text)
    label.set_ellipsize(Pango.EllipsizeMode.END)
    if align_start:
        label.set_xalign(0.0)
    for c in css or []:
        label.add_css_class(c)
    return label


def build_track_menu(window, track: Track, on_favorite=None):
    """Build the standard per-song menu.

    Returns (menu_model, action_group); insert the group with prefix "trk"
    on the widget that hosts the menu. Used by track rows, the queue panel
    and the player bar so every place a song appears offers the same
    actions.
    """
    menu = Gio.Menu()
    sec1 = Gio.Menu()
    sec1.append("Play Next", "trk.play-next")
    sec1.append("Add to Queue", "trk.add-queue")
    sec1.append("Start Radio", "trk.radio")
    menu.append_section(None, sec1)

    sec2 = Gio.Menu()
    fav = ("Remove from Favorites"
           if window.library.is_favorite(track.video_id)
           else "Add to Favorites")
    sec2.append(fav, "trk.favorite")
    sec2.append("Add to Playlist…", "trk.add-playlist")
    sec2.append("Download", "trk.download")
    dis = ("Allow Again"
           if window.library.is_disliked(track.video_id)
           else "Never Play This")
    sec2.append(dis, "trk.dislike")
    menu.append_section(None, sec2)

    sec3 = Gio.Menu()
    if track.album_id:
        sec3.append("Go to Album", "trk.go-album")
    if any(track.artist_ids):
        sec3.append("Go to Artist", "trk.go-artist")
    if sec3.get_n_items():
        menu.append_section(None, sec3)

    def default_favorite():
        added = window.library.toggle_favorite(track)
        window.toast("Added to favorites" if added else "Removed from favorites")

    def toggle_dislike():
        if window.library.is_disliked(track.video_id):
            window.library.remove_dislike(track.video_id)
            window.toast(f"“{track.title}” allowed again")
        else:
            window.library.add_dislike(track)
            window.toast(
                f"“{track.title}” won't appear in radio or AI Mix anymore")

    def go_artist():
        for aid in track.artist_ids:
            if aid:
                window.open_artist(aid)
                return

    actions = {
        "play-next": lambda: (window.service.add_next([track]),
                              window.toast("Playing next")),
        "add-queue": lambda: (window.service.add_to_queue([track]),
                              window.toast("Added to queue")),
        "radio": lambda: window.service.play_track_with_radio(track),
        "favorite": on_favorite or default_favorite,
        "dislike": toggle_dislike,
        "add-playlist": lambda: window.choose_playlist_for(track),
        "download": lambda: window.download_track(track),
        "go-album": lambda: window.open_album(track.album_id),
        "go-artist": go_artist,
    }
    group = Gio.SimpleActionGroup()
    for name, cb in actions.items():
        action = Gio.SimpleAction.new(name, None)
        action.connect("activate", lambda _a, _p, cb=cb: cb())
        group.add_action(action)
    return menu, group


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

        self._fav_btn = heart_button(window.library.is_favorite(track.video_id))
        self._fav_btn.connect("clicked", lambda *_: self._toggle_favorite())
        box.append(self._fav_btn)

        menu_btn = menu_dots_button()
        menu, group = build_track_menu(window, track,
                                       on_favorite=self._toggle_favorite)
        menu_btn.set_menu_model(menu)
        self.insert_action_group("trk", group)
        box.append(menu_btn)

        self.set_child(box)

    def _toggle_favorite(self) -> None:
        added = self._window.library.toggle_favorite(self.track)
        set_heart_state(self._fav_btn, added)
        self._window.toast("Added to favorites" if added else "Removed from favorites")


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
            pid = item.playlist_id or ""
            if pid == "action:ai-mix":
                self._window.start_ai_mix()
            elif pid.startswith("local:"):
                try:
                    local_id = int(pid.split(":", 1)[1])
                except ValueError:
                    return
                self._window.open_local_playlist(local_id, item.title)
            else:
                self._window.open_playlist(pid)
        elif isinstance(item, Artist):
            if item.browse_id:
                self._window.open_artist(item.browse_id)
        elif isinstance(item, Track):
            self._window.service.play_track_with_radio(item)


class CompactTrackChip(Gtk.Button):
    """One short song pill for the Home “For you” strip (~52px tall)."""

    def __init__(self, track: Track, window, playlist: list[Track] | None = None):
        super().__init__()
        self.track = track
        self._window = window
        self._playlist = playlist or [track]
        self.add_css_class("flat")
        self.add_css_class("riff-for-you-chip")
        self.set_has_frame(False)
        self.set_valign(Gtk.Align.CENTER)

        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        row.set_margin_start(4)
        row.set_margin_end(8)
        row.set_margin_top(4)
        row.set_margin_bottom(4)
        art = CoverArt(40)
        art.set_url(track.thumbnail)
        row.append(art)
        text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        text.set_valign(Gtk.Align.CENTER)
        text.set_size_request(110, -1)
        title = _ellipsized(track.title, ["heading", "caption"])
        title.set_max_width_chars(16)
        title.set_single_line_mode(True)
        text.append(title)
        if track.artist:
            artist = _ellipsized(track.artist, ["dim-label", "caption"])
            artist.set_max_width_chars(16)
            artist.set_single_line_mode(True)
            text.append(artist)
        row.append(text)
        self.set_child(row)
        self.set_tooltip_text(f"{track.title}\n{track.artist}".strip())
        self.connect("clicked", self._on_clicked)

    def _on_clicked(self, _btn) -> None:
        tracks = self._playlist
        try:
            idx = next(i for i, t in enumerate(tracks)
                       if t.video_id == self.track.video_id)
        except StopIteration:
            idx = 0
        self._window.service.play_tracks(tracks, start=idx)


class ForYouStrip(Gtk.Box):
    """Compact horizontal “For you” row — one line of chips, not a full list."""

    def __init__(self, title: str, tracks: list[Track], window,
                 subtitle: str = ""):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self.set_vexpand(False)

        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        header.set_margin_start(2)
        t = Gtk.Label(label=title)
        t.add_css_class("heading")
        t.set_xalign(0.0)
        t.set_hexpand(True)
        header.append(t)
        if subtitle:
            s = Gtk.Label(label=subtitle)
            s.add_css_class("dim-label")
            s.add_css_class("caption")
            header.append(s)
        self.append(header)

        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.NEVER)
        scroller.set_vexpand(False)
        scroller.set_propagate_natural_height(True)
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        # Keep the strip short: a handful of chips, swipe for more.
        playlist = list(tracks[:10])
        for track in playlist:
            row.append(CompactTrackChip(track, window, playlist=playlist))
        scroller.set_child(row)
        self.append(scroller)


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
