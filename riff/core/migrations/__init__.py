"""SQLite schema migrations driven by PRAGMA user_version."""

from __future__ import annotations

import logging
import os
import re
import sqlite3

log = logging.getLogger("riff.migrations")

MIGRATIONS_DIR = os.path.dirname(__file__)

CURRENT_VERSION = 1


def _migration_files() -> list[tuple[int, str]]:
    files: list[tuple[int, str]] = []
    if not os.path.isdir(MIGRATIONS_DIR):
        return files
    for name in sorted(os.listdir(MIGRATIONS_DIR)):
        if not name.endswith(".sql"):
            continue
        prefix = name.split("_", 1)[0]
        if not prefix.isdigit():
            continue
        files.append((int(prefix), os.path.join(MIGRATIONS_DIR, name)))
    files.sort(key=lambda x: x[0])
    return files


def get_user_version(conn: sqlite3.Connection) -> int:
    row = conn.execute("PRAGMA user_version").fetchone()
    return int(row[0]) if row else 0


def _split_statements(sql: str) -> list[str]:
    lines: list[str] = []
    for line in sql.splitlines():
        stripped = line.strip()
        if stripped.startswith("--"):
            continue
        lines.append(line)
    body = "\n".join(lines)
    parts = re.split(r";\s*\n", body)
    out: list[str] = []
    for part in parts:
        stmt = part.strip().rstrip(";").strip()
        if stmt:
            out.append(stmt)
    return out


def migrate(conn: sqlite3.Connection) -> int:
    """Apply pending migrations. Returns the resulting user_version."""
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        conn.execute("PRAGMA journal_mode = WAL")
    except sqlite3.Error:
        pass

    version = get_user_version(conn)
    pending = [(v, path) for v, path in _migration_files() if v > version]
    if not pending:
        return version

    for target, path in pending:
        with open(path, encoding="utf-8") as f:
            sql = f.read()
        log.info(
            "applying migration %s (user_version %d → %d)",
            os.path.basename(path),
            version,
            target,
        )
        try:
            conn.execute("BEGIN")
            for stmt in _split_statements(sql):
                conn.execute(stmt)
            conn.execute(f"PRAGMA user_version = {int(target)}")
            conn.execute("COMMIT")
        except Exception:
            try:
                conn.execute("ROLLBACK")
            except sqlite3.Error:
                pass
            raise
        version = target

    return version
