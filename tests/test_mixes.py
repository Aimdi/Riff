"""Rediscover / Fresh Finds / home mix assembly (no GTK)."""

import time

from riff.core.library import Library
from riff.core.mixes import (
    assemble_home_mix_rows,
    fresh_finds,
    load_cached_home_mixes,
    rediscover_tracks,
    store_home_mixes,
)
from riff.core.models import Track


def _track(i: int, artist: str = "A") -> Track:
    return Track(
        video_id=f"v{i}", title=f"Song {i}", artists=[f"{artist}{i // 3}"])


def test_rediscover_finds_quiet_high_play_tracks():
    lib = Library(":memory:")
    try:
        now = time.time()
        # Familiar + quiet (last play 120 days ago).
        for _ in range(4):
            lib.record_play(_track(1))
        with lib._lock, lib._db:
            lib._db.execute(
                "UPDATE history SET played_at = ? WHERE video_id = ?",
                (now - 120 * 86400, "v1"),
            )
        # Recent play — must not appear.
        for _ in range(5):
            lib.record_play(_track(2))
        # Only one lifetime play — below threshold.
        lib.record_play(_track(3))
        with lib._lock, lib._db:
            lib._db.execute(
                "UPDATE history SET played_at = ? WHERE video_id = ?",
                (now - 120 * 86400, "v3"),
            )

        found = rediscover_tracks(lib, quiet_days=90, min_lifetime_plays=2)
        ids = [t.video_id for t in found]
        assert "v1" in ids
        assert "v2" not in ids
        assert "v3" not in ids
    finally:
        lib.close()


def test_assemble_home_mix_rows_caps_and_dedupes():
    red = [_track(i) for i in range(6)]
    fresh = [_track(i) for i in range(3, 12)]  # overlaps v3..v5
    rows = assemble_home_mix_rows(
        rediscover=red, fresh=fresh, max_rows=2, min_count=4)
    assert len(rows) == 2
    assert rows[0][0] == "rediscover"
    assert rows[1][0] == "fresh_finds"
    red_ids = {t.video_id for t in rows[0][2]}
    fresh_ids = {t.video_id for t in rows[1][2]}
    assert not (red_ids & fresh_ids)


def test_fresh_finds_uses_unheard_related():
    lib = Library(":memory:")
    try:
        seed = _track(0, artist="Seed")
        for _ in range(3):
            lib.record_play(seed)

        class FakeApi:
            def related_songs(self, video_id):
                return [_track(i, artist="Rel") for i in range(10, 20)]

        from riff.core.discovery import DiscoveryEngine

        engine = DiscoveryEngine(lib, FakeApi())
        found = fresh_finds(engine, limit=8, seed_count=2)
        assert found
        assert all(t.video_id.startswith("v1") for t in found)
        assert seed.video_id not in {t.video_id for t in found}
    finally:
        lib.close()


def test_home_mix_cache_roundtrip():
    lib = Library(":memory:")
    try:
        rows = [("rediscover", "Rediscover", [_track(1), _track(2)])]
        store_home_mixes(lib, rows)
        loaded = load_cached_home_mixes(lib)
        assert loaded[0][0] == "rediscover"
        assert [t.video_id for t in loaded[0][2]] == ["v1", "v2"]
    finally:
        lib.close()
