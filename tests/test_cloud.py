"""Subsonic Cloud parse + stream URL → Track (no network)."""

import hashlib

from riff.core import cloud as cloud_mod
from riff.core.library import Library
from riff.core.service import PlaybackService
import riff.core.service as service_mod
from tests.test_service import FakeApi, FakeEngine, FakeResolver, sync_run_async

ALBUM_LIST = {
    "albumList2": {
        "album": [
            {
                "id": "al1",
                "name": "Random Access Memories",
                "artist": "Daft Punk",
                "coverArt": "al1",
                "songCount": 13,
                "year": 2013,
            }
        ]
    }
}

RANDOM = {
    "randomSongs": {
        "song": {
            "id": "s1",
            "title": "Get Lucky",
            "artist": "Daft Punk",
            "album": "RAM",
            "coverArt": "c1",
            "duration": 248,
        }
    }
}

ALBUM_DETAIL = {
    "album": {
        "id": "al1",
        "name": "Random Access Memories",
        "artist": "Daft Punk",
        "coverArt": "al1",
        "song": [
            {
                "id": "s1",
                "title": "Get Lucky",
                "artist": "Daft Punk",
                "album": "RAM",
                "duration": 248,
            },
            {
                "id": "s2",
                "title": "Instant Crush",
                "artist": "Daft Punk",
                "album": "RAM",
                "duration": 337,
            },
        ],
    }
}


def test_normalize_and_auth_token():
    assert cloud_mod.normalize_host("music.example.com/") == (
        "https://music.example.com")
    params = cloud_mod.auth_params("u", "secret", legacy=False)
    assert params["u"] == "u"
    assert "t" in params and "s" in params
    expected = hashlib.md5(f"secret{params['s']}".encode()).hexdigest()
    assert params["t"] == expected
    legacy = cloud_mod.auth_params("u", "ab", legacy=True)
    assert legacy["p"] == "enc:6162"


def test_parse_lists_and_album():
    albums = cloud_mod.parse_album_list(ALBUM_LIST)
    assert albums[0].name == "Random Access Memories"
    songs = cloud_mod.parse_random_songs(RANDOM)
    assert songs[0].title == "Get Lucky"
    assert songs[0].duration == 248
    coll = cloud_mod.parse_album_detail(ALBUM_DETAIL, album_id="al1")
    assert len(coll.songs) == 2
    assert coll.subtitle == "Daft Punk"


def test_song_to_track_and_playback(monkeypatch):
    monkeypatch.setattr(service_mod, "run_async", sync_run_async)
    monkeypatch.setattr(service_mod.config.settings, "set", lambda *a: None)
    session = cloud_mod.CloudSession(
        host="https://music.example.com",
        username="u",
        password="p",
        legacy_auth=True,
    )
    songs = cloud_mod.parse_random_songs(RANDOM)
    track = cloud_mod.song_to_track(session, songs[0])
    assert track.video_id == "cloud_s1"
    assert "stream.view" in track.stream_url
    assert "id=s1" in track.stream_url
    assert "p=enc%3A" in track.stream_url or "p=enc:" in track.stream_url

    engine = FakeEngine()
    resolver = FakeResolver()
    svc = PlaybackService(FakeApi(), Library(":memory:"), engine, resolver)
    svc.play_tracks([track], start=0, source="cloud")
    assert engine.played
    assert "stream.view" in engine.played[0]
    assert resolver.resolved == []


def test_cloud_settings_defaults():
    from riff import config
    assert config.DEFAULTS["cloud_host"] == ""
    assert config.DEFAULTS["cloud_legacy_auth"] is False
