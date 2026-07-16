"""Load symbolic icons from Riff's bundled SVGs.

Desktop themes (especially elementary / Breeze on CachyOS) often ship icons
that don't recolor correctly under dark / Pitch Black themes, or that miss
names Riff uses (``riff-stats-symbolic``, etc.). Looking up a name via the
system icon theme then paints a blank or near-invisible glyph.

Every ``*-symbolic.svg`` shipped under ``riff/ui/icons/`` is loaded with
:class:`Gtk.IconPaintable`, which still recolors it as a symbolic icon, and
never defers to the desktop theme for names we provide.
"""

from __future__ import annotations

import os

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gio, Gtk

ICONS_DIR = os.path.join(os.path.dirname(__file__), "icons")


def bundled_path(name: str) -> str | None:
    """Return the path of a bundled SVG for ``name``, or None."""
    if not name:
        return None
    # Accept both "list-add-symbolic" and "list-add-symbolic.svg".
    base = name if name.endswith(".svg") else f"{name}.svg"
    path = os.path.join(ICONS_DIR, base)
    return path if os.path.isfile(path) else None


def paintable(name: str, size: int = 16) -> Gtk.IconPaintable | None:
    path = bundled_path(name)
    if path is None:
        return None
    return Gtk.IconPaintable.new_for_file(
        Gio.File.new_for_path(path), size, 1)


def image(name: str, size: int = 16) -> Gtk.Image:
    """``Gtk.Image`` for ``name``, preferring the bundled SVG."""
    p = paintable(name, size)
    if p is not None:
        img = Gtk.Image.new_from_paintable(p)
    else:
        img = Gtk.Image.new_from_icon_name(name)
    img.set_pixel_size(size)
    return img


def set_image(img: Gtk.Image, name: str, size: int = 16) -> None:
    """Update an existing ``Gtk.Image`` to show ``name``."""
    p = paintable(name, size)
    if p is not None:
        img.set_from_paintable(p)
    else:
        img.set_from_icon_name(name)
    img.set_pixel_size(size)


def set_button(button: Gtk.Button, name: str, size: int = 16) -> None:
    """Set a button's icon from the bundle (or theme fallback)."""
    p = paintable(name, size)
    if p is not None:
        img = Gtk.Image.new_from_paintable(p)
        img.set_pixel_size(size)
        button.set_child(img)
    else:
        button.set_icon_name(name)
