"""Native live sources used by the production v2 composition."""

from __future__ import annotations

import os
import re
import json
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from math import isfinite
from pathlib import Path
from threading import Lock, Thread
from time import monotonic, sleep, time
from typing import Any
from urllib.parse import urlencode

from sports_ticker.domain import DisplaySettings
from sports_ticker.leagues import RACING_SCOREBOARD_PATHS
from sports_ticker.markets import MARKET_GROUPS

from .espn import _is_current_event
from .http import JsonHttpClient, UrllibJsonHttpClient


ESPN_GOLF_URL = "https://site.api.espn.com/apis/site/v2/sports/golf/pga/scoreboard"
ESPN_RACING_URLS = {
    series: f"https://site.api.espn.com/apis/site/v2/sports/{path}/scoreboard"
    for series, path in RACING_SCOREBOARD_PATHS.items()
}
FINNHUB_QUOTE_URL = "https://finnhub.io/api/v1/quote"
FINNHUB_CANDLE_URL = "https://finnhub.io/api/v1/stock/candle"
_ETF_LOGO_DOMAINS = {
    "QQQ": "invesco.com",
    "SPY": "spdrs.com",
    "IWM": "ishares.com",
    "DIA": "statestreet.com",
}


class EspnGolfSource:
    """Read the PGA scoreboard directly from ESPN."""

    def __init__(self, client: JsonHttpClient | None = None, *, timeout: float = 10.0) -> None:
        self._client = client or UrllibJsonHttpClient()
        self._timeout = _timeout(timeout)

    def fetch(self, settings: DisplaySettings) -> Mapping[str, object]:
        payload = self._client.get_json(ESPN_GOLF_URL, timeout=self._timeout)
        event = _first_event(payload)
        if event is None or not _is_current_event(event, timezone_name=settings.timezone):
            return {"content": []}
        competition = _first_mapping(event.get("competitions"))
        players = [_golf_player(value) for value in _mappings(competition.get("competitors"))]
        players = _rank_golf_players(value for value in players if value is not None)
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
                        "round": _golf_round(status["text"]),
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
        records: list[dict[str, object]] = []
        for series, url in ESPN_RACING_URLS.items():
            payload = self._client.get_json(url, timeout=self._timeout)
            event = _first_event(payload)
            if event is None or not _is_current_event(event, timezone_name=settings.timezone):
                continue
            for competition in _mappings(event.get("competitions")) or ({},):
                records.append(_racing_record(series, event, competition))
        return {"content": records}


