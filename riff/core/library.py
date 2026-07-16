"""Local library: favorites, listening history, user playlists, downloads.

SQLite-backed; safe for use from worker threads (connection per call is
avoided by a lock — the workload here is tiny).
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time

from .models import Track

SCHEMA = """
CREATE TABLE IF NOT EXISTS favorites (
    video_id TEXT PRIMARY KEY,
    track_json TEXT NOT NULL,
    added_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    video_id TEXT NOT NULL,
    track_json TEXT NOT NULL,
    played_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_history_video ON history(video_id);
CREATE TABLE IF NOT EXISTS playlists (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS playlist_items (
    playlist_id INTEGER NOT NULL REFERENCES playlists(id) ON DELETE CASCADE,
    position INTEGER NOT NULL,
    video_id TEXT NOT NULL,
    track_json TEXT NOT NULL,
    PRIMARY KEY (playlist_id, position)
);
CREATE TABLE IF NOT EXISTS downloads (
    video_id TEXT PRIMARY KEY,
    track_json TEXT NOT NULL,
    path TEXT NOT NULL,
    downloaded_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS follows (
    browse_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    thumbnail TEXT NOT NULL DEFAULT '',
    followed_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS dislikes (
    video_id TEXT PRIMARY KEY,
    track_json TEXT NOT NULL,
    added_at REAL NOT NULL
);
"""


class Library:
    def __init__(self, db_path: str = ":memory:"):
        self._lock = threading.Lock()
        self._db = sqlite3.connect(db_path, check_same_thread=False)
        self._db.execute("PRAGMA foreign_keys = ON")
        with self._lock, self._db:
            self._db.executescript(SCHEMA)

    def close(self) -> None:
        with self._lock:
            self._db.close()

    # -- favorites ---------------------------------------------------------

    def add_favorite(self, track: Track) -> None:
        with self._lock, self._db:
            self._db.execute(
                "INSERT OR REPLACE INTO favorites (video_id, track_json, added_at) VALUES (?,?,?)",
                (track.video_id, json.dumps(track.to_dict()), time.time()),
            )

    def remove_favorite(self, video_id: str) -> None:
        with self._lock, self._db:
            self._db.execute("DELETE FROM favorites WHERE video_id = ?", (video_id,))

    def is_favorite(self, video_id: str) -> bool:
        with self._lock:
            row = self._db.execute(
                "SELECT 1 FROM favorites WHERE video_id = ?", (video_id,)
            ).fetchone()
        return row is not None

    def favorites(self) -> list[Track]:
        with self._lock:
            rows = self._db.execute(
                "SELECT track_json FROM favorites ORDER BY added_at DESC"
            ).fetchall()
        return [Track.from_dict(json.loads(r[0])) for r in rows]

    def toggle_favorite(self, track: Track) -> bool:
        """Returns the new favorite state."""
        if self.is_favorite(track.video_id):
            self.remove_favorite(track.video_id)
            return False
        self.add_favorite(track)
        return True

    # -- history -------------------------------------------------------------

    def record_play(self, track: Track) -> None:
        with self._lock, self._db:
            self._db.execute(
                "INSERT INTO history (video_id, track_json, played_at) VALUES (?,?,?)",
                (track.video_id, json.dumps(track.to_dict()), time.time()),
            )
            # keep history bounded
            self._db.execute(
                "DELETE FROM history WHERE id NOT IN "
                "(SELECT id FROM history ORDER BY id DESC LIMIT 500)"
            )

    def recent(self, limit: int = 50) -> list[Track]:
        """Most recently played, deduplicated."""
        with self._lock:
            rows = self._db.execute(
                "SELECT track_json FROM history WHERE id IN "
                "(SELECT MAX(id) FROM history GROUP BY video_id) "
                "ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [Track.from_dict(json.loads(r[0])) for r in rows]

    def most_played(self, limit: int = 25) -> list[tuple[Track, int]]:
        with self._lock:
            rows = self._db.execute(
                "SELECT track_json, COUNT(*) as plays FROM history "
                "GROUP BY video_id ORDER BY plays DESC, MAX(id) DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [(Track.from_dict(json.loads(r[0])), r[1]) for r in rows]

    # -- playlists -----------------------------------------------------------

    def create_playlist(self, name: str) -> int:
        with self._lock, self._db:
            cur = self._db.execute(
                "INSERT INTO playlists (name, created_at) VALUES (?,?)",
                (name, time.time()),
            )
            return cur.lastrowid

    def delete_playlist(self, playlist_id: int) -> None:
        with self._lock, self._db:
            self._db.execute("DELETE FROM playlists WHERE id = ?", (playlist_id,))

    def rename_playlist(self, playlist_id: int, name: str) -> None:
        with self._lock, self._db:
            self._db.execute(
                "UPDATE playlists SET name = ? WHERE id = ?", (name, playlist_id)
            )

    def playlists(self) -> list[tuple[int, str, int]]:
        """[(id, name, track_count)]"""
        with self._lock:
            rows = self._db.execute(
                "SELECT p.id, p.name, COUNT(i.video_id) FROM playlists p "
                "LEFT JOIN playlist_items i ON i.playlist_id = p.id "
                "GROUP BY p.id ORDER BY p.created_at"
            ).fetchall()
        return [(r[0], r[1], r[2]) for r in rows]

    def playlist_tracks(self, playlist_id: int) -> list[Track]:
        with self._lock:
            rows = self._db.execute(
                "SELECT track_json FROM playlist_items WHERE playlist_id = ? "
                "ORDER BY position",
                (playlist_id,),
            ).fetchall()
        return [Track.from_dict(json.loads(r[0])) for r in rows]

    def find_playlist(self, name: str) -> int | None:
        with self._lock:
            row = self._db.execute(
                "SELECT id FROM playlists WHERE name = ?", (name,)
            ).fetchone()
        return row[0] if row else None

    def replace_playlist_tracks(self, playlist_id: int,
                                tracks: list[Track]) -> None:
        with self._lock, self._db:
            self._db.execute(
                "DELETE FROM playlist_items WHERE playlist_id = ?",
                (playlist_id,))
            self._db.executemany(
                "INSERT INTO playlist_items (playlist_id, position, video_id, track_json) "
                "VALUES (?,?,?,?)",
                [(playlist_id, i, t.video_id, json.dumps(t.to_dict()))
                 for i, t in enumerate(tracks)])

    def add_to_playlist(self, playlist_id: int, track: Track) -> None:
        with self._lock, self._db:
            row = self._db.execute(
                "SELECT COALESCE(MAX(position), -1) FROM playlist_items "
                "WHERE playlist_id = ?",
                (playlist_id,),
            ).fetchone()
            self._db.execute(
                "INSERT INTO playlist_items (playlist_id, position, video_id, track_json) "
                "VALUES (?,?,?,?)",
                (playlist_id, row[0] + 1, track.video_id, json.dumps(track.to_dict())),
            )

    def remove_from_playlist(self, playlist_id: int, position: int) -> None:
        with self._lock, self._db:
            self._db.execute(
                "DELETE FROM playlist_items WHERE playlist_id = ? AND position = ?",
                (playlist_id, position),
            )
            self._db.execute(
                "UPDATE playlist_items SET position = position - 1 "
                "WHERE playlist_id = ? AND position > ?",
                (playlist_id, position),
            )

    # -- dislikes ("never play this") -------------------------------------------

    def add_dislike(self, track: Track) -> None:
        with self._lock, self._db:
            self._db.execute(
                "INSERT OR REPLACE INTO dislikes (video_id, track_json, added_at) "
                "VALUES (?,?,?)",
                (track.video_id, json.dumps(track.to_dict()), time.time()))

    def remove_dislike(self, video_id: str) -> None:
        with self._lock, self._db:
            self._db.execute(
                "DELETE FROM dislikes WHERE video_id = ?", (video_id,))

    def is_disliked(self, video_id: str) -> bool:
        with self._lock:
            row = self._db.execute(
                "SELECT 1 FROM dislikes WHERE video_id = ?", (video_id,)
            ).fetchone()
        return row is not None

    def disliked_ids(self) -> set[str]:
        with self._lock:
            rows = self._db.execute("SELECT video_id FROM dislikes").fetchall()
        return {r[0] for r in rows}

    def dislikes(self) -> list[Track]:
        with self._lock:
            rows = self._db.execute(
                "SELECT track_json FROM dislikes ORDER BY added_at DESC"
            ).fetchall()
        return [Track.from_dict(json.loads(r[0])) for r in rows]

    # -- stats ---------------------------------------------------------------

    def stats_overview(self) -> dict:
        with self._lock:
            total, distinct, first = self._db.execute(
                "SELECT COUNT(*), COUNT(DISTINCT video_id), MIN(played_at) "
                "FROM history").fetchone()
            seconds = self._db.execute(
                "SELECT COALESCE(SUM(json_extract(track_json, '$.duration')), 0) "
                "FROM history").fetchone()[0]
        return {
            "plays": total or 0,
            "songs": distinct or 0,
            "seconds": int(seconds or 0),
            "since": first,
        }

    def top_artists(self, limit: int = 10) -> list[tuple[str, int]]:
        with self._lock:
            rows = self._db.execute(
                "SELECT track_json FROM history").fetchall()
        counts: dict[str, int] = {}
        for (track_json,) in rows:
            for artist in json.loads(track_json).get("artists") or []:
                if artist:
                    counts[artist] = counts.get(artist, 0) + 1
        ranked = sorted(counts.items(), key=lambda kv: -kv[1])
        return ranked[:limit]

    def plays_by_day(self, days: int = 14) -> list[tuple[str, int]]:
        """[(YYYY-MM-DD, count)] for the last `days` days, oldest first,
        including zero-play days."""
        with self._lock:
            rows = self._db.execute(
                "SELECT date(played_at, 'unixepoch', 'localtime') d, COUNT(*) "
                "FROM history WHERE played_at >= strftime('%s','now') - ? "
                "GROUP BY d",
                (days * 86400,)).fetchall()
        counts = {r[0]: r[1] for r in rows}
        import datetime

        today = datetime.date.today()
        out = []
        for i in range(days - 1, -1, -1):
            day = (today - datetime.timedelta(days=i)).isoformat()
            out.append((day, counts.get(day, 0)))
        return out

    # -- followed artists ------------------------------------------------------

    def follow_artist(self, browse_id: str, name: str, thumbnail: str = "") -> None:
        with self._lock, self._db:
            self._db.execute(
                "INSERT OR REPLACE INTO follows (browse_id, name, thumbnail, followed_at) "
                "VALUES (?,?,?,?)",
                (browse_id, name, thumbnail, time.time()),
            )

    def unfollow_artist(self, browse_id: str) -> None:
        with self._lock, self._db:
            self._db.execute("DELETE FROM follows WHERE browse_id = ?", (browse_id,))

    def is_followed(self, browse_id: str) -> bool:
        with self._lock:
            row = self._db.execute(
                "SELECT 1 FROM follows WHERE browse_id = ?", (browse_id,)
            ).fetchone()
        return row is not None

    def followed_artists(self) -> list[tuple[str, str, str]]:
        """[(browse_id, name, thumbnail)] most recently followed first."""
        with self._lock:
            rows = self._db.execute(
                "SELECT browse_id, name, thumbnail FROM follows "
                "ORDER BY followed_at DESC"
            ).fetchall()
        return [(r[0], r[1], r[2]) for r in rows]

    # -- downloads -----------------------------------------------------------

    def record_download(self, track: Track, path: str) -> None:
        with self._lock, self._db:
            self._db.execute(
                "INSERT OR REPLACE INTO downloads (video_id, track_json, path, downloaded_at) "
                "VALUES (?,?,?,?)",
                (track.video_id, json.dumps(track.to_dict()), path, time.time()),
            )

    def remove_download(self, video_id: str) -> None:
        with self._lock, self._db:
            self._db.execute("DELETE FROM downloads WHERE video_id = ?", (video_id,))

    def download_path(self, video_id: str) -> str | None:
        with self._lock:
            row = self._db.execute(
                "SELECT path FROM downloads WHERE video_id = ?", (video_id,)
            ).fetchone()
        return row[0] if row else None

    def downloads(self) -> list[Track]:
        with self._lock:
            rows = self._db.execute(
                "SELECT track_json, path FROM downloads ORDER BY downloaded_at DESC"
            ).fetchall()
        out = []
        for track_json, path in rows:
            t = Track.from_dict(json.loads(track_json))
            t.local_path = path
            out.append(t)
        return out
