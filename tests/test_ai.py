import pytest

from riff.core.ai import build_prompt, parse_suggestions
from riff.core.models import Track


def track(title, artist):
    return Track(video_id="x", title=title, artists=[artist])


def test_build_prompt_includes_history_and_favorites():
    prompt = build_prompt(
        [track("Harvest Moon", "Neil Young")],
        [track("Dreams", "Fleetwood Mac")],
        count=15,
    )
    assert "Harvest Moon — Neil Young" in prompt
    assert "Dreams — Fleetwood Mac" in prompt
    assert "15 songs" in prompt


def test_build_prompt_handles_empty():
    prompt = build_prompt([], [])
    assert "(none)" in prompt


def test_parse_suggestions():
    text = '{"songs": [{"title": "Old Man", "artist": "Neil Young"}, ' \
           '{"title": "", "artist": "Nobody"}, ' \
           '{"title": "Rhiannon", "artist": "Fleetwood Mac"}]}'
    songs = parse_suggestions(text)
    assert songs == [("Old Man", "Neil Young"), ("Rhiannon", "Fleetwood Mac")]


def test_extract_json_plain():
    from riff.core.ai import extract_json
    assert extract_json('{"songs": []}') == '{"songs": []}'


def test_extract_json_fenced_and_wrapped():
    from riff.core.ai import extract_json
    fenced = '```json\n{"songs": [{"title": "A", "artist": "B"}]}\n```'
    assert extract_json(fenced) == '{"songs": [{"title": "A", "artist": "B"}]}'
    wrapped = 'Here you go:\n{"songs": []}\nEnjoy!'
    assert extract_json(wrapped) == '{"songs": []}'


def test_parse_suggestions_fenced():
    text = '```json\n{"songs": [{"title": "Old Man", "artist": "Neil Young"}]}\n```'
    assert parse_suggestions(text) == [("Old Man", "Neil Young")]


def test_parse_suggestions_bad_json():
    with pytest.raises(ValueError):
        parse_suggestions("not json")


def test_ai_module_imports_without_anthropic():
    # anthropic is an optional dependency — the module must import lazily.
    import importlib

    module = importlib.import_module("riff.core.ai")
    assert hasattr(module, "suggest_songs")
