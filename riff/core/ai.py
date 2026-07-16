"""AI Mix — optional Claude-powered music suggestions.

Uses the user's own Anthropic API key (Settings → AI Mix). The model sees
only listening history/favorites (titles and artists) and returns song
suggestions; nothing else is sent anywhere.
"""

from __future__ import annotations

import json
import logging

from .models import Track

log = logging.getLogger("riff.ai")

MODEL = "claude-opus-4-8"

_SCHEMA = {
    "type": "object",
    "properties": {
        "songs": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "artist": {"type": "string"},
                },
                "required": ["title", "artist"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["songs"],
    "additionalProperties": False,
}

_SYSTEM = (
    "You are a music curator. Given a listener's recent plays and favorites, "
    "suggest songs they are likely to love. Mix familiar-adjacent picks with "
    "a few discoveries; avoid suggesting songs already in their history. "
    "Only suggest real, existing songs."
)


def _format_tracks(tracks: list[Track], limit: int = 30) -> str:
    lines = []
    for t in tracks[:limit]:
        artist = t.artist or "Unknown"
        lines.append(f"- {t.title} — {artist}")
    return "\n".join(lines) or "(none)"


def build_prompt(recent: list[Track], favorites: list[Track],
                 count: int = 20) -> str:
    return (
        f"Recently played:\n{_format_tracks(recent)}\n\n"
        f"Favorites:\n{_format_tracks(favorites)}\n\n"
        f"Suggest {count} songs as JSON."
    )


def parse_suggestions(text: str) -> list[tuple[str, str]]:
    data = json.loads(text)
    out = []
    for s in data.get("songs", []):
        title = (s.get("title") or "").strip()
        artist = (s.get("artist") or "").strip()
        if title:
            out.append((title, artist))
    return out


def suggest_songs(api_key: str, recent: list[Track], favorites: list[Track],
                  count: int = 20) -> list[tuple[str, str]]:
    """Blocking: returns [(title, artist), …]. Raises RuntimeError with a
    user-presentable message on failure."""
    try:
        import anthropic
    except ImportError as exc:
        raise RuntimeError(
            "The 'anthropic' Python package is not installed — "
            "run: pip install --user anthropic"
        ) from exc

    client = anthropic.Anthropic(api_key=api_key)
    try:
        response = client.messages.create(
            model=MODEL,
            max_tokens=4096,
            thinking={"type": "adaptive"},
            system=_SYSTEM,
            messages=[{"role": "user",
                       "content": build_prompt(recent, favorites, count)}],
            output_config={"format": {"type": "json_schema",
                                      "schema": _SCHEMA}},
        )
    except anthropic.AuthenticationError as exc:
        raise RuntimeError("Invalid Anthropic API key — check Settings") from exc
    except anthropic.RateLimitError as exc:
        raise RuntimeError("Anthropic rate limit hit — try again shortly") from exc
    except anthropic.APIConnectionError as exc:
        raise RuntimeError("Couldn't reach the Anthropic API") from exc
    except anthropic.APIStatusError as exc:
        raise RuntimeError(f"Anthropic API error: {exc.message}") from exc

    if response.stop_reason == "refusal":
        raise RuntimeError("The model declined this request")
    text = next((b.text for b in response.content if b.type == "text"), "")
    if not text:
        raise RuntimeError("The model returned no suggestions")
    try:
        return parse_suggestions(text)
    except (ValueError, KeyError) as exc:
        raise RuntimeError("Couldn't parse the model's suggestions") from exc
