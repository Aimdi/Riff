"""All content pages of the app."""

from __future__ import annotations

import logging
import random

from gi.repository import Adw, Gtk, Pango

log = logging.getLogger("riff.pages")

from .. import config
from ..core.models import Album, Artist, Playlist, Track
from ..util import run_async
from . import iconutil
from .widgets import (
    CardGrid,
    Carousel,
    CoverArt,
    DiscoverTrackStrip,
    ForYouStrip,
    TrackList,
    scroll_wrap,
    spinner_page,
    status_page,
)


class ContentPage(Gtk.Box):
    """Base: swaps between spinner / error / loaded content."""

    def __init__(self, window):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.window = window
        self._current: Gtk.Widget | None = None

    def show_widget(self, widget: Gtk.Widget) -> None:
        if self._current is not None:
            self.remove(self._current)
        self._current = widget
        self.append(widget)

    def show_loading(self) -> None:
        self.show_widget(spinner_page())

    def show_error(self, message: str, retry=None) -> None:
        page = status_page(
            "network-error-symbolic", "Couldn't load content", str(message)
        )
        if retry is not None:
            btn = Gtk.Button(label="Try Again")
            btn.add_css_class("pill")
            btn.add_css_class("suggested-action")
            btn.set_halign(Gtk.Align.CENTER)
            btn.connect("clicked", lambda *_: retry())
            page.set_child(btn)
        self.show_widget(page)

    def load_async(self, work, present) -> None:
        """Run `work()` in a thread, then `present(result)`; handles errors."""
        self.show_loading()

        def on_error(exc: Exception) -> None:
            self.show_error(exc, retry=lambda: self.load_async(work, present))

        run_async(work, present, on_error)


