"""Native live sources used by the production v2 composition."""

from __future__ import annotations

import os
import re
import json
import hashlib
from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta, timezone
from math import atan2, cos, isfinite, radians, sin, sqrt
from pathlib import Path
from threading import Lock, Thread
from time import monotonic, sleep, time
from typing import Any, Callable
from urllib.parse import urlencode

from sports_ticker.domain import DisplaySettings
from sports_ticker.markets import MARKET_GROUPS

from .espn import _display_timezone, _event_time
from .http import JsonHttpClient, UrllibJsonHttpClient


ESPN_GOLF_URL = "https://site.api.espn.com/apis/site/v2/sports/golf/pga/scoreboard"
FINNHUB_QUOTE_URL = "https://finnhub.io/api/v1/quote"
FINNHUB_CANDLE_URL = "https://finnhub.io/api/v1/stock/candle"
_ETF_LOGO_DOMAINS = {
    "QQQ": "invesco.com",
    "SPY": "spdrs.com",
    "IWM": "ishares.com",
    "DIA": "statestreet.com",
}

_KNOTS_TO_MPH = 1.15078
_EARTH_RADIUS_MILES = 3958.7613
_AIRLINE_DOMAINS = {
    "UA": "united.com",
    "UAL": "united.com",
    "DL": "delta.com",
    "DAL": "delta.com",
    "AA": "aa.com",
    "AAL": "aa.com",
    "WN": "southwest.com",
    "SWA": "southwest.com",
    "B6": "jetblue.com",
    "JBU": "jetblue.com",
    "AS": "alaskaair.com",
    "ASA": "alaskaair.com",
    "AC": "aircanada.com",
    "ACA": "aircanada.com",
    "BA": "britishairways.com",
    "BAW": "britishairways.com",
    "LH": "lufthansa.com",
    "DLH": "lufthansa.com",
    "AF": "airfrance.us",
    "AFR": "airfrance.us",
    "KL": "klm.com",
    "KLM": "klm.com",
    "EK": "emirates.com",
    "UAE": "emirates.com",
    "NK": "spirit.com",
    "NKS": "spirit.com",
    "F9": "flyfrontier.com",
    "FFT": "flyfrontier.com",
    "QR": "qatarairways.com",
    "QTR": "qatarairways.com",
    "SQ": "singaporeair.com",
    "SIA": "singaporeair.com",
    "VS": "virginatlantic.com",
    "VIR": "virginatlantic.com",
    "CX": "cathaypacific.com",
    "CPA": "cathaypacific.com",
    "JL": "jal.com",
    "JAL": "jal.com",
    "NH": "ana.co.jp",
    "ANA": "ana.co.jp",
}


class EspnGolfSource:
    """Read the PGA scoreboard directly from ESPN."""

    def __init__(
        self,
        client: JsonHttpClient | None = None,
        *,
        timeout: float = 10.0,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._client = client or UrllibJsonHttpClient()
        self._timeout = _timeout(timeout)
        self._now = now or (lambda: datetime.now(timezone.utc))
        self._cache_lock = Lock()
        self._cache: tuple[float, tuple[str, object], Mapping[str, object]] | None = None

    def fetch(self, settings: DisplaySettings) -> Mapping[str, object]:
        now = self._now()
        cache_key = (settings.timezone, now.astimezone(_display_timezone(settings.timezone)).date())
        monotonic_now = monotonic()
        with self._cache_lock:
            if self._cache is not None:
                cached_at, cached_key, cached_value = self._cache
                if cached_key == cache_key and 0 <= monotonic_now - cached_at < 5.0:
                    return cached_value

            payload = self._client.get_json(ESPN_GOLF_URL, timeout=self._timeout)
            event = _first_event(payload)
            if event is None or not _is_current_golf_event(event, timezone_name=settings.timezone, now=now):
                result: Mapping[str, object] = {"content": []}
            else:
                competition = _first_mapping(event.get("competitions"))
                players = [_golf_player(value) for value in _mappings(competition.get("competitors"))]
                players = _rank_golf_players(value for value in players if value is not None)
                status = _status(event, competition)
                result = {
                    "content": [
                        {
                            "id": f"golf:{event.get('id', 'pga')}",
                            "type": "golf",
                            "sport": "golf",
                            "state": status["state"],
                            "status": status["text"],
                            "away_abbr": str(event.get("shortName") or event.get("name") or "PGA TOUR"),
                            "golf": {
                                "brand": _golf_brand(str(event.get("name") or "")),
                                "event_name": str(event.get("name") or "PGA TOUR"),
                                "year": _mapping(event.get("season")).get("year", now.year),
                                "round": _golf_round(status["text"]),
                                "players": players,
                            },
                        }
                    ]
                }
            self._cache = (monotonic_now, cache_key, result)
            return result


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

    def __init__(self, api: object | None = None, *, clock: Callable[[], float] = time) -> None:
        self._api = api
        self._clock = clock

    def fetch(self, settings: DisplaySettings) -> Mapping[str, object]:
        api = self._client()
        now = float(self._clock())
        records: list[dict[str, object]] = []
        if settings.track_flight_id:
            flight = self._tracked_flight(api, settings, now=now)
            if flight is not None:
                records.append(flight)
        airport = self._airport_board(api, settings, now=now)
        if airport is not None:
            records.append(airport)
        return {
            "content": records,
            "observed_at": datetime.fromtimestamp(now, tz=timezone.utc).isoformat(),
        }

    def _client(self) -> object:
        if self._api is None:
            from FlightRadarAPI import FlightRadar24API

            self._api = FlightRadar24API()
        return self._api

    def _tracked_flight(
        self,
        api: object,
        settings: DisplaySettings,
        *,
        now: float,
    ) -> dict[str, object] | None:
        search = getattr(api, "search", None)
        if not callable(search):
            return None
        payload = search(settings.track_flight_id)
        candidate = _search_flight(payload, settings.track_flight_id)
        if candidate is None:
            return _pending_flight(settings)
        entry, detail = candidate
        detail = _merge_flight_details(detail, _fetch_flight_details(api, entry))
        return _tracked_flight_record(
            entry,
            detail,
            settings,
            now=now,
        )

    def _airport_board(
        self,
        api: object,
        settings: DisplaySettings,
        *,
        now: float,
    ) -> dict[str, object] | None:
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
            "weather": _airport_weather(result, settings, plugin_data, now=now),
            "arrivals": _airport_rows(
                _mapping(schedule.get("arrivals")).get("data"),
                "origin",
                "arriving",
                now=now,
            ),
            "departures": _airport_rows(
                _mapping(schedule.get("departures")).get("data"),
                "destination",
                "departing",
                now=now,
            ),
        }


