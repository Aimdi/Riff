"""Local-first music discovery.

Sections are computed from the *local* library (favorites, play counts,
dislikes) and anonymous per-song lookups — the taste profile never leaves
the machine; each outgoing request is a stateless "similar to this one
song" query.
"""

from __future__ import annotations

import logging
import random as _random

log = logging.getLogger("riff.discover")


def build_sections(library, api, *, rng=None, seeds: int = 3,
                   per_section: int = 8) -> list[tuple[str, list]]:
    """Returns [(section_title, tracks)] of things you have NOT played.

    - "Because you liked X": radio around a few random favorites /
      most-played songs, minus dislikes and everything already known.
    - "More from <top artist>": your #1 artist's popular songs you
      haven't listened to yet.
    """
    rng = rng or _random
    banned = set(library.disliked_ids())
    favorites = library.favorites()
    most_played = [t for t, _plays in library.most_played(20)]

    pool_by_id = {}
    for t in most_played + favorites:
        if t.video_id and t.video_id not in banned:
            pool_by_id.setdefault(t.video_id, t)
    pool = list(pool_by_id.values())
    if not pool:
        return []

    known = ({t.video_id for t in library.recent(200)}
             | {t.video_id for t in favorites})
    seen: set[str] = set()
    sections: list[tuple[str, list]] = []

    for seed in rng.sample(pool, min(seeds, len(pool))):
        try:
            similar = api.radio(seed.video_id)
        except Exception:  # noqa: BLE001 — one dead seed must not kill the page
            log.warning("radio failed for seed %s", seed.video_id,
                        exc_info=True)
            continue
        fresh = [t for t in similar
                 if t.video_id
                 and t.video_id != seed.video_id
                 and t.video_id not in banned
                 and t.video_id not in known
                 and t.video_id not in seen]
        if not fresh:
            continue
        seen.update(t.video_id for t in fresh)
        sections.append(
            (f"Because you liked “{seed.title}”", fresh[:per_section]))

    # More from your most-listened artist — the deep cuts you skipped.
    counts: dict[tuple[str, str], int] = {}
    for t in most_played + favorites:
        for aid, name in zip(t.artist_ids, t.artists):
            if aid and name:
                counts[(aid, name)] = counts.get((aid, name), 0) + 1
    if counts:
        (aid, name), _n = max(counts.items(), key=lambda kv: kv[1])
        try:
            artist = api.artist(aid)
            fresh = [t for t in artist.songs
                     if t.video_id not in known
                     and t.video_id not in banned
                     and t.video_id not in seen][:per_section]
            if fresh:
                sections.append((f"More from {name}", fresh))
        except Exception:  # noqa: BLE001
            log.warning("artist lookup failed for %s", name, exc_info=True)

    return sections
