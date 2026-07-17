"""Path safety helpers for downloads and cache files."""

from __future__ import annotations

import os
import re

# Allow alphanumerics, common punctuation; strip everything else for filenames.
_SAFE_RE = re.compile(r"[^A-Za-z0-9 ._'\-()\[\]]+")
_MULTI_SPACE = re.compile(r"\s+")


def safe_filename(name: str, *, max_len: int = 120) -> str:
    """Strict filename stem for track titles / artists.

    Rejects path separators and control characters; collapses whitespace.
    """
    name = (name or "").replace("\x00", "")
    name = name.replace("/", "_").replace("\\", "_")
    name = _SAFE_RE.sub("_", name)
    name = _MULTI_SPACE.sub(" ", name).strip(" .")
    if not name:
        return "track"
    return name[:max_len]


def constrain_path(base_dir: str, *parts: str) -> str:
    """Join *parts* under *base_dir* and reject path traversal.

    Raises ``ValueError`` if the resolved path escapes *base_dir*.
    """
    base = os.path.realpath(base_dir)
    candidate = os.path.realpath(os.path.join(base, *parts))
    if candidate != base and not candidate.startswith(base + os.sep):
        raise ValueError(f"path escapes download directory: {candidate}")
    return candidate