class EspnNewsSource:
    """Read followed-team ESPN headlines without blocking scoreboard refreshes."""

    def __init__(
        self,
        news_urls: Mapping[str, str],
        client: JsonHttpClient | None = None,
        *,
        timeout: float = 10.0,
        refresh_seconds: float = 30.0,
        background: bool = True,
    ) -> None:
        self._news_urls = dict(news_urls)
        self._client = client or UrllibJsonHttpClient()
        self._timeout = _timeout(timeout)
        self._refresh_seconds = _timeout(refresh_seconds)
        self._background = bool(background)
        self._cache: dict[tuple[str, ...], tuple[dict[str, object], ...]] = {}
        self._last_started: dict[tuple[str, ...], float] = {}
        self._refreshing: set[tuple[str, ...]] = set()
        self._lock = Lock()

    def fetch(self, settings: DisplaySettings) -> Mapping[str, object]:
        """Return cached followed-team headlines and refresh them outside polling."""

        if settings.mode != "sports" or not settings.my_teams:
            return {"news": []}
        followed = tuple(sorted({str(value).strip().lower() for value in settings.my_teams if str(value).strip()}))
        if not followed:
            return {"news": []}
        if self._background:
            self._start_refresh(followed)
            with self._lock:
                return {"news": list(self._cache.get(followed, ())) }
        return {"news": list(self._fetch_news(followed))}

    def _start_refresh(self, followed: tuple[str, ...]) -> None:
        now = monotonic()
        with self._lock:
            if followed in self._refreshing or now - self._last_started.get(followed, float("-inf")) < self._refresh_seconds:
                return
            self._last_started[followed] = now
            self._refreshing.add(followed)
        Thread(target=self._refresh, args=(followed,), name="ticker-news-refresh", daemon=True).start()

    def _refresh(self, followed: tuple[str, ...]) -> None:
        try:
            records = self._fetch_news(followed)
            with self._lock:
                self._cache[followed] = records
        finally:
            with self._lock:
                self._refreshing.discard(followed)

    def _fetch_news(self, followed: tuple[str, ...]) -> tuple[dict[str, object], ...]:
        followed_set = set(followed)
        records: list[dict[str, object]] = []
        for league, url in self._news_urls.items():
            if not any(value.startswith(f"{league}:") for value in followed_set):
                continue
            try:
                payload = self._client.get_json(url, timeout=self._timeout)
            except Exception:
                continue
            articles = payload.get("articles", ()) if isinstance(payload, Mapping) else ()
            if not isinstance(articles, Sequence) or isinstance(articles, (str, bytes)):
                continue
            for article in articles:
                if not isinstance(article, Mapping):
                    continue
                headline = str(article.get("headline") or article.get("title") or "").strip()
                if not headline:
                    continue
                teams = tuple(
                    team
                    for team in _article_abbreviations(article)
                    if f"{league}:{team.lower()}" in followed_set
                )
                if not teams:
                    continue
                article_id = str(article.get("id") or article.get("link") or headline)
                identifier = hashlib.sha1(f"{league}:{article_id}".encode()).hexdigest()[:20]
                records.append(
                    {
                        "id": identifier,
                        "kind": "NEWS",
                        "domain": "sports",
                        "sport": league,
                        "from_abbr": teams[0],
                        "to_abbr": "",
                        "from_color": "#8B93A3",
                        "to_color": "#8B93A3",
                        "text": headline,
                        "teams": list(teams),
                    }
                )
        return tuple(records[:24])


def _article_abbreviations(article: Mapping[str, object]) -> tuple[str, ...]:
    """Collect explicit ESPN team abbreviations without guessing from prose."""

    values: set[str] = set()

    def visit(value: object) -> None:
        if isinstance(value, Mapping):
            for key, child in value.items():
                if str(key).lower() in {"abbreviation", "abbrev", "shortname", "short_name"}:
                    text = str(child or "").strip().upper()
                    if 2 <= len(text) <= 4 and text.isalnum():
                        values.add(text)
                visit(child)
        elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
            for child in value:
                visit(child)

    visit(article)
    return tuple(sorted(values))


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


def _search_flight(
    payload: object,
    requested: str,
) -> tuple[Mapping[str, Any], Mapping[str, Any]] | None:
    """Select the requested flight from one real-shaped FR24 search response."""

    values: list[Mapping[str, Any]] = []
    if isinstance(payload, Mapping):
        for key in ("live", "results", "flights", "data"):
            candidate = payload.get(key)
            if isinstance(candidate, Sequence) and not isinstance(candidate, (str, bytes)):
                values.extend(item for item in candidate if isinstance(item, Mapping))
        if not values and _looks_like_flight(payload):
            values.append(payload)
    elif isinstance(payload, Sequence) and not isinstance(payload, (str, bytes)):
        values.extend(item for item in payload if isinstance(item, Mapping))

    if not values:
        return None
    wanted = _compact(requested)
    wanted_parts = _flight_code_parts(wanted)
    ranked: list[tuple[int, int, Mapping[str, Any], Mapping[str, Any]]] = []
    for index, entry in enumerate(values):
        detail = _detail_mapping(entry)
        identifiers = _flight_identifiers(entry, detail)
        score = 1
        for identifier in identifiers:
            candidate = _compact(identifier)
            if not candidate:
                continue
            if candidate == wanted:
                score = max(score, 100)
            elif wanted and (candidate.endswith(wanted) or wanted.endswith(candidate)):
                score = max(score, 70)
            elif wanted_parts[1] and _same_flight_number(candidate, wanted):
                score = max(score, 30)
        ranked.append((score, -index, entry, detail))
    best = max(ranked, key=lambda item: (item[0], item[1]))
    if wanted and best[0] <= 1:
        return None
    _score, _order, entry, detail = best
    return entry, detail


def _fetch_flight_details(api: object, entry: Mapping[str, Any]) -> Mapping[str, Any]:
    """Augment search data with the SDK detail endpoint when the client exposes it."""

    getter = getattr(api, "get_flight_details", None)
    if not callable(getter):
        return {}
    attempts: list[object] = [entry]
    identifier = str(entry.get("id") or entry.get("flight_id") or "").strip()
    if identifier:
        attempts.extend((_FlightReference(identifier), identifier))
    for argument in attempts:
        try:
            result = getter(argument)
        except Exception:
            continue
        if isinstance(result, Mapping) and result:
            return _detail_mapping(result)
    return {}


