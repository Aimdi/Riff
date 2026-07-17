"""Thin wrapper around ytmusicapi that returns Riff's data models.

All methods are blocking; call them through riff.util.run_async from the UI.
Parsing is deliberately defensive — YouTube Music responses vary a lot in
shape and we never want one odd item to take a whole page down.
"""

from __future__ import annotations

import logging
import os
import threading

from ytmusicapi import YTMusic

from .. import config

# Optional account connection: create this file with
#   ytmusicapi browser --file ~/.config/riff/browser.json
# and the home feed, radio and search become personalized to your
# YouTube Music account. Riff itself stores nothing beyond this file.
AUTH_PATH = os.path.join(config.CONFIG_DIR, "browser.json")

from .models import (
    Album,
    Artist,
    HomeSection,
    Playlist,
    Track,
    _best_thumbnail,
    parse_duration,
)

log = logging.getLogger("riff.api")


class MusicApi:
    def __init__(self) -> None:
        self._yt: YTMusic | None = None
        self._yt_anon: YTMusic | None = None
        self._lock = threading.Lock()

    @property
    def yt(self) -> YTMusic:
        # Created lazily so the app window appears instantly even when the
        # network is slow; YTMusic() performs a request to get a visitor id.
        with self._lock:
            if self._yt is None:
                auth = AUTH_PATH if os.path.exists(AUTH_PATH) else None
                if auth:
                    log.info("using account credentials from %s", auth)
                self._yt = YTMusic(auth)
            return self._yt

    @property
    def authenticated(self) -> bool:
        return os.path.exists(AUTH_PATH)

    @property
    def yt_anon(self) -> YTMusic:
        """Anonymous client — used as fallback for public browse endpoints
        that occasionally misbehave with account credentials attached."""
        with self._lock:
            if self._yt_anon is None:
                if self._yt is not None and not self.authenticated:
                    self._yt_anon = self._yt
                else:
                    self._yt_anon = YTMusic()
            return self._yt_anon

    def _browse_with_fallback(self, call):
        """Run `call(client)` with the main client, retrying anonymously when
        an authenticated request fails on a public endpoint."""
        try:
            return call(self.yt)
        except Exception:
            if not self.authenticated:
                raise
            log.warning("authenticated browse failed; retrying anonymously",
                        exc_info=True)
            return call(self.yt_anon)

    # -- search ------------------------------------------------------------

    def search_suggestions(self, query: str) -> list[str]:
        try:
            return [s for s in self.yt.get_search_suggestions(query) if isinstance(s, str)]
        except Exception:  # noqa: BLE001
            return []

    def search(self, query: str, kind: str | None = None) -> dict[str, list]:
        """kind: None (top results) or songs/albums/artists/playlists.

        Returns {"songs": [Track], "albums": [Album], "artists": [Artist],
        "playlists": [Playlist]} — only the relevant keys are populated.
        """
        results = {"songs": [], "albums": [], "artists": [], "playlists": []}
        yt_filter = kind if kind in ("songs", "albums", "artists", "playlists") else None
        items = self.yt.search(query, filter=yt_filter, limit=30)
        for item in items:
            try:
                self._add_search_item(results, item)
            except Exception:  # noqa: BLE001
                log.debug("skipping unparsable search item: %r", item, exc_info=True)
        return results

    def _add_search_item(self, results: dict, item: dict) -> None:
        category = (item.get("resultType") or "").lower()
        if category in ("song", "video") and item.get("videoId"):
            results["songs"].append(Track.from_yt(item))
        elif category == "album" and item.get("browseId"):
            results["albums"].append(
                Album(
                    browse_id=item["browseId"],
                    title=item.get("title") or "",
                    artists=[a.get("name", "") for a in item.get("artists") or []],
                    year=str(item.get("year") or ""),
                    thumbnail=_best_thumbnail(item.get("thumbnails")),
                )
            )
        elif category == "artist" and (item.get("browseId") or item.get("artists")):
            results["artists"].append(
                Artist(
                    browse_id=item.get("browseId") or "",
                    name=item.get("artist") or item.get("title") or "",
                    thumbnail=_best_thumbnail(item.get("thumbnails")),
                )
            )
        elif category == "playlist" and item.get("browseId"):
            results["playlists"].append(
                Playlist(
                    playlist_id=item["browseId"],
                    title=item.get("title") or "",
                    author=item.get("author") or "",
                    thumbnail=_best_thumbnail(item.get("thumbnails")),
                    track_count=int(item.get("itemCount") or 0),
                )
            )

    # -- browse ------------------------------------------------------------

    def home(self, limit: int = 6) -> list[HomeSection]:
        sections: list[HomeSection] = []
        for raw in self.yt.get_home(limit=limit):
            items = []
            for item in raw.get("contents") or []:
                parsed = self._parse_home_item(item)
                if parsed is not None:
                    items.append(parsed)
            if items:
                sections.append(HomeSection(title=raw.get("title") or "", items=items))
        return sections

    def _parse_home_item(self, item: dict):
        try:
            if item.get("videoId"):
                return Track.from_yt(item)
            browse_id = item.get("browseId") or ""
            playlist_id = item.get("playlistId") or ""
            thumb = _best_thumbnail(item.get("thumbnails"))
            if browse_id.startswith("MPRE"):  # album
                artists = [a.get("name", "") for a in item.get("artists") or []]
                return Album(
                    browse_id=browse_id,
                    title=item.get("title") or "",
                    artists=artists,
                    year=str(item.get("year") or ""),
                    thumbnail=thumb,
                )
            if browse_id.startswith("UC"):  # artist/channel
                return Artist(
                    browse_id=browse_id,
                    name=item.get("title") or "",
                    thumbnail=thumb,
                )
            if playlist_id:
                return Playlist(
                    playlist_id=playlist_id,
                    title=item.get("title") or "",
                    author=(item.get("description") or "")[:80],
                    thumbnail=thumb,
                )
        except Exception:  # noqa: BLE001
            log.debug("skipping unparsable home item: %r", item, exc_info=True)
        return None

    def album(self, browse_id: str) -> Album:
        data = self.yt.get_album(browse_id)
        tracks = []
        thumb = _best_thumbnail(data.get("thumbnails"))
        artists = [a.get("name", "") for a in data.get("artists") or []]
        for t in data.get("tracks") or []:
            track = Track.from_yt(t)
            if not track.video_id:
                continue
            track.album = data.get("title") or ""
            track.album_id = browse_id
            if not track.thumbnail:
                track.thumbnail = thumb
            if not track.artists:
                track.artists = artists
            tracks.append(track)
        return Album(
            browse_id=browse_id,
            title=data.get("title") or "",
            artists=artists,
            year=str(data.get("year") or ""),
            thumbnail=thumb,
            track_count=int(data.get("trackCount") or len(tracks)),
            tracks=tracks,
        )

    def artist(self, channel_id: str) -> Artist:
        data = self.yt.get_artist(channel_id)
        songs = []
        for t in (data.get("songs") or {}).get("results") or []:
            track = Track.from_yt(t)
            if track.video_id:
                songs.append(track)

        def parse_albums(key: str) -> list[Album]:
            out = []
            for a in (data.get(key) or {}).get("results") or []:
                if not a.get("browseId"):
                    continue
                out.append(
                    Album(
                        browse_id=a["browseId"],
                        title=a.get("title") or "",
                        artists=[data.get("name") or ""],
                        year=str(a.get("year") or ""),
                        thumbnail=_best_thumbnail(a.get("thumbnails")),
                    )
                )
            return out

        related = []
        for r in (data.get("related") or {}).get("results") or []:
            if r.get("browseId"):
                related.append(Artist(
                    browse_id=r["browseId"],
                    name=r.get("title") or "",
                    thumbnail=_best_thumbnail(r.get("thumbnails")),
                ))

        return Artist(
            browse_id=channel_id,
            name=data.get("name") or "",
            thumbnail=_best_thumbnail(data.get("thumbnails")),
            description=data.get("description") or "",
            songs=songs,
            albums=parse_albums("albums"),
            singles=parse_albums("singles"),
            related=related,
        )

    def playlist(self, playlist_id: str) -> Playlist:
        data = self.yt.get_playlist(playlist_id, limit=200)
        tracks = []
        for t in data.get("tracks") or []:
            track = Track.from_yt(t)
            if track.video_id:
                tracks.append(track)
        author = data.get("author")
        if isinstance(author, dict):
            author = author.get("name") or ""
        return Playlist(
            playlist_id=playlist_id,
            title=data.get("title") or "",
            author=author or "",
            thumbnail=_best_thumbnail(data.get("thumbnails")),
            track_count=int(data.get("trackCount") or len(tracks)),
            tracks=tracks,
        )

    # -- explore -------------------------------------------------------------

    def mood_categories(self) -> list[tuple[str, list[tuple[str, str]]]]:
        """[(section title, [(category title, params), …]), …]"""
        data = self._browse_with_fallback(lambda yt: yt.get_mood_categories())
        out = []
        for section, cats in (data or {}).items():
            items = [
                (c.get("title") or "", c.get("params") or "")
                for c in cats or []
                if c.get("params")
            ]
            if items:
                out.append((section, items))
        return out

    def mood_playlists(self, params: str) -> list[Playlist]:
        data = self._browse_with_fallback(
            lambda yt: yt.get_mood_playlists(params))
        out = []
        for p in data or []:
            if not p.get("playlistId"):
                continue
            out.append(
                Playlist(
                    playlist_id=p["playlistId"],
                    title=p.get("title") or "",
                    author=p.get("description") or "",
                    thumbnail=_best_thumbnail(p.get("thumbnails")),
                )
            )
        return out

    def charts(self) -> list[Track]:
        """Global top songs; empty list when charts are unavailable."""
        try:
            data = self._browse_with_fallback(
                lambda yt: yt.get_charts(country="ZZ"))
        except Exception:  # noqa: BLE001 — some locales/accounts lack charts
            log.warning("charts unavailable", exc_info=True)
            return []
        tracks = []
        for v in (data.get("videos") or {}).get("items") or []:
            track = Track.from_yt(v)
            if track.video_id:
                tracks.append(track)
        return tracks

    # -- account library -------------------------------------------------------

    def library_playlists(self, limit: int = 50) -> list[Playlist]:
        """The signed-in account's playlists, incl. Liked Music ("LM").

        Empty when no account is connected.
        """
        if not self.authenticated:
            return []
        out = []
        for p in self.yt.get_library_playlists(limit=limit) or []:
            pid = p.get("playlistId")
            if not pid:
                continue
            author = p.get("author")
            if isinstance(author, list):
                author = ", ".join(
                    a.get("name", "") for a in author if isinstance(a, dict))
            elif isinstance(author, dict):
                author = author.get("name", "")
            try:
                count = int(p.get("count") or 0)
            except (TypeError, ValueError):
                count = 0
            out.append(
                Playlist(
                    playlist_id=pid,
                    title=p.get("title") or "",
                    author=str(author or ""),
                    thumbnail=_best_thumbnail(p.get("thumbnails")),
                    track_count=count,
                )
            )
        return out

    # -- radio / related ----------------------------------------------------

    def radio(self, video_id: str, limit: int = 25) -> list[Track]:
        """Songs that continue playback after `video_id` (YT Music radio)."""
        data = self.yt.get_watch_playlist(videoId=video_id, radio=True, limit=limit)
        tracks = []
        for t in data.get("tracks") or []:
            if not t.get("videoId") or t["videoId"] == video_id:
                continue
            track = Track.from_yt(t)
            if not track.duration and t.get("length"):
                track.duration = parse_duration(t["length"])
            tracks.append(track)
        return tracks

    def related_songs(self, video_id: str) -> list[Track]:
        """Songs similar to one song via the watch page's related feed
        (get_song_related). Falls back to radio when the feed is empty —
        callers get *some* similarity signal either way."""
        tracks: list[Track] = []
        try:
            watch = self.yt.get_watch_playlist(videoId=video_id, limit=1)
            browse = watch.get("related")
            if browse:
                for section in self.yt.get_song_related(browse) or []:
                    for item in section.get("contents") or []:
                        if not item.get("videoId") \
                                or item["videoId"] == video_id:
                            continue
                        try:
                            tracks.append(Track.from_yt(item))
                        except Exception:  # noqa: BLE001
                            continue
        except Exception:  # noqa: BLE001
            log.debug("related feed failed for %s", video_id, exc_info=True)
        if not tracks:
            tracks = self.radio(video_id)
        return tracks

    def lyrics(self, video_id: str) -> str:
        try:
            watch = self.yt.get_watch_playlist(videoId=video_id, limit=1)
            browse_id = watch.get("lyrics")
            if not browse_id:
                return ""
            data = self.yt.get_lyrics(browse_id)
            lyrics = (data or {}).get("lyrics")
            if isinstance(lyrics, list):  # timed lyrics
                lyrics = "\n".join(
                    line.get("text", "") if isinstance(line, dict) else str(line)
                    for line in lyrics
                )
            return lyrics or ""
        except Exception:  # noqa: BLE001
            return ""
