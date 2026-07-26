"""Seeker / slskd — Soulseek search via self-hosted slskd."""

from __future__ import annotations

import logging
import time

from gi.repository import Gtk, Pango

from .. import config
from ..core import slskd as slskd_mod
from ..util import run_async
from .widgets import scroll_wrap, spinner_page, status_page

log = logging.getLogger("riff.seeker_ui")


def _session() -> slskd_mod.SlskdSession | None:
    host = str(config.settings.get("slskd_host", "") or "")
    if not host:
        return None
    return slskd_mod.SlskdSession(
        host=slskd_mod.normalize_host(host),
        api_key=str(config.settings.get("slskd_api_key", "") or ""),
    )


class SeekerPage(Gtk.Box):
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

        title = Gtk.Label(label="Seeker")
        title.add_css_class("title-1")
        title.set_xalign(0.0)
        box.append(title)

        session = _session()
        if not session:
            sub = Gtk.Label(
                label="Search Soulseek through a self-hosted slskd server. "
                      "Connect in Preferences (URL + optional API key).")
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
        entry.set_placeholder_text("Search Soulseek…")
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

        self._results = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        box.append(self._results)

    def _run_search(
        self, session: slskd_mod.SlskdSession, term: str,
    ) -> None:
        term = (term or "").strip()
        if not term:
            return
        self._clear(self._results)
        self._results.append(spinner_page())

        def work():
            sid = slskd_mod.search(session, term)
            # slskd fills responses asynchronously — poll briefly.
            hits: list[slskd_mod.SlskdHit] = []
            for _ in range(8):
                time.sleep(0.6)
                hits = slskd_mod.search_responses(session, sid)
                if hits:
                    break
            return hits

        def done(hits: list[slskd_mod.SlskdHit]) -> None:
            self._clear(self._results)
            if not hits:
                empty = Gtk.Label(label="No results yet — try again shortly")
                empty.add_css_class("dim-label")
                self._results.append(empty)
                return
            for hit in hits[:40]:
                row = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
                row.set_margin_top(4)
                row.set_margin_bottom(4)
                t = Gtk.Label(label=hit.label)
                t.add_css_class("heading")
                t.set_xalign(0.0)
                t.set_ellipsize(Pango.EllipsizeMode.END)
                u = Gtk.Label(
                    label=f"{hit.username} · {len(hit.files)} files")
                u.add_css_class("caption")
                u.add_css_class("dim-label")
                u.set_xalign(0.0)
                row.append(t)
                row.append(u)
                self._results.append(row)

        def fail(exc: Exception) -> None:
            self._clear(self._results)
            self._results.append(status_page(
                "network-error-symbolic", "Search failed", str(exc)))

        run_async(work, done, fail, name="riff-slskd-search")
