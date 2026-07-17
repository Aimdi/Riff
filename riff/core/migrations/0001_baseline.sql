-- Baseline schema for Riff library (user_version = 1).
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
