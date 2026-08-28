"""Perf / UI helpers exercised after live cloud testing."""

from collections import OrderedDict

from riff.core.library import Library
from riff.core.models import Track


def test_playlist_thumbnails_cheap():
    lib = Library(":memory:")
    try:
        pid = lib.create_playlist("Mix")
        for i in range(5):
            lib.add_to_playlist(pid, Track(
                video_id=f"v{i}", title=f"T{i}", artists=["A"],
                thumbnail=f"https://img/{i}.jpg", duration=100))
        thumbs = lib.playlist_thumbnails(pid, 3)
        assert thumbs == [
            "https://img/0.jpg", "https://img/1.jpg", "https://img/2.jpg"]
    finally:
        lib.close()


def test_cover_cache_lru_policy():
    cache: OrderedDict[str, int] = OrderedDict()
    limit = 3

    def put(key: str, val: int) -> None:
        if key in cache:
            cache.move_to_end(key)
        cache[key] = val
        while len(cache) > limit:
            cache.popitem(last=False)

    put("a", 1)
    put("b", 2)
    put("c", 3)
    put("a", 11)  # refresh
    put("d", 4)   # should drop b (oldest unused)
    assert list(cache.keys()) == ["c", "a", "d"]
    assert "b" not in cache
