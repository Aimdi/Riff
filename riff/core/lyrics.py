"""Synced lyrics from LRCLIB (lrclib.net) with LRC parsing.

LRCLIB is a free, no-key lyrics database also used by many open-source
players. We fall back to YouTube Music's plain lyrics when nothing synced
is available (handled by the caller).
"""

from __future__ import annotations

import json
import logging
import re
import urllib.parse
import urllib.request

from .models import Track

log = logging.getLogger("riff.lyrics")

API = "https://lrclib.net/api"
_TAG = re.compile(r"\[(\d+):(\d{1,2}(?:\.\d+)?)\]")


def parse_lrc(text: str) -> list[tuple[float, str]]:
    """Parse LRC text into a sorted [(seconds, line), …].

    Handles multiple timestamps per line ("[00:12.00][00:50.00]la la").
    Malformed lines are skipped.
    """
    out: list[tuple[float, str]] = []
    for raw in (text or "").splitlines():
        stamps = []
        pos = 0
        for m in _TAG.finditer(raw):
            if m.start() != pos:
                break
            stamps.append(int(m.group(1)) * 60 + float(m.group(2)))
            pos = m.end()
        line = raw[pos:].strip()
        for s in stamps:
            out.append((s, line))
    out.sort(key=lambda item: item[0])
    return out


def _get(url: str):
    req = urllib.request.Request(
        url, headers={"User-Agent": "Riff music player (github.com/aimdi/player)"}
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.load(resp)


def fetch_lyrics(track: Track) -> tuple[list[tuple[float, str]], str]:
    """Returns (synced_lines, plain_text); either may be empty.

    Blocking — call from a worker thread.
    """
    artist = track.artists[0] if track.artists else ""
    params = {
        "track_name": track.title,
        "artist_name": artist,
    }
    if track.album:
        params["album_name"] = track.album
    if track.duration:
        params["duration"] = str(track.duration)

    record = None
    try:
        record = _get(f"{API}/get?{urllib.parse.urlencode(params)}")
    except Exception:  # noqa: BLE001 — 404 for unknown tracks is normal
        try:
            q = urllib.parse.urlencode({"q": f"{artist} {track.title}".strip()})
            results = _get(f"{API}/search?{q}")
            for r in results or []:
                if r.get("syncedLyrics") or r.get("plainLyrics"):
                    record = r
                    break
        except Exception:  # noqa: BLE001
            log.debug("lrclib lookup failed for %s", track.title, exc_info=True)

    if not record:
        return [], ""
    synced = parse_lrc(record.get("syncedLyrics") or "")
    plain = record.get("plainLyrics") or ""
    return synced, plain


def line_index_at(lines: list[tuple[float, str]], position: float) -> int:
    """Index of the line active at `position` seconds, -1 before the first."""
    idx = -1
    for i, (ts, _text) in enumerate(lines):
        if ts <= position:
            idx = i
        else:
            break
    return idx
