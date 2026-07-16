"""Tests for seamless For-you suggestion helpers."""

from __future__ import annotations

from unittest import mock

from riff.core.library import Library
from riff.core.models import Track
from riff.core.suggestions import radio_for_you, taste_seeds


def track(i, title=None):
    return Track(
        video_id=f"v{i}",
        title=title or f"Song {i}",
        artists=[f"Artist {i}"],
    )


def test_taste_seeds_prefers_most_played_and_skips_dislikes():
    lib = Library(":memory:")
    for _ in range(3):
        lib.record_play(track(1))
    lib.record_play(track(2))
    lib.add_favorite(track(3))
    lib.add_dislike(track(2))
    seeds = taste_seeds(lib, limit=5)
    ids = [t.video_id for t in seeds]
    assert "v1" in ids
    assert "v3" in ids
    assert "v2" not in ids
    lib.close()


def test_radio_for_you_merges_related():
    lib = Library(":memory:")
    lib.record_play(track(1))
    related = [track(10), track(11), track(1)]  # v1 already seed — skip

    api = mock.Mock()
    api.radio.return_value = related
    out = radio_for_you(api, lib, limit=5)
    assert [t.video_id for t in out] == ["v10", "v11"]
    lib.close()


def test_radio_for_you_empty_without_seeds():
    lib = Library(":memory:")
    api = mock.Mock()
    assert radio_for_you(api, lib) == []
    api.radio.assert_not_called()
    lib.close()
