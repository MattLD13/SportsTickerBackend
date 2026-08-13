"""Native Open-Meteo weather provider."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date, datetime, timezone
from math import isfinite
from typing import Any
from urllib.parse import urlencode

from sports_ticker.domain import ContentItem, DisplaySettings

from .contracts import ProviderHealth, ProviderResult
from .http import JsonHttpClient, UrllibJsonHttpClient
from .stale_cache import SettingsResultCache


_FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
_AIR_QUALITY_URL = "https://air-quality-api.open-meteo.com/v1/air-quality"


class OpenMeteoWeatherProvider:
    """Fetch current, daily, and air-quality facts for one ticker."""

    def __init__(
        self,
        client: JsonHttpClient | None = None,
        *,
        timeout: float = 10.0,
    ) -> None:
        self.client = client or UrllibJsonHttpClient()
        self.timeout = float(timeout)
        if not isfinite(self.timeout) or self.timeout <= 0:
            raise ValueError("timeout must be a finite positive number")
        self._stale_cache = SettingsResultCache()

    def fetch(self, settings: DisplaySettings) -> ProviderResult:
        """Return fresh weather content or the provider's immutable stale result."""

        if not isinstance(settings, DisplaySettings):
            raise TypeError("settings must be DisplaySettings")
        try:
            if not isfinite(settings.weather_lat) or not isfinite(settings.weather_lon):
                raise ValueError("weather coordinates must be finite")
            forecast_url = _query(
                _FORECAST_URL,
                latitude=settings.weather_lat,
                longitude=settings.weather_lon,
                current=(
                    "temperature_2m,weather_code,apparent_temperature,"
                    "wind_speed_10m,relative_humidity_2m,is_day,cloud_cover"
                ),
                daily=(
                    "weather_code,temperature_2m_max,temperature_2m_min,"
                    "uv_index_max,sunrise,sunset,precipitation_probability_max,"
                    "wind_speed_10m_max"
                ),
                temperature_unit="fahrenheit",
                wind_speed_unit="mph",
                timezone="auto",
            )
            weather_payload = self.client.get_json(forecast_url, timeout=self.timeout)
            aqi, aqi_error = self._fetch_aqi(settings)
            item = _content_item(settings, weather_payload, aqi)
            health = ProviderHealth(
                healthy=aqi_error is None,
                provider="weather",
                error=aqi_error,
            )
            result = ProviderResult(
                content=(item,),
                observed_at=datetime.now(timezone.utc),
                health=health,
            )
            if health.healthy:
                self._stale_cache.set(settings, result)
            return result
        except Exception as exc:
            return self._stale_result(settings, exc)

    def _fetch_aqi(self, settings: DisplaySettings) -> tuple[Any, str | None]:
        """Fetch AQI separately because Open-Meteo exposes it on another host."""

        try:
            payload = self.client.get_json(
                _query(
                    _AIR_QUALITY_URL,
                    latitude=settings.weather_lat,
                    longitude=settings.weather_lon,
                    current="us_aqi",
                    timezone="auto",
                ),
                timeout=self.timeout,
            )
            current = _mapping(payload.get("current")) if isinstance(payload, Mapping) else {}
            return current.get("us_aqi"), None
        except Exception as exc:
            return None, f"air quality: {exc}"

    def _stale_result(
        self,
        settings: DisplaySettings,
        error: Exception,
    ) -> ProviderResult:
        message = f"stale: {error}"
        result = self._stale_cache.get(settings)
        if result is None:
            return ProviderResult(
                health=ProviderHealth(healthy=False, provider="weather", error=message)
            )
        return ProviderResult(
            content=result.content,
            alerts=result.alerts,
            news=result.news,
            observed_at=result.observed_at,
            health=ProviderHealth(healthy=False, provider="weather", error=message),
        )


