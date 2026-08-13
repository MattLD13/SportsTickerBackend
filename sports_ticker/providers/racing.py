"""Injected F1, IndyCar, and NASCAR provider adapter."""

from __future__ import annotations

from typing import Any

from sports_ticker.domain import DisplaySettings

from .contracts import ProviderResult
from .features import RacingSource, _FeatureProvider, _content_payload


class RacingProvider(_FeatureProvider):
    """Adapt one injected racing source into distinct racing kinds."""

    family = "racing"
    provider_name = "racing"

    def __init__(self, source: RacingSource) -> None:
        super().__init__(source)

    def fetch(self, settings: DisplaySettings) -> ProviderResult:
        """Fetch and normalize F1, IndyCar, or NASCAR records."""

        return self._fetch_normalized(
            settings,
            lambda payload: _content_payload(payload, self.family, _racing_kind),
        )


def _racing_kind(record: dict[str, Any], group: str | None) -> str:
    candidates = (
        group,
        record.get("kind"),
        record.get("type"),
        record.get("sport"),
        record.get("league"),
        record.get("series"),
    )
    for raw in candidates:
        value = str(raw or "").strip().lower().replace(" ", "").replace("-", "").replace("_", "")
        if value in {"f1", "formula1"} or "f1" in record:
            return "f1"
        if value in {"indycar", "indy"} or "indycar" in record:
            return "indycar"
        if value in {"nascar"} or "nascar" in record:
            return "nascar"
    raise ValueError("racing record must identify f1, indycar, or nascar")


__all__ = ["RacingProvider", "RacingSource"]
