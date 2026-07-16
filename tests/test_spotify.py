"""Spotify import: URL parsing, embed-page parsing, YT Music matching."""

import json

from riff.core.models import Track
from riff.core.spotify import (
    SpotifyTrack,
    match_on_ytmusic,
    parse_embed_html,
    parse_spotify_url,
    score_candidate,
)


def test_parse_spotify_url_variants():
    pid = "37i9dQZF1DXcBWIGoYBM5M"
    assert parse_spotify_url(
        f"https://open.spotify.com/playlist/{pid}") == ("playlist", pid)
    assert parse_spotify_url(
        f"https://open.spotify.com/playlist/{pid}?si=abc&pt=x"
    ) == ("playlist", pid)
    assert parse_spotify_url(
        f"https://open.spotify.com/intl-de/album/{pid}") == ("album", pid)
    assert parse_spotify_url(f"spotify:playlist:{pid}") == ("playlist", pid)
    assert parse_spotify_url("check this: https://open.spotify.com/track/"
                             f"{pid} 🔥") == ("track", pid)
    assert parse_spotify_url("https://example.com/playlist/x") is None
    assert parse_spotify_url("") is None
    assert parse_spotify_url(None) is None


def _embed_html(entity: dict) -> str:
    # Mirrors the real page: __NEXT_DATA__ JSON with the entity nested a
    # few levels deep (exact path varies; the parser searches the tree).
    payload = {"props": {"pageProps": {"state": {"data": {"entity": entity}}}}}
    return ("<html><body><script id=\"__NEXT_DATA__\" type="
            "\"application/json\">" + json.dumps(payload) +
            "</script></body></html>")


def test_parse_embed_html_playlist():
    entity = {
        "name": "Today's Top Hits",
        "subtitle": "Spotify",
        "trackList": [
            {"title": "Song A", "subtitle": "Artist One", "duration": 201000},
            {"title": "Song B", "subtitle": "Artist Two, Artist Three",
             "duration": 185},
            {"title": "", "subtitle": "ghost"},  # skipped
        ],
    }
    sp = parse_embed_html(_embed_html(entity))
    assert sp.name == "Today's Top Hits"
    assert len(sp.tracks) == 2
    assert sp.tracks[0].duration == 201  # ms normalized to seconds
    assert sp.tracks[1].duration == 185  # already seconds
    assert sp.tracks[1].artists == "Artist Two, Artist Three"


def test_parse_embed_html_failures():
    for bad in ("<html>no data</html>",
                _embed_html({"name": "empty", "trackList": []})):
        try:
            parse_embed_html(bad)
            raise AssertionError("expected RuntimeError")
        except RuntimeError:
            pass


def test_score_prefers_matching_duration():
    sp = SpotifyTrack(title="Blinding Lights", artists="The Weeknd",
                      duration=200)
    good = score_candidate(sp, "Blinding Lights", "The Weeknd", 201)
    cover = score_candidate(sp, "Blinding Lights (Piano Cover)",
                            "SomePianist", 145)
    assert good > 0.9
    assert cover < good - 0.25


class FakeApi:
    def __init__(self, catalog):
        self.catalog = catalog
        self.queries = []

    def search(self, query, kind=None):
        self.queries.append(query)
        return {"songs": self.catalog.get(query, [])}


def _t(vid, title, artist, dur):
    return Track(video_id=vid, title=title, artists=[artist], duration=dur)


def test_match_on_ytmusic_matches_and_misses():
    sp_tracks = [
        SpotifyTrack("Song A", "Artist One", 200),
        SpotifyTrack("Rare Bootleg", "Nobody", 313),
    ]
    api = FakeApi({
        "Song A Artist One": [
            _t("v1", "Song A", "Artist One", 199),
            _t("v2", "Song A (Sped Up)", "Remixer", 150),
        ],
        "Rare Bootleg Nobody": [],
    })
    progress = []
    matched, missed = match_on_ytmusic(
        api, sp_tracks, progress=lambda d, t: progress.append((d, t)))
    assert [t.video_id for t in matched] == ["v1"]
    assert [s.title for s in missed] == ["Rare Bootleg"]
    assert progress == [(1, 2), (2, 2)]


def test_match_survives_search_exceptions():
    class BoomApi:
        def search(self, query, kind=None):
            raise RuntimeError("network down")

    matched, missed = match_on_ytmusic(
        BoomApi(), [SpotifyTrack("A", "B", 100)])
    assert matched == []
    assert len(missed) == 1
