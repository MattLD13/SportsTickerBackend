"""Draw the weather panel: current conditions on the left and five forecast days on the right."""
from __future__ import annotations

import math
from datetime import datetime, timedelta

from PIL import Image, ImageDraw

from ticker.six.ui import weather_art as art
from ticker.six.ui.frame import ContentScene, ItemKey, RenderContext, RenderedContent
from ticker.six.ui.text import FontSet, draw_tiny, plain_text

WIDTH, HEIGHT = 384, 32
CURRENT_WIDTH = 124
FORECAST_X = CURRENT_WIDTH + 1
FORECAST_COLUMN = (WIDTH - FORECAST_X) // 5
FORECAST_DAYS = 5
UNKNOWN_TEMPERATURE = (240, 240, 245)
MISSING_TEXT = (70, 88, 120)
CONDITION_ABBREVIATIONS = {
    "PARTLY CLOUDY": "PARTLY CLDY", "MOSTLY CLOUDY": "MOSTLY CLDY", "SCATTERED SHOWERS": "SCT SHOWERS",
    "THUNDERSTORMS": "T-STORMS", "THUNDERSTORM": "T-STORM", "LIGHT RAIN": "LGT RAIN",
}


class WeatherCard:
    def __init__(self, fonts: FontSet) -> None:
        self._key = ItemKey("weather")
        self._temperature_font = fonts.big

    def visual_key(self, context: RenderContext, scene: ContentScene, asset_revision: int | None = None) -> object:
        # The sky moves at 30 frames each second.
        return self._key(scene, asset_revision, int(context.now.timestamp() * 30))

    def render(self, context: RenderContext, scene: ContentScene) -> RenderedContent:
        return RenderedContent(self.frame(context.now, scene.item))

    def frame(self, now: datetime, item: object) -> Image.Image:
        weather = item if isinstance(item, dict) else {}
        image = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 255))
        draw = ImageDraw.Draw(image)
        situation = weather.get("situation", {}) or {}
        stats = situation.get("stats", {}) or {}
        icon = situation.get("icon", "cloud")
        t = art.loop_time(now.timestamp())
        sky = _Sky.of(situation, icon, now)

        draw.rectangle((0, 0, WIDTH - 1, HEIGHT - 1), fill=art.sky_tint(icon))
        draw.line((0, 0, WIDTH - 1, 0), fill=art.DEEP_BLUE)
        # A flat fill, not a vertical ramp. A dark 32-row ramp shows as hard PWM bands on the panel.
        top, bottom = art.sky_colors(icon, sky.elevation, sky.cloud)
        draw.rectangle((0, 0, CURRENT_WIDTH, HEIGHT - 1),
                       fill=tuple(int(round(max(0.0, min(255.0, value)))) for value in art.mix(top, bottom, 0.55)))
        if any(word in icon.lower() for word in ("rain", "snow", "storm")):
            art.draw_sky_motion(image, draw, icon, 0, 0, CURRENT_WIDTH, 32, t)
        elif sky.night:
            # Stars show only at night, and cloud thins them.
            art.draw_sky_motion(image, draw, "sun", 0, 0, CURRENT_WIDTH, 32, t, dim=1.0 - (sky.cloud or 0.0),
                                mask_moon=sky.icon == "moon")
        draw.line((CURRENT_WIDTH, 0, CURRENT_WIDTH, 31), fill=art.DEEP_BLUE)
        self._current(draw, weather, stats, sky.icon, t)
        days = tuple(situation.get("forecast", []) or ())[:FORECAST_DAYS]
        # Draw every column background first, then the labels on top.
        for index, day in enumerate(days):
            _forecast_background(image, draw, index, day, t + index * 1.7)
        for index, day in enumerate(days):
            _forecast_labels(draw, now, index, day, t + index * 1.7)
        for index in range(len(days), FORECAST_DAYS):
            _missing_day(draw, now, index)
        return image

    def _current(self, draw: ImageDraw.ImageDraw, weather: dict, stats: dict, icon: str, t: float) -> None:
        temperature = str(weather.get("home_abbr", "--")).replace("°", "").strip()
        draw_tiny(draw, 4, 2, plain_text(str(weather.get("away_abbr", "CITY")).upper()).strip()[:15], (125, 170, 230))
        art.draw_icon(draw, icon, 3, 11, t)
        draw.text((24, 10), f"{temperature or '--'}°F", font=self._temperature_font, fill=_temperature_color(temperature))
        aqi, uv, feels, wind, humidity = (_stat(stats, key) for key in ("aqi", "uv", "feels", "wind", "humidity"))
        condition = plain_text(str(weather.get("status", "")).upper()).strip()
        condition = CONDITION_ABBREVIATIONS.get(condition, condition)[:19]
        if feels != "--":
            draw_tiny(draw, 24, 25, f"FEELS {feels}F", _temperature_color(feels))
        elif condition:
            draw_tiny(draw, 24, 25, condition, (105, 145, 190))
        for box, label, value, color, nudge in (
            ((74, 1, 121, 7), "AQI", aqi[:4], _aqi_color(aqi), 0),
            ((74, 9, 121, 15), "UV", uv[:4], (210, 155, 255), 0),
            ((74, 17, 121, 23), "HUM", humidity[:3] + "%", (90, 200, 255), 0),
            ((74, 25, 121, 31), "WIND", wind[:3], (90, 200, 255), 2),
        ):
            _stat_box(draw, box, label, value, color, nudge)


