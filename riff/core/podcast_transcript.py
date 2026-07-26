"""Podcasting 2.0 transcript parse (Riff Mobile PodcastService port).

Pure helpers — no ``gi``. Fetch via ``fetch_transcript`` (blocking HTTP).
"""

from __future__ import annotations

import json
import logging
import re
import urllib.request
from dataclasses import dataclass

log = logging.getLogger("riff.podcast_transcript")

_UA = "Riff/1.0 (transcript; +https://github.com/Aimdi/Riff)"


@dataclass
class TranscriptCue:
    start_sec: float  # -1 when untimed (plain text / HTML)
    text: str
    end_sec: float | None = None
    speaker: str | None = None


def transcript_type_score(type_: str, url: str) -> int:
    """Preference: JSON > SRT > VTT > plain > HTML."""
    t = (type_ or "").lower()
    u = (url or "").lower()
    if "json" in t or u.endswith(".json"):
        return 4
    if "srt" in t or "subrip" in t or u.endswith(".srt"):
        return 3
    if "vtt" in t or u.endswith(".vtt"):
        return 2
    if "plain" in t or u.endswith(".txt"):
        return 1
    if "html" in t or u.endswith(".html"):
        return 0
    return 1


def pick_best_transcript(
    candidates: list[tuple[str, str]],
) -> tuple[str, str]:
    """Pick (url, type) with the highest parseability score."""
    best_url, best_type, best_score = "", "", -1
    for url, type_ in candidates:
        if not url:
            continue
        score = transcript_type_score(type_, url)
        if score > best_score:
            best_score = score
            best_url, best_type = url, type_
    return best_url, best_type


def parse_transcript_document(raw: str, *, type_: str = "") -> list[TranscriptCue]:
    body = (raw or "").strip()
    if not body:
        return []
    t = (type_ or "").lower()
    if t.find("json") >= 0 or body.startswith("{") or body.startswith("["):
        cues = _parse_json_transcript(body)
    elif body.startswith("WEBVTT") or "vtt" in t:
        cues = _parse_timed_transcript(body, is_vtt=True)
    elif (
        "srt" in t
        or "subrip" in t
        or re.search(r"\d{2}:\d{2}:\d{2},\d{3}\s*-->", body)
    ):
        cues = _parse_timed_transcript(body, is_vtt=False)
    else:
        cues = _parse_plain_transcript(body, is_html="html" in t)
    if not cues and body:
        cues = _parse_plain_transcript(body, is_html=False)
    if cues and cues[0].start_sec >= 0:
        cues.sort(key=lambda c: c.start_sec)
        cues = _coalesce_cues(cues)
    return cues


def fetch_transcript(url: str, *, type_: str = "", timeout: float = 30) -> list[TranscriptCue]:
    url = (url or "").strip()
    if not url:
        return []
    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read().decode("utf-8", errors="replace")
    return parse_transcript_document(raw, type_=type_)


def active_cue_index(cues: list[TranscriptCue], pos_sec: float) -> int:
    """Last cue with start_sec <= pos, or -1. Untimed cues → -1."""
    active = -1
    for i, cue in enumerate(cues):
        if cue.start_sec < 0:
            return -1
        if cue.start_sec <= pos_sec:
            active = i
        else:
            break
    return active


def _parse_json_transcript(body: str) -> list[TranscriptCue]:
    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        return []
    segments = data.get("segments") if isinstance(data, dict) else data
    if not isinstance(segments, list):
        return []
    out: list[TranscriptCue] = []
    for seg in segments:
        if not isinstance(seg, dict):
            continue
        text = str(seg.get("body") or seg.get("text") or "").strip()
        if not text:
            continue
        st = seg.get("startTime")
        try:
            start = float(st) if st is not None else -1.0
        except (TypeError, ValueError):
            start = -1.0
        end = None
        et = seg.get("endTime")
        if et is not None:
            try:
                end = float(et)
            except (TypeError, ValueError):
                end = None
        speaker = seg.get("speaker")
        out.append(TranscriptCue(
            start_sec=start,
            end_sec=end,
            speaker=str(speaker) if speaker else None,
            text=text,
        ))
    return out


