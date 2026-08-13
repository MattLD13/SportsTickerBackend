"""Native live sources used by the production v2 composition."""

from __future__ import annotations

import os
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from math import isfinite
from typing import Any
from urllib.parse import urlencode

from sports_ticker.domain import DisplaySettings

from .http import JsonHttpClient, UrllibJsonHttpClient


ESPN_GOLF_URL = "https://site.api.espn.com/apis/site/v2/sports/golf/pga/scoreboard"
ESPN_RACING_URLS = {
    "f1": "https://site.api.espn.com/apis/site/v2/sports/racing/f1/scoreboard",
    "indycar": "https://site.api.espn.com/apis/site/v2/sports/racing/irl/scoreboard",
    "nascar": "https://site.api.espn.com/apis/site/v2/sports/racing/nascar-premier/scoreboard",
}
FINNHUB_QUOTE_URL = "https://finnhub.io/api/v1/quote"


class EspnGolfSource:
    """Read the PGA scoreboard directly from ESPN."""

    def __init__(self, client: JsonHttpClient | None = None, *, timeout: float = 10.0) -> None:
        self._client = client or UrllibJsonHttpClient()
        self._timeout = _timeout(timeout)

    def fetch(self, settings: DisplaySettings) -> Mapping[str, object]:
        del settings
        payload = self._client.get_json(ESPN_GOLF_URL, timeout=self._timeout)
        event = _first_event(payload)
        if event is None:
            return {"content": []}
        competition = _first_mapping(event.get("competitions"))
        players = [_golf_player(value) for value in _mappings(competition.get("competitors"))]
        players = [value for value in players if value is not None]
        status = _status(event, competition)
        return {
            "content": [
                {
                    "id": f"golf:{event.get('id', 'pga')}",
                    "type": "golf",
                    "sport": "golf",
                    "state": status["state"],
                    "status": status["text"],
                    "away_abbr": str(event.get("shortName") or event.get("name") or "PGA TOUR"),
                    "golf": {
                        "event_name": str(event.get("name") or "PGA TOUR"),
                        "year": _mapping(event.get("season")).get("year", datetime.now(timezone.utc).year),
                        "round": status["text"],
                        "players": players,
                    },
                }
            ]
        }


class EspnRacingSource:
    """Read the current F1, IndyCar, and NASCAR sessions from ESPN."""

    def __init__(self, client: JsonHttpClient | None = None, *, timeout: float = 10.0) -> None:
        self._client = client or UrllibJsonHttpClient()
        self._timeout = _timeout(timeout)

    def fetch(self, settings: DisplaySettings) -> Mapping[str, object]:
        del settings
        records: list[dict[str, object]] = []
        for series, url in ESPN_RACING_URLS.items():
            payload = self._client.get_json(url, timeout=self._timeout)
            event = _first_event(payload)
            if event is None:
                continue
            for competition in _mappings(event.get("competitions")) or ({},):
                records.append(_racing_record(series, event, competition))
        return {"content": records}


class FinnhubStockSource:
    """Read selected market quotes through the configured Finnhub key pool."""

    def __init__(
        self,
        client: JsonHttpClient | None = None,
        *,
        symbols: Sequence[str] = ("SPY", "QQQ", "DIA", "IWM"),
        timeout: float = 10.0,
    ) -> None:
        self._client = client or UrllibJsonHttpClient()
        self._symbols = tuple(_symbols(symbols))
        self._timeout = _timeout(timeout)
        self._keys = tuple(
            value
            for name in ("FINNHUB_KEY_1", "FINNHUB_KEY_2", "FINNHUB_KEY_3", "FINNHUB_KEY_4", "FINNHUB_KEY_5")
            if (value := os.environ.get(name, "").strip())
        )
        self._next_key = 0

    def fetch(self, settings: DisplaySettings) -> Mapping[str, object]:
        del settings
        if not self._keys:
            return {"content": []}
        records: list[dict[str, object]] = []
        for symbol in self._symbols:
            key = self._keys[self._next_key % len(self._keys)]
            self._next_key += 1
            quote = self._client.get_json(
                f"{FINNHUB_QUOTE_URL}?{urlencode({'symbol': symbol, 'token': key})}",
                timeout=self._timeout,
            )
            if not isinstance(quote, Mapping) or not _positive(quote.get("c")):
                continue
            price = float(quote["c"])
            change = _number(quote.get("d"))
            percent = _number(quote.get("dp"))
            records.append(
                {
                    "id": f"stock:{symbol}",
                    "type": "stock_ticker",
                    "sport": "stock",
                    "symbol": symbol,
                    "home_abbr": symbol,
                    "home_score": f"{price:.2f}",
                    "away_score": f"{percent:+.2f}%",
                    "home_logo": f"https://financialmodelingprep.com/image-stock/{symbol}.png",
                    "situation": {"change": f"{change:+.2f}"},
                    "status": "MARKET",
                    "state": "in",
                }
            )
        return {"content": records}


