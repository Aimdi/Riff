"""Download tracks for offline playback using yt-dlp."""

from __future__ import annotations

import logging
import os
import re

from .library import Library
from .models import Track

log = logging.getLogger("riff.downloader")


def _safe_filename(name: str) -> str:
    name = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "_", name).strip(" .")
    return name[:120] or "track"


class Downloader:
    def __init__(self, library: Library, download_dir: str):
        self.library = library
        self.download_dir = download_dir

    def download(self, track: Track, progress_cb=None) -> str:
        """Blocking download; returns the final file path.

        progress_cb(fraction: float) is called from the yt-dlp thread.
        """
        os.makedirs(self.download_dir, exist_ok=True)
        stem = _safe_filename(f"{track.artist} - {track.title}".strip(" -"))
        outtmpl = os.path.join(self.download_dir, stem + ".%(ext)s")

        final_path: dict[str, str] = {}

        def hook(d: dict) -> None:
            if d.get("status") == "downloading" and progress_cb:
                total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
                done = d.get("downloaded_bytes") or 0
                if total:
                    progress_cb(min(1.0, done / total))
            elif d.get("status") == "finished":
                final_path["path"] = d.get("filename") or ""

        import yt_dlp

        opts = {
            "format": "bestaudio/best",
            "outtmpl": outtmpl,
            "quiet": True,
            "no_warnings": True,
            "noplaylist": True,
            "progress_hooks": [hook],
            "extractor_args": {"youtube": {"player_client": ["android", "web"]}},
        }
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.download([f"https://music.youtube.com/watch?v={track.video_id}"])

        path = final_path.get("path", "")
        if not path or not os.path.exists(path):
            raise RuntimeError(f"Download failed for {track.title}")
        self.library.record_download(track, path)
        return path

    def delete(self, track: Track) -> None:
        path = self.library.download_path(track.video_id)
        if path and os.path.exists(path):
            try:
                os.remove(path)
            except OSError:
                log.warning("could not remove %s", path)
        self.library.remove_download(track.video_id)
