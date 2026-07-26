"""Podcast RSS parse + subscribe + direct-stream playback (no network)."""

from riff.core.library import Library
from riff.core.models import Track
from riff.core.podcast import PodcastEpisode, parse_episodes, search_shows
import riff.core.service as service_mod
from riff.core.service import PlaybackService
from tests.test_service import FakeApi, FakeEngine, FakeResolver, sync_run_async

SAMPLE_RSS = b"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"
 xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd">
  <channel>
    <title>Demo Show</title>
    <itunes:image href="https://example.com/show.jpg"/>
    <item>
      <title>Episode One</title>
      <guid>ep-1</guid>
      <description>&lt;p&gt;Hello &lt;b&gt;world&lt;/b&gt;&lt;/p&gt;</description>
      <pubDate>Mon, 19 Jul 2026 10:00:00 GMT</pubDate>
      <itunes:duration>1:02:03</itunes:duration>
      <enclosure url="https://cdn.example.com/ep1.mp3" length="12345" type="audio/mpeg"/>
    </item>
    <item>
      <title>No audio</title>
      <guid>ep-missing</guid>
    </item>
    <item>
      <title>Episode Two</title>
      <guid>ep-2</guid>
      <itunes:duration>90</itunes:duration>
      <enclosure url="https://cdn.example.com/ep2.mp3" length="9" type="audio/mpeg"/>
    </item>
  </channel>
</rss>
"""


def test_parse_episodes_enclosures_and_duration():
    eps = parse_episodes(SAMPLE_RSS, show_title="Demo Show")
    assert len(eps) == 2
    assert eps[0].title == "Episode One"
    assert eps[0].stream_url.endswith("ep1.mp3")
    assert eps[0].duration_sec == 3723
    assert "Hello world" in eps[0].description
    assert eps[0].pub_date == "19 Jul 2026"
    assert eps[1].duration_sec == 90
    track = eps[0].to_track()
    assert track.video_id.startswith("podcast_")
    assert track.stream_url.startswith("https://")
    assert track.artists == ["Demo Show"]


def test_podcast_subscribe_roundtrip():
    lib = Library(":memory:")
    try:
        assert lib.podcast_subscriptions() == []
        lib.subscribe_podcast(
            "https://feeds.example.com/a.xml", "A", "Host", "https://art")
        assert lib.is_podcast_subscribed("https://feeds.example.com/a.xml")
        rows = lib.podcast_subscriptions()
        assert rows[0]["title"] == "A"
        lib.unsubscribe_podcast("https://feeds.example.com/a.xml")
        assert not lib.is_podcast_subscribed("https://feeds.example.com/a.xml")
    finally:
        lib.close()


def test_playback_uses_stream_url_not_resolver(monkeypatch):
    monkeypatch.setattr(service_mod, "run_async", sync_run_async)
    monkeypatch.setattr(service_mod.config.settings, "set", lambda *a: None)
    engine = FakeEngine()
    resolver = FakeResolver()
    svc = PlaybackService(FakeApi(), Library(":memory:"), engine, resolver)
    ep = PodcastEpisode(
        guid="g1",
        title="Ep",
        stream_url="https://cdn.example.com/x.mp3",
        show_title="Show",
        duration_sec=120,
    )
    svc.play_tracks([ep.to_track()], source="podcast")
    assert engine.played == ["https://cdn.example.com/x.mp3"]
    assert resolver.resolved == []


def test_track_stream_url_roundtrip():
    t = Track(video_id="podcast_abc", title="E", stream_url="https://x/a.mp3")
    t2 = Track.from_dict(t.to_dict())
    assert t2.stream_url == "https://x/a.mp3"


def test_search_shows_requires_term():
    assert search_shows("   ") == []