class HomePage(ContentPage):
    """Home feed: seamless “For you” picks on top, then YT Music sections."""

    def __init__(self, window):
        super().__init__(window)
        self._loaded = False
        self._box: Gtk.Box | None = None
        self._top: Gtk.Box | None = None
        self._for_you_host: Gtk.Box | None = None
        self._mix_host: Gtk.Box | None = None
        self._for_you_busy = False

    def refresh(self, force: bool = False) -> None:
        if self._loaded and not force:
            return
        self.load_async(lambda: self.window.api.home(limit=8), self._present)

    def _present(self, sections) -> None:
        self._loaded = True
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=20)
        box.set_margin_top(14)
        box.set_margin_bottom(120)
        box.set_margin_start(18)
        box.set_margin_end(18)

        mobile = str(config.settings.get("shell_layout", "mobile")) == "mobile"
        top = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18)
        box.append(top)
        self._top = top
        self._box = box

        # First viewport (mobile): brand → Wave → shortcuts. Everything else
        # sits below the fold so Home reads as one composition, not a dashboard.
        try:
            top.append(self._greeting_header())
            if mobile:
                top.append(self._riff_wave_hero())
            shortcuts = self._shortcut_grid()
            if shortcuts is not None:
                top.append(shortcuts)
        except Exception:  # noqa: BLE001 — Home must render regardless
            log.exception("home hero failed")

        if mobile:
            top.append(self._zone_label("FOR YOU"))
        else:
            top.append(self._ai_mix_hero())

        self._for_you_host = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        top.append(self._for_you_host)

        # Instant paint from cache, then refresh in the background.
        cached = self._cached_for_you()
        if cached:
            self.show_for_you(cached, source="ai")
        else:
            self._show_for_you_loading()
        self._ensure_for_you()

        # Highest-value local row: recently played songs (no API needed).
        recent = self.window.library.recent(16)
        if recent:
            top.append(ForYouStrip("Jump back in", recent, self.window))

        # Zone-B mixes (Rediscover / Fresh Finds / daily…).
        self._mix_host = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18)
        top.append(self._mix_host)
        self._paint_cached_mixes()
        self._ensure_home_mixes()

        explore_sections = list(sections or [])
        if mobile and explore_sections:
            top.append(self._zone_label("EXPLORE"))
            # One composition below the fold — don't dump the whole YT home.
            explore_sections = explore_sections[:3]

        for section in explore_sections:
            tracks = [i for i in section.items if isinstance(i, Track)]
            others = [i for i in section.items if not isinstance(i, Track)]
            if others:
                box.append(Carousel(section.title, others, self.window))
            elif tracks:
                if mobile:
                    box.append(DiscoverTrackStrip(
                        section.title, tracks[:10], self.window))
                else:
                    title = Gtk.Label(label=section.title)
                    title.add_css_class("title-3")
                    title.set_xalign(0.0)
                    box.append(title)
                    tl = TrackList(self.window, radio_on_single=True)
                    tl.set_tracks(tracks[:10])
                    box.append(tl)

        if not sections and not cached:
            empty = status_page(
                "emblem-music-symbolic", "Loading your feed…",
                "Personal picks appear above as soon as they're ready.")
            box.append(empty)

        self.show_widget(scroll_wrap(box))
        self._load_followed_releases(top)

    def _zone_label(self, text: str) -> Gtk.Widget:
        label = Gtk.Label(label=text)
        label.add_css_class("riff-zone-label")
        label.set_xalign(0.0)
        return label

    def _greeting_header(self) -> Gtk.Widget:
        import datetime

        hour = datetime.datetime.now().hour
        if hour < 6:
            text = "Good night"
        elif hour < 12:
            text = "Good morning"
        elif hour < 18:
            text = "Good afternoon"
        else:
            text = "Good evening"
        name = str(config.settings.get("profile_name", "") or "").strip()
        if name:
            text = f"{text}, {name.split()[0]}"
        # Mobile: brand is the hero signal; greeting is a quiet caption.
        if str(config.settings.get("shell_layout", "mobile")) == "mobile":
            wrap = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
            wrap.set_margin_bottom(2)
            brand = Gtk.Label(label="Riff")
            brand.add_css_class("riff-brand-hero")
            brand.set_xalign(0.0)
            wrap.append(brand)
            greet = Gtk.Label(label=text)
            greet.add_css_class("riff-greeting")
            greet.set_xalign(0.0)
            wrap.append(greet)
            return wrap
        label = Gtk.Label(label=text)
        label.set_xalign(0.0)
        label.add_css_class("title-1")
        return label

    def _shortcut_grid(self) -> Gtk.Widget | None:
        """Greeting grid — mobile uses the fixed Riff Mobile 6-tile set."""
        from .window import AI_MIX_PLAYLIST

        window = self.window
        tiles: list[tuple] = []  # (title, cover, glyph, callback)
        mobile = str(config.settings.get("shell_layout", "mobile")) == "mobile"

        if mobile:
            from ..core.mixes import load_cached_home_mixes, load_cached_radar

            mix_map = {
                sid: tracks
                for sid, _title, tracks in load_cached_home_mixes(window.library)
            }
            radar = load_cached_radar(window.library)

            def _play_or_goto(tracks, fallback_page, source):
                if tracks:
                    window.service.play_tracks(
                        list(tracks), start=0, source=source)
                else:
                    window.goto(fallback_page)

            recent_thumbs = [
                t.thumbnail for t in window.library.recent(8) if t.thumbnail]
            fresh_thumbs = [
                t.thumbnail for t in (mix_map.get("fresh_finds") or [])[:8]
                if t.thumbnail]
            redis_thumbs = [
                t.thumbnail for t in (mix_map.get("rediscover") or [])[:8]
                if t.thumbnail]
            radar_thumbs = [t.thumbnail for t in (radar or [])[:8] if t.thumbnail]
            # Glyph fallbacks when caches are empty — live testing showed
            # identical list placeholders making the Discover grid unreadable.
            tiles = [
                ("Favorites", None, "♥", "riff-liked-tile",
                 lambda: window.goto("favorites")),
                ("Recently played", recent_thumbs or None,
                 "◷" if not recent_thumbs else None, "riff-tile-recent",
                 lambda: window.goto("history")),
                ("Fresh Finds", fresh_thumbs or None,
                 "✦" if not fresh_thumbs else None, "riff-tile-fresh",
                 lambda: _play_or_goto(
                     mix_map.get("fresh_finds"), "explore", "fresh_finds")),
                ("Rediscover", redis_thumbs or None,
                 "↺" if not redis_thumbs else None, "riff-tile-rediscover",
                 lambda: _play_or_goto(
                     mix_map.get("rediscover"), "favorites", "rediscover")),
                ("Release Radar", radar_thumbs or None,
                 "◎" if not radar_thumbs else None, "riff-tile-radar",
                 lambda: _play_or_goto(radar, "artists", "release_radar")),
                ("Downloads", None, "↓", "riff-tile-downloads",
                 lambda: window.goto("downloads")),
            ]
        else:
            n_favs = len(window.library.favorites())
            if n_favs:
                tiles.append(("Liked Songs", None, "♥", "riff-liked-tile",
                              lambda: window.goto("favorites")))
            seen_names = set()
            ai_pid = window.library.find_playlist(AI_MIX_PLAYLIST)
            if ai_pid is not None:
                thumbs = window.library.playlist_thumbnails(ai_pid, 8)
                if thumbs:
                    seen_names.add(AI_MIX_PLAYLIST)
                    tiles.append((
                        AI_MIX_PLAYLIST, thumbs, None, "",
                        lambda p=ai_pid: window.open_local_playlist(
                            p, AI_MIX_PLAYLIST)))
            for item in window.library.playlist_tree():
                entries = ([(item["id"], item["name"])]
                           if item["kind"] == "playlist"
                           else [(pid, name)
                                 for pid, name, _c in item["playlists"]])
                for pid, name in entries:
                    if len(tiles) >= 8:
                        break
                    if name in seen_names:
                        continue
                    seen_names.add(name)
                    thumbs = window.library.playlist_thumbnails(pid, 8)
                    if not thumbs:
                        continue
                    tiles.append((
                        name, thumbs, None, "",
                        lambda p=pid, n=name: window.open_local_playlist(p, n)))
            if len(tiles) < 8:
                recent = window.library.recent(1)
                if recent:
                    thumbs = [
                        t.thumbnail for t in window.library.recent(8)
                        if t.thumbnail]
                    tiles.append((
                        "Recently played", thumbs or None,
                        "◷" if not thumbs else None, "riff-tile-recent",
                        lambda: window.goto("history")))

        if not tiles:
            return None

        grid = Gtk.FlowBox()
        grid.set_selection_mode(Gtk.SelectionMode.NONE)
        grid.set_homogeneous(True)
        grid.set_min_children_per_line(2)
        grid.set_max_children_per_line(3 if mobile else 4)
        grid.set_column_spacing(10)
        grid.set_row_spacing(10)
        for title, cover, glyph, style, cb in tiles[:8]:
            grid.append(self._shortcut_tile(
                title, cover, glyph, cb, tile_style=style))
        return grid

    def _riff_wave_hero(self) -> Gtk.Widget:
        """Riff Wave — mobile-style product hero (art + play + moods)."""
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        card.add_css_class("riff-wave-card")
        card.set_margin_top(2)
        card.set_margin_bottom(2)

        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=14)
        art = CoverArt(72)
        thumbs = [
            t.thumbnail for t in self.window.library.recent(6) if t.thumbnail]
        if not thumbs:
            thumbs = [
                t.thumbnail for t in self.window.library.favorites()[:6]
                if t.thumbnail]
        if thumbs:
            art.set_urls(thumbs[:4])
        row.append(art)

        meta = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        meta.set_hexpand(True)
        meta.set_valign(Gtk.Align.CENTER)
        title = Gtk.Label(label="Riff Wave")
        title.add_css_class("title-3")
        title.set_xalign(0.0)
        meta.append(title)
        sub = Gtk.Label(label="Personal radio from your taste")
        sub.add_css_class("dim-label")
        sub.add_css_class("caption")
        sub.set_xalign(0.0)
        sub.set_wrap(True)
        meta.append(sub)
        row.append(meta)

        play = Gtk.Button()
        iconutil.set_button(play, "media-playback-start-symbolic")
        play.add_css_class("suggested-action")
        play.add_css_class("riff-wave-play")
        play.set_tooltip_text("Start Wave")
        play.set_valign(Gtk.Align.CENTER)
        play.connect("clicked", self._on_start_wave)
        row.append(play)
        card.append(row)

        moods = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        try:
            current = float(config.settings.get("exploration", 0.3) or 0.3)
        except (TypeError, ValueError):
            current = 0.3
        options = (("Familiar", 0.15), ("Balanced", 0.5), ("Adventurous", 0.85))
        nearest = min(options, key=lambda ov: abs(ov[1] - current))[0]
        group: Gtk.ToggleButton | None = None
        for label, value in options:
            btn = Gtk.ToggleButton(label=label)
            btn.add_css_class("pill")
            btn.add_css_class("riff-wave-mood")
            if group is None:
                group = btn
            else:
                btn.set_group(group)
            btn.set_active(label == nearest)

            def _pick(_b, v=value) -> None:
                if _b.get_active():
                    config.settings.set("exploration", v)

            btn.connect("toggled", _pick)
            moods.append(btn)
        card.append(moods)
        return card

    def _on_start_wave(self, *_a) -> None:
        from ..core import wave as wave_mod

        win = self.window
        play_btn = None

        def work():
            return wave_mod.build_wave(
                win.api, win.library, win.service.discovery,
                current=win.service.current_track, limit=25)

        def done(tracks: list[Track]) -> None:
            if not tracks:
                win.toast("Wave needs a little listening history first")
                return
            win.service.play_tracks(tracks, start=0, source="riff_wave")
            win.toast(f"Wave · {len(tracks)} songs")

        def fail(exc: Exception) -> None:
            win.toast(f"Wave unavailable: {exc}")

        run_async(work, done, fail, name="riff-wave")
        _ = play_btn

    def _shortcut_tile(
        self, title: str, cover, glyph, callback, *, tile_style: str = "",
    ):
        btn = Gtk.Button()
        btn.add_css_class("riff-shortcut")
        btn.connect("clicked", lambda *_: callback())
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        urls = [u for u in (cover or []) if u]
        if glyph or not urls:
            tile = Gtk.Label(label=glyph or "♪")
            tile.add_css_class("riff-liked-tile")
            if tile_style:
                tile.add_css_class(tile_style)
            tile.set_size_request(56, 56)
        else:
            tile = CoverArt(56, icon="view-list-symbolic")
            tile.set_urls(urls)
        row.append(tile)
        label = Gtk.Label(label=title)
        label.add_css_class("heading")
        label.set_xalign(0.0)
        label.set_hexpand(True)
        label.set_ellipsize(Pango.EllipsizeMode.END)
        row.append(label)
        btn.set_child(row)
        child = Gtk.FlowBoxChild()
        child.set_child(btn)
        return child

    def _ai_mix_hero(self) -> Gtk.Widget:
        """Hero card: current AI Mix cover + Play + Refresh."""
        from .window import AI_MIX_PLAYLIST

        card = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=16)
        card.add_css_class("card")
        card.set_margin_top(2)
        card.set_margin_bottom(2)

        left = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=14)
        left.set_margin_top(14)
        left.set_margin_bottom(14)
        left.set_margin_start(14)
        left.set_margin_end(14)
        left.set_hexpand(True)

        tracks = self._cached_for_you()
        art = CoverArt(96)
        if tracks:
            art.set_url(tracks[0].thumbnail)
        left.append(art)

        meta = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        meta.set_valign(Gtk.Align.CENTER)
        meta.set_hexpand(True)
        kicker = Gtk.Label(label="Made for you")
        kicker.add_css_class("dim-label")
        kicker.add_css_class("caption")
        kicker.set_xalign(0.0)
        meta.append(kicker)
        title = Gtk.Label(label=AI_MIX_PLAYLIST)
        title.add_css_class("title-2")
        title.set_xalign(0.0)
        meta.append(title)
        if tracks:
            sub = Gtk.Label(label=f"{len(tracks)} songs · curated for your taste")
        else:
            sub = Gtk.Label(
                label="Generate a personal mix from your listening history")
        sub.add_css_class("dim-label")
        sub.set_xalign(0.0)
        sub.set_wrap(True)
        meta.append(sub)

        actions = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        actions.set_margin_top(4)
        play = Gtk.Button(label="Play")
        play.add_css_class("pill")
        play.add_css_class("suggested-action")
        play.set_sensitive(bool(tracks))

        def play_mix(_b=None) -> None:
            from .window import AI_MIX_PLAYLIST as name
            pid = self.window.library.find_playlist(name)
            full = (self.window.library.playlist_tracks(pid)
                    if pid is not None else [])
            if full:
                self.window.service.play_tracks(full, start=0)
            else:
                self.window.toast("Generate an AI Mix first")

        play.connect("clicked", play_mix)
        actions.append(play)

        refresh = Gtk.Button(label="Refresh")
        refresh.add_css_class("pill")
        refresh.set_tooltip_text("Generate a fresh AI Mix")
        refresh.connect(
            "clicked", lambda *_: self.window.refresh_ai_mix(interactive=True))
        actions.append(refresh)

        if tracks:
            open_pl = Gtk.Button(label="Open")
            open_pl.add_css_class("flat")

            def open_mix(_b=None) -> None:
                from .window import AI_MIX_PLAYLIST as name
                pid = self.window.library.find_playlist(name)
                if pid is not None:
                    self.window.open_local_playlist(pid, name)

            open_pl.connect("clicked", open_mix)
            actions.append(open_pl)

        meta.append(actions)
        left.append(meta)
        card.append(left)
        return card

    def _cached_for_you(self) -> list[Track]:
        from .window import AI_MIX_PLAYLIST

        pid = self.window.library.find_playlist(AI_MIX_PLAYLIST)
        if pid is None:
            return []
        return self.window.library.playlist_tracks(pid)[:12]

    def _show_for_you_loading(self) -> None:
        host = self._for_you_host
        if host is None:
            return
        while child := host.get_first_child():
            host.remove(child)
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        row.set_margin_top(2)
        row.set_margin_bottom(2)
        title = Gtk.Label(label="For you")
        title.add_css_class("heading")
        row.append(title)
        spin = Gtk.Spinner()
        spin.set_size_request(16, 16)
        spin.start()
        row.append(spin)
        hint = Gtk.Label(label="Picking songs…")
        hint.add_css_class("dim-label")
        hint.add_css_class("caption")
        row.append(hint)
        host.append(row)

    def show_for_you(self, tracks: list[Track], *, source: str = "ai") -> None:
        """Paint For you — Discover list on mobile shell, chips on desktop."""
        host = self._for_you_host
        if host is None or not tracks:
            return
        while child := host.get_first_child():
            host.remove(child)

        subtitle = {
            "ai": "AI",
            "radio": "From your taste",
            "cache": "AI",
        }.get(source, "")
        mobile = str(config.settings.get("shell_layout", "mobile")) == "mobile"
        if mobile:
            host.append(DiscoverTrackStrip(
                "Discover", tracks[:12], self.window, subtitle=subtitle))
        else:
            host.append(ForYouStrip(
                "For you", tracks[:10], self.window, subtitle=subtitle))

    def _paint_cached_mixes(self) -> None:
        from ..core.mixes import load_cached_home_mixes

        host = getattr(self, "_mix_host", None)
        if host is None:
            return
        rows = load_cached_home_mixes(self.window.library)
        if rows:
            self._paint_mix_rows(rows)

    def _paint_mix_rows(self, rows: list) -> None:
        host = getattr(self, "_mix_host", None)
        if host is None:
            return
        while child := host.get_first_child():
            host.remove(child)
        mobile = str(config.settings.get("shell_layout", "mobile")) == "mobile"
        for _sid, title, tracks in rows:
            if mobile:
                host.append(DiscoverTrackStrip(title, tracks, self.window))
            else:
                host.append(ForYouStrip(title, tracks, self.window))

    def _ensure_home_mixes(self) -> None:
        """Background rebuild of Zone-B mixes + Release Radar (Riff Mobile)."""
        from ..core import mixes as mixes_mod

        win = self.window
        mixes_need = mixes_mod.home_mixes_stale(win.library)
        radar_need = mixes_mod.release_radar_stale(win.library)
        if not mixes_need and not radar_need:
            return

        def work():
            rows = mixes_mod.load_cached_home_mixes(win.library)
            if mixes_need:
                red = mixes_mod.rediscover_tracks(win.library)
                fresh: list[Track] = []
                daily: list = []
                quick: list[Track] = []
                because: list[Track] = []
                try:
                    fresh = mixes_mod.fresh_finds(
                        win.service.discovery, limit=24)
                except Exception:  # noqa: BLE001
                    log.exception("fresh finds failed")
                try:
                    daily = mixes_mod.daily_mixes(
                        win.service.discovery, mix_count=3)
                except Exception:  # noqa: BLE001
                    log.exception("daily mixes failed")
                try:
                    quick = mixes_mod.quick_picks(
                        win.service.discovery, limit=20)
                except Exception:  # noqa: BLE001
                    log.exception("quick picks failed")
                try:
                    seeds = win.library.favorites()[:1] or win.library.recent(1)
                    if seeds:
                        because = win.service.discovery.similar_songs(
                            seeds[0], limit=12)
                except Exception:  # noqa: BLE001
                    log.exception("because-you-liked failed")
                rows = mixes_mod.assemble_home_mix_rows(
                    rediscover=red, fresh=fresh, daily=daily,
                    quick=quick, because=because,
                    max_rows=3, min_count=4)
                if rows:
                    mixes_mod.store_home_mixes(win.library, rows)
            if radar_need:
                try:
                    radar = mixes_mod.release_radar(
                        win.api, win.library, limit=30)
                    if radar:
                        mixes_mod.store_release_radar(win.library, radar)
                except Exception:  # noqa: BLE001
                    log.exception("release radar failed")
            return rows

        def done(rows) -> None:
            if rows:
                self._paint_mix_rows(rows)

        run_async(work, done, lambda _e: None, name="riff-home-mixes")

    def _ensure_for_you(self) -> None:
        """Background: AI Mix if possible, else radio-based picks."""
        if self._for_you_busy:
            return
        self._for_you_busy = True

        # Prefer silent AI refresh when a provider is ready and mix is stale.
        if self.window.try_auto_for_you():
            # AI path will call on_for_you_ready when done.
            return

        self._load_radio_for_you(replace_cache=False)

    def _load_radio_for_you(self, *, replace_cache: bool) -> None:
        """Smart non-AI picks from YT radio around your taste."""
        win = self.window
        has_cache = bool(self._cached_for_you())
        self._for_you_busy = True

        def work():
            from ..core.suggestions import radio_for_you
            return radio_for_you(win.api, win.library, limit=12)

        def done(tracks: list[Track]) -> None:
            self._for_you_busy = False
            if not tracks or self._for_you_host is None:
                if not has_cache and self._for_you_host is not None:
                    while child := self._for_you_host.get_first_child():
                        self._for_you_host.remove(child)
                return
            if has_cache and not replace_cache and self._cached_for_you():
                return
            self.show_for_you(tracks, source="radio")

        def fail(_exc: Exception) -> None:
            self._for_you_busy = False
            if not has_cache and self._for_you_host is not None:
                while child := self._for_you_host.get_first_child():
                    self._for_you_host.remove(child)

        run_async(work, done, fail, name="riff-for-you")

    def on_for_you_ready(self, tracks: list[Track], *, source: str = "ai") -> None:
        """Called by the window after a background AI Mix finishes."""
        self._for_you_busy = False
        if tracks:
            self.show_for_you(tracks, source=source)
        elif not self._cached_for_you():
            # AI failed with nothing saved — fall back without re-entering AI.
            self._load_radio_for_you(replace_cache=True)

    def _load_followed_releases(self, top: Gtk.Box) -> None:
        """Append a 'new from your artists' carousel under For you."""
        follows = self.window.library.followed_artists()[:6]
        if not follows:
            return

        def work():
            items, seen = [], set()
            for browse_id, _name, _thumb in follows:
                try:
                    artist = self.window.api.artist(browse_id)
                except Exception:  # noqa: BLE001 — one artist must not kill all
                    continue
                for album in (artist.albums + artist.singles)[:2]:
                    if album.browse_id not in seen:
                        seen.add(album.browse_id)
                        items.append(album)
            return items

        def done(items) -> None:
            if items and top is self._top:
                title = (
                    "Release Radar" if str(config.settings.get(
                        "shell_layout", "mobile")) == "mobile"
                    else "New from artists you follow")
                top.append(Carousel(title, items, self.window))

        run_async(work, done, lambda _e: None, name="riff-follows")


