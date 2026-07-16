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

        folder = Adw.EntryRow()
        folder.set_title("Local music folder")
        folder.set_text(str(config.settings.get("local_music_dir", "~/Music")))
        folder.set_show_apply_button(True)
        folder.connect("apply", lambda row: self._save(
            "local_music_dir", row.get_text()))
        playback.add(folder)
        page.add(playback)

        # -- scrobbling ---------------------------------------------------------
        scrobble = Adw.PreferencesGroup()
        scrobble.set_title("Scrobbling")
        scrobble.set_description(
            "Optional: report your listens to ListenBrainz (free, open "
            "source). Get a token at listenbrainz.org/settings — songs count "
            "after half their length or 4 minutes.")
        lb_row = Adw.PasswordEntryRow()
        lb_row.set_title("ListenBrainz token")
        lb_row.set_text(str(config.settings.get("listenbrainz_token", "") or ""))
        lb_row.set_show_apply_button(True)
        lb_row.connect("apply", lambda row: self._save(
            "listenbrainz_token", row.get_text()))
        scrobble.add(lb_row)
        page.add(scrobble)

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
            "Optional: “AI Mix” in the menu asks an AI model to curate a "
            "queue from your history and favorites. Only song titles and "
            "artists are sent; keys are stored locally in settings.json.")

        provider = Adw.ComboRow()
        provider.set_title("Provider")
        provider.set_model(Gtk.StringList.new(
            ["Anthropic (Claude)", "OpenAI-compatible"]))
        provider.set_selected(
            1 if config.settings.get("ai_provider") == "openai" else 0)
        provider.connect("notify::selected", self._on_provider)
        ai.add(provider)

        auto = Adw.SwitchRow()
        auto.set_title("Refresh AI Mix daily")
        auto.set_subtitle(
            "Rebuild the “✨ AI Mix” playlist automatically once a day "
            "when Riff starts")
        auto.set_active(bool(config.settings.get("ai_mix_auto_refresh", False)))
        auto.connect("notify::active", lambda row, _p: config.settings.set(
            "ai_mix_auto_refresh", bool(row.get_active())))
        ai.add(auto)

        self.key_row = Adw.PasswordEntryRow()
        self.key_row.set_title("Anthropic API key")
        self.key_row.set_text(
            str(config.settings.get("anthropic_api_key", "") or ""))
        self.key_row.set_show_apply_button(True)
        self.key_row.connect("apply", self._on_key_apply)
        ai.add(self.key_row)
        page.add(ai)

        # -- OpenAI-compatible endpoint ---------------------------------------
        openai = Adw.PreferencesGroup()
        openai.set_title("OpenAI-compatible endpoint")
        openai.set_description(
            "Used when the provider above is “OpenAI-compatible”. Works with "
            "OpenAI, OpenRouter, Groq, and local servers like Ollama "
            "(http://localhost:11434/v1, key can stay empty) or LM Studio.")

        self.base_row = Adw.EntryRow()
        self.base_row.set_title("Base URL")
        self.base_row.set_text(str(config.settings.get(
            "openai_base_url", "https://api.openai.com/v1") or ""))
        self.base_row.set_show_apply_button(True)
        self.base_row.connect(
            "apply", lambda row: self._save("openai_base_url", row.get_text()))
        openai.add(self.base_row)

        self.openai_key_row = Adw.PasswordEntryRow()
        self.openai_key_row.set_title("API key (optional for local servers)")
        self.openai_key_row.set_text(
            str(config.settings.get("openai_api_key", "") or ""))
        self.openai_key_row.set_show_apply_button(True)
        self.openai_key_row.connect(
            "apply", lambda row: self._save("openai_api_key", row.get_text()))
        openai.add(self.openai_key_row)

        self.model_row = Adw.EntryRow()
        self.model_row.set_title("Model (e.g. gpt-4o-mini, llama3)")
        self.model_row.set_text(
            str(config.settings.get("openai_model", "") or ""))
        self.model_row.set_show_apply_button(True)
        self.model_row.connect(
            "apply", lambda row: self._save("openai_model", row.get_text()))
        openai.add(self.model_row)
        page.add(openai)

        self.add(page)

    def _save(self, key: str, value: str) -> None:
        config.settings.set(key, value.strip())
        self.window.toast("Saved")

    def _on_provider(self, row: Adw.ComboRow, _pspec) -> None:
        config.settings.set(
            "ai_provider", "openai" if row.get_selected() == 1 else "anthropic")

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
