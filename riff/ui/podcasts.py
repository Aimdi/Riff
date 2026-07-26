"""Podcasts page — Apple search, subscribe, play episodes (Riff Mobile)."""

from __future__ import annotations

import logging

from gi.repository import Gtk, Pango

from ..core import podcast_progress as pp
from ..core.models import format_duration
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

        continuing = self.window.library.in_progress_podcasts()
        if continuing:
            cont_head = Gtk.Label(label="Continue")
            cont_head.add_css_class("title-3")
            cont_head.set_xalign(0.0)
            cont_head.set_margin_top(4)
            box.append(cont_head)
            for row in continuing[:12]:
                box.append(self._continue_row(row))

        queued = self.window.library.podcast_queue_tracks()
        q_head_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        q_head = Gtk.Label(label="Queue")
        q_head.add_css_class("title-3")
        q_head.set_xalign(0.0)
        q_head.set_hexpand(True)
        q_head_row.append(q_head)
        if queued:
            play_q = Gtk.Button(label="Play queue")
            play_q.add_css_class("suggested-action")
            play_q.add_css_class("pill")
            play_q.connect(
                "clicked",
                lambda *_: self.window.service.play_tracks(
                    list(queued), start=0, source="podcast_queue"))
            q_head_row.append(play_q)
            clear_q = Gtk.Button(label="Clear")
            clear_q.add_css_class("flat")
            clear_q.connect("clicked", self._clear_podcast_queue)
            q_head_row.append(clear_q)
        box.append(q_head_row)
        if queued:
            for track in queued[:20]:
                box.append(self._queue_track_row(track))
        else:
            empty_q = Gtk.Label(
                label="Add episodes with Queue on a show page")
            empty_q.add_css_class("dim-label")
            empty_q.set_xalign(0.0)
            box.append(empty_q)

        inbox_head = Gtk.Label(label="Inbox")
        inbox_head.add_css_class("title-3")
        inbox_head.set_xalign(0.0)
        inbox_head.set_margin_top(8)
        box.append(inbox_head)
        self._inbox_host = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL, spacing=4)
        loading_inbox = Gtk.Label(label="Loading inbox…")
        loading_inbox.add_css_class("dim-label")
        self._inbox_host.append(loading_inbox)
        box.append(self._inbox_host)
        self._load_inbox()

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

    def _clear_podcast_queue(self, *_a) -> None:
        self.window.library.podcast_queue_clear()
        self.window.toast("Podcast queue cleared")
        self._show_hub()

    def _queue_track_row(self, track) -> Gtk.Widget:
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        row.set_margin_top(3)
        row.set_margin_bottom(3)
        art = CoverArt(40)
        art.set_url(track.thumbnail)
        row.append(art)
        text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        text.set_hexpand(True)
        t = Gtk.Label(label=track.title)
        t.add_css_class("heading")
        t.set_xalign(0.0)
        t.set_ellipsize(Pango.EllipsizeMode.END)
        a = Gtk.Label(label=track.artist or "")
        a.add_css_class("dim-label")
        a.add_css_class("caption")
        a.set_xalign(0.0)
        text.append(t)
        text.append(a)
        row.append(text)
        rm = Gtk.Button(label="Remove")
        rm.add_css_class("flat")
        rm.connect(
            "clicked",
            lambda *_: (
                self.window.library.podcast_queue_remove(track.video_id),
                self._show_hub()))
        row.append(rm)
        return row

    def _load_inbox(self) -> None:
        """Round-robin latest episodes from each subscription (mobile Inbox)."""
        subs = self.window.library.podcast_subscriptions()
        if not subs:
            self._clear(self._inbox_host)
            empty = Gtk.Label(label="Subscribe to shows to fill your inbox")
            empty.add_css_class("dim-label")
            self._inbox_host.append(empty)
            return

        def work():
            from ..core.podcast import fetch_episodes
            buckets: list[list] = []
            for row in subs[:12]:
                try:
                    eps = fetch_episodes(
                        row["feed_url"],
                        show_title=row.get("title") or "",
                        artwork=row.get("artwork") or "",
                        limit=3)
                    buckets.append(eps)
                except Exception:  # noqa: BLE001
                    continue
            # Round-robin newest-first per show.
            merged = []
            i = 0
            while len(merged) < 30:
                added = False
                for bucket in buckets:
                    if i < len(bucket):
                        merged.append(bucket[i])
                        added = True
                if not added:
                    break
                i += 1
            return merged

        def done(episodes) -> None:
            self._clear(self._inbox_host)
            if not episodes:
                empty = Gtk.Label(label="Inbox is empty")
                empty.add_css_class("dim-label")
                self._inbox_host.append(empty)
                return
            tracks = [ep.to_track() for ep in episodes]
            for i, ep in enumerate(episodes):
                row = Gtk.Box(
                    orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
                row.set_margin_top(3)
                row.set_margin_bottom(3)
                art = CoverArt(48)
                art.set_url(ep.artwork)
                row.append(art)
                text = Gtk.Box(
                    orientation=Gtk.Orientation.VERTICAL, spacing=2)
                text.set_hexpand(True)
                t = Gtk.Label(label=ep.title)
                t.add_css_class("heading")
                t.set_xalign(0.0)
                t.set_ellipsize(Pango.EllipsizeMode.END)
                a = Gtk.Label(label=ep.show_title or ep.pub_date or "")
                a.add_css_class("dim-label")
                a.add_css_class("caption")
                a.set_xalign(0.0)
                text.append(t)
                text.append(a)
                row.append(text)
                play = Gtk.Button(label="Play")
                play.add_css_class("flat")
                play.connect(
                    "clicked",
                    lambda _b, idx=i: self.window.service.play_tracks(
                        tracks, start=idx, source="podcast_inbox"))
                row.append(play)
                q = Gtk.Button(label="Queue")
                q.add_css_class("flat")
                q.connect(
                    "clicked",
                    lambda _b, tr=tracks[i]: (
                        self.window.library.podcast_queue_add(tr),
                        self.window.toast("Added to podcast queue")))
                row.append(q)
                self._inbox_host.append(row)

        run_async(work, done, lambda _e: None, name="riff-pod-inbox")

    def _continue_row(self, row: dict) -> Gtk.Widget:
        track = pp.track_from_progress(row)
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        box.set_margin_top(4)
        box.set_margin_bottom(4)
        art = CoverArt(56)
        art.set_url(str(row.get("artwork") or ""))
        box.append(art)
        text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        text.set_hexpand(True)
        t = Gtk.Label(label=str(row.get("title") or "Episode"))
        t.add_css_class("heading")
        t.set_xalign(0.0)
        t.set_ellipsize(Pango.EllipsizeMode.END)
        artist = str(row.get("artist") or "")
        a = Gtk.Label(label=artist)
        a.add_css_class("dim-label")
        a.add_css_class("caption")
        a.set_xalign(0.0)
        a.set_ellipsize(Pango.EllipsizeMode.END)
        text.append(t)
        text.append(a)
        frac = pp.progress_fraction(
            int(row.get("position_ms") or 0),
            int(row.get("duration_ms") or 0),
        )
        if frac is not None:
            bar = Gtk.ProgressBar()
            bar.set_fraction(frac)
            bar.set_hexpand(True)
            text.append(bar)
        box.append(text)
        play = Gtk.Button(label="Resume")
        play.add_css_class("suggested-action")
        play.add_css_class("pill")
        play.set_sensitive(track is not None)

        def _resume(*_a):
            if track is None:
                return
            self.window.service.play_tracks([track], start=0, source="podcast")

        play.connect("clicked", _resume)
        box.append(play)
        return box

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
                meta_bits = [ep.pub_date] if ep.pub_date else []
                prog = self.window.library.podcast_progress(ep.episode_id)
                if prog:
                    frac = pp.progress_fraction(
                        int(prog.get("position_ms") or 0),
                        int(prog.get("duration_ms") or 0),
                    )
                    if frac is not None:
                        meta_bits.append(f"{int(frac * 100)}% played")
                meta_l = Gtk.Label(label=" · ".join(meta_bits))
                meta_l.set_xalign(0.0)
                meta_l.add_css_class("caption")
                meta_l.add_css_class("dim-label")
                text.append(t)
                text.append(meta_l)
                if prog:
                    bar = Gtk.ProgressBar()
                    bar.set_fraction(pp.progress_fraction(
                        int(prog.get("position_ms") or 0),
                        int(prog.get("duration_ms") or 0),
                    ) or 0.0)
                    bar.set_hexpand(True)
                    text.append(bar)
                box.append(text)
                if ep.duration_sec:
                    dur = Gtk.Label(label=format_duration(ep.duration_sec))
                    dur.add_css_class("caption")
                    dur.add_css_class("dim-label")
                    box.append(dur)
                q = Gtk.Button(label="Queue")
                q.add_css_class("flat")
                q.connect(
                    "clicked",
                    lambda _b, tr=tracks[i]: (
                        self.window.library.podcast_queue_add(tr),
                        self.window.toast("Added to podcast queue")))
                box.append(q)
                if ep.transcript_url:
                    tr = Gtk.Button(label="Transcript")
                    tr.add_css_class("flat")
                    tr.connect(
                        "clicked",
                        lambda _b, e=ep: self._open_transcript(e))
                    box.append(tr)
                row.set_child(box)
                listbox.append(row)
            host.append(listbox)

        def fail(exc: Exception) -> None:
            self._clear(host)
            host.append(status_page(
                "network-error-symbolic", "Couldn't load episodes", str(exc)))

        run_async(work, done, fail, name="riff-pod-eps")

    def _open_transcript(self, ep) -> None:
        from .transcript import open_transcript
        open_transcript(
            self.window,
            url=ep.transcript_url,
            type_=ep.transcript_type or "",
            title=ep.title or "",
        )
