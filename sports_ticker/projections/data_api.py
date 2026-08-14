"""Build the versioned JSON projection for ticker data."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime, time
from typing import Any

from ..domain import CONTENT_FAMILIES, ContentItem, DisplaySettings, TickerSnapshot
from ..providers.contracts import ProviderHealth


_SPORTS_FAMILIES = frozenset(("sports", "golf", "racing"))
_MODE_FAMILIES = {
    "sports": _SPORTS_FAMILIES,
}


def project_data_v2(
    snapshot: TickerSnapshot,
    health: ProviderHealth | Mapping[str, Any],
    meta: Mapping[str, Any],
) -> dict[str, Any]:
    """Return a new JSON-ready version two data projection."""

    if not isinstance(snapshot, TickerSnapshot):
        raise TypeError("snapshot must be a TickerSnapshot")
    if not isinstance(meta, Mapping):
        raise TypeError("meta must be a mapping")

    copied_meta = _json_value(meta)
    if not isinstance(copied_meta, dict):
        raise TypeError("meta must produce a mapping")

    content: dict[str, list[dict[str, Any]]] = {
        family: [] for family in CONTENT_FAMILIES
    }
    for item in snapshot.content:
        family = item.family if item.family in content else item.family
        content.setdefault(family, []).append(_content_item(item))

    return {
        "api_version": "v2",
        "snapshot": {
            "ticker_id": str(snapshot.ticker_id),
            "revision": snapshot.revision,
            "observed_at": _json_value(snapshot.observed_at),
            "stale": _stale_value(meta),
        },
        "settings": _settings_value(snapshot.effective_settings),
        "content": content,
        "events": {
            "alerts": _json_value(snapshot.alerts),
            "news": _json_value(snapshot.news),
        },
        "health": _health_value(health),
        "meta": copied_meta,
    }


def _settings_value(settings: DisplaySettings) -> dict[str, Any]:
    """Copy canonical display settings into a JSON-ready mapping."""

    if not isinstance(settings, DisplaySettings):
        raise TypeError("snapshot settings must be DisplaySettings")
    return {
        "active_sports": _json_value(settings.active_sports),
        "my_teams": list(settings.my_teams),
        "mode": settings.mode,
        "sports_presentation": settings.sports_presentation,
        "pinned_content_id": settings.pinned_content_id,
        "brightness": settings.brightness,
        "inverted": settings.inverted,
        "timezone": settings.timezone,
        "weather_city": settings.weather_city,
        "weather_lat": settings.weather_lat,
        "weather_lon": settings.weather_lon,
        "airport_code_iata": settings.airport_code_iata,
        "airport_code_icao": settings.airport_code_icao,
        "airport_name": settings.airport_name,
        "track_flight_id": settings.track_flight_id,
        "track_guest_name": settings.track_guest_name,
        "live_delay_mode": settings.live_delay_mode,
        "live_delay_seconds": settings.live_delay_seconds,
        "scroll_seamless": settings.scroll_seamless,
        "scroll_speed": settings.scroll_speed,
        "score_alerts": settings.score_alerts,
    }


def select_display_content(
    content: Mapping[str, list[dict[str, Any]]],
    settings: Mapping[str, Any],
) -> dict[str, list[dict[str, Any]]]:
    """Return only records that the receiving panel can show now."""

    mode = str(settings.get("mode") or "sports").strip().lower()
    if mode == "pairing":
        return {}
    families = _MODE_FAMILIES.get(mode, frozenset((mode,)))
    selected = {
        family: list(items)
        for family, items in content.items()
        if family in families and items
    }
    pinned = str(settings.get("pinned_content_id") or "").strip()
    selected = {family: items for family, items in selected.items() if items}
    if mode == "sports" and pinned:
        selected = {
            family: [item for item in items if str(item.get("id") or "") == pinned]
            for family, items in selected.items()
        }
        selected = {family: items for family, items in selected.items() if items}
    return selected


def _content_item(item: ContentItem) -> dict[str, Any]:
    """Serialize one canonical content item without retaining its object."""

    if not isinstance(item, ContentItem):
        raise TypeError("snapshot content must contain ContentItem values")
    return {
        "id": item.id,
        "family": item.family,
        "kind": item.kind,
        "is_shown": item.is_shown,
        "data": _json_value(item.data),
    }


def _health_value(health: ProviderHealth | Mapping[str, Any]) -> dict[str, Any]:
    """Copy provider health while keeping it separate from snapshot staleness."""

    if isinstance(health, ProviderHealth):
        return {
            "provider": health.provider,
            "healthy": health.healthy,
            "error": health.error,
        }
    if not isinstance(health, Mapping):
        raise TypeError("health must be ProviderHealth or a mapping")
    return {
        "provider": str(health.get("provider", "provider")),
        "healthy": bool(health.get("healthy", health.get("ok", False))),
        "error": _json_value(health.get("error")),
    }


def _stale_value(meta: Mapping[str, Any]) -> Any:
    """Copy the displayed stale state from explicit metadata."""

    return _json_value(meta.get("stale", False))


def _json_value(value: Any) -> Any:
    """Copy supported immutable values into JSON-compatible containers."""

    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    if isinstance(value, Mapping):
        return {str(key): _json_value(child) for key, child in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_json_value(child) for child in value]
    raise TypeError(f"value of type {type(value).__name__} is not JSON-ready")


__all__ = ["project_data_v2", "select_display_content"]