class FlightRadarSource:
    """Read a tracked flight or airport activity through FlightRadar24."""

    def __init__(self) -> None:
        self._api: object | None = None

    def fetch(self, settings: DisplaySettings) -> Mapping[str, object]:
        api = self._client()
        records: list[dict[str, object]] = []
        if settings.track_flight_id:
            flight = self._tracked_flight(api, settings)
            if flight is not None:
                records.append(flight)
        airport = self._airport_board(api, settings)
        if airport is not None:
            records.append(airport)
        return {"content": records}

    def _client(self) -> object:
        if self._api is None:
            from FlightRadarAPI import FlightRadar24API

            self._api = FlightRadar24API()
        return self._api

    def _tracked_flight(self, api: object, settings: DisplaySettings) -> dict[str, object] | None:
        search = getattr(api, "search", None)
        if not callable(search):
            return None
        payload = search(settings.track_flight_id)
        live = payload.get("live", ()) if isinstance(payload, Mapping) else ()
        if not isinstance(live, Sequence) or isinstance(live, (str, bytes)) or not live:
            return {
                "id": settings.track_flight_id,
                "type": "flight_visitor",
                "sport": "flight",
                "guest_name": settings.track_guest_name or settings.track_flight_id,
                "status": "pending",
                "is_live": False,
            }
        detail = _mapping(_mapping(live[0]).get("detail"))
        return {
            "id": str(detail.get("flight") or settings.track_flight_id),
            "type": "flight_visitor",
            "sport": "flight",
            "guest_name": settings.track_guest_name or settings.track_flight_id,
            "origin_city": str(detail.get("schd_from") or "UNKNOWN"),
            "dest_city": str(detail.get("schd_to") or "UNKNOWN"),
            "status": "en-route",
            "is_live": True,
            "airline": str(detail.get("operator") or ""),
            "aircraft_type": str(detail.get("ac_type") or ""),
        }

    def _airport_board(self, api: object, settings: DisplaySettings) -> dict[str, object] | None:
        details = getattr(api, "get_airport_details", None)
        if not callable(details):
            return None
        result = _mapping(details(settings.airport_code_iata, flight_limit=4))
        plugin_data = _mapping(_mapping(result.get("airport")).get("pluginData"))
        schedule = _mapping(plugin_data.get("schedule"))
        return {
            "id": f"airport:{settings.airport_code_iata}",
            "type": "flight_airport_hud",
            "sport": "airport",
            "weather": {
                "iata": settings.airport_code_iata,
                "city": settings.airport_name,
                "away_abbr": "",
                "status": "",
            },
            "arrivals": _airport_rows(_mapping(schedule.get("arrivals")).get("data"), "origin"),
            "departures": _airport_rows(_mapping(schedule.get("departures")).get("data"), "destination"),
        }


class EmptyNewsSource:
    """Keep durable v2 overlay events separate from provider content."""

    def fetch(self, settings: DisplaySettings) -> Mapping[str, object]:
        del settings
        return {"news": []}


class ClockProvider:
    """Publish the clock scene marker without a remote dependency."""

    def fetch(self, settings: DisplaySettings) -> Mapping[str, object]:
        del settings
        return {
            "content": [
                {
                    "id": "clock",
                    "type": "clock",
                    "sport": "clock",
                    "status": "active",
                }
            ]
        }


