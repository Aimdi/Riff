"""Library destinations — Albums / Artists / More (Riff Mobile IA)."""

from __future__ import annotations

from gi.repository import Gtk

from ..core.models import Album, Artist, Track
from . import iconutil
from .widgets import CardGrid, scroll_wrap, status_page


# Overflow destinations under "More" on the mobile rail.
_MORE_DESTINATIONS = (
    ("podcasts", "Podcasts", "Apple directory + RSS — play episodes in Riff",
     "emblem-music-symbolic"),
    ("audiobooks", "Audiobooks",
     "LibriVox + Audiobookshelf — chapters play in Riff",
     "media-optical-symbolic"),
    ("cloud", "Cloud",
     "Subsonic / Navidrome — stream your own library",
     "network-server-symbolic"),
    ("soulsync", "SoulSync",
     "Search & queue downloads on your SoulSync server",
     "folder-download-symbolic"),
    ("explore", "Explore & Discover", "Charts, moods, and personal picks",
     "web-browser-symbolic"),
    ("history", "History", "Recently played",
     "document-open-recent-symbolic"),
    ("local", "Local Files", "Music on this computer",
     "folder-music-symbolic"),
    ("downloads", "Downloads", "Offline songs",
     "folder-download-symbolic"),
    ("stats", "Stats", "Listening insights",
     "riff-stats-symbolic"),
    ("dislikes", "Never Play This", "Banned from radio & mixes",
     "action-unavailable-symbolic"),
)


def _albums_from_tracks(tracks: list[Track]) -> list[Album]:
    seen: dict[str, Album] = {}
    for track in tracks:
        key = track.album_id or (track.album.lower().strip() if track.album else "")
        if not key or key in seen:
            continue
        seen[key] = Album(
            browse_id=track.album_id or "",
            title=track.album or "Album",
            artists=list(track.artists or []),
            thumbnail=track.thumbnail or "",
        )
    return list(seen.values())


def _artists_from_local(library) -> list[Artist]:
    """Followed artists first, then artists inferred from favorites/history."""
    out: list[Artist] = []
    seen: set[str] = set()
    for browse_id, name, thumb in library.followed_artists():
        if not browse_id or browse_id in seen:
            continue
        seen.add(browse_id)
        out.append(Artist(browse_id=browse_id, name=name, thumbnail=thumb))
    for track in library.favorites() + library.recent(80):
        for name, aid in zip(track.artists or [], track.artist_ids or []):
            key = aid or name.lower()
            if not key or key in seen:
                continue
            seen.add(key)
            out.append(Artist(
                browse_id=aid or "",
                name=name,
                thumbnail=track.thumbnail or "",
            ))
            if len(out) >= 60:
                return out
    return out


class AlbumsPage(Gtk.Box):
    """Albums gathered from favorites + history (mobile Library → Albums)."""

    def __init__(self, window):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.window = window
        self._host = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self._host.set_vexpand(True)
        self.append(self._host)

    def refresh(self) -> None:
        while child := self._host.get_first_child():
            self._host.remove(child)
        tracks = self.window.library.favorites() + self.window.library.recent(100)
        albums = [a for a in _albums_from_tracks(tracks) if a.browse_id]
        if not albums:
            self._host.append(status_page(
                "media-optical-symbolic", "No albums yet",
                "Play or like songs with album info — they'll show up here."))
            return
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        box.set_margin_top(18)
        box.set_margin_start(18)
        box.set_margin_end(18)
        box.set_margin_bottom(100)
        title = Gtk.Label(label="Albums")
        title.add_css_class("title-1")
        title.set_xalign(0.0)
        box.append(title)
        box.append(CardGrid(albums, self.window, size=140))
        self._host.append(scroll_wrap(box))


class ArtistsPage(Gtk.Box):
    """Followed + inferred artists (mobile Library → Artists)."""

    def __init__(self, window):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.window = window
        self._host = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self._host.set_vexpand(True)
        self.append(self._host)

    def refresh(self) -> None:
        while child := self._host.get_first_child():
            self._host.remove(child)
        artists = _artists_from_local(self.window.library)
        if not artists:
            self._host.append(status_page(
                "avatar-default-symbolic", "No artists yet",
                "Follow artists from their page, or play songs to seed this list."))
            return
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        box.set_margin_top(18)
        box.set_margin_start(18)
        box.set_margin_end(18)
        box.set_margin_bottom(100)
        title = Gtk.Label(label="Artists")
        title.add_css_class("title-1")
        title.set_xalign(0.0)
        box.append(title)
        # Prefer cards when we have thumbnails; fall back to a simple list.
        if any(a.thumbnail for a in artists):
            box.append(CardGrid(artists, self.window, size=120))
        else:
            listbox = Gtk.ListBox()
            listbox.add_css_class("boxed-list")
            listbox.set_selection_mode(Gtk.SelectionMode.NONE)
            for artist in artists:
                row = Gtk.ListBoxRow()
                btn = Gtk.Button(label=artist.name or "Artist")
                btn.add_css_class("flat")
                btn.set_halign(Gtk.Align.START)
                aid = artist.browse_id
                btn.connect(
                    "clicked",
                    lambda *_a, i=aid: i and self.window.open_artist(i))
                row.set_child(btn)
                listbox.append(row)
            box.append(listbox)
        self._host.append(scroll_wrap(box))


class LibraryHub(Gtk.Box):
    """“More” hub for History / Local / Downloads / Stats / Explore."""

    def __init__(self, window):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.window = window
        self.set_vexpand(True)

        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.set_vexpand(True)
        self.append(scroll)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        box.set_margin_top(20)
        box.set_margin_bottom(100)
        box.set_margin_start(20)
        box.set_margin_end(20)
        scroll.set_child(box)

        title = Gtk.Label(label="More")
        title.add_css_class("title-1")
        title.set_xalign(0.0)
        box.append(title)

        sub = Gtk.Label(
            label="Everything else from Riff Mobile — explore, history, "
                  "local files, downloads, and stats.")
        sub.add_css_class("dim-label")
        sub.set_wrap(True)
        sub.set_xalign(0.0)
        sub.set_margin_bottom(12)
        box.append(sub)

        listbox = Gtk.ListBox()
        listbox.add_css_class("boxed-list")
        listbox.set_selection_mode(Gtk.SelectionMode.NONE)
        listbox.connect("row-activated", self._on_row)
        box.append(listbox)

        for name, label, subtitle, icon in _MORE_DESTINATIONS:
            row = Gtk.ListBoxRow()
            row.dest_name = name
            row.set_activatable(True)
            inner = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=14)
            inner.set_margin_top(12)
            inner.set_margin_bottom(12)
            inner.set_margin_start(12)
            inner.set_margin_end(12)
            inner.append(iconutil.image(icon))
            text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
            text.set_hexpand(True)
            t = Gtk.Label(label=label)
            t.add_css_class("heading")
            t.set_xalign(0.0)
            s = Gtk.Label(label=subtitle)
            s.add_css_class("caption")
            s.add_css_class("dim-label")
            s.set_xalign(0.0)
            text.append(t)
            text.append(s)
            inner.append(text)
            chev = Gtk.Label(label="›")
            chev.add_css_class("dim-label")
            chev.add_css_class("title-3")
            inner.append(chev)
            row.set_child(inner)
            listbox.append(row)

    def _on_row(self, _lb, row) -> None:
        name = getattr(row, "dest_name", None)
        if name:
            self.window.goto(name)

    def refresh(self) -> None:
        return
