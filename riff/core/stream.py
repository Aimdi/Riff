"""Resolve a YouTube Music videoId to a direct stream URL via yt-dlp."""

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

# Progressive / muxed A+V under 720p preferred for in-app video (NewPipe-style).
_VIDEO_FORMAT = (
    "best[height<=720][ext=mp4]/"
    "best[height<=720]/"
    "best[ext=mp4]/"
    "best"
)


class StreamResolver:
    def __init__(self, quality: str = "high"):
        self.quality = quality
        # cache key: (video_id, "audio"|"video")
        self._cache: dict[tuple[str, str], tuple[float, str]] = {}
        self._lock = threading.Lock()

    def cached(self, video_id: str, *, video: bool = False) -> str | None:
        key = (video_id, "video" if video else "audio")
        with self._lock:
            entry = self._cache.get(key)
            if entry and time.monotonic() - entry[0] < CACHE_TTL:
                return entry[1]
            self._cache.pop(key, None)
        return None

    def resolve(self, video_id: str, *, video: bool = False) -> str:
        """Blocking: returns a playable URL. Raises on failure.

        ``video=True`` requests a stream that includes a video track (for the
        in-app video panel). Audio-only is the default for music playback.
        """
        hit = self.cached(video_id, video=video)
        if hit:
            return hit

        import yt_dlp

        fmt = (
            _VIDEO_FORMAT
            if video
            else _QUALITY_FORMATS.get(self.quality, _QUALITY_FORMATS["high"])
        )
        opts = {
            "format": fmt,
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
                f"https://www.youtube.com/watch?v={video_id}", download=False
            )
        url = (
            self._pick_video_url(info) if video else self._pick_audio_url(info)
        )
        if not url:
            raise RuntimeError(f"No playable stream found for {video_id}")
        key = (video_id, "video" if video else "audio")
        with self._lock:
            self._cache[key] = (time.monotonic(), url)
        return url

    @staticmethod
    def _pick_audio_url(info: dict | None) -> str:
        if not info:
            return ""
        if info.get("url") and info.get("vcodec") in (None, "none"):
            return info["url"]
        if info.get("url") and not info.get("requested_formats"):
            # single URL that might be audio-only progressive
            if info.get("acodec") not in (None, "none"):
                return info["url"]
        for f in info.get("requested_formats") or []:
            if f.get("acodec") not in (None, "none") and f.get("url"):
                if f.get("vcodec") in (None, "none"):
                    return f["url"]
        for f in info.get("requested_formats") or []:
            if f.get("acodec") not in (None, "none") and f.get("url"):
                return f["url"]
        best = None
        for f in info.get("formats") or []:
            if f.get("acodec") in (None, "none") or not f.get("url"):
                continue
            if f.get("vcodec") not in (None, "none"):
                continue  # skip muxed when we want pure audio
            abr = f.get("abr") or 0
            if best is None or abr > best[0]:
                best = (abr, f["url"])
        if best:
            return best[1]
        # last resort: any audio-bearing URL
        if info.get("url"):
            return info["url"]
        return ""

    @staticmethod
    def _pick_video_url(info: dict | None) -> str:
        """Prefer a single progressive URL (A+V) for GStreamer playbin."""
        if not info:
            return ""
        if info.get("url"):
            return info["url"]
        # Prefer formats that already contain both audio and video.
        best = None
        for f in info.get("formats") or []:
            if not f.get("url"):
                continue
            if f.get("acodec") in (None, "none"):
                continue
            if f.get("vcodec") in (None, "none"):
                continue
            height = f.get("height") or 0
            tbr = f.get("tbr") or 0
            score = (height, tbr)
            if best is None or score > best[0]:
                best = (score, f["url"])
        if best:
            return best[1]
        # requested_formats is usually separate video+audio — playbin needs one URI.
        if info.get("url"):
            return info["url"]
        return ""
