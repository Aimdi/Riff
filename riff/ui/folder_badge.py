"""Colored folder badge with an optional emoji/symbol overlay.

Shape matches the classic flat folder icon set (solid body + tab, rounded
corners) — same silhouette as common multi-style folder packs.
"""

from __future__ import annotations

import math
import re

from gi.repository import Gtk

# Curated palette — unique enough without a full color wheel.
FOLDER_COLORS: tuple[tuple[str, str], ...] = (
    ("#3b82f6", "Blue"),
    ("#38bdf8", "Sky"),
    ("#22c55e", "Green"),
    ("#2fd96e", "Riff green"),
    ("#eab308", "Yellow"),
    ("#f97316", "Orange"),
    ("#ef4444", "Red"),
    ("#ec4899", "Pink"),
    ("#a855f7", "Purple"),
    ("#14b8a6", "Teal"),
    ("#64748b", "Slate"),
    ("#f2f2f2", "Light"),
    ("#1e293b", "Dark"),
)

# One-tap symbols (users can type any emoji in the entry too).
FOLDER_EMOJI_PRESETS: tuple[str, ...] = (
    "🎵", "🔥", "❤️", "⭐", "🎸", "🎧", "💿", "🌙",
    "☀️", "💪", "🌈", "✨", "🚀", "🎯", "💫", "🎤",
)

DEFAULT_FOLDER_COLOR = "#38bdf8"  # close to the cyan reference folders
DEFAULT_FOLDER_EMOJI = "🎵"

_HEX = re.compile(r"^#?[0-9A-Fa-f]{6}$")


def normalize_color(color: str | None) -> str:
    c = (color or DEFAULT_FOLDER_COLOR).strip()
    if not c.startswith("#"):
        c = "#" + c
    if not _HEX.match(c):
        return DEFAULT_FOLDER_COLOR
    return c.lower()


def normalize_emoji(emoji: str | None) -> str:
    """Keep a short symbol (1–4 chars / one grapheme cluster best-effort)."""
    e = (emoji or "").strip()
    if not e:
        return DEFAULT_FOLDER_EMOJI
    return e[:8]


def _hex_rgb(color: str) -> tuple[float, float, float]:
    c = normalize_color(color).lstrip("#")
    return (
        int(c[0:2], 16) / 255.0,
        int(c[2:4], 16) / 255.0,
        int(c[4:6], 16) / 255.0,
    )


