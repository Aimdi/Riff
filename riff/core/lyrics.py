"""Synced lyrics — Better Lyrics, LRCLIB, KuGou (Riff Mobile parity).

Blocking network helpers; call from a worker thread.
"""

from __future__ import annotations

import base64
import json
import logging
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field

from .models import Track

log = logging.getLogger("riff.lyrics")

LRCLIB_API = "https://lrclib.net/api"
BETTER_API = "https://lyrics-api.boidu.dev"
_TAG = re.compile(r"\[(\d+):(\d{1,2}(?:\.\d+)?)\]")
_P_RE = re.compile(
    r'<p\s+[^>]*begin="([^"]+)"[^>]*(?:end="([^"]*)")?[^>]*>(.*?)</p>',
    re.I | re.S,
)
_SPAN_RE = re.compile(
    r'<span\s+[^>]*begin="([^"]+)"[^>]*(?:end="([^"]*)")?[^>]*>(.*?)</span>',
    re.I | re.S,
)
_UA = "Riff music player (github.com/Aimdi/Riff)"


@dataclass
class TtmlWord:
    begin_sec: float
    text: str
    end_sec: float | None = None


@dataclass
class TtmlLine:
    begin_sec: float
    text: str
    end_sec: float | None = None
    words: list[TtmlWord] = field(default_factory=list)

    @property
    def has_words(self) -> bool:
        return bool(self.words)


@dataclass
class LyricsResult:
    synced: list[tuple[float, str]]
    plain: str = ""
    source: str = ""
    ttml: str = ""


def parse_lrc(text: str) -> list[tuple[float, str]]:
    """Parse LRC text into a sorted [(seconds, line), …]."""
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


def parse_clock(begin: str) -> float | None:
    try:
        if ":" in begin:
            seconds = 0.0
            for part in begin.split(":"):
                seconds = seconds * 60 + float(part)
        else:
            seconds = float(begin)
        if seconds < 0:
            return None
        return seconds
    except (TypeError, ValueError):
        return None


