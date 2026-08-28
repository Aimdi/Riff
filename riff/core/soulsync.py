"""SoulSync client — search + request download (Riff Mobile plugin port).

Talks to a self-hosted SoulSync instance via Bearer ``/api/v1``.
Blocking network helpers; call via ``run_async`` from the UI.
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field

log = logging.getLogger("riff.soulsync")

_UA = "Riff/1.0 (SoulSync; +https://github.com/Aimdi/Riff)"


@dataclass
class SoulSyncTrack:
    id: str
    name: str
    artists: list[str] = field(default_factory=list)
    album: str = ""
    duration_ms: int = 0
    image_url: str = ""
    source: str = ""

    @property
    def artist_label(self) -> str:
        return ", ".join(a for a in self.artists if a.strip())

    @property
    def request_query(self) -> str:
        artist = self.artist_label
        if not artist:
            return self.name
        return f"{artist} - {self.name}"


@dataclass
class SoulSyncSession:
    host: str
    api_key: str


def normalize_host(raw: str) -> str:
    h = (raw or "").strip().rstrip("/")
    if not h:
        return ""
    if not h.startswith(("http://", "https://")):
        h = f"https://{h}"
    return h


def _unwrap(raw) -> dict | None:
    if not isinstance(raw, dict):
        return None
    if raw.get("success") is False:
        return None
    data = raw.get("data")
    if isinstance(data, dict):
        return data
    return raw


def _http_json(
    method: str,
    url: str,
    *,
    api_key: str,
    body: dict | None = None,
    timeout: float = 25,
) -> tuple[int, dict]:
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={
            "User-Agent": _UA,
            "Authorization": f"Bearer {api_key}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            status = getattr(resp, "status", 200) or 200
            text = resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        status = exc.code
        text = exc.read().decode("utf-8", errors="replace")
    if not text.strip():
        return status, {}
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        raise RuntimeError("Unexpected SoulSync response") from exc
    if not isinstance(parsed, dict):
        return status, {}
    return status, parsed


def parse_track(raw: dict) -> SoulSyncTrack | None:
    if not isinstance(raw, dict):
        return None
    artists_raw = raw.get("artists")
    artists: list[str] = []
    if isinstance(artists_raw, list):
        artists = [str(a) for a in artists_raw if a]
    elif isinstance(artists_raw, str) and artists_raw.strip():
        artists = [artists_raw]
    name = str(raw.get("name") or raw.get("title") or "").strip()
    if not name:
        return None
    try:
        dur = int(raw.get("duration_ms") or 0)
    except (TypeError, ValueError):
        dur = 0
    return SoulSyncTrack(
        id=str(raw.get("id") or ""),
        name=name,
        artists=artists,
        album=str(raw.get("album") or ""),
        duration_ms=max(0, dur),
        image_url=str(raw.get("image_url") or raw.get("imageUrl") or ""),
        source=str(raw.get("source") or ""),
    )


def parse_tracks_payload(data: dict) -> list[SoulSyncTrack]:
    """Test helper: unwrap search response body."""
    body = _unwrap(data) or data
    tracks = body.get("tracks") if isinstance(body, dict) else None
    out: list[SoulSyncTrack] = []
    if isinstance(tracks, list):
        for row in tracks:
            t = parse_track(row) if isinstance(row, dict) else None
            if t:
                out.append(t)
    return out


def verify(session: SoulSyncSession) -> dict:
    status, raw = _http_json(
        "GET",
        f"{session.host}/api/v1/system/status",
        api_key=session.api_key,
    )
    if status in (401, 403):
        raise RuntimeError("SoulSync authentication failed")
    body = _unwrap(raw)
    if status != 200 or body is None:
        raise RuntimeError("Couldn't reach SoulSync")
    return body


def connect(host: str, api_key: str) -> SoulSyncSession:
    h = normalize_host(host)
    key = (api_key or "").strip()
    if not h or not key:
        raise ValueError("Server URL and API key are required")
    session = SoulSyncSession(host=h, api_key=key)
    verify(session)
    return session


def search_tracks(
    session: SoulSyncSession, query: str, *, limit: int = 25,
) -> list[SoulSyncTrack]:
    query = (query or "").strip()
    if not query:
        return []
    status, raw = _http_json(
        "POST",
        f"{session.host}/api/v1/search/tracks",
        api_key=session.api_key,
        body={"query": query, "source": "auto", "limit": int(limit)},
    )
    if status in (401, 403):
        raise RuntimeError("SoulSync authentication failed")
    return parse_tracks_payload(raw)


def request_download(session: SoulSyncSession, query: str) -> str:
    query = (query or "").strip()
    if not query:
        raise ValueError("Empty download query")
    status, raw = _http_json(
        "POST",
        f"{session.host}/api/v1/request",
        api_key=session.api_key,
        body={"query": query},
    )
    if status in (401, 403):
        raise RuntimeError("SoulSync authentication failed")
    body = _unwrap(raw) or {}
    return str(body.get("request_id") or body.get("status") or "queued")


def list_downloads(
    session: SoulSyncSession, *, limit: int = 30,
) -> list[dict]:
    qs = urllib.parse.urlencode({"limit": str(limit)})
    status, raw = _http_json(
        "GET",
        f"{session.host}/api/v1/downloads?{qs}",
        api_key=session.api_key,
    )
    if status in (401, 403):
        raise RuntimeError("SoulSync authentication failed")
    body = _unwrap(raw) or {}
    rows = body.get("downloads") if isinstance(body, dict) else None
    if not isinstance(rows, list):
        return []
    return [dict(r) for r in rows if isinstance(r, dict)]
