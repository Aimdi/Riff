"""Main application window: sidebar navigation, content stack, player bar."""

from __future__ import annotations

import logging

from gi.repository import Adw, Gio, GLib, Gtk

log = logging.getLogger("riff.window")

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
    LocalFilesPage,
    LocalPlaylistPage,
    MoodPage,
    PlaylistPage,
    PlaylistsPage,
    SearchPage,
    StatsPage,
)
from . import iconutil
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

AI_MIX_PLAYLIST = "✨ AI Mix"

SIDEBAR_ITEMS = [
    ("home", "Home", "user-home-symbolic"),
    ("explore", "Explore", "web-browser-symbolic"),
    ("search", "Search", "system-search-symbolic"),
    ("favorites", "Favorites", "emblem-favorite-symbolic"),
    ("history", "History", "document-open-recent-symbolic"),
    ("stats", "Stats", "riff-stats-symbolic"),
    ("playlists", "Playlists", "view-list-symbolic"),
    ("local", "Local Files", "folder-music-symbolic"),
    ("downloads", "Downloads", "folder-download-symbolic"),
    ("dislikes", "Disliked", "action-unavailable-symbolic"),
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
            "stats": StatsPage(self),
            "playlists": PlaylistsPage(self),
            "local": LocalFilesPage(self),
            "downloads": LibraryPage(self, "downloads"),
            "dislikes": LibraryPage(self, "dislikes"),
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
        menu.append("Mini Player", "win.mini")
        menu.append("Keyboard Shortcuts", "win.shortcuts")
        menu.append("Settings", "win.settings")
        menu.append("About Riff", "win.about")
        menu_btn = Gtk.MenuButton()
        menu_btn.set_child(iconutil.image("open-menu-symbolic"))
        menu_btn.set_menu_model(menu)
        header.pack_end(menu_btn)

        # profile avatar (Spotify-style, top right)
        self._avatar = Adw.Avatar.new(28, None, True)
        avatar_btn = Gtk.Button()
        avatar_btn.set_child(self._avatar)
        avatar_btn.add_css_class("flat")
        avatar_btn.set_tooltip_text("Profile")
        avatar_btn.connect("clicked", lambda *_: self.show_profile())
        header.pack_end(avatar_btn)
        self._refresh_avatar()

        content_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        content_box.append(header)
        content_box.append(self.nav)

        # sidebar (collapsible into a Spotify-style icon rail) ----------------
        self._sidebar_collapsed = bool(
            config.settings.get("sidebar_collapsed", False))

        header_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        self._app_title = Gtk.Label(label="♫ Riff")
        self._app_title.add_css_class("title-2")
        self._app_title.set_hexpand(True)
        self._app_title.set_margin_start(12)
        self._app_title.set_xalign(0.0)
        header_row.append(self._app_title)
        self._collapse_btn = Gtk.Button()
        self._collapse_btn.add_css_class("flat")
        self._collapse_btn.set_tooltip_text("Collapse sidebar")
        self._collapse_label = Gtk.Label(label="«")
        self._collapse_label.add_css_class("riff-heart")
        self._collapse_btn.set_child(self._collapse_label)
        self._collapse_btn.connect(
            "clicked", lambda *_: self._toggle_sidebar())
        header_row.append(self._collapse_btn)
        header_row.set_margin_top(10)
        header_row.set_margin_bottom(6)
        header_row.set_margin_end(4)

        self.sidebar_list = Gtk.ListBox()
        self.sidebar_list.add_css_class("navigation-sidebar")
        self.sidebar_list.connect("row-activated", self._on_sidebar)
        self._nav_rows = []
        for name, label, icon in SIDEBAR_ITEMS:
            row = Gtk.ListBoxRow()
            row.item_name = name
            box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
            box.set_margin_top(8)
            box.set_margin_bottom(8)
            box.set_margin_start(8)
            # Bundled SVGs — system themes leave some of these blank/invisible.
            box.append(iconutil.image(icon))
            text = Gtk.Label(label=label)
            box.append(text)
            row.set_child(box)
            self._nav_rows.append((row, box, text, label))
            self.sidebar_list.append(row)

        sidebar_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        sidebar_box.append(header_row)
        sidebar_box.append(self.sidebar_list)

        # playlists section ---------------------------------------------------
        sidebar_box.append(Gtk.Separator(margin_top=10, margin_bottom=4))
        # Spotify-style create menu: new playlist or folder
        self._new_pl = Gtk.MenuButton()
        self._new_pl_label = Gtk.Label(label="＋  New")
        self._new_pl.set_child(self._new_pl_label)
        self._new_pl.add_css_class("pill")
        self._new_pl.set_margin_top(6)
        self._new_pl.set_margin_bottom(4)
        self._new_pl.set_tooltip_text("New playlist or folder")
        create_menu = Gio.Menu()
        create_menu.append("New playlist", "win.new-playlist")
        create_menu.append("New folder", "win.new-folder")
        self._new_pl.set_menu_model(create_menu)
        sidebar_box.append(self._new_pl)
        self._expanded_folders: set[int] = set(
            int(x) for x in (config.settings.get("expanded_folders") or [])
            if str(x).lstrip("-").isdigit()
        )

        self.playlist_list = Gtk.ListBox()
        self.playlist_list.add_css_class("navigation-sidebar")
        self.playlist_list.set_selection_mode(Gtk.SelectionMode.NONE)
        self.playlist_list.connect("row-activated", self._on_sidebar_playlist)
        sidebar_box.append(self.playlist_list)

        sidebar_scroll = Gtk.ScrolledWindow()
        sidebar_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        sidebar_scroll.set_vexpand(True)
        sidebar_scroll.set_child(sidebar_box)

        self._nav_split = Adw.OverlaySplitView()
        split = self._nav_split
        split.set_sidebar(sidebar_scroll)
        split.set_content(content_box)
        self._apply_sidebar_mode()

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
            "mini": self.open_mini_player,
            "shortcuts": self.show_shortcuts,
            "about": self.show_about,
            "new-playlist": self.create_playlist_dialog,
            "new-folder": self.create_folder_dialog,
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

    def _toggle_sidebar(self) -> None:
        self._sidebar_collapsed = not self._sidebar_collapsed
        config.settings.set("sidebar_collapsed", self._sidebar_collapsed)
        self._apply_sidebar_mode()
        self.reload_sidebar_playlists()

    def _apply_sidebar_mode(self) -> None:
        collapsed = self._sidebar_collapsed
        if collapsed:
            self._nav_split.set_min_sidebar_width(84)
            self._nav_split.set_max_sidebar_width(84)
        else:
            self._nav_split.set_min_sidebar_width(210)
            self._nav_split.set_max_sidebar_width(230)
        self._app_title.set_visible(not collapsed)
        self._collapse_label.set_label("»" if collapsed else "«")
        self._collapse_btn.set_tooltip_text(
            "Expand sidebar" if collapsed else "Collapse sidebar")
        if collapsed:
            self._collapse_btn.set_halign(Gtk.Align.CENTER)
            self._collapse_btn.set_hexpand(True)
        else:
            self._collapse_btn.set_halign(Gtk.Align.END)
            self._collapse_btn.set_hexpand(False)
        for row, box, text, label in self._nav_rows:
            text.set_visible(not collapsed)
            box.set_halign(Gtk.Align.CENTER if collapsed else Gtk.Align.FILL)
            box.set_margin_start(0 if collapsed else 8)
            row.set_tooltip_text(label if collapsed else None)
        # create menu: Spotify-style round "+" when collapsed
        self._new_pl_label.set_label("＋" if collapsed else "＋  New")
        if collapsed:
            self._new_pl.remove_css_class("pill")
            self._new_pl.add_css_class("circular")
            self._new_pl.set_halign(Gtk.Align.CENTER)
            self._new_pl.set_margin_start(0)
            self._new_pl.set_margin_end(0)
        else:
            self._new_pl.remove_css_class("circular")
            self._new_pl.add_css_class("pill")
            self._new_pl.set_halign(Gtk.Align.FILL)
            self._new_pl.set_margin_start(10)
            self._new_pl.set_margin_end(10)

    def reload_sidebar_playlists(self) -> None:
        """Fill the sidebar with folders, local playlists, and (when signed
        in) the account's YouTube Music playlists."""

        def work():
            tree = self.library.playlist_tree()
            covers: dict[int, str] = {}
            for item in tree:
                if item["kind"] == "playlist":
                    tracks = self.library.playlist_tracks(item["id"])
                    covers[item["id"]] = tracks[0].thumbnail if tracks else ""
                else:
                    for pid, _n, _c in item["playlists"]:
                        tracks = self.library.playlist_tracks(pid)
                        covers[pid] = tracks[0].thumbnail if tracks else ""
            try:
                remote = self.api.library_playlists()
            except Exception:  # noqa: BLE001 — sidebar must never fail hard
                remote = []
            return tree, covers, remote

        def present(data) -> None:
            tree, covers, remote = data
            self.playlist_list.remove_all()
            for item in tree:
                if item["kind"] == "folder":
                    self._add_folder_row(item, covers)
                else:
                    pid, name, count = item["id"], item["name"], item["count"]
                    plural = "song" if count == 1 else "songs"
                    self._add_playlist_row(
                        name, f"{count} {plural} · local", "local",
                        (pid, name), covers.get(pid, ""), indent=0)
            for pl in remote:
                self._add_playlist_row(
                    pl.title, pl.author or "YouTube Music", "remote",
                    pl.playlist_id, pl.thumbnail)

        run_async(work, present, lambda _e: None, name="riff-sidebar-pl")

    def _add_folder_row(self, item: dict, covers: dict[int, str]) -> None:
        from gi.repository import Pango

        from . import iconutil
        from .widgets import CoverArt

        fid = item["id"]
        name = item["name"]
        children = item["playlists"]
        expanded = fid in self._expanded_folders
        n = len(children)
        plural = "playlist" if n == 1 else "playlists"

        row = Gtk.ListBoxRow()
        row.kind = "folder"
        row.ref = fid

        if self._sidebar_collapsed:
            art = CoverArt(52, icon="folder-music-symbolic")
            art.set_margin_top(4)
            art.set_margin_bottom(4)
            art.set_halign(Gtk.Align.CENTER)
            row.set_child(art)
            row.set_tooltip_text(f"{name}\n{n} {plural}")
            self.playlist_list.append(row)
            # When collapsed, still show children as cover tiles under it.
            if expanded:
                for pid, pname, count in children:
                    ppl = "song" if count == 1 else "songs"
                    self._add_playlist_row(
                        pname, f"{count} {ppl} · local", "local",
                        (pid, pname), covers.get(pid, ""), indent=0)
            return

        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        box.set_margin_top(4)
        box.set_margin_bottom(4)
        box.set_margin_start(6)
        chevron = Gtk.Label(label="▾" if expanded else "▸")
        chevron.add_css_class("dim-label")
        chevron.set_width_chars(1)
        box.append(chevron)
        icon = iconutil.image("folder-music-symbolic", size=18)
        icon.set_valign(Gtk.Align.CENTER)
        box.append(icon)
        text_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
        text_box.set_valign(Gtk.Align.CENTER)
        text_box.set_hexpand(True)
        t = Gtk.Label(label=name)
        t.set_xalign(0.0)
        t.set_ellipsize(Pango.EllipsizeMode.END)
        t.add_css_class("heading")
        s = Gtk.Label(label=f"{n} {plural}")
        s.set_xalign(0.0)
        s.add_css_class("dim-label")
        s.add_css_class("caption")
        text_box.append(t)
        text_box.append(s)
        box.append(text_box)
        row.set_child(box)
        self.playlist_list.append(row)

        if expanded:
            for pid, pname, count in children:
                ppl = "song" if count == 1 else "songs"
                self._add_playlist_row(
                    pname, f"{count} {ppl} · local", "local",
                    (pid, pname), covers.get(pid, ""), indent=1)

    def _add_playlist_row(self, title: str, subtitle: str,
                          kind: str, ref, cover: str = "",
                          indent: int = 0) -> None:
        from gi.repository import Pango

        from .widgets import CoverArt

        row = Gtk.ListBoxRow()
        row.kind = kind
        row.ref = ref

        if self._sidebar_collapsed:
            # Spotify-style rail: just the cover tile, name in the tooltip.
            art = CoverArt(52, icon="view-list-symbolic")
            art.set_url(cover)
            art.set_margin_top(4)
            art.set_margin_bottom(4)
            art.set_halign(Gtk.Align.CENTER)
            row.set_child(art)
            row.set_tooltip_text(f"{title}\n{subtitle}")
            self.playlist_list.append(row)
            return

        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        box.set_margin_top(4)
        box.set_margin_bottom(4)
        box.set_margin_start(6 + (18 * indent))
        art = CoverArt(38, icon="view-list-symbolic")
        art.set_url(cover)
        art.set_valign(Gtk.Align.CENTER)
        box.append(art)
        text_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
        text_box.set_valign(Gtk.Align.CENTER)
        t = Gtk.Label(label=title)
        t.set_xalign(0.0)
        t.set_ellipsize(Pango.EllipsizeMode.END)
        t.add_css_class("heading")
        s = Gtk.Label(label=subtitle)
        s.set_xalign(0.0)
        s.set_ellipsize(Pango.EllipsizeMode.END)
        s.add_css_class("dim-label")
        s.add_css_class("caption")
        text_box.append(t)
        text_box.append(s)
        box.append(text_box)
        row.set_child(box)
        self.playlist_list.append(row)

    def _on_sidebar_playlist(self, _lb, row) -> None:
        kind = getattr(row, "kind", None)
        if kind == "folder":
            fid = row.ref
            if fid in self._expanded_folders:
                self._expanded_folders.discard(fid)
            else:
                self._expanded_folders.add(fid)
            config.settings.set(
                "expanded_folders", sorted(self._expanded_folders))
            self.reload_sidebar_playlists()
        elif kind == "local":
            pid, name = row.ref
            self.open_local_playlist(pid, name)
        elif kind == "remote":
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

    def goto(self, name: str) -> None:
        """Navigate to a main sidebar page (used by keyboard shortcuts)."""
        for i, (item, _label, _icon) in enumerate(SIDEBAR_ITEMS):
            if item == name:
                row = self.sidebar_list.get_row_at_index(i)
                self.sidebar_list.select_row(row)
                self._on_sidebar(self.sidebar_list, row)
                return

    def create_playlist_dialog(self) -> None:
        self.prompt_text(
            "New Playlist", "Name",
            lambda name: (self.library.create_playlist(name),
                          self.reload_sidebar_playlists()))

    def create_folder_dialog(self) -> None:
        self.prompt_text(
            "New Folder", "Name",
            lambda name: (self.library.create_folder(name),
                          self.reload_sidebar_playlists(),
                          self.toast(f"Folder “{name}” created")))

    def choose_folder_for(self, playlist_id: int) -> None:
        """Move a local playlist into a folder (or root)."""
        folders = self.library.folders()
        dialog = Adw.AlertDialog.new("Move to folder", None)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        listbox = Gtk.ListBox()
        listbox.add_css_class("boxed-list")
        listbox.set_selection_mode(Gtk.SelectionMode.NONE)

        def pick(folder_id: int | None, label: str):
            row = Adw.ActionRow()
            row.set_title(label)
            row.set_activatable(True)
            row.connect("activated", lambda _r, fid=folder_id: (
                self.library.set_playlist_folder(playlist_id, fid),
                self.toast("Moved" if fid is not None else "Moved to root"),
                self.reload_sidebar_playlists(),
                (self.pages["playlists"].refresh()
                 if "playlists" in self.pages else None),
                dialog.close()))
            listbox.append(row)

        pick(None, "No folder (root)")
        for fid, fname in folders:
            pick(fid, fname)
        box.append(listbox)
        if not folders:
            hint = Gtk.Label(label="Create a folder from the sidebar ＋ menu first")
            hint.add_css_class("dim-label")
            hint.set_wrap(True)
            box.append(hint)
        dialog.set_extra_child(box)
        dialog.add_response("cancel", "Cancel")
        dialog.present(self)

    # -- shortcuts overlay -------------------------------------------------------

    SHORTCUTS = [
        ("Basic", [
            ("Create new playlist", "Alt Shift P"),
            ("Quick search", "Ctrl K"),
            ("Keyboard shortcuts", "Ctrl /"),
            ("Settings", "Ctrl ,"),
            ("Quit", "Ctrl Q"),
        ]),
        ("Playback", [
            ("Play / Pause", "Space"),
            ("Like (favorite)", "Alt Shift B"),
            ("Shuffle", "Alt S"),
            ("Repeat", "Alt R"),
            ("Skip to previous", "Ctrl ←"),
            ("Skip to next", "Ctrl →"),
            ("Seek backward", "Shift ←"),
            ("Seek forward", "Shift →"),
            ("Raise volume", "Alt ↑"),
            ("Lower volume", "Alt ↓"),
        ]),
        ("Navigation", [
            ("Home", "Alt Shift H"),
            ("Search", "Ctrl F"),
            ("Liked songs (Favorites)", "Alt Shift S"),
            ("Queue", "Alt Shift Q"),
            ("Your playlists", "Alt Shift 1"),
            ("Stats", "Alt Shift T"),
        ]),
        ("Layout", [
            ("Toggle sidebar rail", "Alt Shift L"),
            ("Mini player", "Alt Shift M"),
            ("Lyrics", "Alt Shift Y"),
        ]),
    ]

    def show_shortcuts(self) -> None:
        dialog = Adw.Dialog.new()
        dialog.set_title("Keyboard Shortcuts")
        dialog.set_content_width(460)
        dialog.set_content_height(620)
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        outer.append(Adw.HeaderBar())
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        box.set_margin_top(6)
        box.set_margin_bottom(24)
        box.set_margin_start(20)
        box.set_margin_end(20)
        hint = Gtk.Label(label="Press Ctrl+/ or ? to toggle this dialog.")
        hint.add_css_class("dim-label")
        hint.set_xalign(0.0)
        box.append(hint)
        for section, items in self.SHORTCUTS:
            title = Gtk.Label(label=section)
            title.add_css_class("title-3")
            title.set_xalign(0.0)
            title.set_margin_top(10)
            box.append(title)
            for name, keys in items:
                row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
                label = Gtk.Label(label=name)
                label.set_xalign(0.0)
                label.set_hexpand(True)
                row.append(label)
                for key in keys.split(" "):
                    cap = Gtk.Label(label=key)
                    cap.add_css_class("keycap")
                    row.append(cap)
                box.append(row)
        sw = Gtk.ScrolledWindow()
        sw.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        sw.set_vexpand(True)
        sw.set_child(box)
        outer.append(sw)
        dialog.set_child(outer)
        dialog.present(self)

    # -- profile --------------------------------------------------------------

    def _refresh_avatar(self) -> None:
        name = str(config.settings.get("profile_name", "") or "")
        self._avatar.set_text(name or "Riff")
        self._avatar.set_show_initials(bool(name))
        picture = str(config.settings.get("profile_picture", "") or "")
        if picture:
            try:
                from gi.repository import Gdk

                self._avatar.set_custom_image(
                    Gdk.Texture.new_from_filename(picture))
            except Exception:  # noqa: BLE001 — file may have moved
                log.warning("couldn't load profile picture %s", picture)

    def show_profile(self) -> None:
        dialog = Adw.Dialog.new()
        dialog.set_title("Profile")
        dialog.set_content_width(360)
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        outer.append(Adw.HeaderBar())

        big = Adw.Avatar.new(96, None, True)
        name0 = str(config.settings.get("profile_name", "") or "")
        big.set_text(name0 or "Riff")
        big.set_show_initials(bool(name0))
        pic0 = str(config.settings.get("profile_picture", "") or "")
        if pic0:
            try:
                from gi.repository import Gdk

                big.set_custom_image(Gdk.Texture.new_from_filename(pic0))
            except Exception:  # noqa: BLE001
                pass
        big.set_halign(Gtk.Align.CENTER)
        outer.append(big)

        name_row = Adw.EntryRow()
        name_row.set_title("Name")
        name_row.set_text(name0)
        name_row.set_show_apply_button(True)
        name_row.connect("apply", lambda row: (
            config.settings.set("profile_name", row.get_text().strip()),
            self._refresh_avatar(),
            big.set_text(row.get_text().strip() or "Riff"),
            big.set_show_initials(True)))
        group = Gtk.ListBox()
        group.add_css_class("boxed-list")
        group.set_selection_mode(Gtk.SelectionMode.NONE)
        group.set_margin_start(16)
        group.set_margin_end(16)
        group.append(name_row)
        outer.append(group)

        choose = Gtk.Button(label="Choose picture…")
        choose.add_css_class("pill")
        choose.set_halign(Gtk.Align.CENTER)
        choose.set_margin_bottom(18)

        def on_choose(_btn) -> None:
            file_dialog = Gtk.FileDialog()
            img_filter = Gtk.FileFilter()
            img_filter.set_name("Images")
            img_filter.add_mime_type("image/*")
            filters = Gio.ListStore.new(Gtk.FileFilter)
            filters.append(img_filter)
            file_dialog.set_filters(filters)

            def on_open(fd, result) -> None:
                try:
                    file = fd.open_finish(result)
                except Exception:  # noqa: BLE001 — user cancelled
                    return
                path = file.get_path()
                if path:
                    config.settings.set("profile_picture", path)
                    self._refresh_avatar()
                    try:
                        from gi.repository import Gdk

                        big.set_custom_image(
                            Gdk.Texture.new_from_filename(path))
                    except Exception:  # noqa: BLE001
                        self.toast("Couldn't load that image")

            file_dialog.open(self, None, on_open)

        choose.connect("clicked", on_choose)
        outer.append(choose)
        dialog.set_child(outer)
        dialog.present(self)

    def open_mini_player(self) -> None:
        from .mini import MiniPlayer

        mini = MiniPlayer(self)
        self.set_visible(False)
        mini.present()

    def show_settings(self) -> None:
        from .settings import SettingsDialog

        SettingsDialog(self).present(self)

    def _ai_provider_config(self, interactive: bool) -> dict | None:
        from ..core import local_ai

        provider = str(config.settings.get("ai_provider", "anthropic"))
        if provider == "local":
            st = local_ai.status()
            if not st.ready:
                if interactive:
                    self.toast(
                        "Install the local model in Settings → AI Mix first")
                    self.show_settings()
                return None
            return {"provider": "local"}
        if provider == "openai":
            model = str(config.settings.get("openai_model", "") or "")
            if not model:
                if interactive:
                    self.toast("Set the model name in Settings to use AI Mix")
                    self.show_settings()
                return None
            return {
                "provider": "openai",
                "base_url": str(config.settings.get("openai_base_url", "") or ""),
                "key": str(config.settings.get("openai_api_key", "") or ""),
                "model": model,
            }
        key = str(config.settings.get("anthropic_api_key", "") or "")
        if not key:
            if interactive:
                self.toast("Add your Anthropic API key in Settings to use AI Mix")
                self.show_settings()
            return None
        return {"provider": "anthropic", "key": key}

    def start_ai_mix(self) -> None:
        self.refresh_ai_mix(interactive=True)

    def maybe_auto_refresh_ai_mix(self) -> None:
        """Daily background refresh, if enabled and configured."""
        import datetime

        if not config.settings.get("ai_mix_auto_refresh", False):
            return
        today = datetime.date.today().isoformat()
        if config.settings.get("ai_mix_last_refresh", "") == today:
            return
        if self._ai_provider_config(interactive=False) is None:
            return
        if not self.library.recent(1) and not self.library.favorites():
            return
        log.info("auto-refreshing AI Mix")
        self.refresh_ai_mix(interactive=False)

    def refresh_ai_mix(self, interactive: bool = True) -> None:
        from ..core import ai, local_ai

        cfg = self._ai_provider_config(interactive)
        if cfg is None:
            return

        dialog = spinner = status_label = None
        if interactive:
            # Progress window: a long AI call must never look like "nothing
            # happened" — status stays visible and errors persist until closed.
            dialog = Adw.Dialog.new()
            dialog.set_title("AI Mix")
            dialog.set_content_width(380)
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
            box.append(Adw.HeaderBar())
            spinner = Gtk.Spinner()
            spinner.set_size_request(32, 32)
            spinner.set_halign(Gtk.Align.CENTER)
            spinner.start()
            box.append(spinner)
            status_label = Gtk.Label(label="Reading your listening history…")
            status_label.set_wrap(True)
            status_label.set_margin_start(20)
            status_label.set_margin_end(20)
            status_label.set_margin_bottom(24)
            box.append(status_label)
            dialog.set_child(box)
            dialog.present(self)

        def set_status(text: str) -> None:
            if status_label is not None:
                GLib.idle_add(
                    lambda: (status_label.set_label(text), False)[1])

        def work():
            recent = self.library.recent(40)
            favorites = self.library.favorites()[:40]
            if not recent and not favorites:
                raise RuntimeError(
                    "Play or favorite some songs first — AI Mix learns from them")
            most_played = self.library.most_played(20)
            following = [f[1] for f in self.library.followed_artists()]
            prev_id = self.library.find_playlist(AI_MIX_PLAYLIST)
            previous_mix = (
                self.library.playlist_tracks(prev_id) if prev_id else [])
            dislikes = self.library.dislikes()
            context = {
                "most_played": most_played,
                "following": following,
                "avoid": previous_mix + dislikes,
            }
            set_status("Analyzing your taste and curating songs…\n"
                       "(this can take up to a minute)")
            if cfg["provider"] == "local":
                set_status(
                    "Running the on-device model…\n"
                    "(first run loads it into memory — can take a minute)")
                suggestions = local_ai.suggest_songs(
                    recent, favorites, **context)
            elif cfg["provider"] == "openai":
                suggestions = ai.suggest_songs_openai(
                    cfg["base_url"], cfg["key"], cfg["model"],
                    recent, favorites, **context)
            else:
                suggestions = ai.suggest_songs(
                    cfg["key"], recent, favorites, **context)
            known = ({t.video_id for t in recent}
                     | {t.video_id for t in previous_mix}
                     | {t.video_id for t in dislikes})
            tracks, seen = [], set()
            for i, (title, artist) in enumerate(suggestions, 1):
                set_status(
                    f"Finding songs on YouTube Music… {i}/{len(suggestions)}")
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
            import datetime

            pid = self.library.find_playlist(AI_MIX_PLAYLIST)
            if pid is None:
                pid = self.library.create_playlist(AI_MIX_PLAYLIST)
            self.library.replace_playlist_tracks(pid, tracks)
            config.settings.set(
                "ai_mix_last_refresh", datetime.date.today().isoformat())
            self.reload_sidebar_playlists()
            if interactive:
                self.service.play_tracks(tracks)
                dialog.close()
            self.toast(
                f"AI Mix refreshed: {len(tracks)} songs — saved to "
                f"“{AI_MIX_PLAYLIST}” in the sidebar")

        def fail(exc: Exception) -> None:
            if not interactive:
                log.warning("background AI Mix refresh failed: %s", exc)
                return
            spinner.stop()
            spinner.set_visible(False)
            status_label.set_label(f"AI Mix failed:\n{exc}")
            status_label.add_css_class("error")

        run_async(work, done, fail, name="riff-ai-mix")

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
