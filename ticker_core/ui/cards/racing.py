"""Draw racing: class cards in the scrolling strip, and a pinned panel with race facts and a moving driver field.

The racing display contract in sports_ticker/projections/racing_display.py makes the class cards.
The pinned panel reads the series payload of the item, such as item["f1"].
"""
from __future__ import annotations

import json
from collections import OrderedDict
from collections.abc import Mapping
from typing import Any

from PIL import Image, ImageDraw, ImageFilter, ImageOps

from sports_ticker.providers.racing_session import racing_timed_session
from sports_ticker.providers.sports_display import racing_flag_code, racing_flag_pixel, racing_signal

from ..frame import ContentScene, ItemKey, RenderContext, RenderedContent
from ..layers import ImageTemplates
from ..text import TINY, FontSet, draw_tiny, plain_text

WIDTH, HEIGHT = 384, 32
CARD_WIDTH, CARD_GAP = 128, 6
INFO_WIDTH = 84
CALM = {"GREEN", "NONE", "CHECKERED"}
HEADER, LABEL, BLUE, GOLD = (255, 240, 150), (70, 90, 140), (180, 210, 255), (255, 215, 0)
RULE = (55, 76, 130)
DRIVER_CARD_LIMIT = 128
SIGNAL_SECONDS = 2
FIELD_SPEED, NAME_SPEED = 20, 14
NAME_EDITS = (("110TH RUNNING OF THE ", ""), ("GRAND PRIX", "GP"), ("CHAMPIONSHIP", "CHAMP"), ("PRESENTED BY", ""),
              ("NASCAR CUP SERIES", ""), ("NASCAR XFINITY SERIES", ""), ("NASCAR CRAFTSMAN TRUCK SERIES", ""), ("NASCAR ", ""))
CARD_FIELDS = ("pos", "name", "display_name", "class", "class_pos", "abbr", "car", "team", "team_logo", "car_illustration",
               "livery_primary", "livery_secondary")
STRIP_FIELDS = ("pos", "name", "display_name", "class", "class_pos", "abbr", "car", "team_logo", "car_illustration", "gap",
                "best_time", "interval", "speed", "livery_primary", "livery_secondary")


def _flag_color(value: object) -> tuple[int, int, int]:
    """Return the panel color of one race control state."""
    return tuple(racing_signal(value, "")["color_rgb"])


