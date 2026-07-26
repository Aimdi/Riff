"""Main application window: sidebar navigation, content stack, player bar."""

from __future__ import annotations

import logging

from gi.repository import Adw, Gdk, Gio, GLib, GObject, Gtk

log = logging.getLogger("riff.window")

from .. import APP_NAME, config
from ..core.models import Track
from ..util import run_async
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
from .full_player import FullPlayer
from .audiobooks import AudiobooksPage
from .cloud import CloudPage
from .library_hub import AlbumsPage, ArtistsPage, LibraryHub
from .player_bar import PlayerBar
from .podcasts import PodcastsPage
from .seeker import SeekerPage
from .soulsync import SoulSyncPage
from .torrents import TorrentsPage

CSS = b"""
/* Riff Mobile surface language - void black + elevated green */
.riff-full-player {
    background-color: #000000;
}
.riff-full-player-backdrop {
    opacity: 0.68;
}
.riff-full-player-scrim {
    background: linear-gradient(
        180deg,
        alpha(#000000, 0.28) 0%,
        alpha(#000000, 0.55) 40%,
        alpha(#000000, 0.92) 100%);
}
.riff-lyric-word {
    opacity: 0.42;
}
.riff-lyric-word-done {
    opacity: 0.78;
}
.riff-lyric-word-active {
    opacity: 1.0;
    color: @accent_color;
    font-weight: 700;
}
.riff-lyrics-source {
    font-size: 0.85em;
    opacity: 0.65;
}
.riff-full-player-art {
    border-radius: 12px;
    box-shadow: 0 18px 48px alpha(#000000, 0.55);
}
.riff-full-player-brand {
    letter-spacing: -0.03em;
    font-weight: 800;
}
.riff-full-lyrics {
    min-height: 220px;
}
.riff-full-lyrics-line {
    font-size: 1.15em;
    opacity: 0.45;
    margin: 4px 0;
}
.riff-full-lyrics-line-active {
    opacity: 1.0;
    color: @accent_color;
    font-weight: 700;
}
button.riff-full-play {
    min-width: 64px;
    min-height: 64px;
}
.riff-mini-strip {
    background-color: alpha(#16181c, 0.96);
    border-top: 1px solid alpha(#ffffff, 0.08);
}
.riff-mini-progress {
    min-height: 2px;
    padding: 0;
    margin: 0;
    opacity: 0.9;
}
.riff-mini-progress trough,
.riff-mini-progress slider {
    min-height: 2px;
    border-radius: 0;
}
.riff-mini-progress slider {
    min-width: 0;
    background: transparent;
    border: none;
    box-shadow: none;
}
.riff-search-fab {
    min-width: 52px;
    min-height: 52px;
    border-radius: 16px;
    box-shadow: 0 8px 24px alpha(#000000, 0.45);
}
.riff-mobile-rail {
    background-color: #000000;
}
.riff-mobile-rail row {
    border-radius: 0;
    padding: 6px 0;
    min-height: 64px;
}
.riff-mobile-rail row:selected,
.riff-mobile-rail row:selected:hover {
    background-color: transparent;
    box-shadow: inset 3px 0 0 @accent_bg_color;
}
.riff-mobile-rail row:selected .riff-rail-glyph {
    background-color: alpha(@accent_bg_color, 0.28);
    border-radius: 12px;
    padding: 6px;
}
.riff-rail-label {
    font-size: 0.62em;
    font-weight: 700;
    letter-spacing: 0.04em;
}
.riff-brand-hero {
    font-size: 2.1em;
    font-weight: 800;
    letter-spacing: -0.04em;
}
.riff-zone-label {
    font-size: 0.72em;
    font-weight: 700;
    letter-spacing: 0.12em;
    opacity: 0.55;
    margin-top: 8px;
}
.riff-wave-card {
    background-color: #16181c;
    border-radius: 16px;
    padding: 14px;
}
.riff-wave-play {
    min-width: 48px;
    min-height: 48px;
    border-radius: 9999px;
}
.riff-discover-list {
    background: transparent;
}
.riff-discover-list row {
    border-radius: 10px;
    margin: 1px 0;
}
.riff-discover-list row:hover {
    background-color: alpha(#ffffff, 0.06);
}
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
/* Home shortcut tiles - elevated chips, green signature (not purple). */
button.riff-shortcut {
    background-color: alpha(#ffffff, 0.06);
    border-radius: 12px;
    padding: 0;
    min-height: 56px;
    transition: background-color 120ms ease;
}
button.riff-shortcut:hover {
    background-color: alpha(#ffffff, 0.12);
}
.riff-liked-tile {
    background: linear-gradient(135deg, #0a7a3a, #1db954);
    border-radius: 10px;
    color: #ffffff;
    font-size: 20px;
    font-weight: 700;
}
.riff-tile-recent {
    background: linear-gradient(135deg, #1f6feb, #58a6ff);
}
.riff-tile-fresh {
    background: linear-gradient(135deg, #0d9488, #2dd4bf);
}
.riff-tile-rediscover {
    background: linear-gradient(135deg, #b45309, #f59e0b);
}
.riff-tile-radar {
    background: linear-gradient(135deg, #be123c, #fb7185);
}
.riff-tile-downloads {
    background: linear-gradient(135deg, #334155, #64748b);
}
.riff-greeting {
    opacity: 0.62;
    font-weight: 500;
}
button.riff-wave-mood {
    background-color: alpha(#ffffff, 0.06);
}
button.riff-wave-mood:checked {
    background-color: @accent_bg_color;
    color: @accent_fg_color;
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
    ("explore", "Explore", "web-browser-symbolic"),
    ("search", "Search", "system-search-symbolic"),
    ("favorites", "Favorites", "emblem-favorite-symbolic"),
    ("podcasts", "Podcasts", "emblem-music-symbolic"),
    ("audiobooks", "Audiobooks", "media-optical-symbolic"),
    ("cloud", "Cloud", "network-server-symbolic"),
    ("soulsync", "SoulSync", "folder-download-symbolic"),
    ("torrents", "Torrents", "folder-download-symbolic"),
    ("seeker", "Seeker", "network-server-symbolic"),
    ("history", "History", "document-open-recent-symbolic"),
    ("stats", "Stats", "riff-stats-symbolic"),
    ("playlists", "Playlists", "view-list-symbolic"),
    ("local", "Local Files", "folder-music-symbolic"),
    ("downloads", "Downloads", "folder-download-symbolic"),
    ("dislikes", "Disliked", "action-unavailable-symbolic"),
]

# Riff Mobile primary rail (Search is a FAB; More holds History/Local/…).
# Matches mobile side_nav: Home · Songs · Podcasts · Audiobooks · …
# (Playlists/Albums/Artists stay reachable; Settings via app menu).
MOBILE_SIDEBAR_ITEMS = [
    ("home", "Home", "user-home-symbolic"),
    ("favorites", "Songs", "emblem-favorite-symbolic"),
    ("podcasts", "Podcasts", "emblem-music-symbolic"),
    ("audiobooks", "Audiobooks", "media-optical-symbolic"),
    ("playlists", "Playlists", "view-list-symbolic"),
    ("albums", "Albums", "media-optical-symbolic"),
    ("artists", "Artists", "avatar-default-symbolic"),
    ("library", "More", "open-menu-symbolic"),
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
        # Required when using Adw.Breakpoint (HIG: no implicit min size).
        self.set_size_request(360, 400)
        self._load_css()
        self._mobile_shell = (
            str(config.settings.get("shell_layout", "mobile")) == "mobile")
        self._nav_items = (
            MOBILE_SIDEBAR_ITEMS if self._mobile_shell else SIDEBAR_ITEMS)

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
            "library": LibraryHub(self),
            "albums": AlbumsPage(self),
            "artists": ArtistsPage(self),
            "podcasts": PodcastsPage(self),
            "audiobooks": AudiobooksPage(self),
            "cloud": CloudPage(self),
            "soulsync": SoulSyncPage(self),
            "torrents": TorrentsPage(self),
            "seeker": SeekerPage(self),
        }
        self.stack = Gtk.Stack()
        self.stack.set_vexpand(True)
        self.stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        self.stack.set_transition_duration(140)
        for name, page in self.pages.items():
            self.stack.add_named(page, name)

        # navigation view wraps the stack so detail pages can be pushed ----
        self.nav = Adw.NavigationView()
        root_page = Adw.NavigationPage.new(self.stack, APP_NAME)
        root_page.set_tag("root")
        self.nav.add(root_page)

        # header bar (lives in ToolbarView top — full window width) ----------
        header = Adw.HeaderBar()
        title = Adw.WindowTitle.new(APP_NAME, "")
        header.set_title_widget(title)
        # App-level actions only; lyrics / AI Mix live on player bar / Home.
        menu = Gio.Menu()
        menu.append("Import from Spotify…", "win.spotify-import")
        menu.append("Generate AI Mix", "win.ai-mix")
        menu.append("Keyboard Shortcuts", "win.shortcuts")
        menu.append("Preferences", "win.settings")
        menu.append("About Riff", "win.about")
        menu_btn = Gtk.MenuButton()
        menu_btn.set_child(iconutil.image("open-menu-symbolic"))
        menu_btn.set_menu_model(menu)
        menu_btn.set_tooltip_text("Menu")
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

        # Narrow-width: reveal sidebar overlay from the header.
        self._sidebar_reveal_btn = Gtk.ToggleButton()
        iconutil.set_button(self._sidebar_reveal_btn, "view-list-symbolic")
        self._sidebar_reveal_btn.add_css_class("flat")
        self._sidebar_reveal_btn.set_tooltip_text("Show navigation")
        self._sidebar_reveal_btn.set_visible(False)
        header.pack_start(self._sidebar_reveal_btn)

        # sidebar (collapsible into a Spotify-style icon rail) ----------------
        self._sidebar_collapsed = bool(
            config.settings.get("sidebar_collapsed", False))
        self._narrow = False

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
        if self._mobile_shell:
            self.sidebar_list.add_css_class("riff-mobile-rail")
        self.sidebar_list.connect("row-activated", self._on_sidebar)
        self._nav_rows = []
        for name, label, icon in self._nav_items:
            row = Gtk.ListBoxRow()
            row.item_name = name
            if self._mobile_shell:
                box = Gtk.Box(
                    orientation=Gtk.Orientation.VERTICAL, spacing=4)
                box.set_margin_top(10)
                box.set_margin_bottom(10)
                box.set_halign(Gtk.Align.CENTER)
                glyph = Gtk.Box()
                glyph.add_css_class("riff-rail-glyph")
                glyph.set_halign(Gtk.Align.CENTER)
                glyph.append(iconutil.image(icon, 18))
                box.append(glyph)
                text = Gtk.Label(label=label)
                text.add_css_class("riff-rail-label")
                box.append(text)
            else:
                box = Gtk.Box(
                    orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
                box.set_margin_top(8)
                box.set_margin_bottom(8)
                box.set_margin_start(8)
                # Bundled SVGs — system themes leave some blank/invisible.
                box.append(iconutil.image(icon))
                text = Gtk.Label(label=label)
                box.append(text)
            row.set_child(box)
            row.set_tooltip_text(label)
            self._nav_rows.append((row, box, text, label))
            self.sidebar_list.append(row)

        sidebar_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        if self._mobile_shell:
            sidebar_box.add_css_class("riff-mobile-rail")
            # Brand mark at top of the rail (Riff Mobile identity).
            brand = Gtk.Label(label="Riff")
            brand.add_css_class("heading")
            brand.set_margin_top(14)
            brand.set_margin_bottom(8)
            brand.set_halign(Gtk.Align.CENTER)
            sidebar_box.append(brand)
        else:
            sidebar_box.append(header_row)
        sidebar_box.append(self.sidebar_list)

        # playlists section ---------------------------------------------------
        self._pl_separator = Gtk.Separator(margin_top=10, margin_bottom=4)
        sidebar_box.append(self._pl_separator)
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
        if self._mobile_shell:
            # Playlists live on their own tab (Riff Mobile); keep rail clean.
            self._pl_separator.set_visible(False)
            self._new_pl.set_visible(False)
            self.playlist_list.set_visible(False)
            self._collapse_btn.set_visible(False)
            self._app_title.set_visible(False)

        sidebar_scroll = Gtk.ScrolledWindow()
        sidebar_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        sidebar_scroll.set_vexpand(True)
        sidebar_scroll.set_child(sidebar_box)

        # Left nav: OverlaySplitView (collapses to overlay under Breakpoint).
        self._nav_split = Adw.OverlaySplitView()
        self._nav_split.set_sidebar(sidebar_scroll)
        self._nav_split.set_content(self.nav)
        self._nav_split.set_enable_hide_gesture(True)
        self._nav_split.set_enable_show_gesture(True)
        self._apply_sidebar_mode()

        # right panel: single Now Playing surface (Queue + Lyrics tabs) ----
        from .now_playing import NowPlayingPanel

        self.now_playing_panel = NowPlayingPanel(self)
        self.queue_split = Adw.OverlaySplitView()
        self.queue_split.set_sidebar_position(Gtk.PackType.END)
        self.queue_split.set_sidebar(self.now_playing_panel)
        self.queue_split.set_content(self._nav_split)
        self.queue_split.set_show_sidebar(False)
        self.queue_split.set_min_sidebar_width(300)
        self.queue_split.set_max_sidebar_width(360)
        self.queue_split.set_enable_hide_gesture(True)

        # player bar + toasts (video plays inside the cover-art slot)
        self.player_bar = PlayerBar(self)
        self._right_sync = False
        self.player_bar.queue_btn.connect("toggled", self._on_queue_toggle)
        self.player_bar.now_btn.connect("toggled", self._on_now_toggle)
        if self._mobile_shell:
            self.player_bar.set_mobile_compact(True)

        # Content area — mobile adds a Search FAB over the split view.
        content = self.queue_split
        if self._mobile_shell:
            overlay = Gtk.Overlay()
            overlay.set_child(self.queue_split)
            fab = Gtk.Button()
            fab.add_css_class("suggested-action")
            fab.add_css_class("riff-search-fab")
            fab.set_child(iconutil.image("system-search-symbolic", 20))
            fab.set_tooltip_text("Search")
            fab.set_halign(Gtk.Align.END)
            fab.set_valign(Gtk.Align.END)
            fab.set_margin_end(18)
            # Clear the mini-player strip so Search isn't buried under chrome.
            fab.set_margin_bottom(86)
            fab.connect("clicked", lambda *_: self.goto("search"))
            overlay.add_overlay(fab)
            content = overlay

        # Adw.ToolbarView: header top, player bottom — proper chrome/backdrop.
        self.toolbar = Adw.ToolbarView()
        self.toolbar.add_top_bar(header)
        self.toolbar.set_content(content)
        self.toolbar.add_bottom_bar(self.player_bar)

        self.toaster = Adw.ToastOverlay()
        self.toaster.set_child(self.toolbar)

        # Shell stack: main | full player | queue/lyrics sheet (mobile).
        self.full_player = FullPlayer(self)
        sheet = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        sheet.add_css_class("riff-full-player")
        sheet_top = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        sheet_top.set_margin_top(10)
        sheet_top.set_margin_start(12)
        sheet_top.set_margin_end(12)
        sheet_close = Gtk.Button(label="⌃")
        sheet_close.add_css_class("flat")
        sheet_close.add_css_class("riff-heart")
        sheet_close.set_tooltip_text("Back to player")
        sheet_close.connect("clicked", lambda *_: self.open_full_player())
        sheet_top.append(sheet_close)
        sheet_title = Gtk.Label(label="Up next")
        sheet_title.add_css_class("title-3")
        sheet_title.set_hexpand(True)
        sheet_top.append(sheet_title)
        to_main = Gtk.Button(label="Close")
        to_main.add_css_class("flat")
        to_main.connect("clicked", lambda *_: self.close_full_player())
        sheet_top.append(to_main)
        sheet.append(sheet_top)
        # Reuse the existing Now Playing panel as the full-width sheet body.
        self._sheet_host = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self._sheet_host.set_vexpand(True)
        sheet.append(self._sheet_host)

        self._shell_stack = Gtk.Stack()
        self._shell_stack.set_transition_type(Gtk.StackTransitionType.SLIDE_UP)
        self._shell_stack.set_transition_duration(220)
        self._shell_stack.add_named(self.toaster, "main")
        self._shell_stack.add_named(self.full_player, "player")
        self._shell_stack.add_named(sheet, "sheet")
        self._player_sheet = sheet
        self.set_content(self._shell_stack)

        # Adaptive: below ~900sp the left nav becomes an overlay flap.
        try:
            bp = Adw.Breakpoint.new(
                Adw.BreakpointCondition.parse("max-width: 900sp"))
            bp.add_setter(self._nav_split, "collapsed", True)
            bp.connect("apply", self._on_narrow_apply)
            bp.connect("unapply", self._on_narrow_unapply)
            self.add_breakpoint(bp)
        except Exception:  # noqa: BLE001 — older Adw without Breakpoint API
            log.warning("Adw.Breakpoint unavailable; shell stays fixed-width")

        self._sidebar_reveal_btn.connect(
            "toggled", self._on_sidebar_reveal_toggled)
        self._nav_split.connect(
            "notify::show-sidebar", self._on_nav_show_sidebar_notify)

        self.service.error_listeners.append(self.toast)
        self.service.video_listeners.append(self._on_video_mode)
        self.service.video_paintable_listeners.append(
            self.player_bar.set_video_paintable)
        self.service.track_listeners.append(self._on_track_accent)
        self._install_actions()
        self.connect("close-request", self._on_close)

        # select Home
        self.sidebar_list.select_row(self.sidebar_list.get_row_at_index(0))
        self.pages["home"].refresh()
        self.reload_sidebar_playlists()
        if self._mobile_shell:
            self._apply_sidebar_mode()
            # Esc closes the full player / sheet.
            key = Gtk.EventControllerKey()
            key.connect("key-pressed", self._on_shell_key)
            self.add_controller(key)

    def _on_shell_key(self, _ctrl, keyval, _code, _state) -> bool:
        from gi.repository import Gdk
        if keyval == Gdk.KEY_Escape:
            visible = self._shell_stack.get_visible_child_name()
            if visible in ("player", "sheet"):
                self.close_full_player()
                return True
        return False

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
        sleep = Gio.SimpleAction.new(
            "sleep-timer", GLib.VariantType.new("s"))
        sleep.connect("activate", self._on_sleep_timer_action)
        self.add_action(sleep)

    def _on_sleep_timer_action(self, _action, param) -> None:
        value = param.get_string() if param is not None else "cancel"
        timer = self.service.sleep_timer
        if value == "cancel":
            timer.cancel()
            self.toast("Sleep timer cancelled")
            return
        if value == "eos":
            timer.start_end_of_song()
            self.toast("Sleep timer · end of song")
            return
        try:
            mins = int(value)
        except (TypeError, ValueError):
            return
        timer.start_minutes(mins)
        self.toast(f"Sleep timer · {mins} min")

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
        # On narrow overlay, auto-hide drawer after a destination pick.
        if self._narrow:
            self._nav_split.set_show_sidebar(False)

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

    def _on_narrow_apply(self, _bp=None) -> None:
        """Breakpoint: left nav becomes an overlay; show header reveal button."""
        self._narrow = True
        self._sidebar_reveal_btn.set_visible(True)
        self._collapse_btn.set_visible(False)
        # Full labels in the overlay drawer for usability.
        self._sidebar_collapsed = False
        self._apply_sidebar_mode()
        self._nav_split.set_show_sidebar(False)
        self._sidebar_reveal_btn.set_active(False)

    def _on_narrow_unapply(self, _bp=None) -> None:
        self._narrow = False
        self._sidebar_reveal_btn.set_visible(False)
        self._collapse_btn.set_visible(True)
        self._nav_split.set_collapsed(False)
        self._nav_split.set_show_sidebar(True)
        self._sidebar_collapsed = bool(
            config.settings.get("sidebar_collapsed", False))
        self._apply_sidebar_mode()
        self.reload_sidebar_playlists()

    def _on_sidebar_reveal_toggled(self, btn: Gtk.ToggleButton) -> None:
        if self._narrow:
            self._nav_split.set_show_sidebar(btn.get_active())

    def _on_nav_show_sidebar_notify(self, *_args) -> None:
        if not self._narrow:
            return
        showing = self._nav_split.get_show_sidebar()
        if self._sidebar_reveal_btn.get_active() != showing:
            self._sidebar_reveal_btn.set_active(showing)

    def _toggle_sidebar(self) -> None:
        if self._narrow:
            self._nav_split.set_show_sidebar(
                not self._nav_split.get_show_sidebar())
            return
        self._sidebar_collapsed = not self._sidebar_collapsed
        config.settings.set("sidebar_collapsed", self._sidebar_collapsed)
        self._apply_sidebar_mode()
        self.reload_sidebar_playlists()

    def _apply_sidebar_mode(self) -> None:
        # Riff Mobile rail is always a compact vertical strip.
        if getattr(self, "_mobile_shell", False) and not self._narrow:
            self._nav_split.set_min_sidebar_width(84)
            self._nav_split.set_max_sidebar_width(84)
            self._app_title.set_visible(False)
            self._collapse_btn.set_visible(False)
            for row, box, text, label in self._nav_rows:
                text.set_visible(True)
                box.set_halign(Gtk.Align.CENTER)
                row.set_tooltip_text(label)
            return
        # In narrow overlay mode always use a full-width drawer (not icon rail).
        collapsed = self._sidebar_collapsed and not self._narrow
        if collapsed:
            self._nav_split.set_min_sidebar_width(84)
            self._nav_split.set_max_sidebar_width(84)
        else:
            self._nav_split.set_min_sidebar_width(210)
            self._nav_split.set_max_sidebar_width(280 if self._narrow else 230)
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
        in) the account's YouTube Music playlists.

        Debounced — playlist edits often fire several reloads in a burst.
        """
        self._sidebar_reload_gen = getattr(self, "_sidebar_reload_gen", 0) + 1
        gen = self._sidebar_reload_gen

        def kick() -> bool:
            if gen != self._sidebar_reload_gen:
                return False
            self._reload_sidebar_playlists_now()
            return False

        try:
            from gi.repository import GLib
            GLib.timeout_add(80, kick)
        except Exception:  # noqa: BLE001
            self._reload_sidebar_playlists_now()

    def _reload_sidebar_playlists_now(self) -> None:
        def work():
            tree = self.library.playlist_tree()
            covers: dict[int, list] = {}
            # Thumbnails only — avoid hydrating full Track lists for art.
            for item in tree:
                if item["kind"] == "playlist":
                    covers[item["id"]] = self.library.playlist_thumbnails(
                        item["id"], 8)
                else:
                    for pid, _n, _c in item["playlists"]:
                        covers[pid] = self.library.playlist_thumbnails(pid, 8)
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
        if self._mobile_shell:
            if btn.get_active():
                self._open_full_player_tab("queue")
            return
        if btn.get_active():
            self._open_right_panel(tab="queue")
        else:
            self._close_right_panel_if_idle()

    def _on_now_toggle(self, btn) -> None:
        if self._mobile_shell:
            if btn.get_active():
                self.open_full_player()
            return
        if btn.get_active():
            self._open_right_panel(tab="queue")
        else:
            self._close_right_panel_if_idle()

    def open_full_player(self, tab: str | None = None) -> None:
        """Show the Riff Mobile full-screen player."""
        self._restore_now_panel_to_split()
        if tab:
            self.full_player.show_tab(tab)
        self._shell_stack.set_visible_child_name("player")

    def close_full_player(self) -> None:
        self._restore_now_panel_to_split()
        self._shell_stack.set_visible_child_name("main")
        # Clear mini-bar toggles without re-opening panels.
        self._right_sync = True
        try:
            self.player_bar.now_btn.set_active(False)
            self.player_bar.queue_btn.set_active(False)
        finally:
            self._right_sync = False

    def _open_full_player_tab(self, tab: str) -> None:
        """Queue sheet over the full player; lyrics stay in-player."""
        if tab == "lyrics":
            # Mobile: lyrics swap in place on the full player stage.
            self._restore_now_panel_to_split()
            self._shell_stack.set_visible_child_name("player")
            self.full_player.show_tab("lyrics")
            return
        self._park_now_panel_in_sheet()
        self.now_playing_panel.show_tab("queue")
        self.now_playing_panel.refresh()
        self.full_player.show_tab("queue")
        self._shell_stack.set_visible_child_name("sheet")

    def _park_now_panel_in_sheet(self) -> None:
        panel = self.now_playing_panel
        if panel.get_parent() is self._sheet_host:
            return
        try:
            panel.unparent()
        except Exception:  # noqa: BLE001
            pass
        self.queue_split.set_sidebar(Gtk.Box())
        self._sheet_host.append(panel)
        panel.set_hexpand(True)
        panel.set_vexpand(True)

    def _restore_now_panel_to_split(self) -> None:
        panel = self.now_playing_panel
        if panel.get_parent() is self._sheet_host:
            self._sheet_host.remove(panel)
        if panel.get_parent() is None:
            self.queue_split.set_sidebar(panel)
        panel.set_size_request(300, -1)

    def _open_right_panel(self, tab: str = "queue") -> None:
        """Show the single Now Playing panel on the given tab."""
        if self._right_sync:
            return
        self._right_sync = True
        try:
            self.now_playing_panel.show_tab(tab)
            self.now_playing_panel.refresh()
            self.queue_split.set_show_sidebar(True)
            bar = self.player_bar
            # Keep toggles reflecting panel open without fighting each other.
            if tab == "lyrics":
                if not bar.now_btn.get_active():
                    bar.now_btn.set_active(True)
                if not bar.queue_btn.get_active():
                    bar.queue_btn.set_active(True)
            elif not bar.now_btn.get_active() and not bar.queue_btn.get_active():
                bar.now_btn.set_active(True)
        finally:
            self._right_sync = False

    def _close_right_panel_if_idle(self) -> None:
        if self._right_sync:
            return
        bar = self.player_bar
        if bar.queue_btn.get_active() or bar.now_btn.get_active():
            return
        self.queue_split.set_show_sidebar(False)

    def toggle_now_playing(self) -> None:
        open_ = not self.queue_split.get_show_sidebar()
        if open_:
            self._right_sync = True
            try:
                self.player_bar.now_btn.set_active(True)
                self.player_bar.queue_btn.set_active(True)
            finally:
                self._right_sync = False
            self._open_right_panel(tab="queue")
        else:
            self._right_sync = True
            try:
                self.player_bar.now_btn.set_active(False)
                self.player_bar.queue_btn.set_active(False)
            finally:
                self._right_sync = False
            self.queue_split.set_show_sidebar(False)

    def set_video_mode(self, enabled: bool) -> None:
        """Play video in the cover-art slot (or restore the thumbnail)."""
        self.service.set_video_mode(bool(enabled))

    def toggle_video_mode(self) -> None:
        self.set_video_mode(not self.service.video_mode)

    def _on_video_mode(self, enabled: bool) -> None:
        if hasattr(self.player_bar, "set_video_active"):
            self.player_bar.set_video_active(enabled)

    # -- helpers used by widgets ------------------------------------------------

    def toast(
        self,
        message: str,
        *,
        action_label: str | None = None,
        action=None,
        timeout: int = 3,
    ) -> None:
        t = Adw.Toast.new(str(message))
        t.set_timeout(timeout)
        if action_label and action is not None:
            t.set_button_label(action_label)
            t.connect("button-clicked", lambda *_: action())
        self.toaster.add_toast(t)

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
        """Open the Now Playing panel on the Lyrics tab (single lyrics surface)."""
        track = self.service.current_track
        if track is None:
            self.toast("Nothing is playing")
            return
        if self._mobile_shell:
            self._open_full_player_tab("lyrics")
            return
        self._right_sync = True
        try:
            self.player_bar.now_btn.set_active(True)
            self.player_bar.queue_btn.set_active(True)
        finally:
            self._right_sync = False
        self._open_right_panel(tab="lyrics")

    def goto(self, name: str) -> None:
        """Navigate to a main sidebar page (used by keyboard shortcuts)."""
        self.close_full_player()
        for i, (item, _label, _icon) in enumerate(self._nav_items):
            if item == name:
                row = self.sidebar_list.get_row_at_index(i)
                self.sidebar_list.select_row(row)
                self._on_sidebar(self.sidebar_list, row)
                return
        # Destinations nested under Library (or Search FAB) — no rail row.
        if name in self.pages:
            self.nav.pop_to_tag("root")
            self.stack.set_visible_child_name(name)
            page = self.pages[name]
            if name == "search":
                page.focus()
            elif hasattr(page, "refresh"):
                page.refresh()

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

        # Rebuild only when closed — opening Preferences was rebuilding the
        # entire Adw tree (including banned-song list) on every click.
        dlg = getattr(self, "_settings_dialog", None)
        if dlg is None:
            dlg = SettingsDialog(self)
            self._settings_dialog = dlg

            def _clear(*_a):
                self._settings_dialog = None

            dlg.connect("closed", _clear)
        dlg.present(self)

    def _on_track_accent(self, track) -> None:
        """Vivi-style dynamic accent from album art (optional)."""
        from . import theme as theme_mod

        if not bool(config.settings.get("match_album_art", True)):
            theme_mod.clear_dynamic_accent()
            return
        if track is None or not (track.thumbnail or "").strip():
            theme_mod.clear_dynamic_accent()
            return
        url = track.thumbnail
        seq = getattr(self, "_accent_seq", 0) + 1
        self._accent_seq = seq

        def done(pair) -> None:
            if seq != getattr(self, "_accent_seq", 0):
                return
            if not pair:
                return
            theme_mod.apply_dynamic_accent(*pair)

        from . import images as images_mod
        images_mod.load_dominant_accent(url, done)

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

    # -- song-level discovery (spec §3.4) -------------------------------------

    def show_similar_songs(self, seed) -> None:
        """Dialog listing ~25 songs similar to the seed, with an
        unheard-only toggle — playable and queueable without touching the
        current queue."""
        from .widgets import TrackList

        dialog = Adw.Dialog.new()
        dialog.set_title(f"Similar to “{seed.title}”")
        dialog.set_content_width(560)
        dialog.set_content_height(640)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        box.append(Adw.HeaderBar())

        controls = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        controls.set_margin_start(16)
        controls.set_margin_end(16)
        play_all = Gtk.Button.new_with_label("Play all")
        play_all.add_css_class("suggested-action")
        play_all.add_css_class("pill")
        controls.append(play_all)
        unheard = Gtk.ToggleButton.new_with_label("Unheard only")
        unheard.add_css_class("pill")
        controls.append(unheard)
        box.append(controls)

        holder = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        holder.set_vexpand(True)
        spinner = Gtk.Spinner()
        spinner.set_size_request(28, 28)
        spinner.set_halign(Gtk.Align.CENTER)
        spinner.set_margin_top(30)
        spinner.start()
        holder.append(spinner)
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.set_vexpand(True)
        scroll.set_child(holder)
        box.append(scroll)
        dialog.set_child(box)
        dialog.present(self)

        state = {"tracks": []}

        def load(unheard_only: bool) -> None:
            def work():
                return self.service.discovery.similar_songs(
                    seed, limit=25, unheard_only=unheard_only)

            def done(tracks) -> None:
                state["tracks"] = tracks
                child = holder.get_first_child()
                while child is not None:
                    holder.remove(child)
                    child = holder.get_first_child()
                if not tracks:
                    empty = Gtk.Label(label=(
                        "Nothing similar found"
                        + (" that you haven't heard" if unheard_only
                           else "") + " — try again later."))
                    empty.add_css_class("dim-label")
                    empty.set_margin_top(30)
                    holder.append(empty)
                    return
                tl = TrackList(self, radio_on_single=True)
                tl.set_tracks(tracks)
                holder.append(tl)

            def fail(exc: Exception) -> None:
                done([])
                self.toast(f"Similar songs failed: {exc}")

            run_async(work, done, fail, name="riff-similar")

        play_all.connect(
            "clicked",
            lambda *_: state["tracks"] and self.service.play_tracks(
                list(state["tracks"]), source="discover_section"))
        unheard.connect(
            "toggled", lambda b: load(b.get_active()))
        load(False)

    def play_similar_next(self, seed) -> None:
        """Silently insert 5 similar songs after the current track —
        exploration without queue destruction."""

        def work():
            return self.service.discovery.similar_songs(seed, limit=5)

        def done(tracks) -> None:
            if not tracks:
                self.toast("No similar songs found")
                return
            self.service.add_next(tracks, source="discover_section")
            self.toast(f"{len(tracks)} similar songs playing next")

        run_async(work, done,
                  lambda exc: self.toast(f"Similar songs failed: {exc}"),
                  name="riff-similar-next")

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

