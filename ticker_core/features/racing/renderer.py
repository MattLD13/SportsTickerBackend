"""Independent IndyCar, F1, and NASCAR content renderer."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from PIL import Image, ImageDraw, ImageFilter, ImageOps

from ticker_core.context import RenderContext
from ticker_core.rendering import ContentScene, FontSet, RenderedContent
from ticker_core.rendering.pixels import TINY as TINY_FONT_MAP
from ticker_core.rendering.pixels import draw_hybrid_text, draw_tiny_text, normalize_special_chars

from .assets import RacingAssetService


PANEL_WIDTH = 384
PANEL_HEIGHT = 32
_NON_FLAG_STATES = {"WARM", "COLD", "FINAL", "OFFICIAL", "UNOFFICIAL", "ENDED", "STANDBY"}


def racing_flag_color(value: object) -> tuple[int, int, int]:
    """Return the panel color for one race control state."""
    name = str(value or "").strip().upper()
    if name in {"GREEN", "CLEAR", "ROLLING START", "FORMATION LAP", "GWC", "FLAG TO FLAG", "FTF"}:
        return (55, 190, 90)
    if name in {"YELLOW", "DOUBLE YELLOW", "CAUTION", "DEBRIS", "FCY", "FULL COURSE YELLOW", "LOCAL YELLOW", "SLOW ZONE", "CODE 60", "CODE60", "WAVE AROUND", "LUCKY DOG"}:
        return (255, 215, 0)
    if name in {"SAFETY CAR", "SC", "PACE CAR", "PACE", "VSC", "VIRTUAL SAFETY CAR", "NEUTRALISED", "NEUTRALIZED"}:
        return (255, 140, 0)
    if name in {"VSC ENDING", "SC ENDING"}:
        return (255, 185, 0)
    if name in {"RED", "RED FLAG"}:
        return (230, 70, 70)
    if name in {"WHITE", "OIL FLAG"}:
        return (230, 230, 230)
    if name == "CHECKERED":
        return (235, 235, 235)
    if name == "BLUE":
        return (60, 100, 235)
    if name in {"BLACK", "MEATBALL"}:
        return (30, 30, 30)
    if name in {"BLACK AND WHITE", "BLACK WHITE"}:
        return (130, 130, 130)
    return (110, 115, 130)


@dataclass(slots=True)
class RacingRenderer:
    """Render all racing series from explicit data and assets."""

    fonts: FontSet
    assets: RacingAssetService
    _strip_cache: dict[tuple[object, ...], tuple[tuple[Image.Image, ...], Image.Image, int]] = field(default_factory=dict)

    def render(self, context: RenderContext, scene: ContentScene) -> RenderedContent:
        """Render a racing scroll card or a full leaderboard."""
        if scene.item.get("sports_presentation") == "pinned":
            return RenderedContent(self._render_full(scene.item, scene.elapsed), static=True)
        return RenderedContent(self._render_scroll(scene.item), static=False)

    def _payload(self, item: Mapping[str, Any]) -> Mapping[str, Any]:
        sport = str(item.get("sport", "")).lower()
        if sport == "f1":
            return _mapping(item.get("f1"))
        if sport == "nascar":
            return _nascar_payload(_mapping(item.get("nascar")))
        return _mapping(item.get("indycar"))

    def _render_scroll(self, item: Mapping[str, Any]) -> Image.Image:
        width = 128
        image = Image.new("RGBA", (width, PANEL_HEIGHT), (0, 0, 0, 255))
        draw = ImageDraw.Draw(image)
        payload = self._payload(item)
        drivers = _drivers(payload)
        header = _header_label(payload)
        draw_hybrid_text(draw, 2, 2, header, (8, 8, 8, 180))
        draw_hybrid_text(draw, 1, 1, header, (255, 240, 150, 255))
        flag = _display_flag(payload.get("flag"), item.get("state", "pre"))
        _draw_mini_flag(draw, width - 12, 0, flag)
        draw.line([(0, 7), (width - 1, 7)], fill=(55, 76, 130))
        session = str(payload.get("session_type") or "Race").lower()
        qualifying = "qual" in session
        sport = str(item.get("sport", "")).lower()
        if not drivers:
            _draw_empty_or_session(draw, payload, item, width)
            return image
        draw_tiny_text(draw, 1, 8, "P", (70, 90, 140))
        draw_tiny_text(draw, 34, 8, "DRIVER", (70, 90, 140))
        label = "TIME" if qualifying and sport == "f1" else "MPH" if qualifying else "INTERVAL" if sport == "nascar" else "GAP"
        draw_tiny_text(draw, 90, 8, label, (70, 90, 140))
        for index, driver in enumerate(drivers[:3]):
            y = (13, 20, 27)[index]
            position = str(driver.get("pos") or index + 1)
            abbreviation = str(driver.get("abbr") or "???").upper()[:3]
            car = str(driver.get("car") or "").strip()
            if qualifying:
                right = str(driver.get("interval") or driver.get("gap") or "")[:12] if sport == "f1" else str(driver.get("speed") or driver.get("interval") or driver.get("gap") or "")[:7]
            else:
                right = str(driver.get("interval") or driver.get("gap") or "")[:12]
            draw_tiny_text(draw, 0, y, position, (255, 215, 0) if position == "1" else (200, 200, 200))
            primary, _ = self._driver_colors(driver)
            number = car or abbreviation
            number_width = _tiny_width(number)
            total = number_width + 2 + _tiny_width(abbreviation)
            start = max(5, int(round(34 + (_tiny_width("DRIVER") / 2) - total / 2)))
            if _luminance(primary) < 80:
                for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                    draw_tiny_text(draw, start + dx, y + dy, number, (255, 255, 255, 200))
            draw_tiny_text(draw, start, y, number, primary)
            draw_tiny_text(draw, start + number_width + 2, y, abbreviation, (255, 255, 255))
            if right:
                draw_tiny_text(draw, min(82, width - len(right) * 4 - 2), y, right, (255, 255, 255) if position == "1" else (180, 210, 255))
        return image

    def _render_full(self, item: Mapping[str, Any], elapsed: float) -> Image.Image:
        image = Image.new("RGBA", (PANEL_WIDTH, PANEL_HEIGHT), (0, 0, 0, 255))
        draw = ImageDraw.Draw(image)
        info_width = 84
        for x in range(info_width):
            draw.line([(x, 0), (x, PANEL_HEIGHT)], fill=(0, 20, 60, int(30 + 20 * x / info_width)))
        payload = self._payload(item)
        self._draw_info(draw, payload, item, info_width, elapsed)
        self._draw_driver_panel(image, payload, item, info_width, elapsed)
        return image

    def _draw_info(self, draw: ImageDraw.ImageDraw, payload: Mapping[str, Any], item: Mapping[str, Any], width: int, elapsed: float) -> None:
        name = _info_name(payload)
        session = str(payload.get("session_type") or "RACE").upper()
        state = str(item.get("state", "pre")).lower()
        flag = _display_flag(payload.get("flag"), state)
        draw.rectangle([0, 0, 2, PANEL_HEIGHT], fill=racing_flag_color(flag))
        _draw_flag(draw, width - 17, 1, flag)
        available = width - 25
        if _tiny_width(name) <= available:
            draw_tiny_text(draw, 4, 1, name, (255, 240, 150))
        else:
            loop = _tiny_width(name) + 18
            strip = Image.new("RGBA", (_tiny_width(name) * 2 + 18 + available, 7), (0, 0, 0, 0))
            strip_draw = ImageDraw.Draw(strip)
            draw_tiny_text(strip_draw, 0, 0, name, (255, 240, 150))
            draw_tiny_text(strip_draw, _tiny_width(name) + 18, 0, name, (255, 240, 150))
            crop = strip.crop((int(max(0, elapsed) * 14) % loop, 0, int(max(0, elapsed) * 14) % loop + available, 7))
            draw._image.paste(crop, (4, 1), crop)
        weather = _mapping(payload.get("weather"))
        draw_tiny_text(draw, 4, 8, session[:11], (180, 210, 255))
        _draw_weather(draw, weather)

    def _draw_driver_panel(self, image: Image.Image, payload: Mapping[str, Any], item: Mapping[str, Any], x_offset: int, elapsed: float) -> None:
        panel_width = PANEL_WIDTH - x_offset
        panel = Image.new("RGBA", (panel_width, PANEL_HEIGHT), (0, 0, 0, 0))
        drivers = sorted(_drivers(payload), key=_driver_position)
        if not drivers:
            label = _header_label(payload)
            draw_tiny_text(ImageDraw.Draw(panel), max(4, (panel_width - _tiny_width(label)) // 2), 10, label, (180, 210, 255))
            if str(item.get("state") or "").lower() == "pre":
                status = str(item.get("status") or "").strip()
                if status:
                    starts = f"STARTS {status}"
                    draw_tiny_text(ImageDraw.Draw(panel), max(4, (panel_width - _tiny_width(starts)) // 2), 18, starts, (200, 200, 200))
            image.paste(panel, (x_offset, 0), panel)
            return
        qualifying = "qual" in str(payload.get("session_type") or "").lower() or "prac" in str(payload.get("session_type") or "").lower()
        f1 = str(item.get("sport") or "").lower() == "f1"
        key = (tuple(_driver_key(driver) for driver in drivers), qualifying, f1, self.assets.revision)
        cards, strip, strip_width = self._driver_strip(drivers, qualifying, f1, key)
        if len(cards) == 1:
            panel.paste(cards[0], (max(0, (panel_width - cards[0].width) // 2), 1), cards[0])
        else:
            view = strip.crop((int(max(0, elapsed) * 20) % strip_width, 0, int(max(0, elapsed) * 20) % strip_width + panel_width, PANEL_HEIGHT))
            panel.alpha_composite(view)
        image.paste(panel, (x_offset, 0), panel)

    def _driver_strip(self, drivers: list[Mapping[str, Any]], qualifying: bool, f1: bool, key: tuple[object, ...]) -> tuple[tuple[Image.Image, ...], Image.Image, int]:
        cached = self._strip_cache.get(key)
        if cached is not None:
            return cached
        cards = tuple(self._driver_card(driver, qualifying, f1) for driver in drivers)
        gap = 6
        width = sum(card.width for card in cards) + gap * len(cards)
        strip = Image.new("RGBA", (width + PANEL_WIDTH - 84, PANEL_HEIGHT), (0, 0, 0, 0))
        x = 0
        index = 0
        while x < strip.width:
            card = cards[index % len(cards)]
            strip.paste(card, (x, 1), card)
            x += card.width + gap
            index += 1
        result = (cards, strip, width)
        self._strip_cache = {key: result}
        return result

    def _driver_card(self, driver: Mapping[str, Any], qualifying: bool, f1: bool) -> Image.Image:
        position = str(driver.get("pos") or "")
        name = str(driver.get("name") or driver.get("abbr") or "???").strip()
        car_number = str(driver.get("car") or "").strip()
        place = _ordinal(position)
        name_font = self.fonts.normal
        name_width = _text_width(name_font, name)
        if name_width > 72:
            name_font = self.fonts.tiny
            name_width = _text_width(name_font, name)
        if name_width > 84:
            name_font = self.fonts.tiny_small
            name_width = _text_width(name_font, name)
        team_logo = str(driver.get("team_logo") or "")
        car_image = str(driver.get("car_illustration") or "")
        badge_card = bool(team_logo) and (not car_image or "nascar.com" in car_image)
        if badge_card:
            width = max(PANEL_HEIGHT - 7 + int(name_width) + 18, 80)
        else:
            width = max(132, int(name_width) + 24, int(_text_width(self.fonts.normal, place) + _text_width(self.fonts.normal, car_number)) + 18)
        card = Image.new("RGBA", (width, PANEL_HEIGHT - 2), (0, 0, 0, 0))
        draw = ImageDraw.Draw(card)
        primary, secondary = self._driver_colors(driver)
        draw.rectangle([0, 0, width - 1, card.height - 1], fill=(12, 12, 18), outline=(255, 215, 0) if position == "1" else (60, 60, 72))
        image = self.assets.image(car_image, "car", (130, 20)) if car_image else None
        if image is None and car_image and "nascar.com" not in car_image:
            image = self.assets.image(car_image, "image", (120, 19))
        drew = False
        if image is not None:
            car = image.convert("RGBA")
            if "nascar.com" not in car_image:
                car = _trim_transparent_padding(car)
            car.thumbnail((120, 19), Image.Resampling.LANCZOS)
            card.paste(car, (0, max(0, card.height - car.height - 1)), car)
            drew = True
        if not drew and f1 and str(driver.get("team") or ""):
            _draw_f1_car(card, primary, secondary)
            drew = True
        if not drew and team_logo:
            badge = self.assets.image(team_logo, "logo", (card.height - 9, card.height - 9))
            if badge is not None:
                badge = badge.convert("RGBA")
                badge.thumbnail((card.height - 9, card.height - 9), Image.Resampling.LANCZOS)
                card.paste(badge, (2, 8), badge)
                drew = True
        if not drew and car_number:
            _draw_number(draw, car_number, primary, secondary, width, card.height)
        draw.text((4, 0), place, font=self.fonts.normal, fill=(255, 215, 0) if position == "1" else (180, 180, 180))
        if car_number and not drew:
            number_width = _text_width(self.fonts.normal, car_number)
            number_x = width - number_width - 5
            if _luminance(primary) < 80:
                for offset_x, offset_y in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                    draw.text((number_x + offset_x, offset_y), car_number, font=self.fonts.normal, fill=(255, 255, 255, 200))
            draw.text((number_x, 0), car_number, font=self.fonts.normal, fill=primary)
        draw.text((max(4, width - int(name_width) - 5), 10), name, font=name_font, fill=(255, 255, 255))
        right = str(driver.get("speed") or driver.get("gap") or "")[:8] if qualifying else str(driver.get("gap") or "")[:10]
        if right:
            draw_tiny_text(draw, max(4, width - _tiny_width(right) - 4), 23, right, (255, 255, 255) if position == "1" else (140, 190, 255))
        return card

    def _driver_colors(self, driver: Mapping[str, Any]) -> tuple[tuple[int, int, int], tuple[int, int, int]]:
        logo_url = str(driver.get("team_logo") or "")
        logo = self.assets.image(logo_url, "logo", (18, 18)) if logo_url else None
        if logo is not None:
            return _sample_colors(logo)
        return _hex(str(driver.get("livery_primary") or ""), (180, 180, 180)), _hex(str(driver.get("livery_secondary") or ""), (80, 80, 80))


def _mapping(value: object) -> Mapping[str, Any]:
    """Return a mapping or an empty mapping."""
    return value if isinstance(value, Mapping) else {}


def _drivers(payload: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    """Return valid driver records from one payload."""
    value = payload.get("drivers")
    return [driver for driver in value if isinstance(driver, Mapping)] if isinstance(value, list) else []


def _nascar_payload(raw: Mapping[str, Any]) -> Mapping[str, Any]:
    """Normalize the NASCAR labels used by the shared layouts."""
    value = dict(raw)
    total = int(value.get("total_laps") or 0)
    remaining = int(value.get("laps_remaining") or 0)
    raw_session = str(value.get("session_type") or "")
    session = "Xfinity" if "Xfinity" in raw_session else "Trucks" if "Truck" in raw_session else raw_session or "Race"
    value["session_name"] = "FINAL" if total and not remaining else session
    value["session_type"] = value["session_name"]
    value["short_name"] = str(value.get("short_name") or value.get("event_name") or "NASCAR")
    value["event_name"] = value["short_name"]
    return value


def _header_label(payload: Mapping[str, Any]) -> str:
    """Build the compact scroll-card header."""
    short = str(payload.get("short_name") or payload.get("event_name") or "Racing").strip().upper()
    short = short.replace("GRAND PRIX", "GP").replace("CHAMPIONSHIP", "CHAMP").replace("PRESENTED BY", "").replace("  ", " ").strip()
    session = str(payload.get("session_name") or payload.get("session_type") or "Race").strip().replace("Sprint Qualifying", "Sprint Quali").replace("Qualifying", "Quali")
    if len(short) + len(session) + 1 > 24:
        short = short[: max(4, 24 - len(session) - 1)]
    return f"{short} {session}"


def _info_name(payload: Mapping[str, Any]) -> str:
    """Build the compact full-screen race name."""
    name = str(payload.get("short_name") or payload.get("event_name") or "RACING").upper()
    for old, new in (("110TH RUNNING OF THE ", ""), ("GRAND PRIX", "GP"), ("CHAMPIONSHIP", "CHAMP"), ("PRESENTED BY", ""), ("NASCAR CUP SERIES", ""), ("NASCAR XFINITY SERIES", ""), ("NASCAR CRAFTSMAN TRUCK SERIES", ""), ("NASCAR ", "")):
        name = name.replace(old, new)
    return name.replace("  ", " ").strip()


def _display_flag(flag: object, state: object) -> str:
    """Select a real race flag from the payload state."""
    value = str(flag or "").strip().upper()
    if value == "CHKD":
        return "CHECKERED"
    if value in _NON_FLAG_STATES:
        value = ""
    if value:
        return value
    return "CHECKERED" if str(state).lower() == "post" else "WHITE" if str(state).lower() == "pre" else "GREEN"


def _draw_mini_flag(draw: ImageDraw.ImageDraw, x: int, y: int, flag: str) -> None:
    """Draw the compact scroll-card flag."""
    if flag == "CHECKERED":
        draw.rectangle([x, y + 1, x + 8, y + 6], fill=(240, 240, 240))
        for row in range(y + 1, y + 7):
            for column in range(x, x + 9):
                if (row + column) % 2 == 0:
                    draw.point((column, row), fill=(45, 45, 45))
    elif flag == "GWC":
        draw.rectangle([x, y + 1, x + 8, y + 6], fill=(240, 240, 240))
        for row in range(y + 1, y + 7):
            for column in range(x, x + 9):
                if (row + column) % 2 == 0:
                    draw.point((column, row), fill=(55, 190, 90))
    elif flag == "MEATBALL":
        draw.rectangle([x, y + 1, x + 8, y + 6], fill=(20, 20, 20))
        center_x, center_y = x + 4, y + 3
        draw.ellipse([center_x - 2, center_y - 2, center_x + 2, center_y + 2], fill=(255, 120, 0))
    elif flag in {"BLACK AND WHITE", "BLACK WHITE"}:
        draw.rectangle([x, y + 1, x + 8, y + 6], fill=(240, 240, 240))
        draw.polygon([(x, y + 1), (x + 8, y + 1), (x, y + 6)], fill=(20, 20, 20))
    elif flag == "DOUBLE YELLOW":
        draw.rectangle([x, y + 1, x + 8, y + 6], fill=(20, 15, 0))
        middle = (y + 1 + y + 6) // 2
        draw.rectangle([x, y + 1, x + 8, middle - 1], fill=(255, 215, 0))
        draw.rectangle([x, middle + 1, x + 8, y + 6], fill=(255, 215, 0))
    elif flag == "BLUE":
        draw.rectangle([x, y + 1, x + 8, y + 6], fill=(60, 100, 235))
        draw.line([(x + 1, y + 6), (x + 8, y + 2)], fill=(255, 215, 0))
        draw.line([(x + 2, y + 6), (x + 8, y + 3)], fill=(255, 215, 0))
    elif flag in {"VSC ENDING", "SC ENDING"}:
        middle = (x + x + 8) // 2
        draw.rectangle([x, y + 1, middle, y + 6], fill=(255, 140, 0))
        draw.rectangle([middle + 1, y + 1, x + 8, y + 6], fill=(55, 190, 90))
    elif flag in {"FLAG TO FLAG", "FTF"}:
        middle = (x + x + 8) // 2
        draw.rectangle([x, y + 1, middle, y + 6], fill=(100, 160, 220))
        draw.rectangle([middle + 1, y + 1, x + 8, y + 6], fill=(55, 190, 90))
    else:
        draw.rectangle([x, y + 1, x + 8, y + 6], fill=racing_flag_color(flag))
    draw.rectangle([x, y + 1, x + 8, y + 6], outline=(35, 35, 35))


def _draw_flag(draw: ImageDraw.ImageDraw, x: int, y: int, flag: str) -> None:
    """Draw the full-screen info-panel flag."""
    draw.rectangle([x - 1, y - 1, x + 15, y + 10], fill=(6, 8, 12), outline=(120, 130, 145))
    if flag == "CHECKERED":
        draw.rectangle([x, y, x + 14, y + 9], fill=(240, 240, 240))
        for row in range(y + 1, y + 9):
            for column in range(x + 1, x + 14):
                if ((row - (y + 1)) // 2 + (column - (x + 1)) // 2) % 2 == 0:
                    draw.point((column, row), fill=(45, 45, 45))
    elif flag == "GWC":
        draw.rectangle([x, y, x + 14, y + 9], fill=(240, 240, 240), outline=(35, 35, 35))
        for row in range(y + 1, y + 9):
            for column in range(x + 1, x + 14):
                if ((row - (y + 1)) // 2 + (column - (x + 1)) // 2) % 2 == 0:
                    draw.point((column, row), fill=(55, 190, 90))
    elif flag == "MEATBALL":
        draw.rectangle([x, y, x + 14, y + 9], fill=(20, 20, 20), outline=(35, 35, 35))
        center_x, center_y = x + 7, y + 4
        draw.ellipse([center_x - 3, center_y - 3, center_x + 3, center_y + 3], fill=(255, 120, 0))
    elif flag in {"BLACK AND WHITE", "BLACK WHITE"}:
        draw.rectangle([x, y, x + 14, y + 9], fill=(240, 240, 240), outline=(35, 35, 35))
        draw.polygon([(x + 1, y + 1), (x + 13, y + 1), (x + 1, y + 8)], fill=(20, 20, 20))
        draw.rectangle([x, y, x + 14, y + 9], outline=(35, 35, 35))
    elif flag == "DOUBLE YELLOW":
        draw.rectangle([x, y, x + 14, y + 9], fill=(20, 15, 0), outline=(35, 35, 35))
        draw.rectangle([x + 1, y + 1, x + 13, y + 2], fill=(255, 215, 0))
        draw.rectangle([x + 1, y + 7, x + 13, y + 8], fill=(255, 215, 0))
    elif flag == "BLUE":
        draw.rectangle([x, y, x + 14, y + 9], fill=(60, 100, 235), outline=(35, 35, 35))
        for index in range(3):
            draw.line([(x + 1 + index, y + 8), (x + 13, y + 1 + index)], fill=(255, 215, 0))
    elif flag in {"VSC ENDING", "SC ENDING"}:
        middle = (x + x + 14) // 2
        draw.rectangle([x, y, middle, y + 9], fill=(255, 140, 0))
        draw.rectangle([middle + 1, y, x + 14, y + 9], fill=(55, 190, 90))
        draw.rectangle([x, y, x + 14, y + 9], outline=(35, 35, 35))
    elif flag in {"FLAG TO FLAG", "FTF"}:
        middle = (x + x + 14) // 2
        draw.rectangle([x, y, middle, y + 9], fill=(100, 160, 220))
        draw.rectangle([middle + 1, y, x + 14, y + 9], fill=(55, 190, 90))
        draw.rectangle([x, y, x + 14, y + 9], outline=(35, 35, 35))
    else:
        draw.rectangle([x, y, x + 14, y + 9], fill=racing_flag_color(flag))
    draw.rectangle([x, y, x + 14, y + 9], outline=(35, 35, 35))


def _draw_empty_or_session(draw: ImageDraw.ImageDraw, payload: Mapping[str, Any], item: Mapping[str, Any], width: int) -> None:
    """Draw an event state when results are not available."""
    has_context = any(payload.get(key) for key in ("short_name", "event_name", "session_type", "session_name"))
    if has_context:
        state = str(item.get("state") or "").lower()
        status = str(item.get("status") or "").strip()
        text = status or "FINAL" if state == "post" else f"STARTS {status}" if state == "pre" and status and not status.upper().startswith("START") else status or "UPCOMING" if state == "pre" else "LIVE"
        draw_tiny_text(draw, max(2, (width - _tiny_width(text[:22])) // 2), 18, text[:22], (200, 210, 235))
        return
    draw.rectangle([0, 0, width - 1, PANEL_HEIGHT - 1], fill=(8, 8, 16))
    draw.rectangle([0, 0, 2, PANEL_HEIGHT - 1], fill=(72, 76, 92))
    draw.rectangle([width - 3, 0, width - 1, PANEL_HEIGHT - 1], fill=(72, 76, 92))
    draw_tiny_text(draw, max(2, (width - _tiny_width("NO GAMES AVAILABLE")) // 2), 10, "NO GAMES AVAILABLE", (205, 212, 224))
    draw_tiny_text(draw, max(2, (width - _tiny_width("CHECK BACK LATER")) // 2), 18, "CHECK BACK LATER", (145, 152, 165))


def _draw_weather(draw: ImageDraw.ImageDraw, weather: Mapping[str, Any]) -> None:
    """Draw the stable conditions panel without network access."""
    air = _round(weather.get("air_temp")) or "--"
    wind = _round(weather.get("wind_mph")) or "--"
    direction = _wind(weather.get("wind_dir")) or "--"
    _draw_condition_icon(draw, 5, 17, "air", (255, 220, 50))
    draw_tiny_text(draw, 15, 16, f"{air}F", (255, 255, 255))
    _draw_condition_icon(draw, 5, 26, "wind", (115, 190, 255))
    draw_tiny_text(draw, 15, 25, f"{wind}-{direction}", (180, 210, 255))


def _draw_condition_icon(draw: ImageDraw.ImageDraw, x: int, y: int, kind: str, color: tuple[int, int, int]) -> None:
    """Draw the established seven-pixel condition symbols."""
    if kind == "air":
        draw.ellipse([x + 1, y + 1, x + 5, y + 5], outline=color)
        draw.point((x + 3, y), fill=color)
        draw.point((x + 3, y + 6), fill=color)
        draw.point((x, y + 3), fill=color)
        draw.point((x + 6, y + 3), fill=color)
        return
    draw.line([(x, y + 1), (x + 5, y + 1)], fill=color)
    draw.point((x + 6, y + 2), fill=color)
    draw.point((x + 5, y + 3), fill=color)
    draw.line([(x + 1, y + 3), (x + 8, y + 3)], fill=(75, 130, 185))
    draw.line([(x, y + 5), (x + 4, y + 5)], fill=color)
    draw.point((x + 5, y + 4), fill=color)
    draw.point((x + 6, y + 5), fill=color)
    draw.point((x + 5, y + 6), fill=color)


def _driver_position(driver: Mapping[str, Any]) -> int:
    """Return an integer driver position for sorting."""
    try:
        return int(str(driver.get("pos") or "999").lstrip("T"))
    except ValueError:
        return 999


def _driver_key(driver: Mapping[str, Any]) -> tuple[str, ...]:
    """Return rendering fields used to cache driver cards."""
    return tuple(str(driver.get(key) or "") for key in ("pos", "name", "abbr", "car", "team_logo", "car_illustration", "gap", "speed", "livery_primary", "livery_secondary"))


def _hex(value: str, fallback: tuple[int, int, int]) -> tuple[int, int, int]:
    """Parse a livery color."""
    text = value.strip().lstrip("#")
    try:
        return tuple(int(text[index : index + 2], 16) for index in (0, 2, 4)) if len(text) == 6 else fallback
    except ValueError:
        return fallback


def _sample_colors(image: Image.Image) -> tuple[tuple[int, int, int], tuple[int, int, int]]:
    """Select two useful logo colors for number text."""
    cleaned = image.convert("RGBA")
    try:
        cleaned = ImageOps.autocontrast(cleaned).filter(ImageFilter.MedianFilter(3))
    except OSError:
        pass
    colors = cleaned.resize((18, 18), Image.Resampling.NEAREST).getcolors(324) or []
    selected: list[tuple[int, int, int]] = []
    for _, color in sorted(colors, reverse=True):
        red, green, blue, alpha = color
        rgb = (red, green, blue)
        if alpha < 40 or max(rgb) < 24 or min(rgb) > 232 or max(rgb) - min(rgb) < 18:
            continue
        if any(sum(abs(rgb[index] - old[index]) for index in range(3)) < 40 for old in selected):
            continue
        selected.append(rgb)
        if len(selected) == 2:
            break
    return (selected + [(80, 80, 80), (80, 80, 80)])[:2]  # type: ignore[return-value]


def _trim_transparent_padding(image: Image.Image) -> Image.Image:
    """Remove transparent image edges before placing a prepared car image."""
    bounds = image.getbbox()
    return image.crop(bounds) if bounds else image


def _draw_f1_car(card: Image.Image, primary: tuple[int, int, int], secondary: tuple[int, int, int]) -> None:
    """Draw a deterministic F1 silhouette when no car image exists."""
    draw = ImageDraw.Draw(card)
    width, height = card.size
    body_y = max(1, height // 2 - 2)
    draw.rectangle([4, body_y, width - 8, body_y + 3], fill=primary)
    draw.polygon([(width - 18, body_y - 2), (width - 8, body_y), (width - 18, body_y + 3)], fill=primary)
    draw.rectangle([width - 7, body_y + 1, width - 2, body_y + 2], fill=secondary)
    for center in (12, width - 15):
        draw.ellipse([center - 3, height - 6, center + 3, height], fill=(18, 18, 22))


def _draw_number(draw: ImageDraw.ImageDraw, number: str, primary: tuple[int, int, int], secondary: tuple[int, int, int], width: int, height: int) -> None:
    """Draw a large fallback NASCAR car number."""
    scale = max(2, min(5, (height - 4) // 5))
    number_height = 5 * scale
    character_width = 4 * scale
    gap = max(1, scale - 1)
    total_width = len(number) * character_width + max(0, len(number) - 1) * gap
    start_x = max(2, (width - total_width) // 2)
    start_y = max(1, (height - number_height) // 2)
    draw.rectangle([0, start_y - 2, width - 1, start_y + number_height + 2], fill=tuple(max(0, channel - 20) for channel in secondary))
    outline = (10, 10, 15) if _luminance(primary) > 60 else (200, 200, 200)
    cursor = start_x
    for character in number:
        for row, bits in enumerate(TINY_FONT_MAP.get(character, [0] * 5)[:5]):
            for column, mask in enumerate((0x8, 0x4, 0x2, 0x1)):
                if bits & mask:
                    x = cursor + column * scale
                    y = start_y + row * scale
                    draw.rectangle([x - 1, y - 1, x + scale, y + scale], fill=outline)
                    draw.rectangle([x, y, x + scale - 1, y + scale - 1], fill=primary)
        cursor += character_width + gap


def _tiny_width(value: object) -> int:
    """Return the bitmap-font width for one label."""
    text = normalize_special_chars(str(value or "").strip()).upper()
    return sum(2 if char == "~" else 5 for char in text)


def _text_width(font: object, text: str) -> int:
    """Return a PIL text width."""
    try:
        box = font.getbbox(text)  # type: ignore[attr-defined]
        return box[2] - box[0]
    except AttributeError:
        return len(text) * 6


def _ordinal(value: str) -> str:
    """Format a driver position as an ordinal."""
    try:
        number = int(value.lstrip("T"))
    except ValueError:
        return f"{value} place" if value else ""
    suffix = "th" if 10 <= number % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(number % 10, "th")
    return f"{number}{suffix} place"


def _luminance(color: tuple[int, int, int]) -> float:
    """Return visible luminance for one RGB color."""
    return 0.299 * color[0] + 0.587 * color[1] + 0.114 * color[2]


def _wind(value: object) -> str:
    """Convert a wind bearing into a compass label."""
    try:
        degrees = float(value)
    except (TypeError, ValueError):
        return ""
    return ("N", "NE", "E", "SE", "S", "SW", "W", "NW")[int((degrees + 22.5) // 45) % 8]


def _round(value: object) -> str:
    """Round a weather value for the compact panel."""
    try:
        return str(int(round(float(value))))
    except (TypeError, ValueError):
        return ""
