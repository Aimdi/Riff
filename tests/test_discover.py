"""Local-first discovery sections: seeding, filtering, dedupe."""

import random

from riff.core.discover import build_sections
from riff.core.library import Library
from riff.core.models import Artist, Track


def _t(vid, title="T", artist="A", aid=""):
    return Track(video_id=vid, title=title, artists=[artist],
                 artist_ids=[aid], duration=180)


class FakeApi:
    def __init__(self, radio_map=None, artists=None):
        self.radio_map = radio_map or {}
        self.artists = artists or {}
        self.radio_calls = []

    def radio(self, video_id, limit=25):
        self.radio_calls.append(video_id)
        return self.radio_map.get(video_id, [])

    def artist(self, channel_id):
        return self.artists[channel_id]


def _library_with_taste():
    lib = Library(":memory:")
    fav = _t("fav1", "Loved Song", "Best Artist", "UC1")
    lib.toggle_favorite(fav)
    for _ in range(3):
        lib.record_play(fav)
    lib.add_dislike(_t("bad1", "Hated"))
    return lib


def test_sections_filter_known_banned_and_dedupe():
    lib = _library_with_taste()
    api = FakeApi(
        radio_map={"fav1": [
            _t("fav1"),          # the seed itself — excluded
            _t("bad1"),          # disliked — excluded
            _t("new1", "Fresh One"),
            _t("new2", "Fresh Two"),
        ]},
        artists={"UC1": Artist(
            browse_id="UC1", name="Best Artist",
            songs=[_t("fav1"), _t("new1"), _t("deep1", "Deep Cut")])},
    )
    sections = build_sections(lib, api, rng=random.Random(7))
    titles = [s[0] for s in sections]
    assert titles[0] == "Because you liked “Loved Song”"
    ids = [t.video_id for t in sections[0][1]]
    assert ids == ["new1", "new2"]
    # top-artist section skips the favorite AND the already-suggested new1
    assert titles[1] == "More from Best Artist"
    assert [t.video_id for t in sections[1][1]] == ["deep1"]


def test_empty_library_returns_no_sections():
    lib = Library(":memory:")
    assert build_sections(lib, FakeApi()) == []


def test_radio_failure_does_not_kill_the_page():
    lib = _library_with_taste()

    class BoomApi(FakeApi):
        def radio(self, video_id, limit=25):
            raise RuntimeError("offline")

    api = BoomApi(artists={"UC1": Artist(
        browse_id="UC1", name="Best Artist",
        songs=[_t("deep1", "Deep Cut")])})
    sections = build_sections(lib, api, rng=random.Random(7))
    assert [s[0] for s in sections] == ["More from Best Artist"]


def test_disliked_seed_is_never_used():
    lib = Library(":memory:")
    bad = _t("bad1", "Hated")
    lib.toggle_favorite(bad)
    lib.add_dislike(bad)
    api = FakeApi(radio_map={"bad1": [_t("x1")]})
    assert build_sections(lib, api) == []
    assert api.radio_calls == []
