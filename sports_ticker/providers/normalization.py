"""Adapt provider payloads into immutable canonical domain values."""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Mapping
from datetime import datetime, timezone
from types import MappingProxyType
from typing import Any

from sports_ticker.domain import CONTENT_FAMILIES, ContentItem, DisplaySettings

from .contracts import ProviderHealth, ProviderResult
from .logo_overrides import corrected_logo


_HIDDEN_STATUS_KEYWORDS = frozenset(
    {"postponed", "suspended", "canceled", "cancelled", "ppd"}
)
_FAMILY_ALIASES = {
    "flight_visitor": "flights",
    "flight_airport_hud": "airports",
    "airport": "airports",
    "airport_hud": "airports",
    "airport_activity": "airports",
    "stock_ticker": "stock",
    "stocks": "stock",
    "system": "status",
}
_RACING_SPORTS = frozenset(
    {"f1", "formula1", "formula_1", "indycar", "nascar", "imsa", "wec", "racing"}
)
_VISITOR_FLIGHT_KINDS = frozenset({"flight", "flight_visitor"})
_AIRPORT_KINDS = frozenset(
    {"airport", "airport_activity", "airport_hud", "flight_airport_hud"}
)
_RECORD_KEYS = frozenset(
    {
        "id",
        "identifier",
        "family",
        "kind",
        "type",
        "sport",
        "is_shown",
        "visible",
        "status",
        "home_abbr",
        "away_abbr",
        "home_team",
        "away_team",
        "data",
    }
)


def normalize_settings(value: DisplaySettings | Mapping[str, Any] | None) -> DisplaySettings:
    """Return immutable display settings from canonical or source mapping input."""

    if isinstance(value, DisplaySettings):
        return value
    if value is None:
        return DisplaySettings()
    if not isinstance(value, Mapping):
        raise TypeError("settings must be DisplaySettings, a mapping, or None")

    active_sports = value.get("active_sports", {})
    if not isinstance(active_sports, Mapping):
        active_sports = {}
    return DisplaySettings(
        active_sports=dict(active_sports),
        my_teams=value.get("my_teams", ()),
        mode=str(value.get("mode", "sports")),
        sports_filter=value.get("sports_filter", "all"),
        sports_presentation=value.get("sports_presentation", "rotation"),
        pinned_content_id=value.get("pinned_content_id", ""),
        brightness=value.get("brightness", 100.0),
        inverted=value.get("inverted", False),
        timezone=value.get("timezone", ""),
        weather_city=value.get("weather_city", "New York"),
        weather_lat=value.get("weather_lat", 40.7128),
        weather_lon=value.get("weather_lon", -74.0060),
        airport_code_iata=value.get("airport_code_iata", "EWR"),
        airport_code_icao=value.get("airport_code_icao", "KEWR"),
        airport_name=value.get("airport_name", "Newark Liberty International"),
        track_flight_id=value.get("track_flight_id", ""),
        track_guest_name=value.get("track_guest_name", ""),
        live_delay_mode=value.get("live_delay_mode", False),
        live_delay_seconds=value.get("live_delay_seconds", 45.0),
        scroll_seamless=value.get("scroll_seamless", True),
        scroll_speed=value.get("scroll_speed", 0.03),
        score_alerts=value.get("score_alerts", True),
    )


def normalize_content(
    records: Iterable[ContentItem | Mapping[str, Any]] | Mapping[str, Any],
    settings: DisplaySettings | Mapping[str, Any] | None = None,
) -> tuple[ContentItem, ...]:
    """Convert flat or family-grouped records into visible canonical content."""

    effective_settings = normalize_settings(settings)
    normalized: list[ContentItem] = []
    for family_hint, record in _content_records(records):
        item = record if isinstance(record, ContentItem) else _content_item(record, family_hint)
        if _is_visible(item, effective_settings):
            normalized.append(item)
    return tuple(normalized)


def normalize_provider_result(
    value: ProviderResult | Mapping[str, Any] | Iterable[Mapping[str, Any]],
    settings: DisplaySettings | Mapping[str, Any] | None = None,
    *,
    provider: str = "provider",
    observed_at: datetime | None = None,
) -> ProviderResult:
    """Return a normalized result that retains every visible content family."""

    effective_settings = normalize_settings(settings)
    if isinstance(value, ProviderResult):
        result_health = value.health
        result_observed_at = value.observed_at
        raw_content = value.content
        raw_alerts = value.alerts
        raw_news = value.news
    elif isinstance(value, Mapping):
        raw_content = _first_present(value, "content", "games", "items", "data")
        if raw_content is None:
            raw_content = ()
        raw_alerts = value.get("alerts", ())
        raw_news = value.get("news", ())
        result_observed_at = _datetime(
            value.get("observed_at", value.get("observation_time"))
        )
        result_health = _health(value.get("health", value.get("healthy", True)), provider)
    else:
        raw_content = value
        raw_alerts = ()
        raw_news = ()
        result_observed_at = None
        result_health = ProviderHealth(provider=provider)

    effective_observed_at = result_observed_at or observed_at or datetime.now(timezone.utc)
    if result_health.provider == "provider" and provider != "provider":
        result_health = ProviderHealth(
            healthy=result_health.healthy,
            provider=provider,
            error=result_health.error,
        )
    return ProviderResult(
        content=normalize_content(raw_content, effective_settings),
        alerts=tuple(_freeze(item) for item in _records(raw_alerts)),
        news=tuple(_freeze(item) for item in _records(raw_news)),
        observed_at=effective_observed_at,
        health=result_health,
    )


