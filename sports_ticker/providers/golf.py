"""Injected golf provider adapter."""

from __future__ import annotations

from typing import Any

from sports_ticker.domain import DisplaySettings

from .features import GolfSource, _FeatureProvider, _content_payload
from .contracts import ProviderResult


class GolfProvider(_FeatureProvider):
    """Adapt one injected golf source into canonical golf content."""

    family = "golf"
    provider_name = "golf"

    def __init__(self, source: GolfSource) -> None:
        super().__init__(source)

    def fetch(self, settings: DisplaySettings) -> ProviderResult:
        """Fetch and normalize golf records."""

        return self._fetch_normalized(
            settings,
            lambda payload: _content_payload(payload, self.family, _golf_kind),
        )


def _golf_kind(record: dict[str, Any], group: str | None) -> str:
    source_kind = str(record.get("kind") or record.get("type") or "").strip().lower()
    group_kind = str(group or "").strip().lower()
    return source_kind or (group_kind if group_kind in {"golf", "masters"} else "golf")


__all__ = ["GolfProvider", "GolfSource"]
