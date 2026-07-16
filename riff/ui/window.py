"""Main application window: sidebar navigation, content stack, player bar."""

from __future__ import annotations

from gi.repository import Adw, Gio, Gtk

from .. import APP_NAME, config
from ..core.models import Track
from ..util import run_async
from ..core import lyrics as lyrics_mod
from .pages import (
    AlbumPage,
    ArtistPage,
    ExplorePage,
    HomePage,
    LibraryPage,
    LocalPlaylistPage,
    MoodPage,
    PlaylistPage,
    PlaylistsPage,
    SearchPage,
)
from .player_bar import PlayerBar
from .queue_panel import QueuePanel

CSS = b"""
.riff-cover {
    border-radius: 8px;
    background-color: alpha(currentColor, 0.08);
}
.riff-cover picture, .riff-cover image {
    border-radius: 8px;
}
.riff-cover-circular, .riff-cover-circular picture, .riff-cover-circular image {
    border-radius: 9999px;
}
.riff-player-bar {
    background-color: @headerbar_bg_color;
    border-top: 1px solid @borders;
}
.riff-card {
    padding: 8px;
    border-radius: 12px;
}
.riff-lyric-current {
    color: @accent_color;
    font-weight: 700;
    font-size: 1.1em;
}
.riff-heart {
    font-size: 17px;
    font-weight: 700;
}
button.dim-label .riff-heart {
    opacity: 0.55;
}
"""

SIDEBAR_ITEMS = [
    ("home", "Home", "user-home-symbolic"),
    ("explore", "Explore", "web-browser-symbolic"),
    ("search", "Search", "system-search-symbolic"),
    ("favorites", "Favorites", "emblem-favorite-symbolic"),
    ("history", "History", "document-open-recent-symbolic"),
    ("playlists", "Playlists", "view-list-symbolic"),
    ("downloads", "Downloads", "folder-download-symbolic"),
]