class _Sky:
    """The sun height, cloud cover, night state, and drawn icon of the current conditions."""

    def __init__(self, elevation: float, cloud: float | None, night: bool, icon: str) -> None:
        self.elevation, self.cloud, self.night, self.icon = elevation, cloud, night, icon

    @classmethod
    def of(cls, situation: dict, icon: str, now: datetime) -> _Sky:
        percent = situation.get("cloud_cover")
        cloud = None if percent is None else max(0.0, min(1.0, float(percent) / 100.0))
        # The observation time is local to the weather location, so it compares directly with sunrise and sunset.
        observed = art.minutes(situation.get("obs_time"))
        minute = observed if observed is not None else now.hour * 60 + now.minute
        day_flag = situation.get("is_day")
        night = not int(day_flag) if day_flag is not None else now.hour < 6 or now.hour >= 20
        elevation = art.sun_elevation(minute, art.minutes(situation.get("sunrise")), art.minutes(situation.get("sunset")))
        if day_flag is not None and ((night and elevation > 0) or (not night and elevation < 0)):
            # The backend day flag decides the sign of the sun height.
            elevation = -elevation
        drawn = str(icon).lower()
        if night and ("sun" in drawn or "clear" in drawn):
            drawn = "moon"
        return cls(elevation, cloud, night, drawn)


