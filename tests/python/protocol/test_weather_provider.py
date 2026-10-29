from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from sports_ticker.domain import DisplaySettings
from sports_ticker.providers.weather import HybridWeatherProvider
from sports_ticker.providers.weather_location import WeatherLocationResolver
from sports_ticker.providers.http import JsonHttpError


class FakeJsonClient:
    def __init__(self, *, nws: bool) -> None:
        self.nws = nws
        self.urls: list[str] = []

    def get_json(self, url: str, *, timeout: float):
        self.urls.append(url)
        if url.startswith("https://api.weather.gov/points/"):
            if not self.nws:
                raise JsonHttpError("HTTP 404 for NWS")
            return {
                "properties": {
                    "forecast": "https://api.weather.gov/gridpoints/OKX/33,37/forecast",
                    "forecastHourly": "https://api.weather.gov/gridpoints/OKX/33,37/forecast/hourly",
                    "observationStations": "https://api.weather.gov/gridpoints/OKX/33,37/stations",
                    "forecastOffice": "https://api.weather.gov/offices/OKX",
                }
            }
        if url == "https://api.weather.gov/offices/OKX":
            return {"name": "New York, NY"}
        if url == "https://api.weather.gov/products/types/UVI":
            return {"@graph": [{"id": "uvi-test"}]}
        if url == "https://api.weather.gov/products/uvi-test":
            valid_date = datetime.now(timezone.utc).strftime("%b %d %Y").upper()
            return {
                "productText": f"""
VALID {valid_date} AT SOLAR NOON
CITY               STATE  UVI       CITY               STATE  UVI
NEW YORK             NY     5       PHILADELPHIA         PA     6
"""
            }
        if url.endswith("/forecast"):
            today = date.today().isoformat()
            return {
                "properties": {
                    "periods": [
                        {
                            "name": "Today",
                            "startTime": f"{today}T08:00:00-04:00",
                            "isDaytime": True,
                            "temperature": 75,
                            "temperatureUnit": "F",
                            "shortForecast": "Mostly Sunny",
                            "probabilityOfPrecipitation": {"value": 10},
                        },
                        {
                            "name": "Tonight",
                            "startTime": f"{today}T18:00:00-04:00",
                            "isDaytime": False,
                            "temperature": 60,
                            "temperatureUnit": "F",
                            "shortForecast": "Clear",
                        },
                    ]
                }
            }
        if url.endswith("/stations"):
            return {"features": [{"id": "https://api.weather.gov/stations/KNYC"}]}
        if url.endswith("/observations/latest"):
            return {
                "properties": {
                    "temperature": {"value": 20, "unitCode": "wmoUnit:degC"},
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "textDescription": "Light Rain",
                    "windSpeed": {"value": 10, "unitCode": "wmoUnit:m_s-1"},
                    "relativeHumidity": {"value": 56},
                }
            }
        if "air-quality-api.open-meteo.com" in url:
            return {"current": {"us_aqi": 31}}
        if "api.open-meteo.com/v1/forecast" in url:
            return {
                "current": {
                    "temperature_2m": 68,
                    "weather_code": 1,
                    "apparent_temperature": 68,
                    "wind_speed_10m": 5,
                    "relative_humidity_2m": 50,
                    "is_day": 1,
                    "cloud_cover": 20,
                },
                "daily": {
                    "time": ["2026-08-24"],
                    "weather_code": [1],
                    "temperature_2m_max": [72],
                    "temperature_2m_min": [59],
                    "uv_index_max": [5],
                    "sunrise": ["2026-08-24T06:00"],
                    "sunset": ["2026-08-24T19:45"],
                    "precipitation_probability_max": [10],
                    "wind_speed_10m_max": [8],
                },
            }
        raise AssertionError(f"unexpected URL: {url}")


def _settings(lat: float, lon: float) -> DisplaySettings:
    return DisplaySettings(mode="weather", weather_city="Test City", weather_lat=lat, weather_lon=lon)


def test_hybrid_weather_prefers_open_meteo_current_for_us_coordinates() -> None:
    client = FakeJsonClient(nws=True)
    result = HybridWeatherProvider(client, monotonic=lambda: 100.0).fetch(_settings(40.7, -74.0))

    data = result.content[0].data
    assert result.health.healthy is True
    assert data["temperature"] == 68
    assert data["icon"] == "cloud"
    assert data["wind"] == 5
    assert data["situation"]["stats"]["uv"] == "5"
    assert data["situation"]["sunrise"] is None
    assert data["situation"]["sunset"] is None
    assert data["forecast"][0]["high"] == 75
    assert data["forecast"][0]["day"] == "TODAY"
    assert any(url.startswith("https://api.weather.gov/points/") for url in client.urls)
    current_url = next(url for url in client.urls if "api.open-meteo.com/v1/forecast" in url)
    assert "current=" in current_url
    assert "daily=" not in current_url


