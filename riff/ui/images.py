"""Asynchronous cover-art loading with a disk + memory cache."""

from __future__ import annotations

import hashlib
import logging
import os
import urllib.request

from gi.repository import Gdk

from .. import config
from ..core.models import upscale_thumbnail
from ..util import run_async

log = logging.getLogger("riff.images")

_memory: dict[str, Gdk.Texture] = {}
_MEMORY_LIMIT = 256


def _cache_path(url: str) -> str:
    digest = hashlib.sha256(url.encode()).hexdigest()[:32]
    return os.path.join(config.ART_CACHE_DIR, digest)


def load_texture(url: str, size: int, callback) -> None:
    """Fetch `url` (scaled to ~size px) and call callback(texture|None) on
    the main loop. Never raises."""
    if not url:
        callback(None)
        return
    url = upscale_thumbnail(url, size)
    tex = _memory.get(url)
    if tex is not None:
        callback(tex)
        return

    path = _cache_path(url)

    def work() -> Gdk.Texture | None:
        if not os.path.exists(path):
            os.makedirs(config.ART_CACHE_DIR, exist_ok=True)
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=20) as resp:
                data = resp.read()
            tmp = path + ".part"
            with open(tmp, "wb") as f:
                f.write(data)
            os.replace(tmp, path)
        # Texture creation is thread-safe; keep it off the main loop.
        return Gdk.Texture.new_from_filename(path)

    def done(texture: Gdk.Texture | None) -> None:
        if texture is not None:
            if len(_memory) > _MEMORY_LIMIT:
                _memory.clear()
            _memory[url] = texture
        callback(texture)

    def error(_exc: Exception) -> None:
        callback(None)

    run_async(work, done, error, name="riff-art")
