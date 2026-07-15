"""Resolve a YouTube Music videoId to a direct audio stream URL via yt-dlp."""

from __future__ import annotations

import logging
import threading
import time

log = logging.getLogger("riff.stream")

# Direct googlevideo URLs expire after ~6 hours; keep a conservative margin.
CACHE_TTL = 30 * 60

_QUALITY_FORMATS = {
    "high": "bestaudio/best",
    "medium": "bestaudio[abr<=160]/bestaudio/best",
    "low": "bestaudio[abr<=96]/bestaudio/best",
}


class StreamResolver:
    def __init__(self, quality: str = "high"):
        self.quality = quality
        self._cache: dict[str, tuple[float, str]] = {}
        self._lock = threading.Lock()

    def cached(self, video_id: str) -> str | None:
        with self._lock:
            entry = self._cache.get(video_id)
            if entry and time.monotonic() - entry[0] < CACHE_TTL:
                return entry[1]
            self._cache.pop(video_id, None)
        return None

    def resolve(self, video_id: str) -> str:
        """Blocking: returns a playable URL. Raises on failure."""
        hit = self.cached(video_id)
        if hit:
            return hit

        import yt_dlp

        opts = {
            "format": _QUALITY_FORMATS.get(self.quality, _QUALITY_FORMATS["high"]),
            "quiet": True,
            "no_warnings": True,
            "noplaylist": True,
            "skip_download": True,
            # Music-only content plays fine through these clients and they
            # tend to hand out URLs that stream without throttling.
            "extractor_args": {"youtube": {"player_client": ["android", "web"]}},
        }
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(
                f"https://music.youtube.com/watch?v={video_id}", download=False
            )
        url = self._pick_url(info)
        if not url:
            raise RuntimeError(f"No playable stream found for {video_id}")
        with self._lock:
            self._cache[video_id] = (time.monotonic(), url)
        return url

    @staticmethod
    def _pick_url(info: dict | None) -> str:
        if not info:
            return ""
        if info.get("url"):
            return info["url"]
        # When yt-dlp returns merged requested formats, take the audio one.
        for f in info.get("requested_formats") or []:
            if f.get("acodec") not in (None, "none") and f.get("url"):
                return f["url"]
        best = None
        for f in info.get("formats") or []:
            if f.get("acodec") in (None, "none") or not f.get("url"):
                continue
            abr = f.get("abr") or 0
            if best is None or abr > best[0]:
                best = (abr, f["url"])
        return best[1] if best else ""
