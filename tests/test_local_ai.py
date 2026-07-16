"""Unit tests for local AI helpers (no network, no real model load)."""

from __future__ import annotations

from unittest import mock

from riff.core import local_ai


def test_model_constants():
    assert local_ai.MODEL_FILENAME.endswith(".gguf")
    assert local_ai.MODEL_LABEL
    assert local_ai.MODEL_URL.startswith("https://")
    assert local_ai.MODEL_FILENAME in local_ai.MODEL_URL


def test_status_not_installed():
    with mock.patch.object(local_ai, "runtime_ready", return_value=False), \
         mock.patch.object(local_ai, "model_file_ready", return_value=False):
        st = local_ai.status()
        assert not st.ready
        assert "not installed" in st.detail.lower()


def test_status_ready():
    with mock.patch.object(local_ai, "runtime_ready", return_value=True), \
         mock.patch.object(local_ai, "model_file_ready", return_value=True):
        st = local_ai.status()
        assert st.ready
        assert "Ready" in st.detail


def test_status_model_only():
    with mock.patch.object(local_ai, "runtime_ready", return_value=False), \
         mock.patch.object(local_ai, "model_file_ready", return_value=True):
        st = local_ai.status()
        assert not st.ready
        assert "engine" in st.detail.lower()


def test_apply_local_settings(tmp_path, monkeypatch):
    from riff import config as cfg

    path = tmp_path / "settings.json"
    store = cfg.Settings(str(path))
    monkeypatch.setattr(cfg, "settings", store)
    monkeypatch.setattr(local_ai.config, "settings", store)

    local_ai.apply_local_settings()
    assert store.get("ai_provider") == "local"


def test_model_file_ready_rejects_tiny_files(tmp_path, monkeypatch):
    tiny = tmp_path / "tiny.gguf"
    tiny.write_bytes(b"not a real model")
    monkeypatch.setattr(local_ai, "_MODEL_PATH", str(tiny))
    assert local_ai.model_file_ready() is False


def test_suggest_songs_parses_llm_output(monkeypatch):
    class FakeLLM:
        def create_chat_completion(self, **_kwargs):
            return {
                "choices": [{
                    "message": {
                        "content": '{"songs": [{"title": "Dreams", '
                                   '"artist": "Fleetwood Mac"}]}'
                    }
                }]
            }

    monkeypatch.setattr(local_ai, "_load_llm", lambda progress=None: FakeLLM())
    from riff.core.models import Track
    songs = local_ai.suggest_songs(
        [Track(video_id="1", title="A", artists=["B"])],
        [],
    )
    assert songs == [("Dreams", "Fleetwood Mac")]
