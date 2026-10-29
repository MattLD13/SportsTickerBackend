"""Read weather for a verified circuit location."""

from __future__ import annotations

from threading import Lock
import time
from collections.abc import Callable, Mapping
from typing import Any
from urllib.parse import urlencode

from .http import JsonHttpClient, JsonHttpError


class CircuitWeatherSource:
    """Cache circuit locations and weather outside display rendering.

    Several racing series read this source at the same time. One lock keeps the
    location lookup at one request each second and keeps each cache entry whole.
    """

    def __init__(self, client: JsonHttpClient, *, timeout: float = 10, clock: Callable[[], float] = time.time):
        self.client, self.timeout, self.clock = client, timeout, clock
        self.locations: dict[tuple[str, str], tuple[float, float]] = {}
        self.conditions: dict[tuple[float, float], tuple[float, dict[str, Any]]] = {}
        self.next_lookup = 0.0
        self._lock = Lock()

    def fetch(self, track: str, country: str = "") -> dict[str, Any]:
        """Return Fahrenheit, mph, and a wind bearing for one circuit."""
        with self._lock:
            return self._fetch(track, country)

    def _fetch(self, track: str, country: str) -> dict[str, Any]:
        try:
            key = (track, country)
            location = self.locations.get(key)
            if location is None:
                if self.clock() < self.next_lookup:
                    return {"available": False, "error": "Circuit lookup is pending"}
                self.next_lookup = self.clock() + 1
                query = {"q": track, "format": "jsonv2", "limit": 5}
                if country:
                    query["countrycodes"] = country.lower()
                rows = self.client.get_json(
                    "https://nominatim.openstreetmap.org/search?" + urlencode(query), timeout=self.timeout,
                )
                row = next((item for item in rows if isinstance(item, Mapping) and item.get("type") in {
                    "raceway", "sports_centre", "track", "stadium",
                }), None)
                if row is None:
                    return {"available": False, "error": "Circuit location is unavailable"}
                location = float(row["lat"]), float(row["lon"])
                self.locations[key] = location
            cached_at, cached = self.conditions.get(location, (0.0, {}))
            if cached and self.clock() - cached_at < 300:
                return cached
            query = urlencode({
                "latitude": location[0], "longitude": location[1],
                "current": "temperature_2m,wind_speed_10m,wind_direction_10m",
                "temperature_unit": "fahrenheit", "wind_speed_unit": "mph", "timezone": "UTC",
            })
            payload = self.client.get_json("https://api.open-meteo.com/v1/forecast?" + query, timeout=self.timeout)
            current = payload["current"]
            result = {
                "available": True, "source": "open-meteo", "observed_at": current["time"],
                "air_temp": str(round(float(current["temperature_2m"]))),
                "wind_mph": str(round(float(current["wind_speed_10m"]))),
                "wind_dir": str(round(float(current["wind_direction_10m"]))),
            }
            self.conditions[location] = self.clock(), result
            return result
        except (JsonHttpError, KeyError, ValueError, TypeError) as error:
            return {"available": False, "error": str(error)}
