"""Torrents Digger — search public torrents-csv index (Riff Mobile)."""

from __future__ import annotations

import logging
import subprocess

from gi.repository import Gdk, Gtk, Pango

from ..core import torrents as torrents_mod
from ..util import run_async
from .widgets import scroll_wrap, spinner_page, status_page

log = logging.getLogger("riff.torrents_ui")


class TorrentsPage(Gtk.Box):
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

        title = Gtk.Label(label="Torrents")
        title.add_css_class("title-1")
        title.set_xalign(0.0)
        box.append(title)
        sub = Gtk.Label(
            label="Search the public torrents-csv index. Open magnets "
                  "in your torrent client, or copy the link.")
        sub.add_css_class("dim-label")
        sub.set_wrap(True)
        sub.set_xalign(0.0)
        box.append(sub)

        search_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        entry = Gtk.SearchEntry()
        entry.set_hexpand(True)
        entry.set_placeholder_text("Search torrents…")
        entry.connect("activate", lambda e: self._run_search(e.get_text()))
        search_row.append(entry)
        go = Gtk.Button(label="Search")
        go.add_css_class("suggested-action")
        go.connect("clicked", lambda *_: self._run_search(entry.get_text()))
        search_row.append(go)
        box.append(search_row)

        self._results = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        box.append(self._results)

    def _run_search(self, term: str) -> None:
        term = (term or "").strip()
        if not term:
            return
        self._clear(self._results)
        self._results.append(spinner_page())

        def work():
            return torrents_mod.search(term)

        def done(hits: list[torrents_mod.TorrentHit]) -> None:
            self._clear(self._results)
            if not hits:
                empty = Gtk.Label(label="No torrents found")
                empty.add_css_class("dim-label")
                self._results.append(empty)
                return
            for hit in hits:
                self._results.append(self._hit_row(hit))

        def fail(exc: Exception) -> None:
            self._clear(self._results)
            self._results.append(status_page(
                "network-error-symbolic", "Search failed", str(exc)))

        run_async(work, done, fail, name="riff-torrent-search")

    def _hit_row(self, hit: torrents_mod.TorrentHit) -> Gtk.Widget:
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        row.set_margin_top(4)
        row.set_margin_bottom(4)
        text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        text.set_hexpand(True)
        t = Gtk.Label(label=hit.name)
        t.add_css_class("heading")
        t.set_xalign(0.0)
        t.set_ellipsize(Pango.EllipsizeMode.END)
        meta = Gtk.Label(
            label=f"{hit.size_label} · ↑{hit.seeders} ↓{hit.leechers}")
        meta.add_css_class("caption")
        meta.add_css_class("dim-label")
        meta.set_xalign(0.0)
        text.append(t)
        text.append(meta)
        row.append(text)
        copy = Gtk.Button(label="Copy")
        copy.add_css_class("flat")
        copy.connect("clicked", lambda *_: self._copy(hit.magnet))
        row.append(copy)
        open_btn = Gtk.Button(label="Open")
        open_btn.add_css_class("suggested-action")
        open_btn.add_css_class("pill")
        open_btn.connect("clicked", lambda *_: self._open(hit.magnet))
        row.append(open_btn)
        return row

    def _copy(self, magnet: str) -> None:
        display = Gdk.Display.get_default()
        if display is None:
            return
        display.get_clipboard().set(magnet)
        self.window.toast("Magnet copied")

    def _open(self, magnet: str) -> None:
        try:
            subprocess.Popen(  # noqa: S603
                ["xdg-open", magnet],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            self.window.toast("Opening magnet…")
        except Exception as exc:  # noqa: BLE001
            self.window.toast(f"Couldn't open magnet: {exc}")
            self._copy(magnet)
