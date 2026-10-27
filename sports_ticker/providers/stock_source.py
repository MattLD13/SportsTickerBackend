"""Read live stock content through an injected source."""
from __future__ import annotations

import os
import json
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from math import isfinite
from pathlib import Path
from threading import Lock, Thread
from time import monotonic, sleep, time
from urllib.parse import urlencode
from sports_ticker.domain import DisplaySettings
from sports_ticker.markets import MARKET_GROUPS
from .background import BackgroundTask
from .http import JsonHttpClient, OwnedClient, PooledJsonHttpClient
from .market_sessions import us_equity_session
from .source_values import _number, _timeout


FINNHUB_QUOTE_URL = "https://finnhub.io/api/v1/quote"


FINNHUB_CANDLE_URL = "https://finnhub.io/api/v1/stock/candle"


_ETF_LOGO_DOMAINS = {
    "QQQ": "invesco.com",
    "SPY": "spdrs.com",
    "IWM": "ishares.com",
    "DIA": "statestreet.com",
}


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
        market_session: callable = us_equity_session,
    ) -> None:
        self._client_owner = OwnedClient(client, PooledJsonHttpClient)
        self._client = self._client_owner.client
        self._worker = BackgroundTask(self._client_owner.close, thread_factory=lambda **kwargs: Thread(**kwargs))
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
        self._closed_session: str | None = None
        self._selection_session: str | None = None
        self._selections: dict[str, list[str]] = {}
        self._market_session = market_session
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
        self._custom_requests: dict[tuple[str, ...], float] = {}
        self._urgent_symbols: list[str] = []
        self._custom_attempts: dict[str, float] = {}

    def close(self) -> None:
        self._worker.close()

    def fetch(self, settings: DisplaySettings) -> Mapping[str, object]:
        with self._refresh_lock:
            now = self._monotonic()
            self._custom_requests = {symbols: seen for symbols, seen in self._custom_requests.items() if now - seen < 300}
            if settings.custom_stock_symbols:
                self._custom_requests[settings.custom_stock_symbols] = now
                with self._quote_lock:
                    for symbol in settings.custom_stock_symbols:
                        if symbol not in self._quotes and now - self._custom_attempts.get(symbol, float("-inf")) >= 30:
                            if symbol not in self._urgent_symbols:
                                self._urgent_symbols.append(symbol)
        self._start_all_market_refresh()
        records: list[dict[str, object]] = []
        for group in MARKET_GROUPS:
            records.extend(self._group_records(group.id, group.label, group.symbols))
        records.extend(self._group_records("stock_custom", "Custom", settings.custom_stock_symbols))
        return {"content": records}

    def _start_all_market_refresh(self) -> None:
        """Start one shared all-market refresh without delaying a settings change."""

        now = self._monotonic()
        market = self._market_session(self._clock())
        with self._refresh_lock:
            custom_symbols = tuple(dict.fromkeys(symbol for symbols in self._custom_requests for symbol in symbols))
            with self._quote_lock:
                missing_custom = any(symbol not in self._quotes for symbol in custom_symbols)
            if not market.open and (market.closed_session is None or (market.closed_session == self._closed_session and not missing_custom)):
                return
            if self._refreshing or (not self._urgent_symbols and now - self._last_refresh < self._refresh_seconds):
                return
            self._last_refresh = now
            self._refreshing = True
        selection_session = (
            f"open:{datetime.fromtimestamp(self._clock(), timezone.utc).date().isoformat()}"
            if market.open else f"close:{market.closed_session}"
        )
        if not self._worker.start(self._refresh_all_markets, args=(market.closed_session, selection_session, custom_symbols), name="ticker-stock-refresh"):
            with self._refresh_lock:
                self._refreshing = False

    def _refresh_all_markets(self, closed_session: str | None = None, selection_session: str | None = None, custom_symbols: Sequence[str] = ()) -> None:
        """Refresh every quote in the source-owned market cache."""

        changed = False
        updates = {}
        try:
            smart_symbols = tuple(dict.fromkeys(symbol for group in MARKET_GROUPS for symbol in group.symbols))
            symbols = list(dict.fromkeys((*custom_symbols, *smart_symbols)))
            visited = set()
            while symbols:
                with self._refresh_lock:
                    urgent = [symbol for symbol in self._urgent_symbols if symbol not in visited]
                    self._urgent_symbols.clear()
                if urgent:
                    symbols = list(dict.fromkeys((*urgent, *symbols)))
                symbol = symbols.pop(0)
                if symbol in visited:
                    continue
                visited.add(symbol)
                with self._refresh_lock:
                    self._custom_attempts[symbol] = self._monotonic()
                quote = self._fetch_quote(symbol) if self._keys else None
                if quote is not None:
                    updates[symbol] = quote
                    with self._quote_lock:
                        self._quotes[symbol] = quote
                    changed = True
            complete = all(symbol in updates for symbol in smart_symbols)
            if closed_session is not None and complete:
                self._closed_session = closed_session
            if changed:
                with self._quote_lock:
                    self._quotes.update(updates)
                    for group in MARKET_GROUPS:
                        if group.id == "stock_momentum":
                            self._selections[group.id] = self._rank_symbols(smart_symbols, popular=0)
                        elif (complete and selection_session != self._selection_session) or group.id not in self._selections:
                            self._selections[group.id] = self._rank_symbols(group.symbols, popular=2)
                    if complete:
                        self._selection_session = selection_session
                self._save_cache()
        finally:
            with self._refresh_lock:
                self._refreshing = False

    def _rank_symbols(self, symbols: Sequence[str], *, popular: int) -> list[str]:
        """Select ten names by daily gain, with reserved places for curated category leaders."""

        available = []
        for symbol in dict.fromkeys(symbols):
            quote = self._quotes.get(symbol)
            if quote is None:
                continue
            try:
                gain = float(quote["change_pct"].rstrip("%"))
            except (ValueError, TypeError):
                continue
            if isfinite(gain):
                available.append((symbol, gain))
        leaders = [symbol for symbol, _ in available[:popular]]
        ranked = sorted(available, key=lambda entry: -entry[1])
        winners = [symbol for symbol, _ in ranked if symbol not in leaders][:10 - len(leaders)]
        selected = set(winners + leaders)
        return [symbol for symbol, _ in ranked if symbol in selected]

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
            if group_id != "stock_custom":
                candidates = tuple(dict.fromkeys(symbol for group in MARKET_GROUPS for symbol in group.symbols)) if group_id == "stock_momentum" else symbols
                symbols = self._selections.get(group_id, self._rank_symbols(candidates, popular=0 if group_id == "stock_momentum" else 2))
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
            if isinstance(payload, Mapping) and isinstance(payload.get("closed_session"), str):
                self._closed_session = payload["closed_session"]
            if isinstance(payload, Mapping):
                selection_session = payload.get("selection_session")
                self._selection_session = selection_session if isinstance(selection_session, str) else None
                selections = payload.get("selections", {})
                if isinstance(selections, Mapping):
                    self._selections = {
                        group.id: [symbol for symbol in selections[group.id] if symbol in group.symbols]
                        for group in MARKET_GROUPS
                        if isinstance(selections.get(group.id), list) and group.id not in {"stock_momentum", "stock_custom"}
                    }
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
                json.dumps({"quotes": quotes, "closed_session": self._closed_session,
                            "selection_session": self._selection_session, "selections": self._selections}, sort_keys=True, separators=(",", ":")),
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


def _symbols(values: Sequence[str]) -> tuple[str, ...]:
    return tuple(value.upper() for raw in values if (value := str(raw).strip().upper()))


def _positive(value: object) -> bool:
    return _number(value) > 0


__all__ = ['FinnhubStockSource']
