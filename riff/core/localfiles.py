"""Index a local music folder into playable Tracks."""

from __future__ import annotations

import hashlib
import os

from .models import Track

EXTENSIONS = {".mp3", ".flac", ".ogg", ".opus", ".m4a", ".wav", ".aac", ".wma"}


def _parse_name(stem: str) -> tuple[str, str]:
    """'Artist - Title' -> (artist, title); otherwise ('', stem)."""
    if " - " in stem:
        artist, title = stem.split(" - ", 1)
        return artist.strip(), title.strip()
    return "", stem.strip()


def scan(folder: str) -> list[Track]:
    """Blocking: walk `folder` and return Tracks for every audio file."""
    tracks = []
    folder = os.path.expanduser(folder)
    if not os.path.isdir(folder):
        return []
    for root, _dirs, files in os.walk(folder):
        for name in files:
            stem, ext = os.path.splitext(name)
            if ext.lower() not in EXTENSIONS:
                continue
            path = os.path.join(root, name)
            artist, title = _parse_name(stem)
            digest = hashlib.sha1(path.encode()).hexdigest()[:16]
            tracks.append(Track(
                video_id=f"local:{digest}",
                title=title,
                artists=[artist] if artist else [],
                local_path=path,
            ))
    tracks.sort(key=lambda t: (t.artist.lower(), t.title.lower()))
    return tracks