class RacingCard:
    def __init__(self, fonts: FontSet, assets: Any) -> None:
        self._fonts, self._assets = fonts, assets
        self._headers = ImageTemplates()
        self._cards: OrderedDict[tuple, Image.Image] = OrderedDict()
        self._strip: dict[tuple, tuple[tuple[Image.Image, ...], Image.Image, int]] = {}
        self._key = ItemKey("racing")
        self._asset_item: Mapping[str, Any] | None = None
        self._asset_revision: int | None = None
        self._asset_state: tuple = ()

    def visual_key(self, context: RenderContext, scene: ContentScene, asset_revision: int | None = None) -> object:
        """Change the key only when this item, its own prepared assets, or the animation frame changes."""
        pinned = scene.item.get("sports_presentation") == "pinned"
        assets = self._prepared(scene.item, asset_revision) if pinned else asset_revision
        return self._key(scene, assets, int(context.now.timestamp() * 30))

    def render(self, context: RenderContext, scene: ContentScene) -> RenderedContent:
        now = context.now.timestamp()
        if scene.item.get("sports_presentation") == "pinned":
            return RenderedContent(self.full(scene.item, scene.elapsed, now))
        return RenderedContent(self.strip(scene.item, now))

    # The class cards of the scrolling strip

    def strip(self, item: Mapping[str, Any], at: float) -> Image.Image:
        cards = _mapping(item.get("racing_display")).get("cards") or []
        if not cards:
            image = Image.new("RGBA", (CARD_WIDTH, HEIGHT), (0, 0, 0, 255))
            draw_tiny(ImageDraw.Draw(image), 5, 12, "NO TIMING", BLUE)
            return image
        strip = Image.new("RGBA", (CARD_WIDTH * len(cards) + CARD_GAP * (len(cards) - 1), HEIGHT), (0, 0, 0, 255))
        for index, card in enumerate(cards):
            strip.paste(self._class_card(card, at), (index * (CARD_WIDTH + CARD_GAP), 0))
        return strip

    def _class_card(self, card: Mapping[str, Any], at: float) -> Image.Image:
        signals = card.get("signals") or [racing_signal("UNKNOWN", "")]
        signal = signals[int(max(0, at) // SIGNAL_SECONDS) % len(signals)]
        suffix = str(card.get("class_label") or "")
        if signal["code"] not in CALM:
            suffix += " " + str(signal["label"]) + str(signal.get("car") or signal.get("sector") or "")
        name = str(card.get("race_name") or "RACING").upper()
        while name and _width(name + " " + suffix) > 112:
            name = name[:-1]
        header = (name + " " + suffix).strip()
        shown = _blink(signal, at)
        image = self._headers.render((header, json.dumps(shown, sort_keys=True, default=str)), lambda: _class_header(header, shown))
        draw = ImageDraw.Draw(image)
        rows = card.get("rows") or []
        if not rows:
            draw_tiny(draw, 3, 14, str(card.get("session") or "WAITING")[:28], BLUE)
            draw_tiny(draw, 3, 24, str(card.get("status") or "WAIT")[:28], (200, 200, 200))
            return image
        draw_tiny(draw, 1, 8, "P", LABEL)
        draw_tiny(draw, 10, 8, "CAR", LABEL)
        draw_tiny(draw, 90, 8, "MPH" if card.get("metric_type") == "mph" else "GAP", LABEL)
        for line, row in enumerate(rows[:3]):
            y = 13 + line * 7
            number = str(row["car"])
            metric = str(row.get("metric") or "")[:12]
            draw_tiny(draw, 1, y, str(row["position"]), tuple(row["position_rgb"]))
            draw_tiny(draw, 10, y, number, tuple(_mapping(row.get("number_style")).get("color_rgb") or (235, 235, 235)))
            draw_tiny(draw, 13 + _width(number), y, str(row["name"]), (255, 255, 255))
            draw_tiny(draw, max(60, 126 - _width(metric)), y, metric, tuple(row["metric_rgb"]))
        return image

    # The pinned panel

    def full(self, item: Mapping[str, Any], elapsed: float, at: float) -> Image.Image:
        image = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 255))
        draw = ImageDraw.Draw(image)
        for x in range(INFO_WIDTH):
            draw.line([(x, 0), (x, HEIGHT)], fill=(0, 20, 60, int(30 + 20 * x / INFO_WIDTH)))
        race = _race(item)
        self._facts(draw, race, item, elapsed, at)
        self._field(image, race, item, elapsed)
        return image

    def _facts(self, draw: ImageDraw.ImageDraw, race: Mapping[str, Any], item: Mapping[str, Any], elapsed: float, at: float) -> None:
        """Draw the race name, the session or flag state, and the weather in the left column."""
        name = _race_name(race)
        session = str(race.get("session_type") or "RACE").upper()
        signal = _current_signal(item, race, at)
        draw.rectangle([0, 0, 2, HEIGHT], fill=_flag_color(signal["code"]))
        _flag(draw, INFO_WIDTH - 17, 1, _blink(signal, at))
        room = INFO_WIDTH - 25
        if _width(name) <= room:
            draw_tiny(draw, 4, 1, name, HEADER)
        else:
            # A long name scrolls in a loop with an 18-pixel gap.
            loop = _width(name) + 18
            strip = Image.new("RGBA", (_width(name) * 2 + 18 + room, 7), (0, 0, 0, 0))
            strip_draw = ImageDraw.Draw(strip)
            draw_tiny(strip_draw, 0, 0, name, HEADER)
            draw_tiny(strip_draw, _width(name) + 18, 0, name, HEADER)
            offset = int(max(0, elapsed) * NAME_SPEED) % loop
            view = strip.crop((offset, 0, offset + room, 7))
            draw._image.paste(view, (4, 1), view)
        lap, laps = int(race.get("lap") or 0), int(race.get("total_laps") or 0)
        remaining = str(race.get("time_to_go") or "").strip()
        if lap > 0 and laps > 0:
            progress = f"{lap}/{laps}"
        elif remaining and "00:00" not in remaining and remaining != "0":
            progress = remaining[:11]
        else:
            progress = session[:11]
        if signal["code"] not in CALM:
            target = str(signal["car"]) if signal.get("car") else "S" + str(signal["sector"]) if signal.get("sector") else ""
            progress = (signal["label"] + " " + target).strip()
        draw_tiny(draw, 4, 8, progress, BLUE)
        _weather(draw, _mapping(race.get("weather")))

    def _field(self, image: Image.Image, race: Mapping[str, Any], item: Mapping[str, Any], elapsed: float) -> None:
        """Draw the driver cards to the right of the facts. More than one card scrolls."""
        width = WIDTH - INFO_WIDTH
        panel = Image.new("RGBA", (width, HEIGHT), (0, 0, 0, 0))
        drivers = sorted(_drivers(race), key=_position)
        if not drivers:
            label = _waiting_label(race)
            draw = ImageDraw.Draw(panel)
            draw_tiny(draw, max(4, (width - _width(label)) // 2), 10, label, BLUE)
            status = str(item.get("status") or "").strip()
            if str(item.get("state") or "").lower() == "pre" and status:
                starts = f"STARTS {status}"
                draw_tiny(ImageDraw.Draw(panel), max(4, (width - _width(starts)) // 2), 18, starts, (200, 200, 200))
            image.paste(panel, (INFO_WIDTH, 0), panel)
            return
        session = str(race.get("session_name") or race.get("session_type") or "").lower()
        metric = str(race.get("qualifying_metric") or "").lower()
        timed = racing_timed_session(session) or metric in {"mph", "time"}
        f1 = str(item.get("sport") or "").lower() == "f1"
        key = (tuple(tuple(str(driver.get(name) or "") for name in STRIP_FIELDS) for driver in drivers), timed, f1, metric,
               self._prepared(item, self._assets.revision))
        cards, strip, strip_width = self._driver_strip(drivers, timed, f1, metric, key)
        if len(cards) == 1:
            panel.paste(cards[0], (max(0, (width - cards[0].width) // 2), 1), cards[0])
        else:
            offset = int(max(0, elapsed) * FIELD_SPEED) % strip_width
            panel.alpha_composite(strip.crop((offset, 0, offset + width, HEIGHT)))
        image.paste(panel, (INFO_WIDTH, 0), panel)

    def _driver_strip(self, drivers, timed: bool, f1: bool, metric: str, key: tuple):
        """Return the driver cards and one loop of them, wide enough to cover the panel at any offset."""
        if key in self._strip:
            return self._strip[key]
        cards = tuple(self._driver_card(driver, timed, f1, metric) for driver in drivers)
        width = sum(card.width for card in cards) + CARD_GAP * len(cards)
        strip = Image.new("RGBA", (width + WIDTH - INFO_WIDTH, HEIGHT), (0, 0, 0, 0))
        x = index = 0
        while x < strip.width:
            card = cards[index % len(cards)]
            strip.paste(card, (x, 1), card)
            x += card.width + CARD_GAP
            index += 1
        self._strip = {key: (cards, strip, width)}
        return self._strip[key]

    def _prepared(self, item: Mapping[str, Any], revision: int | None = None) -> tuple:
        """Return which car and logo images of this item are ready. Assets of other items do not change it."""
        revision = self._assets.revision if revision is None else revision
        if item is self._asset_item and revision == self._asset_revision:
            return self._asset_state
        self._asset_item, self._asset_revision = item, revision
        sport = str(item.get("sport") or "").lower()
        car_sizes = {"nascar": (("nascar_car", (130, 20)), ("image", (120, 19))),
                     "imsa": (("imsa_car", (120, 19)), ("image", (120, 19))),
                     "f1": (("car", (130, 20)), ("image", (120, 19))),
                     "wec": (("car", (130, 20)), ("image", (120, 19)))}.get(sport, (("image", (120, 19)),))
        state = []
        for driver in _drivers(_race(item)):
            car, logo = str(driver.get("car_illustration") or ""), str(driver.get("team_logo") or "")
            state.append((tuple(bool(self._assets.image(car, kind, size)) for kind, size in car_sizes) if car else (),
                          tuple(bool(self._assets.image(logo, "logo", size)) for size in ((18, 18), (21, 21))) if logo else ()))
        self._asset_state = tuple(state)
        return self._asset_state

    def _driver_card(self, driver: Mapping[str, Any], timed: bool, f1: bool, metric: str) -> Image.Image:
        """Return one driver card: the cached identity layer and the current timing value."""
        key = (tuple(str(driver.get(name) or "") for name in CARD_FIELDS), f1, self._asset_state)
        base = self._cards.get(key)
        if base is None:
            base = self._cards[key] = self._identity(driver, f1)
            while len(self._cards) > DRIVER_CARD_LIMIT:
                self._cards.popitem(last=False)
        else:
            self._cards.move_to_end(key)
        card = base.copy()
        position = str(driver.get("pos") or "")
        if metric == "mph":
            value = str(driver.get("speed") or driver.get("qualifying_value") or driver.get("gap") or "")[:8]
        elif timed and not f1 and metric == "time":
            value = str(driver.get("best_time") or driver.get("qualifying_value") or driver.get("gap") or "")[:8]
        elif timed and f1:
            value = str(driver.get("gap") or driver.get("best_time") or "")[:8]
        elif timed:
            value = str(driver.get("speed") or driver.get("best_time") or driver.get("gap") or "")[:8]
        else:
            value = str(driver.get("gap") or driver.get("interval") or "")[:10]
        if value:
            leader = position == "1" or value.upper() == "LEADER"
            draw_tiny(ImageDraw.Draw(card), max(4, card.width - _width(value) - 4), 23, value, GOLD if leader else (140, 190, 255))
        return card

    def _identity(self, driver: Mapping[str, Any], f1: bool) -> Image.Image:
        """Draw the place, the car or logo or number, and the name. Timing text is not part of this layer."""
        fonts = self._fonts
        position = str(driver.get("pos") or "")
        name = str(driver.get("display_name") or driver.get("name") or driver.get("abbr") or "???").strip()
        number = str(driver.get("car") or "").strip()
        place = f"{driver['class']} P{driver['class_pos']}" if driver.get("class") and driver.get("class_pos") else _ordinal(position)
        # A long name steps down to a smaller font: past 72 pixels, then past 84 pixels.
        name_font = fonts.normal
        name_width = _text_width(name_font, name)
        if name_width > 72:
            name_font = fonts.tiny
            name_width = _text_width(name_font, name)
        if name_width > 84:
            name_font = fonts.tiny_small
            name_width = _text_width(name_font, name)
        logo_url, car_url = str(driver.get("team_logo") or ""), str(driver.get("car_illustration") or "")
        if logo_url and not car_url:
            width = max(HEIGHT - 7 + int(name_width) + 18, 80)
        else:
            width = max(132, int(name_width) + 24, int(_text_width(fonts.normal, place) + _text_width(fonts.normal, number)) + 18)
        card = Image.new("RGBA", (width, HEIGHT - 2), (0, 0, 0, 0))
        draw = ImageDraw.Draw(card)
        primary, secondary = self._colors(driver)
        draw.rectangle([0, 0, width - 1, card.height - 1], fill=(12, 12, 18), outline=GOLD if position == "1" else (60, 60, 72))
        art = self._car_art(card, car_url, f1, str(driver.get("team") or ""), logo_url, primary, secondary)
        if not art and number:
            _big_number(draw, number, primary, secondary, width, card.height)
        draw.text((4, 0), place, font=fonts.normal, fill=GOLD if position == "1" else (180, 180, 180))
        if number and not art:
            x = width - _text_width(fonts.normal, number) - 5
            if _luminance(primary) < 80:
                for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                    draw.text((x + dx, dy), number, font=fonts.normal, fill=(255, 255, 255, 200))
            draw.text((x, 0), number, font=fonts.normal, fill=primary)
        draw.text((max(4, width - int(name_width) - 5), 10), name, font=name_font, fill=(255, 255, 255))
        return card

    def _car_art(self, card: Image.Image, car_url: str, f1: bool, team: str, logo_url: str, primary, secondary) -> bool:
        """Draw the car image, or a drawn F1 car, or the team logo. Return False when the card has no art."""
        image = None
        if car_url:
            image = (self._assets.image(car_url, "nascar_car", (130, 20)) or self._assets.image(car_url, "imsa_car", (120, 19))
                     or self._assets.image(car_url, "car", (130, 20)) or self._assets.image(car_url, "image", (120, 19)))
        if image is not None:
            car = image.convert("RGBA")
            bounds = car.getbbox()
            car = car.crop(bounds) if bounds else car
            car.thumbnail((120, 19), Image.Resampling.LANCZOS)
            card.paste(car, (0, max(0, card.height - car.height - 1)), car)
            return True
        if f1 and team:
            _f1_car(card, primary, secondary)
            return True
        if logo_url:
            size = card.height - 9
            badge = self._assets.image(logo_url, "logo", (size, size))
            if badge is not None:
                badge = badge.convert("RGBA")
                badge.thumbnail((size, size), Image.Resampling.LANCZOS)
                card.paste(badge, (2, 8), badge)
                return True
        return False

    def _colors(self, driver: Mapping[str, Any]) -> tuple[tuple[int, int, int], tuple[int, int, int]]:
        logo_url = str(driver.get("team_logo") or "")
        logo = self._assets.image(logo_url, "logo", (18, 18)) if logo_url else None
        if logo is not None:
            return _logo_colors(logo)
        return (_hex(str(driver.get("livery_primary") or ""), (180, 180, 180)),
                _hex(str(driver.get("livery_secondary") or ""), (80, 80, 80)))


def _class_header(header: str, signal: Mapping[str, Any]) -> Image.Image:
    image = Image.new("RGBA", (CARD_WIDTH, HEIGHT), (0, 0, 0, 255))
    draw = ImageDraw.Draw(image)
    draw_tiny(draw, 1, 1, header, HEADER)
    for row in range(6):
        for column in range(9):
            draw.point((116 + column, row + 1), fill=racing_flag_pixel(signal, column, row, 9, 6))
    draw.line([(0, 7), (127, 7)], fill=RULE)
    return image


def _flag(draw: ImageDraw.ImageDraw, x: int, y: int, signal: Mapping[str, Any]) -> None:
    draw.rectangle([x - 1, y - 1, x + 15, y + 10], fill=(6, 8, 12), outline=(120, 130, 145))
    for row in range(10):
        for column in range(15):
            draw.point((x + column, y + row), fill=racing_flag_pixel(signal, column, row, 15, 10))


def _current_signal(item: Mapping[str, Any], race: Mapping[str, Any], at: float) -> Mapping[str, Any]:
    """Return the race control signal to show now. Several distinct signals take turns."""
    signals, seen = [], set()
    for card in _mapping(item.get("racing_display")).get("cards") or []:
        for signal in card.get("signals") or []:
            identity = (signal["code"], signal.get("scope"), signal.get("car"), signal.get("sector"))
            if identity not in seen:
                seen.add(identity)
                signals.append(signal)
    if signals:
        return signals[int(max(0, at) // SIGNAL_SECONDS) % len(signals)]
    flag, state = race.get("flag"), str(item.get("state", "pre")).lower()
    if flag in (None, ""):
        # An absent live flag is unknown, not green.
        code = "CHECKERED" if state == "post" else "NONE" if state == "pre" else "UNKNOWN"
    else:
        code = racing_flag_code(flag)
    return racing_signal(code, str(item.get("sport") or ""))


def _blink(signal: Mapping[str, Any], at: float) -> Mapping[str, Any]:
    """Dim a waved flag every other 0.35 seconds."""
    if signal.get("motion") == "waved" and int(max(0, at) / .35) % 2:
        return {**signal, "color_rgb": [value // 3 for value in signal["color_rgb"]],
                "accent_rgb": [value // 3 for value in signal["accent_rgb"]]}
    return signal


def _weather(draw: ImageDraw.ImageDraw, weather: Mapping[str, Any]) -> None:
    """Draw the air temperature and the wind with their seven-pixel icons."""
    sun, wind = (255, 220, 50), (115, 190, 255)
    draw.ellipse([6, 18, 10, 22], outline=sun)
    for point in ((8, 17), (8, 23), (5, 20), (11, 20)):
        draw.point(point, fill=sun)
    draw_tiny(draw, 15, 16, f"{_rounded(weather.get('air_temp')) or '--'}F", (255, 255, 255))
    x, y = 5, 26
    draw.line([(x, y + 1), (x + 5, y + 1)], fill=wind)
    draw.point((x + 6, y + 2), fill=wind)
    draw.point((x + 5, y + 3), fill=wind)
    draw.line([(x + 1, y + 3), (x + 8, y + 3)], fill=(75, 130, 185))
    draw.line([(x, y + 5), (x + 4, y + 5)], fill=wind)
    for point in ((x + 5, y + 4), (x + 6, y + 5), (x + 5, y + 6)):
        draw.point(point, fill=wind)
    direction = _compass(weather.get("wind_dir")) or "--"
    draw_tiny(draw, 15, 25, f"{_rounded(weather.get('wind_mph')) or '--'}-{direction}", BLUE)


def _f1_car(card: Image.Image, primary, secondary) -> None:
    """Draw a plain F1 car shape in the team colors when no car image exists."""
    draw = ImageDraw.Draw(card)
    width, height = card.size
    body = max(1, height // 2 - 2)
    draw.rectangle([4, body, width - 8, body + 3], fill=primary)
    draw.polygon([(width - 18, body - 2), (width - 8, body), (width - 18, body + 3)], fill=primary)
    draw.rectangle([width - 7, body + 1, width - 2, body + 2], fill=secondary)
    for center in (12, width - 15):
        draw.ellipse([center - 3, height - 6, center + 3, height], fill=(18, 18, 22))


def _big_number(draw: ImageDraw.ImageDraw, number: str, primary, secondary, width: int, height: int) -> None:
    """Draw the car number in large outlined blocks on a band of the secondary color."""
    scale = max(2, min(5, (height - 4) // 5))
    glyph_width, gap = 4 * scale, max(1, scale - 1)
    total = len(number) * glyph_width + max(0, len(number) - 1) * gap
    x0, y0 = max(2, (width - total) // 2), max(1, (height - 5 * scale) // 2)
    draw.rectangle([0, y0 - 2, width - 1, y0 + 5 * scale + 2], fill=tuple(max(0, channel - 20) for channel in secondary))
    outline = (10, 10, 15) if _luminance(primary) > 60 else (200, 200, 200)
    for index, character in enumerate(number):
        cursor = x0 + index * (glyph_width + gap)
        for row, bits in enumerate(TINY.get(character, [0] * 5)[:5]):
            for column, mask in enumerate((8, 4, 2, 1)):
                if bits & mask:
                    x, y = cursor + column * scale, y0 + row * scale
                    draw.rectangle([x - 1, y - 1, x + scale, y + scale], fill=outline)
                    draw.rectangle([x, y, x + scale - 1, y + scale - 1], fill=primary)


# Data

def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _race(item: Mapping[str, Any]) -> Mapping[str, Any]:
    """Return the series payload of one racing item."""
    sport = str(item.get("sport", "")).lower()
    if sport == "nascar":
        return _nascar(_mapping(item.get("nascar")))
    if sport == "f1" or (sport and sport in item):
        return _mapping(item.get(sport))
    return _mapping(item.get("indycar"))


def _nascar(raw: Mapping[str, Any]) -> Mapping[str, Any]:
    """Give the NASCAR payload the session and event names of the other series."""
    race = dict(raw)
    session = str(race.get("session_type") or "")
    session = "Xfinity" if "Xfinity" in session else "Trucks" if "Truck" in session else session or "Race"
    race["session_name"] = race["session_type"] = "FINAL" if int(race.get("total_laps") or 0) and not int(race.get("laps_remaining") or 0) else session
    race["short_name"] = race["event_name"] = str(race.get("short_name") or race.get("event_name") or "NASCAR")
    return race


def _drivers(race: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    value = race.get("drivers")
    return [driver for driver in value if isinstance(driver, Mapping)] if isinstance(value, list) else []


def _waiting_label(race: Mapping[str, Any]) -> str:
    """Return the event and session label for a field with no drivers yet."""
    short = str(race.get("short_name") or race.get("event_name") or "Racing").strip().upper()
    short = short.replace("GRAND PRIX", "GP").replace("CHAMPIONSHIP", "CHAMP").replace("PRESENTED BY", "").replace("  ", " ").strip()
    session = str(race.get("session_name") or race.get("session_type") or "Race").strip()
    session = session.replace("Sprint Qualifying", "Sprint Quali").replace("Qualifying", "Quali")
    if len(short) + len(session) + 1 > 24:
        short = short[: max(4, 24 - len(session) - 1)]
    return f"{short} {session}"


def _race_name(race: Mapping[str, Any]) -> str:
    name = str(race.get("short_name") or race.get("event_name") or "RACING").upper()
    for old, new in NAME_EDITS:
        name = name.replace(old, new)
    return name.replace("  ", " ").strip()


def _position(driver: Mapping[str, Any]) -> int:
    try:
        return int(str(driver.get("pos") or "999").lstrip("T"))
    except ValueError:
        return 999


def _ordinal(value: str) -> str:
    try:
        number = int(value.lstrip("T"))
    except ValueError:
        return f"{value} place" if value else ""
    suffix = "th" if 10 <= number % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(number % 10, "th")
    return f"{number}{suffix} place"


def _hex(value: str, fallback: tuple[int, int, int]) -> tuple[int, int, int]:
    text = value.strip().lstrip("#")
    try:
        return tuple(int(text[index: index + 2], 16) for index in (0, 2, 4)) if len(text) == 6 else fallback
    except ValueError:
        return fallback


def _logo_colors(image: Image.Image) -> tuple[tuple[int, int, int], tuple[int, int, int]]:
    """Return the two most common distinct, saturated colors of a team logo."""
    cleaned = image.convert("RGBA")
    try:
        cleaned = ImageOps.autocontrast(cleaned).filter(ImageFilter.MedianFilter(3))
    except OSError:
        pass
    selected: list[tuple[int, int, int]] = []
    for _, color in sorted(cleaned.resize((18, 18), Image.Resampling.NEAREST).getcolors(324) or [], reverse=True):
        rgb, alpha = color[:3], color[3]
        if alpha < 40 or max(rgb) < 24 or min(rgb) > 232 or max(rgb) - min(rgb) < 18:
            continue
        if any(sum(abs(rgb[index] - old[index]) for index in range(3)) < 40 for old in selected):
            continue
        selected.append(rgb)
        if len(selected) == 2:
            break
    return tuple((selected + [(80, 80, 80), (80, 80, 80)])[:2])


def _width(value: object) -> int:
    """Return the width of five-row text."""
    return sum(2 if char == "~" else 5 for char in plain_text(str(value or "").strip()).upper())


def _text_width(font: Any, text: str) -> int:
    box = font.getbbox(text)
    return box[2] - box[0]


def _luminance(color: tuple[int, int, int]) -> float:
    return 0.299 * color[0] + 0.587 * color[1] + 0.114 * color[2]


def _compass(value: object) -> str:
    try:
        degrees = float(value)
    except (TypeError, ValueError):
        return ""
    return ("N", "NE", "E", "SE", "S", "SW", "W", "NW")[int((degrees + 22.5) // 45) % 8]


def _rounded(value: object) -> str:
    try:
        return str(int(round(float(value))))
    except (TypeError, ValueError):
        return ""
