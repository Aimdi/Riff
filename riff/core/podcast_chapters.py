"""Podcasting 2.0 chapters — ad detection / auto-skip (Riff Mobile port).

Blocking network; call via ``run_async`` from the UI / service.
"""

from __future__ import annotations

import json
import logging
import re
import urllib.request
from dataclasses import dataclass

log = logging.getLogger("riff.podcast_chapters")

_UA = "Riff/1.0 (podcast-chapters; +https://github.com/Aimdi/Riff)"
_AD_NEEDLES = ("sponsor", "advert", "promo", "werbung", "anuncio")
_AD_TOKEN = re.compile(r"(^|\s)ads?(\s|:|$)", re.I)


@dataclass
class PodcastChapter:
    start_sec: float
    title: str = ""
    end_sec: float | None = None

    @property
    def is_ad(self) -> bool:
        t = (self.title or "").lower()
        if any(n in t for n in _AD_NEEDLES):
            return True
        return bool(_AD_TOKEN.search(t))


def parse_chapters_payload(data) -> list[PodcastChapter]:
    if isinstance(data, str):
        try:
            data = json.loads(data)
        except json.JSONDecodeError:
            return []
    if not isinstance(data, dict):
        return []
    rows = data.get("chapters")
    if not isinstance(rows, list):
        return []
    out: list[PodcastChapter] = []
    for raw in rows:
        if not isinstance(raw, dict):
            continue
        st = raw.get("startTime")
        if not isinstance(st, (int, float)):
            continue
        end = raw.get("endTime")
        end_sec = float(end) if isinstance(end, (int, float)) else None
        out.append(PodcastChapter(
            start_sec=float(st),
            title=str(raw.get("title") or ""),
            end_sec=end_sec,
        ))
    out.sort(key=lambda c: c.start_sec)
    return out


def fetch_chapters(url: str) -> list[PodcastChapter]:
    url = (url or "").strip()
    if not url:
        return []
    try:
        req = urllib.request.Request(url, headers={"User-Agent": _UA})
        with urllib.request.urlopen(req, timeout=20) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
        return parse_chapters_payload(raw)
    except Exception:  # noqa: BLE001
        log.debug("chapters fetch failed for %s", url, exc_info=True)
        return []


def chapter_at(chapters: list[PodcastChapter], sec: float) -> PodcastChapter | None:
    current: PodcastChapter | None = None
    for ch in chapters:
        if ch.start_sec <= sec:
            current = ch
        else:
            break
    return current


def end_of_chapter(
    chapters: list[PodcastChapter], chapter: PodcastChapter,
) -> float | None:
    if chapter.end_sec is not None:
        return float(chapter.end_sec)
    try:
        idx = chapters.index(chapter)
    except ValueError:
        return None
    if idx + 1 < len(chapters):
        return float(chapters[idx + 1].start_sec)
    return None
