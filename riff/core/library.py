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

import logging

log = logging.getLogger("riff.library")

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
CREATE TABLE IF NOT EXISTS playlist_folders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    position INTEGER NOT NULL DEFAULT 0,
    created_at REAL NOT NULL,
    icon TEXT NOT NULL DEFAULT 'folder-music-symbolic',
    color TEXT NOT NULL DEFAULT '#3b82f6',
    emoji TEXT NOT NULL DEFAULT '🎵'
);
CREATE TABLE IF NOT EXISTS playlists (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    created_at REAL NOT NULL,
    folder_id INTEGER REFERENCES playlist_folders(id) ON DELETE SET NULL,
    position INTEGER NOT NULL DEFAULT 0
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
CREATE TABLE IF NOT EXISTS listen_events (
    id INTEGER PRIMARY KEY,
    video_id TEXT NOT NULL,
    artist_key TEXT NOT NULL,
    ts INTEGER NOT NULL,
    source TEXT NOT NULL,
    listened_fraction REAL,
    event TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_events_artist_ts ON listen_events(artist_key, ts);
CREATE INDEX IF NOT EXISTS idx_events_video_ts  ON listen_events(video_id, ts);
CREATE TABLE IF NOT EXISTS artist_affinity (
    artist_key TEXT PRIMARY KEY,
    score REAL NOT NULL,
    updated_ts INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS track_cooccurrence (
    a TEXT NOT NULL, b TEXT NOT NULL,
    weight REAL NOT NULL,
    updated_ts INTEGER NOT NULL,
    PRIMARY KEY (a, b)
);
CREATE TABLE IF NOT EXISTS impressions (
    video_id TEXT NOT NULL,
    surface TEXT NOT NULL,
    ts INTEGER NOT NULL,
    PRIMARY KEY (video_id, surface, ts)
);
CREATE TABLE IF NOT EXISTS api_cache (
    cache_key TEXT PRIMARY KEY,
    payload TEXT NOT NULL,
    expires_ts INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS system_mixes (
    mix_id TEXT PRIMARY KEY,
    title TEXT, reason TEXT,
    payload TEXT NOT NULL,
    generated_ts INTEGER NOT NULL
);
"""


class Library:
    def __init__(self, db_path: str = ":memory:"):
        self._lock = threading.Lock()
        self._db = sqlite3.connect(db_path, check_same_thread=False)
        self._db.execute("PRAGMA foreign_keys = ON")
        with self._lock, self._db:
            self._db.executescript(SCHEMA)
            self._migrate_locked()

    def close(self) -> None:
        with self._lock:
            self._db.close()

    def _migrate_locked(self) -> None:
        """Bring older library.db files up to the current schema."""
        cols = {
            r[1]
            for r in self._db.execute("PRAGMA table_info(playlists)").fetchall()
        }
        if "folder_id" not in cols:
            self._db.execute(
                "ALTER TABLE playlists ADD COLUMN folder_id INTEGER "
                "REFERENCES playlist_folders(id) ON DELETE SET NULL"
            )
        if "position" not in cols:
            self._db.execute(
                "ALTER TABLE playlists ADD COLUMN position INTEGER NOT NULL DEFAULT 0"
            )
        # Ensure folder table exists even if SCHEMA was already applied from an
        # older package that lacked it (CREATE IF NOT EXISTS in SCHEMA covers
        # fresh DBs; this is a safety net for partial upgrades).
        self._db.execute(
            "CREATE TABLE IF NOT EXISTS playlist_folders ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT,"
            "name TEXT NOT NULL,"
            "position INTEGER NOT NULL DEFAULT 0,"
            "created_at REAL NOT NULL,"
            "icon TEXT NOT NULL DEFAULT 'folder-music-symbolic',"
            "color TEXT NOT NULL DEFAULT '#3b82f6',"
            "emoji TEXT NOT NULL DEFAULT '🎵')"
        )
        fcols = {
            r[1]
            for r in self._db.execute(
                "PRAGMA table_info(playlist_folders)").fetchall()
        }
        if fcols and "icon" not in fcols:
            self._db.execute(
                "ALTER TABLE playlist_folders ADD COLUMN icon TEXT "
                "NOT NULL DEFAULT 'folder-music-symbolic'"
            )
        if fcols and "color" not in fcols:
            self._db.execute(
                "ALTER TABLE playlist_folders ADD COLUMN color TEXT "
                "NOT NULL DEFAULT '#3b82f6'"
            )
        if fcols and "emoji" not in fcols:
            self._db.execute(
                "ALTER TABLE playlist_folders ADD COLUMN emoji TEXT "
                "NOT NULL DEFAULT '🎵'"
            )

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
            self.log_event(track, "unfavorite")
            return False
        self.add_favorite(track)
        self.log_event(track, "favorite")
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

    def most_played(
        self,
        limit: int = 25,
        since: float | None = None,
        until: float | None = None,
    ) -> list[tuple[Track, int]]:
        where, params = self._history_filter(since, until)
        with self._lock:
            rows = self._db.execute(
                f"SELECT track_json, COUNT(*) as plays FROM history{where} "
                f"GROUP BY video_id ORDER BY plays DESC, MAX(id) DESC LIMIT ?",
                (*params, limit),
            ).fetchall()
        return [(Track.from_dict(json.loads(r[0])), r[1]) for r in rows]

    # -- playlist folders (Spotify-style) --------------------------------------

    DEFAULT_FOLDER_COLOR = "#38bdf8"
    DEFAULT_FOLDER_EMOJI = "🎵"

    @staticmethod
    def _norm_color(color: str | None) -> str:
        import re
        c = (color or Library.DEFAULT_FOLDER_COLOR).strip()
        if not c.startswith("#"):
            c = "#" + c
        if not re.match(r"^#[0-9A-Fa-f]{6}$", c):
            return Library.DEFAULT_FOLDER_COLOR
        return c.lower()

    @staticmethod
    def _norm_emoji(emoji: str | None) -> str:
        e = (emoji or "").strip()
        return e[:8] if e else Library.DEFAULT_FOLDER_EMOJI

    def create_folder(self, name: str, color: str | None = None,
                      emoji: str | None = None, **_legacy) -> int:
        color = self._norm_color(color or self.DEFAULT_FOLDER_COLOR)
        emoji = self._norm_emoji(emoji or self.DEFAULT_FOLDER_EMOJI)
        with self._lock, self._db:
            row = self._db.execute(
                "SELECT COALESCE(MAX(position), -1) FROM playlist_folders"
            ).fetchone()
            cur = self._db.execute(
                "INSERT INTO playlist_folders "
                "(name, position, created_at, icon, color, emoji) "
                "VALUES (?,?,?,?,?,?)",
                (name, row[0] + 1, time.time(), "folder-music-symbolic",
                 color, emoji),
            )
            return cur.lastrowid

    def rename_folder(self, folder_id: int, name: str) -> None:
        with self._lock, self._db:
            self._db.execute(
                "UPDATE playlist_folders SET name = ? WHERE id = ?",
                (name, folder_id),
            )

    def set_folder_style(self, folder_id: int, *, color: str | None = None,
                         emoji: str | None = None) -> None:
        with self._lock, self._db:
            if color is not None:
                self._db.execute(
                    "UPDATE playlist_folders SET color = ? WHERE id = ?",
                    (self._norm_color(color), folder_id),
                )
            if emoji is not None:
                self._db.execute(
                    "UPDATE playlist_folders SET emoji = ? WHERE id = ?",
                    (self._norm_emoji(emoji), folder_id),
                )

    # Back-compat alias used by older UI call sites.
    def set_folder_icon(self, folder_id: int, icon: str) -> None:
        # Old symbolic names are ignored; treat non-hex as emoji if short.
        if icon and icon.startswith("#"):
            self.set_folder_style(folder_id, color=icon)
        elif icon and not icon.endswith("-symbolic"):
            self.set_folder_style(folder_id, emoji=icon)

    def delete_folder(self, folder_id: int) -> None:
        """Remove the folder; playlists inside move back to the root."""
        with self._lock, self._db:
            self._db.execute(
                "UPDATE playlists SET folder_id = NULL WHERE folder_id = ?",
                (folder_id,),
            )
            self._db.execute(
                "DELETE FROM playlist_folders WHERE id = ?", (folder_id,)
            )

    def folders(self) -> list[tuple[int, str, str, str]]:
        """[(id, name, color, emoji)] ordered for the sidebar."""
        with self._lock:
            rows = self._db.execute(
                "SELECT id, name, "
                "COALESCE(color, '#3b82f6'), COALESCE(emoji, '🎵') "
                "FROM playlist_folders ORDER BY position, created_at"
            ).fetchall()
        return [(r[0], r[1], r[2], r[3]) for r in rows]

    def set_playlist_folder(
        self, playlist_id: int, folder_id: int | None
    ) -> None:
        with self._lock, self._db:
            # Place at end of the destination folder (or root).
            if folder_id is None:
                row = self._db.execute(
                    "SELECT COALESCE(MAX(position), -1) FROM playlists "
                    "WHERE folder_id IS NULL"
                ).fetchone()
            else:
                row = self._db.execute(
                    "SELECT COALESCE(MAX(position), -1) FROM playlists "
                    "WHERE folder_id = ?",
                    (folder_id,),
                ).fetchone()
            self._db.execute(
                "UPDATE playlists SET folder_id = ?, position = ? WHERE id = ?",
                (folder_id, row[0] + 1, playlist_id),
            )

    def playlist_folder_id(self, playlist_id: int) -> int | None:
        with self._lock:
            row = self._db.execute(
                "SELECT folder_id FROM playlists WHERE id = ?", (playlist_id,)
            ).fetchone()
        return row[0] if row else None

    # -- playlists -----------------------------------------------------------

    def create_playlist(self, name: str, folder_id: int | None = None) -> int:
        with self._lock, self._db:
            if folder_id is None:
                row = self._db.execute(
                    "SELECT COALESCE(MAX(position), -1) FROM playlists "
                    "WHERE folder_id IS NULL"
                ).fetchone()
            else:
                row = self._db.execute(
                    "SELECT COALESCE(MAX(position), -1) FROM playlists "
                    "WHERE folder_id = ?",
                    (folder_id,),
                ).fetchone()
            cur = self._db.execute(
                "INSERT INTO playlists (name, created_at, folder_id, position) "
                "VALUES (?,?,?,?)",
                (name, time.time(), folder_id, row[0] + 1),
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

    def playlists(self, folder_id: int | None | object = ...) -> list[tuple[int, str, int]]:
        """[(id, name, track_count)].

        * No argument — every playlist (for “add to playlist” pickers).
        * ``folder_id=None`` — only root (not in a folder).
        * ``folder_id=<id>`` — only that folder.
        """
        with self._lock:
            if folder_id is ...:
                rows = self._db.execute(
                    "SELECT p.id, p.name, COUNT(i.video_id) FROM playlists p "
                    "LEFT JOIN playlist_items i ON i.playlist_id = p.id "
                    "GROUP BY p.id ORDER BY p.folder_id IS NOT NULL, "
                    "p.position, p.created_at"
                ).fetchall()
            elif folder_id is None:
                rows = self._db.execute(
                    "SELECT p.id, p.name, COUNT(i.video_id) FROM playlists p "
                    "LEFT JOIN playlist_items i ON i.playlist_id = p.id "
                    "WHERE p.folder_id IS NULL "
                    "GROUP BY p.id ORDER BY p.position, p.created_at"
                ).fetchall()
            else:
                rows = self._db.execute(
                    "SELECT p.id, p.name, COUNT(i.video_id) FROM playlists p "
                    "LEFT JOIN playlist_items i ON i.playlist_id = p.id "
                    "WHERE p.folder_id = ? "
                    "GROUP BY p.id ORDER BY p.position, p.created_at",
                    (folder_id,),
                ).fetchall()
        return [(r[0], r[1], r[2]) for r in rows]

    def playlist_tree(self) -> list[dict]:
        """Sidebar-friendly structure: folders (with children) then root lists.

        Each item is either::
            {"kind": "folder", "id": int, "name": str,
             "playlists": [(id, name, count), ...]}
        or::
            {"kind": "playlist", "id": int, "name": str, "count": int}
        """
        folders = self.folders()
        tree: list[dict] = []
        for fid, fname, fcolor, femoji in folders:
            tree.append({
                "kind": "folder",
                "id": fid,
                "name": fname,
                "color": fcolor,
                "emoji": femoji,
                "playlists": self.playlists(folder_id=fid),
            })
        for pid, name, count in self.playlists(folder_id=None):
            tree.append({
                "kind": "playlist",
                "id": pid,
                "name": name,
                "count": count,
            })
        return tree

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
        self.log_event(track, "playlist_add")

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
        self.log_event(track, "never_play")

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

# -- taste model (spec: local discovery engine) ----------------------------

    def log_event(self, track: Track, event: str, *, source: str = "",
                  listened_fraction: float | None = None,
                  ts: float | None = None) -> None:
        """Append one taste event. Never raises — the model is best-effort
        and must not disturb playback."""
        from . import taste

        try:
            key = taste.artist_key((track.artists or [""])[0])
            with self._lock, self._db:
                self._db.execute(
                    "INSERT INTO listen_events (video_id, artist_key, ts, "
                    "source, listened_fraction, event) VALUES (?,?,?,?,?,?)",
                    (track.video_id, key, int(ts or time.time()),
                     source or "unknown", listened_fraction, event))
                # affinity cache is now stale for this artist
                self._db.execute(
                    "DELETE FROM artist_affinity WHERE artist_key = ?",
                    (key,))
        except Exception:  # noqa: BLE001
            log.exception("taste event logging failed")

    def events_for_artist(self, artist_key: str, limit: int = 2000):
        with self._lock:
            rows = self._db.execute(
                "SELECT event, listened_fraction, source, ts FROM "
                "listen_events WHERE artist_key = ? ORDER BY ts DESC LIMIT ?",
                (artist_key, limit)).fetchall()
        return rows

    def artist_affinity(self, artist_key: str,
                        now: float | None = None) -> float:
        """Decayed affinity, cached for an hour per artist."""
        from . import taste

        now = now or time.time()
        with self._lock:
            row = self._db.execute(
                "SELECT score, updated_ts FROM artist_affinity "
                "WHERE artist_key = ?", (artist_key,)).fetchone()
        if row and now - row[1] < 3600:
            return row[0]
        score = taste.score_events(self.events_for_artist(artist_key), now)
        with self._lock, self._db:
            self._db.execute(
                "INSERT OR REPLACE INTO artist_affinity VALUES (?,?,?)",
                (artist_key, score, int(now)))
        return score

    def artist_skip_rate(self, artist_key: str) -> float:
        from . import taste

        return taste.skip_rate(self.events_for_artist(artist_key, 200))

    def top_artist_keys(self, limit: int = 40) -> list[str]:
        """Artists by (undecayed) event volume — cheap shortlist; callers
        re-rank the shortlist by artist_affinity()."""
        with self._lock:
            rows = self._db.execute(
                "SELECT artist_key, COUNT(*) c FROM listen_events "
                "WHERE artist_key != '' GROUP BY artist_key "
                "ORDER BY c DESC LIMIT ?", (limit,)).fetchall()
        return [r[0] for r in rows]

    def log_impressions(self, video_ids, surface: str,
                        ts: float | None = None) -> None:
        ts = int(ts or time.time())
        try:
            with self._lock, self._db:
                self._db.executemany(
                    "INSERT OR IGNORE INTO impressions VALUES (?,?,?)",
                    [(v, surface, ts) for v in video_ids if v])
        except Exception:  # noqa: BLE001
            log.exception("impression logging failed")

    def recent_impressions(self, days: float = 14,
                           surface: str | None = None) -> set[str]:
        cutoff = time.time() - days * 86400
        with self._lock:
            if surface:
                rows = self._db.execute(
                    "SELECT DISTINCT video_id FROM impressions "
                    "WHERE ts > ? AND surface = ?", (cutoff, surface))
            else:
                rows = self._db.execute(
                    "SELECT DISTINCT video_id FROM impressions WHERE ts > ?",
                    (cutoff,))
            return {r[0] for r in rows.fetchall()}

    def recently_played_ids(self, days: float = 7) -> set[str]:
        cutoff = time.time() - days * 86400
        with self._lock:
            rows = self._db.execute(
                "SELECT DISTINCT video_id FROM listen_events "
                "WHERE ts > ? AND event IN ('play','skip')",
                (cutoff,)).fetchall()
        played = {r[0] for r in rows}
        # history table covers plays from before the event log existed
        with self._lock:
            rows = self._db.execute(
                "SELECT DISTINCT video_id FROM history WHERE played_at > ?",
                (cutoff,)).fetchall()
        return played | {r[0] for r in rows}

    def add_cooccurrence(self, a: str, b: str, weight: float = 1.0) -> None:
        if not a or not b or a == b:
            return
        if b < a:
            a, b = b, a
        try:
            with self._lock, self._db:
                self._db.execute(
                    "INSERT INTO track_cooccurrence VALUES (?,?,?,?) "
                    "ON CONFLICT(a, b) DO UPDATE SET "
                    "weight = weight + excluded.weight, "
                    "updated_ts = excluded.updated_ts",
                    (a, b, weight, int(time.time())))
        except Exception:  # noqa: BLE001
            log.exception("cooccurrence update failed")

    def cooccurring(self, video_id: str, limit: int = 25) -> list[tuple[str, float]]:
        with self._lock:
            rows = self._db.execute(
                "SELECT CASE WHEN a = ? THEN b ELSE a END, weight "
                "FROM track_cooccurrence WHERE a = ? OR b = ? "
                "ORDER BY weight DESC LIMIT ?",
                (video_id, video_id, video_id, limit)).fetchall()
        return [(r[0], r[1]) for r in rows]

    def track_by_id(self, video_id: str) -> Track | None:
        """Best-effort Track lookup from anything we've stored locally."""
        for query in (
            "SELECT track_json FROM history WHERE video_id = ? "
            "ORDER BY played_at DESC LIMIT 1",
            "SELECT track_json FROM favorites WHERE video_id = ? LIMIT 1",
            "SELECT track_json FROM playlist_items WHERE video_id = ? LIMIT 1",
        ):
            with self._lock:
                row = self._db.execute(query, (video_id,)).fetchone()
            if row:
                try:
                    return Track.from_dict(json.loads(row[0]))
                except (ValueError, KeyError):
                    continue
        return None

    def cache_get(self, key: str):
        with self._lock:
            row = self._db.execute(
                "SELECT payload, expires_ts FROM api_cache "
                "WHERE cache_key = ?", (key,)).fetchone()
        if not row or row[1] < time.time():
            return None
        try:
            return json.loads(row[0])
        except ValueError:
            return None

    def cache_put(self, key: str, payload, ttl_seconds: float) -> None:
        try:
            with self._lock, self._db:
                self._db.execute(
                    "INSERT OR REPLACE INTO api_cache VALUES (?,?,?)",
                    (key, json.dumps(payload),
                     int(time.time() + ttl_seconds)))
        except Exception:  # noqa: BLE001
            log.exception("api cache write failed")

    @staticmethod
    def _history_filter(
        since: float | None = None, until: float | None = None
    ) -> tuple[str, list]:
        """SQL WHERE clause + params for history time windows."""
        clauses: list[str] = []
        params: list = []
        if since is not None:
            clauses.append("played_at >= ?")
            params.append(since)
        if until is not None:
            clauses.append("played_at < ?")
            params.append(until)
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        return where, params

    def stats_overview(
        self, since: float | None = None, until: float | None = None
    ) -> dict:
        where, params = self._history_filter(since, until)
        with self._lock:
            total, distinct, first = self._db.execute(
                f"SELECT COUNT(*), COUNT(DISTINCT video_id), MIN(played_at) "
                f"FROM history{where}",
                params,
            ).fetchone()
            seconds = self._db.execute(
                f"SELECT COALESCE(SUM(json_extract(track_json, '$.duration')), 0) "
                f"FROM history{where}",
                params,
            ).fetchone()[0]
            rows = self._db.execute(
                f"SELECT track_json FROM history{where}", params
            ).fetchall()
        artists: set[str] = set()
        for (track_json,) in rows:
            for artist in json.loads(track_json).get("artists") or []:
                if artist:
                    artists.add(artist)
        return {
            "plays": total or 0,
            "songs": distinct or 0,
            "artists": len(artists),
            "seconds": int(seconds or 0),
            "since": first,
        }

    def top_artists(
        self,
        limit: int = 10,
        since: float | None = None,
        until: float | None = None,
    ) -> list[tuple[str, int]]:
        where, params = self._history_filter(since, until)
        with self._lock:
            rows = self._db.execute(
                f"SELECT track_json FROM history{where}", params
            ).fetchall()
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
        try:
            from . import taste
            with self._lock, self._db:
                self._db.execute(
                    "INSERT INTO listen_events (video_id, artist_key, ts, "
                    "source, listened_fraction, event) VALUES (?,?,?,?,?,?)",
                    ("", taste.artist_key(name), int(time.time()),
                     "user_click", None, "follow"))
                self._db.execute(
                    "DELETE FROM artist_affinity WHERE artist_key = ?",
                    (taste.artist_key(name),))
        except Exception:  # noqa: BLE001
            log.exception("follow event logging failed")

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
        self.log_event(track, "download")

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
