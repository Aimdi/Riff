"""slskd client — Soulseek search via self-hosted slskd (Seeker companion).

Minimal REST: login optional (API key), search, browse results.
Blocking HTTP; call via ``run_async``.
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field

log = logging.getLogger("riff.slskd")

_UA = "Riff/1.0 (slskd; +https://github.com/Aimdi/Riff)"


@dataclass
class SlskdSession:
    host: str
    api_key: str = ""


@dataclass
class SlskdFile:
    filename: str
    size: int = 0
    extension: str = ""


@dataclass
class SlskdHit:
    username: str
    files: list[SlskdFile] = field(default_factory=list)

    @property
    def label(self) -> str:
        if not self.files:
            return self.username
        return self.files[0].filename.split("\\")[-1].split("/")[-1]


def normalize_host(raw: str) -> str:
    h = (raw or "").strip().rstrip("/")
    if not h:
        return ""
    if not h.startswith(("http://", "https://")):
        h = f"http://{h}"
    return h


def _http_json(
    method: str, url: str, *, api_key: str = "",
    body: dict | list | None = None,
    timeout: float = 30,
) -> tuple[int, object]:
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
    headers = {
        "User-Agent": _UA,
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    if api_key:
        headers["X-API-Key"] = api_key
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            status = getattr(resp, "status", 200) or 200
            text = resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        status = exc.code
        text = exc.read().decode("utf-8", errors="replace")
    if not text.strip():
        return status, None
    try:
        return status, json.loads(text)
    except json.JSONDecodeError:
        return status, text


def verify(session: SlskdSession) -> dict:
    status, data = _http_json(
        "GET", f"{session.host}/api/v0/application",
        api_key=session.api_key)
    if status in (401, 403):
        raise RuntimeError("slskd authentication failed")
    if status != 200 or not isinstance(data, dict):
        raise RuntimeError("Couldn't reach slskd")
    return data


def connect(host: str, api_key: str = "") -> SlskdSession:
    session = SlskdSession(host=normalize_host(host), api_key=(api_key or "").strip())
    if not session.host:
        raise ValueError("Server URL is required")
    verify(session)
    return session


def search(session: SlskdSession, query: str) -> str:
    """Start a search; returns search id."""
    query = (query or "").strip()
    if not query:
        raise ValueError("Empty search")
    status, data = _http_json(
        "POST",
        f"{session.host}/api/v0/searches",
        api_key=session.api_key,
        body={"searchText": query},
    )
    if status not in (200, 201) or not isinstance(data, dict):
        raise RuntimeError("Search failed")
    sid = str(data.get("id") or data.get("Id") or "")
    if not sid:
        raise RuntimeError("No search id returned")
    return sid


def search_responses(session: SlskdSession, search_id: str) -> list[SlskdHit]:
    status, data = _http_json(
        "GET",
        f"{session.host}/api/v0/searches/{urllib.parse.quote(search_id)}/responses",
        api_key=session.api_key,
    )
    if status != 200:
        return []
    rows = data if isinstance(data, list) else []
    out: list[SlskdHit] = []
    for raw in rows:
        if not isinstance(raw, dict):
            continue
        user = str(raw.get("username") or raw.get("Username") or "")
        files_raw = raw.get("files") or raw.get("Files") or []
        files: list[SlskdFile] = []
        if isinstance(files_raw, list):
            for f in files_raw[:20]:
                if not isinstance(f, dict):
                    continue
                files.append(SlskdFile(
                    filename=str(f.get("filename") or f.get("Filename") or ""),
                    size=int(f.get("size") or f.get("Size") or 0),
                    extension=str(
                        f.get("extension") or f.get("Extension") or ""),
                ))
        if user and files:
            out.append(SlskdHit(username=user, files=files))
    return out


def enqueue_download(
    session: SlskdSession, username: str, filename: str, size: int = 0,
) -> None:
    """Queue a download on the slskd server (mobile Seeker parity)."""
    user = (username or "").strip()
    name = (filename or "").strip()
    if not user or not name:
        raise ValueError("username and filename are required")
    status, _data = _http_json(
        "POST",
        f"{session.host}/api/v0/transfers/downloads/"
        f"{urllib.parse.quote(user)}",
        api_key=session.api_key,
        body=[{"filename": name, "size": int(size or 0)}],
    )
    if status in (401, 403):
        raise RuntimeError("slskd authentication failed")
    if status not in (200, 201):
        raise RuntimeError(f"slskd download failed ({status})")


def parse_responses_payload(data) -> list[SlskdHit]:
    """Test helper."""
    if not isinstance(data, list):
        return []
    out: list[SlskdHit] = []
    for raw in data:
        if not isinstance(raw, dict):
            continue
        user = str(raw.get("username") or "")
        files = []
        for f in raw.get("files") or []:
            if isinstance(f, dict) and f.get("filename"):
                files.append(SlskdFile(
                    filename=str(f["filename"]),
                    size=int(f.get("size") or 0),
                ))
        if user and files:
            out.append(SlskdHit(username=user, files=files))
    return out
