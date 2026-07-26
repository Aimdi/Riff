"""SoulSync plugin page — search + request download (Riff Mobile)."""

from __future__ import annotations

import logging

from gi.repository import Gtk, Pango

from .. import config
from ..core import soulsync as ss
from ..core.models import format_duration
from ..util import run_async
from .widgets import CoverArt, scroll_wrap, spinner_page, status_page

log = logging.getLogger("riff.soulsync_ui")


def _session() -> ss.SoulSyncSession | None:
    host = str(config.settings.get("soulsync_host", "") or "")
    key = str(config.settings.get("soulsync_api_key", "") or "")
    if not host or not key:
        return None
    return ss.SoulSyncSession(host=ss.normalize_host(host), api_key=key)


class SoulSyncPage(Gtk.Box):
    def __init__(self, window):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.window = window
        self._hub = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.append(scroll_wrap(self._hub))

    def refresh(self) -> None:
        self._show_hub()

    def _clear(self, box: Gtk.Box) -> None:
        while child := box.get_first_child():
            box.remove(child)

    def _show_hub(self) -> None:
        self._clear(self._hub)
        box = self._hub
        box.set_margin_top(18)
        box.set_margin_bottom(100)
        box.set_margin_start(18)
        box.set_margin_end(18)
        box.set_spacing(14)

        title = Gtk.Label(label="SoulSync")
        title.add_css_class("title-1")
        title.set_xalign(0.0)
        box.append(title)

        session = _session()
        if not session:
            sub = Gtk.Label(
                label="Search and queue downloads on a self-hosted SoulSync "
                      "server. Connect with URL + API key in Preferences.")
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
        entry.set_placeholder_text("Search tracks to download…")
        entry.connect(
            "activate",
            lambda e: self._run_search(session, e.get_text()))
        search_row.append(entry)
        go = Gtk.Button(label="Search")
        go.add_css_class("suggested-action")
        go.connect(
            "clicked",
            lambda *_: self._run_search(session, entry.get_text()))
        search_row.append(go)
        box.append(search_row)

        self._results_host = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL, spacing=6)
        box.append(self._results_host)

        dl_head = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        h = Gtk.Label(label="Recent downloads")
        h.add_css_class("title-3")
        h.set_xalign(0.0)
        h.set_hexpand(True)
        dl_head.append(h)
        refresh = Gtk.Button(label="Refresh")
        refresh.add_css_class("flat")
        refresh.connect(
            "clicked", lambda *_: self._load_downloads(session))
        dl_head.append(refresh)
        box.append(dl_head)

        self._downloads_host = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self._downloads_host.append(Gtk.Label(label="Loading…"))
        box.append(self._downloads_host)
        self._load_downloads(session)

    def _run_search(self, session: ss.SoulSyncSession, term: str) -> None:
        term = (term or "").strip()
        if not term:
            return
        self._clear(self._results_host)
        self._results_host.append(spinner_page())

        def work():
            return ss.search_tracks(session, term)

        def done(tracks: list[ss.SoulSyncTrack]) -> None:
            self._clear(self._results_host)
            if not tracks:
                empty = Gtk.Label(label="No tracks found")
                empty.add_css_class("dim-label")
                self._results_host.append(empty)
                return
            label = Gtk.Label(label=f"Results for “{term}”")
            label.add_css_class("heading")
            label.set_xalign(0.0)
            self._results_host.append(label)
            for track in tracks:
                self._results_host.append(self._track_row(session, track))

        def fail(exc: Exception) -> None:
            self._clear(self._results_host)
            self._results_host.append(status_page(
                "network-error-symbolic", "Search failed", str(exc)))

        run_async(work, done, fail, name="riff-ss-search")

    def _track_row(
        self, session: ss.SoulSyncSession, track: ss.SoulSyncTrack,
    ) -> Gtk.Widget:
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        row.set_margin_top(4)
        row.set_margin_bottom(4)
        art = CoverArt(48)
        art.set_url(track.image_url)
        row.append(art)
        text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        text.set_hexpand(True)
        t = Gtk.Label(label=track.name)
        t.add_css_class("heading")
        t.set_xalign(0.0)
        t.set_ellipsize(Pango.EllipsizeMode.END)
        a = Gtk.Label(label=track.artist_label or track.album or "SoulSync")
        a.add_css_class("dim-label")
        a.add_css_class("caption")
        a.set_xalign(0.0)
        a.set_ellipsize(Pango.EllipsizeMode.END)
        text.append(t)
        text.append(a)
        row.append(text)
        if track.duration_ms:
            dur = Gtk.Label(
                label=format_duration(max(1, track.duration_ms // 1000)))
            dur.add_css_class("caption")
            dur.add_css_class("dim-label")
            row.append(dur)
        req = Gtk.Button(label="Download")
        req.add_css_class("suggested-action")
        req.add_css_class("pill")
        req.connect(
            "clicked",
            lambda *_: self._request(session, track))
        row.append(req)
        return row

    def _request(
        self, session: ss.SoulSyncSession, track: ss.SoulSyncTrack,
    ) -> None:
        query = track.request_query

        def work():
            return ss.request_download(session, query)

        def done(rid: str) -> None:
            self.window.toast(f"Queued: {track.name} ({rid})")
            self._load_downloads(session)

        def fail(exc: Exception) -> None:
            self.window.toast(f"SoulSync: {exc}")

        run_async(work, done, fail, name="riff-ss-request")

    def _load_downloads(self, session: ss.SoulSyncSession) -> None:
        self._clear(self._downloads_host)
        self._downloads_host.append(spinner_page())

        def work():
            return ss.list_downloads(session, limit=25)

        def done(rows: list[dict]) -> None:
            self._clear(self._downloads_host)
            if not rows:
                empty = Gtk.Label(label="No recent downloads")
                empty.add_css_class("dim-label")
                self._downloads_host.append(empty)
                return
            for row in rows:
                self._downloads_host.append(self._download_row(row))

        def fail(exc: Exception) -> None:
            self._clear(self._downloads_host)
            self._downloads_host.append(status_page(
                "network-error-symbolic", "Couldn't load downloads", str(exc)))

        run_async(work, done, fail, name="riff-ss-downloads")

    def _download_row(self, row: dict) -> Gtk.Widget:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        box.set_margin_top(4)
        box.set_margin_bottom(4)
        title = str(
            row.get("title") or row.get("query") or row.get("name")
            or "Download")
        t = Gtk.Label(label=title)
        t.add_css_class("heading")
        t.set_xalign(0.0)
        t.set_ellipsize(Pango.EllipsizeMode.END)
        status = str(row.get("status") or row.get("state") or "")
        s = Gtk.Label(label=status)
        s.add_css_class("dim-label")
        s.add_css_class("caption")
        s.set_xalign(0.0)
        box.append(t)
        box.append(s)
        return box
