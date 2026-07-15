"""Small helpers: background work that reports back on the GLib main loop."""

from __future__ import annotations

import logging
import threading
import traceback

log = logging.getLogger("riff")

try:
    from gi.repository import GLib

    def _dispatch(fn, *args) -> None:
        GLib.idle_add(lambda: (fn(*args), False)[1])

except ImportError:  # running headless (tests)
    def _dispatch(fn, *args) -> None:
        fn(*args)


def run_async(work, on_done=None, on_error=None, name: str = "riff-worker"):
    """Run `work()` in a daemon thread.

    `on_done(result)` / `on_error(exception)` are invoked on the GTK main
    loop, so they may touch widgets directly.
    """

    def runner():
        try:
            result = work()
        except Exception as exc:  # noqa: BLE001 — surfaced to on_error
            log.warning("async task failed: %s\n%s", exc, traceback.format_exc())
            if on_error is not None:
                _dispatch(on_error, exc)
            return
        if on_done is not None:
            _dispatch(on_done, result)

    t = threading.Thread(target=runner, name=name, daemon=True)
    t.start()
    return t
