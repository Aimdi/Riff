"""Application entry point."""

from __future__ import annotations

import logging
import sys

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gdk, Gio, GLib, Gtk  # noqa: E402

from . import APP_ID, config  # noqa: E402
from .core.api import MusicApi  # noqa: E402
from .core.downloader import Downloader  # noqa: E402
from .core.library import Library  # noqa: E402
from .core.player import PlayerEngine  # noqa: E402
from .core.service import PlaybackService  # noqa: E402
from .mpris import MprisServer  # noqa: E402
from .ui import theme  # noqa: E402
from .ui.window import MainWindow  # noqa: E402

log = logging.getLogger("riff")


def _glib_dispatcher(fn, *args) -> None:
    """Run fn(*args) once on the GTK main loop."""
    GLib.idle_add(lambda: (fn(*args), False)[1])


class RiffApplication(Adw.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID,
                         flags=Gio.ApplicationFlags.DEFAULT_FLAGS)
        self.window: MainWindow | None = None
        self.service: PlaybackService | None = None
        self.mpris: MprisServer | None = None

    def do_activate(self) -> None:
        if self.window is not None:
            self.window.present()
            return

        config.ensure_dirs()
        theme.apply(str(config.settings.get("theme", theme.DEFAULT_THEME)))
        self._register_bundled_icons()
        api = MusicApi()
        library = Library(config.DB_PATH)
        engine = PlayerEngine(dispatcher=_glib_dispatcher)
        self.service = PlaybackService(api, library, engine)
        downloader = Downloader(
            library, config.settings.get("download_dir",
                                         config.DEFAULT_DOWNLOAD_DIR))
        self.window = MainWindow(self, self.service, api, library, downloader)
        try:
            self.mpris = MprisServer(self.service, app=self)
        except Exception:  # noqa: BLE001 — MPRIS is best-effort
            log.exception("MPRIS unavailable")
        try:
            from .core.discordrpc import PresenceManager

            self.presence = PresenceManager(self.service, config.settings)
        except Exception:  # noqa: BLE001 — presence is best-effort
            log.exception("Discord presence unavailable")
            self.presence = None
        self._install_accels()
        self.window.present()
        # Daily AI Mix auto-refresh, shortly after startup so it never
        # competes with the first page load.
        GLib.timeout_add_seconds(
            15, lambda: (self.window.maybe_auto_refresh_ai_mix(), False)[1])

    def _register_bundled_icons(self) -> None:
        """Register bundled SVGs as an icon-theme search path.

        Primary UI widgets load icons via ``riff.ui.iconutil`` (which always
        prefers the shipped SVG so elementary/Breeze cannot blank them).
        This path remains so anything still using ``new_from_icon_name`` /
        ``set_icon_name`` (status pages, ScaleButton volumes, etc.) can still
        resolve Riff-only names like ``riff-stats-symbolic``.
        """
        import os

        icons_dir = os.path.join(os.path.dirname(__file__), "ui", "icons")
        display = Gdk.Display.get_default()
        if display is None:
            return
        if not os.path.isdir(icons_dir):
            log.warning("bundled icons missing at %s — package is incomplete",
                        icons_dir)
            return
        theme = Gtk.IconTheme.get_for_display(display)
        theme.add_search_path(icons_dir)
        if not theme.has_icon("riff-stats-symbolic"):
            log.warning(
                "icon fallback failed: riff-stats-symbolic still not "
                "resolvable (icon theme: %s)", theme.get_theme_name())

    def _install_accels(self) -> None:
        def add(name: str, cb, *accels: str) -> None:
            action = Gio.SimpleAction.new(name, None)
            action.connect("activate", lambda *_: cb())
            self.add_action(action)
            if accels:
                self.set_accels_for_action(f"app.{name}", list(accels))

        svc = self.service
        win = self.window
        bar = win.player_bar

        # playback
        add("play-pause", svc.toggle_pause, "space")
        add("next", svc.next, "<Ctrl>Right")
        add("previous", svc.previous, "<Ctrl>Left")
        add("seek-forward",
            lambda: svc.seek(svc.engine.position + 10), "<Shift>Right")
        add("seek-back",
            lambda: svc.seek(max(0.0, svc.engine.position - 10)), "<Shift>Left")
        add("like-current", bar._on_favorite, "<Alt><Shift>b")
        add("shuffle",
            lambda: bar.shuffle_btn.set_active(
                not bar.shuffle_btn.get_active()), "<Alt>s")
        add("repeat", lambda: bar._on_repeat(None), "<Alt>r")
        add("volume-up",
            lambda: bar.volume.set_value(
                min(100, bar.volume.get_value() + 5)), "<Alt>Up")
        add("volume-down",
            lambda: bar.volume.set_value(
                max(0, bar.volume.get_value() - 5)), "<Alt>Down")

        # navigation
        add("goto-home", lambda: win.goto("home"), "<Alt><Shift>h")
        add("goto-favorites", lambda: win.goto("favorites"), "<Alt><Shift>s")
        add("goto-playlists", lambda: win.goto("playlists"), "<Alt><Shift>1")
        add("goto-stats", lambda: win.goto("stats"), "<Alt><Shift>t")
        add("toggle-queue",
            lambda: bar.queue_btn.set_active(
                not bar.queue_btn.get_active()), "<Alt><Shift>q")

        # layout & misc
        add("new-playlist", win.create_playlist_dialog, "<Alt><Shift>p")
        add("toggle-sidebar", win._toggle_sidebar, "<Alt><Shift>l")
        add("now-playing", win.toggle_now_playing, "<Alt><Shift>n")
        add("mini-player", win.open_mini_player, "<Alt><Shift>m")
        add("lyrics", win.show_lyrics, "<Alt><Shift>y")
        add("shortcuts", win.show_shortcuts, "<Ctrl>slash", "question")
        add("settings", win.show_settings, "<Ctrl>comma")
        add("quit", self.quit, "<Ctrl>q")
        add("search", self._focus_search, "<Ctrl>f", "slash", "<Ctrl>k")

    def _focus_search(self) -> None:
        if self.window:
            self.window.stack.set_visible_child_name("search")
            self.window.pages["search"].focus()

    def do_shutdown(self) -> None:
        if getattr(self, "presence", None):
            self.presence.shutdown()
        if self.mpris:
            self.mpris.shutdown()
        if self.service:
            self.service.shutdown()
        Adw.Application.do_shutdown(self)


def main() -> int:
    from . import __version__

    if "--version" in sys.argv:
        print(f"riff {__version__}")
        return 0
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s: %(message)s")
    log.info("Riff %s starting", __version__)
    app = RiffApplication()
    return app.run([a for a in sys.argv if a != "--version"])


if __name__ == "__main__":
    sys.exit(main())
