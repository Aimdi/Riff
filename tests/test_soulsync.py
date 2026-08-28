"""SoulSync parse helpers + mocked HTTP client."""

import json

from riff.core import soulsync as ss


SEARCH_BODY = {
    "success": True,
    "data": {
        "tracks": [
            {
                "id": "1",
                "name": "Nightcall",
                "artists": ["Kavinsky"],
                "album": "OutRun",
                "duration_ms": 253000,
                "image_url": "https://example.com/a.jpg",
                "source": "spotify",
            },
            {"id": "2", "title": "", "artists": []},
        ]
    },
}


def test_parse_tracks_and_request_query():
    tracks = ss.parse_tracks_payload(SEARCH_BODY)
    assert len(tracks) == 1
    assert tracks[0].name == "Nightcall"
    assert tracks[0].artist_label == "Kavinsky"
    assert tracks[0].request_query == "Kavinsky - Nightcall"
    assert tracks[0].duration_ms == 253000


def test_normalize_host():
    assert ss.normalize_host("ss.example.com/") == "https://ss.example.com"


def test_connect_search_request(monkeypatch):
    calls: list[tuple[str, str]] = []

    def fake_http(method, url, *, api_key, body=None, timeout=25):
        calls.append((method, url))
        if url.endswith("/system/status"):
            return 200, {"success": True, "data": {"ok": True}}
        if url.endswith("/search/tracks"):
            assert body["query"] == "nightcall"
            return 200, SEARCH_BODY
        if url.endswith("/request"):
            assert "Nightcall" in body["query"]
            return 202, {"success": True, "data": {"request_id": "r1"}}
        if "/downloads" in url:
            return 200, {
                "success": True,
                "data": {"downloads": [{"title": "Nightcall", "status": "done"}]},
            }
        return 404, {}

    monkeypatch.setattr(ss, "_http_json", fake_http)
    session = ss.connect("https://ss.example.com", "key")
    assert session.host == "https://ss.example.com"
    tracks = ss.search_tracks(session, "nightcall")
    assert tracks[0].name == "Nightcall"
    rid = ss.request_download(session, tracks[0].request_query)
    assert rid == "r1"
    dls = ss.list_downloads(session)
    assert dls[0]["status"] == "done"
    assert any("/system/status" in u for _m, u in calls)


def test_auth_failure(monkeypatch):
    monkeypatch.setattr(
        ss, "_http_json",
        lambda *a, **k: (401, {"success": False}))
    try:
        ss.connect("https://ss.example.com", "bad")
        assert False, "expected auth error"
    except RuntimeError as exc:
        assert "authentication" in str(exc).lower()


def test_settings_defaults():
    from riff import config
    assert config.DEFAULTS["soulsync_host"] == ""
    assert config.DEFAULTS["soulsync_api_key"] == ""
