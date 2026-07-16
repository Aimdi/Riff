"""Colored folder badge with an optional emoji/symbol overlay."""

from __future__ import annotations

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
    # Avoid huge paste; keep the first few code points.
    return e[:8]


def _hex_rgb(color: str) -> tuple[float, float, float]:
    c = normalize_color(color).lstrip("#")
    return (
        int(c[0:2], 16) / 255.0,
        int(c[2:4], 16) / 255.0,
        int(c[4:6], 16) / 255.0,
    )


class FolderBadge(Gtk.Overlay):
    """Folder shape filled with ``color`` and a centered emoji."""

    def __init__(self, color: str = DEFAULT_FOLDER_COLOR,
                 emoji: str = DEFAULT_FOLDER_EMOJI, size: int = 28):
        super().__init__()
        self._color = normalize_color(color)
        self._emoji = normalize_emoji(emoji)
        self._size = max(16, int(size))
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

        self._label = Gtk.Label(label=self._emoji)
        self._label.set_halign(Gtk.Align.CENTER)
        self._label.set_valign(Gtk.Align.CENTER)
        # Slightly smaller than the badge so it sits inside the tab.
        self._label.set_markup(
            f'<span size="{max(7000, self._size * 380)}">{self._escape(self._emoji)}</span>'
        )
        self.add_overlay(self._label)

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
            self._label.set_markup(
                f'<span size="{max(7000, self._size * 380)}">'
                f'{self._escape(self._emoji)}</span>'
            )
        self._draw.queue_draw()

    def _on_draw(self, _area, cr, width: int, height: int) -> None:
        r, g, b = _hex_rgb(self._color)
        # Soft shadow
        cr.set_source_rgba(0, 0, 0, 0.25)
        self._folder_path(cr, width, height, dy=1.2)
        cr.fill()
        # Body
        cr.set_source_rgb(r, g, b)
        self._folder_path(cr, width, height)
        cr.fill()
        # Lighter tab highlight
        cr.set_source_rgba(1, 1, 1, 0.18)
        self._tab_path(cr, width, height)
        cr.fill()

    def _folder_path(self, cr, w: float, h: float, dy: float = 0.0) -> None:
        # Classic folder: tab on the left, body below.
        m = max(w, h) * 0.06
        x0, y0 = m, m * 2.2 + dy
        x1, y1 = w - m, h - m + dy
        tab_w = (x1 - x0) * 0.42
        tab_h = m * 2.4
        rad = m * 1.4
        # Outer rounded rectangle with raised tab
        cr.new_path()
        cr.move_to(x0 + rad, y0)
        cr.line_to(x0 + tab_w, y0)
        cr.line_to(x0 + tab_w + tab_h * 0.6, y0 - tab_h)
        cr.line_to(x0 + tab_w + tab_h * 0.6 + tab_w * 0.55, y0 - tab_h)
        cr.line_to(x0 + tab_w + tab_h * 0.6 + tab_w * 0.55 + tab_h * 0.5, y0)
        cr.line_to(x1 - rad, y0)
        cr.arc(x1 - rad, y0 + rad, rad, -1.5708, 0)
        cr.line_to(x1, y1 - rad)
        cr.arc(x1 - rad, y1 - rad, rad, 0, 1.5708)
        cr.line_to(x0 + rad, y1)
        cr.arc(x0 + rad, y1 - rad, rad, 1.5708, 3.1416)
        cr.line_to(x0, y0 + rad)
        cr.arc(x0 + rad, y0 + rad, rad, 3.1416, 4.7124)
        cr.close_path()

    def _tab_path(self, cr, w: float, h: float) -> None:
        m = max(w, h) * 0.06
        x0, y0 = m, m * 2.2
        tab_w = (w - 2 * m) * 0.42
        tab_h = m * 2.4
        cr.rectangle(x0 + 1, y0 - tab_h + 1, tab_w * 0.9, tab_h * 0.55)
