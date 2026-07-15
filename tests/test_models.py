from riff.core.models import (
    Track,
    _best_thumbnail,
    format_duration,
    parse_duration,
    upscale_thumbnail,
)


def test_parse_duration():
    assert parse_duration("3:25") == 205
    assert parse_duration("1:02:03") == 3723
    assert parse_duration("0:59") == 59
    assert parse_duration("59") == 59
    assert parse_duration("garbage") == 0
    assert parse_duration(None) == 0
    assert parse_duration("1:2:3:4") == 0


def test_format_duration():
    assert format_duration(205) == "3:25"
    assert format_duration(3723) == "1:02:03"
    assert format_duration(0) == "0:00"
    assert format_duration(None) == "0:00"
    assert format_duration(-5) == "0:00"
    assert format_duration(59.9) == "0:59"


def test_best_thumbnail_prefers_size():
    thumbs = [
        {"url": "small", "width": 60},
        {"url": "medium", "width": 226},
        {"url": "large", "width": 544},
        {"url": "huge", "width": 1200},
    ]
    assert _best_thumbnail(thumbs, prefer=544) == "large"
    assert _best_thumbnail([{"url": "only", "width": 60}]) == "only"
    assert _best_thumbnail([]) == ""
    assert _best_thumbnail(None) == ""


def test_upscale_thumbnail():
    url = "https://lh3.googleusercontent.com/abc=w60-h60-l90-rj"
    assert upscale_thumbnail(url, 544) == (
        "https://lh3.googleusercontent.com/abc=w544-h544-l90-rj"
    )
    other = "https://i.ytimg.com/vi/x/hqdefault.jpg"
    assert upscale_thumbnail(other) == other


def test_track_from_yt_search_shape():
    item = {
        "videoId": "abc123",
        "title": "Get Lucky",
        "artists": [
            {"name": "Daft Punk", "id": "UC1"},
            {"name": "Pharrell Williams", "id": "UC2"},
        ],
        "album": {"name": "Random Access Memories", "id": "MPRE1"},
        "duration": "6:09",
        "thumbnails": [{"url": "u", "width": 226}],
    }
    t = Track.from_yt(item)
    assert t.video_id == "abc123"
    assert t.artist == "Daft Punk, Pharrell Williams"
    assert t.album_id == "MPRE1"
    assert t.duration == 369
    assert t.thumbnail == "u"


def test_track_from_yt_handles_missing_fields():
    t = Track.from_yt({"videoId": "x", "title": "T"})
    assert t.video_id == "x"
    assert t.artist == ""
    assert t.album == ""
    assert t.duration == 0


def test_track_roundtrip():
    t = Track(video_id="v", title="T", artists=["A"], duration=100)
    t2 = Track.from_dict(t.to_dict())
    assert t2 == t
