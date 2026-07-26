"""Podcast episode resume rules (Riff Mobile PodcastProgressService port).

Pure helpers — no network, no ``gi``. Persistence lives in ``Library``.
"""

from __future__ import annotations

from .models import Track

# Ignore the first 15s; clear when nearly finished (last 20s or ≥98%).
MIN_SAVE_MS = 15_000
FINISH_TAIL_MS = 20_000
FINISH_RATIO = 0.98
# Only auto-seek when the saved position is meaningfully into the episode.
MIN_RESUME_SEC = 5.0


def is_podcast_track(track: Track | None) -> bool:
    if track is None:
        return False
    return (track.video_id or "").startswith("podcast_")


def is_finished(position_ms: int, duration_ms: int) -> bool:
    if duration_ms <= 0 or position_ms < 0:
        return False
    if position_ms >= duration_ms - FINISH_TAIL_MS:
        return True
    return position_ms >= duration_ms * FINISH_RATIO


def should_persist(position_ms: int, duration_ms: int) -> bool:
    """True when position should be stored (not finished, past MIN_SAVE_MS)."""
    if duration_ms <= 0:
        return False
    if is_finished(position_ms, duration_ms):
        return False
    return position_ms >= MIN_SAVE_MS


def progress_fraction(position_ms: int, duration_ms: int) -> float | None:
    if duration_ms <= 0:
        return None
    return max(0.0, min(1.0, position_ms / duration_ms))


def resume_seconds(position_ms: int, duration_ms: int) -> float | None:
    """Seconds to seek on play, or None to start from the beginning."""
    if duration_ms <= 0 or position_ms <= 0:
        return None
    if is_finished(position_ms, duration_ms):
        return None
    sec = position_ms / 1000.0
    if sec < MIN_RESUME_SEC:
        return None
    return sec


def track_from_progress(row: dict) -> Track | None:
    """Rebuild a playable Track from a stored progress row."""
    eid = str(row.get("episode_id") or "")
    url = str(row.get("stream_url") or "")
    if not eid.startswith("podcast_") or not url.startswith(
            ("http://", "https://")):
        return None
    try:
        dur_ms = int(row.get("duration_ms") or 0)
    except (TypeError, ValueError):
        dur_ms = 0
    artist = str(row.get("artist") or "")
    return Track(
        video_id=eid,
        title=str(row.get("title") or "Episode"),
        artists=[artist] if artist else [],
        album=artist,
        duration=max(0, dur_ms // 1000),
        thumbnail=str(row.get("artwork") or ""),
        stream_url=url,
    )
