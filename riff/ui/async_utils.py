"""GTK-safe background work helpers.

All network / DB / yt-dlp work must run on worker threads; all GTK mutations
must return to the main loop via ``GLib.idle_add``. Prefer this module (or
``riff.util.run_async``) over ad-hoc threads.
"""

from __future__ import annotations

# Re-export the shared implementation so UI code has a clear import path.
from ..util import run_async

__all__ = ["run_async"]