class _FlightReference:
    """Provide the SDK's ``flight.id`` shape when search returns plain mappings."""

    __slots__ = ("id",)

    def __init__(self, identifier: str) -> None:
        self.id = identifier


def _merge_flight_details(
    search_detail: Mapping[str, Any],
    full_detail: Mapping[str, Any],
) -> Mapping[str, Any]:
    """Merge the search and detail envelopes while retaining nested source facts."""

    if not full_detail:
        return search_detail
    merged = dict(search_detail)
    for key, value in full_detail.items():
        if key == "detail":
            continue
        if isinstance(value, Mapping) and isinstance(merged.get(key), Mapping):
            nested = dict(merged[key])
            nested.update(value)
            merged[key] = nested
        else:
            merged[key] = value
    return merged


def _pending_flight(settings: DisplaySettings) -> dict[str, object]:
    """Return a complete visitor contract while FR24 has no matching live flight."""

    identifier = settings.track_flight_id or "flight_blank"
    guest = settings.track_guest_name or identifier
    airline_iata, airline_icao = _airline_codes_from_flight(identifier)
    return {
        "id": identifier,
        "type": "flight_visitor",
        "sport": "flight",
        "guest_name": guest,
        "route": "UNKNOWN > UNKNOWN",
        "origin_city": "UNKNOWN",
        "dest_city": "UNKNOWN",
        "origin_iata": "",
        "dest_iata": "",
        "origin_icao": "",
        "dest_icao": "",
        "alt": 0,
        "altitude_ft": 0,
        "dist": 0,
        "distance_miles": 0,
        "eta_str": "PENDING",
        "eta_timestamp": None,
        "speed": 0,
        "speed_mph": 0,
        "speed_kts": 0,
        "progress": 0,
        "progress_pct": 0,
        "status": "pending",
        "live_status": "Pending",
        "status_text": "Pending",
        "delay_min": 0,
        "delay_minutes": 0,
        "is_delayed": False,
        "is_live": False,
        "airline": airline_iata or airline_icao,
        "airline_name": "",
        "airline_code": airline_iata or airline_icao,
        "airline_iata": airline_iata,
        "airline_icao": airline_icao,
        "airline_logo": _airline_logo_url(airline_iata or airline_icao),
        "aircraft_type": "",
        "aircraft_model": "",
        "aircraft_code": "",
        "aircraft_registration": "",
        "registration": "",
        "source_updated_at": None,
        "updated_at": None,
        "is_shown": True,
    }


def _tracked_flight_record(
    entry: Mapping[str, Any],
    detail: Mapping[str, Any],
    settings: DisplaySettings,
    *,
    now: float,
) -> dict[str, object]:
    """Normalize one FR24 flight into the stable facts consumed by V2 clients."""

    source = dict(entry)
    source.update(detail)
    identification = _mapping(source.get("identification"))
    number = _mapping(identification.get("number"))
    flight_id = _first_text(
        source.get("flight"),
        source.get("callsign"),
        number.get("default"),
        number.get("alternative"),
        identification.get("callsign"),
        entry.get("id"),
        settings.track_flight_id,
    ) or settings.track_flight_id

    airline = _mapping(source.get("airline"))
    airline_code = _mapping(airline.get("code"))
    prefix, _flight_number = _flight_code_parts(_compact(flight_id))
    airline_iata = _first_text(
        airline_code.get("iata"),
        airline.get("iata"),
        source.get("airline_iata"),
    ).upper()
    airline_icao = _first_text(
        airline_code.get("icao"),
        airline.get("icao"),
        source.get("airline_icao"),
    ).upper()
    if not airline_iata and len(prefix) == 2:
        airline_iata = prefix
    if not airline_icao and len(prefix) == 3:
        airline_icao = prefix
    airline_name = _first_text(
        airline.get("name"),
        airline.get("short"),
        source.get("operator"),
        source.get("airline_name"),
    )

    origin = _airport_info(source, "origin")
    destination = _airport_info(source, "destination")
    origin_iata = origin["iata"] or _first_text(source.get("schd_from"), source.get("orig_iata"), source.get("origin_iata")).upper()
    destination_iata = destination["iata"] or _first_text(source.get("schd_to"), source.get("dest_iata"), source.get("destination_iata")).upper()
    origin_icao = origin["icao"] or _first_text(source.get("orig_icao"), source.get("origin_icao")).upper()
    destination_icao = destination["icao"] or _first_text(source.get("dest_icao"), source.get("destination_icao")).upper()
    origin_city = origin["city"] or origin_iata or "UNKNOWN"
    destination_city = destination["city"] or destination_iata or "UNKNOWN"

    position = _flight_position(source)
    altitude = max(0, _integer(position.get("altitude")))
    speed_kts = max(0.0, _number(position.get("speed_kts")))
    speed_mph = max(0, int(round(speed_kts * _KNOTS_TO_MPH)))
    status_text, state, source_live = _flight_status(source, altitude, bool(position.get("on_ground")))
    times = _flight_times(source)
    delay_min = _delay_minutes(times)
    is_delayed = delay_min >= 15 or "delay" in status_text.casefold()
    live = bool(source_live or (altitude > 0 and state not in {"landed", "arrived"}))
    if is_delayed:
        status = "delayed"
    elif state in {"scheduled", "boarding", "canceled", "cancelled", "diverted", "landed", "arrived"}:
        status = state
    else:
        status = "en-route" if live else state

    latitude, longitude = position.get("latitude"), position.get("longitude")
    remaining = _source_distance(source, "remaining")
    total_distance = _distance_miles(origin.get("latitude"), origin.get("longitude"), destination.get("latitude"), destination.get("longitude"))
    if remaining is None and live:
        remaining = _distance_miles(latitude, longitude, destination.get("latitude"), destination.get("longitude"))
    distance = max(0, int(round(remaining or 0)))
    progress = _source_progress(source)
    if progress is None and total_distance > 0 and remaining is not None:
        progress = (1.0 - (remaining / total_distance)) * 100.0
    progress_value = max(0, min(100, int(round(progress or 0)))) if live else 0

    eta_timestamp = times.get("estimated_arrival") or times.get("actual_arrival")
    if eta_timestamp is None and live and distance and speed_mph:
        eta_timestamp = now + distance / speed_mph * 3600
    eta_str = _eta_text(eta_timestamp, now, distance, speed_mph, live, state)
    updated_timestamp = position.get("timestamp") or _timestamp(
        source.get("updated_at") or source.get("last_updated") or source.get("timestamp")
    ) or now

    aircraft = _mapping(source.get("aircraft"))
    aircraft_model = _mapping(aircraft.get("model"))
    aircraft_code = _first_text(
        aircraft_model.get("code"),
        aircraft.get("code"),
        source.get("aircraft_code"),
        source.get("ac_type"),
    )
    aircraft_name = _first_text(
        aircraft_model.get("text"),
        aircraft_model.get("name"),
        source.get("aircraft_model"),
        source.get("aircraft_type"),
        aircraft_code,
    )
    registration = _first_text(
        aircraft.get("registration"),
        source.get("registration"),
        source.get("reg"),
    )
    logo_code = airline_iata or airline_icao or prefix
    return {
        "id": flight_id,
        "type": "flight_visitor",
        "sport": "flight",
        "guest_name": settings.track_guest_name or flight_id,
        "route": f"{origin_iata or origin_city} > {destination_iata or destination_city}",
        "origin_city": origin_city,
        "dest_city": destination_city,
        "origin_iata": origin_iata,
        "dest_iata": destination_iata,
        "origin_icao": origin_icao,
        "dest_icao": destination_icao,
        "alt": altitude,
        "altitude_ft": altitude,
        "dist": distance,
        "distance_miles": distance,
        "total_distance_miles": max(0, int(round(total_distance))),
        "eta_str": eta_str,
        "eta_timestamp": eta_timestamp,
        "speed": speed_mph,
        "speed_mph": speed_mph,
        "speed_kts": round(speed_kts, 1),
        "progress": progress_value,
        "progress_pct": progress_value,
        "status": status,
        "live_status": status_text or status,
        "status_text": status_text or status,
        "delay_min": delay_min,
        "delay_minutes": delay_min,
        "is_delayed": is_delayed,
        "is_live": live,
        "airline": airline_iata or airline_icao or airline_name,
        "airline_name": airline_name,
        "airline_code": logo_code,
        "airline_iata": airline_iata,
        "airline_icao": airline_icao,
        "airline_logo": _airline_logo_url(logo_code),
        "aircraft_type": aircraft_name,
        "aircraft_model": aircraft_name,
        "aircraft_code": aircraft_code,
        "aircraft_registration": registration,
        "registration": registration,
        "source_updated_at": _iso_timestamp(updated_timestamp),
        "updated_at": _iso_timestamp(updated_timestamp),
        "is_shown": True,
    }


