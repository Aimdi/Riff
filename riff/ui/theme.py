"""App themes.

A theme is a libadwaita color scheme plus an optional CSS overlay that
overrides Adwaita's named UI colors. The default is "Pitch Black" —
true-black backgrounds with a green accent, in the spirit of Notesnook's
Pitch Black theme (great on OLED screens). Snowify-style accent variants
reuse the same true-black surfaces with different accent colors.

This module keeps its data importable without GTK; `apply()` imports gi
lazily so unit tests can inspect the theme table headlessly.
"""

from __future__ import annotations

from dataclasses import dataclass


def _pitch_css(accent_bg: str, accent_fg: str, accent: str) -> str:
    """True-black surface CSS with a parameterized accent.

    Old-style @define-color names first (supported by every libadwaita
    release), then the equivalent CSS variables used by libadwaita >= 1.6.
    GTK's CSS parser drops rules it can't parse without discarding the rest
    of the sheet, so the :root block is harmless on older GTK.
    """
    return f"""
@define-color window_bg_color #000000;
@define-color window_fg_color #f2f2f2;
@define-color view_bg_color #000000;
@define-color view_fg_color #f2f2f2;
@define-color headerbar_bg_color #000000;
@define-color headerbar_fg_color #f2f2f2;
@define-color headerbar_backdrop_color #000000;
@define-color sidebar_bg_color #000000;
@define-color sidebar_backdrop_color #000000;
@define-color secondary_sidebar_bg_color #000000;
@define-color secondary_sidebar_backdrop_color #000000;
@define-color card_bg_color rgba(255, 255, 255, 0.06);
@define-color card_fg_color #f2f2f2;
@define-color popover_bg_color #141414;
@define-color popover_fg_color #f2f2f2;
@define-color dialog_bg_color #0a0a0a;
@define-color dialog_fg_color #f2f2f2;
@define-color accent_bg_color {accent_bg};
@define-color accent_fg_color {accent_fg};
@define-color accent_color {accent};

headerbar, .riff-player-bar {{
    border-color: rgba(255, 255, 255, 0.08);
}}

:root {{
    --window-bg-color: #000000;
    --window-fg-color: #f2f2f2;
    --view-bg-color: #000000;
    --view-fg-color: #f2f2f2;
    --headerbar-bg-color: #000000;
    --headerbar-fg-color: #f2f2f2;
    --headerbar-backdrop-color: #000000;
    --sidebar-bg-color: #000000;
    --sidebar-backdrop-color: #000000;
    --secondary-sidebar-bg-color: #000000;
    --secondary-sidebar-backdrop-color: #000000;
    --card-bg-color: rgba(255, 255, 255, 0.06);
    --card-fg-color: #f2f2f2;
    --popover-bg-color: #141414;
    --popover-fg-color: #f2f2f2;
    --dialog-bg-color: #0a0a0a;
    --dialog-fg-color: #f2f2f2;
    --accent-bg-color: {accent_bg};
    --accent-fg-color: {accent_fg};
    --accent-color: {accent};
}}
"""


def _accent_only_css(accent_bg: str, accent_fg: str, accent: str) -> str:
    """Accent recolor on top of stock Adwaita (for the light Snow theme)."""
    return f"""
@define-color accent_bg_color {accent_bg};
@define-color accent_fg_color {accent_fg};
@define-color accent_color {accent};

:root {{
    --accent-bg-color: {accent_bg};
    --accent-fg-color: {accent_fg};
    --accent-color: {accent};
}}
"""


@dataclass(frozen=True)
class Theme:
    label: str
    scheme: str  # "force-dark" | "force-light" | "default"
    css: str = ""


THEMES: dict[str, Theme] = {
    "pitch-black": Theme(
        "Pitch Black", "force-dark",
        _pitch_css("#008837", "#ffffff", "#2fd96e")),
    "pitch-blue": Theme(
        "Pitch Black · Blue", "force-dark",
        _pitch_css("#1a6ee8", "#ffffff", "#69a9ff")),
    "pitch-violet": Theme(
        "Pitch Black · Violet", "force-dark",
        _pitch_css("#7c3aed", "#ffffff", "#b78cff")),
    "pitch-crimson": Theme(
        "Pitch Black · Crimson", "force-dark",
        _pitch_css("#d81b4b", "#ffffff", "#ff6b8a")),
    "pitch-amber": Theme(
        "Pitch Black · Amber", "force-dark",
        _pitch_css("#c77800", "#ffffff", "#ffb340")),
    "snow": Theme(
        "Snow (light)", "force-light",
        _accent_only_css("#2563eb", "#ffffff", "#1d4ed8")),
    "dark": Theme("Dark", "force-dark"),
    "light": Theme("Light", "force-light"),
    "system": Theme("Follow system", "default"),
}

DEFAULT_THEME = "pitch-black"

_provider = None
_accent_provider = None
_last_theme_key = DEFAULT_THEME


def apply(key: str, display=None) -> None:
    """Apply a theme by key; unknown keys fall back to the default."""
    global _provider, _last_theme_key

    from gi.repository import Adw, Gdk, Gtk

    theme = THEMES.get(key) or THEMES[DEFAULT_THEME]
    _last_theme_key = key if key in THEMES else DEFAULT_THEME

    schemes = {
        "force-dark": Adw.ColorScheme.FORCE_DARK,
        "force-light": Adw.ColorScheme.FORCE_LIGHT,
        "default": Adw.ColorScheme.DEFAULT,
    }
    Adw.StyleManager.get_default().set_color_scheme(schemes[theme.scheme])

    display = display or Gdk.Display.get_default()
    if display is None:
        return
    if _provider is not None:
        Gtk.StyleContext.remove_provider_for_display(display, _provider)
        _provider = None
    if theme.css:
        provider = Gtk.CssProvider()
        provider.load_from_data(theme.css.encode())
        Gtk.StyleContext.add_provider_for_display(
            display, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        _provider = provider
    # Re-apply dynamic accent on top of the base theme when active.
    # Caller clears/sets via apply_dynamic_accent.


def apply_dynamic_accent(
    accent_bg: str, accent_fg: str, accent: str, display=None,
) -> None:
    """Overlay album-art accents (Vivi DynamicTheme lite)."""
    global _accent_provider

    from gi.repository import Gdk, Gtk

    display = display or Gdk.Display.get_default()
    if display is None:
        return
    clear_dynamic_accent(display)
    css = _accent_only_css(accent_bg, accent_fg, accent)
    # Also recolor pitch-black accent defines when those themes are active.
    css += f"""
@define-color accent_bg_color {accent_bg};
@define-color accent_fg_color {accent_fg};
@define-color accent_color {accent};
"""
    provider = Gtk.CssProvider()
    provider.load_from_data(css.encode())
    Gtk.StyleContext.add_provider_for_display(
        display, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION + 1)
    _accent_provider = provider


def clear_dynamic_accent(display=None) -> None:
    global _accent_provider

    from gi.repository import Gdk, Gtk

    display = display or Gdk.Display.get_default()
    if display is None or _accent_provider is None:
        return
    Gtk.StyleContext.remove_provider_for_display(display, _accent_provider)
    _accent_provider = None
