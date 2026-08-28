"""Audiobookshelf parse + stream URL → Track (no network)."""

from riff.core import audiobookshelf as abs_mod
from riff.core.library import Library
from riff.core.service import PlaybackService
import riff.core.service as service_mod
from tests.test_service import FakeApi, FakeEngine, FakeResolver, sync_run_async

ITEMS = {
    "results": [
        {
            "id": "book-1",
            "media": {
                "metadata": {
                    "title": "Dune",
                    "authorName": "Frank Herbert",
                    "subtitle": "Book 1",
                }
            },
        }
    ]
}

ITEM_DETAIL = {
    "id": "book-1",
    "media": {
        "metadata": {
            "title": "Dune",
            "authorName": "Frank Herbert",
            "description": "Desert planet.",
        },
        "audioFiles": [
            {
                "ino": "99",
                "index": 0,
                "duration": 120.5,
                "metadata": {"filename": "01.mp3"},
            }
        ],
    },
}

PLAY_SESSION = {
    "id": "sess-1",
    "currentTime": 12,
    "audioTracks": [
        {
            "index": 0,
            "title": "Chapter 1",
            "contentUrl": "/api/items/book-1/file/99",
            "duration": 120.5,
        },
        {
            "index": 1,
            "title": "Chapter 2",
            "contentUrl": "/api/items/book-1/file/100",
            "duration": 200,
        },
    ],
}


def test_normalize_and_stream_url():
    assert abs_mod.normalize_host("abs.example.com/") == (
        "https://abs.example.com")
    url = abs_mod.stream_url(
        "https://abs.example.com", "tok&en", "/api/items/1/file/2")
    assert url.startswith("https://abs.example.com/api/items/1/file/2?")
    assert "token=tok%26en" in url


def test_parse_items_and_play_to_tracks():
    books = abs_mod.parse_items_payload(ITEMS)
    assert books[0].title == "Dune"
    assert books[0].author == "Frank Herbert"
    detail = abs_mod.parse_play_payload(
        ITEM_DETAIL, PLAY_SESSION, item_id="book-1")
    assert detail.session_id == "sess-1"
    assert len(detail.tracks) == 2
    tracks = detail.to_tracks("https://abs.example.com", "secret")
    assert tracks[0].video_id == "abs_book-1_0"
    assert tracks[0].stream_url.endswith("token=secret")
    assert tracks[0].album == "Dune"
    assert tracks[0].duration == 120


def test_fallback_audio_files_when_session_empty():
    detail = abs_mod.parse_play_payload(
        ITEM_DETAIL, {"id": "s", "audioTracks": []}, item_id="book-1")
    assert len(detail.tracks) == 1
    assert detail.tracks[0].content_url.endswith("/file/99")


def test_prefer_book_library():
    libs = abs_mod.parse_libraries_payload({
        "libraries": [
            {"id": "a", "name": "Podcasts", "mediaType": "podcast"},
            {"id": "b", "name": "Books", "mediaType": "book"},
        ]
    })
    preferred = abs_mod.prefer_book_library(libs)
    assert preferred is not None
    assert preferred.id == "b"


def test_playback_abs_stream(monkeypatch):
    monkeypatch.setattr(service_mod, "run_async", sync_run_async)
    monkeypatch.setattr(service_mod.config.settings, "set", lambda *a: None)
    engine = FakeEngine()
    resolver = FakeResolver()
    svc = PlaybackService(FakeApi(), Library(":memory:"), engine, resolver)
    detail = abs_mod.parse_play_payload(
        ITEM_DETAIL, PLAY_SESSION, item_id="book-1")
    tracks = detail.to_tracks("https://abs.example.com", "tok")
    svc.play_tracks(tracks, start=0, source="audiobook")
    assert engine.played
    assert engine.played[0].startswith(
        "https://abs.example.com/api/items/book-1/file/99")
    assert resolver.resolved == []


def test_abs_settings_defaults():
    from riff import config
    assert config.DEFAULTS["abs_token"] == ""
    assert config.DEFAULTS["abs_library_id"] == ""
