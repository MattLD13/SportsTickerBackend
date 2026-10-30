"""Search supported US stock symbols through the configured market data provider."""

from collections import OrderedDict
from collections.abc import Mapping
import os
import re
from threading import Lock
from time import monotonic
from urllib.parse import urlencode

from ticker.server.providers.http import JsonHttpClient, OwnedClient, PooledJsonHttpClient


class StockSymbolCatalog:
    """Cache bounded symbol searches without exposing the provider key to clients."""

    def __init__(self, client: JsonHttpClient | None = None, *, clock=monotonic) -> None:
        self._client_owner = OwnedClient(client, PooledJsonHttpClient)
        self._client = self._client_owner.client
        self._clock = clock
        self._cache = OrderedDict()
        self._lock = Lock()

    def close(self) -> None:
        self._client_owner.close()

    def search(self, query: str) -> list[dict[str, str]]:
        query = query.strip().upper()
        if not query:
            return []
        if len(query) > 60:
            raise ValueError("Stock search must contain at most 60 characters")
        with self._lock:
            cached = self._cache.get(query)
            if cached is not None and self._clock() - cached[0] < 3600:
                self._cache.move_to_end(query)
                return [dict(row) for row in cached[1]]
            key = next((os.environ.get(name, "").strip() for name in (
                "FINNHUB_API_KEY", "FINNHUB_KEY_1", "FINNHUB_KEY_2", "FINNHUB_KEY_3", "FINNHUB_KEY_4", "FINNHUB_KEY_5"
            ) if os.environ.get(name, "").strip()), "")
            if not key:
                raise RuntimeError("Stock search is not configured")
            try:
                payload = self._client.get_json(
                    "https://finnhub.io/api/v1/search?" + urlencode({"q": query, "exchange": "US", "token": key}),
                    timeout=5.0,
                )
            except Exception as error:
                raise RuntimeError("Stock search is temporarily unavailable") from error
            values = payload.get("result") if isinstance(payload, Mapping) else None
            if not isinstance(values, list):
                raise RuntimeError("Stock search returned an invalid response")
            found = {}
            for row in values:
                if not isinstance(row, Mapping):
                    continue
                symbol = str(row.get("symbol") or "").strip().upper()
                name = str(row.get("description") or "").strip()
                if name and re.fullmatch(r"[A-Z][A-Z0-9]{0,9}(?:[.-][A-Z0-9]{1,3})?", symbol):
                    found.setdefault(symbol, {"symbol": symbol, "name": name[:160]})
            results = sorted(found.values(), key=lambda row: (row["symbol"] != query, not row["symbol"].startswith(query), row["symbol"]))[:12]
            self._cache[query] = (self._clock(), results)
            while len(self._cache) > 256:
                self._cache.popitem(last=False)
            return [dict(row) for row in results]