def _content_records(
    value: Iterable[ContentItem | Mapping[str, Any]] | Mapping[str, Any],
) -> tuple[tuple[str | None, ContentItem | Mapping[str, Any]], ...]:
    """Flatten source family groups while retaining each record mapping."""

    if isinstance(value, ContentItem):
        return ((None, value),)
    if isinstance(value, Mapping) and _is_grouped_content(value):
        flattened: list[tuple[str | None, ContentItem | Mapping[str, Any]]] = []
        for family, records in value.items():
            family_name = str(family).strip().lower()
            for record in _records(records):
                if isinstance(record, (ContentItem, Mapping)):
                    flattened.append((family_name, record))
        return tuple(flattened)
    return tuple((None, record) for record in _records(value))


def _is_grouped_content(value: Mapping[str, Any]) -> bool:
    """Identify a family map without mistaking one source record for a group."""

    if any(str(key).strip().lower() in CONTENT_FAMILIES for key in value):
        return True
    if any(str(key).strip().lower() in _FAMILY_ALIASES for key in value):
        return True
    return not any(str(key).strip().lower() in _RECORD_KEYS for key in value) and any(
        isinstance(item, (list, tuple, set, frozenset)) for item in value.values()
    )


def _content_item(record: Mapping[str, Any], family_hint: str | None = None) -> ContentItem:
    """Convert one source mapping and copy all source facts into immutable data."""

    if not isinstance(record, Mapping):
        raise TypeError("content records must be mappings or ContentItem values")
    family = _family(record, family_hint)
    kind = _text(_first_present(record, "kind", "type"), family)
    return ContentItem(
        id=_stable_identifier(record, family, kind),
        family=family,
        kind=kind,
        is_shown=bool(record.get("is_shown", record.get("visible", True))),
        data=_data_payload(record, family, kind),
    )


def _family(record: Mapping[str, Any], family_hint: str | None) -> str:
    """Return the canonical display family for one source record."""

    explicit = _text(record.get("family")).lower()
    if explicit:
        return _canonical_family(explicit)
    kind = _text(_first_present(record, "kind", "type")).lower()
    sport = _normalize_sport(record.get("sport"))
    if family_hint:
        hinted = _canonical_family(family_hint)
        if hinted != "sports":
            if hinted == "flights" and kind in _AIRPORT_KINDS:
                return "airports"
            if hinted == "airports" and kind in _VISITOR_FLIGHT_KINDS:
                return "flights"
            return hinted
    if kind in {"weather", "music", "clock"} or sport in {"weather", "music", "clock"}:
        return kind if kind in {"weather", "music", "clock"} else sport
    if kind in _VISITOR_FLIGHT_KINDS or sport in _VISITOR_FLIGHT_KINDS:
        return "flights"
    if kind in _AIRPORT_KINDS:
        return "airports"
    if kind.startswith("flight_airport") or sport in {"airport", "airports"}:
        return "airports"
    if kind in {"stock", "stocks", "stock_ticker"} or sport in {"stock", "stocks"}:
        return "stock"
    if kind == "golf" or sport == "golf":
        return "golf"
    if kind in _RACING_SPORTS or sport in _RACING_SPORTS:
        return "racing"
    if kind in {"status", "system"}:
        return "status"
    return "sports"


def _canonical_family(value: str) -> str:
    """Normalize family aliases into the canonical family names."""

    normalized = value.strip().lower()
    return _FAMILY_ALIASES.get(normalized, normalized or "sports")


def _stable_identifier(record: Mapping[str, Any], family: str, kind: str) -> str:
    """Preserve a source identifier or derive one deterministically from source facts."""

    for key in ("id", "identifier", "uid", "key"):
        value = record.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    stable = repr(_stable_value(record)).encode("utf-8", "replace")
    digest = hashlib.sha256(stable).hexdigest()[:16]
    return f"{family}:{kind}:{digest}"


def _stable_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return tuple(sorted((str(key), _stable_value(item)) for key, item in value.items()))
    if isinstance(value, (list, tuple)):
        return tuple(_stable_value(item) for item in value)
    if isinstance(value, (set, frozenset)):
        return tuple(sorted(_stable_value(item) for item in value))
    return value


