"""Pure taste-model math: event weights, decay, artist normalization.

No I/O, no GTK, no globals — everything here is a deterministic function
so the taste model is trivially unit-testable. Storage lives in
core/library.py; orchestration in core/discovery.py.
"""

from __future__ import annotations

import math
import re

HALF_LIFE_DAYS = 90.0
DAY = 86400.0

# Explicit event weights (spec §2.1).
EVENT_WEIGHTS = {
    "favorite": 3.0,
    "unfavorite": -1.5,
    "playlist_add": 2.0,
    "download": 2.0,
    "follow": 5.0,
    "never_play": -4.0,
    "thumb_up": 3.0,
    "thumb_down": -3.0,
    "dismiss": -0.5,
}

# Sources where the user actively chose the song (stronger signal).
USER_SOURCES = {"user_click"}


def artist_key(name: str) -> str:
    """Normalize an artist string so affinity aggregates across YTM's
    inconsistent credits: lowercase, strip feature credits & punctuation."""
    s = (name or "").lower()
    s = re.split(r"\b(?:feat|ft|featuring|with|x)\.?\s", s)[0]
    s = re.sub(r"[^\w\s]", "", s, flags=re.UNICODE)
    return " ".join(s.split())


def decay(value: float, age_seconds: float,
          half_life_days: float = HALF_LIFE_DAYS) -> float:
    """Exponential time decay: value halves every half_life_days."""
    if age_seconds <= 0:
        return value
    return value * math.pow(0.5, age_seconds / (half_life_days * DAY))


def play_weight(listened_fraction: float | None, source: str) -> float:
    """Weight of one play/skip event from how much of it was heard."""
    f = -1.0 if listened_fraction is None else max(0.0, listened_fraction)
    if listened_fraction is None:
        base = 0.5  # end unknown (e.g. app closed) — mild positive
    elif f >= 0.85:
        base = 1.0
    elif f >= 0.30:
        base = 0.3
    elif f >= 0.10:
        base = -1.0  # skip
    else:
        base = -2.0  # quick skip
    if base > 0 and source in USER_SOURCES:
        base += 0.5  # the user chose this — stronger signal
    return base


def event_weight(event: str, listened_fraction: float | None,
                 source: str) -> float:
    if event in ("play", "skip"):
        return play_weight(listened_fraction, source)
    return EVENT_WEIGHTS.get(event, 0.0)


def score_events(events, now: float,
                 half_life_days: float = HALF_LIFE_DAYS) -> float:
    """Decayed affinity from (event, listened_fraction, source, ts) tuples."""
    total = 0.0
    for event, fraction, source, ts in events:
        w = event_weight(event, fraction, source)
        total += decay(w, now - float(ts), half_life_days)
    return total


def skip_rate(events) -> float:
    """Fraction of play events that were skips (<30% listened)."""
    plays = [(e, f) for e, f, _s, _t in events if e in ("play", "skip")]
    if not plays:
        return 0.0
    skips = sum(1 for _e, f in plays if f is not None and f < 0.30)
    return skips / len(plays)


def normalized_title_key(title: str, artist: str) -> str:
    """Kill re-uploads / “(Remastered)” dupes in candidate lists."""
    t = (title or "").lower()
    t = re.sub(r"[\(\[][^\)\]]*[\)\]]", "", t)  # parenthesized qualifiers
    t = re.sub(r"[^\w\s]", "", t)
    return " ".join(t.split()) + "::" + artist_key(artist)
