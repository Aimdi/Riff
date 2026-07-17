"""DiscoveryEngine pipeline: constraints, learning, caching (spec §2.2)."""

from riff.core.discovery import DiscoveryEngine
from riff.core.library import Library
from riff.core.models import Track


class FakeSettings:
    def __init__(self, values=None):
        self.values = values or {}

    def get(self, key, default=None):
        return self.values.get(key, default)


class FakeApi:
    def __init__(self, related=None):
        self.related = related or {}
        self.calls = []

    def related_songs(self, video_id):
        self.calls.append(video_id)
        return self.related.get(video_id, [])


def _t(vid, title=None, artist="Artist"):
    return Track(video_id=vid, title=title or vid, artists=[artist],
                 duration=200)


def _engine(library=None, api=None, exploration=0.3):
    lib = library or Library(":memory:")
    return DiscoveryEngine(lib, api or FakeApi(),
                           FakeSettings({"exploration": exploration})), lib


def test_artist_cap_and_dedupe():
    engine, lib = _engine()
    candidates = [(_t(f"a{i}", f"Song {i}", "Same Artist"), 1.0)
                  for i in range(5)]
    candidates += [(_t("b1", "Other Song", "Other"), 1.0),
                   (_t("b2", "Other Song (Remastered)", "Other"), 1.0)]
    picked = engine.rank(candidates, surface="test", limit=10)
    same = [t for t in picked if t.artists == ["Same Artist"]]
    assert len(same) == 2  # cap
    others = [t for t in picked if t.artists == ["Other"]]
    assert len(others) == 1  # remaster deduped


def test_never_play_and_recent_are_dropped():
    engine, lib = _engine()
    bad = _t("bad", "Banned")
    lib.add_dislike(bad)
    recent = _t("rec", "Recent")
    lib.log_event(recent, "play", source="queue", listened_fraction=1.0)
    fresh = _t("new", "Fresh")
    picked = engine.rank([(bad, 1.0), (recent, 1.0), (fresh, 1.0)],
                         surface="test", limit=10)
    ids = [t.video_id for t in picked]
    assert "bad" not in ids
    assert ids[0] == "new"  # recent penalized below fresh


def test_skipped_artist_sinks_in_radio():
    """Skipping an artist 3× measurably lowers their radio frequency."""
    engine, lib = _engine(exploration=0.0)
    for _ in range(3):
        lib.log_event(_t("s1", "Skipped", "Skippy"), "play",
                      source="radio", listened_fraction=0.05)
    lib.log_event(_t("l1", "Loved", "Lovely"), "favorite")
    seed = _t("seed", "Seed", "SeedArtist")
    raw = [_t("c1", "Candidate 1", "Skippy"),
           _t("c2", "Candidate 2", "Lovely")]
    out = engine.smart_radio_batch(seed, raw, history_window=[])
    assert [t.artists[0] for t in out][0] == "Lovely"


def test_smart_radio_never_repeats_session_tracks():
    engine, lib = _engine()
    session = [_t("s1"), _t("s2")]
    raw = [_t("s1"), _t("s2"), _t("n1"), _t("n2", artist="B")]
    out = engine.smart_radio_batch(_t("seed"), raw, history_window=session)
    ids = {t.video_id for t in out}
    assert ids == {"n1", "n2"}


def test_unheard_only_and_impression_rotation():
    engine, lib = _engine()
    heard = _t("h1", "Heard")
    lib.log_event(heard, "play", source="queue", listened_fraction=1.0)
    fresh1, fresh2 = _t("f1", "Fresh1", "A1"), _t("f2", "Fresh2", "A2")
    picked = engine.rank([(heard, 1.0), (fresh1, 1.0), (fresh2, 1.0)],
                         surface="fresh", limit=1, unheard_only=True)
    assert len(picked) == 1 and picked[0].video_id in ("f1", "f2")
    first = picked[0].video_id
    # the shown track was impression-logged → next unheard-only pick rotates
    picked2 = engine.rank([(fresh1, 1.0), (fresh2, 1.0)],
                          surface="fresh", limit=1, unheard_only=True)
    assert picked2 and picked2[0].video_id != first


def test_similar_songs_uses_cache_and_cooccurrence():
    api = FakeApi(related={"seed": [_t("r1", "Rel 1", "RA"),
                                    _t("r2", "Rel 2", "RB")]})
    engine, lib = _engine(api=api)
    seed = _t("seed", "Seed Song", "Seedy")
    out1 = engine.similar_songs(seed, limit=10)
    assert {t.video_id for t in out1} == {"r1", "r2"}
    assert api.calls == ["seed"]
    # second call is served from the api_cache — no new network call
    engine.similar_songs(seed, limit=10)
    assert api.calls == ["seed"]
    # the related lookup fed the co-occurrence graph
    assert lib.cooccurring("seed")


def test_affinity_reflects_events_end_to_end():
    lib = Library(":memory:")
    from riff.core import taste

    lib.log_event(_t("x", "X", "Fav Artist"), "favorite")
    lib.log_event(_t("y", "Y", "Skip Artist"), "play",
                  source="radio", listened_fraction=0.02)
    assert lib.artist_affinity(taste.artist_key("Fav Artist")) > 0
    assert lib.artist_affinity(taste.artist_key("Skip Artist")) < 0