class DiscoverPage(ContentPage):
    """Privacy-preserving discovery: sections seeded from the local
    library, filled by anonymous per-song lookups."""

    def __init__(self, window):
        super().__init__(window)
        self._loaded = False

    def refresh(self, force: bool = False) -> None:
        if self._loaded and not force:
            return
        from ..core import discover

        self.load_async(
            lambda: discover.build_sections(
                self.window.library, self.window.api),
            self._present)

    def _present(self, sections) -> None:
        self._loaded = True
        if not sections:
            self.show_widget(status_page(
                "emblem-favorite-symbolic", "Nothing to discover from yet",
                "Play and ♥ a few songs first — Discover is built from "
                "your local favorites and history. Nothing about your "
                "taste ever leaves this device."))
            return

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        box.set_margin_top(18)
        box.set_margin_bottom(120)
        box.set_margin_start(18)
        box.set_margin_end(18)

        head = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        title = Gtk.Label(label="Discover")
        title.add_css_class("title-1")
        title.set_xalign(0.0)
        title.set_hexpand(True)
        head.append(title)
        again = Gtk.Button.new_with_label("Surprise me again")
        again.add_css_class("pill")
        again.set_valign(Gtk.Align.CENTER)
        again.connect("clicked", lambda *_: self.refresh(force=True))
        head.append(again)
        box.append(head)

        note = Gtk.Label(label=(
            "Fresh songs you haven't played, seeded by your local "
            "favorites — anonymous per-song lookups only."))
        note.add_css_class("dim-label")
        note.add_css_class("caption")
        note.set_xalign(0.0)
        box.append(note)

        for section_title, tracks in sections:
            label = Gtk.Label(label=section_title)
            label.add_css_class("title-3")
            label.set_xalign(0.0)
            box.append(label)
            tl = TrackList(self.window, radio_on_single=True)
            tl.set_tracks(tracks)
            box.append(tl)

        self.show_widget(scroll_wrap(box))


