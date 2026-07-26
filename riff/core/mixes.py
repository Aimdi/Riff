"""Local discovery mixes — Rediscover / Fresh Finds (Riff Mobile parity).

UI-free; network only via DiscoveryEngine for Fresh Finds.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from .models import Track

if TYPE_CHECKING:
    from .discovery import DiscoveryEngine
    from .library import Library


def rediscover_tracks(
    library: Library,
    *,
    quiet_days: int = 90,
    min_lifetime_plays: int = 2,
    limit: int = 30,
) -> list[Track]:
    """High-play tracks that have been quiet for a while (mobile rediscoverIds)."""
    return library.rediscover_tracks(
        quiet_days=quiet_days,
        min_lifetime_plays=min_lifetime_plays,
        limit=limit,
    )


def fresh_finds(
    engine: DiscoveryEngine,
    *,
    limit: int = 24,
    seed_count: int = 8,
) -> list[Track]:
    """Unheard related songs seeded from local taste (mobile Fresh Finds)."""
    library = engine.library
    seeds: list[Track] = []
    seen: set[str] = set()
    for track, _plays in library.most_played(limit=seed_count):
        if track.video_id and track.video_id not in seen:
            seeds.append(track)
            seen.add(track.video_id)
    for track in library.favorites()[:seed_count]:
        if track.video_id and track.video_id not in seen:
            seeds.append(track)
            seen.add(track.video_id)
    if not seeds:
        return []

    candidates: list[tuple[Track, float]] = []
    for seed in seeds[:seed_count]:
        for related in engine.related_cached(seed.video_id)[:12]:
            candidates.append((related, 0.85))
        for related in engine._cooccurrence_candidates(seed.video_id)[:8]:
            candidates.append((related, 0.95))

    return engine.rank(
        candidates,
        surface="fresh_finds",
        limit=limit,
        unheard_only=True,
        max_per_artist=2,
        exclude=seen,
        exploration=max(0.45, engine.exploration()),
    )


def daily_mixes(
    engine: DiscoveryEngine,
    *,
    mix_count: int = 3,
    tracks_per: int = 16,
) -> list[tuple[str, str, list[Track]]]:
    """Lightweight Daily Mixes — one mix per taste seed cluster (mobile MFY)."""
    from .suggestions import taste_seeds

    library = engine.library
    seeds = taste_seeds(library, limit=mix_count * 2)
    if len(seeds) < 2:
        return []
    out: list[tuple[str, str, list[Track]]] = []
    used: set[str] = {t.video_id for t in seeds}
    for i, seed in enumerate(seeds[:mix_count], start=1):
        candidates = [
            (t, 1.0) for t in engine.related_cached(seed.video_id)[:20]]
        candidates += [
            (t, 0.9) for t in engine._cooccurrence_candidates(seed.video_id)[:10]]
        ranked = engine.rank(
            candidates,
            surface=f"daily_mix_{i}",
            limit=tracks_per,
            max_per_artist=2,
            exclude=used,
            exploration=min(0.55, max(0.25, engine.exploration())),
        )
        if len(ranked) < 6:
            continue
        used.update(t.video_id for t in ranked)
        artist = (seed.artists or ["Your taste"])[0]
        title = f"Daily Mix {i}"
        if artist:
            title = f"Daily Mix {i} · {artist}"
        out.append((f"daily_mix_{i}", title, ranked))
    return out


def assemble_home_mix_rows(
    *,
    rediscover: list[Track],
    fresh: list[Track],
    daily: list[tuple[str, str, list[Track]]] | None = None,
    max_rows: int = 4,
    min_count: int = 4,
) -> list[tuple[str, str, list[Track]]]:
    """Pick up to ``max_rows`` personal mix strips (mobile Zone-B spirit).

    Returns list of (id, title, tracks).
    """
    rows: list[tuple[str, str, list[Track]]] = []
    used: set[str] = set()

    def take(section_id: str, title: str, tracks: list[Track]) -> None:
        if len(rows) >= max_rows:
            return
        picked = [t for t in tracks if t.video_id and t.video_id not in used]
        if len(picked) < min_count:
            return
        picked = picked[:12]
        used.update(t.video_id for t in picked)
        rows.append((section_id, title, picked))

    # Daily Mix leads first (flagship), then Rediscover, then Fresh Finds.
    for sid, title, tracks in daily or []:
        take(sid, title, tracks)
    take("rediscover", "Rediscover", rediscover)
    take("fresh_finds", "Fresh Finds", fresh)
    return rows


def home_mixes_stale(library: Library, *, max_age_days: float = 1.0) -> bool:
    """True when cached home mixes should be rebuilt."""
    hit = library.cache_get("home_mixes_v1")
    if not hit or not isinstance(hit, dict):
        return True
    built = float(hit.get("built_at", 0) or 0)
    return (time.time() - built) > max_age_days * 86400


def load_cached_home_mixes(library: Library) -> list[tuple[str, str, list[Track]]]:
    hit = library.cache_get("home_mixes_v1")
    if not hit or not isinstance(hit, dict):
        return []
    out: list[tuple[str, str, list[Track]]] = []
    for row in hit.get("rows") or []:
        try:
            sid = str(row["id"])
            title = str(row["title"])
            tracks = [Track.from_dict(d) for d in row.get("tracks") or []]
        except (KeyError, TypeError, ValueError):
            continue
        if tracks:
            out.append((sid, title, tracks))
    return out


def store_home_mixes(
    library: Library, rows: list[tuple[str, str, list[Track]]],
) -> None:
    payload = {
        "built_at": time.time(),
        "rows": [
            {
                "id": sid,
                "title": title,
                "tracks": [t.to_dict() for t in tracks],
            }
            for sid, title, tracks in rows
        ],
    }
    library.cache_put("home_mixes_v1", payload, 7 * 86400)
