"""Riff Rewind — narrative listening summary (Riff Mobile port)."""

from __future__ import annotations

from .library import Library


def listener_level(plays: int) -> int:
    """Gamified listener level from total plays (RiPlay / mobile formula)."""
    p = int(plays or 0)
    if p <= 0:
        return 0
    level = 0
    while 10 * ((level + 1) * (level + 1)) <= p * 2:
        level += 1
        if level > 999:
            break
    return level


def build_rewind(library: Library) -> dict:
    """All-time rewind payload. ``enough`` is False when plays < 5."""
    overview = library.stats_overview()
    plays = int(overview.get("plays") or 0)
    top_artists = library.top_artists(1)
    top_songs = library.most_played(1)
    return {
        "enough": plays >= 5,
        "plays": plays,
        "seconds": int(overview.get("seconds") or 0),
        "artists": int(overview.get("artists") or 0),
        "level": listener_level(plays),
        "top_artist": top_artists[0] if top_artists else None,
        "top_song": top_songs[0] if top_songs else None,
    }