class BrowsePage(Gtk.Box):
    """Explore + Discover merged behind one sidebar entry.

    A pill switcher picks between the personal Discover view (local-taste
    recommendations) and the public Charts & Moods view; each keeps its own
    lazy loading and only refreshes when shown.
    """

    def __init__(self, window):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.window = window
        self.discover = DiscoverPage(window)
        self.explore = ExplorePage(window)

        switcher = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        switcher.set_halign(Gtk.Align.CENTER)
        switcher.set_margin_top(12)
        self._discover_btn = Gtk.ToggleButton.new_with_label("Discover")
        self._discover_btn.add_css_class("pill")
        self._explore_btn = Gtk.ToggleButton.new_with_label("Charts & Moods")
        self._explore_btn.add_css_class("pill")
        self._explore_btn.set_group(self._discover_btn)
        switcher.append(self._discover_btn)
        switcher.append(self._explore_btn)
        self.append(switcher)

        self._stack = Gtk.Stack()
        self._stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        self._stack.set_vexpand(True)
        self._stack.add_named(self.discover, "discover")
        self._stack.add_named(self.explore, "explore")
        self.append(self._stack)

        self._discover_btn.connect(
            "toggled", lambda b: b.get_active() and self._show("discover"))
        self._explore_btn.connect(
            "toggled", lambda b: b.get_active() and self._show("explore"))
        # Don't load anything during construction — the first visit
        # (SearchPage.focus/refresh) triggers the initial lazy load.
        self._ready = False
        self._discover_btn.set_active(True)
        self._ready = True

    def _show(self, name: str) -> None:
        self._stack.set_visible_child_name(name)
        if not self._ready:
            return
        page = self.discover if name == "discover" else self.explore
        page.refresh()

    def show_view(self, name: str) -> None:
        (self._discover_btn if name == "discover"
         else self._explore_btn).set_active(True)

    def refresh(self) -> None:
        self._show(self._stack.get_visible_child_name() or "discover")


class SearchPage(ContentPage):
    FILTERS = [
        ("all", "All"),
        ("songs", "Songs"),
        ("albums", "Albums"),
        ("artists", "Artists"),
        ("playlists", "Playlists"),
    ]
    _RECENT_MAX = 8

    def __init__(self, window):
        super().__init__(window)
        self._query = ""
        self._kind = "all"
        self._search_seq = 0
        self._suggest_seq = 0

        controls = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        controls.set_margin_top(12)
        controls.set_margin_start(18)
        controls.set_margin_end(18)

        self.entry = Gtk.SearchEntry()
        self.entry.set_placeholder_text("Search songs, albums, artists…")
        self.entry.connect("activate", self._on_search)
        self.entry.connect("search-changed", self._on_maybe_search)
        controls.append(self.entry)

        # Live suggestions popover
        self._suggest_list = Gtk.ListBox()
        self._suggest_list.add_css_class("boxed-list")
        self._suggest_list.set_selection_mode(Gtk.SelectionMode.NONE)
        self._suggest_list.connect(
            "row-activated", self._on_suggestion_activated)
        suggest_scroll = Gtk.ScrolledWindow()
        suggest_scroll.set_policy(
            Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        suggest_scroll.set_max_content_height(240)
        suggest_scroll.set_propagate_natural_height(True)
        suggest_scroll.set_child(self._suggest_list)
        self._suggest_popover = Gtk.Popover()
        self._suggest_popover.set_autohide(True)
        self._suggest_popover.set_has_arrow(False)
        self._suggest_popover.set_child(suggest_scroll)
        self._suggest_popover.set_parent(self.entry)

        # Recent search chips (shown above browse when empty)
        self._recent_host = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL, spacing=6)
        controls.append(self._recent_host)

        filter_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self._filter_buttons: dict[str, Gtk.ToggleButton] = {}
        group_first: Gtk.ToggleButton | None = None
        for key, label in self.FILTERS:
            btn = Gtk.ToggleButton(label=label)
            btn.add_css_class("pill")
            if group_first is None:
                group_first = btn
                btn.set_active(True)
            else:
                btn.set_group(group_first)
            btn.connect("toggled", self._on_filter, key)
            self._filter_buttons[key] = btn
            filter_box.append(btn)
        controls.append(filter_box)
        self._filter_box = filter_box
        self._filter_box.set_visible(False)
        self.append(controls)

        # Empty Search is recents + a link to Explore — not the full Browse hub.
        self._results_area = ContentPage(window)
        self._results_area.set_vexpand(True)
        self._empty = ContentPage(window)
        self._empty.set_vexpand(True)
        self._mode_stack = Gtk.Stack()
        self._mode_stack.set_vexpand(True)
        self._mode_stack.set_transition_type(
            Gtk.StackTransitionType.CROSSFADE)
        self._mode_stack.add_named(self._empty, "empty")
        self._mode_stack.add_named(self._results_area, "results")
        self.append(self._mode_stack)
        self._paint_empty()
        self._paint_recent_chips()

    def focus(self) -> None:
        self.entry.grab_focus()
        if self._mode_stack.get_visible_child_name() == "empty":
            self._paint_empty()
            self._paint_recent_chips()

    def refresh(self) -> None:
        if self._mode_stack.get_visible_child_name() == "empty":
            self._paint_empty()
            self._paint_recent_chips()

    def _paint_empty(self) -> None:
        """Recent chips live above; here: StatusPage + Explore CTA."""
        page = status_page(
            "system-search-symbolic",
            "Search YouTube Music",
            "Find songs, albums, artists and playlists — or open Explore "
            "for Discover, charts and moods.",
            action_label="Open Explore",
            on_action=lambda: self.window.goto("explore"),
        )
        self._empty.show_widget(page)

    def _show_mode(self, mode: str) -> None:
        # mode is "empty" | "results" (legacy "browse" → empty)
        if mode == "browse":
            mode = "empty"
        self._mode_stack.set_visible_child_name(mode)
        self._filter_box.set_visible(mode == "results")
        self._recent_host.set_visible(mode == "empty")

    def _recent_searches(self) -> list[str]:
        raw = config.settings.get("recent_searches", [])
        if not isinstance(raw, list):
            return []
        return [str(s) for s in raw if s][: self._RECENT_MAX]

    def _save_recent(self, query: str) -> None:
        q = query.strip()
        if not q:
            return
        recent = [q] + [
            s for s in self._recent_searches() if s.lower() != q.lower()
        ]
        config.settings.set("recent_searches", recent[: self._RECENT_MAX])

    def _clear_recent(self) -> None:
        config.settings.set("recent_searches", [])
        self._paint_recent_chips()

    def _paint_recent_chips(self) -> None:
        while child := self._recent_host.get_first_child():
            self._recent_host.remove(child)
        recent = self._recent_searches()
        if not recent:
            self._recent_host.set_visible(False)
            return
        self._recent_host.set_visible(True)
        head = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        t = Gtk.Label(label="Recent")
        t.add_css_class("caption")
        t.add_css_class("dim-label")
        t.set_xalign(0.0)
        t.set_hexpand(True)
        head.append(t)
        clear = Gtk.Button(label="Clear")
        clear.add_css_class("flat")
        clear.connect("clicked", lambda *_: self._clear_recent())
        head.append(clear)
        self._recent_host.append(head)
        chips = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        for q in recent:
            chip = Gtk.Button(label=q)
            chip.add_css_class("pill")
            chip.connect("clicked", self._on_recent_chip, q)
            chips.append(chip)
        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.NEVER)
        scroller.set_child(chips)
        self._recent_host.append(scroller)

    def _on_recent_chip(self, _btn, query: str) -> None:
        self.entry.set_text(query)
        self._query = query
        self._run_search()

    def _on_filter(self, button: Gtk.ToggleButton, key: str) -> None:
        if button.get_active():
            self._kind = key
            if self._query:
                self._run_search()

    def _on_maybe_search(self, entry: Gtk.SearchEntry) -> None:
        text = entry.get_text().strip()
        if not text:
            self._query = ""
            self._search_seq += 1
            self._hide_suggestions()
            self._show_mode("empty")
            return
        if len(text) >= 2:
            self._load_suggestions(text)
        if len(text) >= 3 and text != self._query:
            self._query = text
            self._run_search()

    def _on_search(self, entry: Gtk.SearchEntry) -> None:
        self._query = entry.get_text().strip()
        self._hide_suggestions()
        if self._query:
            self._run_search()

    def _load_suggestions(self, text: str) -> None:
        self._suggest_seq += 1
        seq = self._suggest_seq

        def work():
            return self.window.api.search_suggestions(text)

        def done(suggestions: list[str]) -> None:
            if seq != self._suggest_seq:
                return
            self._suggest_list.remove_all()
            if not suggestions:
                self._hide_suggestions()
                return
            for s in suggestions[:8]:
                row = Adw.ActionRow()
                row.set_title(s)
                row.set_activatable(True)
                self._suggest_list.append(row)
            self._suggest_popover.popup()

        run_async(
            work, done, lambda _e: self._hide_suggestions(), name="riff-suggest")

    def _hide_suggestions(self) -> None:
        try:
            self._suggest_popover.popdown()
        except Exception:
            pass

    def _on_suggestion_activated(self, _lb, row: Gtk.ListBoxRow) -> None:
        child = row.get_child()
        title = child.get_title() if isinstance(child, Adw.ActionRow) else ""
        if not title:
            return
        self._hide_suggestions()
        self.entry.set_text(title)
        self._query = title
        self._run_search()

    def _run_search(self) -> None:
        self._show_mode("results")
        query, kind = self._query, self._kind
        if not query:
            return
        self._save_recent(query)
        self._search_seq += 1
        seq = self._search_seq
        api_kind = None if kind == "all" else kind

        def present(results: dict) -> None:
            if seq != self._search_seq:
                return  # stale response
            self._present(results)

        self._results_area.load_async(
            lambda: self.window.api.search(query, api_kind), present
        )

    def _present(self, results: dict) -> None:
        area = self._results_area
        songs = results.get("songs") or []
        albums = results.get("albums") or []
        artists = results.get("artists") or []
        playlists = results.get("playlists") or []

        if self._kind == "all":
            if not (songs or albums or artists or playlists):
                area.show_widget(status_page(
                    "edit-find-symbolic", "No results",
                    f"Nothing found for “{self._query}”."))
                return
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=22)
            top = songs[0] if songs else (
                albums or artists or playlists or [None])[0]
            if top is not None:
                box.append(self._top_result_card(
                    top, songs[:5] if songs else None))
            if albums:
                box.append(Carousel(
                    "Albums", albums[:12], self.window, card_size=140))
            if artists:
                box.append(Carousel(
                    "Artists", artists[:12], self.window, card_size=140))
            if playlists:
                box.append(Carousel(
                    "Playlists", playlists[:12], self.window, card_size=140))
            area.show_widget(scroll_wrap(_padded(box)))
            return

        if self._kind == "songs" and songs:
            tl = TrackList(self.window, radio_on_single=True)
            tl.set_tracks(songs)
            area.show_widget(scroll_wrap(_padded(tl)))
            return

        cards = {
            "albums": albums,
            "artists": artists,
            "playlists": playlists,
        }.get(self._kind, [])
        if cards:
            area.show_widget(scroll_wrap(_padded(CardGrid(cards, self.window))))
            return

        area.show_widget(status_page(
            "edit-find-symbolic", "No results",
            f"Nothing found for “{self._query}”."))

    def _top_result_card(
        self, item, related_songs: list[Track] | None
    ) -> Gtk.Widget:
        outer = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=18)
        outer.add_css_class("card")
        outer.set_margin_top(4)

        left = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=14)
        left.set_margin_top(12)
        left.set_margin_bottom(12)
        left.set_margin_start(12)
        left.set_margin_end(12)
        left.set_hexpand(True)

        circular = isinstance(item, Artist)
        art = CoverArt(120, circular=circular)
        art.set_url(getattr(item, "thumbnail", "") or "")
        left.append(art)

        meta = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        meta.set_valign(Gtk.Align.CENTER)
        meta.set_hexpand(True)
        kind = (
            "Song" if isinstance(item, Track)
            else "Album" if isinstance(item, Album)
            else "Artist" if isinstance(item, Artist)
            else "Playlist"
        )
        k = Gtk.Label(label=f"Top result · {kind}")
        k.add_css_class("dim-label")
        k.add_css_class("caption")
        k.set_xalign(0.0)
        meta.append(k)
        title = getattr(item, "title", "") or getattr(item, "name", "") or ""
        t = Gtk.Label(label=title)
        t.add_css_class("title-2")
        t.set_xalign(0.0)
        t.set_wrap(True)
        meta.append(t)
        sub = ""
        if isinstance(item, Track):
            sub = item.artist
        elif isinstance(item, Album):
            sub = item.artist
        elif isinstance(item, Playlist):
            sub = item.author
        if sub:
            s = Gtk.Label(label=sub)
            s.add_css_class("dim-label")
            s.set_xalign(0.0)
            meta.append(s)

        play = Gtk.Button(label="Play")
        play.add_css_class("pill")
        play.add_css_class("suggested-action")
        play.set_halign(Gtk.Align.START)
        play.connect("clicked", lambda *_: self._play_top(item))
        meta.append(play)
        left.append(meta)
        outer.append(left)

        if related_songs and len(related_songs) > 1:
            songs_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
            songs_box.set_margin_top(8)
            songs_box.set_margin_bottom(8)
            songs_box.set_margin_end(8)
            songs_box.set_size_request(280, -1)
            rest = [
                s for s in related_songs
                if not (isinstance(item, Track) and s.video_id == item.video_id)
            ][:5]
            if not rest:
                rest = related_songs[1:6]
            tl = TrackList(self.window, radio_on_single=True)
            tl.set_tracks(rest)
            songs_box.append(tl)
            outer.append(songs_box)

        return outer

    def _play_top(self, item) -> None:
        if isinstance(item, Track):
            self.window.service.play_track_with_radio(item)
        elif isinstance(item, Album):
            self.window.open_album(item.browse_id)
        elif isinstance(item, Artist) and item.browse_id:
            self.window.open_artist(item.browse_id)
        elif isinstance(item, Playlist):
            self.window.open_playlist(item.playlist_id)


