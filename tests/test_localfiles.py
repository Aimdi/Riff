from riff.core.localfiles import _parse_name, scan


def test_parse_name():
    assert _parse_name("Neil Young - Harvest Moon") == ("Neil Young", "Harvest Moon")
    assert _parse_name("random_track") == ("", "random_track")
    assert _parse_name("A - B - C") == ("A", "B - C")


def test_scan(tmp_path):
    (tmp_path / "sub").mkdir()
    (tmp_path / "Neil Young - Old Man.mp3").write_bytes(b"x")
    (tmp_path / "sub" / "ambient.flac").write_bytes(b"x")
    (tmp_path / "cover.jpg").write_bytes(b"x")
    (tmp_path / "notes.txt").write_bytes(b"x")

    tracks = scan(str(tmp_path))
    assert len(tracks) == 2
    assert tracks[0].title == "ambient" and tracks[0].artist == ""
    assert tracks[1].artist == "Neil Young" and tracks[1].title == "Old Man"
    assert all(t.local_path and t.video_id.startswith("local:") for t in tracks)


def test_scan_missing_folder():
    assert scan("/nonexistent/nowhere") == []