class MainWindow(Adw.ApplicationWindow):
    def __init__(self, app, service, api, library, downloader):
        super().__init__(application=app)
        self.service = service
        self.api = api
        self.library = library
        self.downloader = downloader

        self.set_title(APP_NAME)
        self.set_default_size(
            int(config.settings.get("window_width", 1100)),
            int(config.settings.get("window_height", 720)),
        )
        self._load_css()

        # pages -----------------------------------------------------------
        self.pages = {
            "home": HomePage(self),
            "explore": ExplorePage(self),
            "search": SearchPage(self),
            "favorites": LibraryPage(self, "favorites"),
            "history": LibraryPage(self, "history"),
            "playlists": PlaylistsPage(self),
            "downloads": LibraryPage(self, "downloads"),
        }
        self.stack = Gtk.Stack()
        self.stack.set_vexpand(True)
        for name, page in self.pages.items():
            self.stack.add_named(page, name)

        # navigation view wraps the stack so detail pages can be pushed ----
        self.nav = Adw.NavigationView()
        root_page = Adw.NavigationPage.new(self.stack, APP_NAME)
        root_page.set_tag("root")
        self.nav.add(root_page)

        # header bar --------------------------------------------------------
        header = Adw.HeaderBar()
        title = Adw.WindowTitle.new(APP_NAME, "")
        header.set_title_widget(title)
        menu = Gio.Menu()
        menu.append("AI Mix", "win.ai-mix")
        menu.append("Lyrics", "win.lyrics")
        menu.append("Settings", "win.settings")
        menu.append("About Riff", "win.about")
        menu_btn = Gtk.MenuButton()
        menu_btn.set_icon_name("open-menu-symbolic")
        menu_btn.set_menu_model(menu)
        header.pack_end(menu_btn)

        content_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        content_box.append(header)
        content_box.append(self.nav)

        # sidebar -----------------------------------------------------------
        self.sidebar_list = Gtk.ListBox()
        self.sidebar_list.add_css_class("navigation-sidebar")
        self.sidebar_list.connect("row-activated", self._on_sidebar)
        for name, label, icon in SIDEBAR_ITEMS:
            row = Gtk.ListBoxRow()
            row.item_name = name
            box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
            box.set_margin_top(8)
            box.set_margin_bottom(8)
            box.set_margin_start(8)
            box.append(Gtk.Image.new_from_icon_name(icon))
            box.append(Gtk.Label(label=label))
            row.set_child(box)
            self.sidebar_list.append(row)

        sidebar_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        app_title = Gtk.Label(label="♫ Riff")
        app_title.add_css_class("title-2")
        app_title.set_margin_top(16)
        app_title.set_margin_bottom(10)
        sidebar_box.append(app_title)
        sidebar_box.append(self.sidebar_list)

        # playlists section, YT-Music style ---------------------------------
        sidebar_box.append(Gtk.Separator(margin_top=10, margin_bottom=4))
        new_pl = Gtk.Button()
        new_pl_label = Gtk.Label(label="＋  New playlist")
        new_pl.set_child(new_pl_label)
        new_pl.add_css_class("pill")
        new_pl.set_margin_start(10)
        new_pl.set_margin_end(10)
        new_pl.set_margin_top(6)
        new_pl.set_margin_bottom(4)
        new_pl.connect("clicked", lambda *_: self.prompt_text(
            "New Playlist", "Name",
            lambda name: (self.library.create_playlist(name),
                          self.reload_sidebar_playlists())))
        sidebar_box.append(new_pl)

        self.playlist_list = Gtk.ListBox()
        self.playlist_list.add_css_class("navigation-sidebar")
        self.playlist_list.set_selection_mode(Gtk.SelectionMode.NONE)
        self.playlist_list.connect("row-activated", self._on_sidebar_playlist)
        sidebar_box.append(self.playlist_list)

        sidebar_scroll = Gtk.ScrolledWindow()
        sidebar_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        sidebar_scroll.set_vexpand(True)
        sidebar_scroll.set_child(sidebar_box)

        split = Adw.OverlaySplitView()
        split.set_sidebar(sidebar_scroll)
        split.set_content(content_box)
        split.set_min_sidebar_width(200)
        split.set_max_sidebar_width(220)

        # queue flap on the right --------------------------------------------
        self.queue_panel = QueuePanel(self)
        self.queue_split = Adw.OverlaySplitView()
        self.queue_split.set_sidebar_position(Gtk.PackType.END)
        self.queue_split.set_sidebar(self.queue_panel)
        self.queue_split.set_content(split)
        self.queue_split.set_show_sidebar(False)
        self.queue_split.set_min_sidebar_width(300)
        self.queue_split.set_max_sidebar_width(340)

        # player bar + toasts ---------------------------------------------------
        self.player_bar = PlayerBar(self)
        self.player_bar.queue_btn.connect("toggled", self._on_queue_toggle)

        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        outer.append(self.queue_split)
        outer.append(self.player_bar)

        self.toaster = Adw.ToastOverlay()
        self.toaster.set_child(outer)
        self.set_content(self.toaster)

        self.service.error_listeners.append(self.toast)
        self._install_actions()
        self.connect("close-request", self._on_close)

        # select Home
        self.sidebar_list.select_row(self.sidebar_list.get_row_at_index(0))
        self.pages["home"].refresh()
        self.reload_sidebar_playlists()

    # -- css / actions --------------------------------------------------------

    def _load_css(self) -> None:
        provider = Gtk.CssProvider()
        provider.load_from_data(CSS)
        Gtk.StyleContext.add_provider_for_display(
            self.get_display(), provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

    def _install_actions(self) -> None:
        actions = {
            "lyrics": self.show_lyrics,
            "settings": self.show_settings,
            "ai-mix": self.start_ai_mix,
            "about": self.show_about,
        }
        for name, cb in actions.items():
            action = Gio.SimpleAction.new(name, None)
            action.connect("activate", lambda _a, _p, cb=cb: cb())
            self.add_action(action)

    # -- navigation ------------------------------------------------------------

    def _on_sidebar(self, _lb, row) -> None:
        name = getattr(row, "item_name", "home")
        self.nav.pop_to_tag("root")
        self.stack.set_visible_child_name(name)
        page = self.pages[name]
        if name == "search":
            page.focus()
        elif hasattr(page, "refresh"):
            page.refresh()

    def _push(self, widget, title: str) -> None:
        page = Adw.NavigationPage.new(widget, title or APP_NAME)
        self.nav.push(page)

    def open_album(self, browse_id: str) -> None:
        if browse_id:
            self._push(AlbumPage(self, browse_id), "Album")

    def open_artist(self, channel_id: str) -> None:
        if channel_id:
            self._push(ArtistPage(self, channel_id), "Artist")

    def open_playlist(self, playlist_id: str) -> None:
        if playlist_id:
            self._push(PlaylistPage(self, playlist_id), "Playlist")

    def open_local_playlist(self, playlist_id: int, name: str) -> None:
        self._push(LocalPlaylistPage(self, playlist_id, name), name)

    def open_mood(self, title: str, params: str) -> None:
        self._push(MoodPage(self, title, params), title)

    # -- sidebar playlists -------------------------------------------------------

    def reload_sidebar_playlists(self) -> None:
        """Fill the sidebar with local playlists plus, when an account is
        connected, the account's own playlists (incl. Liked Music)."""

        def work():
            local = self.library.playlists()
            try:
                remote = self.api.library_playlists()
            except Exception:  # noqa: BLE001 — sidebar must never fail hard
                remote = []
            return local, remote

        def present(data) -> None:
            local, remote = data
            self.playlist_list.remove_all()
            for pid, name, count in local:
                plural = "song" if count == 1 else "songs"
                self._add_playlist_row(
                    name, f"{count} {plural} · local", "local", (pid, name))
            for pl in remote:
                self._add_playlist_row(
                    pl.title, pl.author or "YouTube Music", "remote",
                    pl.playlist_id)

        run_async(work, present, lambda _e: None, name="riff-sidebar-pl")

    def _add_playlist_row(self, title: str, subtitle: str,
                          kind: str, ref) -> None:
        from gi.repository import Pango

        row = Gtk.ListBoxRow()
        row.kind = kind
        row.ref = ref
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
        box.set_margin_top(5)
        box.set_margin_bottom(5)
        box.set_margin_start(8)
        t = Gtk.Label(label=title)
        t.set_xalign(0.0)
        t.set_ellipsize(Pango.EllipsizeMode.END)
        t.add_css_class("heading")
        s = Gtk.Label(label=subtitle)
        s.set_xalign(0.0)
        s.set_ellipsize(Pango.EllipsizeMode.END)
        s.add_css_class("dim-label")
        s.add_css_class("caption")
        box.append(t)
        box.append(s)
        row.set_child(box)
        self.playlist_list.append(row)

    def _on_sidebar_playlist(self, _lb, row) -> None:
        if row.kind == "local":
            pid, name = row.ref
            self.open_local_playlist(pid, name)
        else:
            self.open_playlist(row.ref)

    def _on_queue_toggle(self, btn) -> None:
        self.queue_split.set_show_sidebar(btn.get_active())

    # -- helpers used by widgets ------------------------------------------------

    def toast(self, message: str) -> None:
        self.toaster.add_toast(Adw.Toast.new(str(message)))

    def prompt_text(self, title: str, placeholder: str, on_accept,
                    accept_label: str = "Create") -> None:
        dialog = Adw.AlertDialog.new(title, None)
        entry = Gtk.Entry()
        entry.set_placeholder_text(placeholder)
        entry.set_margin_top(6)
        dialog.set_extra_child(entry)
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("ok", accept_label)
        dialog.set_response_appearance("ok", Adw.ResponseAppearance.SUGGESTED)
        dialog.set_default_response("ok")

        def on_response(_d, response: str) -> None:
            text = entry.get_text().strip()
            if response == "ok" and text:
                on_accept(text)

        dialog.connect("response", on_response)
        entry.connect("activate", lambda *_:
                      (dialog.close(), on_response(dialog, "ok")))
        dialog.present(self)

    def choose_playlist_for(self, track: Track) -> None:
        playlists = self.library.playlists()
        dialog = Adw.AlertDialog.new("Add to Playlist", track.title)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        listbox = Gtk.ListBox()
        listbox.add_css_class("boxed-list")
        listbox.set_selection_mode(Gtk.SelectionMode.NONE)
        for pid, name, count in playlists:
            row = Adw.ActionRow()
            row.set_title(name)
            row.set_subtitle(f"{count} songs")
            row.set_activatable(True)
            row.connect("activated", lambda _r, pid=pid: (
                self.library.add_to_playlist(pid, track),
                self.toast("Added to playlist"),
                self.reload_sidebar_playlists(),
                dialog.close()))
            listbox.append(row)
        if playlists:
            box.append(listbox)
        new_btn = Gtk.Button(label="New Playlist…")
        new_btn.add_css_class("flat")
        new_btn.connect("clicked", lambda *_: (
            dialog.close(),
            self.prompt_text("New Playlist", "Name", lambda name: (
                self.library.add_to_playlist(
                    self.library.create_playlist(name), track),
                self.toast(f"Added to “{name}”"),
                self.reload_sidebar_playlists()))))
        box.append(new_btn)
        dialog.set_extra_child(box)
        dialog.add_response("cancel", "Cancel")
        dialog.present(self)

    def download_track(self, track: Track) -> None:
        self.toast(f"Downloading “{track.title}”…")

        def done(path: str) -> None:
            self.toast(f"Downloaded “{track.title}”")

        def error(exc: Exception) -> None:
            self.toast(f"Download failed: {exc}")

        run_async(lambda: self.downloader.download(track), done, error,
                  name="riff-download")

    def show_lyrics(self) -> None:
        track = self.service.current_track
        if track is None:
            self.toast("Nothing is playing")
            return

        def work():
            synced, plain = lyrics_mod.fetch_lyrics(track)
            if not synced and not plain:
                plain = self.api.lyrics(track.video_id)
            return synced, plain

        def present(result) -> None:
            synced, plain = result
            if synced:
                self._lyrics_dialog_synced(track, synced)
            else:
                self._lyrics_dialog_plain(track, plain)

        run_async(work, present, lambda _e: self.toast("Couldn't fetch lyrics"))

    def _lyrics_dialog(self, track: Track, content: Gtk.Widget) -> Adw.Dialog:
        dialog = Adw.Dialog.new()
        dialog.set_title(f"Lyrics — {track.title}")
        dialog.set_content_width(480)
        dialog.set_content_height(620)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        box.append(Adw.HeaderBar())
        sw = Gtk.ScrolledWindow()
        sw.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        sw.set_vexpand(True)
        sw.set_child(content)
        box.append(sw)
        dialog.set_child(box)
        return dialog

    def _lyrics_dialog_plain(self, track: Track, text: str) -> None:
        label = Gtk.Label(label=text or "No lyrics found for this song.")
        label.set_wrap(True)
        label.set_margin_top(12)
        label.set_margin_bottom(24)
        label.set_margin_start(24)
        label.set_margin_end(24)
        label.set_selectable(True)
        self._lyrics_dialog(track, label).present(self)

    def _lyrics_dialog_synced(self, track: Track,
                              lines: list[tuple[float, str]]) -> None:
        listbox = Gtk.ListBox()
        listbox.set_selection_mode(Gtk.SelectionMode.NONE)
        listbox.set_margin_top(12)
        listbox.set_margin_bottom(24)
        listbox.set_margin_start(16)
        listbox.set_margin_end(16)
        labels: list[Gtk.Label] = []
        for ts, text in lines:
            row = Gtk.ListBoxRow()
            row.timestamp = ts
            label = Gtk.Label(label=text or "♪")
            label.set_wrap(True)
            label.set_xalign(0.0)
            label.set_margin_top(4)
            label.set_margin_bottom(4)
            label.add_css_class("dim-label")
            row.set_child(label)
            listbox.append(row)
            labels.append(label)
        listbox.connect(
            "row-activated",
            lambda _lb, row: self.service.seek(row.timestamp))

        dialog = self._lyrics_dialog(track, listbox)
        state = {"idx": -1}

        def on_position(pos: float) -> None:
            idx = lyrics_mod.line_index_at(lines, pos)
            if idx == state["idx"]:
                return
            if 0 <= state["idx"] < len(labels):
                labels[state["idx"]].remove_css_class("riff-lyric-current")
                labels[state["idx"]].add_css_class("dim-label")
            state["idx"] = idx
            if 0 <= idx < len(labels):
                labels[idx].remove_css_class("dim-label")
                labels[idx].add_css_class("riff-lyric-current")
                row = listbox.get_row_at_index(idx)
                scroller = listbox.get_ancestor(Gtk.ScrolledWindow)
                if row is not None and scroller is not None:
                    # keep the active line roughly centered
                    vadj = scroller.get_vadjustment()
                    target = row.get_allocation().y
                    vadj.set_value(max(0.0, target - vadj.get_page_size() / 2.5))

        self.service.position_listeners.append(on_position)
        dialog.connect(
            "closed",
            lambda *_: self.service.position_listeners.remove(on_position))
        dialog.present(self)

    def show_settings(self) -> None:
        from .settings import SettingsDialog

        SettingsDialog(self).present(self)

    def start_ai_mix(self) -> None:
        from ..core import ai

        key = str(config.settings.get("anthropic_api_key", "") or "")
        if not key:
            self.toast("Add your Anthropic API key in Settings to use AI Mix")
            self.show_settings()
            return

        def work():
            recent = self.library.recent(30)
            favorites = self.library.favorites()[:30]
            if not recent and not favorites:
                raise RuntimeError(
                    "Play or favorite some songs first — AI Mix learns from them")
            suggestions = ai.suggest_songs(key, recent, favorites)
            known = {t.video_id for t in recent}
            tracks, seen = [], set()
            for title, artist in suggestions:
                try:
                    results = self.api.search(f"{title} {artist}", "songs")
                except Exception:  # noqa: BLE001 — skip unresolvable songs
                    continue
                for candidate in results.get("songs", [])[:1]:
                    if candidate.video_id not in seen | known:
                        seen.add(candidate.video_id)
                        tracks.append(candidate)
            if not tracks:
                raise RuntimeError("Couldn't find the suggested songs on YouTube Music")
            return tracks

        def done(tracks) -> None:
            self.service.play_tracks(tracks)
            self.toast(f"AI Mix: queued {len(tracks)} songs")

        self.toast("Creating your AI Mix — this takes a few seconds…")
        run_async(work, done,
                  lambda exc: self.toast(f"AI Mix failed: {exc}"),
                  name="riff-ai-mix")

    def show_about(self) -> None:
        from .. import __version__

        about = Adw.AboutDialog.new()
        about.set_application_name(APP_NAME)
        about.set_application_icon("io.github.aimdi.Riff")
        about.set_version(__version__)
        about.set_comments("A native YouTube Music player for Linux")
        about.set_website("https://github.com/aimdi/player")
        about.set_license_type(Gtk.License.GPL_3_0)
        about.present(self)

    def _on_close(self, _win) -> bool:
        w, h = self.get_default_size()
        config.settings.set("window_width", w)
        config.settings.set("window_height", h)
        return False
