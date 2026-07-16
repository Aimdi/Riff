"""Application entry point."""

from __future__ import annotations

import logging
import sys

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gio, GLib  # noqa: E402

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
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s: %(message)s")
    app = RiffApplication()
    return app.run(sys.argv)


if __name__ == "__main__":
    sys.exit(main())