def test_hybrid_weather_uses_open_meteo_current_when_nws_observation_is_stale() -> None:
    class StaleObservationClient(FakeJsonClient):
        def get_json(self, url: str, *, timeout: float):
            payload = super().get_json(url, timeout=timeout)
            if url.endswith("/observations/latest"):
                payload["properties"]["timestamp"] = (
                    datetime.now(timezone.utc) - timedelta(hours=2)
                ).isoformat()
            return payload

    client = StaleObservationClient(nws=True)
    result = HybridWeatherProvider(client, monotonic=lambda: 100.0).fetch(_settings(40.7, -74.0))

    data = result.content[0].data
    assert data["temperature"] == 68
    assert data["icon"] == "cloud"
    assert any("api.open-meteo.com/v1/forecast" in url for url in client.urls)


def test_hybrid_weather_uses_open_meteo_when_nws_does_not_cover_location() -> None:
    client = FakeJsonClient(nws=False)
    result = HybridWeatherProvider(client, monotonic=lambda: 100.0).fetch(_settings(51.5, -0.1))

    data = result.content[0].data
    assert result.health.healthy is True
    assert data["temperature"] == 68
    assert data["icon"] == "cloud"
    assert data["forecast"][0]["day"] == "TODAY"
    assert any("api.open-meteo.com/v1/forecast" in url for url in client.urls)


def test_hybrid_weather_uses_nws_uv_bulletin_and_open_meteo_current() -> None:
    client = FakeJsonClient(nws=True)
    result = HybridWeatherProvider(client, monotonic=lambda: 100.0).fetch(_settings(40.7, -74.0))

    data = result.content[0].data
    assert result.health.healthy is True
    assert result.health.error is None
    assert data["situation"]["stats"]["uv"] == "5"
    current_url = next(url for url in client.urls if "api.open-meteo.com/v1/forecast" in url)
    assert "current=" in current_url
    assert "daily=" not in current_url


def test_hybrid_weather_reports_nws_uv_failure() -> None:
    class UviFailureClient(FakeJsonClient):
        def get_json(self, url: str, *, timeout: float):
            if "api.weather.gov/products" in url:
                self.urls.append(url)
                raise JsonHttpError("NWS UV request failed")
            return super().get_json(url, timeout=timeout)

    client = UviFailureClient(nws=True)
    result = HybridWeatherProvider(client, monotonic=lambda: 100.0).fetch(_settings(40.7, -74.0))

    data = result.content[0].data
    assert result.health.healthy is True
    assert result.health.error == "NWS UV: NWS UV request failed"
    assert data["situation"]["stats"]["uv"] == "--"


def test_weather_provider_uses_source_calendar_labels() -> None:
    from sports_ticker.providers.weather import _forecast

    forecast = _forecast(
        {"time": ["2026-08-26", "2026-08-27"]},
        today=date(2026, 8, 26),
    )

    assert [day["day"] for day in forecast] == ["TODAY", "THU"]


def test_nws_forecast_uses_observation_day_when_tonight_is_first() -> None:
    from sports_ticker.providers.weather import _nws_forecast

    periods = [
        {"isDaytime": False, "startTime": "2026-08-27T18:00:00-04:00", "temperature": 60},
        {"isDaytime": True, "startTime": "2026-08-28T08:00:00-04:00", "temperature": 75},
    ]

    assert _nws_forecast(periods, today=date(2026, 8, 27))[0]["day"] == "FRI"


def test_hybrid_weather_uses_hourly_forecast_when_station_observation_is_missing() -> None:
    class MissingObservationClient(FakeJsonClient):
        def get_json(self, url: str, *, timeout: float):
            if url.endswith("/observations/latest"):
                self.urls.append(url)
                return {"properties": {"temperature": {"value": None}}}
            if "api.open-meteo.com/v1/forecast" in url:
                self.urls.append(url)
                raise JsonHttpError("Open-Meteo current conditions unavailable")
            if url.endswith("/forecast/hourly"):
                self.urls.append(url)
                return {
                    "properties": {
                        "periods": [
                            {
                                "startTime": "2026-08-25T12:00:00-04:00",
                                "isDaytime": True,
                                "temperature": 71,
                                "temperatureUnit": "F",
                                "shortForecast": "Rain Showers",
                            }
                        ]
                    }
                }
            return super().get_json(url, timeout=timeout)

    client = MissingObservationClient(nws=True)
    result = HybridWeatherProvider(client, monotonic=lambda: 100.0).fetch(_settings(40.7, -74.0))

    data = result.content[0].data
    assert data["temperature"] == 71
    assert data["icon"] == "rain"


def test_weather_location_resolver_canonicalizes_a_zip() -> None:
    class GeocoderClient:
        def get_json(self, url: str, *, timeout: float):
            assert "name=07030" in url
            assert "countryCode=US" in url
            return {
                "results": [
                    {
                        "name": "Hoboken",
                        "latitude": 40.74399,
                        "longitude": -74.03236,
                        "postcodes": ["07030"],
                    }
                ]
            }

    resolved = WeatherLocationResolver(GeocoderClient()).resolve("07030")

    assert resolved == {
        "weather_city": "Hoboken",
        "weather_lat": 40.74399,
        "weather_lon": -74.03236,
    }
