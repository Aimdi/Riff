"""LibriVox parse + chapter → Track.stream_url (no network)."""

from riff.core.librivox import parse_books_payload
from riff.core.library import Library
from riff.core.service import PlaybackService
import riff.core.service as service_mod
from tests.test_service import FakeApi, FakeEngine, FakeResolver, sync_run_async

SAMPLE = {
    "books": [
        {
            "id": "52",
            "title": "Letters of Two Brides",
            "description": "<p>An <b>epistolary</b> novel.</p>",
            "language": "English",
            "totaltimesecs": 32960,
            "url_librivox": "https://librivox.org/example/",
            "authors": [
                {"id": "86", "first_name": "Honoré de", "last_name": "Balzac"},
            ],
            "coverart_jpg": "https://example.com/cover.jpg",
            "sections": [
                {
                    "id": "121136",
                    "section_number": "1",
                    "title": "Letter 1",
                    "listen_url": (
                        "https://www.archive.org/download/demo/ch1_64kb.mp3"),
                    "playtime": "1764",
                },
                {
                    "id": "121137",
                    "section_number": "2",
                    "title": "Letter 2",
                    "listen_url": (
                        "https://www.archive.org/download/demo/ch2_64kb.mp3"),
                    "playtime": "790",
                },
            ],
        }
    ]
}


def test_parse_book_and_chapters():
    books = parse_books_payload(SAMPLE, with_chapters=True)
    assert len(books) == 1
    book = books[0]
    assert book.id == "52"
    assert book.title == "Letters of Two Brides"
    assert book.authors == ["Honoré de Balzac"]
    assert "epistolary" in book.description.lower()
    assert "<" not in book.description
    assert len(book.chapters) == 2
    tracks = book.chapter_tracks()
    assert tracks[0].video_id == "librivox_52_1"
    assert tracks[0].stream_url.endswith("ch1_64kb.mp3")
    assert tracks[0].album == book.title
    assert tracks[0].duration == 1764


def test_playback_librivox_stream(monkeypatch):
    monkeypatch.setattr(service_mod, "run_async", sync_run_async)
    monkeypatch.setattr(service_mod.config.settings, "set", lambda *a: None)
    engine = FakeEngine()
    resolver = FakeResolver()
    svc = PlaybackService(FakeApi(), Library(":memory:"), engine, resolver)
    book = parse_books_payload(SAMPLE, with_chapters=True)[0]
    svc.play_tracks(book.chapter_tracks(), start=1, source="audiobook")
    assert engine.played == [
        "https://www.archive.org/download/demo/ch2_64kb.mp3"]
    assert resolver.resolved == []


def test_abs_settings_defaults():
    from riff import config
    assert "abs_host" in config.DEFAULTS
    assert config.DEFAULTS["abs_host"] == ""
