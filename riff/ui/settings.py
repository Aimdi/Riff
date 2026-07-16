"""Settings dialog: playback quality, radio, account status, AI Mix."""

from __future__ import annotations

import os

from gi.repository import Adw, Gtk

from .. import config
from ..core import local_ai
from ..core.api import AUTH_PATH
from ..util import run_async
from . import theme

_QUALITIES = ["high", "medium", "low"]
_QUALITY_LABELS = ["High (best available)", "Medium (~160 kbps)", "Low (~96 kbps)"]

# Provider combo indices — keep in sync with _on_provider / _provider_index.
_PROVIDERS = ("local", "anthropic", "openai")
_PROVIDER_LABELS = (
    "Local (recommended)",
    "Anthropic (Claude)",
    "OpenAI-compatible",
)


class SettingsDialog(Adw.PreferencesDialog):
    def __init__(self, window):
        super().__init__()
        self.window = window
        self.set_title("Settings")
        self._installing = False

        page = Adw.PreferencesPage()
        page.set_title("General")
        page.set_icon_name("emblem-system-symbolic")

        # -- appearance --------------------------------------------------------
        appearance = Adw.PreferencesGroup()
        appearance.set_title("Appearance")

        self._theme_keys = list(theme.THEMES)
        theme_row = Adw.ComboRow()
        theme_row.set_title("Theme")
        theme_row.set_subtitle("Pitch Black: true black, easy on OLED screens")
        theme_row.set_model(Gtk.StringList.new(
            [theme.THEMES[k].label for k in self._theme_keys]))
        current_theme = str(config.settings.get("theme", theme.DEFAULT_THEME))
        theme_row.set_selected(
            self._theme_keys.index(current_theme)
            if current_theme in self._theme_keys else 0)
        theme_row.connect("notify::selected", self._on_theme)
        appearance.add(theme_row)
        page.add(appearance)

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
            "artists leave your machine (cloud providers) — Local keeps "
            "everything private.")

        provider = Adw.ComboRow()
        provider.set_title("Provider")
        provider.set_model(Gtk.StringList.new(list(_PROVIDER_LABELS)))
        provider.set_selected(self._provider_index(
            str(config.settings.get("ai_provider", "anthropic"))))
        provider.connect("notify::selected", self._on_provider)
        ai.add(provider)
        self._provider_row = provider

        auto = Adw.SwitchRow()
        auto.set_title("For you on Home")
        auto.set_subtitle(
            "On by default: Home shows AI song picks at the top and "
            "refreshes your mix in the background (uses AI when set up, "
            "otherwise smart radio from your history)")
        auto.set_active(bool(config.settings.get("ai_mix_auto_refresh", True)))
        auto.connect("notify::active", lambda row, _p: config.settings.set(
            "ai_mix_auto_refresh", bool(row.get_active())))
        ai.add(auto)
        page.add(ai)

        # -- Local model (Riff-managed) ----------------------------------------
        self.local_group = Adw.PreferencesGroup()
        self.local_group.set_title("Local model")
        self.local_group.set_description(local_ai.MODEL_WHY)

        self._local_models = list(local_ai.MODELS)
        self.local_model_row = Adw.ComboRow()
        self.local_model_row.set_title("Model")
        self.local_model_row.set_subtitle(
            "★ = Riff’s recommended pick. Bigger ≈ smarter and slower.")
        self.local_model_row.set_model(Gtk.StringList.new(
            [m.combo_label for m in self._local_models]))
        current_mid = str(
            config.settings.get("local_ai_model", local_ai.DEFAULT_MODEL_ID)
            or local_ai.DEFAULT_MODEL_ID)
        try:
            self.local_model_row.set_selected(
                next(i for i, m in enumerate(self._local_models)
                     if m.id == current_mid))
        except StopIteration:
            self.local_model_row.set_selected(
                next(i for i, m in enumerate(self._local_models)
                     if m.recommended))
        self.local_model_row.connect("notify::selected", self._on_local_model)
        self.local_group.add(self.local_model_row)

        self.local_status_row = Adw.ActionRow()
        self.local_status_row.set_title("Status")
        self.local_status_row.set_subtitle("Checking…")
        self.local_install_btn = Gtk.Button(label="Install")
        self.local_install_btn.add_css_class("pill")
        self.local_install_btn.add_css_class("suggested-action")
        self.local_install_btn.set_valign(Gtk.Align.CENTER)
        self.local_install_btn.connect("clicked", self._on_install_local)
        self.local_status_row.add_suffix(self.local_install_btn)
        self.local_group.add(self.local_status_row)
        page.add(self.local_group)

        # -- Anthropic key -----------------------------------------------------
        self.anthropic_group = Adw.PreferencesGroup()
        self.anthropic_group.set_title("Anthropic")
        self.anthropic_group.set_description(
            "Used when the provider is “Anthropic (Claude)”.")

        self.key_row = Adw.PasswordEntryRow()
        self.key_row.set_title("Anthropic API key")
        self.key_row.set_text(
            str(config.settings.get("anthropic_api_key", "") or ""))
        self.key_row.set_show_apply_button(True)
        self.key_row.connect("apply", self._on_key_apply)
        self.anthropic_group.add(self.key_row)
        page.add(self.anthropic_group)

        # -- OpenAI-compatible endpoint ---------------------------------------
        self.openai_group = Adw.PreferencesGroup()
        self.openai_group.set_title("OpenAI-compatible endpoint")
        self.openai_group.set_description(
            "Used when the provider is “OpenAI-compatible”. Works with "
            "OpenAI, OpenRouter, Groq, and hand-rolled local servers.")

        self.base_row = Adw.EntryRow()
        self.base_row.set_title("Base URL")
        self.base_row.set_text(str(config.settings.get(
            "openai_base_url", "https://api.openai.com/v1") or ""))
        self.base_row.set_show_apply_button(True)
        self.base_row.connect(
            "apply", lambda row: self._save("openai_base_url", row.get_text()))
        self.openai_group.add(self.base_row)

        self.openai_key_row = Adw.PasswordEntryRow()
        self.openai_key_row.set_title("API key (optional for local servers)")
        self.openai_key_row.set_text(
            str(config.settings.get("openai_api_key", "") or ""))
        self.openai_key_row.set_show_apply_button(True)
        self.openai_key_row.connect(
            "apply", lambda row: self._save("openai_api_key", row.get_text()))
        self.openai_group.add(self.openai_key_row)

        self.model_row = Adw.EntryRow()
        self.model_row.set_title("Model (e.g. gpt-4o-mini, llama3)")
        self.model_row.set_text(
            str(config.settings.get("openai_model", "") or ""))
        self.model_row.set_show_apply_button(True)
        self.model_row.connect(
            "apply", lambda row: self._save("openai_model", row.get_text()))
        self.openai_group.add(self.model_row)
        page.add(self.openai_group)

        self.add(page)
        self._refresh_provider_visibility()
        self._refresh_local_status()

    # -- helpers ---------------------------------------------------------------

    @staticmethod
    def _provider_index(key: str) -> int:
        try:
            return _PROVIDERS.index(key)
        except ValueError:
            return 1  # anthropic

    def _current_provider(self) -> str:
        idx = int(self._provider_row.get_selected())
        if 0 <= idx < len(_PROVIDERS):
            return _PROVIDERS[idx]
        return "anthropic"

    def _refresh_provider_visibility(self) -> None:
        provider = self._current_provider()
        self.local_group.set_visible(provider == "local")
        self.anthropic_group.set_visible(provider == "anthropic")
        self.openai_group.set_visible(provider == "openai")

    def _selected_local_model(self) -> local_ai.LocalModel:
        idx = int(self.local_model_row.get_selected())
        if 0 <= idx < len(self._local_models):
            return self._local_models[idx]
        return local_ai.selected_model()

    def _on_local_model(self, row: Adw.ComboRow, _pspec) -> None:
        model = self._local_models[row.get_selected()]
        local_ai.set_selected_model(model.id)
        self.local_model_row.set_subtitle(model.blurb)
        self._refresh_local_status()

    def _refresh_local_status(self) -> None:
        """Check engine + selected GGUF on a worker thread."""
        if self._installing:
            return
        model = self._selected_local_model()
        self.local_model_row.set_subtitle(model.blurb)

        def work():
            return local_ai.status(model)

        def done(st: local_ai.LocalAiStatus) -> None:
            self.local_status_row.set_title(st.model.label)
            self.local_status_row.set_subtitle(st.detail)
            if st.ready:
                self.local_install_btn.set_label("Ready")
                self.local_install_btn.set_sensitive(False)
                self.local_install_btn.remove_css_class("suggested-action")
            else:
                if st.runtime_ready and not st.model_ready:
                    label = f"Download ({st.model.size_hint})"
                elif st.model_ready and not st.runtime_ready:
                    label = "Install engine"
                else:
                    label = f"Install ({st.model.size_hint})"
                self.local_install_btn.set_label(label)
                self.local_install_btn.set_sensitive(True)
                self.local_install_btn.add_css_class("suggested-action")

        run_async(work, done, lambda _e: None, name="riff-local-ai-status")

    def _save(self, key: str, value: str) -> None:
        config.settings.set(key, value.strip())
        self.window.toast("Saved")

    def _on_theme(self, row: Adw.ComboRow, _pspec) -> None:
        key = self._theme_keys[row.get_selected()]
        config.settings.set("theme", key)
        theme.apply(key)

    def _on_provider(self, row: Adw.ComboRow, _pspec) -> None:
        provider = _PROVIDERS[row.get_selected()]
        config.settings.set("ai_provider", provider)
        if provider == "local":
            local_ai.apply_local_settings()
        self._refresh_provider_visibility()
        if provider == "local":
            self._refresh_local_status()

    def _on_quality(self, row: Adw.ComboRow, _pspec) -> None:
        value = _QUALITIES[row.get_selected()]
        config.settings.set("audio_quality", value)
        self.window.service.resolver.quality = value

    def _on_radio(self, row: Adw.SwitchRow, _pspec) -> None:
        config.settings.set("autoplay_radio", bool(row.get_active()))

    def _on_key_apply(self, row: Adw.PasswordEntryRow) -> None:
        config.settings.set("anthropic_api_key", row.get_text().strip())
        self.window.toast("API key saved")

    def _on_install_local(self, _btn) -> None:
        if self._installing:
            return
        model = self._selected_local_model()
        local_ai.set_selected_model(model.id)
        self._installing = True
        self.local_install_btn.set_sensitive(False)
        self.local_install_btn.set_label("Working…")
        self.local_status_row.set_subtitle(f"Installing {model.label}…")

        dialog = Adw.Dialog.new()
        dialog.set_title(f"Install {model.label}")
        dialog.set_content_width(400)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        box.append(Adw.HeaderBar())
        spinner = Gtk.Spinner()
        spinner.set_size_request(32, 32)
        spinner.set_halign(Gtk.Align.CENTER)
        spinner.start()
        box.append(spinner)
        status = Gtk.Label(label="Preparing…")
        status.set_wrap(True)
        status.set_margin_start(20)
        status.set_margin_end(20)
        status.set_margin_bottom(24)
        box.append(status)
        dialog.set_child(box)
        dialog.present(self)

        def progress(msg: str) -> None:
            from gi.repository import GLib
            GLib.idle_add(lambda: (status.set_label(msg), False)[1])

        def work():
            return local_ai.install_local_ai(
                progress=progress, model_id=model.id)

        def done(st: local_ai.LocalAiStatus) -> None:
            self._installing = False
            local_ai.apply_local_settings()
            config.settings.set("ai_provider", "local")
            self._provider_row.set_selected(self._provider_index("local"))
            spinner.stop()
            dialog.close()
            self._refresh_local_status()
            self.window.toast(
                f"{st.model.label} ready — AI Mix runs fully on-device")

        def fail(exc: Exception) -> None:
            self._installing = False
            spinner.stop()
            spinner.set_visible(False)
            status.set_label(f"Install failed:\n{exc}")
            status.add_css_class("error")
            self.local_install_btn.set_sensitive(True)
            self.local_install_btn.set_label("Retry")
            self.local_status_row.set_subtitle(str(exc))

        run_async(work, done, fail, name="riff-local-ai-install")
