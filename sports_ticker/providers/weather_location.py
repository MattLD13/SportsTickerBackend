"""Resolve a U.S. ZIP code to weather coordinates when a user saves settings.

Core owns this lookup because it validates settings before it stores them.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from math import isfinite
import re
from urllib.parse import urlencode

from .http import JsonHttpClient, OwnedClient, PooledJsonHttpClient
from .payloads import as_mapping

_GEOCODING_URL = "https://geocoding-api.open-meteo.com/v1/search"
_POSTAL_CODE = re.compile(r"^\d{5}(?:-\d{4})?$")


class WeatherLocationResolver:
    """Resolve U.S. ZIP codes before the backend stores weather coordinates."""

    def __init__(
        self,
        client: JsonHttpClient | None = None,
        *,
        timeout: float = 10.0,
    ) -> None:
        self._client_owner = OwnedClient(client, PooledJsonHttpClient)
        self.client = self._client_owner.client
        self.timeout = float(timeout)
        if not isfinite(self.timeout) or self.timeout <= 0:
            raise ValueError("timeout must be a finite positive number")

    def close(self) -> None:
        self._client_owner.close()

    def resolve(self, value: str) -> Mapping[str, object] | None:
        """Return canonical city and coordinates when ``value`` is a U.S. ZIP code."""

        query = str(value).strip()
        if not _POSTAL_CODE.fullmatch(query):
            return None
        postal = query[:5]
        payload = self.client.get_json(
            _GEOCODING_URL + "?" + urlencode(dict(
                name=postal,
                count=10,
                countryCode="US",
                language="en",
                format="json",
            )),
            timeout=self.timeout,
        )
        results = payload.get("results") if isinstance(payload, Mapping) else None
        if not isinstance(results, Sequence) or isinstance(results, (str, bytes)):
            return None
        for result in results:
            item = as_mapping(result)
            postcodes = item.get("postcodes")
            if not isinstance(postcodes, Sequence) or isinstance(postcodes, (str, bytes)):
                continue
            if postal not in {str(code).strip() for code in postcodes}:
                continue
            try:
                return {
                    "weather_city": "" if (name := item.get("name")) is None else str(name).strip(),
                    "weather_lat": float(item["latitude"]),
                    "weather_lon": float(item["longitude"]),
                }
            except (KeyError, TypeError, ValueError):
                return None
        return None


__all__ = ["WeatherLocationResolver"]