def _airport_rows(
    value: object,
    counterpart: str,
    state: str = "",
    *,
    now: float | None = None,
) -> list[dict[str, object]]:
    """Normalize one FR24 arrivals or departures schedule side."""

    values = value if isinstance(value, Sequence) and not isinstance(value, (str, bytes)) else ()
    rows: list[dict[str, object]] = []
    for flight in values[:4]:
        wrapper = _mapping(flight)
        raw = _mapping(wrapper.get("flight")) or wrapper
        origin = _airport_info(raw, "origin")
        destination = _airport_info(raw, "destination")
        selected = origin if counterpart == "origin" else destination
        identification = _mapping(raw.get("identification"))
        number = _mapping(identification.get("number"))
        display_number = _first_text(
            number.get("default"),
            number.get("alternative"),
            identification.get("callsign"),
            raw.get("flight"),
            raw.get("number"),
        )
        airline = _mapping(raw.get("airline"))
        airline_code = _mapping(airline.get("code"))
        airline_iata = _first_text(airline_code.get("iata"), airline.get("iata")).upper()
        airline_icao = _first_text(airline_code.get("icao"), airline.get("icao")).upper()
        if not display_number:
            display_number = airline_iata or airline_icao or "---"
        position = _flight_position(raw)
        times = _flight_times(raw)
        scheduled = times.get("scheduled_arrival" if counterpart == "origin" else "scheduled_departure")
        estimated = times.get("estimated_arrival" if counterpart == "origin" else "estimated_departure")
        actual = times.get("actual_arrival" if counterpart == "origin" else "actual_departure")
        event_timestamp = actual or estimated or scheduled
        status_text, row_state = _schedule_status(raw, state)
        delay_min = _delay_minutes(times, lifecycle=state, counterpart=counterpart)
        source_updated = position.get("timestamp") or event_timestamp
        if source_updated is None and now is not None:
            source_updated = now
        rows.append(
            {
                "flight_number": display_number,
                "airport_code": selected["iata"] or selected["icao"] or "---",
                "airport_city": selected["city"] or selected["name"] or "---",
                "origin_iata": origin["iata"],
                "destination_iata": destination["iata"],
                "origin_city": origin["city"] or origin["iata"],
                "destination_city": destination["city"] or destination["iata"],
                "airline": airline_iata or airline_icao or _first_text(airline.get("name")),
                "airline_name": _first_text(airline.get("name"), airline.get("short")),
                "airline_iata": airline_iata,
                "airline_icao": airline_icao,
                "airline_logo": _airline_logo_url(airline_iata or airline_icao),
                "status": status_text,
                "status_label": status_text,
                "state": row_state,
                "is_delayed": delay_min >= 15 or "delay" in status_text.casefold(),
                "delay_min": delay_min,
                "delay_minutes": delay_min,
                "scheduled_timestamp": scheduled,
                "estimated_timestamp": estimated,
                "actual_timestamp": actual,
                "scheduled_at": _iso_timestamp(scheduled),
                "estimated_at": _iso_timestamp(estimated),
                "actual_at": _iso_timestamp(actual),
                "altitude_ft": max(0, _integer(position.get("altitude"))),
                "is_live": bool(position.get("altitude") or position.get("live")),
                "aircraft_type": _aircraft_label(raw),
                "aircraft_code": _aircraft_code(raw),
                "gate": _first_text(raw.get("gate"), _mapping(raw.get("airport")).get("gate")),
                "terminal": _first_text(raw.get("terminal"), _mapping(raw.get("airport")).get("terminal")),
                "source_updated_at": _iso_timestamp(source_updated),
                "is_shown": True,
            }
        )
    return rows


def _looks_like_flight(value: Mapping[str, Any]) -> bool:
    """Identify one search result mapping without requiring a fixed SDK class."""

    keys = {str(key).strip().lower() for key in value}
    return bool(keys & {"id", "flight", "callsign", "identification", "aircraft", "airport"})


def _detail_mapping(value: object) -> dict[str, Any]:
    """Flatten an FR24 result's optional ``detail`` envelope."""

    if not isinstance(value, Mapping):
        return {}
    detail = _mapping(value.get("detail"))
    flattened = {str(key): item for key, item in value.items() if key != "detail"}
    flattened.update(detail)
    return flattened


