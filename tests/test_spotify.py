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


# -- Web API backend -----------------------------------------------------


class FakeSpotifyApi:
    """Local HTTP stand-in for accounts.spotify.com + api.spotify.com."""

    def __init__(self):
        import http.server
        import threading

        outer = self
        self.requests = []

        class Handler(http.server.BaseHTTPRequestHandler):
            def _send(self, payload, code=200):
                body = json.dumps(payload).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_POST(self):
                outer.requests.append(
                    ("POST", self.path, self.headers.get("Authorization")))
                self._send({"access_token": "tok123", "expires_in": 3600})

            def do_GET(self):
                outer.requests.append(
                    ("GET", self.path, self.headers.get("Authorization")))
                if self.path.startswith("/v1/playlists/PL1"):
                    self._send({
                        "name": "Mega List",
                        "owner": {"display_name": "Tester"},
                        "tracks": {
                            "items": [{"track": {
                                "name": "First", "duration_ms": 200000,
                                "artists": [{"name": "A1"}]}}],
                            "next": f"{outer.base}/v1/page2",
                        },
                    })
                elif self.path == "/v1/page2":
                    self._send({
                        "items": [{"track": {
                            "name": "Second", "duration_ms": 100000,
                            "artists": [{"name": "A2"}, {"name": "A3"}]}}],
                        "next": None,
                    })
                else:
                    self._send({"error": "not found"}, 404)

            def log_message(self, *a):
                pass

        import http.server as hs
        self.httpd = hs.HTTPServer(("127.0.0.1", 0), Handler)
        self.base = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        threading.Thread(target=self.httpd.serve_forever,
                         daemon=True).start()

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


def test_fetch_api_pages_through_full_playlist():
    from riff.core import spotify as sp_mod

    fake = FakeSpotifyApi()
    try:
        sp_mod._token_cache.clear()
        result = sp_mod.fetch_api(
            "playlist", "PL1", "cid", "secret",
            token_url=f"{fake.base}/api/token",
            api_base=f"{fake.base}/v1")
        assert result.name == "Mega List"
        assert [t.title for t in result.tracks] == ["First", "Second"]
        assert result.tracks[1].artists == "A2, A3"
        assert result.tracks[0].duration == 200
        # token request used Basic auth; API calls used the Bearer token
        assert fake.requests[0][0] == "POST"
        assert fake.requests[0][2].startswith("Basic ")
        assert all(r[2] == "Bearer tok123"
                   for r in fake.requests[1:])
        # token is cached: a second fetch must not re-request it
        n_posts = sum(1 for r in fake.requests if r[0] == "POST")
        sp_mod.fetch_api("playlist", "PL1", "cid", "secret",
                         token_url=f"{fake.base}/api/token",
                         api_base=f"{fake.base}/v1")
        assert sum(1 for r in fake.requests if r[0] == "POST") == n_posts
    finally:
        fake.close()


def test_fetch_best_falls_back_to_embed(monkeypatch):
    from riff.core import spotify as sp_mod

    def boom(*a, **k):
        raise RuntimeError("api blocked (editorial playlist)")

    embed = SpotifyTrack("From Embed", "X", 100)
    monkeypatch.setattr(sp_mod, "fetch_api", boom)
    monkeypatch.setattr(
        sp_mod, "fetch",
        lambda kind, item_id: sp_mod.SpotifyList(
            name="Embedded", kind=kind, tracks=[embed]))
    result = sp_mod.fetch_best("playlist", "X1", "cid", "secret")
    assert result.name == "Embedded"


def test_fetch_best_without_credentials_uses_embed(monkeypatch):
    from riff.core import spotify as sp_mod

    called = []
    monkeypatch.setattr(
        sp_mod, "fetch_api",
        lambda *a, **k: called.append("api"))
    monkeypatch.setattr(
        sp_mod, "fetch",
        lambda kind, item_id: sp_mod.SpotifyList(
            name="E", kind=kind,
            tracks=[SpotifyTrack("T", "A", 1)]))
    result = sp_mod.fetch_best("playlist", "X1", "", "")
    assert result.name == "E"
    assert called == []
