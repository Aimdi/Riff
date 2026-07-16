"""ListenBrainz scrobbling (listenbrainz.org — open source, free).

Submissions are best-effort: failures are logged, never surfaced as errors.
"""

from __future__ import annotations

import json
import logging
import time
import urllib.request

from .models import Track

log = logging.getLogger("riff.scrobble")

API = "https://api.listenbrainz.org/1/submit-listens"


def build_payload(track: Track, listened_at: int | None = None) -> dict:
    metadata = {
        "artist_name": track.artist or "Unknown Artist",
        "track_name": track.title,
    }
    if track.album:
        metadata["release_name"] = track.album
    return {
        "listen_type": "single",
        "payload": [{
            "listened_at": int(listened_at or time.time()),
            "track_metadata": metadata,
        }],
    }


def should_scrobble(position: float, duration: float) -> bool:
    """Standard scrobble rule: half the track or 4 minutes, whichever is
    less; never for plays under 30 seconds."""
    if position < 30:
        return False
    if position >= 240:
        return True
    return duration > 0 and position >= duration / 2


def submit(token: str, track: Track) -> None:
    """Blocking; call from a worker thread. Never raises."""
    if not token or not track.title:
        return
    try:
        req = urllib.request.Request(
            API,
            data=json.dumps(build_payload(track)).encode(),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Token {token}",
            },
        )
        with urllib.request.urlopen(req, timeout=15):
            pass
        log.info("scrobbled: %s — %s", track.title, track.artist)
    except Exception:  # noqa: BLE001 — scrobbling must never break playback
        log.warning("scrobble failed for %s", track.title, exc_info=True)