class ExplorePage(ContentPage):
    """Public discovery without an account: charts and mood/genre playlists."""

    def __init__(self, window):
        super().__init__(window)
        self._loaded = False

    def refresh(self, force: bool = False) -> None:
        if self._loaded and not force:
            return

        def work():
            # Each source can fail independently (some endpoints behave
            # differently for authenticated accounts) — show whatever loads
            # and only fail the page when nothing at all came back.
            api = self.window.api
            problems = []
            try:
                categories = api.mood_categories()
            except Exception as exc:  # noqa: BLE001
                log.warning("mood categories failed", exc_info=True)
                categories = []
                problems.append(f"categories: {exc}")
            try:
                charts = api.charts()
            except Exception as exc:  # noqa: BLE001
                log.warning("charts failed", exc_info=True)
                charts = []
                problems.append(f"charts: {exc}")
            if not charts and not categories:
                raise RuntimeError("; ".join(problems) or "nothing returned")
            return charts, categories

        self.load_async(work, self._present)

    def _present(self, data) -> None:
        self._loaded = True
        charts, categories = data
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=20)
        if charts:
            title = Gtk.Label(label="Top songs worldwide")
            title.add_css_class("title-3")
            title.set_xalign(0.0)
            box.append(title)
            tl = TrackList(self.window, numbered=True, radio_on_single=True)
            tl.set_tracks(charts[:15])
            box.append(tl)
        for section, cats in categories:
            title = Gtk.Label(label=section)
            title.add_css_class("title-3")
            title.set_xalign(0.0)
            title.set_margin_top(8)
            box.append(title)
            flow = Gtk.FlowBox()
            flow.set_selection_mode(Gtk.SelectionMode.NONE)
            flow.set_max_children_per_line(10)
            flow.set_column_spacing(8)
            flow.set_row_spacing(8)
            for cat_title, params in cats:
                chip = Gtk.Button(label=cat_title)
                chip.add_css_class("pill")
                chip.connect("clicked", self._on_category, cat_title, params)
                flow.append(chip)
            box.append(flow)
        self.show_widget(scroll_wrap(_padded(box)))

    def _on_category(self, _btn, title: str, params: str) -> None:
        self.window.open_mood(title, params)


class MoodPage(ContentPage):
    """Grid of public playlists for one mood/genre category."""

    def __init__(self, window, title: str, params: str):
        super().__init__(window)
        self.load_async(
            lambda: window.api.mood_playlists(params), self._present)
        self._title = title

    def _present(self, playlists) -> None:
        if not playlists:
            self.show_widget(status_page(
                "view-list-symbolic", self._title, "No playlists found here."))
            return
        grid = CardGrid(playlists, self.window)
        self.show_widget(scroll_wrap(_padded(grid)))


def _padded(child: Gtk.Widget) -> Gtk.Box:
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
    box.set_margin_top(12)
    box.set_margin_bottom(120)
    box.set_margin_start(18)
    box.set_margin_end(18)
    box.append(child)
    return box


class _DetailPage(ContentPage):
    """Shared layout for album and playlist pages."""

    def _header(self, thumbnail: str, title: str, subtitle: str,
                tracks: list[Track], circular: bool = False,
                extra_button: Gtk.Widget | None = None) -> Gtk.Widget:
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=20)
        art = CoverArt(180, circular=circular)
        art.set_url(thumbnail)
        art.set_valign(Gtk.Align.START)
        box.append(art)

        info = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        info.set_valign(Gtk.Align.CENTER)
        t = Gtk.Label(label=title)
        t.add_css_class("title-1")
        t.set_xalign(0.0)
        t.set_wrap(True)
        info.append(t)
        if subtitle:
            s = Gtk.Label(label=subtitle)
            s.add_css_class("dim-label")
            s.set_xalign(0.0)
            s.set_wrap(True)
            info.append(s)

        buttons = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        buttons.set_margin_top(10)
        play = Gtk.Button()
        play.set_child(_button_content("media-playback-start-symbolic", "Play"))
        play.add_css_class("pill")
        play.add_css_class("suggested-action")
        play.connect("clicked", lambda *_:
                     self.window.service.play_tracks(tracks) if tracks else None)
        buttons.append(play)

        shuffle = Gtk.Button()
        shuffle.set_child(_button_content(
            "media-playlist-shuffle-symbolic", "Shuffle"))
        shuffle.add_css_class("pill")
        shuffle.connect("clicked", lambda *_: self._play_shuffled(tracks))
        buttons.append(shuffle)

        queue = Gtk.Button()
        # Match the player-bar queue icon; list-add is reserved for "Add".
        queue.set_child(_button_content("view-list-ordered-symbolic", "Queue"))
        queue.add_css_class("pill")
        queue.connect("clicked", lambda *_:
                      (self.window.service.add_to_queue(tracks),
                       self.window.toast("Added to queue")))
        buttons.append(queue)
        if extra_button is not None:
            buttons.append(extra_button)

        info.append(buttons)
        box.append(info)
        return box

    def _play_shuffled(self, tracks: list[Track]) -> None:
        if not tracks:
            return
        svc = self.window.service
        svc.play_tracks(tracks, start=random.randrange(len(tracks)))
        # If shuffle was already on, set_tracks built a shuffled order.
        if not svc.queue.shuffle:
            svc.queue.set_shuffle(True)


