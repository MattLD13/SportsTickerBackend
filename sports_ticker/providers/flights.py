"""Injected visitor-flight and airport-HUD provider adapter."""

from __future__ import annotations

from typing import Any

from sports_ticker.domain import ContentItem, DisplaySettings

from .contracts import ProviderResult
from .features import FlightsSource, _FeatureProvider, _content_payload


class FlightsProvider(_FeatureProvider):
    """Adapt one injected flight source into visitor or airport HUD content."""

    family = "flights"
    provider_name = "flights"

    def __init__(self, source: FlightsSource) -> None:
        super().__init__(source)

    def fetch(self, settings: DisplaySettings) -> ProviderResult:
        """Fetch and normalize flight records with distinct HUD kinds."""

        result = self._fetch_normalized(
            settings,
            lambda payload: _content_payload(
                payload,
                self.family,
                _flight_kind,
                _flight_family,
            ),
        )
        if settings.track_flight_id or any(
            item.family == "flights" for item in result.content
        ):
            return result
        return ProviderResult(
            content=(*result.content, _default_flight_item()),
            alerts=result.alerts,
            news=result.news,
            observed_at=result.observed_at,
            health=result.health,
        )


def _flight_kind(record: dict[str, Any], group: str | None) -> str:
    values = (
        group,
        record.get("kind"),
        record.get("type"),
        record.get("sport"),
    )
    candidate = " ".join(str(value or "").strip().lower() for value in values)
    if "visitor" in candidate or record.get("guest_name") is not None:
        return "flight_visitor"
    return "flight_airport_hud"


def _flight_family(record: dict[str, Any], group: str | None) -> str:
    """Keep tracked visitor flights separate from airport activity records."""

    return "flights" if _flight_kind(record, group) == "flight_visitor" else "airports"


def _default_flight_item() -> ContentItem:
    """Return the tracker setup card when no visitor flight is selected."""

    return ContentItem(
        id="flight_blank",
        family="flights",
        kind="flight_visitor",
        is_shown=True,
        data={
            "type": "flight_visitor",
            "sport": "flight",
            "id": "flight_blank",
            "guest_name": "NO FLIGHT SELECTED",
            "route": "TRACKER > SETUP",
            "origin_city": "TRACKER",
            "dest_city": "SETUP",
            "alt": 0,
            "dist": 0,
            "eta_str": "--",
            "speed": 0,
            "progress": 0,
            "status": "ADD FLIGHT",
            "delay_min": 0,
            "is_delayed": False,
            "is_live": False,
            "aircraft_type": "",
            "aircraft_code": "",
        },
    )


__all__ = ["FlightsProvider", "FlightsSource"]
