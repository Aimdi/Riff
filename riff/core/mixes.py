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


def release_radar(
    api,
    library: Library,
    *,
    limit: int = 30,
) -> list[Track]:
    """Song-level Release Radar from followed artists (mobile ensureReleaseRadar)."""
    follows = library.followed_artists()[:20]
    if not follows:
        return []
    out: list[Track] = []
    seen: set[str] = set()
    for browse_id, name, _thumb in follows:
        try:
            artist = api.artist(browse_id)
        except Exception:  # noqa: BLE001
            continue
        for track in list(artist.songs or [])[:8]:
            if not track.video_id or track.video_id in seen:
                continue
            if not track.artists:
                track.artists = [name] if name else []
            seen.add(track.video_id)
            out.append(track)
            if len(out) >= limit:
                return out
    return out


def quick_picks(
    engine: DiscoveryEngine,
    *,
    limit: int = 20,
) -> list[Track]:
    """Dense Quick Picks shelf — recent taste → similar (mobile QP)."""
    library = engine.library
    seeds = library.recent(6) or [
        t for t, _ in library.most_played(limit=6)]
    if not seeds:
        seeds = library.favorites()[:6]
    if not seeds:
        return []
    candidates: list[tuple[Track, float]] = []
    exclude = {t.video_id for t in seeds if t.video_id}
    for seed in seeds[:6]:
        for related in engine.related_cached(seed.video_id)[:10]:
            candidates.append((related, 1.0))
        for related in engine._cooccurrence_candidates(seed.video_id)[:6]:
            candidates.append((related, 0.9))
    return engine.rank(
        candidates,
        surface="quick_picks",
        limit=limit,
        max_per_artist=2,
        exclude=exclude,
        exploration=max(0.2, min(0.5, engine.exploration())),
    )


def assemble_home_mix_rows(
    *,
    rediscover: list[Track],
    fresh: list[Track],
    daily: list[tuple[str, str, list[Track]]] | None = None,
    quick: list[Track] | None = None,
    because: list[Track] | None = None,
    max_rows: int = 3,
    min_count: int = 4,
) -> list[tuple[str, str, list[Track]]]:
    """Zone-B assembly: Daily Mixes → Quick Picks → one contextual row.

    Returns list of (id, title, tracks). Cap matches mobile ``kHomeFeedZoneBCap``.
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

    # One Daily Mixes lead row (flagship), then Quick Picks, then one contextual.
    if daily:
        # Prefer a combined "Your daily mixes" lead strip from first mix
        # that has enough tracks (mobile uniqueDailyMixLeads spirit).
        for sid, title, tracks in daily:
            take(sid, title, tracks)
            if rows:
                break
    take("quick_picks", "Quick picks", quick or [])
    # At most one contextual row (Because → Rediscover → Fresh).
    if len(rows) < max_rows:
        if because and len([t for t in because if t.video_id]) >= min_count:
            take("because", "Because you liked", because)
        elif rediscover:
            take("rediscover", "Rediscover", rediscover)
        elif fresh:
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


def load_cached_radar(library: Library) -> list[Track]:
    hit = library.cache_get("release_radar_v1")
    if not hit or not isinstance(hit, dict):
        return []
    try:
        return [Track.from_dict(d) for d in hit.get("tracks") or []]
    except (TypeError, ValueError):
        return []


def store_release_radar(library: Library, tracks: list[Track]) -> None:
    library.cache_put(
        "release_radar_v1",
        {"built_at": time.time(), "tracks": [t.to_dict() for t in tracks]},
        7 * 86400,
    )


def release_radar_stale(library: Library, *, max_age_days: float = 6.0) -> bool:
    hit = library.cache_get("release_radar_v1")
    if not hit or not isinstance(hit, dict):
        return True
    built = float(hit.get("built_at", 0) or 0)
    return (time.time() - built) > max_age_days * 86400
