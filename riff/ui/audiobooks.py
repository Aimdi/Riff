"""Audiobooks — LibriVox discover + Audiobookshelf library (Riff Mobile)."""

from __future__ import annotations

import logging

from gi.repository import Gtk, Pango

from .. import config
from ..core import audiobookshelf as abs_mod
from ..core.librivox import Audiobook, book_detail, browse_books, search_books
from ..core.models import format_duration
from ..util import run_async
from .widgets import CoverArt, scroll_wrap, spinner_page, status_page

log = logging.getLogger("riff.audiobooks")


def _abs_session() -> abs_mod.AbsSession | None:
    host = str(config.settings.get("abs_host", "") or "")
    token = str(config.settings.get("abs_token", "") or "")
    if not host or not token:
        return None
    return abs_mod.AbsSession(
        host=abs_mod.normalize_host(host),
        token=token,
        user_id=str(config.settings.get("abs_user_id", "") or ""),
        username=str(config.settings.get("abs_username", "") or ""),
        library_id=str(config.settings.get("abs_library_id", "") or ""),
    )


class AudiobooksPage(Gtk.Box):
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

        title = Gtk.Label(label="Audiobooks")
        title.add_css_class("title-1")
        title.set_xalign(0.0)
        box.append(title)

        sub = Gtk.Label(
            label="LibriVox free books, plus your Audiobookshelf library "
                  "when connected in Preferences.")
        sub.add_css_class("dim-label")
        sub.set_wrap(True)
        sub.set_xalign(0.0)
        box.append(sub)

        session = _abs_session()
        if session:
            lib_head = Gtk.Label(label="Your library")
            lib_head.add_css_class("title-3")
            lib_head.set_xalign(0.0)
            box.append(lib_head)
            self._abs_host = Gtk.Box(
                orientation=Gtk.Orientation.VERTICAL, spacing=6)
            loading = Gtk.Label(label="Loading library…")
            loading.add_css_class("dim-label")
            self._abs_host.append(loading)
            box.append(self._abs_host)
            self._load_abs_library(session)
        else:
            hint = Gtk.Label(
                label="Connect Audiobookshelf in Preferences "
                      "to stream your own library.")
            hint.add_css_class("dim-label")
            hint.set_wrap(True)
            hint.set_xalign(0.0)
            box.append(hint)

        search_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        entry = Gtk.SearchEntry()
        entry.set_hexpand(True)
        entry.set_placeholder_text("Search LibriVox by title or author…")
        entry.connect("activate", lambda e: self._run_search(e.get_text()))
        search_row.append(entry)
        go = Gtk.Button(label="Search")
        go.add_css_class("suggested-action")
        go.connect("clicked", lambda *_: self._run_search(entry.get_text()))
        search_row.append(go)
        box.append(search_row)

        self._results_host = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL, spacing=8)
        box.append(self._results_host)

        head = Gtk.Label(label="Browse LibriVox")
        head.add_css_class("title-3")
        head.set_xalign(0.0)
        box.append(head)

        self._browse_host = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL, spacing=6)
        loading = Gtk.Label(label="Loading…")
        loading.add_css_class("dim-label")
        self._browse_host.append(loading)
        box.append(self._browse_host)
        self._load_browse()

    def _load_abs_library(self, session: abs_mod.AbsSession) -> None:
        def work():
            lib_id = session.library_id
            if not lib_id:
                libs = abs_mod.fetch_libraries(session)
                preferred = abs_mod.prefer_book_library(libs)
                if preferred:
                    lib_id = preferred.id
                    config.settings.set("abs_library_id", lib_id)
                    session.library_id = lib_id
            return abs_mod.fetch_books(session, lib_id, limit=40)

        def done(books: list[abs_mod.AbsBook]) -> None:
            self._clear(self._abs_host)
            if not books:
                empty = Gtk.Label(label="Library is empty")
                empty.add_css_class("dim-label")
                self._abs_host.append(empty)
                return
            for book in books:
                self._abs_host.append(self._abs_book_row(session, book))

        def fail(exc: Exception) -> None:
            self._clear(self._abs_host)
            self._abs_host.append(status_page(
                "network-error-symbolic", "Couldn't load library", str(exc)))

        run_async(work, done, fail, name="riff-abs-books")

    def _abs_book_row(
        self, session: abs_mod.AbsSession, book: abs_mod.AbsBook,
    ) -> Gtk.Widget:
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        row.set_margin_top(4)
        row.set_margin_bottom(4)
        art = CoverArt(64)
        art.set_url(book.cover_url(session.host, session.token))
        row.append(art)
        text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        text.set_hexpand(True)
        t = Gtk.Label(label=book.title)
        t.add_css_class("heading")
        t.set_xalign(0.0)
        t.set_ellipsize(Pango.EllipsizeMode.END)
        a = Gtk.Label(label=book.author or "Audiobookshelf")
        a.add_css_class("dim-label")
        a.add_css_class("caption")
        a.set_xalign(0.0)
        a.set_ellipsize(Pango.EllipsizeMode.END)
        text.append(t)
        text.append(a)
        row.append(text)
        open_btn = Gtk.Button(label="Open")
        open_btn.add_css_class("suggested-action")
        open_btn.add_css_class("pill")
        open_btn.connect(
            "clicked", lambda *_: self._open_abs_book(session, book.id))
        row.append(open_btn)
        return row

    def _open_abs_book(
        self, session: abs_mod.AbsSession, book_id: str,
    ) -> None:
        self._clear(self._detail)
        self._stack.set_visible_child_name("detail")
        shell = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        shell.set_margin_top(12)
        shell.set_margin_start(16)
        shell.set_margin_end(16)
        shell.set_margin_bottom(100)
        self._detail.append(scroll_wrap(shell))

        back = Gtk.Button(label="← Audiobooks")
        back.add_css_class("flat")
        back.set_halign(Gtk.Align.START)
        back.connect("clicked", lambda *_: self._show_hub())
        shell.append(back)
        host = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        host.append(spinner_page())
        shell.append(host)

        def work():
            return abs_mod.open_book(session, book_id)

        def done(book: abs_mod.AbsBookDetail) -> None:
            self._clear(host)
            tracks = book.to_tracks(session.host, session.token)
            head = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=14)
            art = CoverArt(120)
            art.set_url(
                abs_mod.AbsBook(id=book.id, title=book.title).cover_url(
                    session.host, session.token))
            head.append(art)
            meta = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
            meta.set_valign(Gtk.Align.CENTER)
            title = Gtk.Label(label=book.title)
            title.add_css_class("title-2")
            title.set_xalign(0.0)
            title.set_wrap(True)
            author = Gtk.Label(label=book.author or "Audiobookshelf")
            author.add_css_class("dim-label")
            author.set_xalign(0.0)
            meta.append(title)
            meta.append(author)
            head.append(meta)
            host.append(head)

            if book.description:
                desc = Gtk.Label(label=book.description)
                desc.set_wrap(True)
                desc.set_xalign(0.0)
                desc.add_css_class("dim-label")
                host.append(desc)

            if not tracks:
                host.append(status_page(
                    "emblem-music-symbolic", "No audio tracks",
                    "This item has no playable files."))
                return

            play_all = Gtk.Button(label=f"Play all · {len(tracks)} tracks")
            play_all.add_css_class("suggested-action")
            play_all.add_css_class("pill")
            play_all.set_halign(Gtk.Align.START)
            play_all.connect(
                "clicked",
                lambda *_: self.window.service.play_tracks(
                    tracks, start=0, source="audiobook"))
            host.append(play_all)

            listbox = Gtk.ListBox()
            listbox.set_selection_mode(Gtk.SelectionMode.NONE)
            listbox.add_css_class("riff-discover-list")
            listbox.connect(
                "row-activated",
                lambda _lb, row: self.window.service.play_tracks(
                    tracks, start=getattr(row, "ch_index", 0),
                    source="audiobook"))
            for i, track in enumerate(tracks):
                row = Gtk.ListBoxRow()
                row.ch_index = i
                row.set_activatable(True)
                box = Gtk.Box(
                    orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
                box.set_margin_top(8)
                box.set_margin_bottom(8)
                num = Gtk.Label(label=str(i + 1))
                num.add_css_class("dim-label")
                num.set_width_chars(3)
                box.append(num)
                text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
                text.set_hexpand(True)
                t = Gtk.Label(label=track.title)
                t.set_xalign(0.0)
                t.set_ellipsize(Pango.EllipsizeMode.END)
                t.add_css_class("heading")
                text.append(t)
                box.append(text)
                if track.duration:
                    dur = Gtk.Label(label=format_duration(track.duration))
                    dur.add_css_class("caption")
                    dur.add_css_class("dim-label")
                    box.append(dur)
                row.set_child(box)
                listbox.append(row)
            host.append(listbox)

        def fail(exc: Exception) -> None:
            self._clear(host)
            host.append(status_page(
                "network-error-symbolic", "Couldn't open book", str(exc)))

        run_async(work, done, fail, name="riff-abs-detail")

    def _load_browse(self) -> None:
        def work():
            return browse_books(limit=30)

        def done(books: list[Audiobook]) -> None:
            self._clear(self._browse_host)
            if not books:
                self._browse_host.append(status_page(
                    "network-error-symbolic", "Couldn't load LibriVox",
                    "Check your network and try again."))
                return
            for book in books:
                self._browse_host.append(self._book_row(book))

        def fail(exc: Exception) -> None:
            self._clear(self._browse_host)
            self._browse_host.append(status_page(
                "network-error-symbolic", "Couldn't load LibriVox", str(exc)))

        run_async(work, done, fail, name="riff-lv-browse")

    def _run_search(self, term: str) -> None:
        term = (term or "").strip()
        if not term:
            return
        self._clear(self._results_host)
        self._results_host.append(spinner_page())

        def work():
            return search_books(term)

        def done(books: list[Audiobook]) -> None:
            self._clear(self._results_host)
            if not books:
                empty = Gtk.Label(label="No audiobooks found")
                empty.add_css_class("dim-label")
                self._results_host.append(empty)
                return
            label = Gtk.Label(label=f"Results for “{term}”")
            label.add_css_class("heading")
            label.set_xalign(0.0)
            self._results_host.append(label)
            for book in books:
                self._results_host.append(self._book_row(book))

        def fail(exc: Exception) -> None:
            self._clear(self._results_host)
            self._results_host.append(status_page(
                "network-error-symbolic", "Search failed", str(exc)))

        run_async(work, done, fail, name="riff-lv-search")

    def _book_row(self, book: Audiobook) -> Gtk.Widget:
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        row.set_margin_top(4)
        row.set_margin_bottom(4)
        art = CoverArt(64)
        art.set_url(book.cover)
        row.append(art)
        text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        text.set_hexpand(True)
        t = Gtk.Label(label=book.title)
        t.add_css_class("heading")
        t.set_xalign(0.0)
        t.set_ellipsize(Pango.EllipsizeMode.END)
        a = Gtk.Label(label=book.author or book.language or "LibriVox")
        a.add_css_class("dim-label")
        a.add_css_class("caption")
        a.set_xalign(0.0)
        a.set_ellipsize(Pango.EllipsizeMode.END)
        text.append(t)
        text.append(a)
        row.append(text)
        open_btn = Gtk.Button(label="Open")
        open_btn.add_css_class("suggested-action")
        open_btn.add_css_class("pill")
        open_btn.connect("clicked", lambda *_: self._open_book(book.id))
        row.append(open_btn)
        return row

    def _open_book(self, book_id: str) -> None:
        self._clear(self._detail)
        self._stack.set_visible_child_name("detail")
        shell = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        shell.set_margin_top(12)
        shell.set_margin_start(16)
        shell.set_margin_end(16)
        shell.set_margin_bottom(100)
        self._detail.append(scroll_wrap(shell))

        back = Gtk.Button(label="← Audiobooks")
        back.add_css_class("flat")
        back.set_halign(Gtk.Align.START)
        back.connect("clicked", lambda *_: self._show_hub())
        shell.append(back)
        host = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        host.append(spinner_page())
        shell.append(host)

        def work():
            return book_detail(book_id)

        def done(book: Audiobook) -> None:
            self._clear(host)
            head = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=14)
            art = CoverArt(120)
            art.set_url(book.cover)
            head.append(art)
            meta = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
            meta.set_valign(Gtk.Align.CENTER)
            title = Gtk.Label(label=book.title)
            title.add_css_class("title-2")
            title.set_xalign(0.0)
            title.set_wrap(True)
            author = Gtk.Label(label=book.author or "LibriVox")
            author.add_css_class("dim-label")
            author.set_xalign(0.0)
            meta.append(title)
            meta.append(author)
            if book.totaltimesecs:
                tot = Gtk.Label(label=format_duration(book.totaltimesecs))
                tot.set_xalign(0.0)
                tot.add_css_class("caption")
                tot.add_css_class("dim-label")
                meta.append(tot)
            head.append(meta)
            host.append(head)

            if book.description:
                desc = Gtk.Label(label=book.description)
                desc.set_wrap(True)
                desc.set_xalign(0.0)
                desc.add_css_class("dim-label")
                host.append(desc)

            tracks = book.chapter_tracks()
            if not tracks:
                host.append(status_page(
                    "emblem-music-symbolic", "No chapters",
                    "This book has no listen URLs yet."))
                return

            play_all = Gtk.Button(label=f"Play all · {len(tracks)} chapters")
            play_all.add_css_class("suggested-action")
            play_all.add_css_class("pill")
            play_all.set_halign(Gtk.Align.START)
            play_all.connect(
                "clicked",
                lambda *_: self.window.service.play_tracks(
                    tracks, start=0, source="audiobook"))
            host.append(play_all)

            listbox = Gtk.ListBox()
            listbox.set_selection_mode(Gtk.SelectionMode.NONE)
            listbox.add_css_class("riff-discover-list")
            listbox.connect(
                "row-activated",
                lambda _lb, row: self.window.service.play_tracks(
                    tracks, start=getattr(row, "ch_index", 0),
                    source="audiobook"))
            playable = [c for c in book.chapters if c.stream_url]
            for i, ch in enumerate(playable):
                row = Gtk.ListBoxRow()
                row.ch_index = i
                row.set_activatable(True)
                box = Gtk.Box(
                    orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
                box.set_margin_top(8)
                box.set_margin_bottom(8)
                num = Gtk.Label(label=str(ch.index))
                num.add_css_class("dim-label")
                num.set_width_chars(3)
                box.append(num)
                text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
                text.set_hexpand(True)
                t = Gtk.Label(label=ch.title)
                t.set_xalign(0.0)
                t.set_ellipsize(Pango.EllipsizeMode.END)
                t.add_css_class("heading")
                text.append(t)
                box.append(text)
                if ch.duration:
                    dur = Gtk.Label(label=format_duration(ch.duration))
                    dur.add_css_class("caption")
                    dur.add_css_class("dim-label")
                    box.append(dur)
                row.set_child(box)
                listbox.append(row)
            host.append(listbox)

        def fail(exc: Exception) -> None:
            self._clear(host)
            host.append(status_page(
                "network-error-symbolic", "Couldn't load book", str(exc)))

        run_async(work, done, fail, name="riff-lv-detail")
