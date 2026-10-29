"""Weather from Open-Meteo: the current conditions and a three-day forecast."""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from ticker3.sdk.feature import Feature, Poll

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
READ_SECONDS = 600

# WMO weather interpretation codes, as Open-Meteo documents them.
CONDITIONS = {
    0: ("sun", "Clear"), 1: ("partly", "Mostly clear"), 2: ("partly", "Partly cloudy"), 3: ("cloud", "Cloudy"),
    45: ("fog", "Fog"), 48: ("fog", "Fog"),
    51: ("rain", "Drizzle"), 53: ("rain", "Drizzle"), 55: ("rain", "Drizzle"), 56: ("rain", "Freezing drizzle"), 57: ("rain", "Freezing drizzle"),
    61: ("rain", "Light rain"), 63: ("rain", "Rain"), 65: ("rain", "Heavy rain"), 66: ("rain", "Freezing rain"), 67: ("rain", "Freezing rain"),
    71: ("snow", "Light snow"), 73: ("snow", "Snow"), 75: ("snow", "Heavy snow"), 77: ("snow", "Snow grains"),
    80: ("rain", "Showers"), 81: ("rain", "Showers"), 82: ("rain", "Heavy showers"), 85: ("snow", "Snow showers"), 86: ("snow", "Snow showers"),
    95: ("storm", "Thunderstorm"), 96: ("storm", "Thunderstorm"), 99: ("storm", "Thunderstorm"),
}

MANIFEST = {
    "feature": "weather",
    "title": "Weather",
    "version": "1",
    "settings": {"fields": {
        "latitude": {"type": "float", "min": -90, "max": 90, "required": True},
        "longitude": {"type": "float", "min": -180, "max": 180, "required": True},
        "units": {"type": "enum", "values": ["f", "c"], "default": "f"},
        "label": {"type": "string", "default": "", "max_length": 16, "role": "view"},
    }},
    "templates": json.loads(Path(__file__).with_name("templates.json").read_text(encoding="utf-8")),
}


def forecast_url(config: dict[str, Any]) -> str:
    metric = config["units"] == "c"
    return FORECAST_URL + "?" + urlencode({
        "latitude": config["latitude"], "longitude": config["longitude"],
        "current": "temperature_2m,weather_code,wind_speed_10m,is_day",
        "daily": "weather_code,temperature_2m_max,temperature_2m_min",
        "temperature_unit": "celsius" if metric else "fahrenheit", "wind_speed_unit": "kmh" if metric else "mph",
        "timezone": "auto", "forecast_days": 4,
    })


def records(payload: dict[str, Any], config: dict[str, Any]) -> list[dict[str, Any]]:
    """Return the record `now` with the current conditions and the next three days."""
    current, daily = payload["current"], payload["daily"]
    icon, condition = CONDITIONS.get(int(current["weather_code"]), ("cloud", "Unknown"))
    if icon == "sun" and not current.get("is_day", 1):
        icon = "moon"
    values: dict[str, Any] = {
        "temp": f"{round(current['temperature_2m'])}°",
        "icon": icon, "condition": condition,
        "hi": f"{round(daily['temperature_2m_max'][0])}°", "lo": f"{round(daily['temperature_2m_min'][0])}°",
        "wind": f"{round(current['wind_speed_10m'])} {'km/h' if config['units'] == 'c' else 'mph'}",
        "observed": current["time"],
    }
    for index in range(1, min(4, len(daily["time"]))):
        day_icon, _ = CONDITIONS.get(int(daily["weather_code"][index]), ("cloud", "Unknown"))
        values.update({
            f"day{index}.name": date.fromisoformat(daily["time"][index]).strftime("%a").upper(),
            f"day{index}.icon": day_icon,
            f"day{index}.hi": f"{round(daily['temperature_2m_max'][index])}°",
            f"day{index}.lo": f"{round(daily['temperature_2m_min'][index])}°",
        })
    return [{"id": "now", "template": "weather.now", "values": values}]


class Weather(Feature):
    manifest = MANIFEST

    async def poll(self, config, context):
        payload = await context.http.get_json(forecast_url(config), reuse=60)
        return Poll(records(payload, config), READ_SECONDS)


def create() -> Weather:
    return Weather()
