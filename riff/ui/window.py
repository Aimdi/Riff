"""Main application window: sidebar navigation, content stack, player bar."""

from __future__ import annotations

import logging

from gi.repository import Adw, Gdk, Gio, GLib, GObject, Gtk

log = logging.getLogger("riff.window")

from .. import APP_NAME, config
from ..core.models import Track
from ..util import run_async
from ..core import lyrics as lyrics_mod
from .pages import (
    AlbumPage,
    ArtistPage,
    BrowsePage,
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
button.riff-video-toggle {
    padding: 0;
    min-height: 22px;
    min-width: 22px;
    background-color: alpha(#000000, 0.55);
    color: #ffffff;
}
button.riff-video-toggle:checked {
    background-color: alpha(@accent_bg_color, 0.9);
}
/* Compact Home "For you" chips */
button.riff-for-you-chip {
    padding: 0;
    min-height: 0;
    border-radius: 10px;
    background-color: alpha(currentColor, 0.06);
}
button.riff-for-you-chip:hover {
    background-color: alpha(currentColor, 0.12);
}
/* Drop target highlight when dragging a playlist onto a folder. */
row.riff-drop-hover {
    background-color: alpha(@accent_bg_color, 0.35);
    border-radius: 8px;
}
/* Keep cover tiles from growing with huge YouTube textures. */
.riff-cover {
    min-width: 0;
    min-height: 0;
}
.riff-cover picture {
    min-width: 0;
    min-height: 0;
}
/* Now-playing title/artist look like plain text but act as links. */
button.riff-now-link {
    padding: 0;
    min-height: 0;
    min-width: 0;
    border-radius: 0;
}
button.riff-now-link label {
    padding: 0;
}
button.riff-now-link:hover label {
    opacity: 0.75;
}
button.riff-now-link.riff-now-link-active:hover label {
    color: @accent_color;
    opacity: 1;
}
button.riff-cover-link {
    padding: 0;
    min-height: 0;
    min-width: 0;
    border-radius: 8px;
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
/* Spotify-style Home shortcut tiles (greeting grid). */
button.riff-shortcut {
    background-color: alpha(currentColor, 0.07);
    border-radius: 8px;
    padding: 0;
    min-height: 56px;
}
button.riff-shortcut:hover {
    background-color: alpha(currentColor, 0.15);
}
.riff-liked-tile {
    background: linear-gradient(135deg, #4526c8, #9a6aff);
    border-radius: 8px;
    color: #ffffff;
    font-size: 20px;
}
/* Spotify-style hover play button on cards. */
button.riff-card-play {
    background-color: @accent_bg_color;
    color: @accent_fg_color;
    border-radius: 9999px;
    min-width: 42px;
    min-height: 42px;
    padding: 0;
}
button.riff-card-play:hover {
    background-color: @accent_color;
}
button.dim-label .riff-heart {
    opacity: 0.55;
}
"""

AI_MIX_PLAYLIST = "✨ AI Mix"

SIDEBAR_ITEMS = [
    ("home", "Home", "user-home-symbolic"),
    ("explore", "Explore", "riff-discover-symbolic"),
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
            "explore": BrowsePage(self),
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
        menu.append("Import from Spotify…", "win.spotify-import")
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

        # right panel: queue / Now Playing share one flap (like Spotify) ----
        from .now_playing import NowPlayingPanel

        self.queue_panel = QueuePanel(self)
        self.queue_split = Adw.OverlaySplitView()
        self.queue_split.set_sidebar_position(Gtk.PackType.END)
        self.right_stack = Gtk.Stack()
        self.right_stack.set_transition_type(
            Gtk.StackTransitionType.CROSSFADE)
        self.right_stack.add_named(self.queue_panel, "queue")
        self.queue_split.set_sidebar(self.right_stack)
        self.queue_split.set_content(split)
        self.queue_split.set_show_sidebar(False)
        self.queue_split.set_min_sidebar_width(300)
        self.queue_split.set_max_sidebar_width(340)

        # player bar + toasts (video plays inside the cover-art slot)
        self.player_bar = PlayerBar(self)
        self.now_playing_panel = NowPlayingPanel(self)
        self.right_stack.add_named(self.now_playing_panel, "now")
        self._right_sync = False
        self.player_bar.queue_btn.connect("toggled", self._on_queue_toggle)
        self.player_bar.now_btn.connect("toggled", self._on_now_toggle)

        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        outer.append(self.queue_split)
        outer.append(self.player_bar)

        self.toaster = Adw.ToastOverlay()
        self.toaster.set_child(outer)
        self.set_content(self.toaster)

        self.service.error_listeners.append(self.toast)
        self.service.video_listeners.append(self._on_video_mode)
        self.service.video_paintable_listeners.append(
            self.player_bar.set_video_paintable)
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
            "spotify-import": self.import_spotify_dialog,
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
            covers: dict[int, list] = {}
            # Up to 8 thumbnails per playlist: set_urls dedupes and builds a
            # 2x2 collage when 4 distinct covers exist (Snowify-style).
            for item in tree:
                if item["kind"] == "playlist":
                    tracks = self.library.playlist_tracks(item["id"])
                    covers[item["id"]] = [t.thumbnail for t in tracks[:8]]
                else:
                    for pid, _n, _c in item["playlists"]:
                        tracks = self.library.playlist_tracks(pid)
                        covers[pid] = [t.thumbnail for t in tracks[:8]]
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
                        (pid, name), covers.get(pid) or [], indent=0)
            for pl in remote:
                self._add_playlist_row(
                    pl.title, pl.author or "YouTube Music", "remote",
                    pl.playlist_id, pl.thumbnail)

        run_async(work, present, lambda _e: None, name="riff-sidebar-pl")

    def _add_folder_row(self, item: dict, covers: dict[int, list]) -> None:
        from gi.repository import Pango

        from .folder_badge import FolderBadge

        fid = item["id"]
        name = item["name"]
        fcolor = item.get("color") or self.library.DEFAULT_FOLDER_COLOR
        femoji = item.get("emoji") or self.library.DEFAULT_FOLDER_EMOJI
        children = item["playlists"]
        expanded = fid in self._expanded_folders
        n = len(children)
        plural = "playlist" if n == 1 else "playlists"

        row = Gtk.ListBoxRow()
        row.kind = "folder"
        row.ref = fid
        row.folder_meta = {
            "id": fid, "name": name, "color": fcolor, "emoji": femoji,
        }
        self._install_folder_drop(row, fid)
        self._install_folder_context_menu(row, fid, name, fcolor, femoji)

        if self._sidebar_collapsed:
            badge = FolderBadge(fcolor, femoji, size=42)
            badge.set_margin_top(6)
            badge.set_margin_bottom(6)
            badge.set_halign(Gtk.Align.CENTER)
            row.set_child(badge)
            row.set_tooltip_text(
                f"{name}\n{n} {plural}\nRight-click for options · drop playlists")
            self.playlist_list.append(row)
            if expanded:
                for pid, pname, count in children:
                    ppl = "song" if count == 1 else "songs"
                    self._add_playlist_row(
                        pname, f"{count} {ppl} · local", "local",
                        (pid, pname), covers.get(pid) or [], indent=0)
            return

        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        box.set_margin_top(4)
        box.set_margin_bottom(4)
        box.set_margin_start(6)
        chevron = Gtk.Label(label="▾" if expanded else "▸")
        chevron.add_css_class("dim-label")
        chevron.set_width_chars(1)
        box.append(chevron)
        icon = FolderBadge(fcolor, femoji, size=28)
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
        row.set_tooltip_text(
            "Click to expand · right-click for options · drag playlists here")
        self.playlist_list.append(row)

        if expanded:
            for pid, pname, count in children:
                ppl = "song" if count == 1 else "songs"
                self._add_playlist_row(
                    pname, f"{count} {ppl} · local", "local",
                    (pid, pname), covers.get(pid) or [], indent=1)

    @staticmethod
    def _set_row_cover(art, cover) -> None:
        if isinstance(cover, (list, tuple)):
            art.set_urls(list(cover))
        else:
            art.set_url(cover or "")

    def _add_playlist_row(self, title: str, subtitle: str,
                          kind: str, ref, cover="",
                          indent: int = 0) -> None:
        from gi.repository import Pango

        from .widgets import CoverArt

        row = Gtk.ListBoxRow()
        row.kind = kind
        row.ref = ref

        if kind == "local":
            pid = ref[0] if isinstance(ref, tuple) else ref
            self._install_playlist_drag(row, int(pid))
            # Right-click → move to folder
            gesture = Gtk.GestureClick()
            gesture.set_button(3)
            gesture.connect(
                "pressed",
                lambda _g, _n, _x, _y, p=int(pid): self.choose_folder_for(p))
            row.add_controller(gesture)

        if self._sidebar_collapsed:
            art = CoverArt(52, icon="view-list-symbolic")
            self._set_row_cover(art, cover)
            art.set_margin_top(4)
            art.set_margin_bottom(4)
            art.set_halign(Gtk.Align.CENTER)
            row.set_child(art)
            row.set_tooltip_text(f"{title}\n{subtitle}\nDrag onto a folder")
            self.playlist_list.append(row)
            return

        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        box.set_margin_top(4)
        box.set_margin_bottom(4)
        box.set_margin_start(6 + (18 * indent))
        art = CoverArt(38, icon="view-list-symbolic")
        self._set_row_cover(art, cover)
        art.set_valign(Gtk.Align.CENTER)
        box.append(art)
        text_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
        text_box.set_valign(Gtk.Align.CENTER)
        text_box.set_hexpand(True)
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
        row.set_tooltip_text(f"{title}\nDrag onto a folder · right-click to move")
        self.playlist_list.append(row)

    def _install_playlist_drag(self, row: Gtk.ListBoxRow, playlist_id: int) -> None:
        source = Gtk.DragSource()
        source.set_actions(Gdk.DragAction.MOVE)
        source.connect(
            "prepare",
            lambda _s, _x, _y, pid=playlist_id:
                Gdk.ContentProvider.new_for_value(f"playlist:{pid}"))
        row.add_controller(source)

    def _install_folder_context_menu(
            self, widget: Gtk.Widget, folder_id: int, name: str,
            color: str, emoji: str) -> None:
        """Right-click (or long-press) menu on a folder row."""
        gesture = Gtk.GestureClick()
        gesture.set_button(3)

        def on_press(_g, _n, x, y) -> None:
            self.show_folder_menu(
                widget, folder_id, name, color, emoji, x=x, y=y)

        gesture.connect("pressed", on_press)
        widget.add_controller(gesture)

        # Long-press for touchpads / touch screens.
        long_press = Gtk.GestureLongPress()
        long_press.connect(
            "pressed",
            lambda _g, x, y: self.show_folder_menu(
                widget, folder_id, name, color, emoji, x=x, y=y))
        widget.add_controller(long_press)

    def show_folder_menu(self, parent: Gtk.Widget, folder_id: int,
                         name: str, color: str, emoji: str,
                         x: float = 0, y: float = 0) -> None:
        """Popover: style, rename, delete."""
        pop = Gtk.Popover()
        pop.set_has_arrow(True)
        pop.set_autohide(True)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        box.set_margin_top(6)
        box.set_margin_bottom(6)
        box.set_margin_start(6)
        box.set_margin_end(6)

        head = Gtk.Label(label=name)
        head.add_css_class("heading")
        head.set_margin_bottom(4)
        box.append(head)

        def item(label: str, cb) -> None:
            btn = Gtk.Button(label=label)
            btn.add_css_class("flat")
            btn.set_halign(Gtk.Align.FILL)
            btn.connect("clicked", lambda *_: (cb(), pop.popdown()))
            box.append(btn)

        item("Change color & emoji…",
             lambda: self.choose_folder_style(folder_id, color, emoji))
        item("Rename…", lambda: self.prompt_text(
            "Rename Folder", "New name",
            lambda n: (self.library.rename_folder(folder_id, n),
                       self.reload_sidebar_playlists(),
                       self.pages["playlists"].refresh(),
                       self.toast(f'Renamed to "{n}"')),
            accept_label="Rename"))
        item("Delete folder", lambda: (
            self.library.delete_folder(folder_id),
            self.reload_sidebar_playlists(),
            self.pages["playlists"].refresh(),
            self.toast("Folder deleted — playlists kept")))

        pop.set_child(box)
        pop.set_parent(parent)
        # Point the popover at the click location when possible.
        try:
            rect = Gdk.Rectangle()
            rect.x = int(x)
            rect.y = int(y)
            rect.width = 1
            rect.height = 1
            pop.set_pointing_to(rect)
        except Exception:  # noqa: BLE001
            pass
        pop.popup()

    def _install_folder_drop(self, row: Gtk.ListBoxRow, folder_id: int) -> None:
        target = Gtk.DropTarget.new(GObject.TYPE_STRING, Gdk.DragAction.MOVE)
        target.connect(
            "drop",
            lambda _t, value, _x, _y, fid=folder_id:
                self._on_playlist_dropped(value, fid))
        target.connect(
            "enter",
            lambda *_a: (row.add_css_class("riff-drop-hover"),
                         Gdk.DragAction.MOVE)[1])
        target.connect(
            "leave",
            lambda *_a: row.remove_css_class("riff-drop-hover"))
        row.add_controller(target)

    def _on_playlist_dropped(self, value, folder_id: int | None) -> bool:
        try:
            raw = str(value)
            if raw.startswith("playlist:"):
                pid = int(raw.split(":", 1)[1])
            else:
                pid = int(raw)
        except (TypeError, ValueError):
            return False
        self.library.set_playlist_folder(pid, folder_id)
        if folder_id is not None:
            self._expanded_folders.add(folder_id)
            config.settings.set(
                "expanded_folders", sorted(self._expanded_folders))
        self.reload_sidebar_playlists()
        page = self.pages.get("playlists")
        if page is not None and hasattr(page, "refresh"):
            page.refresh()
        self.toast("Moved to folder" if folder_id is not None else "Moved to root")
        return True

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
        self._show_right_panel("queue" if btn.get_active() else None)

    def _on_now_toggle(self, btn) -> None:
        self._show_right_panel("now" if btn.get_active() else None)

    def _show_right_panel(self, which: str | None) -> None:
        if self._right_sync:
            return
        self._right_sync = True
        try:
            bar = self.player_bar
            if which is None:
                if not (bar.queue_btn.get_active()
                        or bar.now_btn.get_active()):
                    self.queue_split.set_show_sidebar(False)
            else:
                (bar.now_btn if which == "queue" else
                 bar.queue_btn).set_active(False)
                self.right_stack.set_visible_child_name(which)
                self.queue_split.set_show_sidebar(True)
        finally:
            self._right_sync = False

    def toggle_now_playing(self) -> None:
        btn = self.player_bar.now_btn
        btn.set_active(not btn.get_active())

    def set_video_mode(self, enabled: bool) -> None:
        """Play video in the cover-art slot (or restore the thumbnail)."""
        self.service.set_video_mode(bool(enabled))

    def toggle_video_mode(self) -> None:
        self.set_video_mode(not self.service.video_mode)

    def _on_video_mode(self, enabled: bool) -> None:
        if hasattr(self.player_bar, "set_video_active"):
            self.player_bar.set_video_active(enabled)

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
                self.toast(f'Added to "{name}"'),
                self.reload_sidebar_playlists()))))
        box.append(new_btn)
        dialog.set_extra_child(box)
        dialog.add_response("cancel", "Cancel")
        dialog.present(self)

    def download_track(self, track: Track) -> None:
        self.toast(f'Downloading "{track.title}"…')

        def done(path: str) -> None:
            self.toast(f'Downloaded "{track.title}"')

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
        self._folder_style_dialog(title="New Folder", accept_label="Create")

    def choose_folder_style(self, folder_id: int, color: str = "",
                            emoji: str = "") -> None:
        """Edit color + emoji for an existing folder."""
        self._folder_style_dialog(
            title="Folder look",
            accept_label="Save",
            initial_name="",  # name not edited here
            initial_color=color or self.library.DEFAULT_FOLDER_COLOR,
            initial_emoji=emoji or self.library.DEFAULT_FOLDER_EMOJI,
            name_required=False,
            on_accept=lambda _name, col, emo: (
                self.library.set_folder_style(
                    folder_id, color=col, emoji=emo),
                self.reload_sidebar_playlists(),
                self.pages["playlists"].refresh(),
                self.toast("Folder look updated")))

    # Back-compat name used by older call sites.
    def choose_folder_icon(self, folder_id: int, current: str = "") -> None:
        self.choose_folder_style(folder_id)

    def _folder_style_dialog(
            self, title: str = "New Folder", accept_label: str = "Create",
            initial_name: str = "", initial_color: str | None = None,
            initial_emoji: str | None = None, name_required: bool = True,
            on_accept=None) -> None:
        """Name (optional) + color swatches + emoji for a folder badge."""
        from .folder_badge import (
            DEFAULT_FOLDER_COLOR,
            DEFAULT_FOLDER_EMOJI,
            FOLDER_COLORS,
            FOLDER_EMOJI_PRESETS,
            FolderBadge,
        )

        style = {
            "color": initial_color or DEFAULT_FOLDER_COLOR,
            "emoji": initial_emoji or DEFAULT_FOLDER_EMOJI,
        }
        dialog = Adw.AlertDialog.new(
            title, "Pick a folder color and an emoji or symbol")
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        box.set_margin_top(6)

        preview_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        preview_row.set_halign(Gtk.Align.CENTER)
        badge = FolderBadge(style["color"], style["emoji"], size=48)
        preview_row.append(badge)
        preview_label = Gtk.Label(label=initial_name or "Folder")
        preview_label.add_css_class("heading")
        preview_row.append(preview_label)
        box.append(preview_row)

        entry = None
        if name_required:
            entry = Gtk.Entry()
            entry.set_placeholder_text("Folder name")
            entry.set_text(initial_name)
            box.append(entry)

            def on_name_changed(e: Gtk.Entry) -> None:
                preview_label.set_label(e.get_text().strip() or "Folder")

            entry.connect("changed", on_name_changed)

        # Colors
        color_label = Gtk.Label(label="Color")
        color_label.set_xalign(0.0)
        color_label.add_css_class("caption")
        color_label.add_css_class("dim-label")
        box.append(color_label)
        color_flow = Gtk.FlowBox()
        color_flow.set_selection_mode(Gtk.SelectionMode.NONE)
        color_flow.set_max_children_per_line(6)
        color_flow.set_column_spacing(6)
        color_flow.set_row_spacing(6)

        def paint_preview() -> None:
            badge.set_style(style["color"], style["emoji"])

        def pick_color(hex_color: str) -> None:
            style["color"] = hex_color
            paint_preview()

        def _swatch(hex_color: str) -> Gtk.Button:
            btn = Gtk.Button()
            btn.set_tooltip_text(hex_color)
            btn.add_css_class("flat")
            btn.set_size_request(34, 34)
            da = Gtk.DrawingArea()
            da.set_content_width(26)
            da.set_content_height(26)

            def draw(_a, cr, w, h, c=hex_color):
                c = c.lstrip("#")
                cr.set_source_rgb(
                    int(c[0:2], 16) / 255,
                    int(c[2:4], 16) / 255,
                    int(c[4:6], 16) / 255)
                cr.arc(w / 2, h / 2, min(w, h) / 2 - 1, 0, 6.2832)
                cr.fill()

            da.set_draw_func(draw)
            btn.set_child(da)
            btn.connect("clicked", lambda _b, c=hex_color: pick_color(c))
            return btn

        for hex_color, cname in FOLDER_COLORS:
            sw = _swatch(hex_color)
            sw.set_tooltip_text(cname)
            color_flow.append(sw)
        box.append(color_flow)

        # Emoji / symbol
        emo_label = Gtk.Label(label="Emoji or symbol")
        emo_label.set_xalign(0.0)
        emo_label.add_css_class("caption")
        emo_label.add_css_class("dim-label")
        box.append(emo_label)
        emo_entry = Gtk.Entry()
        emo_entry.set_placeholder_text("Type any emoji…")
        emo_entry.set_text(style["emoji"])
        emo_entry.set_max_length(8)

        def on_emo_changed(e: Gtk.Entry) -> None:
            style["emoji"] = e.get_text().strip() or DEFAULT_FOLDER_EMOJI
            paint_preview()

        emo_entry.connect("changed", on_emo_changed)
        box.append(emo_entry)

        emo_flow = Gtk.FlowBox()
        emo_flow.set_selection_mode(Gtk.SelectionMode.NONE)
        emo_flow.set_max_children_per_line(8)
        emo_flow.set_column_spacing(4)
        emo_flow.set_row_spacing(4)
        for emo in FOLDER_EMOJI_PRESETS:
            btn = Gtk.Button(label=emo)
            btn.add_css_class("flat")
            btn.connect("clicked", lambda _b, e=emo: (
                style.update(emoji=e),
                emo_entry.set_text(e),
                paint_preview()))
            emo_flow.append(btn)
        box.append(emo_flow)

        dialog.set_extra_child(box)
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("ok", accept_label)
        dialog.set_response_appearance("ok", Adw.ResponseAppearance.SUGGESTED)
        dialog.set_default_response("ok")

        def on_response(_d, response: str) -> None:
            if response != "ok":
                return
            name = entry.get_text().strip() if entry is not None else ""
            if name_required and not name:
                return
            if on_accept is not None:
                on_accept(name, style["color"], style["emoji"])
                return
            self.library.create_folder(
                name, color=style["color"], emoji=style["emoji"])
            self.reload_sidebar_playlists()
            page = self.pages.get("playlists")
            if page is not None and hasattr(page, "refresh"):
                page.refresh()
            self.toast(f'Folder "{name}" created')

        dialog.connect("response", on_response)
        if entry is not None:
            entry.connect("activate", lambda *_: (
                on_response(dialog, "ok"), dialog.close()))
        dialog.present(self)

    def choose_folder_for(self, playlist_id: int) -> None:
        """Move a local playlist into a folder (or root) — button-based picker."""
        from .folder_badge import FolderBadge

        folders = self.library.folders()
        dialog = Adw.AlertDialog.new(
            "Move to folder",
            "Choose a folder, or put the playlist back at the root.")
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        box.set_margin_top(6)

        def add_option(folder_id: int | None, label: str,
                       color: str | None = None, emoji: str | None = None):
            btn = Gtk.Button()
            btn.add_css_class("pill")
            btn.set_halign(Gtk.Align.FILL)
            if color is not None:
                row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
                row.append(FolderBadge(color, emoji or "🎵", size=22))
                row.append(Gtk.Label(label=label))
                btn.set_child(row)
            else:
                btn.set_label(label)
            btn.connect("clicked", lambda _b, fid=folder_id: (
                self.library.set_playlist_folder(playlist_id, fid),
                self.toast(
                    "Moved to folder" if fid is not None else "Moved to root"),
                self.reload_sidebar_playlists(),
                self.pages["playlists"].refresh(),
                dialog.close()))
            box.append(btn)

        add_option(None, "No folder (root)")
        for fid, fname, fcolor, femoji in folders:
            add_option(fid, fname, fcolor, femoji)
        if not folders:
            hint = Gtk.Label(
                label="Create a folder from the sidebar ＋ menu first")
            hint.add_css_class("dim-label")
            hint.set_wrap(True)
            box.append(hint)
        dialog.set_extra_child(box)
        dialog.add_response("cancel", "Cancel")
        dialog.present(self)


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
            ("Now Playing panel", "Alt Shift N"),
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
        local_ready = local_ai.status().ready

        if provider == "local":
            if not local_ready:
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

        # anthropic (default)
        key = str(config.settings.get("anthropic_api_key", "") or "")
        if key:
            return {"provider": "anthropic", "key": key}
        # Seamless Home: fall back to on-device model when no cloud key.
        if local_ready:
            return {"provider": "local"}
        if interactive:
            self.toast("Add your Anthropic API key in Settings to use AI Mix")
            self.show_settings()
        return None

    def start_ai_mix(self) -> None:
        self.refresh_ai_mix(interactive=True)

    def try_auto_for_you(self) -> bool:
        """Start a silent AI Mix for Home if possible. True when a job starts."""
        import datetime

        if not config.settings.get("ai_mix_auto_refresh", True):
            return False
        if not self.library.recent(1) and not self.library.favorites():
            return False
        cfg = self._ai_provider_config(interactive=False)
        if cfg is None:
            return False
        today = datetime.date.today().isoformat()
        # Refresh when never done today, or when the mix playlist is empty.
        pid = self.library.find_playlist(AI_MIX_PLAYLIST)
        has_tracks = bool(pid and self.library.playlist_tracks(pid))
        if (config.settings.get("ai_mix_last_refresh", "") == today
                and has_tracks):
            return False
        log.info("auto For you / AI Mix (silent)")
        self.refresh_ai_mix(interactive=False)
        return True

    def maybe_auto_refresh_ai_mix(self) -> None:
        """Daily background refresh (also used shortly after app start)."""
        self.try_auto_for_you()

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
            home = self.pages.get("home")
            if home is not None and hasattr(home, "on_for_you_ready"):
                home.on_for_you_ready(tracks[:12], source="ai")
            if interactive:
                self.service.play_tracks(tracks)
                dialog.close()
                self.toast(
                    f"AI Mix ready: {len(tracks)} songs — on Home under For you")
            else:
                log.info("silent AI Mix ready (%d songs)", len(tracks))

        def fail(exc: Exception) -> None:
            home = self.pages.get("home")
            if home is not None and hasattr(home, "on_for_you_ready"):
                # Empty list → Home falls back to radio picks (no AI retry loop).
                home.on_for_you_ready([], source="ai")
            if not interactive:
                log.warning("background AI Mix refresh failed: %s", exc)
                return
            spinner.stop()
            spinner.set_visible(False)
            status_label.set_label(f"AI Mix failed:\n{exc}")
            status_label.add_css_class("error")

        run_async(work, done, fail, name="riff-ai-mix")

    # -- Spotify import --------------------------------------------------------

    # Well-known Spotify editorial playlists, one click away. Anything else
    # can be pasted as a link. Region-locked entries fail gracefully.
    SPOTIFY_PICKS = [
        ("Today's Top Hits", "37i9dQZF1DXcBWIGoYBM5M"),
        ("RapCaviar", "37i9dQZF1DX0XUsuxWHRQd"),
        ("Hot Hits Deutschland", "37i9dQZF1DX4jP4eebSWR9"),
        ("Rock Classics", "37i9dQZF1DWXRqgorJj26U"),
        ("Beast Mode", "37i9dQZF1DX76Wlfdnj7AP"),
        ("Peaceful Piano", "37i9dQZF1DX4sWSpwq3LiO"),
        ("lofi beats", "37i9dQZF1DWWQRwui0ExPn"),
    ]

    def import_spotify_dialog(self) -> None:
        from ..core import spotify

        dialog = Adw.Dialog.new()
        dialog.set_title("Import from Spotify")
        dialog.set_content_width(460)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        box.append(Adw.HeaderBar())

        hint = Gtk.Label(label=(
            "Paste a link to any public Spotify playlist or album. Riff "
            "reads its songs from Spotify and matches them on YouTube "
            "Music — no Spotify account needed."))
        hint.set_wrap(True)
        hint.set_margin_start(20)
        hint.set_margin_end(20)
        hint.add_css_class("dim-label")
        box.append(hint)

        entry = Gtk.Entry()
        entry.set_placeholder_text("https://open.spotify.com/playlist/…")
        entry.set_margin_start(20)
        entry.set_margin_end(20)
        box.append(entry)

        import_btn = Gtk.Button.new_with_label("Import")
        import_btn.add_css_class("suggested-action")
        import_btn.add_css_class("pill")
        import_btn.set_halign(Gtk.Align.CENTER)
        box.append(import_btn)

        def go(*_a) -> None:
            parsed = spotify.parse_spotify_url(entry.get_text())
            if not parsed:
                self.toast(
                    "That doesn't look like a Spotify playlist/album link")
                return
            dialog.close()
            self._run_spotify_import(*parsed)

        entry.connect("activate", go)
        import_btn.connect("clicked", go)

        picks_title = Gtk.Label(label="Or grab a Spotify classic:")
        picks_title.add_css_class("dim-label")
        picks_title.add_css_class("caption")
        box.append(picks_title)
        picks = Gtk.FlowBox()
        picks.set_selection_mode(Gtk.SelectionMode.NONE)
        picks.set_max_children_per_line(3)
        picks.set_margin_start(14)
        picks.set_margin_end(14)
        picks.set_margin_bottom(20)
        for name, pid in self.SPOTIFY_PICKS:
            b = Gtk.Button.new_with_label(name)
            b.add_css_class("pill")
            b.connect(
                "clicked",
                lambda _b, p=pid: (dialog.close(),
                                   self._run_spotify_import("playlist", p)))
            picks.append(b)
        box.append(picks)

        dialog.set_child(box)
        dialog.present(self)
        entry.grab_focus()

    def _run_spotify_import(self, kind: str, item_id: str) -> None:
        from ..core import spotify

        dialog = Adw.Dialog.new()
        dialog.set_title("Spotify import")
        dialog.set_content_width(380)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        box.append(Adw.HeaderBar())
        spinner = Gtk.Spinner()
        spinner.set_size_request(32, 32)
        spinner.set_halign(Gtk.Align.CENTER)
        spinner.start()
        box.append(spinner)
        status_label = Gtk.Label(label="Reading the playlist from Spotify…")
        status_label.set_wrap(True)
        status_label.set_margin_start(20)
        status_label.set_margin_end(20)
        status_label.set_margin_bottom(24)
        box.append(status_label)
        dialog.set_child(box)
        dialog.present(self)

        def set_status(text: str) -> None:
            GLib.idle_add(lambda: (status_label.set_label(text), False)[1])

        def work():
            sp = spotify.fetch_best(
                kind, item_id,
                str(config.settings.get("spotify_client_id", "") or ""),
                str(config.settings.get("spotify_client_secret", "") or ""))
            set_status(f"“{sp.name}” — matching {len(sp.tracks)} songs "
                       "on YouTube Music…")

            def prog(done_n: int, total: int) -> None:
                set_status(f"“{sp.name}” — matching songs… {done_n}/{total}")

            matched, missed = spotify.match_on_ytmusic(
                self.api, sp.tracks, progress=prog)
            if not matched:
                raise RuntimeError(
                    "None of the songs could be matched on YouTube Music")
            pid = self.library.find_playlist(sp.name)
            if pid is None:
                pid = self.library.create_playlist(sp.name)
            self.library.replace_playlist_tracks(pid, matched)
            return sp.name, pid, len(matched), len(missed)

        def done(result) -> None:
            name, pid, n_ok, n_miss = result
            dialog.close()
            self.reload_sidebar_playlists()
            msg = f"Imported “{name}”: {n_ok} songs"
            if n_miss:
                msg += f" ({n_miss} not found on YouTube Music)"
            self.toast(msg)
            self.open_local_playlist(pid, name)

        def fail(exc: Exception) -> None:
            spinner.stop()
            spinner.set_visible(False)
            status_label.set_label(f"Import failed:\n{exc}")
            status_label.add_css_class("error")

        run_async(work, done, fail, name="riff-spotify-import")

    def show_about(self) -> None:
        from .. import __version__

        about = Adw.AboutDialog.new()
        about.set_application_name(APP_NAME)
        about.set_application_icon("io.github.aimdi.Riff")
        about.set_version(__version__)
        about.set_comments("A native YouTube Music player for Linux")
        about.set_website("https://github.com/Aimdi/Riff")
        about.set_license_type(Gtk.License.GPL_3_0)
        about.present(self)

    def _on_close(self, _win) -> bool:
        w, h = self.get_default_size()
        config.settings.set("window_width", w)
        config.settings.set("window_height", h)
        return False



    # -- shortcuts overlay -------------------------------------------------------

