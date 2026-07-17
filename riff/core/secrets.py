"""Secret storage for API tokens.

Prefers the FreeDesktop Secret Service (libsecret via PyGObject). Falls back
to a mode-0600 file under the XDG config dir when no keyring backend is
available (headless CI, minimal containers).

``gi`` is imported lazily so pure-logic tests never require GTK.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from typing import Final

log = logging.getLogger("riff.secrets")

SCHEMA_NAME: Final = "io.github.aimdi.Riff"
SCHEMA_ATTR: Final = "key"

SECRET_KEYS: Final[frozenset[str]] = frozenset(
    {
        "anthropic_api_key",
        "openai_api_key",
        "listenbrainz_token",
    }
)

_lock = threading.Lock()
_schema = None
_backend: str | None = None


def _fallback_path() -> str:
    from .. import config

    return os.path.join(config.CONFIG_DIR, "secrets.json")


def _probe_backend() -> str:
    global _backend, _schema
    if _backend is not None:
        return _backend
    try:
        import gi

        gi.require_version("Secret", "1")
        from gi.repository import Secret

        _schema = Secret.Schema.new(
            SCHEMA_NAME,
            Secret.SchemaFlags.NONE,
            {SCHEMA_ATTR: Secret.SchemaAttributeType.STRING},
        )
        Secret.password_lookup_sync(_schema, {SCHEMA_ATTR: "__probe__"}, None)
        _backend = "libsecret"
        log.debug("secrets backend: libsecret")
    except Exception:
        _schema = None
        _backend = "file"
        log.warning(
            "Secret Service unavailable; storing secrets in %s (mode 0600)",
            _fallback_path(),
        )
    return _backend


def _file_load() -> dict[str, str]:
    try:
        with open(_fallback_path(), encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return {str(k): str(v) for k, v in data.items() if v}
    except (OSError, ValueError):
        pass
    return {}


def _file_save(data: dict[str, str]) -> None:
    path = _fallback_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, path)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def get_secret(key: str) -> str | None:
    with _lock:
        backend = _probe_backend()
        if backend == "libsecret":
            try:
                from gi.repository import Secret

                value = Secret.password_lookup_sync(_schema, {SCHEMA_ATTR: key}, None)
                return value or None
            except Exception:
                log.warning("libsecret lookup failed for %s", key, exc_info=True)
                return None
        data = _file_load()
        return data.get(key) or None


def set_secret(key: str, value: str) -> None:
    value = (value or "").strip()
    if not value:
        delete_secret(key)
        return
    with _lock:
        backend = _probe_backend()
        if backend == "libsecret":
            try:
                from gi.repository import Secret

                Secret.password_store_sync(
                    _schema,
                    {SCHEMA_ATTR: key},
                    Secret.COLLECTION_DEFAULT,
                    f"Riff {key}",
                    value,
                    None,
                )
                return
            except Exception:
                log.warning("libsecret store failed; falling back to file", exc_info=True)
                global _backend
                _backend = "file"
        data = _file_load()
        data[key] = value
        _file_save(data)


def delete_secret(key: str) -> None:
    with _lock:
        backend = _probe_backend()
        if backend == "libsecret":
            try:
                from gi.repository import Secret

                Secret.password_clear_sync(_schema, {SCHEMA_ATTR: key}, None)
            except Exception:
                log.debug("libsecret clear failed for %s", key, exc_info=True)
        data = _file_load()
        if key in data:
            del data[key]
            if data:
                _file_save(data)
            else:
                try:
                    os.remove(_fallback_path())
                except OSError:
                    pass


def migrate_from_mapping(data: dict) -> list[str]:
    moved: list[str] = []
    for key in SECRET_KEYS:
        if key not in data:
            continue
        value = data.pop(key)
        if value and str(value).strip():
            if not get_secret(key):
                set_secret(key, str(value))
            moved.append(key)
        else:
            moved.append(key)
    return moved


def backend_name() -> str:
    with _lock:
        return _probe_backend()
