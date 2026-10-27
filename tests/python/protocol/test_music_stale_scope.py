"""Keep music stale results inside the ticker that produced them."""
import pytest

from sports_ticker.domain import DisplaySettings
from sports_ticker.providers.music import MusicProvider

pytestmark = pytest.mark.critical


def test_rate_limited_music_never_reuses_another_tickers_record():
    class Source:
        failed = False

        def fetch(self, settings):
            raise AssertionError("Music requests must carry ticker ownership")

        def fetch_for_ticker(self, ticker_id, settings):
            if self.failed or ticker_id == "other":
                raise RuntimeError("Spotify Web API rate limit cooldown is active")
            return {"content": [{"id": "track-a", "name": "Private Track", "is_playing": True}]}

    source = Source()
    provider = MusicProvider(source)
    settings = DisplaySettings(mode="music")
    first = provider.fetch_for_ticker("owner", settings)
    assert first.health.healthy and first.content[0].data["name"] == "Private Track"
    other = provider.fetch_for_ticker("other", settings)
    assert not other.health.healthy and other.content == ()
    source.failed = True
    own_stale = provider.fetch_for_ticker("owner", settings)
    assert not own_stale.health.healthy and own_stale.content == first.content
    assert own_stale.observed_at == first.observed_at
    assert own_stale.health.provider == first.health.provider
    assert own_stale.health.error == "stale: Spotify Web API rate limit cooldown is active"
    assert own_stale.health.diagnostic["exception_type"] == "RuntimeError"