class FinnhubStockSource:
    """Read selected market quotes with rate limits and durable last-known values."""

    def __init__(
        self,
        client: JsonHttpClient | None = None,
        *,
        timeout: float = 10.0,
        cache_path: Path | str | None = None,
        clock: callable = time,
        monotonic_clock: callable = monotonic,
        sleeper: callable = sleep,
        refresh_seconds: float = 30.0,
    ) -> None:
        self._client = client or UrllibJsonHttpClient()
        self._timeout = _timeout(timeout)
        self._keys = tuple(dict.fromkeys(
            value
            for name in (
                "FINNHUB_API_KEY", "FINNHUB_KEY_1", "FINNHUB_KEY_2",
                "FINNHUB_KEY_3", "FINNHUB_KEY_4", "FINNHUB_KEY_5",
            )
            if (value := os.environ.get(name, "").strip())
        ))
        self._clock = clock
        self._monotonic = monotonic_clock
        self._sleep = sleeper
        self._cache_path = Path(
            cache_path or os.environ.get("TICKER_STOCK_CACHE_PATH", "ticker_data/stocks.json")
        )
        self._quotes = self._load_cache()
        self._next_key = 0
        self._request_interval = 1.1 / len(self._keys) if self._keys else 0.0
        self._last_request = float("-inf")
        self._refresh_seconds = _timeout(refresh_seconds)
        self._last_refresh = float("-inf")
        self._request_lock = Lock()
        self._refresh_lock = Lock()
        self._quote_lock = Lock()
        self._refreshing = False

    def fetch(self, settings: DisplaySettings) -> Mapping[str, object]:
        self._start_all_market_refresh()
        records: list[dict[str, object]] = []
        for group in MARKET_GROUPS:
            records.extend(self._group_records(group.id, group.label, group.symbols))
        return {"content": records}

    def _start_all_market_refresh(self) -> None:
        """Start one shared all-market refresh without delaying a settings change."""

        now = self._monotonic()
        with self._refresh_lock:
            if self._refreshing or now - self._last_refresh < self._refresh_seconds:
                return
            self._last_refresh = now
            self._refreshing = True
        Thread(target=self._refresh_all_markets, name="ticker-stock-refresh", daemon=True).start()

    def _refresh_all_markets(self) -> None:
        """Refresh every quote in the source-owned market cache."""

        changed = False
        try:
            symbols = tuple(
                dict.fromkeys(symbol for group in MARKET_GROUPS for symbol in group.symbols)
            )
            for symbol in symbols:
                quote = self._fetch_quote(symbol) if self._keys else None
                if quote is not None:
                    with self._quote_lock:
                        self._quotes[symbol] = quote
                    changed = True
            if changed:
                self._save_cache()
        finally:
            with self._refresh_lock:
                self._refreshing = False

    def _group_records(
        self,
        group_id: str,
        group_label: str,
        symbols: Sequence[str],
    ) -> list[dict[str, object]]:
        """Build one selected market list from the shared quote cache."""

        records: list[dict[str, object]] = []
        with self._quote_lock:
            quotes = dict(self._quotes)
        for symbol in symbols:
            quote = quotes.get(symbol)
            if quote is None:
                continue
            records.append(
                {
                    "id": f"stock:{symbol}",
                    "type": "stock_ticker",
                    "sport": "stock",
                    "market_group": group_id,
                    "list_id": group_id,
                    "symbol": symbol,
                    "home_abbr": symbol,
                    "home_score": quote["price"],
                    "away_score": quote["change_pct"],
                    "home_logo": _stock_logo_url(symbol),
                    "situation": {"change": quote["change_amount"]},
                    "status": group_label,
                    "state": "in",
                }
            )
        return records

    def _fetch_quote(self, symbol: str) -> dict[str, str] | None:
        """Fetch one quote, with a close-price fallback after market data ages."""

        key = self._next_api_key()
        if not key:
            return None
        try:
            quote = self._get_json(FINNHUB_QUOTE_URL, symbol=symbol, token=key)
            if not isinstance(quote, Mapping) or not _positive(quote.get("c")):
                return None
            price = _number(quote.get("c"))
            change = _number(quote.get("d"))
            percent = _number(quote.get("dp"))
            timestamp = _number(quote.get("t"))
            if timestamp > 0 and self._clock() - timestamp > 30:
                try:
                    candle = self._latest_candle(
                        symbol, key, previous_close=_number(quote.get("pc"))
                    )
                except Exception:
                    candle = None
                if candle is not None:
                    price, change, percent = candle
            return {
                "price": f"{price:.2f}",
                "change_amount": f"{change:+.2f}",
                "change_pct": f"{percent:+.2f}%",
            }
        except Exception:
            return None

    def _latest_candle(
        self, symbol: str, key: str, *, previous_close: float
    ) -> tuple[float, float, float] | None:
        """Use the latest one-minute close when the quote timestamp is stale."""

        now = int(self._clock())
        candle = self._get_json(
            FINNHUB_CANDLE_URL,
            symbol=symbol,
            resolution="1",
            **{"from": now - 1800, "to": now, "token": key},
        )
        closes = candle.get("c") if isinstance(candle, Mapping) else None
        if not isinstance(closes, Sequence) or isinstance(closes, (str, bytes)) or not closes:
            return None
        latest = _number(closes[-1])
        if latest <= 0:
            return None
        reference = previous_close if previous_close > 0 else latest
        change = latest - reference
        return latest, change, (change / reference) * 100 if reference else 0.0

    def _next_api_key(self) -> str:
        """Rotate configured keys in stable order."""

        key = self._keys[self._next_key % len(self._keys)]
        self._next_key += 1
        return key

    def _get_json(self, endpoint: str, **query: object) -> Mapping[str, object]:
        """Make one paced Finnhub request through the injected JSON client."""

        with self._request_lock:
            delay = self._request_interval - (self._monotonic() - self._last_request)
            if delay > 0:
                self._sleep(delay)
            self._last_request = self._monotonic()
        result = self._client.get_json(
            f"{endpoint}?{urlencode(query)}", timeout=self._timeout
        )
        return result if isinstance(result, Mapping) else {}

    def _load_cache(self) -> dict[str, dict[str, str]]:
        """Load valid last-known quote values without allowing malformed cache data."""

        try:
            payload = json.loads(self._cache_path.read_text(encoding="utf-8"))
            values = payload.get("quotes", payload) if isinstance(payload, Mapping) else {}
            return {
                str(symbol).upper(): {
                    "price": str(data["price"]),
                    "change_amount": str(data["change_amount"]),
                    "change_pct": str(data["change_pct"]),
                }
                for symbol, data in values.items()
                if isinstance(data, Mapping)
                and all(key in data for key in ("price", "change_amount", "change_pct"))
            }
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            return {}

    def _save_cache(self) -> None:
        """Persist last-known valid quotes atomically for a backend restart."""

        temporary = self._cache_path.with_name(f".{self._cache_path.name}.tmp")
        try:
            self._cache_path.parent.mkdir(parents=True, exist_ok=True)
            with self._quote_lock:
                quotes = dict(self._quotes)
            temporary.write_text(
                json.dumps({"quotes": quotes}, sort_keys=True, separators=(",", ":")),
                encoding="utf-8",
            )
            os.replace(temporary, self._cache_path)
        except OSError:
            temporary.unlink(missing_ok=True)


