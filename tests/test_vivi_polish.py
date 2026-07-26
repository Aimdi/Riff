"""Vivi-inspired polish: palette, audio fx, lyrics scoring."""

from riff.core import audio_fx
from riff.core import lyrics as lyrics_mod
from riff.ui import palette


def test_accent_pair_readable():
    bg, fg, accent = palette.accent_pair(30, 140, 80)
    assert bg.startswith("#") and len(bg) == 7
    assert fg in ("#000000", "#ffffff")
    assert accent.startswith("#")


def test_audio_fx_compose():
    assert audio_fx.build_af(eq_preset="flat", normalize=False) == ""
    assert "loudnorm" in audio_fx.build_af(eq_preset="flat", normalize=True)
    assert "equalizer" in audio_fx.build_af(eq_preset="bass", normalize=False)
    # Night embeds loudnorm — don't double it.
    night = audio_fx.build_af(eq_preset="night", normalize=True)
    assert night.count("loudnorm") == 1


def test_lyrics_result_keeps_ttml(monkeypatch):
    ttml = '<p begin="1.0"><span begin="1.0">Hi</span></p>'

    def better(*_a, **_k):
        return lyrics_mod.LyricsResult(
            synced=[(1.0, "Hi")], plain="Hi", source="better", ttml=ttml)

    monkeypatch.setattr(lyrics_mod, "fetch_better_lyrics", better)
    monkeypatch.setattr(lyrics_mod, "fetch_lrclib", lambda *_a, **_k: None)
    monkeypatch.setattr(lyrics_mod, "fetch_kugou", lambda *_a, **_k: None)
    from riff.core.models import Track
    hit = lyrics_mod.fetch_lyrics_result(
        Track(video_id="x", title="T", artists=["A"]), source="auto")
    assert hit is not None
    assert hit.ttml == ttml
    assert any(l.has_words for l in lyrics_mod.parse_ttml(hit.ttml))
