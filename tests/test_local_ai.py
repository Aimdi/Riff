"""Unit tests for local AI helpers (no network, no real model load)."""

from __future__ import annotations

from unittest import mock

from riff.core import local_ai


def test_catalog_has_recommended():
    assert any(m.recommended for m in local_ai.MODELS)
    assert local_ai.DEFAULT_MODEL_ID in local_ai._MODELS_BY_ID
    rec = local_ai.get_model(local_ai.DEFAULT_MODEL_ID)
    assert rec.recommended
    assert rec.url.startswith("https://")
    assert rec.filename.endswith(".gguf")


def test_all_models_have_unique_ids_and_files():
    ids = [m.id for m in local_ai.MODELS]
    files = [m.filename for m in local_ai.MODELS]
    assert len(ids) == len(set(ids))
    assert len(files) == len(set(files))


def test_get_model_fallback():
    assert local_ai.get_model("nope-not-real").id == local_ai.DEFAULT_MODEL_ID


def test_status_not_installed():
    m = local_ai.get_model("qwen2.5-1.5b")
    with mock.patch.object(local_ai, "runtime_ready", return_value=False), \
         mock.patch.object(local_ai, "model_file_ready", return_value=False):
        st = local_ai.status(m)
        assert not st.ready
        assert "not installed" in st.detail.lower()
        assert st.model.id == m.id


def test_status_ready():
    m = local_ai.get_model("qwen2.5-3b")
    with mock.patch.object(local_ai, "runtime_ready", return_value=True), \
         mock.patch.object(local_ai, "model_file_ready", return_value=True):
        st = local_ai.status(m)
        assert st.ready
        assert "Ready" in st.detail


def test_set_selected_model_unloads_on_change(tmp_path, monkeypatch):
    from riff import config as cfg

    path = tmp_path / "settings.json"
    store = cfg.Settings(str(path))
    monkeypatch.setattr(cfg, "settings", store)
    monkeypatch.setattr(local_ai.config, "settings", store)

    local_ai._llm = object()
    local_ai._llm_model_id = "qwen2.5-1.5b"
    local_ai.set_selected_model("qwen2.5-3b")
    assert store.get("local_ai_model") == "qwen2.5-3b"
    assert local_ai._llm is None
    assert local_ai._llm_model_id is None


def test_apply_local_settings(tmp_path, monkeypatch):
    from riff import config as cfg

    path = tmp_path / "settings.json"
    store = cfg.Settings(str(path))
    monkeypatch.setattr(cfg, "settings", store)
    monkeypatch.setattr(local_ai.config, "settings", store)

    local_ai.apply_local_settings()
    assert store.get("ai_provider") == "local"
    assert store.get("local_ai_model") in local_ai._MODELS_BY_ID


def test_model_file_ready_rejects_tiny_files(tmp_path, monkeypatch):
    m = local_ai.get_model("qwen2.5-1.5b")
    tiny = tmp_path / m.filename
    tiny.write_bytes(b"not a real model")
    # LocalModel.path is a property on the dataclass instance — patch
    # model_file_ready's path via a mock model-like object.
    fake = mock.Mock()
    fake.path = str(tiny)
    fake.min_bytes = m.min_bytes
    assert local_ai.model_file_ready(fake) is False


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
    monkeypatch.setattr(
        local_ai, "selected_model",
        lambda: local_ai.get_model("qwen2.5-3b"))
    from riff.core.models import Track
    songs = local_ai.suggest_songs(
        [Track(video_id="1", title="A", artists=["B"])],
        [],
    )
    assert songs == [("Dreams", "Fleetwood Mac")]
