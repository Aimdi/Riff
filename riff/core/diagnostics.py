"""Runtime diagnostics for Settings → About / Test connection."""

from __future__ import annotations

import importlib.metadata
import logging
import platform
import sys
from dataclasses import dataclass, field

log = logging.getLogger("riff.diagnostics")


def _pkg_version(name: str) -> str:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return "not installed"


@dataclass
class LayerResult:
    name: str
    ok: bool
    detail: str


@dataclass
class DiagnosticsReport:
    riff_version: str
    python: str
    platform: str
    ytmusicapi: str
    yt_dlp: str
    secrets_backend: str
    layers: list[LayerResult] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return all(layer.ok for layer in self.layers)

    def summary(self) -> str:
        lines = [
            f"Riff {self.riff_version}",
            f"Python {self.python} on {self.platform}",
            f"ytmusicapi {self.ytmusicapi}",
            f"yt-dlp {self.yt_dlp}",
            f"secrets: {self.secrets_backend}",
            "",
        ]
        for layer in self.layers:
            mark = "ok" if layer.ok else "FAIL"
            lines.append(f"[{mark}] {layer.name}: {layer.detail}")
        return "\n".join(lines)


def versions_banner() -> str:
    from .. import __version__

    return (
        f"Riff {__version__} | ytmusicapi {_pkg_version('ytmusicapi')} | "
        f"yt-dlp {_pkg_version('yt-dlp')} | Python {sys.version.split()[0]}"
    )


def run_connection_test(api=None) -> DiagnosticsReport:
    from .. import __version__
    from . import secrets as secrets_mod

    report = DiagnosticsReport(
        riff_version=__version__,
        python=sys.version.split()[0],
        platform=platform.platform(),
        ytmusicapi=_pkg_version("ytmusicapi"),
        yt_dlp=_pkg_version("yt-dlp"),
        secrets_backend=secrets_mod.backend_name(),
    )

    try:
        import yt_dlp  # noqa: F401
        from ytmusicapi import YTMusic  # noqa: F401

        report.layers.append(LayerResult("imports", True, "ytmusicapi + yt-dlp importable"))
    except Exception as exc:
        report.layers.append(LayerResult("imports", False, str(exc)))
        return report

    try:
        if api is None:
            from .api import MusicApi

            api = MusicApi()
        results = api.search("test", kind="songs")
        n = len(results.get("songs") or [])
        report.layers.append(LayerResult("ytmusicapi", True, f"search returned {n} songs"))
    except Exception as exc:
        report.layers.append(LayerResult("ytmusicapi", False, str(exc)))
        return report

    try:
        songs = results.get("songs") or []
        if songs and songs[0].video_id:
            from .stream import StreamResolver

            url = StreamResolver(quality="low").resolve(songs[0].video_id)
            report.layers.append(
                LayerResult(
                    "yt-dlp",
                    True,
                    f"resolved stream ({'https' if url.startswith('http') else 'uri'})",
                )
            )
        else:
            report.layers.append(
                LayerResult("yt-dlp", True, "skipped (no search hit to resolve)")
            )
    except Exception as exc:
        report.layers.append(LayerResult("yt-dlp", False, str(exc)))

    return report
