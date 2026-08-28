"""Torrents CSV search (Riff Mobile Torrents Digger public index).

Blocking HTTP; call via ``run_async``. Returns magnet links — download
is left to the user's torrent client (xdg-open / copy).
"""

from __future__ import annotations

import json
import logging
import urllib.parse
import urllib.request
from dataclasses import dataclass

log = logging.getLogger("riff.torrents")

_UA = "Riff/1.0 (torrents; +https://github.com/Aimdi/Riff)"
_ROOT = "https://torrents-csv.com"


@dataclass
class TorrentHit:
    name: str
    infohash: str
    size_bytes: int = 0
    seeders: int = 0
    leechers: int = 0
    magnet: str = ""

    @property
    def size_label(self) -> str:
        n = float(self.size_bytes or 0)
        for unit in ("B", "KB", "MB", "GB", "TB"):
            if n < 1024 or unit == "TB":
                return f"{n:.1f} {unit}" if unit != "B" else f"{int(n)} B"
            n /= 1024
        return ""


def parse_hits(payload) -> list[TorrentHit]:
    rows = payload
    if isinstance(payload, dict):
        rows = payload.get("torrents") or payload.get("results") or []
    if not isinstance(rows, list):
        return []
    out: list[TorrentHit] = []
    for raw in rows:
        if not isinstance(raw, dict):
            continue
        name = str(raw.get("name") or raw.get("title") or "").strip()
        infohash = str(
            raw.get("infohash") or raw.get("info_hash") or raw.get("hash")
            or "").strip().lower()
        if not name or not infohash:
            continue
        try:
            size = int(raw.get("size_bytes") or raw.get("size") or 0)
        except (TypeError, ValueError):
            size = 0
        try:
            seeders = int(raw.get("seeders") or raw.get("seeds") or 0)
        except (TypeError, ValueError):
            seeders = 0
        try:
            leechers = int(raw.get("leechers") or raw.get("leeches") or 0)
        except (TypeError, ValueError):
            leechers = 0
        magnet = str(raw.get("magnet") or "")
        if not magnet:
            magnet = (
                f"magnet:?xt=urn:btih:{infohash}&dn="
                f"{urllib.parse.quote(name)}"
            )
        out.append(TorrentHit(
            name=name, infohash=infohash, size_bytes=size,
            seeders=seeders, leechers=leechers, magnet=magnet,
        ))
    return out


def search(query: str, *, limit: int = 40) -> list[TorrentHit]:
    query = (query or "").strip()
    if not query:
        return []
    qs = urllib.parse.urlencode({"q": query, "page": "1"})
    url = f"{_ROOT}/service/search?{qs}"
    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    with urllib.request.urlopen(req, timeout=25) as resp:
        raw = resp.read().decode("utf-8", errors="replace")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError("Unexpected torrents-csv response") from exc
    return parse_hits(data)[:limit]
