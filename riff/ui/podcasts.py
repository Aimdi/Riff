"""Podcasts page — Apple search, subscribe, play episodes (Riff Mobile)."""

from __future__ import annotations

import logging

from gi.repository import Gtk, Pango

from ..core.podcast import (
    PodcastShow,
    ensure_feed_url,
    fetch_episodes,
    search_shows,
    top_shows,
)
from ..util import run_async
from .widgets import CoverArt, scroll_wrap, spinner_page, status_page

log = logging.getLogger("riff.podcasts")


class PodcastsPage(Gtk.Box):
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

        title = Gtk.Label(label="Podcasts")
        title.add_css_class("title-1")
        title.set_xalign(0.0)
        box.append(title)

        sub = Gtk.Label(
            label="Search Apple’s directory, subscribe to RSS feeds, "
                  "play episodes — same idea as Riff Mobile.")
        sub.add_css_class("dim-label")
        sub.set_wrap(True)
        sub.set_xalign(0.0)
        box.append(sub)

        search_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        entry = Gtk.SearchEntry()
        entry.set_hexpand(True)
        entry.set_placeholder_text("Search podcasts…")
        entry.connect("activate", lambda e: self._run_search(e.get_text()))
        search_row.append(entry)
        go = Gtk.Button(label="Search")
        go.add_css_class("suggested-action")
        go.connect("clicked", lambda *_: self._run_search(entry.get_text()))
        search_row.append(go)
        box.append(search_row)

        self._results_host = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        box.append(self._results_host)

        subs = self.window.library.podcast_subscriptions()
        head = Gtk.Label(label="Subscriptions" if subs else "Popular")
        head.add_css_class("title-3")
        head.set_xalign(0.0)
        head.set_margin_top(8)
        box.append(head)

        self._subs_host = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        box.append(self._subs_host)
        if subs:
            for row in subs:
                show = PodcastShow(
                    title=row["title"],
                    author=row.get("author") or "",
                    artwork=row.get("artwork") or "",
                    feed_url=row["feed_url"],
                )
                self._subs_host.append(self._show_row(show, subscribed=True))
        else:
            loading = Gtk.Label(label="Loading popular podcasts…")
            loading.add_css_class("dim-label")
            self._subs_host.append(loading)
            self._load_popular()

    def _load_popular(self) -> None:
        def work():
            shows = top_shows(limit=12)
            # Resolve a handful of feed URLs so Open works immediately.
            resolved = []
            for show in shows[:8]:
                try:
                    resolved.append(ensure_feed_url(show))
                except Exception:  # noqa: BLE001
                    resolved.append(show)
            return resolved

        def done(shows: list[PodcastShow]) -> None:
            self._clear(self._subs_host)
            if not shows:
                self._subs_host.append(status_page(
                    "network-error-symbolic", "Couldn't load charts",
                    "Search above, or check your network."))
                return
            for show in shows:
                if show.feed_url:
                    self._subs_host.append(self._show_row(show))

        run_async(work, done, lambda _e: None, name="riff-pod-top")

    def _run_search(self, term: str) -> None:
        term = (term or "").strip()
        if not term:
            return
        self._clear(self._results_host)
        self._results_host.append(spinner_page())

        def work():
            return search_shows(term)

        def done(shows: list[PodcastShow]) -> None:
            self._clear(self._results_host)
            if not shows:
                empty = Gtk.Label(label="No podcasts found")
                empty.add_css_class("dim-label")
                self._results_host.append(empty)
                return
            label = Gtk.Label(label=f"Results for “{term}”")
            label.add_css_class("heading")
            label.set_xalign(0.0)
            self._results_host.append(label)
            for show in shows:
                self._results_host.append(self._show_row(show))

        def fail(exc: Exception) -> None:
            self._clear(self._results_host)
            self._results_host.append(status_page(
                "network-error-symbolic", "Search failed", str(exc)))

        run_async(work, done, fail, name="riff-pod-search")

    def _show_row(self, show: PodcastShow, *, subscribed: bool | None = None) -> Gtk.Widget:
        if subscribed is None:
            subscribed = self.window.library.is_podcast_subscribed(show.feed_url)
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        row.set_margin_top(4)
        row.set_margin_bottom(4)
        art = CoverArt(56)
        art.set_url(show.artwork)
        row.append(art)
        text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        text.set_hexpand(True)
        t = Gtk.Label(label=show.title or "Podcast")
        t.add_css_class("heading")
        t.set_xalign(0.0)
        t.set_ellipsize(Pango.EllipsizeMode.END)
        a = Gtk.Label(label=show.author or "")
        a.add_css_class("dim-label")
        a.add_css_class("caption")
        a.set_xalign(0.0)
        a.set_ellipsize(Pango.EllipsizeMode.END)
        text.append(t)
        text.append(a)
        row.append(text)

        open_btn = Gtk.Button(label="Open")
        open_btn.add_css_class("flat")
        open_btn.connect("clicked", lambda *_: self._open_show(show))
        row.append(open_btn)

        sub_btn = Gtk.ToggleButton(label="Subscribed" if subscribed else "Subscribe")
        sub_btn.add_css_class("pill")
        sub_btn.set_active(subscribed)
        sub_btn.set_sensitive(bool(show.feed_url))
        sub_btn.connect("toggled", lambda b: self._toggle_sub(show, b))
        row.append(sub_btn)
        return row

    def _toggle_sub(self, show: PodcastShow, btn: Gtk.ToggleButton) -> None:
        if not show.feed_url:
            btn.set_active(False)
            return
        if btn.get_active():
            self.window.library.subscribe_podcast(
                show.feed_url, show.title, show.author, show.artwork)
            btn.set_label("Subscribed")
            self.window.toast(f"Subscribed to {show.title}")
        else:
            self.window.library.unsubscribe_podcast(show.feed_url)
            btn.set_label("Subscribe")
            self.window.toast(f"Unsubscribed from {show.title}")

    def _open_show(self, show: PodcastShow) -> None:
        self._clear(self._detail)
        self._stack.set_visible_child_name("detail")
        shell = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        shell.set_margin_top(12)
        shell.set_margin_start(16)
        shell.set_margin_end(16)
        shell.set_margin_bottom(100)
        self._detail.append(scroll_wrap(shell))

        back = Gtk.Button(label="← Podcasts")
        back.add_css_class("flat")
        back.set_halign(Gtk.Align.START)
        back.connect("clicked", lambda *_: self._show_hub())
        shell.append(back)

        head = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=14)
        art = CoverArt(96)
        art.set_url(show.artwork)
        head.append(art)
        meta = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        meta.set_valign(Gtk.Align.CENTER)
        title = Gtk.Label(label=show.title or "Podcast")
        title.add_css_class("title-2")
        title.set_xalign(0.0)
        title.set_wrap(True)
        author = Gtk.Label(label=show.author or "")
        author.add_css_class("dim-label")
        author.set_xalign(0.0)
        meta.append(title)
        meta.append(author)
        head.append(meta)
        shell.append(head)

        host = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        host.append(spinner_page())
        shell.append(host)

        def work():
            s = ensure_feed_url(show)
            if not s.feed_url:
                raise RuntimeError("No RSS feed URL for this show")
            eps = fetch_episodes(
                s.feed_url, show_title=s.title, artwork=s.artwork, limit=80)
            return s, eps

        def done(result) -> None:
            show2, episodes = result
            self._clear(host)
            if not episodes:
                host.append(status_page(
                    "emblem-music-symbolic", "No episodes",
                    "This feed has no playable enclosures."))
                return
            count = Gtk.Label(label=f"{len(episodes)} episodes")
            count.add_css_class("heading")
            count.set_xalign(0.0)
            host.append(count)
            tracks = [ep.to_track() for ep in episodes]
            listbox = Gtk.ListBox()
            listbox.set_selection_mode(Gtk.SelectionMode.NONE)
            listbox.add_css_class("riff-discover-list")
            listbox.connect(
                "row-activated",
                lambda _lb, row: self.window.service.play_tracks(
                    tracks, start=getattr(row, "ep_index", 0),
                    source="podcast"))
            for i, ep in enumerate(episodes):
                row = Gtk.ListBoxRow()
                row.ep_index = i
                row.set_activatable(True)
                box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
                box.set_margin_top(8)
                box.set_margin_bottom(8)
                ep_art = CoverArt(48)
                ep_art.set_url(ep.artwork or show2.artwork)
                box.append(ep_art)
                text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
                text.set_hexpand(True)
                t = Gtk.Label(label=ep.title)
                t.set_xalign(0.0)
                t.set_ellipsize(Pango.EllipsizeMode.END)
                t.add_css_class("heading")
                meta_l = Gtk.Label(label=ep.pub_date or "")
                meta_l.set_xalign(0.0)
                meta_l.add_css_class("caption")
                meta_l.add_css_class("dim-label")
                text.append(t)
                text.append(meta_l)
                box.append(text)
                if ep.duration_sec:
                    from ..core.models import format_duration
                    dur = Gtk.Label(label=format_duration(ep.duration_sec))
                    dur.add_css_class("caption")
                    dur.add_css_class("dim-label")
                    box.append(dur)
                row.set_child(box)
                listbox.append(row)
            host.append(listbox)

        def fail(exc: Exception) -> None:
            self._clear(host)
            host.append(status_page(
                "network-error-symbolic", "Couldn't load episodes", str(exc)))

        run_async(work, done, fail, name="riff-pod-eps")
