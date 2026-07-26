"""Cloud — Subsonic-compatible self-hosted music (Riff Mobile Cloud tab)."""

from __future__ import annotations

import logging

from gi.repository import Gtk, Pango

from .. import config
from ..core import cloud as cloud_mod
from ..core.models import format_duration
from ..util import run_async
from .widgets import CoverArt, scroll_wrap, spinner_page, status_page

log = logging.getLogger("riff.cloud_ui")


def _session() -> cloud_mod.CloudSession | None:
    host = str(config.settings.get("cloud_host", "") or "")
    user = str(config.settings.get("cloud_username", "") or "")
    password = str(config.settings.get("cloud_password", "") or "")
    if not host or not user or not password:
        return None
    return cloud_mod.CloudSession(
        host=cloud_mod.normalize_host(host),
        username=user,
        password=password,
        legacy_auth=bool(config.settings.get("cloud_legacy_auth", False)),
    )


class CloudPage(Gtk.Box):
    def __init__(self, window):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.window = window
        self._stack = Gtk.Stack()
        self._stack.set_vexpand(True)
        self.append(self._stack)

        self._hub = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self._stack.add_named(scroll_wrap(self._hub), "hub")
        self._detail = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self._stack.add_named(self._detail, "detail")
        self._stack.set_visible_child_name("hub")

    def refresh(self) -> None:
        self._show_hub()

    def _clear(self, box: Gtk.Box) -> None:
        while child := box.get_first_child():
            box.remove(child)

    def _show_hub(self) -> None:
        self._clear(self._hub)
        self._stack.set_visible_child_name("hub")
        box = self._hub
        box.set_margin_top(18)
        box.set_margin_bottom(100)
        box.set_margin_start(18)
        box.set_margin_end(18)
        box.set_spacing(14)

        title = Gtk.Label(label="Cloud")
        title.add_css_class("title-1")
        title.set_xalign(0.0)
        box.append(title)

        session = _session()
        if not session:
            sub = Gtk.Label(
                label="Stream your own collection from a Subsonic-compatible "
                      "server (Navidrome, OpenSubsonic, Airsonic…). "
                      "Connect in Preferences.")
            sub.add_css_class("dim-label")
            sub.set_wrap(True)
            sub.set_xalign(0.0)
            box.append(sub)
            return

        sub = Gtk.Label(label=session.host)
        sub.add_css_class("dim-label")
        sub.set_xalign(0.0)
        box.append(sub)

        search_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        entry = Gtk.SearchEntry()
        entry.set_hexpand(True)
        entry.set_placeholder_text("Search cloud library…")
        entry.connect("activate", lambda e: self._run_search(session, e.get_text()))
        search_row.append(entry)
        go = Gtk.Button(label="Search")
        go.add_css_class("suggested-action")
        go.connect(
            "clicked",
            lambda *_: self._run_search(session, entry.get_text()))
        search_row.append(go)
        box.append(search_row)

        self._results_host = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL, spacing=8)
        box.append(self._results_host)

        songs_head = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        sh = Gtk.Label(label="Random songs")
        sh.add_css_class("title-3")
        sh.set_xalign(0.0)
        sh.set_hexpand(True)
        songs_head.append(sh)
        reshuffle = Gtk.Button(label="Shuffle")
        reshuffle.add_css_class("flat")
        reshuffle.connect(
            "clicked", lambda *_: self._load_songs(session, self._songs_host))
        songs_head.append(reshuffle)
        box.append(songs_head)

        self._songs_host = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self._songs_host.append(Gtk.Label(label="Loading…"))
        box.append(self._songs_host)

        albums_h = Gtk.Label(label="Albums")
        albums_h.add_css_class("title-3")
        albums_h.set_xalign(0.0)
        albums_h.set_margin_top(8)
        box.append(albums_h)
        self._albums_host = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self._albums_host.append(Gtk.Label(label="Loading…"))
        box.append(self._albums_host)

        pl_h = Gtk.Label(label="Playlists")
        pl_h.add_css_class("title-3")
        pl_h.set_xalign(0.0)
        pl_h.set_margin_top(8)
        box.append(pl_h)
        self._playlists_host = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self._playlists_host.append(Gtk.Label(label="Loading…"))
        box.append(self._playlists_host)

        self._load_songs(session, self._songs_host)
        self._load_albums(session)
        self._load_playlists(session)

    def _load_songs(
        self, session: cloud_mod.CloudSession, host: Gtk.Box,
    ) -> None:
        self._clear(host)
        host.append(spinner_page())

        def work():
            return cloud_mod.fetch_random_songs(session, size=30)

        def done(songs: list[cloud_mod.CloudSong]) -> None:
            self._clear(host)
            if not songs:
                empty = Gtk.Label(label="No songs")
                empty.add_css_class("dim-label")
                host.append(empty)
                return
            tracks = cloud_mod.songs_to_tracks(session, songs)
            play = Gtk.Button(label=f"Play all · {len(tracks)}")
            play.add_css_class("suggested-action")
            play.add_css_class("pill")
            play.set_halign(Gtk.Align.START)
            play.connect(
                "clicked",
                lambda *_: self.window.service.play_tracks(
                    tracks, start=0, source="cloud"))
            host.append(play)
            for i, song in enumerate(songs):
                host.append(self._song_row(session, songs, i))

        def fail(exc: Exception) -> None:
            self._clear(host)
            host.append(status_page(
                "network-error-symbolic", "Couldn't load songs", str(exc)))

        run_async(work, done, fail, name="riff-cloud-songs")

    def _load_albums(self, session: cloud_mod.CloudSession) -> None:
        def work():
            return cloud_mod.fetch_albums(session, size=40)

        def done(albums: list[cloud_mod.CloudAlbum]) -> None:
            self._clear(self._albums_host)
            if not albums:
                empty = Gtk.Label(label="No albums")
                empty.add_css_class("dim-label")
                self._albums_host.append(empty)
                return
            for album in albums:
                self._albums_host.append(self._album_row(session, album))

        def fail(exc: Exception) -> None:
            self._clear(self._albums_host)
            self._albums_host.append(status_page(
                "network-error-symbolic", "Couldn't load albums", str(exc)))

        run_async(work, done, fail, name="riff-cloud-albums")

    def _load_playlists(self, session: cloud_mod.CloudSession) -> None:
        def work():
            return cloud_mod.fetch_playlists(session)

        def done(playlists: list[cloud_mod.CloudPlaylist]) -> None:
            self._clear(self._playlists_host)
            if not playlists:
                empty = Gtk.Label(label="No playlists")
                empty.add_css_class("dim-label")
                self._playlists_host.append(empty)
                return
            for pl in playlists:
                self._playlists_host.append(self._playlist_row(session, pl))

        def fail(exc: Exception) -> None:
            self._clear(self._playlists_host)
            self._playlists_host.append(status_page(
                "network-error-symbolic", "Couldn't load playlists", str(exc)))

        run_async(work, done, fail, name="riff-cloud-playlists")

    def _run_search(
        self, session: cloud_mod.CloudSession, term: str,
    ) -> None:
        term = (term or "").strip()
        if not term:
            return
        self._clear(self._results_host)
        self._results_host.append(spinner_page())

        def work():
            return cloud_mod.search(session, term)

        def done(result: cloud_mod.CloudSearchResult) -> None:
            self._clear(self._results_host)
            if not result.songs and not result.albums:
                empty = Gtk.Label(label="No results")
                empty.add_css_class("dim-label")
                self._results_host.append(empty)
                return
            label = Gtk.Label(label=f"Results for “{term}”")
            label.add_css_class("heading")
            label.set_xalign(0.0)
            self._results_host.append(label)
            if result.albums:
                ah = Gtk.Label(label="Albums")
                ah.add_css_class("caption")
                ah.add_css_class("dim-label")
                ah.set_xalign(0.0)
                self._results_host.append(ah)
                for album in result.albums:
                    self._results_host.append(self._album_row(session, album))
            if result.songs:
                sh = Gtk.Label(label="Songs")
                sh.add_css_class("caption")
                sh.add_css_class("dim-label")
                sh.set_xalign(0.0)
                self._results_host.append(sh)
                for i, _song in enumerate(result.songs):
                    self._results_host.append(
                        self._song_row(session, result.songs, i))

        def fail(exc: Exception) -> None:
            self._clear(self._results_host)
            self._results_host.append(status_page(
                "network-error-symbolic", "Search failed", str(exc)))

        run_async(work, done, fail, name="riff-cloud-search")

    def _song_row(
        self,
        session: cloud_mod.CloudSession,
        songs: list[cloud_mod.CloudSong],
        index: int,
    ) -> Gtk.Widget:
        song = songs[index]
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        row.set_margin_top(3)
        row.set_margin_bottom(3)
        art = CoverArt(48)
        art.set_url(cloud_mod.cover_url(session, song.cover_art, size=200))
        row.append(art)
        text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        text.set_hexpand(True)
        t = Gtk.Label(label=song.title)
        t.add_css_class("heading")
        t.set_xalign(0.0)
        t.set_ellipsize(Pango.EllipsizeMode.END)
        a = Gtk.Label(label=song.artist or song.album or "Cloud")
        a.add_css_class("dim-label")
        a.add_css_class("caption")
        a.set_xalign(0.0)
        a.set_ellipsize(Pango.EllipsizeMode.END)
        text.append(t)
        text.append(a)
        row.append(text)
        if song.duration:
            dur = Gtk.Label(label=format_duration(song.duration))
            dur.add_css_class("caption")
            dur.add_css_class("dim-label")
            row.append(dur)
        play = Gtk.Button(label="Play")
        play.add_css_class("flat")
        tracks = cloud_mod.songs_to_tracks(session, songs)
        play.connect(
            "clicked",
            lambda *_: self.window.service.play_tracks(
                tracks, start=index, source="cloud"))
        row.append(play)
        return row

    def _album_row(
        self, session: cloud_mod.CloudSession, album: cloud_mod.CloudAlbum,
    ) -> Gtk.Widget:
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        row.set_margin_top(3)
        row.set_margin_bottom(3)
        art = CoverArt(56)
        art.set_url(cloud_mod.cover_url(session, album.cover_art, size=200))
        row.append(art)
        text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        text.set_hexpand(True)
        t = Gtk.Label(label=album.name)
        t.add_css_class("heading")
        t.set_xalign(0.0)
        t.set_ellipsize(Pango.EllipsizeMode.END)
        a = Gtk.Label(label=album.artist or "Album")
        a.add_css_class("dim-label")
        a.add_css_class("caption")
        a.set_xalign(0.0)
        text.append(t)
        text.append(a)
        row.append(text)
        open_btn = Gtk.Button(label="Open")
        open_btn.add_css_class("suggested-action")
        open_btn.add_css_class("pill")
        open_btn.connect(
            "clicked",
            lambda *_: self._open_collection(session, "album", album.id))
        row.append(open_btn)
        return row

    def _playlist_row(
        self, session: cloud_mod.CloudSession, pl: cloud_mod.CloudPlaylist,
    ) -> Gtk.Widget:
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        row.set_margin_top(3)
        row.set_margin_bottom(3)
        art = CoverArt(56)
        art.set_url(cloud_mod.cover_url(session, pl.cover_art, size=200))
        row.append(art)
        text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        text.set_hexpand(True)
        t = Gtk.Label(label=pl.name)
        t.add_css_class("heading")
        t.set_xalign(0.0)
        meta = f"{pl.song_count} songs" if pl.song_count else "Playlist"
        a = Gtk.Label(label=meta)
        a.add_css_class("dim-label")
        a.add_css_class("caption")
        a.set_xalign(0.0)
        text.append(t)
        text.append(a)
        row.append(text)
        open_btn = Gtk.Button(label="Open")
        open_btn.add_css_class("suggested-action")
        open_btn.add_css_class("pill")
        open_btn.connect(
            "clicked",
            lambda *_: self._open_collection(session, "playlist", pl.id))
        row.append(open_btn)
        return row

    def _open_collection(
        self, session: cloud_mod.CloudSession, kind: str, item_id: str,
    ) -> None:
        self._clear(self._detail)
        self._stack.set_visible_child_name("detail")
        shell = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        shell.set_margin_top(12)
        shell.set_margin_start(16)
        shell.set_margin_end(16)
        shell.set_margin_bottom(100)
        self._detail.append(scroll_wrap(shell))

        back = Gtk.Button(label="← Cloud")
        back.add_css_class("flat")
        back.set_halign(Gtk.Align.START)
        back.connect("clicked", lambda *_: self._show_hub())
        shell.append(back)
        host = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        host.append(spinner_page())
        shell.append(host)

        def work():
            if kind == "playlist":
                return cloud_mod.fetch_playlist(session, item_id)
            return cloud_mod.fetch_album(session, item_id)

        def done(coll: cloud_mod.CloudCollection) -> None:
            self._clear(host)
            head = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=14)
            art = CoverArt(120)
            art.set_url(cloud_mod.cover_url(session, coll.cover_art))
            head.append(art)
            meta = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
            meta.set_valign(Gtk.Align.CENTER)
            title = Gtk.Label(label=coll.name)
            title.add_css_class("title-2")
            title.set_xalign(0.0)
            title.set_wrap(True)
            sub = Gtk.Label(label=coll.subtitle or kind.title())
            sub.add_css_class("dim-label")
            sub.set_xalign(0.0)
            meta.append(title)
            meta.append(sub)
            head.append(meta)
            host.append(head)

            tracks = cloud_mod.songs_to_tracks(session, coll.songs)
            if not tracks:
                host.append(status_page(
                    "emblem-music-symbolic", "No songs",
                    "This collection has no playable tracks."))
                return

            play_all = Gtk.Button(label=f"Play all · {len(tracks)}")
            play_all.add_css_class("suggested-action")
            play_all.add_css_class("pill")
            play_all.set_halign(Gtk.Align.START)
            play_all.connect(
                "clicked",
                lambda *_: self.window.service.play_tracks(
                    tracks, start=0, source="cloud"))
            host.append(play_all)

            for i, _song in enumerate(coll.songs):
                host.append(self._song_row(session, coll.songs, i))

        def fail(exc: Exception) -> None:
            self._clear(host)
            host.append(status_page(
                "network-error-symbolic", "Couldn't open", str(exc)))

        run_async(work, done, fail, name="riff-cloud-detail")
