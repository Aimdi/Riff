"""Settings dialog: playback quality, radio, account status, AI Mix key."""

from __future__ import annotations

import os

from gi.repository import Adw, Gtk

from .. import config
from ..core.api import AUTH_PATH

_QUALITIES = ["high", "medium", "low"]
_QUALITY_LABELS = ["High (best available)", "Medium (~160 kbps)", "Low (~96 kbps)"]


class SettingsDialog(Adw.PreferencesDialog):
    def __init__(self, window):
        super().__init__()
        self.window = window
        self.set_title("Settings")

        page = Adw.PreferencesPage()
        page.set_title("General")
        page.set_icon_name("emblem-system-symbolic")

        # -- playback --------------------------------------------------------
        playback = Adw.PreferencesGroup()
        playback.set_title("Playback")

        quality = Adw.ComboRow()
        quality.set_title("Audio quality")
        quality.set_subtitle("Applies to newly played songs")
        quality.set_model(Gtk.StringList.new(_QUALITY_LABELS))
        current = config.settings.get("audio_quality", "high")
        quality.set_selected(
            _QUALITIES.index(current) if current in _QUALITIES else 0)
        quality.connect("notify::selected", self._on_quality)
        playback.add(quality)

        radio = Adw.SwitchRow()
        radio.set_title("Radio autoplay")
        radio.set_subtitle("Keep playing similar songs when the queue ends")
        radio.set_active(bool(config.settings.get("autoplay_radio", True)))
        radio.connect("notify::active", self._on_radio)
        playback.add(radio)
        page.add(playback)

        # -- account -----------------------------------------------------------
        account = Adw.PreferencesGroup()
        account.set_title("YouTube Music account")
        acct_row = Adw.ActionRow()
        if os.path.exists(AUTH_PATH):
            acct_row.set_title("Connected")
            acct_row.set_subtitle(
                f"Using credentials from {AUTH_PATH} — delete the file to "
                "go back to anonymous mode, then restart Riff")
        else:
            acct_row.set_title("Not connected (anonymous)")
            acct_row.set_subtitle(
                "Optional: run  ytmusicapi browser --file "
                f"{AUTH_PATH}  to personalize Home and radio")
        account.add(acct_row)
        page.add(account)

        # -- AI mix ------------------------------------------------------------
        ai = Adw.PreferencesGroup()
        ai.set_title("AI Mix")
        ai.set_description(
            "Optional: with an Anthropic API key, “AI Mix” in the menu asks "
            "Claude to curate a queue from your history and favorites. Only "
            "song titles and artists are sent; the key is stored locally in "
            "settings.json.")

        self.key_row = Adw.PasswordEntryRow()
        self.key_row.set_title("Anthropic API key")
        self.key_row.set_text(
            str(config.settings.get("anthropic_api_key", "") or ""))
        self.key_row.set_show_apply_button(True)
        self.key_row.connect("apply", self._on_key_apply)
        ai.add(self.key_row)
        page.add(ai)

        self.add(page)

    def _on_quality(self, row: Adw.ComboRow, _pspec) -> None:
        value = _QUALITIES[row.get_selected()]
        config.settings.set("audio_quality", value)
        # take effect immediately for the next resolved stream
        self.window.service.resolver.quality = value

    def _on_radio(self, row: Adw.SwitchRow, _pspec) -> None:
        config.settings.set("autoplay_radio", bool(row.get_active()))

    def _on_key_apply(self, row: Adw.PasswordEntryRow) -> None:
        config.settings.set("anthropic_api_key", row.get_text().strip())
        self.window.toast("API key saved")
