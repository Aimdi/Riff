"""Audiobookshelf client — login, browse, stream (Riff Mobile / Lissen port).

Blocking network helpers; call via ``run_async`` from the UI.
Tracks use ``abs_`` video_id + ``stream_url`` so playback skips yt-dlp.
"""

from __future__ import annotations

import json
import logging
import mimetypes
import uuid
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field

from .models import Track

log = logging.getLogger("riff.audiobookshelf")

_UA = "Riff/1.0 (Audiobookshelf; Lissen-compatible; +https://github.com/Aimdi/Riff)"


@dataclass
class AbsFolder:
    id: str
    full_path: str = ""


@dataclass
class AbsLibrary:
    id: str
    name: str
    media_type: str = "book"
    folders: list[AbsFolder] = field(default_factory=list)


@dataclass
class AbsBook:
    id: str
    title: str
    author: str = ""
    subtitle: str = ""

    def cover_url(self, host: str, token: str, *, width: int = 400) -> str:
        h = normalize_host(host)
        tok = urllib.parse.quote(token, safe="")
        return f"{h}/api/items/{self.id}/cover?width={width}&token={tok}"


@dataclass
class AbsAudioTrack:
    index: int
    title: str
    content_url: str
    duration: float = 0.0


@dataclass
class AbsBookDetail:
    id: str
    title: str
    author: str
    tracks: list[AbsAudioTrack] = field(default_factory=list)
    description: str = ""
    narrator: str = ""
    current_time: float = 0.0
    session_id: str = ""

    def to_tracks(self, host: str, token: str) -> list[Track]:
        cover = AbsBook(id=self.id, title=self.title).cover_url(host, token)
        artists = [self.author] if self.author else ["Audiobook"]
        out: list[Track] = []
        for t in self.tracks:
            url = stream_url(host, token, t.content_url)
            if not url:
                continue
            out.append(Track(
                video_id=f"abs_{self.id}_{t.index}",
                title=t.title or f"Track {t.index + 1}",
                artists=list(artists),
                album=self.title,
                duration=int(t.duration or 0),
                thumbnail=cover,
                stream_url=url,
            ))
        return out


@dataclass
class AbsSession:
    host: str
    token: str
    user_id: str = ""
    username: str = ""
    library_id: str = ""


def normalize_host(raw: str) -> str:
    h = (raw or "").strip().rstrip("/")
    if not h:
        return ""
    if not h.startswith(("http://", "https://")):
        h = f"https://{h}"
    return h


def stream_url(host: str, token: str, content_url: str) -> str:
    content_url = (content_url or "").strip()
    if not content_url or not token:
        return ""
    if content_url.startswith(("http://", "https://")):
        path = content_url
    else:
        h = normalize_host(host)
        path = f"{h}{content_url if content_url.startswith('/') else '/' + content_url}"
    sep = "&" if "?" in path else "?"
    return f"{path}{sep}token={urllib.parse.quote(token, safe='')}"


def _http_json(
    method: str,
    url: str,
    *,
    token: str | None = None,
    body: dict | None = None,
    headers: dict | None = None,
    timeout: float = 30,
) -> dict | list:
    hdrs = {
        "User-Agent": _UA,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    if token:
        hdrs["Authorization"] = f"Bearer {token}"
    if headers:
        hdrs.update(headers)
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=hdrs, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:200]
        raise RuntimeError(f"ABS {exc.code}: {detail or exc.reason}") from exc
    if not raw.strip():
        return {}
    parsed = json.loads(raw)
    if isinstance(parsed, (dict, list)):
        return parsed
    return {}


def login(host: str, username: str, password: str) -> AbsSession:
    h = normalize_host(host)
    if not h or not username:
        raise ValueError("Server URL and username are required")
    data = _http_json(
        "POST",
        f"{h}/login",
        body={"username": username, "password": password or ""},
        headers={"x-return-tokens": "true"},
    )
    if not isinstance(data, dict) or not isinstance(data.get("user"), dict):
        raise RuntimeError("Unexpected login response")
    user = data["user"]
    token = str(user.get("accessToken") or user.get("token") or "")
    if not token:
        raise RuntimeError("No token in login response")
    return AbsSession(
        host=h,
        token=token,
        user_id=str(user.get("id") or ""),
        username=username,
    )


def _parse_folders(raw_folders) -> list[AbsFolder]:
    out: list[AbsFolder] = []
    if not isinstance(raw_folders, list):
        return out
    for f in raw_folders:
        if not isinstance(f, dict) or not f.get("id"):
            continue
        out.append(AbsFolder(
            id=str(f["id"]),
            full_path=str(f.get("fullPath") or f.get("name") or ""),
        ))
    return out


def fetch_libraries(session: AbsSession) -> list[AbsLibrary]:
    data = _http_json(
        "GET", f"{session.host}/api/libraries", token=session.token)
    libs = data.get("libraries") if isinstance(data, dict) else data
    out: list[AbsLibrary] = []
    if isinstance(libs, list):
        for raw in libs:
            if not isinstance(raw, dict) or not raw.get("id"):
                continue
            out.append(AbsLibrary(
                id=str(raw["id"]),
                name=str(raw.get("name") or "Library"),
                media_type=str(raw.get("mediaType") or "book"),
                folders=_parse_folders(raw.get("folders")),
            ))
    return out


