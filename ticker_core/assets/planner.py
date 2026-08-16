"""Plan all content assets before a mode selects visible content."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from .model import AssetRequest


@dataclass(frozen=True, slots=True)
class AssetPlan:
    """Store the unique prepared variants needed by one payload."""

    requests: tuple[AssetRequest, ...]


class AssetPlanner:
    """Extract assets from every parsed payload content family."""

    def plan(self, payload_or_content: object) -> AssetPlan:
        """Build requests from all content without reading the active mode."""
        requests: set[AssetRequest] = set()
        for item in _payload_items(payload_or_content):
            self._add_item(requests, item)
        return AssetPlan(tuple(sorted(requests, key=lambda request: (request.url, request.processor, request.size))))

    def _add_item(self, requests: set[AssetRequest], item: Mapping[str, Any]) -> None:
        family = str(item.get("family") or "").lower()
        kind = str(item.get("kind") or "").lower()
        item_type = str(item.get("type") or kind).lower()
        sport = str(item.get("sport") or family).lower()
        if item.get("team_logo"):
            for size in ((16, 16), (24, 24)):
                _add(requests, item.get("team_logo"), "logo", size)
        for key in ("from_logo", "to_logo"):
            _add(requests, item.get(key), "logo", (24, 24))
        if item_type == "music" or sport == "music" or family == "music" or kind in {"music", "spotify"}:
            for key in ("cover", "last_cover", "home_logo", "last_logo", "artwork", "cover_url", "album_art"):
                _add(requests, item.get(key), "logo", (42, 42))
            for url in (*_urls(item.get("next_logos")), *_urls(item.get("next_artwork")), *_urls(item.get("next_covers"))):
                _add(requests, url, "logo", (42, 42))
            last_song = item.get("last_song")
            if isinstance(last_song, Mapping):
                _add(requests, last_song.get("cover"), "logo", (42, 42))
            for next_song in _records(item.get("next_songs")):
                _add(requests, next_song.get("cover"), "logo", (42, 42))
            return
        if item_type in {"flight_visitor", "flight_airport_hud", "flight_arrival", "flight_departure"} or sport in {"flight", "flights"} or family in {"flight", "flights"}:
            for record in (item, *_records(item.get("arrivals")), *_records(item.get("departures"))):
                for key in ("airline_logo", "airline_image", "airline_logo_url", "carrier_logo", "home_logo", "away_logo"):
                    _add(requests, record.get(key), "logo", (24, 24))
                _add(requests, _flight_logo_url(record), "logo", (22, 22))
            return
        if item_type == "racing" or sport in {"indycar", "f1", "nascar"} or family == "racing" or kind in {"racing", "indycar", "f1", "nascar"}:
            series = _mapping(item.get(sport)) or _mapping(item.get(kind)) or _mapping(item.get("indycar")) or _mapping(item.get("f1")) or _mapping(item.get("nascar"))
            for driver in series.get("drivers", ()):
                if not isinstance(driver, Mapping):
                    continue
                _add(requests, driver.get("team_logo"), "logo", (18, 18))
                _add(requests, driver.get("team_logo"), "logo", (21, 21))
                car = driver.get("car_illustration")
                _add(requests, car, "car" if "nascar.com" in str(car or "") else "image", (130, 20) if "nascar.com" in str(car or "") else (120, 19))
            return
        for key in ("home_logo", "away_logo"):
            for size in ((16, 16), (22, 22), (24, 24)):
                _add(requests, item.get(key), "logo", size)


def _content_items(value: object) -> Iterable[Mapping[str, Any]]:
    """Read content item mappings from protocol data or raw mappings."""
    content = getattr(value, "content", value)
    if isinstance(content, Mapping):
        nested = content.get("content")
        if isinstance(nested, Mapping):
            content = nested
    if isinstance(content, Mapping):
        for family in content.values():
            yield from _content_items(family)
        return
    for item in content if isinstance(content, Iterable) and not isinstance(content, (str, bytes, Mapping)) else ():
        data = getattr(item, "data", item)
        if isinstance(data, Mapping):
            family = getattr(item, "family", None)
            kind = getattr(item, "kind", None)
            if family or kind:
                merged = dict(data)
                if family and "family" not in merged:
                    merged["family"] = family
                if kind and "kind" not in merged:
                    merged["kind"] = kind
                yield merged
            else:
                yield data


def _payload_items(value: object) -> Iterable[Mapping[str, Any]]:
    """Read content and overlay items before display policy filters them."""
    yield from _content_items(value)
    for name in ("alerts", "news"):
        items = getattr(value, name, ())
        if isinstance(value, Mapping):
            items = value.get(name, ())
        if not isinstance(items, (list, tuple)):
            continue
        for item in items:
            data = getattr(item, "data", item)
            if isinstance(data, Mapping):
                yield data


def _mapping(value: object) -> Mapping[str, Any]:
    """Return one mapping or an empty mapping."""
    return value if isinstance(value, Mapping) else {}


def _urls(value: object) -> Iterable[str]:
    """Return valid URL strings from a payload value."""
    return (entry for entry in value if isinstance(entry, str) and entry) if isinstance(value, (list, tuple)) else ()


def _records(value: object) -> Iterable[Mapping[str, Any]]:
    """Return mapping records from one aggregate content field."""
    return (entry for entry in value if isinstance(entry, Mapping)) if isinstance(value, (list, tuple)) else ()


def _add(requests: set[AssetRequest], value: object, processor: str, size: tuple[int, int]) -> None:
    """Add one nonempty URL request."""
    if isinstance(value, str) and value:
        requests.add(AssetRequest(value, processor, size))


def _flight_logo_url(item: Mapping[str, Any]) -> str:
    """Return the same airline favicon URL used by the flight renderer."""
    for key in ("airline_logo", "airline_image", "airline_logo_url", "carrier_logo"):
        value = str(item.get(key) or "").strip()
        if value:
            return value
    for key in ("airline_iata", "airline_code", "airline_icao", "airline"):
        code = str(item.get(key) or "").strip().upper().replace(" ", "")
        if len(code) in (2, 3) and code.isalnum():
            return f"https://www.google.com/s2/favicons?domain={_airline_domain(code)}&sz=64"
    flight_id = str(item.get("away_abbr") or "").strip().upper().replace(" ", "")
    if len(flight_id) in (2, 3) and flight_id.isalnum():
        return f"https://www.google.com/s2/favicons?domain={_airline_domain(flight_id)}&sz=64"
    return ""


def _airline_domain(code: str) -> str:
    """Map known airline codes to their public domains."""
    return {
        "UA": "united.com", "DL": "delta.com", "AA": "aa.com", "WN": "southwest.com",
        "B6": "jetblue.com", "AS": "alaskaair.com", "AC": "aircanada.com", "BA": "britishairways.com",
        "LH": "lufthansa.com", "AF": "airfrance.us", "KL": "klm.com", "EK": "emirates.com",
    }.get(code, f"{code.lower()}.com")