def _flight_identifiers(*values: Mapping[str, Any]) -> tuple[str, ...]:
    """Return every flight identifier exposed by search and detail responses."""

    identifiers: list[str] = []
    for value in values:
        identification = _mapping(value.get("identification"))
        number = _mapping(identification.get("number"))
        for candidate in (
            value.get("flight"),
            value.get("callsign"),
            value.get("number"),
            number.get("default"),
            number.get("alternative"),
            identification.get("callsign"),
        ):
            text = _first_text(candidate)
            if text and text not in identifiers:
                identifiers.append(text)
    return tuple(identifiers)


def _compact(value: object) -> str:
    """Normalize a flight code for exact comparisons."""

    return "".join(character for character in str(value or "").upper() if character.isalnum())


def _flight_code_parts(value: str) -> tuple[str, str]:
    """Split a two or three letter flight designator from its number."""

    text = _compact(value)
    if not text:
        return "", ""
    if len(text) >= 3 and text[1].isdigit() and text[0].isalpha():
        return text[:2], text[2:].lstrip("0") or "0"
    match = re.match(r"^([A-Z]{1,3})(\d+)$", text)
    if match is None:
        return "", ""
    return match.group(1), match.group(2).lstrip("0") or "0"


def _same_flight_number(candidate: str, requested: str) -> bool:
    """Match one flight number across equivalent IATA and ICAO designators."""

    candidate_prefix, candidate_number = _flight_code_parts(candidate)
    requested_prefix, requested_number = _flight_code_parts(requested)
    if not candidate_number or candidate_number != requested_number:
        return False
    if not candidate_prefix or not requested_prefix:
        return False
    if candidate_prefix == requested_prefix:
        return True
    candidate_codes = set(_airline_codes_from_flight(candidate))
    requested_codes = set(_airline_codes_from_flight(requested))
    if candidate_codes & requested_codes:
        return True
    return (
        len(candidate_prefix) != len(requested_prefix)
        and candidate_prefix[:2] == requested_prefix[:2]
    )


def _airline_codes_from_flight(value: object) -> tuple[str, str]:
    """Infer IATA and ICAO carrier codes when FR24 omits the airline block."""

    prefix, _number = _flight_code_parts(_compact(value))
    pairs = {
        "UA": "UAL",
        "DL": "DAL",
        "AA": "AAL",
        "WN": "SWA",
        "B6": "JBU",
        "AS": "ASA",
        "AC": "ACA",
        "BA": "BAW",
        "LH": "DLH",
        "AF": "AFR",
        "KL": "KLM",
        "EK": "UAE",
        "NK": "NKS",
        "F9": "FFT",
        "QR": "QTR",
        "SQ": "SIA",
        "VS": "VIR",
        "CX": "CPA",
        "JL": "JAL",
        "NH": "ANA",
    }
    if len(prefix) == 2:
        return prefix, pairs.get(prefix, "")
    if len(prefix) == 3:
        iata = next((key for key, icao in pairs.items() if icao == prefix), "")
        return iata, prefix
    return "", ""


def _airline_logo_url(code: object) -> str:
    """Return the same cacheable favicon URL used by the Pi asset planner."""

    clean = _compact(code)
    if not clean:
        return ""
    domain = _AIRLINE_DOMAINS.get(clean, f"{clean.lower()}.com")
    return f"https://www.google.com/s2/favicons?domain={domain}&sz=64"


def _airport_info(source: Mapping[str, Any], role: str) -> dict[str, Any]:
    """Extract one airport's codes, city, and coordinates from a FR24 record."""

    airports = _mapping(source.get("airport"))
    block = _mapping(airports.get(role))
    if not block and isinstance(source.get(role), Mapping):
        block = _mapping(source.get(role))
    code = _mapping(block.get("code"))
    code_value = block.get("code") if not isinstance(block.get("code"), Mapping) else ""
    position = _mapping(block.get("position"))
    region = _mapping(position.get("region")) or _mapping(block.get("region"))
    if not region:
        region = _mapping(block.get("location"))
    prefix = "orig" if role == "origin" else "dest"
    scheduled_code = "schd_from" if role == "origin" else "schd_to"
    iata = _first_text(
        code.get("iata"),
        code_value if len(_compact(code_value)) == 3 else "",
        block.get("iata"),
        source.get(f"{prefix}_iata"),
        source.get(f"{role}_iata"),
        source.get(scheduled_code),
        source.get(role) if not isinstance(source.get(role), Mapping) else "",
    ).upper()
    icao = _first_text(
        code.get("icao"),
        block.get("icao"),
        source.get(f"{prefix}_icao"),
        source.get(f"{role}_icao"),
    ).upper()
    city = _first_text(
        region.get("city"),
        region.get("name"),
        block.get("city"),
        block.get("municipality"),
    )
    name = _first_text(block.get("name"), city, iata, icao)
    latitude = _number_first(
        position.get("latitude"),
        position.get("lat"),
        block.get("latitude"),
        block.get("lat"),
    )
    longitude = _number_first(
        position.get("longitude"),
        position.get("lon"),
        position.get("lng"),
        block.get("longitude"),
        block.get("lon"),
        block.get("lng"),
    )
    return {
        "iata": iata,
        "icao": icao,
        "city": city,
        "name": name,
        "latitude": latitude,
        "longitude": longitude,
    }


def _flight_position(source: Mapping[str, Any]) -> dict[str, Any]:
    """Read the newest position and motion values from FR24 search details."""

    point: Mapping[str, Any] = {}
    trail = source.get("trail")
    if isinstance(trail, Sequence) and not isinstance(trail, (str, bytes)):
        point = next((item for item in trail if isinstance(item, Mapping)), {})
    if not point:
        point = _mapping(source.get("position"))
    altitude = _number_first(
        point.get("alt"),
        point.get("altitude"),
        point.get("altitude_ft"),
        source.get("alt"),
        source.get("altitude"),
        source.get("altitude_ft"),
    ) or 0.0
    speed_kts = _number_first(
        point.get("spd"),
        point.get("speed_kts"),
        point.get("ground_speed"),
        source.get("spd"),
        source.get("speed_kts"),
        source.get("ground_speed"),
    )
    if speed_kts <= 0:
        speed_mph = _number_first(point.get("speed_mph"), source.get("speed_mph"))
        speed_kts = speed_mph / _KNOTS_TO_MPH if speed_mph > 0 else 0.0
    latitude = _number_first(point.get("lat"), point.get("latitude"), source.get("lat"), source.get("latitude"))
    longitude = _number_first(
        point.get("lng"),
        point.get("lon"),
        point.get("longitude"),
        source.get("lng"),
        source.get("lon"),
        source.get("longitude"),
    )
    timestamp = _timestamp(
        point.get("ts") or point.get("timestamp") or point.get("time")
        or source.get("updated_at") or source.get("last_updated") or source.get("timestamp")
    )
    on_ground = _boolean(point.get("on_ground"), source.get("on_ground"))
    live = _boolean(point.get("live"), source.get("live"))
    return {
        "altitude": altitude,
        "speed_kts": speed_kts,
        "latitude": latitude,
        "longitude": longitude,
        "timestamp": timestamp,
        "on_ground": on_ground,
        "live": live,
    }


