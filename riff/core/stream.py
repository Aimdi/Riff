"""Resolve a YouTube Music videoId to a direct stream URL via yt-dlp."""

from __future__ import annotations

import logging
import re
import threading
import time

log = logging.getLogger("riff.stream")

_YT_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")
_YT_URL_RE = re.compile(
    r"(?:v=|/v/|youtu\.be/|/shorts/|/embed/)([A-Za-z0-9_-]{11})"
)


def extract_youtube_video_id(text: str) -> str | None:
    """Parse a bare video id or YouTube / Music URL → 11-char id."""
    raw = (text or "").strip()
    if not raw:
        return None
    # Riff synthetic ids (podcasts, ABS, …) must never look like YouTube.
    if raw.startswith((
        "podcast_", "librivox_", "abs_", "cloud_", "local_",
    )):
        return None
    if _YT_ID_RE.fullmatch(raw):
        return raw
    m = _YT_URL_RE.search(raw)
    return m.group(1) if m else None

# Direct googlevideo URLs expire after ~6 hours; keep a conservative margin.
CACHE_TTL = 30 * 60

_QUALITY_FORMATS = {
    "high": "bestaudio/best",
    "medium": "bestaudio[abr<=160]/bestaudio/best",
    "low": "bestaudio[abr<=96]/bestaudio/best",
}

# Video track for the cover-art surface. Prefer progressive muxed (has audio
# too); otherwise a video-only stream — the service keeps audio on mpv.
_VIDEO_FORMAT = (
    "best[height<=720][ext=mp4][acodec!=none][vcodec!=none]/"
    "best[height<=480][acodec!=none][vcodec!=none]/"
    "18/"  # classic progressive 360p mp4 when still offered
    "bestvideo[height<=720][ext=mp4]/"
    "bestvideo[height<=720]/"
    "bestvideo/"
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

    def invalidate(self, video_id: str) -> None:
        """Drop cached URLs for a video (Meld: recover before skip)."""
        with self._lock:
            for kind in ("audio", "video"):
                self._cache.pop((video_id, kind), None)

    # Tried in order until one yields a stream. YouTube regularly breaks
    # individual player clients (PO-token requirements etc.), so never rely
    # on a single pinned client: yt-dlp's own defaults come first — its
    # maintainers update them as YouTube changes — with explicit clients as
    # fallbacks. ``android_vr`` is Meld/Vivi's preferred low-gate client.
    _CLIENT_ATTEMPTS: tuple[tuple[str, ...] | None, ...] = (
        None,                    # yt-dlp defaults
        ("android_vr", "android"),
        ("android", "web"),      # historic riff behavior
        ("web_music", "ios"),    # music-specific / least-gated alternates
    )

    def resolve(self, video_id: str, *, video: bool = False) -> str:
        """Blocking: returns a playable URL. Raises on failure.

        ``video=True`` requests a stream that includes a video track (for the
        in-app video panel). Audio-only is the default for music playback.
        """
        hit = self.cached(video_id, video=video)
        if hit:
            return hit

        fmt = (
            _VIDEO_FORMAT
            if video
            else _QUALITY_FORMATS.get(self.quality, _QUALITY_FORMATS["high"])
        )
        # music.youtube.com is noticeably less bot-gated for songs; plain
        # watch pages are only needed when we want the actual video track.
        page = ("https://www.youtube.com/watch?v=" if video
                else "https://music.youtube.com/watch?v=")

        last_error: Exception | None = None
        for clients in self._CLIENT_ATTEMPTS:
            try:
                info = self._extract(page + video_id, fmt, clients)
            except Exception as exc:  # noqa: BLE001 — try the next client set
                last_error = exc
                log.warning("extract failed (clients=%s): %s", clients, exc)
                continue
            url = (self._pick_video_url(info) if video
                   else self._pick_audio_url(info))
            if url:
                key = (video_id, "video" if video else "audio")
                with self._lock:
                    self._cache[key] = (time.monotonic(), url)
                return url
            last_error = RuntimeError("no stream in response")
            log.warning("no usable stream (clients=%s) for %s",
                        clients, video_id)
        raise RuntimeError(
            f"{last_error} — if this keeps happening, update yt-dlp "
            "(sudo pacman -Syu yt-dlp): YouTube changes often and old "
            "yt-dlp versions stop working"
        )

    @staticmethod
    def _extract(url: str, fmt: str, clients: tuple[str, ...] | None) -> dict | None:
        import yt_dlp

        opts = {
            "format": fmt,
            "quiet": True,
            "no_warnings": True,
            "noplaylist": True,
            "skip_download": True,
        }
        if clients:
            opts["extractor_args"] = {
                "youtube": {"player_client": list(clients)}}
        with yt_dlp.YoutubeDL(opts) as ydl:
            return ydl.extract_info(url, download=False)

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
        """Pick a video URL for the in-app surface.

        Prefers progressive A+V (so GStreamer can play sound alone), then
        falls back to video-only (audio stays on mpv).
        """
        if not info:
            return ""
        if info.get("url") and info.get("vcodec") not in (None, "none"):
            return info["url"]

        best_muxed = None
        best_video = None
        for f in info.get("formats") or []:
            if not f.get("url"):
                continue
            vcodec = f.get("vcodec")
            acodec = f.get("acodec")
            if vcodec in (None, "none"):
                continue
            height = f.get("height") or 0
            tbr = f.get("tbr") or f.get("vbr") or 0
            score = (height, tbr)
            if acodec not in (None, "none"):
                if best_muxed is None or score > best_muxed[0]:
                    best_muxed = (score, f["url"], True)
            else:
                if best_video is None or score > best_video[0]:
                    best_video = (score, f["url"], False)

        # Also check requested_formats (yt-dlp sometimes only lists video there).
        for f in info.get("requested_formats") or []:
            if not f.get("url") or f.get("vcodec") in (None, "none"):
                continue
            height = f.get("height") or 0
            tbr = f.get("tbr") or f.get("vbr") or 0
            score = (height, tbr)
            has_a = f.get("acodec") not in (None, "none")
            if has_a:
                if best_muxed is None or score > best_muxed[0]:
                    best_muxed = (score, f["url"], True)
            else:
                if best_video is None or score > best_video[0]:
                    best_video = (score, f["url"], False)

        if best_muxed:
            return best_muxed[1]
        if best_video:
            return best_video[1]
        if info.get("url"):
            return info["url"]
        return ""