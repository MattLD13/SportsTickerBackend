"""Injected stock provider adapter."""

from __future__ import annotations

from typing import Any

from sports_ticker.domain import DisplaySettings

from .contracts import ProviderResult
from .features import StockSource, _FeatureProvider, _content_payload


class StockProvider(_FeatureProvider):
    """Adapt one injected stock source into canonical stock content."""

    family = "stock"
    provider_name = "stock"

    def __init__(self, source: StockSource) -> None:
        super().__init__(source)

    def fetch(self, settings: DisplaySettings) -> ProviderResult:
        """Fetch and normalize stock records."""

        return self._fetch_normalized(
            settings,
            lambda payload: _content_payload(payload, self.family, _stock_kind),
        )


def _stock_kind(record: dict[str, Any], group: str | None) -> str:
    return "stock"


__all__ = ["StockProvider", "StockSource"]
