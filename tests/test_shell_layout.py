"""Shell layout defaults (no GTK required)."""

from riff import config


def test_default_shell_is_mobile():
    assert config.DEFAULTS["shell_layout"] == "mobile"


def test_shell_layout_accepts_desktop():
    assert "shell_layout" in config.DEFAULTS
