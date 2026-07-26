"""Riff Wave — one-tap personal radio (Riff Mobile startRiffWave port).

UI-free seed resolution + playlist assembly. Call via ``run_async``.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from .models import Track

if TYPE_CHECKING:
    from .api import MusicApi
    from .discovery import DiscoveryEngine
    from .library import Library

log = logging.getLogger("riff.wave")


def resolve_seed(
    library: Library,
    *,
    current: Track | None = None,
    daily_leads: list[Track] | None = None,
    quick_picks: list[Track] | None = None,
) -> Track | None:
    """Seed priority: current → daily lead → quick pick → recent → favorite."""
    if current and current.video_id:
        return current
    for track in daily_leads or []:
        if track.video_id:
            return track
    for track in quick_picks or []:
        if track.video_id:
            return track
    recent = library.recent(1)
    if recent:
        return recent[0]
    favs = library.favorites()
    if favs:
        return favs[0]
    played = library.most_played(limit=1)
    if played:
        return played[0][0]
    return None


def with_seed_first(seed: Track, tracks: list[Track]) -> list[Track]:
    out = [seed]
    seen = {seed.video_id}
    for t in tracks:
        if t.video_id and t.video_id not in seen:
            out.append(t)
            seen.add(t.video_id)
    return out


def build_wave(
    api: MusicApi,
    library: Library,
    discovery: DiscoveryEngine,
    *,
    current: Track | None = None,
    limit: int = 25,
) -> list[Track]:
    """Assemble a Wave playlist (blocking — network)."""
    from . import mixes as mixes_mod

    cached = mixes_mod.load_cached_home_mixes(library)
    daily_leads: list[Track] = []
    quick: list[Track] = []
    for sid, _title, tracks in cached:
        if sid.startswith("daily_mix") and tracks:
            daily_leads.append(tracks[0])
        if sid == "quick_picks":
            quick = list(tracks)

    seed = resolve_seed(
        library, current=current, daily_leads=daily_leads, quick_picks=quick)
    if seed is None:
        return []

    # 1) smart radio via related + local graph
    try:
        related = discovery.similar_songs(seed, limit=limit)
        if len(related) >= 8:
            return with_seed_first(seed, related)[: limit + 1]
    except Exception:  # noqa: BLE001
        log.debug("wave similar failed", exc_info=True)

    # 2) YTM watch/radio playlist
    try:
        radio = api.radio(seed.video_id)
        if radio:
            ranked = discovery.smart_radio_batch(
                seed, radio, history_window=[seed])
            if ranked:
                return with_seed_first(seed, ranked)[: limit + 1]
            return with_seed_first(seed, radio)[: limit + 1]
    except Exception:  # noqa: BLE001
        log.debug("wave radio failed", exc_info=True)

    # 3) daily mix fallback
    for sid, _title, tracks in cached:
        if sid.startswith("daily_mix") and len(tracks) >= 4:
            return with_seed_first(seed, tracks)[: limit + 1]

    return [seed]