def _content_item(
    settings: DisplaySettings,
    payload: Any,
    aqi: Any,
) -> ContentItem:
    if not isinstance(payload, Mapping):
        raise TypeError("forecast JSON must be an object")
    current = _mapping(payload.get("current"))
    daily = _mapping(payload.get("daily"))
    if not current:
        raise ValueError("forecast response is missing current data")

    temperature = _rounded(current.get("temperature_2m"), 0)
    weather_code = current.get("weather_code", 0)
    icon = _weather_icon(weather_code)
    feels = _rounded(current.get("apparent_temperature"), temperature)
    wind = _rounded(current.get("wind_speed_10m"), 0)
    humidity = _rounded(current.get("relative_humidity_2m"), 0)
    is_day = _optional_int(current.get("is_day"))
    cloud_cover = _optional_int(current.get("cloud_cover"))
    sunrise = _first(daily.get("sunrise"))
    sunset = _first(daily.get("sunset"))
    aqi_value = _optional_int(aqi)
    forecast = _forecast(daily)
    day_night = None if is_day is None else ("day" if is_day else "night")
    stats = {
        "aqi": _display(aqi_value),
        "uv": _display(_rounded(_first(daily.get("uv_index_max")), 0)),
        "feels": str(feels),
        "wind": str(wind),
        "humidity": str(humidity),
    }
    situation = {
        "icon": icon,
        "is_day": is_day,
        "day_night": day_night,
        "cloud_cover": cloud_cover,
        "obs_time": current.get("time"),
        "sunrise": sunrise,
        "sunset": sunset,
        "stats": stats,
        "forecast": forecast,
    }
    data = {
        "type": "weather",
        "sport": "weather",
        "home_abbr": str(temperature),
        "away_abbr": settings.weather_city,
        "status": icon.upper(),
        "city": settings.weather_city,
        "temperature": temperature,
        "temp": temperature,
        "icon": icon,
        "weather_code": weather_code,
        "feels": feels,
        "wind": wind,
        "humidity": humidity,
        "aqi": aqi_value,
        "is_day": is_day,
        "day_night": day_night,
        "cloud_cover": cloud_cover,
        "sunrise": sunrise,
        "sunset": sunset,
        "forecast": forecast,
        "situation": situation,
        "condition": icon,
    }
    return ContentItem(
        id="weather_main",
        family="weather",
        kind="weather",
        is_shown=True,
        data=data,
    )


def _forecast(daily: Mapping[str, Any]) -> list[dict[str, Any]]:
    days = daily.get("time")
    if not isinstance(days, Sequence) or isinstance(days, (str, bytes)):
        return []
    result: list[dict[str, Any]] = []
    for index, raw_day in enumerate(days[:5]):
        try:
            item = {
                "day": _day_name(raw_day),
                "icon": _weather_icon(_at(daily.get("weather_code"), index, 0)),
                "high": _rounded(_at(daily.get("temperature_2m_max"), index), 0),
                "low": _rounded(_at(daily.get("temperature_2m_min"), index), 0),
            }
            pop = _at(daily.get("precipitation_probability_max"), index)
            peak_wind = _at(daily.get("wind_speed_10m_max"), index)
            if pop is not None:
                item["pop"] = _rounded(pop, 0)
            if peak_wind is not None:
                item["wind"] = _rounded(peak_wind, 0)
            result.append(item)
        except (TypeError, ValueError):
            continue
    return result


def _query(base: str, **params: Any) -> str:
    return f"{base}?{urlencode(params)}"


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _first(value: Any) -> Any:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return value[0] if value else None
    return None


def _at(value: Any, index: int, default: Any = None) -> Any:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return value[index] if index < len(value) else default
    return default


def _rounded(value: Any, default: int) -> int:
    if value is None:
        return default
    try:
        return int(round(float(value)))
    except (TypeError, ValueError):
        return default


def _optional_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(round(float(value)))
    except (TypeError, ValueError):
        return None


def _display(value: Any) -> str:
    return "--" if value is None else str(value)


def _day_name(value: Any) -> str:
    try:
        parsed = date.fromisoformat(str(value))
    except ValueError:
        return "DAY"
    return "TODAY" if parsed == date.today() else parsed.strftime("%a").upper()


def _weather_icon(value: Any) -> str:
    try:
        code = int(value)
    except (TypeError, ValueError):
        return "cloud"
    if code == 0:
        return "sun"
    if code in {1, 2, 3, 45, 48}:
        return "cloud"
    if code in {51, 53, 55, 56, 57, 61, 63, 65, 66, 67, 80, 81, 82}:
        return "rain"
    if code in {71, 73, 75, 77, 85, 86}:
        return "snow"
    if code in {95, 96, 99}:
        return "storm"
    return "cloud"


__all__ = ["OpenMeteoWeatherProvider"]