def _button_content(icon: str, label: str) -> Gtk.Box:
    box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
    box.append(iconutil.image(icon))
    box.append(Gtk.Label(label=label))
    return box


class AlbumPage(_DetailPage):
    def __init__(self, window, browse_id: str):
        super().__init__(window)
        self.load_async(lambda: window.api.album(browse_id), self._present)

    def _present(self, album: Album) -> None:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=20)
        subtitle_parts = [album.artist, album.year,
                          f"{len(album.tracks)} songs" if album.tracks else ""]
        box.append(self._header(
            album.thumbnail, album.title,
            " · ".join(p for p in subtitle_parts if p), album.tracks))
        tl = TrackList(self.window, numbered=True, show_art=False)
        tl.set_tracks(album.tracks)
        box.append(tl)
        self.show_widget(scroll_wrap(_padded(box)))


class PlaylistPage(_DetailPage):
    def __init__(self, window, playlist_id: str):
        super().__init__(window)
        self.load_async(lambda: window.api.playlist(playlist_id), self._present)

    def _present(self, pl: Playlist) -> None:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=20)
        subtitle_parts = [pl.author, f"{pl.track_count or len(pl.tracks)} songs"]
        box.append(self._header(
            pl.thumbnail, pl.title,
            " · ".join(p for p in subtitle_parts if p), pl.tracks,
            extra_button=self._add_button(pl)))
        tl = TrackList(self.window)
        tl.set_tracks(pl.tracks)
        box.append(tl)
        self.show_widget(scroll_wrap(_padded(box)))

    def _add_button(self, pl: Playlist) -> Gtk.Button:
        """Snapshot this public playlist into a local one."""
        btn = Gtk.Button()
        btn.set_child(_button_content("list-add-symbolic", "Add"))
        btn.add_css_class("pill")
        btn.set_tooltip_text("Save a local copy of this playlist")

        def on_clicked(_b: Gtk.Button) -> None:
            if not pl.tracks:
                self.window.toast("No songs to add")
                return
            name = pl.title.strip() or "Playlist"
            lib = self.window.library
            pid = lib.create_playlist(name)
            lib.replace_playlist_tracks(pid, pl.tracks)
            self.window.reload_sidebar_playlists()
            n = len(pl.tracks)
            plural = "song" if n == 1 else "songs"
            self.window.toast(f"Added “{name}” · {n} {plural}")
            btn.set_sensitive(False)
            btn.set_child(_button_content("list-add-symbolic", "Added"))

        btn.connect("clicked", on_clicked)
        return btn


class ArtistPage(_DetailPage):
    def __init__(self, window, channel_id: str):
        super().__init__(window)
        self.load_async(lambda: window.api.artist(channel_id), self._present)

    def _present(self, artist: Artist) -> None:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        box.append(self._header(
            artist.thumbnail, artist.name, "Artist",
            artist.songs, circular=True,
            extra_button=self._follow_button(artist)))
        if artist.songs:
            title = Gtk.Label(label="Top Songs")
            title.add_css_class("title-3")
            title.set_xalign(0.0)
            box.append(title)
            tl = TrackList(self.window, radio_on_single=True)
            tl.set_tracks(artist.songs[:10])
            box.append(tl)
        if artist.albums:
            box.append(Carousel("Albums", artist.albums, self.window))
        if artist.singles:
            box.append(Carousel("Singles & EPs", artist.singles, self.window))
        if artist.related:
            box.append(Carousel("Fans also like", artist.related,
                                self.window))
        self.show_widget(scroll_wrap(_padded(box)))

    def _follow_button(self, artist: Artist) -> Gtk.ToggleButton:
        btn = Gtk.ToggleButton()
        btn.add_css_class("pill")
        library = self.window.library
        btn.set_active(library.is_followed(artist.browse_id))
        btn.set_label("Following" if btn.get_active() else "Follow")

        def on_toggled(b: Gtk.ToggleButton) -> None:
            if b.get_active():
                library.follow_artist(
                    artist.browse_id, artist.name, artist.thumbnail)
                self.window.toast(
                    f"Following {artist.name} — new releases appear on Home")
            else:
                library.unfollow_artist(artist.browse_id)
                self.window.toast(f"Unfollowed {artist.name}")
            b.set_label("Following" if b.get_active() else "Follow")

        btn.connect("toggled", on_toggled)
        return btn


class LibraryPage(ContentPage):
    """Favorites / History / Downloads, backed by the local database."""

    def __init__(self, window, kind: str):
        super().__init__(window)
        self.kind = kind  # "favorites" | "history" | "downloads"

    def refresh(self) -> None:
        lib = self.window.library
        fetch = {
            "favorites": lib.favorites,
            "history": lib.recent,
            "downloads": lib.downloads,
            "dislikes": lib.dislikes,
        }[self.kind]
        self.load_async(fetch, self._present)

    def _present(self, tracks: list[Track]) -> None:
        if not tracks:
            specs = {
                "favorites": (
                    "emblem-favorite-symbolic", "No favorites yet",
                    "Songs you favorite appear here.",
                    "Search music", lambda: self.window.goto("search"),
                ),
                "history": (
                    "document-open-recent-symbolic", "No history yet",
                    "Songs you play appear here.",
                    "Go to Home", lambda: self.window.goto("home"),
                ),
                "downloads": (
                    "folder-download-symbolic", "No downloads yet",
                    "Use a song's menu to download it for offline listening.",
                    "Search music", lambda: self.window.goto("search"),
                ),
                "dislikes": (
                    "action-unavailable-symbolic", "Nothing blocked",
                    "Use a song's menu → “Never Play This” to keep it "
                    "out of radio and AI Mix.",
                    None, None,
                ),
            }[self.kind]
            icon, title, desc, action_label, on_action = specs
            self.show_widget(status_page(
                icon, title, desc,
                action_label=action_label, on_action=on_action))
            return
        tl = TrackList(self.window)
        tl.set_tracks(tracks)
        self.show_widget(scroll_wrap(_padded(tl)))


