"""Seamless “For you” song picks for Home.

Order of preference (handled by the UI layer):
  1. Cached AI Mix playlist
  2. Fresh AI Mix (if a provider is ready)
  3. This module — radio seeded from listening taste (no API key, always works)
"""

from __future__ import annotations

import logging

from .api import MusicApi
from .library import Library
from .models import Track

log = logging.getLogger("riff.suggestions")


def taste_seeds(library: Library, limit: int = 6) -> list[Track]:
    """Tracks that best represent the user's taste right now."""
    seeds: list[Track] = []
    seen: set[str] = set()

    def add(track: Track | None) -> None:
        if track is None or not track.video_id or track.video_id in seen:
            return
        if library.is_disliked(track.video_id):
            return
        seen.add(track.video_id)
        seeds.append(track)

    for track, _plays in library.most_played(limit):
        add(track)
    for track in library.favorites()[:limit]:
        add(track)
    for track in library.recent(limit):
        add(track)
    return seeds[:limit]


def radio_for_you(api: MusicApi, library: Library, limit: int = 12) -> list[Track]:
    """Build a For-you list from YouTube Music radio around taste seeds.

    Blocking — call via run_async. Never raises; returns [] on total failure.
    """
    seeds = taste_seeds(library)
    if not seeds:
        return []

    disliked = library.disliked_ids()
    out: list[Track] = []
    seen: set[str] = {t.video_id for t in seeds}

    for seed in seeds:
        if len(out) >= limit:
            break
        try:
            related = api.radio(seed.video_id, limit=10)
        except Exception:  # noqa: BLE001 — try the next seed
            log.debug("radio failed for %s", seed.video_id, exc_info=True)
            continue
        for track in related:
            if not track.video_id or track.video_id in seen:
                continue
            if track.video_id in disliked:
                continue
            seen.add(track.video_id)
            out.append(track)
            if len(out) >= limit:
                break
    return out
