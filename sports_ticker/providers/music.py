"""Injected music provider adapter."""

from __future__ import annotations

from typing import Any

from sports_ticker.domain import DisplaySettings

from .contracts import ProviderResult
from .features import MusicSource, _FeatureProvider, _content_payload


class MusicProvider(_FeatureProvider):
    """Adapt one injected music source into canonical music content."""

    family = "music"
    provider_name = "music"

    def __init__(self, source: MusicSource) -> None:
        super().__init__(source)

    def fetch(self, settings: DisplaySettings) -> ProviderResult:
        """Fetch and normalize music records."""

        return self._fetch_normalized(
            settings,
            lambda payload: _content_payload(payload, self.family, _music_kind),
        )

    def fetch_for_ticker(self, ticker_id: str, settings: DisplaySettings) -> ProviderResult:
        """Fetch music for one ticker when the source supports account ownership."""

        scoped_fetch = getattr(self._source, "fetch_for_ticker", None)
        if not callable(scoped_fetch):
            return self.fetch(settings)
        return self._fetch_normalized(
            settings,
            lambda payload: _content_payload(payload, self.family, _music_kind),
            lambda: scoped_fetch(str(ticker_id).strip(), settings),
        )


def _music_kind(record: dict[str, Any], group: str | None) -> str:
    source_kind = str(record.get("kind") or record.get("type") or "").strip().lower()
    return source_kind or "music"


__all__ = ["MusicProvider", "MusicSource"]