def _stat_box(draw: ImageDraw.ImageDraw, box, label: str, value: str, color, nudge: int) -> None:
    """Draw one 6-pixel label and value box."""
    draw.rectangle(box, fill=(2, 6, 14), outline=art.DEEP_BLUE)
    middle = (box[0] + box[2]) // 2
    y = box[1] + ((box[3] - box[1] + 1) - 5) // 2
    draw_tiny(draw, box[0] + ((middle - box[0]) - len(label) * 5) // 2 + nudge, y, label, (95, 120, 160))
    draw_tiny(draw, middle + ((box[2] - middle + 1) - len(value) * 5) // 2 + nudge, y, value, color)


def _column(index: int) -> tuple[int, int]:
    left = FORECAST_X + index * FORECAST_COLUMN
    return left, WIDTH - 1 if index == 4 else left + FORECAST_COLUMN - 1


def _forecast_background(image: Image.Image, draw: ImageDraw.ImageDraw, index: int, day: dict, t: float) -> None:
    left, right = _column(index)
    icon = day.get("icon", "cloud")
    tint = art.sky_tint(icon)
    draw.rectangle((left, 0, right, 31), fill=tint if index % 2 == 0 else tuple(max(0, channel - 1) for channel in tint))
    density, wind = 1.0, 0.0
    if day.get("pop") is not None:
        # The chance of rain sets the particle density. The sigmoid centers on 40%, where chances cluster.
        density = 1.0 / (1.0 + math.exp(-(float(day["pop"]) / 100.0 - 0.40) / 0.16))
    if day.get("wind") is not None:
        # The peak wind of the day leans the streaks.
        wind = max(-0.9, min(0.9, (float(day["wind"]) - 3.0) / 12.0))
    art.draw_sky_motion(image, draw, icon, left, 0, right - left + 1, 32, t, dim=0.0, density=density, wind=wind)
    if index < 4:
        draw.line((right, 3, right, 29), fill=art.DEEP_BLUE)


def _forecast_labels(draw: ImageDraw.ImageDraw, now: datetime, index: int, day: dict, t: float) -> None:
    left, right = _column(index)
    width = right - left + 1
    _day_heading(draw, now, index, left, right)
    art.draw_icon(draw, day.get("icon", "cloud"), left + max(0, (width - 16) // 2), 9, t)
    high = str(day.get("high", "--")).replace("°", "")
    low = str(day.get("low", "--")).replace("°", "")
    _high_low(draw, left, width, high, low, (255, 115, 75), (90, 165, 255))


def _missing_day(draw: ImageDraw.ImageDraw, now: datetime, index: int) -> None:
    """A day that the backend did not send shows its name and no values."""
    left, right = _column(index)
    if index < FORECAST_DAYS - 1:
        draw.line((right, 3, right, 29), fill=art.DEEP_BLUE)
    _day_heading(draw, now, index, left, right)
    _high_low(draw, left, right - left + 1, "--", "--", MISSING_TEXT, MISSING_TEXT)


def _day_heading(draw: ImageDraw.ImageDraw, now: datetime, index: int, left: int, right: int) -> None:
    width = right - left + 1
    name = "TODAY" if index == 0 else (now + timedelta(days=index)).strftime("%a").upper()
    draw_tiny(draw, left + max(0, (width - len(name) * 5) // 2), 2, name, (255, 255, 255) if index == 0 else (110, 160, 220))
    draw.line((left + 4, 8, right - 4, 8), fill=art.DEEP_BLUE)


def _high_low(draw: ImageDraw.ImageDraw, left: int, width: int, high: str, low: str, high_color, low_color) -> None:
    x = left + max(0, (width - (len(high) * 5 + 5 + len(low) * 5)) // 2)
    draw_tiny(draw, x, 26, high, high_color)
    draw_tiny(draw, x + len(high) * 5, 26, "/", MISSING_TEXT)
    draw_tiny(draw, x + len(high) * 5 + 5, 26, low, low_color)


def _temperature_color(text: object):
    """Return the color of a Fahrenheit reading, or a neutral color when the text is not a number."""
    try:
        value = int(float(text))
    except (TypeError, ValueError, OverflowError):
        return UNKNOWN_TEMPERATURE
    return ((255, 90, 35) if value >= 90 else (255, 185, 40) if value >= 75 else (95, 225, 105) if value >= 55
            else (95, 190, 255) if value >= 35 else (190, 230, 255))


def _aqi_color(aqi: object):
    try:
        value = int(aqi)
    except (TypeError, ValueError, OverflowError):
        return (100, 100, 100)
    return (0, 255, 0) if value <= 50 else (255, 255, 0) if value <= 100 else (255, 126, 0) if value <= 150 else (255, 0, 0)


def _stat(stats: dict, key: str) -> str:
    return str(stats.get(key, "--")).strip() or "--"
