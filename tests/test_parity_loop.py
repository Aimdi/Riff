"""Parity loop: Wave, Zone-B, sleep timer, Release Radar helpers, queue."""

from riff.core import mixes as mixes_mod
from riff.core import torrents as torrents_mod
from riff.core import wave as wave_mod
from riff.core.library import Library
from riff.core.models import Track
from riff.core.sleep_timer import SleepTimer
from riff.core.slskd import parse_responses_payload


def _t(vid: str, title: str = "T", artist: str = "A") -> Track:
    return Track(video_id=vid, title=title, artists=[artist], duration=120)


def test_zone_b_assembly_order():
    daily = [("daily_mix_1", "Daily Mix 1", [_t(f"d{i}") for i in range(8)])]
    quick = [_t(f"q{i}") for i in range(10)]
    red = [_t(f"r{i}") for i in range(8)]
    rows = mixes_mod.assemble_home_mix_rows(
        rediscover=red, fresh=[], daily=daily, quick=quick,
        max_rows=3, min_count=4)
    assert [r[0] for r in rows] == ["daily_mix_1", "quick_picks", "rediscover"]


def test_wave_seed_and_order():
    lib = Library(":memory:")
    try:
        seed = _t("seed1", "Seed")
        lib.record_play(seed)
        resolved = wave_mod.resolve_seed(lib)
        assert resolved is not None
        assert resolved.video_id == "seed1"
        ordered = wave_mod.with_seed_first(
            seed, [_t("a"), seed, _t("b")])
        assert [t.video_id for t in ordered] == ["seed1", "a", "b"]
    finally:
        lib.close()


def test_sleep_timer_minutes_and_eos():
    fired = []
    timer = SleepTimer(lambda: fired.append(1))
    timer.start_minutes(5)
    assert timer.state.active
    assert timer.state.label == "5 min"
    timer.cancel()
    assert not timer.state.active
    timer.start_end_of_song()
    assert timer.on_track_ending()
    assert not timer.state.active


def test_podcast_queue_roundtrip():
    lib = Library(":memory:")
    try:
        a = _t("podcast_aaa", "Ep A", "Show")
        a.stream_url = "https://cdn.example.com/a.mp3"
        b = _t("podcast_bbb", "Ep B", "Show")
        b.stream_url = "https://cdn.example.com/b.mp3"
        lib.podcast_queue_add(a)
        lib.podcast_queue_add(b)
        tracks = lib.podcast_queue_tracks()
        assert [t.video_id for t in tracks] == ["podcast_aaa", "podcast_bbb"]
        lib.podcast_queue_remove("podcast_aaa")
        assert [t.video_id for t in lib.podcast_queue_tracks()] == ["podcast_bbb"]
        lib.podcast_queue_clear()
        assert lib.podcast_queue_tracks() == []
    finally:
        lib.close()


def test_torrents_parse_and_slskd_parse():
    hits = torrents_mod.parse_hits([
        {
            "name": "Album FLAC",
            "infohash": "abc123",
            "size_bytes": 1024 ** 3,
            "seeders": 12,
            "leechers": 2,
        }
    ])
    assert hits[0].magnet.startswith("magnet:?xt=urn:btih:abc123")
    assert "GB" in hits[0].size_label
    sl = parse_responses_payload([
        {
            "username": "user1",
            "files": [{"filename": "Song.mp3", "size": 1000}],
        }
    ])
    assert sl[0].label == "Song.mp3"


def test_release_radar_cache():
    lib = Library(":memory:")
    try:
        assert mixes_mod.release_radar_stale(lib)
        tracks = [_t("rr1"), _t("rr2")]
        mixes_mod.store_release_radar(lib, tracks)
        loaded = mixes_mod.load_cached_radar(lib)
        assert [t.video_id for t in loaded] == ["rr1", "rr2"]
        assert not mixes_mod.release_radar_stale(lib)
    finally:
        lib.close()
