"""LibriVox audiobooks — discover + chapter streams (desktop playable).

Riff Mobile's Discover tab is Apple→Audible (browse-only). Desktop plays
public-domain LibriVox via Archive.org ``listen_url`` → ``Track.stream_url``.
"""

from __future__ import annotations

import json
import logging
import re
import urllib.parse
import urllib.request
from dataclasses import dataclass, field

from .models import Track

log = logging.getLogger("riff.librivox")

_UA = "Riff/1.0 (audiobooks; +https://github.com/Aimdi/Riff)"
_API = "https://librivox.org/api/feed/audiobooks/"


@dataclass
class AudiobookChapter:
    id: str
    index: int
    title: str
    stream_url: str
    duration: int = 0

    def to_track(self, book: "Audiobook") -> Track:
        return Track(
            video_id=f"librivox_{book.id}_{self.index}",
            title=self.title or f"Chapter {self.index}",
            artists=list(book.authors),
            album=book.title,
            duration=int(self.duration or 0),
            thumbnail=book.cover,
            stream_url=self.stream_url,
        )


@dataclass
class Audiobook:
    id: str
    title: str
    authors: list[str] = field(default_factory=list)
    cover: str = ""
    description: str = ""
    language: str = ""
    totaltimesecs: int = 0
    url_librivox: str = ""
    chapters: list[AudiobookChapter] = field(default_factory=list)

    @property
    def author(self) -> str:
        return ", ".join(a for a in self.authors if a)

    def chapter_tracks(self) -> list[Track]:
        return [c.to_track(self) for c in self.chapters if c.stream_url]


def _http_json(url: str, *, timeout: float = 30) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8", errors="replace"))


def _strip_html(text: str) -> str:
    text = re.sub(r"(?is)<(script|style).*?>.*?</\1>", "", text or "")
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _author_name(raw) -> str:
    if isinstance(raw, dict):
        first = (raw.get("first_name") or "").strip()
        last = (raw.get("last_name") or "").strip()
        return " ".join(p for p in (first, last) if p)
    return str(raw or "").strip()


def _parse_book(raw: dict, *, with_chapters: bool = False) -> Audiobook:
    authors = [_author_name(a) for a in (raw.get("authors") or [])]
    authors = [a for a in authors if a]
    cover = (
        raw.get("coverart_jpg")
        or raw.get("coverart_thumbnail")
        or ""
    )
    try:
        total = int(raw.get("totaltimesecs") or 0)
    except (TypeError, ValueError):
        total = 0
    book = Audiobook(
        id=str(raw.get("id") or ""),
        title=str(raw.get("title") or "Audiobook"),
        authors=authors,
        cover=str(cover),
        description=_strip_html(str(raw.get("description") or "")),
        language=str(raw.get("language") or ""),
        totaltimesecs=total,
        url_librivox=str(raw.get("url_librivox") or ""),
    )
    if with_chapters:
        chapters: list[AudiobookChapter] = []
        for sec in raw.get("sections") or []:
            url = (sec.get("listen_url") or "").strip()
            if not url:
                continue
            try:
                idx = int(sec.get("section_number") or len(chapters) + 1)
            except (TypeError, ValueError):
                idx = len(chapters) + 1
            try:
                dur = int(float(sec.get("playtime") or 0))
            except (TypeError, ValueError):
                dur = 0
            chapters.append(AudiobookChapter(
                id=str(sec.get("id") or f"{book.id}-{idx}"),
                index=idx,
                title=str(sec.get("title") or f"Section {idx}"),
                stream_url=url,
                duration=dur,
            ))
        chapters.sort(key=lambda c: c.index)
        book.chapters = chapters
    return book


def browse_books(*, limit: int = 40, offset: int = 0) -> list[Audiobook]:
    qs = urllib.parse.urlencode({
        "format": "json",
        "limit": str(limit),
        "offset": str(offset),
        "coverart": "1",
    })
    data = _http_json(f"{_API}?{qs}")
    return [_parse_book(b) for b in (data.get("books") or []) if b.get("id")]


def search_books(term: str, *, limit: int = 40) -> list[Audiobook]:
    term = (term or "").strip()
    if not term:
        return []
    # LibriVox matches title OR author when both params are set separately;
    # try title first, then author if thin.
    qs = urllib.parse.urlencode({
        "format": "json",
        "title": term,
        "limit": str(limit),
        "coverart": "1",
    })
    data = _http_json(f"{_API}?{qs}")
    books = [_parse_book(b) for b in (data.get("books") or []) if b.get("id")]
    if len(books) >= 3:
        return books[:limit]
    qs2 = urllib.parse.urlencode({
        "format": "json",
        "author": term,
        "limit": str(limit),
        "coverart": "1",
    })
    data2 = _http_json(f"{_API}?{qs2}")
    seen = {b.id for b in books}
    for raw in data2.get("books") or []:
        book = _parse_book(raw)
        if book.id and book.id not in seen:
            books.append(book)
            seen.add(book.id)
    return books[:limit]


def book_detail(book_id: str) -> Audiobook:
    qs = urllib.parse.urlencode({
        "format": "json",
        "id": str(book_id),
        "extended": "1",
        "coverart": "1",
    })
    data = _http_json(f"{_API}?{qs}")
    books = data.get("books") or []
    if not books:
        raise LookupError(f"LibriVox book {book_id} not found")
    return _parse_book(books[0], with_chapters=True)


def parse_books_payload(data: dict, *, with_chapters: bool = False) -> list[Audiobook]:
    """Test helper: parse a LibriVox API JSON body."""
    return [
        _parse_book(b, with_chapters=with_chapters)
        for b in (data.get("books") or [])
        if b.get("id")
    ]
