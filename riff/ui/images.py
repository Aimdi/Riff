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


def _fetch(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        return resp.read()


def load_texture(url: str, size: int, callback) -> None:
    """Fetch `url` (scaled to ~size px) and call callback(texture|None) on
    the main loop. Never raises."""
    if not url:
        callback(None)
        return
    original = url
    url = upscale_thumbnail(url, size)
    tex = _memory.get(url)
    if tex is not None:
        callback(tex)
        return

    path = _cache_path(url)

    def work() -> Gdk.Texture | None:
        if not os.path.exists(path):
            os.makedirs(config.ART_CACHE_DIR, exist_ok=True)
            try:
                data = _fetch(url)
            except Exception:  # noqa: BLE001 — retry without size rewrite
                if url == original:
                    raise
                log.debug("upscaled art failed, retrying original: %s", url)
                data = _fetch(original)
            tmp = path + ".part"
            with open(tmp, "wb") as f:
                f.write(data)
            os.replace(tmp, path)
        # Texture creation is thread-safe; keep it off the main loop.
        try:
            return Gdk.Texture.new_from_filename(path)
        except Exception:
            # Whatever we cached isn't a decodable image — don't keep it.
            try:
                os.remove(path)
            except OSError:
                pass
            raise

    def done(texture: Gdk.Texture | None) -> None:
        if texture is not None:
            if len(_memory) > _MEMORY_LIMIT:
                _memory.clear()
            _memory[url] = texture
        callback(texture)

    def error(exc: Exception) -> None:
        log.warning("cover art failed (%s): %s", exc, original[:120])
        callback(None)

    run_async(work, done, error, name="riff-art")
