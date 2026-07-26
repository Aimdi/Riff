"""Asynchronous cover-art loading with a disk + memory cache."""

from __future__ import annotations

import hashlib
import logging
import os
import urllib.request
from collections import OrderedDict

from gi.repository import Gdk

from .. import config
from ..core.models import upscale_thumbnail
from ..util import run_async

log = logging.getLogger("riff.images")

# LRU texture cache — previously wiped entirely at the limit (janky thrash).
_memory: OrderedDict[str, Gdk.Texture] = OrderedDict()
_MEMORY_LIMIT = 256


def _cache_put(key: str, texture: Gdk.Texture) -> None:
    if key in _memory:
        _memory.move_to_end(key)
    _memory[key] = texture
    while len(_memory) > _MEMORY_LIMIT:
        _memory.popitem(last=False)


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
        _memory.move_to_end(url)
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
            _cache_put(url, texture)
        callback(texture)

    def error(exc: Exception) -> None:
        log.warning("cover art failed (%s): %s", exc, original[:120])
        callback(None)

    run_async(work, done, error, name="riff-art")


def load_collage(urls: list[str], size: int, callback) -> None:
    """Compose up to 4 covers into a 2×2 collage texture (Snowify-style
    auto-generated playlist covers). Falls back to a single cover when fewer
    than 4 distinct images are available. callback(texture|None) runs on the
    main loop; never raises."""
    urls = [u for u in urls if u]
    # dedupe, keep order — an album playlist would otherwise show the same
    # art four times.
    seen: set[str] = set()
    distinct = [u for u in urls if not (u in seen or seen.add(u))]
    if len(distinct) < 4:
        load_texture(distinct[0] if distinct else "", size, callback)
        return
    quad = distinct[:4]

    key = "collage:" + "|".join(quad) + f":{size}"
    tex = _memory.get(key)
    if tex is not None:
        _memory.move_to_end(key)
        callback(tex)
        return

    def work() -> Gdk.Texture | None:
        from gi.repository import GdkPixbuf

        os.makedirs(config.ART_CACHE_DIR, exist_ok=True)
        half = max(2, size // 2)
        out = GdkPixbuf.Pixbuf.new(
            GdkPixbuf.Colorspace.RGB, False, 8, half * 2, half * 2)
        out.fill(0x101010FF)
        for i, u in enumerate(quad):
            u2 = upscale_thumbnail(u, half)
            path = _cache_path(u2)
            if not os.path.exists(path):
                try:
                    data = _fetch(u2)
                except Exception:  # noqa: BLE001 — retry unrewritten URL
                    data = _fetch(u)
                tmp = path + ".part"
                with open(tmp, "wb") as f:
                    f.write(data)
                os.replace(tmp, path)
            pb = GdkPixbuf.Pixbuf.new_from_file(path)
            # crop-scale to fill the quadrant (like content-fit: cover)
            scale = max(half / pb.get_width(), half / pb.get_height())
            w, h = int(pb.get_width() * scale), int(pb.get_height() * scale)
            scaled = pb.scale_simple(w, h, GdkPixbuf.InterpType.BILINEAR)
            sx, sy = max(0, (w - half) // 2), max(0, (h - half) // 2)
            tile = scaled.new_subpixbuf(sx, sy, min(half, w), min(half, h))
            tile.copy_area(0, 0, tile.get_width(), tile.get_height(),
                           out, (i % 2) * half, (i // 2) * half)
        return Gdk.Texture.new_for_pixbuf(out)

    def done(texture: Gdk.Texture | None) -> None:
        if texture is not None:
            _cache_put(key, texture)
        callback(texture)

    def error(exc: Exception) -> None:
        log.warning("collage failed (%s); using first cover", exc)
        load_texture(quad[0], size, callback)

    run_async(work, done, error, name="riff-collage")
