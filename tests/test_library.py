import pytest

from riff.core.library import Library
from riff.core.models import Track


@pytest.fixture
def lib():
    library = Library(":memory:")
    yield library
    library.close()


def track(i=0):
    return Track(video_id=f"v{i}", title=f"Song {i}", artists=[f"Artist {i}"])


def test_favorites(lib):
    t = track()
    assert not lib.is_favorite(t.video_id)
    assert lib.toggle_favorite(t) is True
    assert lib.is_favorite(t.video_id)
    favs = lib.favorites()
    assert len(favs) == 1 and favs[0].video_id == "v0"
    assert lib.toggle_favorite(t) is False
    assert lib.favorites() == []


def test_history_dedup_and_order(lib):
    lib.record_play(track(1))
    lib.record_play(track(2))
    lib.record_play(track(1))  # played again -> should be first, once
    recent = lib.recent()
    assert [t.video_id for t in recent] == ["v1", "v2"]


def test_history_bounded(lib):
    for i in range(520):
        lib.record_play(track(i))
    assert len(lib.recent(limit=1000)) <= 500


def test_most_played(lib):
    for _ in range(3):
        lib.record_play(track(7))
    lib.record_play(track(8))
    top = lib.most_played()
    assert top[0][0].video_id == "v7"
    assert top[0][1] == 3


def test_playlists(lib):
    pid = lib.create_playlist("Chill")
    assert lib.playlists() == [(pid, "Chill", 0)]
    lib.add_to_playlist(pid, track(1))
    lib.add_to_playlist(pid, track(2))
    assert [t.video_id for t in lib.playlist_tracks(pid)] == ["v1", "v2"]
    lib.remove_from_playlist(pid, 0)
    assert [t.video_id for t in lib.playlist_tracks(pid)] == ["v2"]
    lib.add_to_playlist(pid, track(3))
    assert [t.video_id for t in lib.playlist_tracks(pid)] == ["v2", "v3"]
    lib.rename_playlist(pid, "Chill 2")
    assert lib.playlists()[0][1] == "Chill 2"
    lib.delete_playlist(pid)
    assert lib.playlists() == []


def test_playlist_folders(lib):
    fid = lib.create_folder("Workouts")
    assert lib.folders() == [(fid, "Workouts")]
    a = lib.create_playlist("Cardio", folder_id=fid)
    b = lib.create_playlist("Loose")  # root
    assert lib.playlists(folder_id=fid) == [(a, "Cardio", 0)]
    assert lib.playlists(folder_id=None) == [(b, "Loose", 0)]
    # all playlists still listed for pickers
    all_ids = {p[0] for p in lib.playlists()}
    assert all_ids == {a, b}

    lib.set_playlist_folder(b, fid)
    assert lib.playlist_folder_id(b) == fid
    assert {p[0] for p in lib.playlists(folder_id=fid)} == {a, b}
    assert lib.playlists(folder_id=None) == []

    tree = lib.playlist_tree()
    assert tree[0]["kind"] == "folder" and tree[0]["id"] == fid
    assert len(tree[0]["playlists"]) == 2

    lib.rename_folder(fid, "Gym")
    assert lib.folders()[0][1] == "Gym"
    lib.delete_folder(fid)
    assert lib.folders() == []
    # playlists survive and return to root
    assert {p[0] for p in lib.playlists(folder_id=None)} == {a, b}


def test_follows(lib):
    assert lib.followed_artists() == []
    lib.follow_artist("UC1", "Daft Punk", "http://thumb")
    lib.follow_artist("UC2", "Boards of Canada")
    assert lib.is_followed("UC1")
    ids = [f[0] for f in lib.followed_artists()]
    assert set(ids) == {"UC1", "UC2"}
    lib.unfollow_artist("UC1")
    assert not lib.is_followed("UC1")
    assert len(lib.followed_artists()) == 1


def test_dislikes(lib):
    t = track(9)
    assert not lib.is_disliked("v9")
    lib.add_dislike(t)
    assert lib.is_disliked("v9")
    assert lib.disliked_ids() == {"v9"}
    assert [d.video_id for d in lib.dislikes()] == ["v9"]
    lib.remove_dislike("v9")
    assert not lib.is_disliked("v9")


def test_stats(lib):
    for i in (1, 1, 1, 2):
        lib.record_play(track(i))
    o = lib.stats_overview()
    assert o["plays"] == 4 and o["songs"] == 2
    top = lib.top_artists()
    assert top[0] == ("Artist 1", 3)
    days = lib.plays_by_day(3)
    assert len(days) == 3
    assert days[-1][1] == 4  # all plays happened "today"


def test_find_and_replace_playlist(lib):
    assert lib.find_playlist("✨ AI Mix") is None
    pid = lib.create_playlist("✨ AI Mix")
    assert lib.find_playlist("✨ AI Mix") == pid
    lib.replace_playlist_tracks(pid, [track(1), track(2)])
    assert [t.video_id for t in lib.playlist_tracks(pid)] == ["v1", "v2"]
    # replacing again fully swaps the contents
    lib.replace_playlist_tracks(pid, [track(3)])
    assert [t.video_id for t in lib.playlist_tracks(pid)] == ["v3"]
    lib.replace_playlist_tracks(pid, [])
    assert lib.playlist_tracks(pid) == []


def test_downloads(lib, tmp_path):
    t = track(5)
    path = str(tmp_path / "song.m4a")
    lib.record_download(t, path)
    assert lib.download_path("v5") == path
    downloads = lib.downloads()
    assert downloads[0].local_path == path
    lib.remove_download("v5")
    assert lib.download_path("v5") is None
