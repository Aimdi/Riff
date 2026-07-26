"""Subsonic-compatible Cloud music (Navidrome / OpenSubsonic / …).

Riff Mobile Cloud tab port. Blocking network helpers; call via ``run_async``.
Tracks use ``cloud_`` video_id + ``stream_url`` so playback skips yt-dlp.
"""

from __future__ import annotations

import hashlib
import json
import logging
import secrets
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field

from .models import Track

log = logging.getLogger("riff.cloud")

_UA = "Riff/1.0 (Cloud; Subsonic-compatible; +https://github.com/Aimdi/Riff)"
_API_VERSION = "1.16.1"
_CLIENT = "Riff"


class CloudApiError(RuntimeError):
    def __init__(self, code: int | None, message: str):
        super().__init__(message or f"Server error ({code})")
        self.code = code

    @property
    def is_auth_error(self) -> bool:
        return self.code in (40, 41)


@dataclass
class CloudSong:
    id: str
    title: str
    artist: str = ""
    album: str = ""
    album_id: str = ""
    cover_art: str = ""
    duration: int = 0
    track: int = 0


@dataclass
class CloudAlbum:
    id: str
    name: str
    artist: str = ""
    cover_art: str = ""
    song_count: int = 0
    year: int = 0


@dataclass
class CloudPlaylist:
    id: str
    name: str
    cover_art: str = ""
    song_count: int = 0
    duration: int = 0


@dataclass
class CloudCollection:
    id: str
    name: str
    subtitle: str = ""
    cover_art: str = ""
    songs: list[CloudSong] = field(default_factory=list)


@dataclass
class CloudSearchResult:
    songs: list[CloudSong] = field(default_factory=list)
    albums: list[CloudAlbum] = field(default_factory=list)


@dataclass
class CloudSession:
    host: str
    username: str
    password: str
    legacy_auth: bool = False


def normalize_host(raw: str) -> str:
    h = (raw or "").strip()
    while h.endswith("/"):
        h = h[:-1]
    if not h:
        return ""
    if not h.startswith(("http://", "https://")):
        h = f"https://{h}"
    return h


def _as_list(parent, key: str) -> list:
    if not isinstance(parent, dict):
        return []
    value = parent.get(key)
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        return [value]
    return []


def _parse_song(raw) -> CloudSong | None:
    if not isinstance(raw, dict) or not raw.get("id"):
        return None
    try:
        dur = int(raw.get("duration") or 0)
    except (TypeError, ValueError):
        dur = 0
    try:
        track = int(raw.get("track") or 0)
    except (TypeError, ValueError):
        track = 0
    return CloudSong(
        id=str(raw["id"]),
        title=str(raw.get("title") or raw.get("name") or "Untitled"),
        artist=str(raw.get("artist") or ""),
        album=str(raw.get("album") or ""),
        album_id=str(raw.get("albumId") or ""),
        cover_art=str(raw.get("coverArt") or ""),
        duration=max(0, dur),
        track=track,
    )


def _parse_album(raw) -> CloudAlbum | None:
    if not isinstance(raw, dict) or not raw.get("id"):
        return None
    try:
        count = int(raw.get("songCount") or 0)
    except (TypeError, ValueError):
        count = 0
    try:
        year = int(raw.get("year") or 0)
    except (TypeError, ValueError):
        year = 0
    return CloudAlbum(
        id=str(raw["id"]),
        name=str(raw.get("name") or raw.get("title") or raw.get("album") or "Album"),
        artist=str(raw.get("artist") or ""),
        cover_art=str(raw.get("coverArt") or ""),
        song_count=count,
        year=year,
    )


def _parse_playlist(raw) -> CloudPlaylist | None:
    if not isinstance(raw, dict) or not raw.get("id"):
        return None
    try:
        count = int(raw.get("songCount") or 0)
    except (TypeError, ValueError):
        count = 0
    try:
        dur = int(raw.get("duration") or 0)
    except (TypeError, ValueError):
        dur = 0
    return CloudPlaylist(
        id=str(raw["id"]),
        name=str(raw.get("name") or "Playlist"),
        cover_art=str(raw.get("coverArt") or ""),
        song_count=count,
        duration=max(0, dur),
    )


def auth_params(
    username: str, password: str, *, legacy: bool = False,
) -> dict[str, str]:
    base = {
        "u": username,
        "v": _API_VERSION,
        "c": _CLIENT,
        "f": "json",
    }
    if legacy:
        hex_pass = password.encode("utf-8").hex()
        base["p"] = f"enc:{hex_pass}"
        return base
    salt = secrets.token_hex(6)
    token = hashlib.md5(f"{password}{salt}".encode("utf-8")).hexdigest()
    base["t"] = token
    base["s"] = salt
    return base


def rest_url(
    session: CloudSession, endpoint: str, params: dict | None = None,
) -> str:
    query = auth_params(
        session.username, session.password, legacy=session.legacy_auth)
    if params:
        query.update({k: str(v) for k, v in params.items()})
    return f"{session.host}/rest/{endpoint}?{urllib.parse.urlencode(query)}"


def stream_url(session: CloudSession, song_id: str) -> str:
    return rest_url(session, "stream.view", {"id": song_id})


def cover_url(
    session: CloudSession, cover_art: str, *, size: int = 400,
) -> str:
    if not cover_art:
        return ""
    return rest_url(
        session, "getCoverArt.view", {"id": cover_art, "size": str(size)})