def _mix(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def _shade(rgb: tuple[float, float, float], toward: float, t: float
           ) -> tuple[float, float, float]:
    return tuple(_mix(c, toward, t) for c in rgb)  # type: ignore[return-value]


class FolderBadge(Gtk.Overlay):
    """Flat folder icon filled with ``color`` and a centered emoji."""

    def __init__(self, color: str = DEFAULT_FOLDER_COLOR,
                 emoji: str = DEFAULT_FOLDER_EMOJI, size: int = 28):
        super().__init__()
        self._color = normalize_color(color)
        self._emoji = normalize_emoji(emoji)
        self._size = max(18, int(size))
        self.set_size_request(self._size, self._size)
        self.set_hexpand(False)
        self.set_vexpand(False)
        self.set_halign(Gtk.Align.CENTER)
        self.set_valign(Gtk.Align.CENTER)

        self._draw = Gtk.DrawingArea()
        self._draw.set_content_width(self._size)
        self._draw.set_content_height(self._size)
        self._draw.set_draw_func(self._on_draw)
        self.set_child(self._draw)

        self._label = Gtk.Label()
        self._label.set_halign(Gtk.Align.CENTER)
        self._label.set_valign(Gtk.Align.CENTER)
        # Sit emoji in the body, under the tab.
        self._label.set_margin_top(max(3, self._size // 5))
        self._apply_emoji_markup()
        self.add_overlay(self._label)

    def _emoji_pango_size(self) -> int:
        return max(6500, int(self._size * 400))

    def _apply_emoji_markup(self) -> None:
        self._label.set_markup(
            f'<span size="{self._emoji_pango_size()}">'
            f"{self._escape(self._emoji)}</span>"
        )

    @staticmethod
    def _escape(text: str) -> str:
        return (text.replace("&", "&amp;")
                    .replace("<", "&lt;")
                    .replace(">", "&gt;"))

    def set_style(self, color: str | None = None, emoji: str | None = None) -> None:
        if color is not None:
            self._color = normalize_color(color)
        if emoji is not None:
            self._emoji = normalize_emoji(emoji)
            self._apply_emoji_markup()
        self._draw.queue_draw()

    def _on_draw(self, _area, cr, width: int, height: int) -> None:
        """Draw the classic flat folder: back tab + solid rounded body."""
        rgb = _hex_rgb(self._color)
        # Luminance: light fills get a dark outline so they stay visible on OLED.
        lum = 0.2126 * rgb[0] + 0.7152 * rgb[1] + 0.0722 * rgb[2]
        tab_rgb = _shade(rgb, 0.0 if lum > 0.55 else 1.0, 0.18 if lum > 0.55 else 0.12)
        # Slightly darker tab (reference bottom-left: tab is a deeper blue)
        tab_rgb = _shade(rgb, 0.0, 0.22)

        # Geometry matching the reference silhouette (viewBox-ish 0..1)
        # Tab on top-left with a diagonal right edge; rounded body below.
        m = min(width, height)
        pad = m * 0.06
        x0 = pad
        x1 = width - pad
        y_tab = pad
        y_body = pad + m * 0.20
        y1 = height - pad
        tab_w = (x1 - x0) * 0.42
        r = m * 0.14  # rounded corners like the reference

        # --- back tab (darker strip behind) ---
        cr.new_path()
        # left top of tab
        cr.move_to(x0 + r * 0.6, y_tab)
        cr.line_to(x0 + tab_w * 0.85, y_tab)
        # diagonal cut down to body line (classic folder notch)
        cr.line_to(x0 + tab_w + m * 0.08, y_body)
        cr.line_to(x0 + r * 0.6, y_body)
        cr.arc_negative(x0 + r * 0.6, y_tab + r * 0.6, r * 0.6, math.pi / 2, math.pi)
        cr.close_path()
        cr.set_source_rgb(*tab_rgb)
        cr.fill()

        # --- main body (solid, highly rounded) ---
        self._rounded_rect(cr, x0, y_body, x1 - x0, y1 - y_body, r)
        cr.set_source_rgb(*rgb)
        cr.fill()

        # Clean edge for light colors (outline style from the reference pack)
        if lum > 0.85:
            cr.set_line_width(max(1.25, m * 0.04))
            cr.set_source_rgb(0.12, 0.12, 0.14)
            self._rounded_rect(cr, x0, y_body, x1 - x0, y1 - y_body, r)
            cr.stroke()
            # tab outline
            cr.new_path()
            cr.move_to(x0 + r * 0.6, y_tab)
            cr.line_to(x0 + tab_w * 0.85, y_tab)
            cr.line_to(x0 + tab_w + m * 0.08, y_body)
            cr.stroke()

    @staticmethod
    def _rounded_rect(cr, x: float, y: float, w: float, h: float,
                      radius: float) -> None:
        r = min(radius, w / 2, h / 2)
        cr.new_path()
        cr.move_to(x + r, y)
        cr.line_to(x + w - r, y)
        cr.arc(x + w - r, y + r, r, -0.5 * math.pi, 0)
        cr.line_to(x + w, y + h - r)
        cr.arc(x + w - r, y + h - r, r, 0, 0.5 * math.pi)
        cr.line_to(x + r, y + h)
        cr.arc(x + r, y + h - r, r, 0.5 * math.pi, math.pi)
        cr.line_to(x, y + r)
        cr.arc(x + r, y + r, r, math.pi, 1.5 * math.pi)
        cr.close_path()
