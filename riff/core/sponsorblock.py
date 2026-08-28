"""SponsorBlock client — privacy-friendly hash-prefix API (Meld/Metrolist).

Blocking helpers; call via ``run_async``. Only applies to plain YouTube
``video_id`` values (not podcast_/abs_/…).
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass

log = logging.getLogger("riff.sponsorblock")

BASE = "https://sponsor.ajay.app"
# Categories useful for music videos (Meld defaults lean non-music).
DEFAULT_CATEGORIES = ("music_offtopic", "intro", "outro", "sponsor")
ALL_CATEGORIES = (
    "sponsor", "selfpromo", "interaction", "intro", "outro",
    "preview", "music_offtopic", "filler",
)
_UA = "Riff/1.0 (SponsorBlock; +https://github.com/Aimdi/Riff)"
_CACHE_TTL = 30 * 60
_cache: dict[str, tuple[float, list["Segment"]]] = {}


@dataclass
class Segment:
    category: str
    start: float
    end: float

    @property
    def label(self) -> str:
        return {
            "sponsor": "sponsor",
            "selfpromo": "self-promo",
            "intro": "intro",
            "outro": "outro",
            "music_offtopic": "non-music",
            "interaction": "interaction",
            "preview": "preview",
            "filler": "filler",
        }.get(self.category, self.category)


def is_eligible_video_id(video_id: str) -> bool:
    vid = (video_id or "").strip()
    if not vid or len(vid) < 6:
        return False
    if vid.startswith((
        "podcast_", "librivox_", "abs_", "cloud_", "local_",
    )):
        return False
    return True


def _sha256_hex(video_id: str) -> str:
    return hashlib.sha256(video_id.encode("utf-8")).hexdigest()


def parse_segments_payload(data, video_id: str) -> list[Segment]:
    """Parse hash-prefix response → segments for ``video_id``."""
    rows = data if isinstance(data, list) else []
    for entry in rows:
        if not isinstance(entry, dict):
            continue
        if str(entry.get("videoID") or "").lower() != video_id.lower():
            continue
        out: list[Segment] = []
        for raw in entry.get("segments") or []:
            if not isinstance(raw, dict):
                continue
            if str(raw.get("actionType") or "skip") != "skip":
                continue
            seg = raw.get("segment") or []
            if not isinstance(seg, list) or len(seg) < 2:
                continue
            try:
                start, end = float(seg[0]), float(seg[1])
            except (TypeError, ValueError):
                continue
            if end <= start:
                continue
            out.append(Segment(
                category=str(raw.get("category") or ""),
                start=start,
                end=end,
            ))
        out.sort(key=lambda s: s.start)
        return out
    return []


def fetch_segments(
    video_id: str,
    *,
    categories: tuple[str, ...] | list[str] = DEFAULT_CATEGORIES,
) -> list[Segment]:
    """Blocking fetch; returns [] on any failure."""
    if not is_eligible_video_id(video_id):
        return []
    cats = tuple(c for c in categories if c)
    if not cats:
        return []
    now = time.monotonic()
    cached = _cache.get(video_id)
    if cached and now - cached[0] < _CACHE_TTL:
        return [s for s in cached[1] if s.category in cats]

    prefix = _sha256_hex(video_id)[:4]
    params = [("actionType", "skip")]
    for c in ALL_CATEGORIES:
        params.append(("category", c))
    url = f"{BASE}/api/skipSegments/{prefix}?{urllib.parse.urlencode(params)}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": _UA})
        with urllib.request.urlopen(req, timeout=12) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="replace"))
    except Exception:  # noqa: BLE001
        log.debug("SponsorBlock fetch failed for %s", video_id, exc_info=True)
        return []
    all_segs = parse_segments_payload(data, video_id)
    _cache[video_id] = (now, all_segs)
    return [s for s in all_segs if s.category in cats]


def segment_at(segments: list[Segment], pos: float) -> Segment | None:
    for s in segments:
        if s.start <= pos < s.end - 0.15:
            return s
    return None
