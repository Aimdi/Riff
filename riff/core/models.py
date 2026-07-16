"""Plain data models shared between the API layer, library and UI."""

from __future__ import annotations

import re
from dataclasses import dataclass, field, asdict


def _best_thumbnail(thumbnails: list[dict] | None, prefer: int = 544) -> str:
    """Pick the thumbnail closest to (but preferably >=) the wanted size."""
    if not thumbnails:
        return ""
    best = None
    for t in thumbnails:
        url = t.get("url")
        if not url:
            continue
        w = t.get("width") or 0
        if best is None:
            best = (w, url)
            continue
        bw = best[0]
        # Prefer the smallest width that is >= prefer; else the largest overall.
        if (bw < prefer and w > bw) or (w >= prefer and (bw < prefer or w < bw)):
            best = (w, url)
    return best[1] if best else ""


def upscale_thumbnail(url: str, size: int = 544) -> str:
    """YouTube Music thumbnails encode their size in the URL; request a bigger
    one. Only the size numbers are rewritten — other flags in the parameter
    block (padding, format, …) must be preserved or some googleusercontent
    variants return errors."""
    if "googleusercontent.com" not in url and "ggpht.com" not in url:
        return url
    new = re.sub(r"=w\d+-h\d+", f"=w{size}-h{size}", url, count=1)
    if new == url:
        new = re.sub(r"=s\d+", f"=s{size}", url, count=1)
    return new


@dataclass
class Track:
    video_id: str
    title: str
    artists: list[str] = field(default_factory=list)
    artist_ids: list[str] = field(default_factory=list)
    album: str = ""
    album_id: str = ""
    duration: int = 0  # seconds
    thumbnail: str = ""
    local_path: str = ""  # set when downloaded for offline playback

    @property
    def artist(self) -> str:
        return ", ".join(a for a in self.artists if a)

    @property
    def duration_text(self) -> str:
        return format_duration(self.duration)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Track":
        return cls(
            video_id=d.get("video_id", ""),
            title=d.get("title", ""),
            artists=list(d.get("artists") or []),
            artist_ids=list(d.get("artist_ids") or []),
            album=d.get("album", "") or "",
            album_id=d.get("album_id", "") or "",
            duration=int(d.get("duration") or 0),
            thumbnail=d.get("thumbnail", "") or "",
            local_path=d.get("local_path", "") or "",
        )

    @classmethod
    def from_yt(cls, item: dict) -> "Track":
        """Build a Track from the many shapes ytmusicapi returns."""
        artists, artist_ids = [], []
        for a in item.get("artists") or []:
            name = a.get("name")
            if name:
                artists.append(name)
                artist_ids.append(a.get("id") or "")
        album = item.get("album") or {}
        if isinstance(album, str):
            album = {"name": album}
        duration = item.get("duration_seconds") or 0
        if not duration and item.get("duration"):
            duration = parse_duration(item["duration"])
        if not duration and item.get("lengthSeconds"):
            duration = int(item["lengthSeconds"])
        return cls(
            video_id=item.get("videoId") or "",
            title=item.get("title") or "",
            artists=artists,
            artist_ids=artist_ids,
            album=(album or {}).get("name") or "",
            album_id=(album or {}).get("id") or "",
            duration=int(duration),
            thumbnail=_best_thumbnail(item.get("thumbnails")),
        )


@dataclass
class Album:
    browse_id: str
    title: str
    artists: list[str] = field(default_factory=list)
    year: str = ""
    thumbnail: str = ""
    track_count: int = 0
    tracks: list[Track] = field(default_factory=list)

    @property
    def artist(self) -> str:
        return ", ".join(a for a in self.artists if a)


@dataclass
class Artist:
    browse_id: str
    name: str
    thumbnail: str = ""
    description: str = ""
    songs: list[Track] = field(default_factory=list)
    albums: list[Album] = field(default_factory=list)
    singles: list[Album] = field(default_factory=list)


@dataclass
class Playlist:
    playlist_id: str
    title: str
    author: str = ""
    thumbnail: str = ""
    track_count: int = 0
    tracks: list[Track] = field(default_factory=list)


@dataclass
class HomeSection:
    title: str
    # Mixed contents: Track / Album / Playlist / Artist
    items: list = field(default_factory=list)


def parse_duration(text: str) -> int:
    """'3:25' -> 205, '1:02:03' -> 3723. Returns 0 on garbage."""
    try:
        parts = [int(p) for p in str(text).strip().split(":")]
    except (ValueError, AttributeError):
        return 0
    if not parts or len(parts) > 3:
        return 0
    seconds = 0
    for p in parts:
        seconds = seconds * 60 + p
    return seconds


def format_duration(seconds: int | float | None) -> str:
    """205 -> '3:25', 3723 -> '1:02:03'."""
    s = int(seconds or 0)
    if s < 0:
        s = 0
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    if h:
        return f"{h}:{m:02d}:{sec:02d}"
    return f"{m}:{sec:02d}"