class StatsPage(ContentPage):
    """Listening statistics from the local history database."""

    RANGES = [
        ("week", "Week", 7),
        ("month", "Month", 30),
        ("year", "Year", 365),
        ("all", "All time", 0),
    ]

    def __init__(self, window):
        super().__init__(window)
        self._range = "month"

    def refresh(self) -> None:
        lib = self.window.library
        since, until, prev_since, prev_until, activity_days = self._window_for(
            self._range)

        def work():
            overview = lib.stats_overview(since=since, until=until)
            prev = (
                lib.stats_overview(since=prev_since, until=prev_until)
                if prev_since is not None else None
            )
            return (
                overview,
                prev,
                lib.most_played(10, since=since, until=until),
                lib.top_artists(10, since=since, until=until),
                lib.plays_by_day(activity_days) if activity_days
                else lib.plays_by_day(30),
            )

        self.load_async(work, self._present)

    @staticmethod
    def _window_for(key: str) -> tuple:
        import time

        now = time.time()
        if key == "week":
            secs = 7 * 86400
            return now - secs, None, now - 2 * secs, now - secs, 7
        if key == "month":
            secs = 30 * 86400
            return now - secs, None, now - 2 * secs, now - secs, 30
        if key == "year":
            secs = 365 * 86400
            return now - secs, None, now - 2 * secs, now - secs, 30
        return None, None, None, None, 30

    def _on_range(self, button: Gtk.ToggleButton, key: str) -> None:
        if button.get_active() and key != self._range:
            self._range = key
            self.refresh()

    @staticmethod
    def _delta_label(current: int, previous: int | None) -> str:
        if previous is None or previous == 0:
            return ""
        pct = round(100 * (current - previous) / previous)
        if pct == 0:
            return "±0%"
        return f"{pct:+d}%"

    def _range_selector(self) -> Gtk.Box:
        range_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        group_first: Gtk.ToggleButton | None = None
        for key, label, _days in self.RANGES:
            btn = Gtk.ToggleButton(label=label)
            btn.add_css_class("pill")
            if group_first is None:
                group_first = btn
            else:
                btn.set_group(group_first)
            btn.set_active(key == self._range)
            btn.connect("toggled", self._on_range, key)
            range_row.append(btn)
        return range_row

    def _present(self, data) -> None:
        overview, prev, top_songs, top_artists, days = data
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=22)
        top = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        top.append(self._range_selector())
        rewind_btn = Gtk.Button(label="Riff Rewind")
        rewind_btn.add_css_class("suggested-action")
        rewind_btn.add_css_class("pill")
        rewind_btn.set_valign(Gtk.Align.CENTER)
        rewind_btn.connect("clicked", lambda *_: self._show_rewind())
        top.append(rewind_btn)
        box.append(top)

        if not overview["plays"]:
            box.append(status_page(
                "riff-stats-symbolic", "No stats yet",
                "Play some music in this period and your listening trends "
                "appear here.",
                action_label="Go to Home",
                on_action=lambda: self.window.goto("home")))
            self.show_widget(scroll_wrap(_padded(box)))
            return

        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        row.set_homogeneous(True)
        hours = overview["seconds"] / 3600
        prev_hours = (prev["seconds"] / 3600) if prev else None
        cards = [
            (f"{overview['plays']}", "plays",
             overview["plays"], prev["plays"] if prev else None),
            (f"{overview['songs']}", "songs",
             overview["songs"], prev["songs"] if prev else None),
            (f"{overview.get('artists', 0)}", "artists",
             overview.get("artists", 0),
             prev.get("artists", 0) if prev else None),
            (f"{hours:.1f} h", "listened",
             int(hours * 10),
             int(prev_hours * 10) if prev_hours is not None else None),
        ]
        for value, label, cur, prv in cards:
            card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
            card.add_css_class("card")
            card.set_margin_top(2)
            v = Gtk.Label(label=value)
            v.add_css_class("title-1")
            v.set_margin_top(14)
            n = Gtk.Label(label=label)
            n.add_css_class("dim-label")
            card.append(v)
            card.append(n)
            delta = self._delta_label(cur, prv)
            if delta:
                dlab = Gtk.Label(label=delta)
                dlab.add_css_class("caption")
                if delta.startswith("+"):
                    dlab.add_css_class("success")
                elif delta.startswith("-"):
                    dlab.add_css_class("error")
                else:
                    dlab.add_css_class("dim-label")
                dlab.set_margin_bottom(10)
                card.append(dlab)
                n.set_margin_bottom(4)
            else:
                n.set_margin_bottom(14)
            row.append(card)
        box.append(row)

        period_label = {
            "week": "Last 7 days",
            "month": "Last 30 days",
            "year": "Recent activity",
            "all": "Last 30 days",
        }.get(self._range, "Activity")
        title = Gtk.Label(label=period_label)
        title.add_css_class("title-3")
        title.set_xalign(0.0)
        box.append(title)
        maximum = max((c for _d, c in days), default=0) or 1
        day_list = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        for day, count in days:
            line = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
            d = Gtk.Label(label=day[5:])  # MM-DD
            d.add_css_class("numeric")
            d.add_css_class("dim-label")
            line.append(d)
            bar = Gtk.LevelBar.new_for_interval(0, maximum)
            bar.set_value(count)
            bar.set_hexpand(True)
            bar.set_valign(Gtk.Align.CENTER)
            line.append(bar)
            c = Gtk.Label(label=str(count))
            c.add_css_class("numeric")
            c.set_width_chars(4)
            line.append(c)
            day_list.append(line)
        box.append(day_list)

        if top_songs:
            t = Gtk.Label(label="Top songs")
            t.add_css_class("title-3")
            t.set_xalign(0.0)
            box.append(t)
            max_plays = max(p for _tr, p in top_songs) or 1
            song_list = Gtk.Box(
                orientation=Gtk.Orientation.VERTICAL, spacing=6)
            for i, (track, plays) in enumerate(top_songs, 1):
                line = Gtk.Box(
                    orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
                num = Gtk.Label(label=str(i))
                num.add_css_class("dim-label")
                num.set_width_chars(2)
                line.append(num)
                art = CoverArt(36)
                art.set_url(track.thumbnail)
                line.append(art)
                text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
                text.set_hexpand(True)
                tt = Gtk.Label(label=track.title)
                tt.set_xalign(0.0)
                tt.add_css_class("heading")
                text.append(tt)
                bar = Gtk.LevelBar.new_for_interval(0, max_plays)
                bar.set_value(plays)
                bar.set_hexpand(True)
                text.append(bar)
                line.append(text)
                pc = Gtk.Label(label=str(plays))
                pc.add_css_class("numeric")
                pc.add_css_class("dim-label")
                pc.set_width_chars(4)
                line.append(pc)
                btn = Gtk.Button()
                btn.add_css_class("flat")
                btn.set_child(line)
                btn.connect(
                    "clicked",
                    lambda _b, tr=track: self.window.service.play_track_with_radio(tr),
                )
                song_list.append(btn)
            box.append(song_list)

        if top_artists:
            t = Gtk.Label(label="Top artists")
            t.add_css_class("title-3")
            t.set_xalign(0.0)
            box.append(t)
            max_a = max(p for _n, p in top_artists) or 1
            lb = Gtk.ListBox()
            lb.add_css_class("boxed-list")
            lb.set_selection_mode(Gtk.SelectionMode.NONE)
            for i, (name, plays) in enumerate(top_artists, 1):
                row_a = Adw.ActionRow()
                row_a.set_title(f"{i}.  {name}")
                row_a.set_subtitle(f"{plays} plays")
                bar = Gtk.LevelBar.new_for_interval(0, max_a)
                bar.set_value(plays)
                bar.set_size_request(80, -1)
                bar.set_valign(Gtk.Align.CENTER)
                row_a.add_suffix(bar)
                lb.append(row_a)
            box.append(lb)

        self.show_widget(scroll_wrap(_padded(box)))

    def _show_rewind(self) -> None:
        from ..core import rewind as rewind_mod

        data = rewind_mod.build_rewind(self.window.library)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18)
        back = Gtk.Button(label="← Stats")
        back.add_css_class("flat")
        back.set_halign(Gtk.Align.START)
        back.connect("clicked", lambda *_: self.refresh())
        box.append(back)

        title = Gtk.Label(label="Riff Rewind")
        title.add_css_class("title-1")
        title.set_xalign(0.0)
        box.append(title)
        sub = Gtk.Label(
            label="Your listening story from local history — "
                  "no account, no server.")
        sub.add_css_class("dim-label")
        sub.set_wrap(True)
        sub.set_xalign(0.0)
        box.append(sub)

        if not data.get("enough"):
            box.append(status_page(
                "riff-stats-symbolic", "Not enough plays yet",
                "Keep listening — Rewind unlocks after a handful of plays."))
            self.show_widget(scroll_wrap(_padded(box)))
            return

        level = Gtk.Label(label=str(data["level"]))
        level.add_css_class("title-1")
        level.set_xalign(0.0)
        box.append(level)
        level_cap = Gtk.Label(label="Listener level")
        level_cap.add_css_class("dim-label")
        level_cap.set_xalign(0.0)
        box.append(level_cap)

        hours = data["seconds"] / 3600
        hours_txt = f"{hours:.0f}" if hours >= 100 else f"{hours:.1f}"
        for value, label in (
            (str(data["plays"]), "total plays"),
            (hours_txt, "hours listened"),
            (str(data["artists"]), "artists explored"),
        ):
            line = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
            v = Gtk.Label(label=value)
            v.add_css_class("title-1")
            line.append(v)
            n = Gtk.Label(label=label)
            n.add_css_class("title-3")
            n.set_xalign(0.0)
            n.set_hexpand(True)
            line.append(n)
            box.append(line)

        if data.get("top_artist"):
            name, plays = data["top_artist"]
            art = Gtk.Label(label=f"Top artist · {name} ({plays})")
            art.add_css_class("heading")
            art.set_xalign(0.0)
            box.append(art)
        if data.get("top_song"):
            track, plays = data["top_song"]
            song = Gtk.Label(
                label=f"Top song · {track.title} ({plays})")
            song.add_css_class("heading")
            song.set_xalign(0.0)
            box.append(song)

        self.show_widget(scroll_wrap(_padded(box)))


class LocalFilesPage(ContentPage):
    """Music files from a local folder (Settings → local music folder)."""

    def refresh(self) -> None:
        from .. import config
        from ..core import localfiles

        folder = str(config.settings.get("local_music_dir", "~/Music"))
        self.load_async(lambda: (folder, localfiles.scan(folder)),
                        self._present)

    def _present(self, data) -> None:
        folder, tracks = data
        if not tracks:
            self.show_widget(status_page(
                "folder-music-symbolic", "No local music found",
                f"No audio files in {folder}. Change the folder in Settings — "
                "files named “Artist - Title.mp3” get proper artist tags."))
            return
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        play = Gtk.Button()
        play.set_child(_button_content("media-playback-start-symbolic",
                                       f"Play All ({len(tracks)})"))
        play.add_css_class("pill")
        play.add_css_class("suggested-action")
        play.set_halign(Gtk.Align.START)
        play.connect("clicked",
                     lambda *_: self.window.service.play_tracks(tracks))
        box.append(play)
        tl = TrackList(self.window, show_art=False)
        tl.set_tracks(tracks)
        box.append(tl)
        self.show_widget(scroll_wrap(_padded(box)))


