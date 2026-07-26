"""Album-art palette extraction (Vivi / Material You–lite).

Pure helpers usable from worker threads. No ``gi`` required for hex math;
Pixbuf decode happens only when GTK is available.
"""

from __future__ import annotations

import colorsys
import os


def _clamp_byte(n: float) -> int:
    return max(0, min(255, int(round(n))))


def rgb_to_hex(r: int, g: int, b: int) -> str:
    return f"#{_clamp_byte(r):02x}{_clamp_byte(g):02x}{_clamp_byte(b):02x}"


def accent_pair(r: int, g: int, b: int) -> tuple[str, str, str]:
    """Return (accent_bg, accent_fg, accent) suitable for Pitch Black themes."""
    h, s, v = colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)
    # Boost saturation/value so the accent reads on true-black UI.
    s = max(0.45, min(0.95, s * 1.25 + 0.1))
    v_bg = max(0.45, min(0.85, v * 0.9 + 0.15))
    v_fg_accent = min(1.0, v_bg + 0.25)
    br, bg, bb = colorsys.hsv_to_rgb(h, s, v_bg)
    ar, ag, ab = colorsys.hsv_to_rgb(h, min(1.0, s + 0.05), v_fg_accent)
    # Readable button label on accent_bg.
    luminance = 0.2126 * br + 0.7152 * bg + 0.0722 * bb
    fg = "#000000" if luminance > 0.62 else "#ffffff"
    return (
        rgb_to_hex(br * 255, bg * 255, bb * 255),
        fg,
        rgb_to_hex(ar * 255, ag * 255, ab * 255),
    )


def dominant_from_file(path: str, *, sample: int = 32) -> tuple[int, int, int] | None:
    """Pick a vibrant-ish dominant RGB from an image file."""
    if not path or not os.path.isfile(path):
        return None
    try:
        from gi.repository import GdkPixbuf
    except Exception:  # noqa: BLE001
        return None
    try:
        pb = GdkPixbuf.Pixbuf.new_from_file_at_size(path, sample, sample)
    except Exception:  # noqa: BLE001
        return None
    if pb is None:
        return None
    w, h = pb.get_width(), pb.get_height()
    n = pb.get_n_channels()
    row = pb.get_rowstride()
    pixels = pb.get_pixels()
    best = None
    best_score = -1.0
    # Sample a sparse grid; prefer saturated mid-bright colors.
    step = max(1, min(w, h) // 8)
    for y in range(0, h, step):
        for x in range(0, w, step):
            i = y * row + x * n
            r, g, b = pixels[i], pixels[i + 1], pixels[i + 2]
            hh, ss, vv = colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)
            if vv < 0.18 or vv > 0.95 or ss < 0.12:
                continue
            score = ss * 1.4 + (1.0 - abs(vv - 0.55))
            if score > best_score:
                best_score = score
                best = (r, g, b)
    if best is None:
        # Fallback: average of non-near-black pixels.
        tot = [0, 0, 0]
        count = 0
        for y in range(0, h, step):
            for x in range(0, w, step):
                i = y * row + x * n
                r, g, b = pixels[i], pixels[i + 1], pixels[i + 2]
                if r + g + b < 40:
                    continue
                tot[0] += r
                tot[1] += g
                tot[2] += b
                count += 1
        if count:
            best = (tot[0] // count, tot[1] // count, tot[2] // count)
    return best


def blur_pixbuf_path(path: str, *, size: int = 48) -> object | None:
    """Downscale heavily for a soft wash (cheap blur stand-in)."""
    if not path or not os.path.isfile(path):
        return None
    try:
        from gi.repository import Gdk, GdkPixbuf
    except Exception:  # noqa: BLE001
        return None
    try:
        small = GdkPixbuf.Pixbuf.new_from_file_at_scale(path, size, size, True)
        if small is None:
            return None
        # Upscale with bilinear → soft wash.
        big = small.scale_simple(640, 640, GdkPixbuf.InterpType.BILINEAR)
        return Gdk.Texture.new_for_pixbuf(big)
    except Exception:  # noqa: BLE001
        return None
