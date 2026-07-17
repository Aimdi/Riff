"""Typed exceptions for the streaming / API boundary."""

from __future__ import annotations


class RiffError(Exception):
    """Base class for recoverable Riff failures."""


class RiffApiError(RiffError):
    """YouTube Music / ytmusicapi request failed."""


class RiffRateLimitError(RiffApiError):
    """Upstream rate-limited the client."""


class RiffUnavailableError(RiffApiError):
    """Service unreachable or API out of date after retries."""


class RiffStreamError(RiffError):
    """Stream URL resolution or playback source failure."""


class RiffCircuitOpen(RiffApiError):
    """Circuit breaker open — stop hammering the API (not auto-retried)."""
