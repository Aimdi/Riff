"""Theme table sanity — importable without GTK (apply() imports gi lazily)."""

import importlib


def _load():
    return importlib.import_module("riff.ui.theme")


def test_default_theme_is_pitch_black():
    theme = _load()
    assert theme.DEFAULT_THEME == "pitch-black"
    assert theme.DEFAULT_THEME in theme.THEMES


def test_theme_table_shape():
    theme = _load()
    for key, t in theme.THEMES.items():
        assert t.label
        assert t.scheme in ("force-dark", "force-light", "default"), key


def test_pitch_black_is_true_black_with_green_accent():
    theme = _load()
    css = theme.THEMES["pitch-black"].css
    assert "@define-color window_bg_color #000000;" in css
    assert "@define-color accent_bg_color #008837;" in css
    # variables for libadwaita >= 1.6 too
    assert "--window-bg-color: #000000;" in css
    assert "--accent-bg-color: #008837;" in css


def test_default_setting_matches_theme_module():
    from riff import config

    theme = _load()
    assert config.DEFAULTS["theme"] == theme.DEFAULT_THEME


def test_accent_variants_share_true_black_surfaces():
    theme = _load()
    for key in ("pitch-blue", "pitch-violet", "pitch-crimson", "pitch-amber"):
        t = theme.THEMES[key]
        assert t.scheme == "force-dark", key
        assert "@define-color window_bg_color #000000;" in t.css, key
    # each variant has a distinct accent
    accents = set()
    for key, t in theme.THEMES.items():
        for line in t.css.splitlines():
            if line.startswith("@define-color accent_bg_color"):
                accents.add(line)
    assert len(accents) >= 5


def test_snow_is_light_with_recolored_accent():
    theme = _load()
    t = theme.THEMES["snow"]
    assert t.scheme == "force-light"
    assert "accent_bg_color #2563eb" in t.css
    assert "window_bg_color" not in t.css  # stock light surfaces
