"""Injected golf provider adapter."""

from __future__ import annotations

import re
from collections.abc import Mapping
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
            lambda payload: _golf_payload(_content_payload(payload, self.family, _golf_kind)),
        )


def _golf_kind(record: dict[str, Any], group: str | None) -> str:
    source_kind = str(record.get("kind") or record.get("type") or "").strip().lower()
    group_kind = str(group or "").strip().lower()
    return source_kind or (group_kind if group_kind in {"golf", "masters"} else "golf")


def _golf_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Keep one short round label in every canonical golf record."""

    result = dict(payload)
    records: list[dict[str, Any]] = []
    for source in payload.get("content", ()):
        record = dict(source) if isinstance(source, Mapping) else {}
        golf = record.get("golf")
        details = dict(golf) if isinstance(golf, Mapping) else {}
        label = _round_label(details.get("round") or record.get("status"))
        if label:
            record["status"] = label
            details["round"] = label
            record["golf"] = details
        records.append(record)
    result["content"] = records
    return result


def _round_label(value: object) -> str:
    """Return one stable golf round label without ESPN progress wording."""

    match = re.search(r"\b(?:round|r)\s*(\d+)\b", str(value or ""), re.IGNORECASE)
    return f"Round {match.group(1)}" if match else ""


__all__ = ["GolfProvider", "GolfSource"]
