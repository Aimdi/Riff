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
