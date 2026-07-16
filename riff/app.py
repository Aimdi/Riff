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
        self._install_accels()
        self.window.present()
        # Daily AI Mix auto-refresh, shortly after startup so it never
        # competes with the first page load.
        GLib.timeout_add_seconds(
            15, lambda: (self.window.maybe_auto_refresh_ai_mix(), False)[1])

    def _register_bundled_icons(self) -> None:
        """Riff bundles the symbolic icons it uses.

        Desktops whose GTK icon theme lacks GNOME icon names (e.g. Breeze on
        KDE Plasma) would otherwise render blank buttons — the favorite heart
        and the per-song menu were invisible on stock CachyOS. Icons placed
        directly on the search path act as a fallback: the active theme still
        wins when it provides a name.
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
        if not theme.has_icon("emblem-favorite-symbolic"):
            log.warning(
                "icon fallback failed: emblem-favorite-symbolic still not "
                "resolvable (icon theme: %s)", theme.get_theme_name())

    def _install_accels(self) -> None:
        def add(name: str, cb, *accels: str) -> None:
            action = Gio.SimpleAction.new(name, None)
            action.connect("activate", lambda *_: cb())
            self.add_action(action)
            if accels:
                self.set_accels_for_action(f"app.{name}", list(accels))

        svc = self.service
        add("play-pause", svc.toggle_pause, "space")
        add("next", svc.next, "<Ctrl>Right")
        add("previous", svc.previous, "<Ctrl>Left")
        add("seek-forward",
            lambda: svc.seek(svc.engine.position + 10), "<Shift>Right")
        add("seek-back",
            lambda: svc.seek(max(0.0, svc.engine.position - 10)), "<Shift>Left")
        add("quit", self.quit, "<Ctrl>q")
        add("search", self._focus_search, "<Ctrl>f", "slash")

    def _focus_search(self) -> None:
        if self.window:
            self.window.stack.set_visible_child_name("search")
            self.window.pages["search"].focus()

    def do_shutdown(self) -> None:
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
