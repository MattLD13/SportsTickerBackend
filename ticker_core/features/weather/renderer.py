"""Render deterministic animated weather panels."""

from __future__ import annotations

import math
from typing import Any

from PIL import Image, ImageDraw

from ticker_core.context import RenderContext
from ticker_core.features.utility.primitives import PANEL_H, PANEL_W, normal_text, tiny_text
from ticker_core.rendering import ContentScene, FontSet, RenderedContent
from .legacy_port import PreparedWeatherRenderer


class WeatherRenderer:
    """Render weather details without backend or network calls."""

    def __init__(self, fonts: FontSet) -> None:
        self._fonts = fonts

    def render(self, context: RenderContext, scene: ContentScene) -> RenderedContent:
        """Render a weather content item."""
        return RenderedContent(self.detailed(context, scene.item), static=True)

    def detailed(self, context: RenderContext, item: object) -> Image.Image:
        """Render the current weather and forecast view."""
        game = item if isinstance(item, dict) else {}
        return PreparedWeatherRenderer(self._fonts, context.now).draw_weather_detailed(game)
        situation = game.get("situation", {})
        situation = situation if isinstance(situation, dict) else {}
        stats = situation.get("stats", {})
        stats = stats if isinstance(stats, dict) else {}
        forecast = situation.get("forecast", [])
        forecast = forecast if isinstance(forecast, list) else []
        icon = str(situation.get("icon", "cloud"))
        t = context.now.timestamp()
        image = Image.new("RGBA", (PANEL_W, PANEL_H), (0, 0, 0, 255))
        draw = ImageDraw.Draw(image)
        sky = self._sky(icon, situation, context)
        draw.rectangle((0, 0, 123, 31), fill=sky)
        draw.rectangle((124, 0, 383, 31), fill=(5, 7, 14))
        draw.line((124, 0, 124, 31), fill=(18, 45, 95))
        self._ambient(draw, icon, 0, 0, 124, 32, t)
        city = normal_text(game.get("away_abbr", "CITY")).upper()[:15]
        tiny_text(draw, 4, 2, city, (125, 170, 230), self._fonts.tiny)
        self._icon(draw, icon, 3, 11, t)
        temp = normal_text(game.get("home_abbr", "--")).replace("o", "") or "--"
        draw.text((24, 10), f"{temp}°F", font=self._fonts.big, fill=self._temperature_color(temp))
        condition = normal_text(game.get("status", "")).upper()[:18]
        tiny_text(draw, 24, 25, condition, (180, 195, 220), self._fonts.tiny)
        self._stat(draw, 58, 10, "FEEL", stats.get("feels", "--"), self._temperature_color(stats.get("feels", "--")))
        self._stat(draw, 89, 10, "WIND", stats.get("wind", "--"), (120, 190, 255))
        self._stat(draw, 58, 19, "HUM", stats.get("humidity", "--"), (120, 210, 230))
        self._stat(draw, 89, 19, "AQI", stats.get("aqi", "--"), self._aqi_color(stats.get("aqi")))
        self._forecast(draw, forecast[:5], t)
        return image

    def _forecast(self, draw: ImageDraw.ImageDraw, forecast: list[object], t: float) -> None:
        start, width = 128, 51
        for index in range(5):
            entry = forecast[index] if index < len(forecast) and isinstance(forecast[index], dict) else {}
            x = start + index * width
            if index:
                draw.line((x - 2, 1, x - 2, 30), fill=(18, 30, 52))
            label = normal_text(entry.get("day", entry.get("label", ""))).upper()[:4]
            tiny_text(draw, x + 2, 2, label, (130, 160, 205), self._fonts.tiny)
            self._icon(draw, str(entry.get("icon", "cloud")), x + 16, 9, t + index * 1.7)
            high = normal_text(entry.get("high", entry.get("temp", "--"))).replace("o", "")
            low = normal_text(entry.get("low", "")).replace("o", "")
            tiny_text(draw, x + 3, 25, f"{high}/{low}" if low else high, self._temperature_color(high), self._fonts.tiny)

    def _stat(self, draw: ImageDraw.ImageDraw, x: int, y: int, label: str, value: object, color: tuple[int, int, int]) -> None:
        tiny_text(draw, x, y, label, (100, 120, 155), self._fonts.tiny)
        tiny_text(draw, x, y + 6, normal_text(value)[:6], color, self._fonts.tiny)

    @staticmethod
    def _sky(icon: str, situation: dict[str, Any], context: RenderContext) -> tuple[int, int, int]:
        day = situation.get("is_day")
        if day is None:
            day = 6 <= context.now.hour < 20
        lowered = icon.lower()
        if "storm" in lowered:
            return 7, 2, 12
        if "rain" in lowered:
            return 4, 7, 16
        if "snow" in lowered:
            return 9, 11, 20
        if not day:
            return 0, 1, 9
        if "sun" in lowered or "clear" in lowered:
            return 3, 12, 30
        return 7, 12, 24

    def _ambient(self, draw: ImageDraw.ImageDraw, icon: str, x: int, y: int, width: int, height: int, t: float) -> None:
        lowered = icon.lower()
        if "rain" in lowered or "storm" in lowered:
            for index in range(11):
                px = x + int((index * 37 % 113) + 3)
                py = y + int((t * (23 + index % 5) + index * 17) % 36) - 2
                for offset in range(3):
                    if y <= py + offset < y + height:
                        draw.point((px, py + offset), fill=(44, 80, 132))
        elif "snow" in lowered:
            for index in range(7):
                px = x + int((index * 19 % 110) + math.sin(t + index) * 2)
                py = y + int((t * (1.4 + index / 5) + index * 6) % 34)
                draw.point((px, py), fill=(80, 110, 155))
        elif not any(word in lowered for word in ("cloud", "fog", "mist")):
            for index in range(18):
                px, py = x + (index * 29 % max(1, width)), y + (index * 11 % max(1, height))
                value = int(max(0, math.sin(t * (1.4 + index / 9) + index) ** 2 * 120))
                if value:
                    draw.point((px, py), fill=(value, value, value))

    def _icon(self, draw: ImageDraw.ImageDraw, name: str, x: int, y: int, t: float) -> None:
        icon = name.lower()
        sun, cloud, rain, snow = (255, 200, 0), (205, 210, 220), (60, 130, 255), (210, 235, 255)
        if "sun" in icon or "clear" in icon:
            cx, cy = x + 7, y + 7
            draw.ellipse((cx - 5, cy - 5, cx + 5, cy + 5), fill=sun)
            for index in range(12):
                angle = index * math.tau / 12 + t * 0.5
                long = math.sin(t + index * math.pi) > 0
                length = 4 if long else 2
                draw.line((round(cx + math.cos(angle) * 8), round(cy + math.sin(angle) * 8), round(cx + math.cos(angle) * (5 + length)), round(cy + math.sin(angle) * (5 + length))), fill=(210 if long else 150, 185 if long else 130, 70))
        elif "fog" in icon or "mist" in icon or "haze" in icon:
            for index, py in enumerate((y + 3, y + 6, y + 9, y + 12)):
                offset = int(math.sin(t * 0.6 + index) * 2)
                draw.line((x + 2 + offset, py, x + 13 + offset, py), fill=(170, 175, 195))
        elif "cloud" in icon or "overcast" in icon:
            draw.ellipse((x + 0, y + 6, x + 11, y + 13), fill=(100, 105, 122))
            draw.ellipse((x + 4, y + 5, x + 15, y + 13), fill=(165, 170, 185))
            draw.ellipse((x + 3, y + 3, x + 13, y + 11), fill=(215, 218, 230))
        else:
            draw.ellipse((x + 1, y + 1, x + 14, y + 9), fill=(75, 80, 100) if "storm" in icon else cloud if "rain" in icon else (185, 195, 210))
            if "rain" in icon or "storm" in icon:
                for index in range(5):
                    py = y + 10 + int((t * 5 + index * .8) % 6)
                    draw.line((x + 3 + index * 2, py, x + 2 + index * 2, py + 2), fill=rain)
            elif "snow" in icon:
                for index in range(5):
                    draw.point((x + 3 + index * 2, y + 10 + int((t * 2 + index) % 7)), fill=snow)
            elif "storm" in icon:
                draw.line((x + 8, y + 9, x + 6, y + 13, x + 9, y + 13, x + 7, y + 16), fill=(255, 220, 0))

    @staticmethod
    def _temperature_color(value: object) -> tuple[int, int, int]:
        try:
            temp = int(float(str(value).replace("°", "").replace("o", "")))
            return (255, 90, 35) if temp >= 90 else (255, 185, 40) if temp >= 75 else (95, 225, 105) if temp >= 55 else (95, 190, 255) if temp >= 35 else (190, 230, 255)
        except ValueError:
            return 240, 240, 245

    @staticmethod
    def _aqi_color(value: object) -> tuple[int, int, int]:
        try:
            aqi = int(value)
            return (0, 255, 0) if aqi <= 50 else (255, 255, 0) if aqi <= 100 else (255, 126, 0) if aqi <= 150 else (255, 0, 0)
        except (TypeError, ValueError):
            return 100, 100, 100
