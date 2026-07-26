"""Playback audio FX presets (Vivi EQ / loudnorm lite via mpv ``af``)."""

from __future__ import annotations

EQ_PRESETS: dict[str, str] = {
    # lavfi equalizer bands — gentle, desktop-friendly.
    "flat": "",
    "bass": (
        "lavfi=[equalizer=f=80:width_type=h:width=80:g=6,"
        "equalizer=f=200:width_type=h:width=100:g=3]"
    ),
    "vocal": (
        "lavfi=[equalizer=f=300:width_type=h:width=200:g=-2,"
        "equalizer=f=2500:width_type=h:width=1200:g=4,"
        "equalizer=f=5000:width_type=h:width=2000:g=2]"
    ),
    "night": (
        "lavfi=[equalizer=f=80:width_type=h:width=80:g=-3,"
        "equalizer=f=8000:width_type=h:width=4000:g=-4,"
        "loudnorm=I=-16:TP=-1.5:LRA=11]"
    ),
}

EQ_LABELS = {
    "flat": "Flat",
    "bass": "Bass boost",
    "vocal": "Vocal",
    "night": "Night",
}


# Meld-style skip silence — gentle thresholds so music isn't chewed up.
_SKIP_SILENCE = (
    "lavfi=[silenceremove=start_periods=1:start_silence=0.3:"
    "start_threshold=-50dB:detection=peak:stop_periods=-1:"
    "stop_duration=0.35:stop_threshold=-50dB]"
)


def build_af(
    *,
    eq_preset: str = "flat",
    normalize: bool = False,
    skip_silence: bool = False,
) -> str:
    """Compose an mpv af graph from EQ / loudnorm / skip-silence."""
    parts: list[str] = []
    eq = EQ_PRESETS.get((eq_preset or "flat").strip().lower(), "")
    if eq:
        parts.append(eq)
    if normalize and eq_preset != "night":
        # night already includes loudnorm.
        parts.append("lavfi=[loudnorm=I=-16:TP=-1.5:LRA=11]")
    if skip_silence:
        parts.append(_SKIP_SILENCE)
    if not parts:
        return ""
    if len(parts) == 1:
        return parts[0]
    # Multiple lavfi graphs: join with comma at af level.
    return ",".join(parts)
