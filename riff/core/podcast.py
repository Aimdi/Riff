"""Podcasts — Apple directory search + RSS subscribe/play (Riff Mobile port).

Blocking network helpers; call via ``run_async`` from the UI.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field

from .models import Track

log = logging.getLogger("riff.podcast")

_UA = "Riff/1.0 (podcast; +https://github.com/Aimdi/Riff)"
_ITUNES = "http://www.itunes.com/dtds/podcast-1.0.dtd"
_MEDIA = "http://search.yahoo.com/mrss/"
_PODCAST = "https://podcastindex.org/namespace/1.0"


@dataclass
class PodcastShow:
    title: str
    author: str = ""
    artwork: str = ""
    feed_url: str = ""
    collection_id: str = ""

    def to_dict(self) -> dict:
        return {
            "title": self.title,
            "author": self.author,
            "artwork": self.artwork,
            "feed_url": self.feed_url,
            "collection_id": self.collection_id,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "PodcastShow":
        return cls(
            title=str(d.get("title") or ""),
            author=str(d.get("author") or ""),
            artwork=str(d.get("artwork") or ""),
            feed_url=str(d.get("feed_url") or d.get("feedUrl") or ""),
            collection_id=str(d.get("collection_id") or ""),
        )


@dataclass
class PodcastEpisode:
    guid: str
    title: str
    stream_url: str
    description: str = ""
    artwork: str = ""
    pub_date: str = ""
    duration_sec: int = 0
    size_bytes: int = 0
    show_title: str = ""
    transcript_url: str = ""
    transcript_type: str = ""
    chapters_url: str = ""

    @property
    def episode_id(self) -> str:
        digest = hashlib.md5(self.guid.encode("utf-8")).hexdigest()[:16]
        return f"podcast_{digest}"

    def to_track(self) -> Track:
        return Track(
            video_id=self.episode_id,
            title=self.title or "Episode",
            artists=[self.show_title] if self.show_title else [],
            album=self.show_title,
            duration=int(self.duration_sec or 0),
            thumbnail=self.artwork or "",
            stream_url=self.stream_url,
            transcript_url=self.transcript_url or "",
            transcript_type=self.transcript_type or "",
            chapters_url=self.chapters_url or "",
        )


def _http_get(url: str, *, timeout: float = 25) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def _http_json(url: str) -> dict:
    raw = _http_get(url)
    # Apple sometimes returns text/javascript.
    text = raw.decode("utf-8", errors="replace")
    return json.loads(text)


def search_shows(term: str, *, limit: int = 40) -> list[PodcastShow]:
    """Apple Podcasts directory search."""
    term = (term or "").strip()
    if not term:
        return []
    qs = urllib.parse.urlencode({
        "media": "podcast",
        "term": term,
        "limit": str(limit),
    })
    data = _http_json(f"https://itunes.apple.com/search?{qs}")
    out: list[PodcastShow] = []
    for row in data.get("results") or []:
        feed = (row.get("feedUrl") or "").strip()
        if not feed:
            continue
        art = (
            row.get("artworkUrl600")
            or row.get("artworkUrl100")
            or row.get("artworkUrl60")
            or ""
        )
        out.append(PodcastShow(
            title=str(row.get("collectionName") or row.get("trackName") or ""),
            author=str(row.get("artistName") or ""),
            artwork=str(art),
            feed_url=feed,
            collection_id=str(row.get("collectionId") or row.get("trackId") or ""),
        ))
    return out


PODCAST_GENRES: list[tuple[str, str]] = [
    ("1489", "News"),
    ("1303", "Comedy"),
    ("1488", "True Crime"),
    ("1324", "Society & Culture"),
    ("1321", "Business"),
    ("1318", "Technology"),
    ("1512", "History"),
    ("1487", "Health & Fitness"),
    ("1533", "Science"),
    ("1304", "Education"),
    ("1310", "Music"),
    ("1545", "Sports"),
    ("1483", "Fiction"),
    ("1314", "Religion & Spirituality"),
    ("1502", "Leisure"),
    ("1309", "TV & Film"),
    ("1301", "Arts"),
    ("1305", "Kids & Family"),
    ("1511", "Government"),
]


def _shows_from_chart_entries(entries) -> list[PodcastShow]:
    out: list[PodcastShow] = []
    for entry in entries or []:
        if not isinstance(entry, dict):
            continue
        name = ((entry.get("im:name") or {}).get("label")) or ""
        author = ((entry.get("im:artist") or {}).get("label")) or ""
        images = entry.get("im:image") or []
        art = ""
        if images:
            art = (images[-1].get("label") or "") if isinstance(
                images[-1], dict) else ""
        cid = ((entry.get("id") or {}).get("attributes") or {}).get("im:id") or ""
        out.append(PodcastShow(
            title=str(name),
            author=str(author),
            artwork=str(art),
            feed_url="",
            collection_id=str(cid),
        ))
    return out


def top_shows(*, limit: int = 25) -> list[PodcastShow]:
    """US top podcasts chart (may lack feedUrl until lookup)."""
    data = _http_json(
        f"https://itunes.apple.com/us/rss/toppodcasts/limit={int(limit)}/json")
    entries = ((data.get("feed") or {}).get("entry")) or []
    return _shows_from_chart_entries(entries)


def top_by_genre(genre_id: str, *, limit: int = 40) -> list[PodcastShow]:
    """Top podcasts in an Apple genre (may lack feedUrl until lookup)."""
    genre_id = (genre_id or "").strip()
    if not genre_id:
        return []
    data = _http_json(
        f"https://itunes.apple.com/us/rss/toppodcasts/"
        f"genre={urllib.parse.quote(genre_id)}/limit={int(limit)}/json")
    entries = ((data.get("feed") or {}).get("entry")) or []
    return _shows_from_chart_entries(entries)


def lookup_feed_urls(collection_ids: list[str]) -> dict[str, str]:
    """Map Apple collectionId → feedUrl."""
    ids = [c for c in collection_ids if c]
    if not ids:
        return {}
    qs = urllib.parse.urlencode({"id": ",".join(ids)})
    data = _http_json(f"https://itunes.apple.com/lookup?{qs}")
    out: dict[str, str] = {}
    for row in data.get("results") or []:
        cid = str(row.get("collectionId") or "")
        feed = (row.get("feedUrl") or "").strip()
        if cid and feed:
            out[cid] = feed
    return out


def ensure_feed_url(show: PodcastShow) -> PodcastShow:
    """Fill feed_url via Apple lookup when missing (charts)."""
    if show.feed_url or not show.collection_id:
        return show
    feeds = lookup_feed_urls([show.collection_id])
    feed = feeds.get(show.collection_id, "")
    if feed:
        show.feed_url = feed
    return show


def _strip_html(text: str) -> str:
    text = re.sub(r"(?is)<(script|style).*?>.*?</\1>", "", text or "")
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _parse_itunes_duration(raw: str | None) -> int:
    if not raw:
        return 0
    raw = raw.strip()
    if raw.isdigit():
        return int(raw)
    parts = raw.split(":")
    try:
        nums = [int(p) for p in parts]
    except ValueError:
        return 0
    if len(nums) == 3:
        return nums[0] * 3600 + nums[1] * 60 + nums[2]
    if len(nums) == 2:
        return nums[0] * 60 + nums[1]
    return 0


def _child_text(el: ET.Element, names: tuple[str, ...]) -> str:
    for name in names:
        node = el.find(name)
        if node is not None and (node.text or "").strip():
            return (node.text or "").strip()
    return ""


def _attr(el: ET.Element | None, key: str) -> str:
    if el is None:
        return ""
    return (el.attrib.get(key) or "").strip()


def parse_episodes(
    feed_xml: bytes | str,
    *,
    show_title: str = "",
    fallback_art: str = "",
    limit: int = 100,
) -> list[PodcastEpisode]:
    """Parse a podcast RSS/Atom-ish feed into episodes with enclosures."""
    if isinstance(feed_xml, str):
        feed_xml = feed_xml.encode("utf-8")
    try:
        root = ET.fromstring(feed_xml)
    except ET.ParseError:
        log.warning("invalid podcast RSS", exc_info=True)
        return []

    # RSS 2.0: channel/item ; some feeds put items under root.
    channel = root.find("channel")
    if channel is None:
        channel = root

    itunes_img = channel.find(f"{{{_ITUNES}}}image")
    channel_art = _attr(itunes_img, "href")
    if not channel_art:
        image = channel.find("image")
        if image is not None:
            channel_art = _child_text(image, ("url",))
    if not channel_art:
        channel_art = fallback_art
    if not show_title:
        show_title = _child_text(channel, ("title",))

    out: list[PodcastEpisode] = []
    for item in channel.findall("item"):
        enclosure = item.find("enclosure")
        url = _attr(enclosure, "url")
        if not url:
            continue
        guid = _child_text(item, ("guid",)) or url
        title = _child_text(item, ("title",)) or "Episode"
        desc = _strip_html(_child_text(item, ("description",)))
        pub = _child_text(item, ("pubDate",))
        # Compact date: "Mon, 19 Jul 2026 ..." → "19 Jul 2026"
        m = re.search(r"\d{1,2}\s+\w{3}\s+\d{4}", pub)
        date = m.group(0) if m else pub[:16]
        dur = _parse_itunes_duration(
            _child_text(item, (f"{{{_ITUNES}}}duration",)))
        try:
            size = int(_attr(enclosure, "length") or "0")
        except ValueError:
            size = 0
        ep_art = _attr(item.find(f"{{{_ITUNES}}}image"), "href")
        if not ep_art:
            ep_art = _attr(item.find(f"{{{_MEDIA}}}thumbnail"), "url")
        if not ep_art:
            ep_art = channel_art
        chapters_url = _attr(
            item.find(f"{{{_PODCAST}}}chapters"), "url")
        transcript_url, transcript_type = _best_transcript(item)
        out.append(PodcastEpisode(
            guid=guid,
            title=title,
            stream_url=url,
            description=desc,
            artwork=ep_art,
            pub_date=date,
            duration_sec=dur,
            size_bytes=size,
            show_title=show_title,
            transcript_url=transcript_url,
            transcript_type=transcript_type,
            chapters_url=chapters_url,
        ))
        if len(out) >= limit:
            break
    return out


def _best_transcript(item: ET.Element) -> tuple[str, str]:
    from .podcast_transcript import pick_best_transcript

    candidates: list[tuple[str, str]] = []
    for node in item.findall(f"{{{_PODCAST}}}transcript"):
        url = _attr(node, "url")
        if url:
            candidates.append((url, (_attr(node, "type") or "").lower()))
    return pick_best_transcript(candidates)


def fetch_episodes(
    feed_url: str,
    *,
    show_title: str = "",
    artwork: str = "",
    limit: int = 100,
) -> list[PodcastEpisode]:
    raw = _http_get(feed_url)
    return parse_episodes(
        raw, show_title=show_title, fallback_art=artwork, limit=limit)


def is_podcast_track(track: Track | None) -> bool:
    if track is None:
        return False
    if (track.stream_url or "").startswith(("http://", "https://")):
        return True
    return (track.video_id or "").startswith("podcast_")
