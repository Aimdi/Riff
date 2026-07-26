"""Home composition helpers (Riff Mobile–aligned desktop shell)."""

from riff import config


def test_mobile_shell_default():
    assert config.DEFAULTS["shell_layout"] == "mobile"


def test_version_bumped_for_ui_release():
    from riff import __version__
    assert __version__.startswith("0.23")
