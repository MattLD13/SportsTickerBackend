"""Render flight panels from cached data and assets."""

from __future__ import annotations

from typing import Any

from PIL import Image, ImageDraw

from ticker_core.context import RenderContext
from ticker_core.features.utility.primitives import PANEL_H, PANEL_W, tiny_text
from ticker_core.features.utility.renderer import EmptyLogoSource, LogoSource
from ticker_core.rendering import ContentScene, FontSet, RenderedContent


BOARD_ROWS = 4
CITY_CHARS = 22
BOARD_RULE = (30, 60, 100)
BOARD_ALT = (70, 90, 120)
BOARD_WX = (90, 110, 140)
BOARD_WX_CHARS = 24


class FlightRenderer:
    """Render visitor tracking and airport HUD content."""

    _bg = (5, 5, 8)
    _amber = (255, 170, 0)
    _blue = (80, 180, 255)
    _white = (220, 220, 230)
    _green = (80, 255, 80)
    _red = (255, 60, 60)
    _grey = (120, 120, 130)

    def __init__(self, fonts: FontSet, logos: LogoSource | None = None) -> None:
        self._fonts = fonts
        self._logos = logos or EmptyLogoSource()

    def render(self, context: RenderContext, scene: ContentScene) -> RenderedContent:
        """Render one flight content item."""
        del context
        item_type = str(scene.item.get("type", "")).lower()
        if item_type == "flight_visitor":
            return RenderedContent(self.visitor(scene.item))
        if item_type == "flight_airport_hud":
            return RenderedContent(
                self.airport(
                    scene.item.get("weather"),
                    scene.item.get("arrivals", []),
                    scene.item.get("departures", []),
                ),
            )
        raise ValueError(f"FlightRenderer cannot render {item_type!r}.")

    def visitor(self, item: Any) -> Image.Image:
        """Render one tracked visitor flight."""
        game = item if isinstance(item, dict) else {}
        image = Image.new("RGBA", (PANEL_W, PANEL_H), (0, 0, 0, 255))
        draw = ImageDraw.Draw(image)
        guest = str(game.get("guest_name", game.get("id", "???")))
        flight_id = str(game.get("id", "???"))
        origin = str(game.get("origin_city", "???"))
        destination = str(game.get("dest_city", "???"))
        altitude = self._integer(game.get("alt"))
        distance = self._integer(game.get("dist"))
        speed = self._integer(game.get("speed"))
        eta = str(game.get("eta_str", "--"))
        progress = self._integer(game.get("progress"))
        status = str(game.get("status", "scheduled"))
        live = bool(game.get("is_live", False))
        delayed = bool(game.get("is_delayed", False)) or self._integer(game.get("delay_min")) > 0 or "delay" in status.lower()
        aircraft = str(game.get("aircraft_type", "")).strip()[:60]
        plane_color = self._red if delayed else self._green if live else self._amber
        self._plane(draw, 6, 2, plane_color)
        logo_width, logo_x = 22, PANEL_W - 28
        logo_url = self._logo_url(game)
        logo = self._logos.get(logo_url, (logo_width, logo_width)) if logo_url else None
        if logo is not None:
            image.alpha_composite(logo, (logo_x, 1))
        if guest.upper() != flight_id.upper() and flight_id.lower() != "flight_blank":
            tiny_text(draw, logo_x - len(flight_id) * 5 - 5, 2, flight_id, self._grey, self._fonts.tiny)
        tiny_text(draw, 14, 2, guest, self._amber, self._fonts.tiny)
        tiny_text(draw, 6, 10, f"{origin} > {destination}", self._blue, self._fonts.tiny)
        suffix = f"  {aircraft}" if aircraft else ""
        if live:
            tiny_text(draw, 6, 18, f"{distance} MI  {eta}  {speed} MPH  {altitude:,} FT{suffix}", self._white, self._fonts.tiny)
        else:
            tiny_text(draw, 6, 18, f"{status.upper()}{suffix}", self._amber, self._fonts.tiny)
        bar_x, bar_y, bar_width = 6, 27, 372
        background, fill = ((60, 10, 10), self._red) if delayed else ((15, 35, 15), self._green)
        draw.rectangle((bar_x, bar_y, bar_x + bar_width, bar_y + 3), fill=background)
        ratio = progress / 100.0 if live else 0.02
        draw.rectangle((bar_x, bar_y, bar_x + int(bar_width * max(0.02, min(0.98, ratio))), bar_y + 3), fill=fill)
        return image

    def airport(self, weather: object, arrivals: object, departures: object) -> Image.Image:
        """Render the combined airport HUD."""
        weather_item = weather if isinstance(weather, dict) else {}
        inbound = arrivals if isinstance(arrivals, list) else []
        outbound = departures if isinstance(departures, list) else []
        image = Image.new("RGBA", (PANEL_W, PANEL_H), (0, 0, 0, 255))
        draw = ImageDraw.Draw(image)
        code = str(weather_item.get("iata") or weather_item.get("home_abbr", "")).strip().upper()[:10]
        city = str(weather_item.get("city", "")).strip().upper()[:12]
        x = 3
        if code:
            tiny_text(draw, x, 0, code, self._blue, self._fonts.tiny)
            x += len(code) * 5 + 5
        if city:
            tiny_text(draw, x, 0, city, self._blue, self._fonts.tiny)
            x += len(city) * 5 + 5
        tiny_text(draw, x, 0, "INBOUND", self._green, self._fonts.tiny)
        tiny_text(draw, 196, 0, "OUTBOUND", self._red, self._fonts.tiny)
        if weather_item:
            label = f"{weather_item.get('away_abbr', '--')} {weather_item.get('status', '')}".strip().upper()
            if len(label) > BOARD_WX_CHARS:
                label = label[:BOARD_WX_CHARS].rsplit(" ", 1)[0]
            tiny_text(draw, PANEL_W - len(label) * 5 - 3, 0, label, BOARD_WX, self._fonts.tiny)
        draw.rectangle((0, 6, PANEL_W, 6), fill=BOARD_RULE)
        draw.rectangle((190, 8, 190, 31), fill=BOARD_RULE)
        self._side(draw, inbound, 3, 188, self._green, "NO INBOUND")
        self._side(draw, outbound, 196, 381, self._red, "NO OUTBOUND")
        return image

    def _side(self, draw: ImageDraw.ImageDraw, rows: list[object], x: int, edge: int, color: tuple[int, int, int], empty: str) -> None:
        if not rows:
            tiny_text(draw, x, 9, empty, self._grey, self._fonts.tiny)
            return
        for index, row in enumerate(rows[:BOARD_ROWS]):
            item = row if isinstance(row, dict) else {}
            y = 9 + index * 6
            flight_number = str(item.get("flight_number", "---")).upper()[:8]
            airport_code = str(item.get("airport_code", "---")).upper()[:3]
            city = str(item.get("airport_city", "---")).upper()[:CITY_CHARS]
            tiny_text(draw, x, y, flight_number, color, self._fonts.tiny)
            code_x = x + len(flight_number) * 5 + 4
            tiny_text(draw, code_x, y, airport_code, self._grey, self._fonts.tiny)
            city_x = code_x + len(airport_code) * 5 + 4
            max_city_chars = max(0, (edge - city_x) // 5)
            tiny_text(draw, city_x, y, city[:max_city_chars], self._white, self._fonts.tiny)

    @staticmethod
    def _integer(value: object) -> int:
        try:
            return int(float(value or 0))
        except (TypeError, ValueError):
            return 0

    @staticmethod
    def _plane(draw: ImageDraw.ImageDraw, x: int, y: int, color: tuple[int, int, int]) -> None:
        for px, py in ((x + 2, y), (x + 1, y + 1), (x + 2, y + 1), (x + 3, y + 1), (x, y + 2), (x + 1, y + 2), (x + 2, y + 2), (x + 3, y + 2), (x + 4, y + 2), (x + 2, y + 3), (x + 1, y + 4), (x + 2, y + 4), (x + 3, y + 4)):
            if 0 <= px < PANEL_W and 0 <= py < PANEL_H:
                draw.point((px, py), fill=color)

    @staticmethod
    def _logo_url(item: dict[str, Any]) -> str:
        url = str(item.get("airline_logo") or "").strip()
        if url:
            return url
        for key in ("airline_iata", "airline_code", "airline_icao", "airline"):
            code = str(item.get(key) or "").strip().upper().replace(" ", "")
            if len(code) in (2, 3) and code.isalnum():
                return f"https://www.google.com/s2/favicons?domain={FlightRenderer._domain(code)}&sz=64"
        code = str(item.get("away_abbr") or "").strip().upper().replace(" ", "")
        if len(code) in (2, 3) and code.isalnum():
            return f"https://www.google.com/s2/favicons?domain={FlightRenderer._domain(code)}&sz=64"
        return ""

    @staticmethod
    def _domain(code: str) -> str:
        return {"UA": "united.com", "DL": "delta.com", "AA": "aa.com", "WN": "southwest.com", "B6": "jetblue.com", "AS": "alaskaair.com", "AC": "aircanada.com", "BA": "britishairways.com", "LH": "lufthansa.com", "AF": "airfrance.us", "KL": "klm.com", "EK": "emirates.com"}.get(code, f"{code.lower()}.com")
