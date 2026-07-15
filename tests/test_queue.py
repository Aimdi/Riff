from riff.core.models import Track
from riff.core.queue import REPEAT_ALL, REPEAT_ONE, PlayQueue


def tracks(n):
    return [Track(video_id=f"v{i}", title=f"T{i}") for i in range(n)]


def test_sequential_playback():
    q = PlayQueue()
    q.set_tracks(tracks(3))
    assert q.current.video_id == "v0"
    assert q.next().video_id == "v1"
    assert q.next().video_id == "v2"
    assert q.next() is None
    assert q.previous().video_id == "v1"


def test_start_index():
    q = PlayQueue()
    q.set_tracks(tracks(5), start=2)
    assert q.current.video_id == "v2"
    assert q.next().video_id == "v3"


def test_repeat_all_wraps():
    q = PlayQueue()
    q.set_tracks(tracks(2))
    q.repeat = REPEAT_ALL
    assert q.next().video_id == "v1"
    assert q.next().video_id == "v0"
    assert q.previous().video_id == "v1"


def test_repeat_one_natural_vs_manual():
    q = PlayQueue()
    q.set_tracks(tracks(3))
    q.repeat = REPEAT_ONE
    # natural end repeats the same track
    assert q.next(manual=False).video_id == "v0"
    # manual skip advances
    assert q.next(manual=True).video_id == "v1"


def test_shuffle_anchors_current():
    q = PlayQueue()
    q.set_tracks(tracks(20), start=5)
    q.set_shuffle(True)
    assert q.current.video_id == "v5"
    assert q.current_index == 0
    seen = {q.current.video_id}
    while (t := q.next()) is not None:
        seen.add(t.video_id)
    assert seen == {f"v{i}" for i in range(20)}


def test_shuffle_off_restores_position():
    q = PlayQueue()
    q.set_tracks(tracks(10))
    q.set_shuffle(True)
    q.next()
    current = q.current.video_id
    q.set_shuffle(False)
    assert q.current.video_id == current
    # order is sequential again
    assert [t.video_id for t in q.tracks] == [f"v{i}" for i in range(10)]


def test_add_next_and_end():
    q = PlayQueue()
    q.set_tracks(tracks(3))
    q.next()  # at v1
    q.add_next([Track(video_id="x", title="X")])
    q.add_end([Track(video_id="y", title="Y")])
    order = [t.video_id for t in q.tracks]
    assert order == ["v0", "v1", "x", "v2", "y"]
    assert q.next().video_id == "x"


def test_remove_at():
    q = PlayQueue()
    q.set_tracks(tracks(4))
    q.next()  # at v1 (index 1)
    q.remove_at(0)  # remove v0 before current
    assert q.current.video_id == "v1"
    assert q.current_index == 0
    q.remove_at(1)  # remove v2 after current
    assert [t.video_id for t in q.tracks] == ["v1", "v3"]


def test_remove_current():
    q = PlayQueue()
    q.set_tracks(tracks(3))
    q.remove_at(0)
    assert q.current.video_id == "v1"


def test_jump_to_and_peek():
    q = PlayQueue()
    q.set_tracks(tracks(4))
    assert q.peek_next().video_id == "v1"
    assert q.jump_to(3).video_id == "v3"
    assert q.peek_next() is None
    assert q.has_next() is False


def test_empty_queue_is_safe():
    q = PlayQueue()
    assert q.current is None
    assert q.next() is None
    assert q.previous() is None
    assert q.peek_next() is None
    q.remove_at(0)
    q.set_shuffle(True)


def test_cycle_repeat():
    q = PlayQueue()
    assert q.cycle_repeat() == REPEAT_ALL
    assert q.cycle_repeat() == REPEAT_ONE
    assert q.cycle_repeat() == "off"