def format_timestamp(seconds: float) -> str | None:
    if seconds < 0:
        return None
    m = int(seconds // 60)
    s = seconds - m * 60
    whole = int(s)
    frac = int(round((s - whole) * 100))
    if frac > 99:
        frac = 99
    return f"{m:02d}:{whole:02d}.{frac:02d}"


def _decode_ttml_text(raw: str) -> str:
    text = re.sub(r"<[^>]+>", "", raw or "")
    text = (
        text.replace("&amp;", "&")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&quot;", '"')
        .replace("&#39;", "'")
    )
    return re.sub(r"\s+", " ", text).strip()


def parse_ttml(ttml: str) -> list[TtmlLine]:
    out: list[TtmlLine] = []
    for m in _P_RE.finditer(ttml or ""):
        begin = parse_clock(m.group(1))
        if begin is None:
            continue
        end_raw = m.group(2)
        end = parse_clock(end_raw) if end_raw else None
        raw = m.group(3) or ""
        words: list[TtmlWord] = []
        for s in _SPAN_RE.finditer(raw):
            wb = parse_clock(s.group(1))
            if wb is None:
                continue
            we_raw = s.group(2)
            we = parse_clock(we_raw) if we_raw else None
            text = _decode_ttml_text(s.group(3) or "")
            if not text:
                continue
            words.append(TtmlWord(begin_sec=wb, end_sec=we, text=text))
        line_text = (
            " ".join(w.text for w in words) if words else _decode_ttml_text(raw)
        )
        if not line_text:
            continue
        out.append(TtmlLine(
            begin_sec=begin, end_sec=end, text=line_text, words=words))
    return out


def ttml_to_lrc(ttml: str) -> str | None:
    lines = parse_ttml(ttml)
    if not lines:
        return None
    buf: list[str] = []
    for line in lines:
        stamp = format_timestamp(line.begin_sec)
        if stamp is None:
            continue
        buf.append(f"[{stamp}]{line.text}")
    out = "\n".join(buf).strip()
    return out if "[" in out else None


def ttml_to_plain(ttml: str) -> str:
    lines = parse_ttml(ttml)
    return "\n".join(l.text for l in lines)


def _http_json(url: str, *, timeout: float = 12) -> object | None:
    req = urllib.request.Request(
        url, headers={"User-Agent": _UA, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.load(resp)
    except Exception:  # noqa: BLE001
        return None


def fetch_better_lyrics(
    artist: str, title: str, *, album: str = "", duration: int = 0,
) -> LyricsResult | None:
    params: dict[str, str] = {}
    if title.strip():
        params["s"] = title.strip()
    if artist.strip():
        params["a"] = artist.strip()
    if album.strip():
        params["al"] = album.strip()
    if duration > 0:
        params["d"] = str(duration)
    if not params:
        return None
    data = _http_json(f"{BETTER_API}/getLyrics?{urllib.parse.urlencode(params)}")
    if not isinstance(data, dict):
        return None
    ttml = data.get("ttml")
    if not isinstance(ttml, str) or not ttml.strip():
        return None
    lrc = ttml_to_lrc(ttml)
    if not lrc:
        return None
    return LyricsResult(
        synced=parse_lrc(lrc),
        plain=ttml_to_plain(ttml),
        source="better",
        ttml=ttml,
    )


def fetch_lrclib(
    artist: str, title: str, *, album: str = "", duration: int = 0,
) -> LyricsResult | None:
    params = {"track_name": title, "artist_name": artist}
    if album:
        params["album_name"] = album
    if duration:
        params["duration"] = str(duration)
    record = None
    try:
        data = _http_json(f"{LRCLIB_API}/get?{urllib.parse.urlencode(params)}")
        if isinstance(data, dict):
            record = data
    except Exception:  # noqa: BLE001
        record = None
    if not record:
        q = urllib.parse.urlencode({"q": f"{artist} {title}".strip()})
        results = _http_json(f"{LRCLIB_API}/search?{q}")
        if isinstance(results, list):
            for r in results:
                if isinstance(r, dict) and (
                        r.get("syncedLyrics") or r.get("plainLyrics")):
                    record = r
                    break
    if not record:
        return None
    synced = parse_lrc(record.get("syncedLyrics") or "")
    plain = record.get("plainLyrics") or ""
    if not synced and not plain:
        return None
    return LyricsResult(synced=synced, plain=plain or "", source="lrclib")


def _kugou_keyword(artist: str, title: str) -> str:
    new_title = title
    featuring = ""
    feat_idx = title.find(" (feat. ")
    if feat_idx != -1:
        end = title.find(")", feat_idx)
        if end != -1:
            featuring = title[feat_idx + 8:end]
            new_title = title[:feat_idx]
    new_artist = (featuring and f"{artist}, {featuring}" or artist)
    new_artist = (
        new_artist.replace(", ", "、").replace(" & ", "、").replace(".", ""))
    return f"{new_artist} - {new_title}"


def _kugou_first_candidate(data) -> tuple[str, str] | None:
    if isinstance(data, str):
        try:
            data = json.loads(data)
        except json.JSONDecodeError:
            return None
    if not isinstance(data, dict):
        return None
    cands = data.get("candidates")
    if not isinstance(cands, list) or not cands:
        return None
    first = cands[0]
    if not isinstance(first, dict):
        return None
    cid, key = first.get("id"), first.get("accesskey")
    if cid is None or key is None:
        return None
    return str(cid), str(key)


def _kugou_download(cid: str, access_key: str) -> str | None:
    qs = urllib.parse.urlencode({
        "ver": 1, "man": "yes", "client": "pc", "fmt": "lrc",
        "id": cid, "accesskey": access_key,
    })
    data = _http_json(f"https://krcs.kugou.com/download?{qs}")
    if not isinstance(data, dict):
        return None
    content = data.get("content")
    if not isinstance(content, str) or not content:
        return None
    try:
        text = base64.b64decode(content).decode("utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        return None
    return text if "[" in text else None


def fetch_kugou(
    artist: str, title: str, *, duration: int = 0,
) -> LyricsResult | None:
    keyword = _kugou_keyword(artist, title)
    qs = urllib.parse.urlencode({
        "version": 9108, "plat": 0, "pagesize": 8, "showtype": 0,
        "keyword": keyword,
    })
    songs_data = _http_json(
        f"https://mobileservice.kugou.com/api/v3/search/song?{qs}")
    info = []
    if isinstance(songs_data, dict):
        raw = (songs_data.get("data") or {}).get("info")
        if isinstance(raw, list):
            info = raw
    for tol in range(0, 6):
        for s in info:
            if not isinstance(s, dict):
                continue
            try:
                dur = int(s.get("duration") or 0)
            except (TypeError, ValueError):
                dur = 0
            if duration > 0 and abs(dur - duration) > tol:
                continue
            h = s.get("hash")
            if not h:
                continue
            cand = _http_json(
                "https://krcs.kugou.com/search?"
                + urllib.parse.urlencode({
                    "ver": 1, "man": "yes", "client": "mobi", "hash": h}))
            pair = _kugou_first_candidate(cand)
            if not pair:
                continue
            lrc = _kugou_download(*pair)
            if lrc:
                return LyricsResult(synced=parse_lrc(lrc), source="kugou")
    cand = _http_json(
        "https://krcs.kugou.com/search?"
        + urllib.parse.urlencode({
            "ver": 1, "man": "yes", "client": "mobi", "keyword": keyword}))
    pair = _kugou_first_candidate(cand)
    if pair:
        lrc = _kugou_download(*pair)
        if lrc:
            return LyricsResult(synced=parse_lrc(lrc), source="kugou")
    return None


def fetch_lyrics(
    track: Track,
    *,
    source: str = "auto",
) -> tuple[list[tuple[float, str]], str]:
    """Returns (synced_lines, plain_text); either may be empty.

    ``source``: ``auto`` | ``better`` | ``lrclib`` (KuGou always last fallback).
    Blocking — call from a worker thread.
    """
    artist = track.artists[0] if track.artists else ""
    title = track.title or ""
    album = track.album or ""
    duration = int(track.duration or 0)
    src = (source or "auto").strip().lower()
    if src in ("betterlyrics", "better_lyrics"):
        src = "better"
    providers = []
    if src == "better":
        providers = ["better", "lrclib", "kugou"]
    elif src == "lrclib":
        providers = ["lrclib", "kugou"]
    else:
        providers = ["lrclib", "better", "kugou"]

    for name in providers:
        try:
            if name == "better":
                hit = fetch_better_lyrics(
                    artist, title, album=album, duration=duration)
            elif name == "lrclib":
                hit = fetch_lrclib(
                    artist, title, album=album, duration=duration)
            else:
                hit = fetch_kugou(artist, title, duration=duration)
        except Exception:  # noqa: BLE001
            log.debug("%s lyrics failed for %s", name, title, exc_info=True)
            hit = None
        if hit and (hit.synced or hit.plain):
            return hit.synced, hit.plain
    return [], ""


def line_index_at(lines: list[tuple[float, str]], position: float) -> int:
    """Index of the line active at `position` seconds, -1 before the first."""
    idx = -1
    for i, (ts, _text) in enumerate(lines):
        if ts <= position:
            idx = i
        else:
            break
    return idx