def _racing_record(series: str, event: Mapping[str, Any], competition: Mapping[str, Any]) -> dict[str, object]:
    status = _status(event, competition)
    session = _mapping(competition.get("type")).get("abbreviation") or "RACE"
    payload = {
        "event_name": str(event.get("name") or series.upper()),
        "short_name": str(event.get("shortName") or event.get("name") or series.upper()),
        "track_name": str(_mapping(competition.get("venue")).get("fullName") or ""),
        "session_name": str(session),
        "session_type": str(session),
        "flag": "CHECKERED" if status["state"] == "post" else "GREEN" if status["state"] == "in" else "WHITE",
        "drivers": _racing_drivers(competition),
    }
    return {
        "id": f"{series}:{event.get('id', 'event')}:{competition.get('id', 'session')}",
        "type": "racing",
        "sport": series,
        "series": series,
        "state": status["state"],
        "status": status["text"],
        "away_abbr": payload["short_name"],
        "home_abbr": payload["session_name"],
        series: payload,
    }


def _racing_drivers(competition: Mapping[str, Any]) -> list[dict[str, object]]:
    drivers: list[dict[str, object]] = []
    for index, competitor in enumerate(_mappings(competition.get("competitors"))[:20], start=1):
        athlete = _mapping(competitor.get("athlete"))
        position = competitor.get("order", competitor.get("curatedRank", index))
        drivers.append(
            {
                "pos": position,
                "name": str(athlete.get("displayName") or athlete.get("shortName") or "Driver"),
                "abbr": str(athlete.get("shortName") or "DRV")[:3].upper(),
                "car": str(competitor.get("id") or ""),
                "gap": str(competitor.get("score") or ""),
            }
        )
    return drivers


def _golf_player(value: Mapping[str, Any]) -> dict[str, object] | None:
    athlete = _mapping(value.get("athlete"))
    name = str(athlete.get("displayName") or athlete.get("shortName") or "").strip()
    if not name:
        return None
    round_scores = _mappings(value.get("linescores"))
    holes = _mappings(round_scores[0].get("linescores")) if round_scores else ()
    return {
        "pos": value.get("order", "-"),
        "name": name,
        "total": value.get("score", 0),
        "today": round_scores[0].get("displayValue") if round_scores else None,
        "thru": len(holes),
        "holes": [item.get("value") for item in holes[:18]],
    }


def _airport_rows(value: object, counterpart: str) -> list[dict[str, object]]:
    values = value if isinstance(value, Sequence) and not isinstance(value, (str, bytes)) else ()
    rows: list[dict[str, object]] = []
    for flight in values[:4]:
        raw = _mapping(_mapping(flight).get("flight"))
        airline = _mapping(raw.get("airline"))
        code = _mapping(airline.get("code"))
        airport = _mapping(_mapping(raw.get("airport")).get(counterpart))
        airport_code = _mapping(airport.get("code"))
        identification = _mapping(raw.get("identification"))
        number = _mapping(identification.get("number"))
        aircraft = _mapping(raw.get("aircraft"))
        rows.append(
            {
                "away_abbr": str(code.get("iata") or code.get("icao") or "---"),
                "other_iata": str(airport_code.get("iata") or "---"),
                "home_abbr": str(number.get("default") or "---"),
                "altitude": _mapping(aircraft.get("model")).get("code", ""),
            }
        )
    return rows


def _first_event(payload: object) -> Mapping[str, Any] | None:
    return _mappings(_mapping(payload).get("events"))[0] if _mappings(_mapping(payload).get("events")) else None


def _status(event: Mapping[str, Any], competition: Mapping[str, Any]) -> dict[str, str]:
    source = _mapping(competition.get("status")) or _mapping(event.get("status"))
    kind = _mapping(source.get("type"))
    return {
        "state": str(kind.get("state") or "pre").lower(),
        "text": str(kind.get("shortDetail") or kind.get("detail") or kind.get("description") or "Scheduled"),
    }


def _mappings(value: object) -> tuple[Mapping[str, Any], ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return ()
    return tuple(item for item in value if isinstance(item, Mapping))


def _first_mapping(value: object) -> Mapping[str, Any]:
    values = _mappings(value)
    return values[0] if values else {}


def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _timeout(value: float) -> float:
    result = float(value)
    if not isfinite(result) or result <= 0:
        raise ValueError("timeout must be finite and positive")
    return result


def _symbols(values: Sequence[str]) -> tuple[str, ...]:
    return tuple(value.upper() for raw in values if (value := str(raw).strip().upper()))


def _positive(value: object) -> bool:
    return _number(value) > 0


def _number(value: object) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


__all__ = [
    "EmptyNewsSource",
    "ClockProvider",
    "EspnGolfSource",
    "EspnRacingSource",
    "FinnhubStockSource",
    "FlightRadarSource",
]