def _flight_status(
    source: Mapping[str, Any],
    altitude: int,
    on_ground: bool,
) -> tuple[str, str, bool]:
    """Normalize FR24 status text, lifecycle state, and live marker."""

    status = _mapping(source.get("status"))
    generic = _mapping(status.get("generic"))
    generic_status = _mapping(generic.get("status"))
    text = _first_text(
        status.get("text"),
        status.get("description"),
        status.get("status"),
        generic_status.get("text"),
        source.get("status_text"),
        source.get("statusText"),
    )
    explicit_state = _first_text(
        status.get("state"),
        generic_status.get("type"),
        generic_status.get("state"),
        source.get("state"),
    )
    state = _state_from_text(explicit_state or text)
    live = _boolean(status.get("live"), source.get("live"))
    if not state:
        state = "en-route" if live or altitude > 0 else "scheduled"
    if state in {"landed", "arrived", "canceled", "cancelled", "diverted"}:
        live = False
    elif altitude > 0 and not on_ground:
        live = True
    if not text:
        text = {
            "en-route": "En route",
            "scheduled": "Scheduled",
            "landed": "Landed",
            "arrived": "Arrived",
        }.get(state, state.replace("-", " ").title())
    return text, state, live


def _state_from_text(value: object) -> str:
    """Map source status text into an explicit flight lifecycle state."""

    text = str(value or "").strip().casefold()
    if not text:
        return ""
    if any(token in text for token in ("cancel", "canceled", "cancelled", "no flight")):
        return "canceled"
    if "divert" in text:
        return "diverted"
    if "landed" in text or "touchdown" in text:
        return "landed"
    if "landing" in text:
        return "landing"
    if "arrived" in text:
        return "arrived"
    if "arriving" in text or "on approach" in text:
        return "arriving"
    if any(token in text for token in ("delay", "late")):
        return "delayed"
    if any(token in text for token in ("en route", "en-route", "airborne", "in flight", "cruise", "live")):
        return "en-route"
    if any(token in text for token in ("boarding", "gate")):
        return "boarding"
    if "departed" in text or "left gate" in text:
        return "departed"
    if any(token in text for token in ("depart", "taxi")):
        return "departing"
    if any(token in text for token in ("scheduled", "estimated", "not started", "unknown")):
        return "scheduled"
    return text.replace(" ", "-")


def _flight_times(source: Mapping[str, Any]) -> dict[str, float | None]:
    """Read scheduled, estimated, and actual timestamps from a FR24 record."""

    time_info = _mapping(source.get("time"))

    def value(*buckets: str, keys: tuple[str, ...]) -> float | None:
        for bucket in buckets:
            block = _mapping(time_info.get(bucket))
            for key in keys:
                timestamp = _timestamp(block.get(key))
                if timestamp is not None:
                    return timestamp
        return None

    result: dict[str, float | None] = {
        "scheduled_departure": value("scheduled", keys=("departure", "depart")) or _timestamp(source.get("scheduled_departure")),
        "scheduled_arrival": value("scheduled", keys=("arrival", "arrive")) or _timestamp(source.get("scheduled_arrival")),
        "estimated_departure": value("estimated", "real", keys=("departure", "depart")) or _timestamp(source.get("estimated_departure")),
        "estimated_arrival": value("estimated", "real", keys=("arrival", "arrive")) or _timestamp(source.get("estimated_arrival") or source.get("est_arr")),
        "actual_departure": value("actual", "real", keys=("departure", "depart")) or _timestamp(source.get("actual_departure")),
        "actual_arrival": value("actual", "real", keys=("arrival", "arrive")) or _timestamp(source.get("actual_arrival")),
    }
    explicit_delay = _number_first(source.get("delay_min"), source.get("delay_minutes"), source.get("delay"))
    result["explicit_delay"] = explicit_delay if explicit_delay > 0 else None
    return result


def _delay_minutes(
    times: Mapping[str, float | None],
    *,
    counterpart: str | None = None,
    lifecycle: str | None = None,
) -> int:
    """Compute a nonnegative delay from scheduled and estimated source times."""

    lifecycle_name = str(lifecycle or "").strip().casefold()
    if lifecycle_name in {"arriving", "arrival", "landing", "landed", "arrived"}:
        pairs = (("scheduled_arrival", "estimated_arrival"), ("scheduled_arrival", "actual_arrival"))
    elif lifecycle_name in {"departing", "departure", "boarding", "departed"}:
        pairs = (("scheduled_departure", "estimated_departure"), ("scheduled_departure", "actual_departure"))
    elif counterpart == "origin":
        pairs = (("scheduled_departure", "estimated_departure"), ("scheduled_departure", "actual_departure"))
    elif counterpart == "destination":
        pairs = (("scheduled_arrival", "estimated_arrival"), ("scheduled_arrival", "actual_arrival"))
    else:
        pairs = (
            ("scheduled_arrival", "estimated_arrival"),
            ("scheduled_arrival", "actual_arrival"),
            ("scheduled_departure", "estimated_departure"),
            ("scheduled_departure", "actual_departure"),
        )
    for scheduled_key, actual_key in pairs:
        scheduled = times.get(scheduled_key)
        actual = times.get(actual_key)
        if scheduled is not None and actual is not None:
            return max(0, int((actual - scheduled) / 60))
    return max(0, _integer(times.get("explicit_delay")))


def _source_distance(source: Mapping[str, Any], kind: str) -> float | None:
    """Read an explicit remaining distance when FR24 provides one."""

    keys = {
        "remaining": ("distance_remaining", "remaining_distance", "distance_to_destination", "dist"),
        "total": ("total_distance", "route_distance"),
    }.get(kind, ())
    for key in keys:
        value = source.get(key)
        if isinstance(value, Mapping):
            value = _first_text(value.get("miles"), value.get("mi"), value.get("remaining"), value.get("value"))
        number = _number_optional(value)
        if number is not None and number > 0:
            return number
    distance = _mapping(source.get("distance"))
    if distance:
        value = _first_text(distance.get("miles"), distance.get("mi"), distance.get("remaining"), distance.get("value"))
        number = _number_optional(value)
        if number is not None and number > 0:
            return number
    return None


