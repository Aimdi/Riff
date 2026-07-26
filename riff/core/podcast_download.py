"""Download podcast episodes for offline play (Riff Mobile port).

Stores files under ``<download_dir>/podcast_downloads/`` and records them
in the library ``downloads`` table (same as music downloads).
"""

from __future__ import annotations

import logging
import os
import re
import urllib.request

from .library import Library
from .models import Track

log = logging.getLogger("riff.podcast_download")

_UA = "Riff/1.0 (podcast-download; +https://github.com/Aimdi/Riff)"


def _safe_id(video_id: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_-]", "_", video_id or "episode")[:80]


def _ext_from_url(url: str) -> str:
    from urllib.parse import urlparse

    path = urlparse(url).path if "://" in url else url
    base = path.rsplit("/", 1)[-1]
    dot = base.rfind(".")
    if dot >= 0 and len(base) - dot <= 5:
        return base[dot:].lower()
    return ".mp3"


def podcast_download_dir(download_dir: str) -> str:
    return os.path.join(download_dir, "podcast_downloads")


def is_downloaded(library: Library, episode_id: str) -> bool:
    path = library.download_path(episode_id)
    return bool(path and os.path.exists(path))


def download_episode(
    library: Library,
    track: Track,
    download_dir: str,
    *,
    progress_cb=None,
) -> str:
    """Blocking download of a podcast enclosure. Returns local path."""
    url = (track.stream_url or "").strip()
    if not url.startswith(("http://", "https://")):
        raise ValueError("Episode has no stream URL")
    existing = library.download_path(track.video_id)
    if existing and os.path.exists(existing):
        return existing

    dest_dir = podcast_download_dir(download_dir)
    os.makedirs(dest_dir, exist_ok=True)
    path = os.path.join(dest_dir, _safe_id(track.video_id) + _ext_from_url(url))
    tmp = path + ".part"

    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    with urllib.request.urlopen(req, timeout=120) as resp:
        total = int(resp.headers.get("Content-Length") or 0)
        done = 0
        with open(tmp, "wb") as fh:
            while True:
                chunk = resp.read(256 * 1024)
                if not chunk:
                    break
                fh.write(chunk)
                done += len(chunk)
                if progress_cb and total > 0:
                    progress_cb(min(1.0, done / total))
    os.replace(tmp, path)
    track.local_path = path
    library.record_download(track, path)
    return path


def delete_episode(library: Library, episode_id: str) -> None:
    path = library.download_path(episode_id)
    if path and os.path.exists(path):
        try:
            os.remove(path)
        except OSError:
            log.warning("could not remove %s", path)
    library.remove_download(episode_id)
