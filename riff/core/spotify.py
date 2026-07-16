"""Import Spotify playlists/albums — no Spotify account or API key needed.

The Spotube approach, adapted: Spotify supplies only the *metadata* (what
songs are on the playlist), then each song is matched on YouTube Music and
played from there like everything else in Riff. Metadata comes from
Spotify's public embed pages (open.spotify.com/embed/…) — the exact same
payload any website embedding a playlist receives, fetched anonymously.

Pure parsing/matching helpers are kept free of network and GTK so they are
unit-testable; only ``fetch()`` touches the network.
"""

from __future__ import annotations

import json
import logging
import re
import urllib.request
from dataclasses import dataclass, field
from difflib import SequenceMatcher

log = logging.getLogger("riff.spotify")

_EMBED_URL = "https://open.spotify.com/embed/{kind}/{item_id}"
_UA = ("Mozilla/5.0 (X11; Linux x86_64; rv:130.0) "
       "Gecko/20100101 Firefox/130.0")

# open.spotify.com/playlist/<id>, /album/<id>, optional /intl-xx/ prefix,
# and spotify:playlist:<id> URIs.
_URL_RE = re.compile(
    r"(?:open\.spotify\.com/(?:intl-[a-z]{2}(?:-[A-Za-z]{2})?/)?"
    r"(playlist|album|track)/|spotify:(playlist|album|track):)"
    r"([A-Za-z0-9]{15,40})")

_NEXT_DATA_RE = re.compile(
    r'<script[^>]*id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.DOTALL)


@dataclass
class SpotifyTrack:
    title: str
    artists: str  # display string, possibly several names
    duration: int = 0  # seconds

    @property
    def query(self) -> str:
        return f"{self.title} {self.artists}".strip()


@dataclass
class SpotifyList:
    name: str
    kind: str  # "playlist" | "album"
    subtitle: str = ""
    tracks: list[SpotifyTrack] = field(default_factory=list)


def parse_spotify_url(text: str) -> tuple[str, str] | None:
    """Extract (kind, id) from a Spotify link/URI; None when not one."""
    m = _URL_RE.search(text or "")
    if not m:
        return None
    kind = m.group(1) or m.group(2)
    return kind, m.group(3)


def parse_embed_html(html: str, kind: str = "playlist") -> SpotifyList:
    """Parse a Spotify embed page into a SpotifyList. Raises on no data."""
    m = _NEXT_DATA_RE.search(html or "")
    if not m:
        raise RuntimeError("Spotify returned no embed data for this link")
    data = json.loads(m.group(1))
    entity = _find_entity(data)
    if entity is None:
        raise RuntimeError(
            "Couldn't read the playlist from Spotify — the link may be "
            "private, region-locked, or Spotify changed their page")
    tracks = []
    for item in entity.get("trackList") or []:
        title = str(item.get("title") or "").strip()
        if not title:
            continue
        duration = item.get("duration") or 0
        try:
            duration = int(duration)
        except (TypeError, ValueError):
            duration = 0
        if duration > 30_000:  # milliseconds → seconds
            duration //= 1000
        tracks.append(SpotifyTrack(
            title=title,
            artists=str(item.get("subtitle") or "").strip(),
            duration=duration,
        ))
    if not tracks:
        raise RuntimeError("This Spotify link has no visible songs")
    return SpotifyList(
        name=str(entity.get("name") or entity.get("title") or "Spotify import"),
        kind=kind,
        subtitle=str(entity.get("subtitle") or ""),
        tracks=tracks,
    )


def _find_entity(node) -> dict | None:
    """Locate the dict carrying trackList anywhere in the embed JSON.

    Spotify reshuffles the exact path between releases; searching the tree
    keeps the import working across their changes.
    """
    if isinstance(node, dict):
        if isinstance(node.get("trackList"), list):
            return node
        for value in node.values():
            found = _find_entity(value)
            if found is not None:
                return found
    elif isinstance(node, list):
        for value in node:
            found = _find_entity(value)
            if found is not None:
                return found
    return None


def fetch(kind: str, item_id: str) -> SpotifyList:
    """Blocking: download and parse a public playlist/album. Raises on
    failure with a user-presentable message."""
    url = _EMBED_URL.format(kind=kind, item_id=item_id)
    req = urllib.request.Request(url, headers={
        "User-Agent": _UA,
        "Accept-Language": "en",
    })
    try:
        with urllib.request.urlopen(req, timeout=25) as resp:
            html = resp.read().decode("utf-8", "replace")
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"Couldn't reach Spotify: {exc}") from exc
    return parse_embed_html(html, kind)


# -- YouTube Music matching ---------------------------------------------------

def _similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, a.lower().strip(), b.lower().strip()).ratio()


def score_candidate(sp: SpotifyTrack, title: str, artist: str,
                    duration: int) -> float:
    """Similarity score 0..1 for a YT Music search result vs a Spotify
    track. Duration agreement matters most (same recording), then title,
    then artist overlap."""
    s_title = _similarity(sp.title, title)
    s_artist = _similarity(sp.artists, artist) if sp.artists else 0.5
    if sp.duration and duration:
        diff = abs(sp.duration - duration)
        tolerance = max(8.0, sp.duration * 0.12)
        s_dur = max(0.0, 1.0 - diff / (tolerance * 3))
    else:
        s_dur = 0.5
    return 0.45 * s_title + 0.2 * s_artist + 0.35 * s_dur


def match_on_ytmusic(api, sp_tracks: list[SpotifyTrack],
                     progress=None, min_score: float = 0.45):
    """Find each Spotify track on YouTube Music.

    Returns (matched_tracks, missed_spotify_tracks). ``progress(done,
    total)`` is called after every song when given. Never raises for a
    single bad track — one failed lookup must not kill an import.
    """
    matched, missed = [], []
    total = len(sp_tracks)
    for i, sp in enumerate(sp_tracks):
        best, best_score = None, 0.0
        try:
            results = api.search(sp.query, "songs").get("songs") or []
        except Exception:  # noqa: BLE001
            log.warning("search failed for %r", sp.query, exc_info=True)
            results = []
        for track in results[:6]:
            s = score_candidate(
                sp, track.title, track.artist, track.duration)
            if s > best_score:
                best, best_score = track, s
        if best is not None and best_score >= min_score:
            matched.append(best)
        else:
            missed.append(sp)
        if progress:
            progress(i + 1, total)
    return matched, missed