class PlaylistsPage(ContentPage):
    """Local playlists + folders (Spotify-style)."""

    def __init__(self, window):
        super().__init__(window)

    def refresh(self) -> None:
        def work():
            tree = self.window.library.playlist_tree()
            covers = {}
            for item in tree:
                if item["kind"] == "playlist":
                    tracks = self.window.library.playlist_tracks(item["id"])
                    covers[item["id"]] = tracks[0].thumbnail if tracks else ""
                else:
                    for pid, _n, _c in item["playlists"]:
                        tracks = self.window.library.playlist_tracks(pid)
                        covers[pid] = tracks[0].thumbnail if tracks else ""
            return tree, covers

        self.load_async(work, self._present)

    def _present(self, data) -> None:
        tree, covers = data
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)

        actions = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        new_btn = Gtk.Button()
        new_btn.set_child(_button_content("list-add-symbolic", "New Playlist"))
        new_btn.add_css_class("pill")
        new_btn.connect("clicked", lambda *_: self._create_playlist())
        actions.append(new_btn)
        folder_btn = Gtk.Button()
        folder_btn.set_child(
            _button_content("folder-music-symbolic", "New Folder"))
        folder_btn.add_css_class("pill")
        folder_btn.connect("clicked", lambda *_: self._create_folder())
        actions.append(folder_btn)
        box.append(actions)

        if not tree:
            box.append(status_page(
                "view-list-symbolic", "No playlists yet",
                "Create a playlist or a folder to organize them."))
            self.show_widget(scroll_wrap(_padded(box)))
            return

        for item in tree:
            if item["kind"] == "folder":
                box.append(self._folder_block(item, covers))
            else:
                listbox = Gtk.ListBox()
                listbox.add_css_class("boxed-list")
                listbox.set_selection_mode(Gtk.SelectionMode.NONE)
                listbox.append(self._playlist_row(
                    item["id"], item["name"], item["count"], covers))
                box.append(listbox)

        self.show_widget(scroll_wrap(_padded(box)))

    def _folder_block(self, item: dict, covers: dict) -> Gtk.Widget:
        from gi.repository import Gdk, GObject

        from .folder_badge import FolderBadge

        block = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        fcolor = item.get("color") or "#38bdf8"
        femoji = item.get("emoji") or "🎵"
        icon_btn = Gtk.Button()
        icon_btn.add_css_class("flat")
        icon_btn.set_tooltip_text("Change color & emoji · right-click for menu")
        icon_btn.set_child(FolderBadge(fcolor, femoji, size=36))
        icon_btn.connect(
            "clicked",
            lambda *_: self.window.choose_folder_style(
                item["id"], fcolor, femoji))
        # Right-click menu on the badge / header area
        self.window._install_folder_context_menu(
            icon_btn, item["id"], item["name"], fcolor, femoji)
        header.append(icon_btn)
        title = Gtk.Label(label=item["name"])
        title.add_css_class("title-3")
        title.set_xalign(0.0)
        title.set_hexpand(True)
        title.set_selectable(False)
        header.append(title)
        self.window._install_folder_context_menu(
            header, item["id"], item["name"], fcolor, femoji)
        rename = Gtk.Button()
        iconutil.set_button(rename, "document-edit-symbolic")
        rename.add_css_class("flat")
        rename.set_tooltip_text("Rename folder")
        rename.connect("clicked", self._on_rename_folder, item["id"])
        header.append(rename)
        delete = Gtk.Button()
        iconutil.set_button(delete, "user-trash-symbolic")
        delete.add_css_class("flat")
        delete.set_tooltip_text("Delete folder (playlists stay)")
        delete.connect("clicked", self._on_delete_folder, item["id"])
        header.append(delete)
        block.append(header)

        listbox = Gtk.ListBox()
        listbox.add_css_class("boxed-list")
        listbox.set_selection_mode(Gtk.SelectionMode.NONE)
        # Drop playlists onto the folder's list area.
        drop = Gtk.DropTarget.new(GObject.TYPE_STRING, Gdk.DragAction.MOVE)
        drop.connect(
            "drop",
            lambda _t, value, _x, _y, fid=item["id"]:
                self.window._on_playlist_dropped(value, fid))
        listbox.add_controller(drop)
        if item["playlists"]:
            for pid, name, count in item["playlists"]:
                listbox.append(self._playlist_row(pid, name, count, covers))
        else:
            empty = Adw.ActionRow()
            empty.set_title("Empty folder")
            empty.set_subtitle(
                "Drag a playlist here, or use Move to folder on a playlist")
            empty.set_sensitive(False)
            listbox.append(empty)
        block.append(listbox)
        return block

    def _playlist_row(self, pid: int, name: str, count: int,
                      covers: dict) -> Adw.ActionRow:
        from gi.repository import Gdk

        row = Adw.ActionRow()
        row.set_title(name)
        row.set_subtitle(f"{count} songs · drag to a folder")
        row.set_activatable(True)
        art = CoverArt(44, icon="view-list-symbolic")
        art.set_url(covers.get(pid, ""))
        art.set_valign(Gtk.Align.CENTER)
        row.add_prefix(art)
        # Drag playlist onto a folder.
        source = Gtk.DragSource()
        source.set_actions(Gdk.DragAction.MOVE)
        source.connect(
            "prepare",
            lambda _s, _x, _y, p=pid:
                Gdk.ContentProvider.new_for_value(f"playlist:{p}"))
        row.add_controller(source)
        move = Gtk.Button()
        iconutil.set_button(move, "folder-music-symbolic")
        move.add_css_class("flat")
        move.set_valign(Gtk.Align.CENTER)
        move.set_tooltip_text("Move to folder")
        move.connect(
            "clicked",
            lambda *_: self.window.choose_folder_for(pid))
        row.add_suffix(move)
        rename = Gtk.Button()
        iconutil.set_button(rename, "document-edit-symbolic")
        rename.add_css_class("flat")
        rename.set_valign(Gtk.Align.CENTER)
        rename.set_tooltip_text("Rename")
        rename.connect("clicked", self._on_rename, pid)
        row.add_suffix(rename)
        delete = Gtk.Button()
        iconutil.set_button(delete, "user-trash-symbolic")
        delete.add_css_class("flat")
        delete.set_valign(Gtk.Align.CENTER)
        delete.set_tooltip_text("Delete")
        delete.connect("clicked", self._on_delete, pid)
        row.add_suffix(delete)
        row.connect("activated", self._on_open, pid, name)
        return row

    def _create_playlist(self) -> None:
        self.window.prompt_text(
            "New Playlist", "Name",
            lambda name: (self.window.library.create_playlist(name),
                          self.refresh(),
                          self.window.reload_sidebar_playlists()))

    def _create_folder(self) -> None:
        self.window.create_folder_dialog()

    def _on_rename(self, _btn, pid: int) -> None:
        self.window.prompt_text(
            "Rename Playlist", "New name",
            lambda name: (self.window.library.rename_playlist(pid, name),
                          self.refresh(),
                          self.window.reload_sidebar_playlists()),
            accept_label="Rename")

    def _on_rename_folder(self, _btn, folder_id: int) -> None:
        self.window.prompt_text(
            "Rename Folder", "New name",
            lambda name: (self.window.library.rename_folder(folder_id, name),
                          self.refresh(),
                          self.window.reload_sidebar_playlists()),
            accept_label="Rename")

    def _on_delete(self, _btn, pid: int) -> None:
        self.window.library.delete_playlist(pid)
        self.refresh()
        self.window.reload_sidebar_playlists()

    def _on_delete_folder(self, _btn, folder_id: int) -> None:
        self.window.library.delete_folder(folder_id)
        self.refresh()
        self.window.reload_sidebar_playlists()

    def _on_open(self, _row, pid: int, name: str) -> None:
        self.window.open_local_playlist(pid, name)


class LocalPlaylistPage(ContentPage):
    def __init__(self, window, playlist_id: int, name: str):
        super().__init__(window)
        self.playlist_id = playlist_id
        self.name = name
        self.refresh()

    def refresh(self) -> None:
        self.load_async(
            lambda: self.window.library.playlist_tracks(self.playlist_id),
            self._present)

    def _present(self, tracks: list[Track]) -> None:
        if not tracks:
            self.show_widget(status_page(
                "view-list-symbolic", self.name,
                "This playlist is empty — add songs from any song menu."))
            return
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        play = Gtk.Button()
        play.set_child(_button_content("media-playback-start-symbolic", "Play All"))
        play.add_css_class("pill")
        play.add_css_class("suggested-action")
        play.set_halign(Gtk.Align.START)
        play.connect("clicked",
                     lambda *_: self.window.service.play_tracks(tracks))
        box.append(play)
        tl = TrackList(self.window)
        tl.set_tracks(tracks)
        box.append(tl)
        self.show_widget(scroll_wrap(_padded(box)))