def _source_progress(source: Mapping[str, Any]) -> float | None:
    """Read an explicit route progress percentage when supplied by FR24."""

    for key in ("progress", "progress_pct", "progress_percent", "route_progress"):
        value = source.get(key)
        if isinstance(value, Mapping):
            value = _first_text(value.get("percent"), value.get("percentage"), value.get("value"))
        number = _number_optional(value)
        if number is not None and number >= 0:
            return number
    return None


def _distance_miles(
    latitude_a: object,
    longitude_a: object,
    latitude_b: object,
    longitude_b: object,
) -> float:
    """Return a great-circle distance in statute miles."""

    values = tuple(_number_optional(value) for value in (latitude_a, longitude_a, latitude_b, longitude_b))
    if any(value is None for value in values):
        return 0.0
    lat_a, lon_a, lat_b, lon_b = values
    assert lat_a is not None and lon_a is not None and lat_b is not None and lon_b is not None
    if not all(isfinite(value) for value in (lat_a, lon_a, lat_b, lon_b)):
        return 0.0
    if abs(lat_a) > 90 or abs(lat_b) > 90 or abs(lon_a) > 180 or abs(lon_b) > 180:
        return 0.0
    lat_delta = radians(lat_b - lat_a)
    lon_delta = radians(lon_b - lon_a)
    a = sin(lat_delta / 2) ** 2 + cos(radians(lat_a)) * cos(radians(lat_b)) * sin(lon_delta / 2) ** 2
    return 2 * _EARTH_RADIUS_MILES * atan2(sqrt(max(0.0, a)), sqrt(max(0.0, 1 - a)))


def _eta_text(
    eta_timestamp: float | None,
    now: float,
    distance: int,
    speed_mph: int,
    live: bool,
    state: str,
) -> str:
    """Format a compact ETA string for the 384x32 visitor panel."""

    if not live:
        if state in {"landed", "arrived"}:
            return "LANDED"
        if state in {"canceled", "cancelled"}:
            return "CANCELED"
        return "SCHEDULED"
    if eta_timestamp is not None:
        remaining_seconds = eta_timestamp - now
        if remaining_seconds <= 0:
            return "LANDING"
        return _format_duration(remaining_seconds)
    if distance > 0 and speed_mph > 0:
        return _format_duration(distance / speed_mph * 3600)
    return "EN ROUTE"


def _format_duration(seconds: float) -> str:
    """Format seconds as the established compact hour and minute label."""

    minutes = max(0, int(seconds // 60))
    hours, minutes = divmod(minutes, 60)
    return f"{hours}H {minutes}M" if hours else f"{minutes} MIN"


def _schedule_status(source: Mapping[str, Any], default: str) -> tuple[str, str]:
    """Return a useful board label and lifecycle state for one schedule row."""

    status = _mapping(source.get("status"))
    generic = _mapping(status.get("generic"))
    generic_status = _mapping(generic.get("status"))
    text = _first_text(
        status.get("text"),
        status.get("description"),
        status.get("status"),
        generic_status.get("text"),
        source.get("status_text"),
    )
    state = _state_from_text(text)
    if not state:
        state = default
    label = text.upper() if text else default.upper()
    return label, state


def _aircraft_code(source: Mapping[str, Any]) -> str:
    """Read one aircraft ICAO type code from a flight record."""

    aircraft = _mapping(source.get("aircraft"))
    model = _mapping(aircraft.get("model"))
    return _first_text(model.get("code"), aircraft.get("code"), source.get("aircraft_code"), source.get("ac_type"))


def _aircraft_label(source: Mapping[str, Any]) -> str:
    """Read a human aircraft model label with a code fallback."""

    aircraft = _mapping(source.get("aircraft"))
    model = _mapping(aircraft.get("model"))
    return _first_text(model.get("text"), model.get("name"), source.get("aircraft_model"), source.get("aircraft_type"), _aircraft_code(source))


def _first_text(*values: object) -> str:
    """Return the first nonempty scalar text value."""

    for value in values:
        if isinstance(value, Mapping) or value is None or isinstance(value, bool):
            continue
        text = str(value).strip()
        if text:
            return text
    return ""


def _number_first(*values: object) -> float:
    """Return the first finite numeric value."""

    for value in values:
        number = _number_optional(value)
        if number is not None and isfinite(number):
            return number
    return 0.0


def _number_optional(value: object) -> float | None:
    """Parse one optional numeric source value without treating missing data as zero."""

    if value is None or isinstance(value, bool) or isinstance(value, Mapping):
        return None
    if isinstance(value, str) and not value.strip():
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if isfinite(number) else None


def _integer(value: object) -> int:
    """Convert one source number to a stable integer."""

    return int(round(_number(value))) if isfinite(_number(value)) else 0


def _boolean(*values: object) -> bool:
    """Read the first explicit boolean-like source value."""

    for value in values:
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)) and isfinite(float(value)):
            return bool(value)
        text = str(value or "").strip().casefold()
        if text in {"true", "yes", "on", "1", "live"}:
            return True
        if text in {"false", "no", "off", "0", "ground", "landed"}:
            return False
    return False


def _timestamp(value: object) -> float | None:
    """Parse FR24 Unix, ISO, or nested timestamp values."""

    if isinstance(value, Mapping):
        for key in ("utc", "unix", "time", "timestamp", "value", "local", "iso"):
            if key in value:
                return _timestamp(value[key])
        return None
    if isinstance(value, datetime):
        current = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        return current.timestamp()
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            numeric = float(text)
        except ValueError:
            try:
                parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
            except ValueError:
                return None
            current = parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
            return current.timestamp()
        value = numeric
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if not isfinite(numeric) or numeric <= 0:
        return None
    if numeric > 100_000_000_000:
        numeric /= 1000
    return numeric


def _iso_timestamp(value: object) -> str | None:
    """Serialize one Unix timestamp for the V2 JSON contract."""

    timestamp = _timestamp(value)
    if timestamp is None:
        return None
    return datetime.fromtimestamp(timestamp, tz=timezone.utc).isoformat()


