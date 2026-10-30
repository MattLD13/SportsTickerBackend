"""Injected news provider adapter."""

from __future__ import annotations

from ticker.shared.domain import DisplaySettings

from ticker.server.providers.contracts import ProviderResult
from ticker.server.providers.features import NewsSource, _FeatureProvider, _news_payload


class NewsProvider(_FeatureProvider):
    """Adapt one injected news source into the provider news channel."""

    family = "news"
    provider_name = "news"

    def __init__(self, source: NewsSource) -> None:
        super().__init__(source)

    def fetch(self, settings: DisplaySettings) -> ProviderResult:
        """Fetch news events without emitting content records."""

        return self._fetch_normalized(settings, _news_payload)


__all__ = ["NewsProvider", "NewsSource"]
