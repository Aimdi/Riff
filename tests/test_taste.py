"""Pure taste-model math (spec §2.1)."""

from riff.core import taste


def test_artist_key_normalizes_credits():
    assert taste.artist_key("The Weeknd") == "the weeknd"
    assert taste.artist_key("Drake feat. Rihanna") == "drake"
    assert taste.artist_key("KORDHELL ft Scarlxrd") == "kordhell"
    assert taste.artist_key("A$AP Rocky!") == "aap rocky"
    assert taste.artist_key("") == ""


def test_decay_halves_at_half_life():
    day = taste.DAY
    assert taste.decay(10.0, 0) == 10.0
    assert abs(taste.decay(10.0, 90 * day) - 5.0) < 1e-9
    assert abs(taste.decay(10.0, 180 * day) - 2.5) < 1e-9


def test_play_weight_brackets():
    assert taste.play_weight(1.0, "radio") == 1.0
    assert taste.play_weight(0.5, "radio") == 0.3
    assert taste.play_weight(0.2, "radio") == -1.0
    assert taste.play_weight(0.05, "radio") == -2.0
    # user-chosen plays get the extra bump on positives only
    assert taste.play_weight(1.0, "user_click") == 1.5
    assert taste.play_weight(0.05, "user_click") == -2.0
    # unknown outcome is a mild positive
    assert taste.play_weight(None, "radio") == 0.5


def test_score_events_decays_and_sums():
    now = 1_000_000.0
    events = [
        ("favorite", None, "user_click", now),          # +3
        ("play", 1.0, "radio", now - 90 * taste.DAY),   # +1 decayed to 0.5
        ("play", 0.05, "radio", now),                   # -2
    ]
    score = taste.score_events(events, now)
    assert abs(score - (3.0 + 0.5 - 2.0)) < 1e-6


def test_skip_rate():
    events = [
        ("play", 1.0, "radio", 0),
        ("play", 0.1, "radio", 0),
        ("play", 0.05, "radio", 0),
        ("favorite", None, "user_click", 0),  # not a play — ignored
    ]
    assert abs(taste.skip_rate(events) - 2 / 3) < 1e-9


def test_normalized_title_key_kills_remasters():
    a = taste.normalized_title_key("Song Name (Remastered 2011)", "Artist")
    b = taste.normalized_title_key("Song Name", "artist")
    assert a == b
    c = taste.normalized_title_key("Song Name [Live]", "Artist")
    assert c == a
