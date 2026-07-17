"""DiscoveryEngine — the shared candidate → score → filter pipeline.

Every discovery surface (similar songs, smart radio, mixes) goes through
the same steps: gather candidates with a source confidence, score them
against the local taste model, apply constraints (artist caps, dedupe,
recency/impression penalties, never-play drops), then log impressions.

UI-free and deterministic under an injected RNG; network access happens
only through the injected api object and is cached in the library's
api_cache table (related songs: 7-day TTL).
"""

from __future__ import annotations

import logging
import math

from . import taste
from .models import Track

log = logging.getLogger("riff.discovery")

RELATED_TTL = 7 * 86400


def _spread_artists(tracks: list[Track]) -> list[Track]:
    """Break up same-artist runs: swap an offender with the next track by
    a different artist. Order otherwise stays score-descending."""
    def key(t: Track) -> str:
        return taste.artist_key((t.artists or [""])[0])

    out = list(tracks)
    for i in range(1, len(out)):
        if key(out[i]) == key(out[i - 1]):
            for j in range(i + 1, len(out)):
                if key(out[j]) != key(out[i - 1]):
                    out[i], out[j] = out[j], out[i]
                    break
    return out


class DiscoveryEngine:
    def __init__(self, library, api, settings=None):
        self.library = library
        self.api = api
        self._settings = settings

    # -- knobs ---------------------------------------------------------------

    def exploration(self) -> float:
        """0 = familiar, 1 = adventurous."""
        if self._settings is None:
            from .. import config

            self._settings = config.settings
        try:
            return max(0.0, min(1.0, float(
                self._settings.get("exploration", 0.3))))
        except (TypeError, ValueError):
            return 0.3

    # -- candidate sources ---------------------------------------------------

    def related_cached(self, video_id: str) -> list[Track]:
        key = f"related:{video_id}"
        hit = self.library.cache_get(key)
        if hit is not None:
            return [Track.from_dict(d) for d in hit]
        try:
            tracks = self.api.related_songs(video_id)
        except Exception:  # noqa: BLE001
            log.warning("related lookup failed for %s", video_id,
                        exc_info=True)
            return []
        self.library.cache_put(
            key, [t.to_dict() for t in tracks], RELATED_TTL)
        # feed the local similarity graph: seed co-occurs with its related
        for t in tracks[:10]:
            self.library.add_cooccurrence(video_id, t.video_id, 0.25)
        return tracks

    def _cooccurrence_candidates(self, video_id: str) -> list[Track]:
        out = []
        for other_id, _w in self.library.cooccurring(video_id, 25):
            track = self.library.track_by_id(other_id)
            if track is not None:
                out.append(track)
        return out

    # -- scoring + constraints ----------------------------------------------

    def _score(self, track: Track, confidence: float, *, exploration: float,
               heard: set[str], recent: set[str], shown: set[str]) -> float:
        key = taste.artist_key((track.artists or [""])[0])
        affinity = math.tanh(self.library.artist_affinity(key) / 10.0)
        skip_rate = self.library.artist_skip_rate(key)
        unheard = track.video_id not in heard

        score = 1.0 * confidence
        # familiar-lean weights affinity, adventurous-lean weights novelty
        score += (1.0 - exploration) * 0.8 * affinity
        score += exploration * (0.9 if unheard else -0.3)
        score -= 1.5 * skip_rate
        if track.video_id in recent:
            score -= 2.0
        if track.video_id in shown:
            score -= 1.0
        return score

    def rank(self, candidates: list[tuple[Track, float]], *, surface: str,
             limit: int, unheard_only: bool = False,
             max_per_artist: int = 2, exclude: set[str] | None = None,
             exploration: float | None = None,
             log_impressions: bool = True) -> list[Track]:
        """The pipeline: score → constraints → greedy diversify → log."""
        exploration = (self.exploration() if exploration is None
                       else exploration)
        banned = set(self.library.disliked_ids())
        recent = self.library.recently_played_ids(7)
        heard = self.library.recently_played_ids(3650)
        shown = self.library.recent_impressions(14)
        exclude = exclude or set()

        seen_ids: set[str] = set()
        seen_titles: set[str] = set()
        scored: list[tuple[float, Track]] = []
        for track, confidence in candidates:
            vid = track.video_id
            if not vid or vid in banned or vid in exclude:
                continue
            if vid in seen_ids:
                continue
            title_key = taste.normalized_title_key(
                track.title, (track.artists or [""])[0])
            if title_key in seen_titles:
                continue
            if unheard_only and (vid in heard or vid in shown):
                continue
            seen_ids.add(vid)
            seen_titles.add(title_key)
            scored.append((self._score(
                track, confidence, exploration=exploration,
                heard=heard, recent=recent, shown=shown), track))

        scored.sort(key=lambda pair: pair[0], reverse=True)

        # greedy re-rank with a per-artist cap (MMR-style diversification)
        picked: list[Track] = []
        per_artist: dict[str, int] = {}
        for _s, track in scored:
            if len(picked) >= limit:
                break
            key = taste.artist_key((track.artists or [""])[0])
            if per_artist.get(key, 0) >= max_per_artist:
                continue
            picked.append(track)
            per_artist[key] = per_artist.get(key, 0) + 1
        picked = _spread_artists(picked)

        if log_impressions and picked:
            self.library.log_impressions(
                [t.video_id for t in picked], surface)
        return picked

    # -- entry points ---------------------------------------------------------

    def similar_songs(self, seed: Track, limit: int = 25,
                      unheard_only: bool = False) -> list[Track]:
        """Songs like this one: YTM related feed blended with the local
        co-occurrence graph."""
        candidates = [(t, 1.0) for t in self.related_cached(seed.video_id)]
        candidates += [(t, 0.9)
                       for t in self._cooccurrence_candidates(seed.video_id)]
        return self.rank(
            candidates, surface="similar", limit=limit,
            unheard_only=unheard_only, exclude={seed.video_id})

    def smart_radio_batch(self, seed: Track, raw: list[Track],
                          history_window: list[Track]) -> list[Track]:
        """Post-process a raw radio batch (spec §3.5): dedupe against the
        session and the last 7 days, cap artists, drop never-play and
        high-skip artists, re-rank by the exploration setting."""
        session_ids = {t.video_id for t in history_window}
        candidates = [(t, 1.0) for t in raw]
        return self.rank(
            candidates, surface="radio", limit=len(raw),
            exclude=session_ids | {seed.video_id},
            max_per_artist=2, log_impressions=False)
