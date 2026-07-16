from riff.core.lyrics import line_index_at, parse_lrc


def test_parse_lrc_basic():
    text = "[00:12.00]First line\n[00:15.30]Second line\n[01:02.5]Third"
    lines = parse_lrc(text)
    assert lines == [(12.0, "First line"), (15.3, "Second line"), (62.5, "Third")]


def test_parse_lrc_multiple_timestamps_per_line():
    lines = parse_lrc("[00:10.00][00:50.00]la la")
    assert lines == [(10.0, "la la"), (50.0, "la la")]


def test_parse_lrc_skips_metadata_and_garbage():
    text = "[ar:Artist]\n[ti:Title]\nno timestamp here\n[00:05.00]ok"
    lines = parse_lrc(text)
    assert lines == [(5.0, "ok")]


def test_parse_lrc_sorts_and_handles_empty():
    text = "[00:30.00]later\n[00:10.00]earlier"
    assert [t for t, _ in parse_lrc(text)] == [10.0, 30.0]
    assert parse_lrc("") == []
    assert parse_lrc(None) == []


def test_line_index_at():
    lines = [(10.0, "a"), (20.0, "b"), (30.0, "c")]
    assert line_index_at(lines, 5) == -1
    assert line_index_at(lines, 10) == 0
    assert line_index_at(lines, 19.9) == 0
    assert line_index_at(lines, 25) == 1
    assert line_index_at(lines, 99) == 2
    assert line_index_at([], 10) == -1
