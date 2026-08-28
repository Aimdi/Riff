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


def _size_label(n: int) -> str:
    if n <= 0:
        return ""
    mb = n / (1024 * 1024)
    if mb >= 1024:
        return f"{mb / 1024:.1f} GB"
    return f"{mb:.1f} MB"


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
                self._results.append(self._hit_block(session, hit))

        def fail(exc: Exception) -> None:
            self._clear(self._results)
            self._results.append(status_page(
                "network-error-symbolic", "Search failed", str(exc)))

        run_async(work, done, fail, name="riff-slskd-search")

    def _hit_block(
        self, session: slskd_mod.SlskdSession, hit: slskd_mod.SlskdHit,
    ) -> Gtk.Widget:
        block = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        block.set_margin_top(6)
        block.set_margin_bottom(6)
        head = Gtk.Label(label=f"{hit.username} · {len(hit.files)} files")
        head.add_css_class("heading")
        head.set_xalign(0.0)
        block.append(head)
        for f in hit.files[:12]:
            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            name = f.filename.split("\\")[-1].split("/")[-1] or f.filename
            text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
            text.set_hexpand(True)
            t = Gtk.Label(label=name)
            t.set_xalign(0.0)
            t.set_ellipsize(Pango.EllipsizeMode.END)
            text.append(t)
            meta = _size_label(f.size)
            if meta:
                m = Gtk.Label(label=meta)
                m.add_css_class("caption")
                m.add_css_class("dim-label")
                m.set_xalign(0.0)
                text.append(m)
            row.append(text)
            dl = Gtk.Button(label="Download")
            dl.add_css_class("suggested-action")
            dl.add_css_class("pill")
            dl.connect(
                "clicked",
                lambda _b, u=hit.username, fn=f.filename, sz=f.size: (
                    self._enqueue(session, u, fn, sz)))
            row.append(dl)
            block.append(row)
        return block

    def _enqueue(
        self,
        session: slskd_mod.SlskdSession,
        username: str,
        filename: str,
        size: int,
    ) -> None:
        short = filename.split("\\")[-1].split("/")[-1] or filename
        self.window.toast(f"Queuing “{short}”…")

        def work():
            slskd_mod.enqueue_download(session, username, filename, size)

        def done(_=None) -> None:
            self.window.toast(f"Queued on slskd · {short}")

        def fail(exc: Exception) -> None:
            self.window.toast(f"Download failed: {exc}")

        run_async(work, done, fail, name="riff-slskd-dl")
