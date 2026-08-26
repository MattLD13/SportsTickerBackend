"""Weather providers with NWS routing for U.S. coordinates."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from datetime import date, datetime, timedelta, timezone
from math import isfinite
import threading
import time
import re
from typing import Any
from urllib.parse import urlencode

from sports_ticker.domain import ContentItem, DisplaySettings

from .contracts import ProviderHealth, ProviderResult
from .http import JsonHttpClient, UrllibJsonHttpClient
from .stale_cache import SettingsResultCache


_FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
_AIR_QUALITY_URL = "https://air-quality-api.open-meteo.com/v1/air-quality"
_NWS_POINTS_URL = "https://api.weather.gov/points"
_NWS_POINT_CACHE_SECONDS = 24 * 60 * 60
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
        self.client = client or UrllibJsonHttpClient()
        self.timeout = float(timeout)
        if not isfinite(self.timeout) or self.timeout <= 0:
            raise ValueError("timeout must be a finite positive number")

    def resolve(self, value: str) -> Mapping[str, object] | None:
        """Return canonical city and coordinates when ``value`` is a U.S. ZIP code."""

        query = str(value).strip()
        if not _POSTAL_CODE.fullmatch(query):
            return None
        postal = query[:5]
        payload = self.client.get_json(
            _query(
                _GEOCODING_URL,
                name=postal,
                count=10,
                countryCode="US",
                language="en",
                format="json",
            ),
            timeout=self.timeout,
        )
        results = payload.get("results") if isinstance(payload, Mapping) else None
        if not isinstance(results, Sequence) or isinstance(results, (str, bytes)):
            return None
        for result in results:
            item = _mapping(result)
            postcodes = item.get("postcodes")
            if not isinstance(postcodes, Sequence) or isinstance(postcodes, (str, bytes)):
                continue
            if postal not in {str(code).strip() for code in postcodes}:
                continue
            try:
                return {
                    "weather_city": _text(item.get("name")),
                    "weather_lat": float(item["latitude"]),
                    "weather_lon": float(item["longitude"]),
                }
            except (KeyError, TypeError, ValueError):
                return None
        return None


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

    def fetch_aqi(self, settings: DisplaySettings) -> Any:
        """Return AQI without making AQI availability control weather health."""

        value, _ = self._fetch_aqi(settings)
        return value

    def fetch_supplemental(self, settings: DisplaySettings) -> Mapping[str, Any]:
        """Return daily display fields that supplement an NWS weather result."""

        payload = self.client.get_json(
            _query(
                _FORECAST_URL,
                latitude=settings.weather_lat,
                longitude=settings.weather_lon,
                daily="uv_index_max,sunrise,sunset",
                timezone="auto",
            ),
            timeout=self.timeout,
        )
        daily = _mapping(payload.get("daily")) if isinstance(payload, Mapping) else {}
        return {
            "uv": _rounded(_first(daily.get("uv_index_max")), 0),
            "sunrise": _first(daily.get("sunrise")),
            "sunset": _first(daily.get("sunset")),
        }

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


class HybridWeatherProvider:
    """Use NWS for U.S. coordinates and Open-Meteo everywhere else."""

    def __init__(
        self,
        client: JsonHttpClient | None = None,
        *,
        timeout: float = 10.0,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self.client = client or UrllibJsonHttpClient()
        self.timeout = float(timeout)
        if not isfinite(self.timeout) or self.timeout <= 0:
            raise ValueError("timeout must be a finite positive number")
        self._monotonic = monotonic
        self._open_meteo = OpenMeteoWeatherProvider(self.client, timeout=self.timeout)
        self._stale_cache = SettingsResultCache()
        self._points_cache: dict[tuple[float, float], tuple[float, Mapping[str, Any]]] = {}
        self._points_lock = threading.RLock()

    def fetch(self, settings: DisplaySettings) -> ProviderResult:
        """Fetch one normalized result, routing by the supplied coordinates."""

        if not isinstance(settings, DisplaySettings):
            raise TypeError("settings must be DisplaySettings")
        try:
            result = self._fetch_nws(settings)
        except Exception:
            result = self._open_meteo.fetch(settings)
        if result.health.healthy:
            self._stale_cache.set(settings, result)
            return result
        stale = self._stale_cache.get(settings)
        return stale if stale is not None else result

    def _fetch_nws(self, settings: DisplaySettings) -> ProviderResult:
        """Fetch NWS grid data and the nearest current observation."""

        point = self._nws_point(settings)
        properties = _mapping(point.get("properties"))
        forecast_url = _text(properties.get("forecast"))
        hourly_url = _text(properties.get("forecastHourly"))
        stations_url = _text(properties.get("observationStations"))
        if not forecast_url or not stations_url:
            raise ValueError("NWS point response is missing forecast links")

        forecast_payload = self.client.get_json(forecast_url, timeout=self.timeout)
        observation = self._nws_observation(stations_url)
        hourly_payload = None
        if hourly_url and not _nws_observation_is_fresh(observation):
            hourly_payload = self.client.get_json(hourly_url, timeout=self.timeout)
        aqi = self._open_meteo.fetch_aqi(settings)
        try:
            supplemental = self._open_meteo.fetch_supplemental(settings)
        except Exception:
            supplemental = {}
        item = _nws_content_item(
            settings,
            point,
            forecast_payload,
            observation,
            aqi,
            hourly_payload,
            supplemental,
        )
        return ProviderResult(
            content=(item,),
            observed_at=datetime.now(timezone.utc),
            health=ProviderHealth(healthy=True, provider="weather"),
        )

    def _nws_point(self, settings: DisplaySettings) -> Mapping[str, Any]:
        """Resolve one coordinate to an NWS forecast grid and cache its metadata."""

        key = (round(settings.weather_lat, 5), round(settings.weather_lon, 5))
        now = float(self._monotonic())
        with self._points_lock:
            cached = self._points_cache.get(key)
            if cached is not None and now - cached[0] < _NWS_POINT_CACHE_SECONDS:
                return cached[1]
        url = f"{_NWS_POINTS_URL}/{key[0]:.5f},{key[1]:.5f}"
        payload = self.client.get_json(url, timeout=self.timeout)
        if not isinstance(payload, Mapping):
            raise TypeError("NWS point response must be an object")
        with self._points_lock:
            self._points_cache[key] = (now, payload)
        return payload

    def _nws_observation(self, stations_url: str) -> Mapping[str, Any]:
        """Fetch the latest observation from the nearest NWS station."""

        station_payload = self.client.get_json(stations_url, timeout=self.timeout)
        features = station_payload.get("features") if isinstance(station_payload, Mapping) else None
        if not isinstance(features, Sequence) or isinstance(features, (str, bytes)) or not features:
            return {}
        first = _mapping(features[0])
        station_url = _text(first.get("id"))
        station_properties = _mapping(first.get("properties"))
        station_url = station_url or _text(station_properties.get("@id"))
        station_id = _text(station_properties.get("stationIdentifier"))
        if not station_url and station_id:
            station_url = f"https://api.weather.gov/stations/{station_id}"
        if not station_url:
            return {}
        return _mapping(
            self.client.get_json(
                f"{station_url.rstrip('/')}/observations/latest",
                timeout=self.timeout,
            )
        )


def _nws_content_item(
    settings: DisplaySettings,
    point: Mapping[str, Any],
    forecast_payload: Any,
    observation: Mapping[str, Any],
    aqi: Any,
    hourly_payload: Any = None,
    supplemental: Mapping[str, Any] | None = None,
) -> ContentItem:
    """Normalize NWS forecast and observation data into the weather contract."""

    forecast_properties = _mapping(forecast_payload.get("properties"))
    periods = forecast_properties.get("periods")
    if not isinstance(periods, Sequence) or isinstance(periods, (str, bytes)) or not periods:
        raise ValueError("NWS forecast response is missing periods")
    first_period = _mapping(periods[0])
    observation_properties = _mapping(observation.get("properties"))
    hourly_periods = _mapping(hourly_payload.get("properties")).get("periods") if isinstance(hourly_payload, Mapping) else None
    hourly_period = _mapping(hourly_periods[0]) if isinstance(hourly_periods, Sequence) and not isinstance(hourly_periods, (str, bytes)) and hourly_periods else {}
    current_properties = observation_properties if _nws_observation_is_fresh(observation) else {}
    supplemental = supplemental or {}
    if not current_properties and not hourly_period:
        raise ValueError("NWS has no current observation or hourly forecast")

    temperature = _temperature_f(
        current_properties.get("temperature"),
        _number(hourly_period.get("temperature"), _number(first_period.get("temperature"), 0)),
        hourly_period.get("temperatureUnit") or first_period.get("temperatureUnit"),
    )
    description = _text(
        current_properties.get("textDescription")
        or hourly_period.get("shortForecast")
        or first_period.get("shortForecast")
        or "Weather unavailable"
    )
    icon = _condition_icon(description)
    feels = _temperature_f(
        current_properties.get("heatIndex")
        or current_properties.get("windChill"),
        temperature,
        "F",
    )
    wind = _wind_mph(current_properties.get("windSpeed"))
    humidity = _number(_mapping(current_properties.get("relativeHumidity")).get("value"), 0)
    is_day = hourly_period.get("isDaytime", first_period.get("isDaytime"))
    if not isinstance(is_day, bool):
        is_day = None
    cloud_cover = None
    aqi_value = _optional_int(aqi)
    forecast = _nws_forecast(periods)
    day_night = None if is_day is None else ("day" if is_day else "night")
    stats = {
        "aqi": _display(aqi_value),
        "uv": _display(supplemental.get("uv")),
        "feels": str(feels),
        "wind": str(wind),
        "humidity": str(humidity),
    }
    obs_time = current_properties.get("timestamp") or hourly_period.get("startTime") or first_period.get("startTime")
    situation = {
        "icon": icon,
        "is_day": is_day,
        "day_night": day_night,
        "cloud_cover": cloud_cover,
        "obs_time": obs_time,
        "sunrise": supplemental.get("sunrise"),
        "sunset": supplemental.get("sunset"),
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
        "weather_code": None,
        "feels": feels,
        "wind": wind,
        "humidity": humidity,
        "aqi": aqi_value,
        "is_day": is_day,
        "day_night": day_night,
        "cloud_cover": cloud_cover,
        "sunrise": supplemental.get("sunrise"),
        "sunset": supplemental.get("sunset"),
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


def _nws_observation_is_fresh(observation: Mapping[str, Any]) -> bool:
    """Use station observations only while they contain a recent temperature."""

    properties = _mapping(observation.get("properties"))
    temperature = _mapping(properties.get("temperature")).get("value")
    if temperature is None:
        return False
    timestamp = _text(properties.get("timestamp"))
    if not timestamp:
        return True
    try:
        observed_at = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except ValueError:
        return False
    if observed_at.tzinfo is None:
        observed_at = observed_at.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) - observed_at <= timedelta(hours=2)


def _nws_forecast(periods: Sequence[Any]) -> list[dict[str, Any]]:
    """Convert NWS day and night periods into the existing five-day view."""

    result: list[dict[str, Any]] = []
    for index, raw_period in enumerate(periods):
        period = _mapping(raw_period)
        if period.get("isDaytime") is not True:
            continue
        low_period = _mapping(periods[index + 1]) if index + 1 < len(periods) else {}
        temperature = _number(period.get("temperature"), 0)
        low = _number(low_period.get("temperature"), temperature)
        probability = _mapping(period.get("probabilityOfPrecipitation")).get("value")
        result.append(
            {
                "day": _nws_day_name(period.get("startTime")),
                "icon": _condition_icon(_text(period.get("shortForecast"))),
                "high": temperature,
                "low": low,
                "pop": _number(probability, 0),
            }
        )
        if len(result) >= 5:
            break
    return result


def _nws_day_name(value: Any) -> str:
    """Return the local calendar label from an NWS ISO timestamp."""

    raw = _text(value)
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return "DAY"
    return _day_name(parsed.date().isoformat())


def _condition_icon(value: Any) -> str:
    """Map an NWS text forecast to the renderer's stable icon names."""

    text = _text(value).lower()
    if any(word in text for word in ("thunder", "storm", "lightning")):
        return "storm"
    if any(word in text for word in ("snow", "sleet", "blizzard", "ice")):
        return "snow"
    if any(word in text for word in ("rain", "shower", "drizzle")):
        return "rain"
    if any(word in text for word in ("fog", "mist", "haze")):
        return "fog"
    if any(word in text for word in ("sunny", "clear")):
        return "sun"
    return "cloud"


def _temperature_f(value: Any, fallback: Any, unit: Any) -> int:
    """Convert one NWS temperature value to rounded Fahrenheit."""

    value_mapping = _mapping(value)
    number = value_mapping.get("value")
    if number is None:
        number = fallback
        unit = "F"
    else:
        unit = value_mapping.get("unitCode") or value_mapping.get("unit") or unit
    try:
        result = float(number)
        if str(unit).upper() in {"C", "CELSIUS", "WMOUNIT:DEGC", "WMOUNIT:DEG_C"}:
            result = result * 9 / 5 + 32
        return int(round(result))
    except (TypeError, ValueError):
        return 0


def _wind_mph(value: Any) -> int:
    """Convert an NWS wind speed value from metres per second to mph."""

    raw = _mapping(value).get("value")
    try:
        return int(round(float(raw) * 2.236936))
    except (TypeError, ValueError):
        return 0


def _number(value: Any, default: int) -> int:
    try:
        return int(round(float(value)))
    except (TypeError, ValueError):
        return default


def _text(value: Any) -> str:
    return str(value).strip() if value is not None else ""


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


__all__ = ["HybridWeatherProvider", "OpenMeteoWeatherProvider", "WeatherLocationResolver"]
