from riff.core.models import Track
from riff.core.scrobble import build_payload, should_scrobble


def test_should_scrobble_rules():
    assert not should_scrobble(20, 300)      # under 30s: never
    assert not should_scrobble(60, 300)      # under half
    assert should_scrobble(150, 300)         # half reached
    assert should_scrobble(240, 100000)      # 4-minute rule
    assert not should_scrobble(100, 0)       # unknown duration, under 4 min
    assert should_scrobble(250, 0)           # unknown duration, over 4 min


def test_build_payload():
    t = Track(video_id="v", title="Dreams", artists=["Fleetwood Mac"],
              album="Rumours")
    p = build_payload(t, listened_at=1000)
    assert p["listen_type"] == "single"
    meta = p["payload"][0]["track_metadata"]
    assert meta == {"artist_name": "Fleetwood Mac", "track_name": "Dreams",
                    "release_name": "Rumours"}
    assert p["payload"][0]["listened_at"] == 1000


def test_build_payload_minimal():
    t = Track(video_id="v", title="Untitled")
    meta = build_payload(t)["payload"][0]["track_metadata"]
    assert meta["artist_name"] == "Unknown Artist"
    assert "release_name" not in meta
