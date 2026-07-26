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

_LYRICS_SOURCES = ["auto", "better", "lrclib"]
_LYRICS_LABELS = [
    "Auto (LRCLIB → Better → KuGou)",
    "Better Lyrics first",
    "LRCLIB first",
]

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

        shell = Adw.ComboRow()
        shell.set_title("Shell layout")
        shell.set_subtitle(
            "Mobile matches Riff Mobile (rail, mini player, full Now Playing). "
            "Restart may be needed after switching.")
        shell.set_model(Gtk.StringList.new(["Mobile (Riff Mobile)", "Desktop"]))
        shell_keys = ("mobile", "desktop")
        current_shell = str(config.settings.get("shell_layout", "mobile"))
        shell.set_selected(
            shell_keys.index(current_shell)
            if current_shell in shell_keys else 0)
        shell.connect(
            "notify::selected",
            lambda row, _p: config.settings.set(
                "shell_layout", shell_keys[row.get_selected()]))
        appearance.add(shell)
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

        crossfade = Adw.SpinRow.new_with_range(0, 12, 1)
        crossfade.set_title("Crossfade")
        crossfade.set_subtitle(
            "Seconds of blend between songs (like Spotify) — 0 turns it off")
        crossfade.set_value(float(config.settings.get("crossfade", 0) or 0))
        crossfade.connect(
            "notify::value",
            lambda row, _p: config.settings.set(
                "crossfade", int(row.get_value())))
        playback.add(crossfade)

        explore = Adw.ActionRow()
        explore.set_title("Exploration")
        explore.set_subtitle(
            "Radio & discovery taste: Familiar ↔ Adventurous")
        scale = Gtk.Scale.new_with_range(
            Gtk.Orientation.HORIZONTAL, 0, 100, 5)
        scale.set_size_request(180, -1)
        scale.set_draw_value(False)
        try:
            scale.set_value(
                float(config.settings.get("exploration", 0.3)) * 100)
        except (TypeError, ValueError):
            scale.set_value(30)
        scale.connect(
            "value-changed",
            lambda sc: config.settings.set(
                "exploration", round(sc.get_value() / 100, 2)))
        explore.add_suffix(scale)
        playback.add(explore)

        radio = Adw.SwitchRow()
        radio.set_title("Radio autoplay")
        radio.set_subtitle("Keep playing similar songs when the queue ends")
        radio.set_active(bool(config.settings.get("autoplay_radio", True)))
        radio.connect("notify::active", self._on_radio)
        playback.add(radio)

        smart_q = Adw.SwitchRow()
        smart_q.set_title("Smart queue")
        smart_q.set_subtitle(
            "Automatically add similar songs when few tracks remain "
            "(Riff Mobile Smart Queue)")
        smart_q.set_active(
            bool(config.settings.get("smart_queue_injection", True)))
        smart_q.connect(
            "notify::active",
            lambda row, _p: config.settings.set(
                "smart_queue_injection", bool(row.get_active())))
        playback.add(smart_q)

        pod_cont = Adw.SwitchRow()
        pod_cont.set_title("Continuous podcasts")
        pod_cont.set_subtitle(
            "Advance through the podcast episode queue automatically")
        pod_cont.set_active(
            bool(config.settings.get("podcast_continuous", True)))
        pod_cont.connect(
            "notify::active",
            lambda row, _p: config.settings.set(
                "podcast_continuous", bool(row.get_active())))
        playback.add(pod_cont)

        pod_ads = Adw.SwitchRow()
        pod_ads.set_title("Skip podcast ads")
        pod_ads.set_subtitle(
            "Automatically skip sponsor/ad chapters when Podcasting 2.0 "
            "markers are present")
        pod_ads.set_active(
            bool(config.settings.get("podcast_auto_skip_ads", True)))
        pod_ads.connect(
            "notify::active",
            lambda row, _p: config.settings.set(
                "podcast_auto_skip_ads", bool(row.get_active())))
        playback.add(pod_ads)

        lyrics = Adw.ComboRow()
        lyrics.set_title("Lyrics source")
        lyrics.set_subtitle(
            "Preferred synced-lyrics provider (KuGou is always a fallback)")
        lyrics.set_model(Gtk.StringList.new(_LYRICS_LABELS))
        cur_lyrics = str(config.settings.get("lyrics_source", "auto") or "auto")
        lyrics.set_selected(
            _LYRICS_SOURCES.index(cur_lyrics)
            if cur_lyrics in _LYRICS_SOURCES else 0)
        lyrics.connect(
            "notify::selected",
            lambda row, _p: config.settings.set(
                "lyrics_source",
                _LYRICS_SOURCES[row.get_selected()]
                if 0 <= row.get_selected() < len(_LYRICS_SOURCES)
                else "auto"))
        playback.add(lyrics)

        folder = Adw.EntryRow()
        folder.set_title("Local music folder")
        folder.set_text(str(config.settings.get("local_music_dir", "~/Music")))
        folder.set_show_apply_button(True)
        folder.connect("apply", lambda row: self._save(
            "local_music_dir", row.get_text()))
        playback.add(folder)
        page.add(playback)

        # -- Never play / banned ----------------------------------------------
        banned = Adw.PreferencesGroup()
        banned.set_title("Never play")
        banned.set_description(
            "Tracks you've marked “never play this” are excluded from "
            "radio and discovery.")
        dislikes = self.window.library.dislikes()
        if not dislikes:
            empty = Adw.ActionRow()
            empty.set_title("No banned songs")
            empty.set_subtitle("Long-press a track in the player to ban it")
            banned.add(empty)
        else:
            for track in dislikes[:40]:
                row = Adw.ActionRow()
                row.set_title(track.title or track.video_id)
                row.set_subtitle(track.artist or "")
                rm = Gtk.Button(label="Remove")
                rm.add_css_class("flat")
                rm.set_valign(Gtk.Align.CENTER)

                def _unban(_b, vid=track.video_id, r=row) -> None:
                    self.window.library.remove_dislike(vid)
                    banned.remove(r)
                    self.window.toast("Removed from never-play list")

                rm.connect("clicked", _unban)
                row.add_suffix(rm)
                banned.add(row)
        page.add(banned)

        # -- Audiobookshelf (Lissen-compatible) --------------------------------
        abs_group = Adw.PreferencesGroup()
        abs_group.set_title("Audiobookshelf")
        abs_group.set_description(
            "Stream your self-hosted library (same API as Riff Mobile / "
            "Lissen). LibriVox discover still works without a server.")
        self._abs_host = Adw.EntryRow()
        self._abs_host.set_title("Server URL")
        self._abs_host.set_text(
            str(config.settings.get("abs_host", "") or ""))
        self._abs_host.set_show_apply_button(True)
        self._abs_host.connect("apply", lambda row: self._save(
            "abs_host", row.get_text().strip()))
        abs_group.add(self._abs_host)
        self._abs_user = Adw.EntryRow()
        self._abs_user.set_title("Username")
        self._abs_user.set_text(
            str(config.settings.get("abs_username", "") or ""))
        self._abs_user.set_show_apply_button(True)
        self._abs_user.connect("apply", lambda row: self._save(
            "abs_username", row.get_text().strip()))
        abs_group.add(self._abs_user)
        self._abs_pass = Adw.PasswordEntryRow()
        self._abs_pass.set_title("Password")
        self._abs_pass.set_text(
            str(config.settings.get("abs_password", "") or ""))
        self._abs_pass.set_show_apply_button(True)
        self._abs_pass.connect("apply", lambda row: self._save(
            "abs_password", row.get_text()))
        abs_group.add(self._abs_pass)
        connected = bool(config.settings.get("abs_token", ""))
        self._abs_status = Adw.ActionRow()
        self._abs_status.set_title(
            "Connected" if connected else "Not connected")
        self._abs_status.set_subtitle(
            str(config.settings.get("abs_host", "") or "")
            if connected else "Save credentials, then Connect")
        connect_btn = Gtk.Button(
            label="Disconnect" if connected else "Connect")
        connect_btn.set_valign(Gtk.Align.CENTER)
        if not connected:
            connect_btn.add_css_class("suggested-action")
        connect_btn.connect("clicked", self._on_abs_toggle)
        self._abs_status.add_suffix(connect_btn)
        self._abs_connect_btn = connect_btn
        abs_group.add(self._abs_status)
        page.add(abs_group)

        # -- Cloud (Subsonic-compatible) --------------------------------------
        cloud_group = Adw.PreferencesGroup()
        cloud_group.set_title("Cloud music")
        cloud_group.set_description(
            "Stream your own collection from Navidrome, OpenSubsonic, "
            "Airsonic, Gonic, Ampache, or any Subsonic-compatible server.")
        self._cloud_host = Adw.EntryRow()
        self._cloud_host.set_title("Server URL")
        self._cloud_host.set_text(
            str(config.settings.get("cloud_host", "") or ""))
        self._cloud_host.set_show_apply_button(True)
        self._cloud_host.connect("apply", lambda row: self._save(
            "cloud_host", row.get_text().strip()))
        cloud_group.add(self._cloud_host)
        self._cloud_user = Adw.EntryRow()
        self._cloud_user.set_title("Username")
        self._cloud_user.set_text(
            str(config.settings.get("cloud_username", "") or ""))
        self._cloud_user.set_show_apply_button(True)
        self._cloud_user.connect("apply", lambda row: self._save(
            "cloud_username", row.get_text().strip()))
        cloud_group.add(self._cloud_user)
        self._cloud_pass = Adw.PasswordEntryRow()
        self._cloud_pass.set_title("Password")
        self._cloud_pass.set_text(
            str(config.settings.get("cloud_password", "") or ""))
        self._cloud_pass.set_show_apply_button(True)
        self._cloud_pass.connect("apply", lambda row: self._save(
            "cloud_password", row.get_text()))
        cloud_group.add(self._cloud_pass)
        cloud_ok = bool(
            config.settings.get("cloud_host")
            and config.settings.get("cloud_username")
            and config.settings.get("cloud_password"))
        self._cloud_status = Adw.ActionRow()
        self._cloud_status.set_title(
            "Connected" if cloud_ok else "Not connected")
        self._cloud_status.set_subtitle(
            str(config.settings.get("cloud_host", "") or "")
            if cloud_ok else "Save credentials, then Connect")
        cloud_btn = Gtk.Button(
            label="Disconnect" if cloud_ok else "Connect")
        cloud_btn.set_valign(Gtk.Align.CENTER)
        if not cloud_ok:
            cloud_btn.add_css_class("suggested-action")
        cloud_btn.connect("clicked", self._on_cloud_toggle)
        self._cloud_status.add_suffix(cloud_btn)
        self._cloud_connect_btn = cloud_btn
        cloud_group.add(self._cloud_status)
        page.add(cloud_group)

        # -- SoulSync plugin --------------------------------------------------
        ss_group = Adw.PreferencesGroup()
        ss_group.set_title("SoulSync")
        ss_group.set_description(
            "Optional plugin: search and queue downloads on a self-hosted "
            "SoulSync server (Bearer API key).")
        self._ss_host = Adw.EntryRow()
        self._ss_host.set_title("Server URL")
        self._ss_host.set_text(
            str(config.settings.get("soulsync_host", "") or ""))
        self._ss_host.set_show_apply_button(True)
        self._ss_host.connect("apply", lambda row: self._save(
            "soulsync_host", row.get_text().strip()))
        ss_group.add(self._ss_host)
        self._ss_key = Adw.PasswordEntryRow()
        self._ss_key.set_title("API key")
        self._ss_key.set_text(
            str(config.settings.get("soulsync_api_key", "") or ""))
        self._ss_key.set_show_apply_button(True)
        self._ss_key.connect("apply", lambda row: self._save(
            "soulsync_api_key", row.get_text()))
        ss_group.add(self._ss_key)
        ss_ok = bool(
            config.settings.get("soulsync_host")
            and config.settings.get("soulsync_api_key"))
        self._ss_status = Adw.ActionRow()
        self._ss_status.set_title(
            "Connected" if ss_ok else "Not connected")
        self._ss_status.set_subtitle(
            str(config.settings.get("soulsync_host", "") or "")
            if ss_ok else "Save URL + key, then Connect")
        ss_btn = Gtk.Button(label="Disconnect" if ss_ok else "Connect")
        ss_btn.set_valign(Gtk.Align.CENTER)
        if not ss_ok:
            ss_btn.add_css_class("suggested-action")
        ss_btn.connect("clicked", self._on_soulsync_toggle)
        self._ss_status.add_suffix(ss_btn)
        self._ss_connect_btn = ss_btn
        ss_group.add(self._ss_status)
        page.add(ss_group)

        # -- Seeker / slskd ---------------------------------------------------
        sk_group = Adw.PreferencesGroup()
        sk_group.set_title("Seeker (slskd)")
        sk_group.set_description(
            "Search Soulseek through a self-hosted slskd instance "
            "(API key optional depending on your server).")
        self._sk_host = Adw.EntryRow()
        self._sk_host.set_title("Server URL")
        self._sk_host.set_text(
            str(config.settings.get("slskd_host", "") or ""))
        self._sk_host.set_show_apply_button(True)
        self._sk_host.connect("apply", lambda row: self._save(
            "slskd_host", row.get_text().strip()))
        sk_group.add(self._sk_host)
        self._sk_key = Adw.PasswordEntryRow()
        self._sk_key.set_title("API key (optional)")
        self._sk_key.set_text(
            str(config.settings.get("slskd_api_key", "") or ""))
        self._sk_key.set_show_apply_button(True)
        self._sk_key.connect("apply", lambda row: self._save(
            "slskd_api_key", row.get_text()))
        sk_group.add(self._sk_key)
        sk_btn = Gtk.Button(label="Connect")
        sk_btn.add_css_class("suggested-action")
        sk_btn.set_valign(Gtk.Align.CENTER)
        sk_row = Adw.ActionRow()
        sk_row.set_title("Test connection")
        sk_row.add_suffix(sk_btn)
        sk_btn.connect("clicked", self._on_slskd_connect)
        sk_group.add(sk_row)
        page.add(sk_group)

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

        # -- Spotify import (optional Web API) ---------------------------------
        spotify = Adw.PreferencesGroup()
        spotify.set_title("Spotify import")
        spotify.set_description(
            "“Import from Spotify” works out of the box (no account). "
            "Optionally add your own free Spotify developer app — create "
            "one at developer.spotify.com/dashboard — to import playlists "
            "longer than ~100 songs completely. Note: Spotify blocks its "
            "own editorial playlists for new API apps; Riff automatically "
            "falls back to the keyless method for those.")

        sp_id = Adw.EntryRow()
        sp_id.set_title("Spotify Client ID")
        sp_id.set_text(str(config.settings.get("spotify_client_id", "") or ""))
        sp_id.set_show_apply_button(True)
        sp_id.connect("apply", lambda row: self._save(
            "spotify_client_id", row.get_text()))
        spotify.add(sp_id)

        sp_secret = Adw.PasswordEntryRow()
        sp_secret.set_title("Spotify Client Secret")
        sp_secret.set_text(
            str(config.settings.get("spotify_client_secret", "") or ""))
        sp_secret.set_show_apply_button(True)
        sp_secret.connect("apply", lambda row: self._save(
            "spotify_client_secret", row.get_text()))
        spotify.add(sp_secret)
        page.add(spotify)

        # -- Discord Rich Presence -------------------------------------------
        discord = Adw.PreferencesGroup()
        discord.set_title("Discord Rich Presence")
        discord.set_description(
            "Optional: show what you're listening to on Discord (like "
            "Snowify). Create a free application named “Riff” at "
            "discord.com/developers/applications and paste its "
            "Application ID here. Needs the Discord app running.")

        rpc_switch = Adw.SwitchRow()
        rpc_switch.set_title("Show current song on Discord")
        rpc_switch.set_active(
            bool(config.settings.get("discord_rpc_enabled", False)))
        rpc_switch.connect(
            "notify::active",
            lambda row, _p: config.settings.set(
                "discord_rpc_enabled", bool(row.get_active())))
        discord.add(rpc_switch)

        rpc_id = Adw.EntryRow()
        rpc_id.set_title("Discord Application ID")
        rpc_id.set_text(
            str(config.settings.get("discord_client_id", "") or ""))
        rpc_id.set_show_apply_button(True)
        rpc_id.connect("apply", lambda row: self._save(
            "discord_client_id", row.get_text()))
        discord.add(rpc_id)
        page.add(discord)

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

    def _on_abs_toggle(self, _btn) -> None:
        if config.settings.get("abs_token", ""):
            for key in ("abs_token", "abs_user_id", "abs_library_id"):
                config.settings.set(key, "")
            self._abs_status.set_title("Not connected")
            self._abs_status.set_subtitle("Save credentials, then Connect")
            self._abs_connect_btn.set_label("Connect")
            self._abs_connect_btn.add_css_class("suggested-action")
            self.window.toast("Audiobookshelf disconnected")
            return

        from ..core import audiobookshelf as abs_mod

        host = self._abs_host.get_text().strip()
        user = self._abs_user.get_text().strip()
        password = self._abs_pass.get_text()
        config.settings.set("abs_host", host)
        config.settings.set("abs_username", user)
        config.settings.set("abs_password", password)
        self._abs_status.set_subtitle("Connecting…")
        self._abs_connect_btn.set_sensitive(False)

        def work():
            session = abs_mod.login(host, user, password)
            libs = abs_mod.fetch_libraries(session)
            lib = abs_mod.prefer_book_library(libs)
            if lib:
                session.library_id = lib.id
            return session

        def done(session) -> None:
            config.settings.set("abs_host", session.host)
            config.settings.set("abs_username", session.username)
            config.settings.set("abs_token", session.token)
            config.settings.set("abs_user_id", session.user_id)
            config.settings.set("abs_library_id", session.library_id)
            self._abs_status.set_title("Connected")
            self._abs_status.set_subtitle(session.host)
            self._abs_connect_btn.set_label("Disconnect")
            self._abs_connect_btn.set_sensitive(True)
            self._abs_connect_btn.remove_css_class("suggested-action")
            self.window.toast("Audiobookshelf connected")

        def fail(exc: Exception) -> None:
            self._abs_status.set_title("Not connected")
            self._abs_status.set_subtitle(str(exc))
            self._abs_connect_btn.set_sensitive(True)
            self.window.toast(f"Audiobookshelf: {exc}")

        run_async(work, done, fail, name="riff-abs-login")

    def _on_cloud_toggle(self, _btn) -> None:
        if (config.settings.get("cloud_host")
                and config.settings.get("cloud_username")
                and config.settings.get("cloud_password")
                and self._cloud_connect_btn.get_label() == "Disconnect"):
            for key in (
                "cloud_host", "cloud_username", "cloud_password",
            ):
                config.settings.set(key, "")
            config.settings.set("cloud_legacy_auth", False)
            self._cloud_host.set_text("")
            self._cloud_user.set_text("")
            self._cloud_pass.set_text("")
            self._cloud_status.set_title("Not connected")
            self._cloud_status.set_subtitle("Save credentials, then Connect")
            self._cloud_connect_btn.set_label("Connect")
            self._cloud_connect_btn.add_css_class("suggested-action")
            self.window.toast("Cloud disconnected")
            return

        from ..core import cloud as cloud_mod

        host = self._cloud_host.get_text().strip()
        user = self._cloud_user.get_text().strip()
        password = self._cloud_pass.get_text()
        config.settings.set("cloud_host", host)
        config.settings.set("cloud_username", user)
        config.settings.set("cloud_password", password)
        self._cloud_status.set_subtitle("Connecting…")
        self._cloud_connect_btn.set_sensitive(False)

        def work():
            return cloud_mod.login(host, user, password)

        def done(session) -> None:
            config.settings.set("cloud_host", session.host)
            config.settings.set("cloud_username", session.username)
            config.settings.set("cloud_password", session.password)
            config.settings.set("cloud_legacy_auth", session.legacy_auth)
            self._cloud_status.set_title("Connected")
            self._cloud_status.set_subtitle(session.host)
            self._cloud_connect_btn.set_label("Disconnect")
            self._cloud_connect_btn.set_sensitive(True)
            self._cloud_connect_btn.remove_css_class("suggested-action")
            self.window.toast("Cloud music connected")

        def fail(exc: Exception) -> None:
            config.settings.set("cloud_password", "")
            self._cloud_status.set_title("Not connected")
            self._cloud_status.set_subtitle(str(exc))
            self._cloud_connect_btn.set_sensitive(True)
            self.window.toast(f"Cloud: {exc}")

        run_async(work, done, fail, name="riff-cloud-login")

    def _on_soulsync_toggle(self, _btn) -> None:
        if (config.settings.get("soulsync_host")
                and config.settings.get("soulsync_api_key")
                and self._ss_connect_btn.get_label() == "Disconnect"):
            config.settings.set("soulsync_host", "")
            config.settings.set("soulsync_api_key", "")
            self._ss_host.set_text("")
            self._ss_key.set_text("")
            self._ss_status.set_title("Not connected")
            self._ss_status.set_subtitle("Save URL + key, then Connect")
            self._ss_connect_btn.set_label("Connect")
            self._ss_connect_btn.add_css_class("suggested-action")
            self.window.toast("SoulSync disconnected")
            return

        from ..core import soulsync as ss_mod

        host = self._ss_host.get_text().strip()
        key = self._ss_key.get_text().strip()
        config.settings.set("soulsync_host", host)
        config.settings.set("soulsync_api_key", key)
        self._ss_status.set_subtitle("Connecting…")
        self._ss_connect_btn.set_sensitive(False)

        def work():
            return ss_mod.connect(host, key)

        def done(session) -> None:
            config.settings.set("soulsync_host", session.host)
            config.settings.set("soulsync_api_key", session.api_key)
            self._ss_status.set_title("Connected")
            self._ss_status.set_subtitle(session.host)
            self._ss_connect_btn.set_label("Disconnect")
            self._ss_connect_btn.set_sensitive(True)
            self._ss_connect_btn.remove_css_class("suggested-action")
            self.window.toast("SoulSync connected")

        def fail(exc: Exception) -> None:
            config.settings.set("soulsync_api_key", "")
            self._ss_status.set_title("Not connected")
            self._ss_status.set_subtitle(str(exc))
            self._ss_connect_btn.set_sensitive(True)
            self.window.toast(f"SoulSync: {exc}")

        run_async(work, done, fail, name="riff-ss-connect")

    def _on_slskd_connect(self, _btn) -> None:
        from ..core import slskd as slskd_mod

        host = self._sk_host.get_text().strip()
        key = self._sk_key.get_text().strip()
        config.settings.set("slskd_host", host)
        config.settings.set("slskd_api_key", key)

        def work():
            return slskd_mod.connect(host, key)

        def done(session) -> None:
            config.settings.set("slskd_host", session.host)
            config.settings.set("slskd_api_key", session.api_key)
            self.window.toast("slskd connected")

        def fail(exc: Exception) -> None:
            self.window.toast(f"slskd: {exc}")

        run_async(work, done, fail, name="riff-slskd-connect")

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
