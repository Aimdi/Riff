"""Colored folder badge with an optional emoji/symbol overlay.

Drawn with Cairo for a smooth, modern folder (rounded body + tab, soft
shadow and highlight) rather than a blocky polygon.
"""

from __future__ import annotations

import math
import re

from gi.repository import Gtk

# Curated palette — unique enough without a full color wheel.
FOLDER_COLORS: tuple[tuple[str, str], ...] = (
    ("#3b82f6", "Blue"),
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

DEFAULT_FOLDER_COLOR = "#3b82f6"
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
    """Folder shape filled with ``color`` and a centered emoji."""

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
        # Nudge emoji into the folder body (below the tab).
        self._label.set_margin_top(max(2, self._size // 7))
        self._apply_emoji_markup()
        self.add_overlay(self._label)

    def _emoji_pango_size(self) -> int:
        # Pango size is in 1024ths of a point; scale with badge size.
        return max(6500, int(self._size * 420))

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
        rgb = _hex_rgb(self._color)
        dark = _shade(rgb, 0.0, 0.28)
        light = _shade(rgb, 1.0, 0.22)
        mid = _shade(rgb, 0.0, 0.08)

        # Drop shadow
        cr.save()
        cr.translate(0, height * 0.04)
        cr.set_source_rgba(0, 0, 0, 0.28)
        self._body_path(cr, width, height, pad=0.08)
        cr.fill()
        cr.restore()

        # Back tab (slightly darker)
        cr.set_source_rgb(*dark)
        self._tab_path(cr, width, height)
        cr.fill()

        # Main body with vertical-ish gradient feel (two fills)
        cr.set_source_rgb(*mid)
        self._body_path(cr, width, height, pad=0.08)
        cr.fill()

        # Front face — brighter lower body inset
        cr.set_source_rgb(*rgb)
        self._body_path(cr, width, height, pad=0.10, top_extra=0.06)
        cr.fill()

        # Soft top sheen
        cr.set_source_rgba(*light, 0.35)
        self._sheen_path(cr, width, height)
        cr.fill()

        # Crisp outline
        cr.set_line_width(max(1.0, width * 0.03))
        cr.set_source_rgba(0, 0, 0, 0.18)
        self._body_path(cr, width, height, pad=0.08)
        cr.stroke()
        cr.set_source_rgba(0, 0, 0, 0.12)
        self._tab_path(cr, width, height)
        cr.stroke()

    def _tab_path(self, cr, w: float, h: float) -> None:
        """Rounded tab along the top-left."""
        pad = w * 0.08
        tab_h = h * 0.22
        tab_w = w * 0.46
        r = min(w, h) * 0.08
        x0 = pad
        y0 = pad + tab_h * 0.15
        # Tab sits above the body join line
        y_join = pad + tab_h
        cr.new_path()
        cr.move_to(x0 + r, y0)
        cr.line_to(x0 + tab_w - r * 1.2, y0)
        # right side of tab slopes into body
        cr.curve_to(
            x0 + tab_w, y0,
            x0 + tab_w + r * 0.6, y_join,
            x0 + tab_w + r * 1.4, y_join,
        )
        cr.line_to(x0 + r, y_join)
        cr.arc(x0 + r, y0 + r, r, math.pi, 1.5 * math.pi)
        cr.close_path()

    def _body_path(self, cr, w: float, h: float, pad: float = 0.08,
                   top_extra: float = 0.0) -> None:
        """Rounded rectangle for the folder body."""
        p = w * pad
        r = min(w, h) * 0.12
        top = h * (0.26 + top_extra)
        x0, y0 = p, top
        x1, y1 = w - p, h - p * 0.9
        self._rounded_rect(cr, x0, y0, x1 - x0, y1 - y0, r)

    def _sheen_path(self, cr, w: float, h: float) -> None:
        p = w * 0.12
        r = min(w, h) * 0.10
        top = h * 0.30
        self._rounded_rect(cr, p, top, w - 2 * p, h * 0.22, r)

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
