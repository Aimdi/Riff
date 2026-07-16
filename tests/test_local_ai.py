"""Unit tests for local AI helpers (no network, no real Ollama)."""

from __future__ import annotations

from unittest import mock

from riff.core import local_ai


def test_model_constants():
    assert local_ai.MODEL_ID
    assert ":" in local_ai.MODEL_ID  # ollama-style tag
    assert local_ai.MODEL_LABEL
    assert local_ai.OPENAI_COMPAT_BASE.endswith("/v1")


def test_model_installed_matches_tags():
    with mock.patch.object(local_ai, "list_models", return_value=[
        "qwen2.5:3b", "llama3.2:1b",
    ]):
        assert local_ai.model_installed("qwen2.5:3b") is True
        assert local_ai.model_installed("llama3.2:1b") is True
        assert local_ai.model_installed("missing:7b") is False


def test_model_installed_prefix_variants():
    with mock.patch.object(local_ai, "list_models", return_value=[
        "qwen2.5:3b-instruct-q4_K_M",
    ]):
        assert local_ai.model_installed("qwen2.5:3b") is True


def test_status_not_installed():
    with mock.patch.object(local_ai, "find_ollama", return_value=None), \
         mock.patch.object(local_ai, "server_up", return_value=False), \
         mock.patch.object(local_ai, "model_installed", return_value=False):
        st = local_ai.status()
        assert not st.ready
        assert "not installed" in st.detail.lower()


def test_status_ready():
    with mock.patch.object(local_ai, "find_ollama", return_value="/usr/bin/ollama"), \
         mock.patch.object(local_ai, "server_up", return_value=True), \
         mock.patch.object(local_ai, "model_installed", return_value=True):
        st = local_ai.status()
        assert st.ready
        assert "Ready" in st.detail


def test_apply_local_settings(tmp_path, monkeypatch):
    from riff import config as cfg

    path = tmp_path / "settings.json"
    store = cfg.Settings(str(path))
    monkeypatch.setattr(cfg, "settings", store)
    monkeypatch.setattr(local_ai.config, "settings", store)

    local_ai.apply_local_settings()
    assert store.get("ai_provider") == "local"
    assert store.get("openai_model") == local_ai.MODEL_ID
    assert store.get("openai_base_url") == local_ai.OPENAI_COMPAT_BASE
