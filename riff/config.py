"""Paths and persisted settings."""

from __future__ import annotations

import json
import os
import threading

APP_DIR_NAME = "riff"


def _xdg(env: str, default: str) -> str:
    return os.environ.get(env) or os.path.expanduser(default)


CONFIG_DIR = os.path.join(_xdg("XDG_CONFIG_HOME", "~/.config"), APP_DIR_NAME)
DATA_DIR = os.path.join(_xdg("XDG_DATA_HOME", "~/.local/share"), APP_DIR_NAME)
CACHE_DIR = os.path.join(_xdg("XDG_CACHE_HOME", "~/.cache"), APP_DIR_NAME)
ART_CACHE_DIR = os.path.join(CACHE_DIR, "art")
DEFAULT_DOWNLOAD_DIR = os.path.join(
    _xdg("XDG_MUSIC_DIR", "~/Music"), "Riff"
)

DB_PATH = os.path.join(DATA_DIR, "library.db")
SETTINGS_PATH = os.path.join(CONFIG_DIR, "settings.json")

DEFAULTS = {
    "volume": 100,
    "audio_quality": "high",  # "high" | "medium" | "low"
    "download_dir": DEFAULT_DOWNLOAD_DIR,
    "autoplay_radio": True,
    "ai_provider": "anthropic",  # "anthropic" | "openai"
    "anthropic_api_key": "",
    "openai_base_url": "https://api.openai.com/v1",
    "openai_api_key": "",
    "openai_model": "",
    "window_width": 1100,
    "window_height": 720,
}


def ensure_dirs() -> None:
    for d in (CONFIG_DIR, DATA_DIR, CACHE_DIR, ART_CACHE_DIR):
        os.makedirs(d, exist_ok=True)


class Settings:
    """Tiny JSON-backed settings store, safe to call from any thread."""

    def __init__(self, path: str = SETTINGS_PATH):
        self._path = path
        self._lock = threading.Lock()
        self._data = dict(DEFAULTS)
        try:
            with open(path, "r", encoding="utf-8") as f:
                stored = json.load(f)
            if isinstance(stored, dict):
                self._data.update(stored)
        except (OSError, ValueError):
            pass

    def get(self, key: str, default=None):
        with self._lock:
            return self._data.get(key, DEFAULTS.get(key, default))

    def set(self, key: str, value) -> None:
        with self._lock:
            self._data[key] = value
            self._save_locked()

    def _save_locked(self) -> None:
        try:
            os.makedirs(os.path.dirname(self._path), exist_ok=True)
            tmp = self._path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self._data, f, indent=2)
            os.replace(tmp, self._path)
        except OSError:
            pass


settings = Settings()
