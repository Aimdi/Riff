"""AI Mix — optional Claude-powered music suggestions.

Uses the user's own Anthropic API key (Settings → AI Mix). The model sees
only listening history/favorites (titles and artists) and returns song
suggestions; nothing else is sent anywhere.
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request

from .models import Track

log = logging.getLogger("riff.ai")

MODEL = "claude-opus-4-8"
OPENAI_DEFAULT_BASE_URL = "https://api.openai.com/v1"

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


def extract_json(text: str) -> str:
    """Trim markdown fences / prose around a JSON object.

    OpenAI-compatible servers (especially local models) don't always honor
    JSON response formats and may wrap the object in ```json fences.
    """
    text = text.strip()
    if text.startswith("```"):
        first_newline = text.find("\n")
        if first_newline != -1:
            text = text[first_newline + 1:]
        if text.rstrip().endswith("```"):
            text = text.rstrip()[:-3]
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        return text[start:end + 1]
    return text


def parse_suggestions(text: str) -> list[tuple[str, str]]:
    data = json.loads(extract_json(text))
    out = []
    for s in data.get("songs", []):
        title = (s.get("title") or "").strip()
        artist = (s.get("artist") or "").strip()
        if title:
            out.append((title, artist))
    return out


def suggest_songs_openai(base_url: str, api_key: str, model: str,
                         recent: list[Track], favorites: list[Track],
                         count: int = 20) -> list[tuple[str, str]]:
    """Blocking: [(title, artist), …] from any OpenAI-compatible endpoint
    (OpenAI, OpenRouter, Groq, Ollama, LM Studio, …). Raises RuntimeError
    with a user-presentable message on failure."""
    if not model:
        raise RuntimeError(
            "Set a model name in Settings (e.g. gpt-4o-mini, or llama3 for Ollama)")
    url = (base_url or OPENAI_DEFAULT_BASE_URL).rstrip("/") + "/chat/completions"
    system = (
        _SYSTEM
        + ' Respond ONLY with a JSON object of the form '
          '{"songs": [{"title": "...", "artist": "..."}]} — no other text.'
    )
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": build_prompt(recent, favorites, count)},
        ],
        "response_format": {"type": "json_object"},
    }
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    def post(payload: dict) -> dict:
        req = urllib.request.Request(
            url, data=json.dumps(payload).encode(), headers=headers)
        with urllib.request.urlopen(req, timeout=120) as resp:
            return json.load(resp)

    try:
        try:
            data = post(body)
        except urllib.error.HTTPError as exc:
            # Some compatible servers reject response_format — retry without.
            if exc.code == 400 and "response_format" in body:
                body.pop("response_format")
                data = post(body)
            else:
                raise
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403):
            raise RuntimeError("Invalid API key for this endpoint — check Settings") from exc
        if exc.code == 404:
            raise RuntimeError(
                "Endpoint or model not found — check the base URL and model "
                "name in Settings") from exc
        if exc.code == 429:
            raise RuntimeError("Rate limit hit — try again shortly") from exc
        raise RuntimeError(f"AI endpoint error (HTTP {exc.code})") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(
            f"Couldn't reach {url.split('/chat')[0]} — is the server running?"
        ) from exc

    try:
        text = data["choices"][0]["message"]["content"] or ""
    except (KeyError, IndexError, TypeError) as exc:
        raise RuntimeError("Unexpected response from the AI endpoint") from exc
    try:
        return parse_suggestions(text)
    except (ValueError, KeyError) as exc:
        raise RuntimeError("Couldn't parse the model's suggestions") from exc


def suggest_songs(api_key: str, recent: list[Track], favorites: list[Track],
                  count: int = 20) -> list[tuple[str, str]]:
    """Blocking: returns [(title, artist), …]. Raises RuntimeError with a
    user-presentable message on failure."""
    try:
        import anthropic
    except ImportError as exc:
        import shutil

        if shutil.which("pacman"):
            hint = "sudo pacman -S python-anthropic (or: paru -S python-anthropic)"
        else:
            hint = "pip install --user anthropic"
        raise RuntimeError(
            f"The 'anthropic' Python package is not installed — run: {hint}"
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
