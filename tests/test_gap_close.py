"""Final mobile-parity leftovers: folders, chapters, lyrics, rewind, slskd."""

import base64
from unittest import mock

from riff.core import audiobookshelf as abs_mod
from riff.core import lyrics as lyrics_mod
from riff.core import podcast_chapters as pc
from riff.core import podcast_download as pod_dl
from riff.core import rewind as rewind_mod
from riff.core import slskd as slskd_mod
from riff.core.library import Library
from riff.core.models import Track
from riff.core.podcast import PODCAST_GENRES, _shows_from_chart_entries


def test_podcast_genres_and_chart_parse():
    assert any(g[1] == "Comedy" for g in PODCAST_GENRES)
    shows = _shows_from_chart_entries([
        {
            "im:name": {"label": "Show A"},
            "im:artist": {"label": "Host"},
            "im:image": [{"label": "http://art/1.jpg"}],
            "id": {"attributes": {"im:id": "99"}},
        }
    ])
    assert shows[0].title == "Show A"
    assert shows[0].collection_id == "99"


def test_podcast_folders_roundtrip():
    lib = Library(":memory:")
    try:
        lib.subscribe_podcast("https://feed/a", "A")
        lib.subscribe_podcast("https://feed/b", "B")
        fid = lib.create_podcast_folder("Crime", "#ef4444")
        assert lib.podcast_folder_toggle(fid, "https://feed/a") is True
        assert lib.podcast_folder_feeds(fid) == ["https://feed/a"]
        assert lib.podcast_folder_toggle(fid, "https://feed/a") is False
        lib.podcast_folder_add(fid, "https://feed/b")
        folders = lib.podcast_folders()
        assert folders[0]["count"] == 1
        lib.unsubscribe_podcast("https://feed/b")
        assert "https://feed/b" not in lib.podcast_folder_feeds(fid)
        lib.delete_podcast_folder(fid)
        assert lib.podcast_folders() == []
    finally:
        lib.close()


def test_saved_audiobooks_roundtrip():
    lib = Library(":memory:")
    try:
        assert lib.toggle_saved_audiobook(
            "book-1", "Dune", author="FH", source="abs") is True
        assert lib.is_audiobook_saved("book-1")
        rows = lib.saved_audiobooks()
        assert rows[0]["title"] == "Dune"
        assert lib.toggle_saved_audiobook("book-1", "Dune") is False
        assert lib.saved_audiobooks() == []
    finally:
        lib.close()


def test_podcast_chapters_ad_skip():
    chapters = pc.parse_chapters_payload({
        "chapters": [
            {"startTime": 0, "title": "Intro"},
            {"startTime": 60, "title": "Sponsor message"},
            {"startTime": 120, "title": "Main"},
        ]
    })
    assert chapters[1].is_ad
    assert not chapters[0].is_ad
    assert pc.chapter_at(chapters, 70).title == "Sponsor message"
    assert pc.end_of_chapter(chapters, chapters[1]) == 120.0


def test_podcast_download_ext_and_dir(tmp_path):
    assert pod_dl._ext_from_url("https://cdn/ep.mp3?x=1") == ".mp3"
    assert pod_dl.podcast_download_dir(str(tmp_path)).endswith(
        "podcast_downloads")


def test_listener_level_and_rewind():
    assert rewind_mod.listener_level(0) == 0
    assert rewind_mod.listener_level(5) >= 1
    lib = Library(":memory:")
    try:
        for i in range(6):
            lib.record_play(Track(
                video_id=f"v{i}", title=f"T{i}", artists=["A"], duration=180))
        data = rewind_mod.build_rewind(lib)
        assert data["enough"] is True
        assert data["plays"] == 6
        assert data["level"] >= 1
    finally:
        lib.close()


def test_ttml_to_lrc_and_plain():
    ttml = """
    <tt><body>
      <p begin="00:01.00" end="00:02.00">
        <span begin="00:01.00">Hello</span>
        <span begin="00:01.50">world</span>
      </p>
      <p begin="12.5">Plain line</p>
    </body></tt>
    """
    lrc = lyrics_mod.ttml_to_lrc(ttml)
    assert lrc is not None
    assert "[00:01.00]Hello world" in lrc
    assert "Plain line" in lyrics_mod.ttml_to_plain(ttml)
    lines = lyrics_mod.parse_ttml(ttml)
    assert lines[0].has_words


def test_fetch_lyrics_source_order(monkeypatch):
    calls = []

    def better(*_a, **_k):
        calls.append("better")
        return None

    def lrclib(*_a, **_k):
        calls.append("lrclib")
        return lyrics_mod.LyricsResult(
            synced=[(1.0, "hi")], plain="hi", source="lrclib")

    def kugou(*_a, **_k):
        calls.append("kugou")
        return None

    monkeypatch.setattr(lyrics_mod, "fetch_better_lyrics", better)
    monkeypatch.setattr(lyrics_mod, "fetch_lrclib", lrclib)
    monkeypatch.setattr(lyrics_mod, "fetch_kugou", kugou)
    track = Track(video_id="x", title="Song", artists=["Art"])
    synced, plain = lyrics_mod.fetch_lyrics(track, source="better")
    # Continues past line-synced hits looking for word-capable TTML.
    assert calls[:2] == ["better", "lrclib"]
    assert synced[0][1] == "hi"
    assert plain == "hi"
    # Auto prefers Better first (syllable-capable).
    calls.clear()
    lyrics_mod.fetch_lyrics(track, source="auto")
    assert calls[0] == "better"


def test_kugou_decode_helper():
    raw = base64.b64encode(b"[00:01.00]line\n").decode()
    with mock.patch.object(
        lyrics_mod, "_http_json",
        return_value={"content": raw},
    ):
        text = lyrics_mod._kugou_download("1", "key")
    assert text and "[00:01.00]line" in text


def test_abs_library_folders_parse():
    libs = abs_mod.parse_libraries_payload({
        "libraries": [
            {
                "id": "lib1",
                "name": "Books",
                "mediaType": "book",
                "folders": [
                    {"id": "fold1", "fullPath": "/audiobooks"},
                ],
            }
        ]
    })
    assert libs[0].folders[0].id == "fold1"
    assert libs[0].folders[0].full_path == "/audiobooks"


def test_slskd_enqueue_posts_list():
    session = slskd_mod.SlskdSession(host="http://slskd.local", api_key="k")
    captured = {}

    def fake_http(method, url, *, api_key="", body=None, timeout=30):
        captured["method"] = method
        captured["url"] = url
        captured["body"] = body
        captured["api_key"] = api_key
        return 201, {}

    with mock.patch.object(slskd_mod, "_http_json", side_effect=fake_http):
        slskd_mod.enqueue_download(
            session, "user1", "C:\\Music\\Song.mp3", 1234)
    assert captured["method"] == "POST"
    assert "transfers/downloads/user1" in captured["url"]
    assert captured["body"] == [
        {"filename": "C:\\Music\\Song.mp3", "size": 1234}]
    assert captured["api_key"] == "k"