def _airport_weather(
    result: Mapping[str, Any],
    settings: DisplaySettings,
    plugin_data: Mapping[str, Any],
    *,
    now: float,
) -> dict[str, object]:
    """Normalize weather and airport identity from an FR24 airport response."""

    airport = _mapping(result.get("airport"))
    details = _mapping(plugin_data.get("details"))
    identity = dict(airport)
    identity.update(details)
    weather_candidates = (
        _mapping(plugin_data.get("weather")),
        _mapping(plugin_data.get("currentWeather")),
        _mapping(plugin_data.get("current_weather")),
        _mapping(airport.get("weather")),
        _mapping(result.get("weather")),
    )
    weather: dict[str, Any] = {}
    for candidate in weather_candidates:
        if candidate:
            weather.update(candidate)
            break
    current = _mapping(weather.get("current"))
    if not current:
        current = _mapping(weather.get("data"))
    if current:
        merged = dict(weather)
        merged.update(current)
        weather = merged
    code_value = identity.get("code")
    code = _mapping(code_value)
    position = _mapping(identity.get("position"))
    region = _mapping(position.get("region")) or _mapping(identity.get("region"))
    city = _first_text(
        region.get("city"),
        region.get("name"),
        identity.get("city"),
        settings.airport_name,
    )
    iata = _first_text(
        code.get("iata"),
        identity.get("iata"),
        code_value if len(_compact(code_value)) == 3 else "",
        settings.airport_code_iata,
    ).upper()
    icao = _first_text(
        code.get("icao"),
        identity.get("icao"),
        code_value if len(_compact(code_value)) == 4 else "",
        settings.airport_code_icao,
    ).upper()
    temp = _mapping(weather.get("temp"))
    temperature_f = _number_optional(temp.get("fahrenheit"))
    temperature_c = _number_optional(temp.get("celsius"))
    temperature_f = _number_optional(
        weather.get("temperature_f"),
    ) or temperature_f
    if temperature_f is None:
        temperature_f = _number_optional(weather.get("temp_f"))
    if temperature_f is None:
        temperature_f = _number_optional(weather.get("temperature"),)
    if temperature_f is None:
        temperature_f = _number_optional(weather.get("temp"))
    if temperature_f is None:
        temperature_c = temperature_c or _number_optional(weather.get("temperature_c"))
        if temperature_c is None:
            temperature_c = _number_optional(weather.get("temp_c"))
        if temperature_c is not None:
            temperature_f = temperature_c * 9 / 5 + 32
    raw_temperature = (
        temp.get("fahrenheit")
        or temp.get("celsius")
        or weather.get("temperature_f")
        or weather.get("temp_f")
        or weather.get("temperature")
        or weather.get("temp")
    )
    temperature = _temperature_text(
        temperature_f,
        raw_temperature,
    )
    sky = _mapping(weather.get("sky"))
    condition_value = weather.get("condition")
    sky_condition = _mapping(sky.get("condition"))
    condition = _first_text(
        sky_condition.get("text"),
        sky_condition.get("description"),
        _mapping(condition_value).get("text"),
        _mapping(condition_value).get("description"),
        condition_value,
        weather.get("cond"),
        weather.get("description"),
        weather.get("summary"),
        weather.get("icon"),
    )
    condition = condition.upper() if condition else "WEATHER UNAVAILABLE"
    wind = _mapping(weather.get("wind"))
    wind_speed = _mapping(wind.get("speed"))
    wind_mph = _number_optional(wind_speed.get("mph"))
    if wind_mph is None:
        wind_mph = _number_optional(weather.get("wind_mph"))
    observed = _timestamp(
        weather.get("time")
        or weather.get("cached")
        or weather.get("updated_at")
        or weather.get("timestamp")
    ) or now
    return {
        "iata": iata,
        "icao": icao,
        "home_abbr": iata or icao,
        "city": city,
        "airport_name": _first_text(identity.get("name"), settings.airport_name),
        "away_abbr": temperature,
        "temperature_f": temperature_f,
        "status": condition,
        "condition": condition,
        "weather_code": weather.get("code") or weather.get("weather_code"),
        "wind_mph": wind_mph,
        "humidity": _number_optional(weather.get("humidity")),
        "observed_at": _iso_timestamp(observed),
    }


def _temperature_text(value: float | None, raw: object) -> str:
    """Return a compact Fahrenheit temperature label for the airport header."""

    text = _first_text(raw)
    if text and any(symbol in text.upper() for symbol in ("F", "C", "°")):
        return text.upper().replace("°", "")
    if value is None:
        return "--"
    return f"{int(round(value))}F"


def _first_event(payload: object) -> Mapping[str, Any] | None:
    return _mappings(_mapping(payload).get("events"))[0] if _mappings(_mapping(payload).get("events")) else None


def _status(event: Mapping[str, Any], competition: Mapping[str, Any]) -> dict[str, str]:
    source = _mapping(competition.get("status")) or _mapping(event.get("status"))
    kind = _mapping(source.get("type"))
    return {
        "state": str(kind.get("state") or "pre").lower(),
        "text": str(kind.get("shortDetail") or kind.get("detail") or kind.get("description") or "Scheduled"),
    }


def _is_current_golf_event(
    event: Mapping[str, Any],
    *,
    timezone_name: str = "",
    now: datetime | None = None,
) -> bool:
    """Return True if one golf event is live or scheduled for the active local day."""

    source = _first_mapping(event.get("competitions")) or event
    status = _mapping(source.get("status")) or _mapping(event.get("status"))
    kind = _mapping(status.get("type"))
    state = str(kind.get("state") or "pre").strip().lower()
    if state in {"in", "half", "crit"}:
        return True

    starts_at = _event_time(event.get("date") or source.get("date"))
    if starts_at is None:
        return False
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    tz = _display_timezone(timezone_name)
    local_now = current.astimezone(tz)
    local_start = starts_at.astimezone(tz)
    current_date = (local_now - timedelta(days=1)).date() if local_now.hour < 3 else local_now.date()

    if state == "pre":
        return current_date >= local_start.date()

    ends_at = _event_time(event.get("endDate") or source.get("endDate")) or starts_at
    local_end = ends_at.astimezone(tz)
    return local_start.date() <= current_date <= local_end.date()


def _golf_round(status: str) -> str:
    """Return a stable golf round label when ESPN provides one."""

    match = re.search(r"\bround\s*(\d+)\b", status, re.IGNORECASE)
    return f"Round {match.group(1)}" if match else status


def _golf_brand(event_name: str) -> str:
    """Return the explicit golf palette brand for one source event."""

    return "masters" if "masters" in event_name.casefold() else "pga"


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
    "EspnNewsSource",
    "ClockProvider",
    "EspnGolfSource",
    "FinnhubStockSource",
    "FlightRadarSource",
]