def _parse_timed_transcript(body: str, *, is_vtt: bool) -> list[TranscriptCue]:
    out: list[TranscriptCue] = []
    blocks = re.split(r"\n{2,}", body.replace("\r\n", "\n"))
    for block in blocks:
        lines = [ln for ln in block.split("\n") if ln.strip()]
        if not lines:
            continue
        first = lines[0]
        if is_vtt and (
            first.startswith("WEBVTT")
            or first.startswith("NOTE")
            or first.startswith("STYLE")
            or first.startswith("REGION")
        ):
            continue
        timing_idx = next(
            (i for i, ln in enumerate(lines) if "-->" in ln), -1)
        if timing_idx < 0 or timing_idx + 1 > len(lines):
            continue
        parts = lines[timing_idx].split("-->")
        if len(parts) < 2:
            continue
        start = _parse_timestamp(parts[0])
        end_token = parts[1].strip().split()[0] if parts[1].strip() else ""
        end = _parse_timestamp(end_token)
        if start is None:
            continue
        text = " ".join(lines[timing_idx + 1:]).strip()
        speaker = None
        v = re.match(r"^<v\s+([^>]+)>", text)
        if v:
            speaker = v.group(1).strip()
        text = re.sub(r"<[^>]*>", "", text).strip()
        sp = re.match(r"^([A-Za-z][\w .\-]{0,30}):\s+(.*)$", text)
        if speaker is None and sp and sp.group(2):
            speaker = sp.group(1)
            text = sp.group(2)
        if not text:
            continue
        out.append(TranscriptCue(
            start_sec=start, end_sec=end, speaker=speaker, text=text))
    return out


def _parse_timestamp(raw: str) -> float | None:
    m = re.search(
        r"(?:(\d+):)?(\d{1,2}):(\d{1,2})[.,](\d{1,3})", (raw or "").strip())
    if not m:
        return None
    h = int(m.group(1) or 0)
    minute = int(m.group(2))
    sec = int(m.group(3))
    ms = int(m.group(4).ljust(3, "0"))
    return h * 3600 + minute * 60 + sec + ms / 1000.0


def _parse_plain_transcript(body: str, *, is_html: bool) -> list[TranscriptCue]:
    text = body
    if is_html or "<p" in text or "<br" in text.lower():
        text = re.sub(r"<br\s*/?>", "\n", text, flags=re.I)
        text = re.sub(r"</p>", "\n\n", text, flags=re.I)
        # Strip tags but keep paragraph breaks.
        text = re.sub(r"(?is)<(script|style).*?>.*?</\1>", "", text)
        text = re.sub(r"(?s)<[^>]+>", "", text)
    out: list[TranscriptCue] = []
    for para in re.split(r"\n{2,}", text):
        cleaned = re.sub(r"\s+", " ", para).strip()
        if cleaned:
            out.append(TranscriptCue(start_sec=-1, text=cleaned))
    return out


def _coalesce_cues(raw: list[TranscriptCue]) -> list[TranscriptCue]:
    max_chars = 200
    max_gap_sec = 1.5
    sentence_end = re.compile(r"""[.!?…]["')\]]?$""")
    out: list[TranscriptCue] = []
    for cue in raw:
        last = out[-1] if out else None
        same_speaker = last is not None and (
            cue.speaker is None
            or last.speaker is None
            or cue.speaker == last.speaker
        )
        if last is None:
            gap = float("inf")
        else:
            gap = cue.start_sec - (
                last.end_sec if last.end_sec is not None else last.start_sec)
        if (
            last is not None
            and same_speaker
            and gap <= max_gap_sec
            and len(last.text) + len(cue.text) + 1 <= max_chars
            and not sentence_end.search(last.text)
        ):
            out[-1] = TranscriptCue(
                start_sec=last.start_sec,
                end_sec=cue.end_sec if cue.end_sec is not None else last.end_sec,
                speaker=last.speaker or cue.speaker,
                text=f"{last.text} {cue.text}",
            )
        else:
            out.append(cue)
    return out