def upload_book(
    session: AbsSession,
    *,
    library_id: str,
    folder_id: str,
    title: str,
    files: list[tuple[str, bytes]],
    author: str = "",
    series: str = "",
    timeout: float = 1800,
) -> None:
    """Multipart ``POST /api/upload`` (mobile Audiobookshelf parity).

    ``files`` is a list of ``(filename, bytes)``. Keys are ``0``, ``1``, …
    as ABS expects.
    """
    if not library_id or not folder_id:
        raise ValueError("library and folder are required")
    if not files:
        raise ValueError("No files to upload")
    boundary = f"----RiffBoundary{uuid.uuid4().hex}"
    body = bytearray()

    def _field(name: str, value: str) -> None:
        body.extend(f"--{boundary}\r\n".encode())
        body.extend(
            f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode())
        body.extend(f"{value}\r\n".encode())

    def _file(name: str, filename: str, data: bytes) -> None:
        ctype = mimetypes.guess_type(filename)[0] or "application/octet-stream"
        body.extend(f"--{boundary}\r\n".encode())
        body.extend(
            f'Content-Disposition: form-data; name="{name}"; '
            f'filename="{filename}"\r\n'.encode())
        body.extend(f"Content-Type: {ctype}\r\n\r\n".encode())
        body.extend(data)
        body.extend(b"\r\n")

    _field("title", title or "Untitled")
    _field("library", library_id)
    _field("folder", folder_id)
    if (author or "").strip():
        _field("author", author.strip())
    if (series or "").strip():
        _field("series", series.strip())
    for i, (filename, data) in enumerate(files):
        _file(str(i), filename or f"track{i}.mp3", data)
    body.extend(f"--{boundary}--\r\n".encode())

    url = f"{session.host}/api/upload"
    req = urllib.request.Request(
        url,
        data=bytes(body),
        method="POST",
        headers={
            "User-Agent": _UA,
            "Authorization": f"Bearer {session.token}",
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            resp.read()
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:200]
        raise RuntimeError(f"ABS upload {exc.code}: {detail or exc.reason}") from exc


def prefer_book_library(libraries: list[AbsLibrary]) -> AbsLibrary | None:
    for lib in libraries:
        if lib.media_type == "book":
            return lib
    return libraries[0] if libraries else None


def fetch_books(
    session: AbsSession,
    library_id: str,
    *,
    page: int = 0,
    limit: int = 50,
) -> list[AbsBook]:
    if not library_id:
        return []
    qs = urllib.parse.urlencode({
        "limit": str(limit),
        "page": str(page),
        "sort": "media.metadata.title",
        "desc": "0",
        "minified": "1",
    })
    data = _http_json(
        "GET",
        f"{session.host}/api/libraries/{library_id}/items?{qs}",
        token=session.token,
    )
    results = data.get("results") if isinstance(data, dict) else None
    return [_parse_book_item(r) for r in (results or []) if isinstance(r, dict)]


def search_books(
    session: AbsSession, library_id: str, query: str, *, limit: int = 40,
) -> list[AbsBook]:
    query = (query or "").strip()
    if not library_id or not query:
        return fetch_books(session, library_id, limit=limit)
    qs = urllib.parse.urlencode({"q": query, "limit": str(limit)})
    data = _http_json(
        "GET",
        f"{session.host}/api/libraries/{library_id}/search?{qs}",
        token=session.token,
    )
    hits = data.get("book") if isinstance(data, dict) else None
    out: list[AbsBook] = []
    if isinstance(hits, list):
        for hit in hits:
            if not isinstance(hit, dict):
                continue
            item = hit.get("libraryItem") if isinstance(
                hit.get("libraryItem"), dict) else hit
            if isinstance(item, dict):
                book = _parse_book_item(item)
                if book.id:
                    out.append(book)
    return out


def open_book(session: AbsSession, item_id: str) -> AbsBookDetail:
    detail = _http_json(
        "GET", f"{session.host}/api/items/{item_id}", token=session.token)
    if not isinstance(detail, dict):
        raise RuntimeError("Unexpected item response")
    media = detail.get("media") if isinstance(detail.get("media"), dict) else {}
    meta = media.get("metadata") if isinstance(media.get("metadata"), dict) else {}
    title = str(meta.get("title") or "Audiobook")
    author = str(meta.get("authorName") or "")
    if not author and isinstance(meta.get("authors"), list):
        names = []
        for a in meta["authors"]:
            if isinstance(a, dict):
                names.append(str(a.get("name") or ""))
            elif a:
                names.append(str(a))
        author = ", ".join(n for n in names if n)
    narrators = ""
    if isinstance(meta.get("narrators"), list):
        narrators = ", ".join(str(n) for n in meta["narrators"] if n)
    else:
        narrators = str(meta.get("narrator") or "")
    description = str(meta.get("description") or "")

    play = _http_json(
        "POST",
        f"{session.host}/api/items/{item_id}/play",
        token=session.token,
        body={
            "deviceInfo": {
                "clientName": "Riff",
                "deviceId": f"riff-{session.user_id or 'desktop'}",
                "deviceName": "Riff Desktop",
            },
            "supportedMimeTypes": [
                "audio/flac", "audio/mpeg", "audio/mp4", "audio/ogg",
                "audio/aac", "audio/webm", "audio/x-m4a",
            ],
            "mediaPlayer": "Riff",
            "forceTranscode": False,
            "forceDirectPlay": True,
        },
    )
    if not isinstance(play, dict):
        play = {}
    session_id = str(play.get("id") or "")
    try:
        current_time = float(play.get("currentTime") or 0)
    except (TypeError, ValueError):
        current_time = 0.0
    tracks = _parse_session_tracks(play, item_id=item_id, media=media)
    return AbsBookDetail(
        id=item_id,
        title=title,
        author=author,
        tracks=tracks,
        description=description,
        narrator=narrators,
        current_time=current_time,
        session_id=session_id,
    )


def _parse_book_item(raw: dict) -> AbsBook:
    media = raw.get("media") if isinstance(raw.get("media"), dict) else {}
    meta = media.get("metadata") if isinstance(media.get("metadata"), dict) else {}
    author = str(meta.get("authorName") or "")
    if not author and isinstance(meta.get("authors"), list) and meta["authors"]:
        first = meta["authors"][0]
        author = str(first.get("name") if isinstance(first, dict) else first or "")
    return AbsBook(
        id=str(raw.get("id") or ""),
        title=str(meta.get("title") or "Untitled"),
        author=author,
        subtitle=str(meta.get("subtitle") or ""),
    )


def _parse_session_tracks(
    session: dict, *, item_id: str, media: dict,
) -> list[AbsAudioTrack]:
    tracks: list[AbsAudioTrack] = []
    audio_tracks = session.get("audioTracks") or []
    if isinstance(audio_tracks, list):
        for i, t in enumerate(audio_tracks):
            if not isinstance(t, dict):
                continue
            content_url = str(t.get("contentUrl") or "").strip()
            if not content_url:
                continue
            meta = t.get("metadata") if isinstance(t.get("metadata"), dict) else {}
            title = str(
                t.get("title") or meta.get("filename") or f"Track {i + 1}")
            try:
                idx = int(t.get("index") if t.get("index") is not None else i)
            except (TypeError, ValueError):
                idx = i
            try:
                dur = float(t.get("duration") or 0)
            except (TypeError, ValueError):
                dur = 0.0
            tracks.append(AbsAudioTrack(
                index=idx, title=title, content_url=content_url, duration=dur,
            ))
    if tracks:
        return tracks
    files = media.get("audioFiles") if isinstance(media, dict) else None
    if not isinstance(files, list):
        return tracks
    for i, f in enumerate(files):
        if not isinstance(f, dict):
            continue
        ino = str(f.get("ino") or "")
        if not ino:
            continue
        meta = f.get("metadata") if isinstance(f.get("metadata"), dict) else {}
        tags = f.get("metaTags") if isinstance(f.get("metaTags"), dict) else {}
        title = str(
            tags.get("tagTitle") or meta.get("filename") or f"Track {i + 1}")
        try:
            idx = int(f.get("index") if f.get("index") is not None else i)
        except (TypeError, ValueError):
            idx = i
        try:
            dur = float(f.get("duration") or 0)
        except (TypeError, ValueError):
            dur = 0.0
        tracks.append(AbsAudioTrack(
            index=idx,
            title=title,
            content_url=f"/api/items/{item_id}/file/{ino}",
            duration=dur,
        ))
    return tracks


def parse_libraries_payload(data: dict | list) -> list[AbsLibrary]:
    """Test helper."""
    libs = data.get("libraries") if isinstance(data, dict) else data
    out: list[AbsLibrary] = []
    if isinstance(libs, list):
        for raw in libs:
            if isinstance(raw, dict) and raw.get("id"):
                out.append(AbsLibrary(
                    id=str(raw["id"]),
                    name=str(raw.get("name") or "Library"),
                    media_type=str(raw.get("mediaType") or "book"),
                    folders=_parse_folders(raw.get("folders")),
                ))
    return out


def parse_items_payload(data: dict) -> list[AbsBook]:
    """Test helper for library items listing."""
    results = data.get("results") or []
    return [_parse_book_item(r) for r in results if isinstance(r, dict)]


def parse_play_payload(
    item: dict, play: dict, *, item_id: str = "item1",
) -> AbsBookDetail:
    """Test helper: combine item + play session into AbsBookDetail."""
    media = item.get("media") if isinstance(item.get("media"), dict) else {}
    meta = media.get("metadata") if isinstance(media.get("metadata"), dict) else {}
    title = str(meta.get("title") or "Audiobook")
    author = str(meta.get("authorName") or "")
    tracks = _parse_session_tracks(play, item_id=item_id, media=media)
    return AbsBookDetail(
        id=item_id,
        title=title,
        author=author,
        tracks=tracks,
        description=str(meta.get("description") or ""),
        session_id=str(play.get("id") or ""),
    )
