"""Draw the tracked visitor flight and the airport arrivals and departures board."""
from __future__ import annotations

from typing import Any

from PIL import Image, ImageDraw

from ticker.panel.frame import ContentScene, ItemKey, Logos, NoLogos, RenderContext, RenderedContent
from ticker.panel.layers import ImageTemplates
from ticker.panel.text import FontSet, draw_tiny

WIDTH, HEIGHT = 384, 32
AMBER, BLUE, WHITE = (255, 170, 0), (80, 180, 255), (220, 220, 230)
GREEN, RED, GREY = (80, 255, 80), (255, 60, 60), (120, 120, 130)
RULE, WEATHER = (30, 60, 100), (90, 110, 140)
BOARD_ROWS, CITY_CHARS, WEATHER_CHARS = 4, 22, 24
# The plane icon: five rows that point up and to the right.
PLANE = ((2, 0), (1, 1), (2, 1), (3, 1), (0, 2), (1, 2), (2, 2), (3, 2), (4, 2), (2, 3), (1, 4), (2, 4), (3, 4))


class FlightCard:
    def __init__(self, fonts: FontSet, logos: Logos | None = None) -> None:
        self._key = ItemKey("flight")
        self._logos = logos or NoLogos()
        self._boards = ImageTemplates(capacity=16, max_bytes=1024 * 1024)

    def visual_key(self, context: RenderContext, scene: ContentScene, asset_revision: int | None = None) -> object:
        return self._key(scene, asset_revision, None)

    def render(self, context: RenderContext, scene: ContentScene) -> RenderedContent:
        kind = str(scene.item.get("type", "")).lower()
        if kind == "flight_visitor":
            return RenderedContent(self.visitor(scene.item))
        if kind == "flight_airport_hud":
            item = scene.item
            return RenderedContent(self.board(item.get("weather"), item.get("arrivals", []), item.get("departures", [])))
        raise ValueError(f"FlightCard cannot draw {kind!r}.")

    def visitor(self, item: object) -> Image.Image:
        flight = item if isinstance(item, dict) else {}
        image = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 255))
        draw = ImageDraw.Draw(image)
        guest = str(flight.get("guest_name", flight.get("id", "???")))
        number = str(flight.get("id", "???"))
        status = str(flight.get("status", "scheduled"))
        live = bool(flight.get("is_live", False))
        delayed = bool(flight.get("is_delayed", False)) or _number(flight.get("delay_min")) > 0 or "delay" in status.lower()
        aircraft = str(flight.get("aircraft_type", "")).strip()[:60]
        for dx, dy in PLANE:
            draw.point((6 + dx, 2 + dy), fill=RED if delayed else GREEN if live else AMBER)
        logo_x, logo_size = WIDTH - 28, 22
        url = str(flight.get("airline_logo") or "").strip()
        logo = self._logos.get(url, (logo_size, logo_size)) if url else None
        if logo is not None:
            image.alpha_composite(logo, (logo_x, 1))
        if guest.upper() != number.upper() and number.lower() != "flight_blank":
            draw_tiny(draw, logo_x - len(number) * 5 - 5, 2, number, GREY)
        draw_tiny(draw, 14, 2, guest, AMBER)
        draw_tiny(draw, 6, 10, f"{flight.get('origin_city', '???')} > {flight.get('dest_city', '???')}", BLUE)
        suffix = f"  {aircraft}" if aircraft else ""
        if live:
            facts = (f"{_number(flight.get('dist'))} MI  {flight.get('eta_str', '--')}  {_number(flight.get('speed'))} MPH  "
                     f"{_number(flight.get('alt')):,} FT{suffix}")
            draw_tiny(draw, 6, 18, facts, WHITE)
        else:
            draw_tiny(draw, 6, 18, f"{status.upper()}{suffix}", AMBER)
        rail, fill = ((60, 10, 10), RED) if delayed else ((15, 35, 15), GREEN)
        ratio = _number(flight.get("progress")) / 100.0 if live else 0.02
        draw.rectangle((6, 27, 378, 30), fill=rail)
        draw.rectangle((6, 27, 6 + int(372 * max(0.02, min(0.98, ratio))), 30), fill=fill)
        return image

    def board(self, weather: object, arrivals: object, departures: object) -> Image.Image:
        conditions = weather if isinstance(weather, dict) else {}
        code = str(conditions.get("iata") or conditions.get("home_abbr", "")).strip().upper()[:10]
        city = str(conditions.get("city", "")).strip().upper()[:12]
        label = ""
        if conditions:
            label = f"{conditions.get('away_abbr', '--')} {conditions.get('status', '')}".strip().upper()
            if len(label) > WEATHER_CHARS:
                label = label[:WEATHER_CHARS].rsplit(" ", 1)[0]
        header = (code, city, bool(conditions), label)
        image = self._boards.render(header, lambda: _board_header(*header))
        draw = ImageDraw.Draw(image)
        _board_side(draw, arrivals if isinstance(arrivals, list) else [], 3, 188, GREEN, "NO INBOUND")
        _board_side(draw, departures if isinstance(departures, list) else [], 196, 381, RED, "NO OUTBOUND")
        return image


def _board_header(code: str, city: str, has_weather: bool, label: str) -> Image.Image:
    image = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 255))
    draw = ImageDraw.Draw(image)
    x = 3
    for text in (code, city):
        if text:
            draw_tiny(draw, x, 0, text, BLUE)
            x += len(text) * 5 + 5
    draw_tiny(draw, x, 0, "INBOUND", GREEN)
    draw_tiny(draw, 196, 0, "OUTBOUND", RED)
    if has_weather:
        draw_tiny(draw, WIDTH - len(label) * 5 - 3, 0, label, WEATHER)
    draw.rectangle((0, 6, WIDTH, 6), fill=RULE)
    draw.rectangle((190, 8, 190, 31), fill=RULE)
    return image


def _board_side(draw: ImageDraw.ImageDraw, rows: list[Any], x: int, edge: int, color: tuple[int, int, int], empty: str) -> None:
    if not rows:
        draw_tiny(draw, x, 9, empty, GREY)
        return
    for index, row in enumerate(rows[:BOARD_ROWS]):
        flight = row if isinstance(row, dict) else {}
        y = 9 + index * 6
        number = str(flight.get("flight_number", "---")).upper()[:8]
        airport = str(flight.get("airport_code", "---")).upper()[:3]
        city = str(flight.get("airport_city", "---")).upper()[:CITY_CHARS]
        draw_tiny(draw, x, y, number, color)
        code_x = x + len(number) * 5 + 4
        draw_tiny(draw, code_x, y, airport, GREY)
        city_x = code_x + len(airport) * 5 + 4
        draw_tiny(draw, city_x, y, city[:max(0, (edge - city_x) // 5)], WHITE)


def _number(value: object) -> int:
    try:
        return int(float(value or 0))
    except (TypeError, ValueError):
        return 0