def _stock_logo_url(symbol: str) -> str:
    """Return one stable stock logo URL that the Pi caches by URL and size."""

    clean = str(symbol).strip().upper()
    domain = _ETF_LOGO_DOMAINS.get(clean)
    if domain:
        return f"https://logo.clearbit.com/{domain}"
    return f"https://financialmodelingprep.com/image-stock/{clean.replace('.', '-')}.png"


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
        "pos": "-",
        "name": name,
        "total": value.get("score", 0),
        "today": round_scores[0].get("displayValue") if round_scores else None,
        "thru": len(holes),
        "holes": [item.get("value") for item in holes[:18]],
    }


def _rank_golf_players(players: object) -> list[dict[str, object]]:
    """Assign competition ranks so equal totals share a tied position."""

    rows = [dict(value) for value in players if isinstance(value, Mapping)]
    totals = [str(row.get("total") or "").strip().upper() for row in rows]
    rank = 1
    index = 0
    while index < len(rows):
        total = totals[index]
        end = index + 1
        while end < len(rows) and totals[end] == total:
            end += 1
        group_size = end - index
        for row in rows[index:end]:
            row["pos"] = f"T{rank}" if group_size > 1 and total else str(rank) if total else "-"
        rank += group_size
        index = end
    return rows


def _airport_rows(value: object, counterpart: str) -> list[dict[str, object]]:
    values = value if isinstance(value, Sequence) and not isinstance(value, (str, bytes)) else ()
    rows: list[dict[str, object]] = []
    for flight in values[:4]:
        raw = _mapping(_mapping(flight).get("flight"))
        airline = _mapping(raw.get("airline"))
        code = _mapping(airline.get("code"))
        airport = _mapping(_mapping(raw.get("airport")).get(counterpart))
        airport_code = _mapping(airport.get("code"))
        airport_position = _mapping(airport.get("position"))
        airport_region = _mapping(airport_position.get("region"))
        identification = _mapping(raw.get("identification"))
        number = _mapping(identification.get("number"))
        rows.append(
            {
                "flight_number": str(number.get("default") or code.get("iata") or code.get("icao") or "---"),
                "airport_code": str(airport_code.get("iata") or "---"),
                "airport_city": str(airport_region.get("city") or airport.get("name") or "---"),
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


def _golf_round(status: str) -> str:
    """Return a stable golf round label when ESPN provides one."""

    match = re.search(r"\bround\s*(\d+)\b", status, re.IGNORECASE)
    return f"Round {match.group(1)}" if match else status


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