def _data_payload(
    record: Mapping[str, Any],
    family: str,
    kind: str,
) -> dict[str, Any]:
    """Copy family-owned facts into a payload with an explicit family schema."""

    nested = record.get("data")
    data = dict(nested) if isinstance(nested, Mapping) else {}
    envelope_keys = {
        "id",
        "identifier",
        "uid",
        "key",
        "family",
        "kind",
        "type",
        "is_shown",
        "visible",
        "data",
    }
    for key, value in record.items():
        if str(key) not in envelope_keys:
            data.setdefault(key, value)

    if family in {"sports", "golf", "racing"}:
        sport = _normalize_sport(
            data.get("sport")
            or record.get("sport")
            or record.get("league")
            or (kind if family != "sports" else "")
        )
        data["sport"] = sport
        data.setdefault("schema", f"{family}.{sport or kind}")
        if family == "sports":
            _apply_sports_logo_overrides(data)
            data.setdefault("display", _sports_display(data))
    elif family in {"flights", "airports"}:
        data.setdefault("schema", f"{family}.{kind}")
    return data


def _apply_sports_logo_overrides(data: dict[str, Any]) -> None:
    """Resolve scoreboard logos through the shared provider override table."""

    league = data.get("league") or data.get("sport") or ""
    league_key = str(league).strip().upper()
    league_key = {
        "BASEBALL": "MLB",
        "BASKETBALL": "NBA",
        "FOOTBALL": "NFL",
        "HOCKEY": "NHL",
    }.get(league_key, league_key)
    display = data.get("display")
    display_copy = dict(display) if isinstance(display, Mapping) else {}
    for side in ("away", "home"):
        abbreviation = data.get(f"{side}_abbr") or _nested_text(data.get(side), "abbreviation", "abbr")
        field = f"{side}_logo"
        source_url = data.get(field)
        corrected = corrected_logo(league_key, str(abbreviation), source_url if source_url is not None else None)
        if corrected:
            data[field] = corrected
            side_display = display_copy.get(side)
            side_copy = dict(side_display) if isinstance(side_display, Mapping) else {}
            side_copy["logo"] = corrected
            display_copy[side] = side_copy
    if display_copy:
        data["display"] = display_copy


def _sports_display(data: Mapping[str, Any]) -> dict[str, Any]:
    """Normalize scoreboard facts inside sports data without creating domain teams."""

    existing = data.get("display")
    if isinstance(existing, Mapping):
        return dict(existing)
    canonical = data.get("canonical")
    source = canonical if isinstance(canonical, Mapping) else data
    return {
        "away": {
            "label": _text(
                source.get("away_abbr")
                or _nested_text(source.get("away"), "abbreviation", "abbr")
            ),
            "score": source.get("away_score"),
            "logo": source.get("away_logo"),
        },
        "home": {
            "label": _text(
                source.get("home_abbr")
                or _nested_text(source.get("home"), "abbreviation", "abbr")
            ),
            "score": source.get("home_score"),
            "logo": source.get("home_logo"),
        },
        "clock": source.get("clock", source.get("game_clock")),
    }


def _nested_text(value: Any, *keys: str) -> str:
    if not isinstance(value, Mapping):
        return ""
    for key in keys:
        if value.get(key) is not None:
            return _text(value[key])
    return ""


def _is_visible(item: ContentItem, settings: DisplaySettings) -> bool:
    """Apply explicit visibility, active-sport, and hidden-status rules."""

    if not item.is_shown:
        return False
    sport = _text(item.data.get("sport")).lower()
    if sport and not settings.active_sports.get(sport, True):
        return False
    status = _text(item.data.get("status")).lower()
    return not any(keyword in status for keyword in _HIDDEN_STATUS_KEYWORDS)


def _records(value: Any) -> tuple[Any, ...]:
    """Turn one provider collection into a stable tuple without changing it."""

    if value is None:
        return ()
    if isinstance(value, (str, bytes, Mapping, ContentItem)):
        return (value,)
    try:
        return tuple(value)
    except TypeError:
        return (value,)


def _first_present(mapping: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in mapping:
            return mapping[key]
    return None


def _health(value: Any, provider: str) -> ProviderHealth:
    if isinstance(value, ProviderHealth):
        return value
    if isinstance(value, Mapping):
        healthy = value.get("healthy", value.get("ok", value.get("status") == "ok"))
        return ProviderHealth(
            healthy=healthy,
            provider=str(value.get("provider", provider)),
            error=value.get("error", value.get("message")),
        )
    if isinstance(value, bool):
        return ProviderHealth(healthy=value, provider=provider)
    return ProviderHealth(healthy=bool(value), provider=provider)


def _datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


def _normalize_sport(value: Any) -> str:
    sport = _text(value).lower()
    return "mlb" if sport == "wbc" else sport


def _text(value: Any, default: str = "") -> str:
    return default if value is None else str(value)


def _freeze(value: Any) -> object:
    if isinstance(value, Mapping):
        return MappingProxyType({_freeze(key): _freeze(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_freeze(item) for item in value)
    if isinstance(value, tuple):
        return tuple(_freeze(item) for item in value)
    if isinstance(value, set):
        return frozenset(_freeze(item) for item in value)
    if isinstance(value, bytearray):
        return bytes(value)
    return value


__all__ = ["normalize_content", "normalize_provider_result", "normalize_settings"]