def song_to_track(session: CloudSession, song: CloudSong) -> Track:
    return Track(
        video_id=f"cloud_{song.id}",
        title=song.title,
        artists=[song.artist] if song.artist else [session.host],
        album=song.album,
        duration=int(song.duration or 0),
        thumbnail=cover_url(session, song.cover_art),
        stream_url=stream_url(session, song.id),
    )


def songs_to_tracks(
    session: CloudSession, songs: list[CloudSong],
) -> list[Track]:
    return [song_to_track(session, s) for s in songs]


def _request(
    session: CloudSession, endpoint: str, params: dict | None = None,
    *, timeout: float = 30,
) -> dict:
    url = rest_url(session, endpoint, params)
    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:200]
        raise CloudApiError(exc.code, detail or exc.reason) from exc
    try:
        data = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError as exc:
        raise CloudApiError(None, "Unexpected server response") from exc
    body = data.get("subsonic-response") if isinstance(data, dict) else None
    if not isinstance(body, dict):
        raise CloudApiError(None, "Not a Subsonic-compatible server")
    if body.get("status") != "ok":
        err = body.get("error") if isinstance(body.get("error"), dict) else {}
        code = err.get("code")
        try:
            code_i = int(code) if code is not None else None
        except (TypeError, ValueError):
            code_i = None
        raise CloudApiError(code_i, str(err.get("message") or ""))
    return body


def login(host: str, username: str, password: str) -> CloudSession:
    h = normalize_host(host)
    if not h or not username:
        raise ValueError("Server URL and username are required")
    session = CloudSession(
        host=h, username=username, password=password or "", legacy_auth=False)
    try:
        _request(session, "ping.view")
    except CloudApiError as exc:
        if exc.code == 41:
            session.legacy_auth = True
            _request(session, "ping.view")
        else:
            raise
    return session


def fetch_albums(
    session: CloudSession, *, size: int = 40, offset: int = 0,
) -> list[CloudAlbum]:
    body = _request(session, "getAlbumList2.view", {
        "type": "alphabeticalByName",
        "size": str(size),
        "offset": str(offset),
    })
    return [
        a for a in (_parse_album(x) for x in _as_list(body.get("albumList2"), "album"))
        if a
    ]


def fetch_playlists(session: CloudSession) -> list[CloudPlaylist]:
    body = _request(session, "getPlaylists.view")
    return [
        p for p in (
            _parse_playlist(x) for x in _as_list(body.get("playlists"), "playlist")
        )
        if p
    ]


def fetch_random_songs(
    session: CloudSession, *, size: int = 40,
) -> list[CloudSong]:
    body = _request(session, "getRandomSongs.view", {"size": str(size)})
    return [
        s for s in (
            _parse_song(x) for x in _as_list(body.get("randomSongs"), "song")
        )
        if s
    ]


def fetch_album(session: CloudSession, album_id: str) -> CloudCollection:
    body = _request(session, "getAlbum.view", {"id": album_id})
    raw = body.get("album") if isinstance(body.get("album"), dict) else {}
    songs = [s for s in (_parse_song(x) for x in _as_list(raw, "song")) if s]
    return CloudCollection(
        id=album_id,
        name=str(raw.get("name") or raw.get("title") or "Album"),
        subtitle=str(raw.get("artist") or ""),
        cover_art=str(raw.get("coverArt") or ""),
        songs=songs,
    )


def fetch_playlist(session: CloudSession, playlist_id: str) -> CloudCollection:
    body = _request(session, "getPlaylist.view", {"id": playlist_id})
    raw = body.get("playlist") if isinstance(body.get("playlist"), dict) else {}
    songs = [s for s in (_parse_song(x) for x in _as_list(raw, "entry")) if s]
    return CloudCollection(
        id=playlist_id,
        name=str(raw.get("name") or "Playlist"),
        subtitle=str(raw.get("owner") or ""),
        cover_art=str(raw.get("coverArt") or ""),
        songs=songs,
    )


def search(session: CloudSession, query: str) -> CloudSearchResult:
    query = (query or "").strip()
    if not query:
        return CloudSearchResult()
    body = _request(session, "search3.view", {
        "query": query,
        "songCount": "80",
        "albumCount": "30",
        "artistCount": "0",
    })
    result = body.get("searchResult3")
    return CloudSearchResult(
        songs=[
            s for s in (_parse_song(x) for x in _as_list(result, "song")) if s
        ],
        albums=[
            a for a in (_parse_album(x) for x in _as_list(result, "album")) if a
        ],
    )


# --- test helpers (no network) ------------------------------------------------

def parse_album_list(body: dict) -> list[CloudAlbum]:
    return [
        a for a in (_parse_album(x) for x in _as_list(body.get("albumList2"), "album"))
        if a
    ]


def parse_random_songs(body: dict) -> list[CloudSong]:
    return [
        s for s in (_parse_song(x) for x in _as_list(body.get("randomSongs"), "song"))
        if s
    ]


def parse_album_detail(body: dict, *, album_id: str = "") -> CloudCollection:
    raw = body.get("album") if isinstance(body.get("album"), dict) else {}
    songs = [s for s in (_parse_song(x) for x in _as_list(raw, "song")) if s]
    return CloudCollection(
        id=album_id or str(raw.get("id") or ""),
        name=str(raw.get("name") or raw.get("title") or "Album"),
        subtitle=str(raw.get("artist") or ""),
        cover_art=str(raw.get("coverArt") or ""),
        songs=songs,
    )
