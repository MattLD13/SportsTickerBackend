"""Render racing sessions and complete classifications from explicit data."""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
import json
from typing import Any

from PIL import Image, ImageDraw, ImageFilter, ImageOps

from ticker_core.context import RenderContext
from ticker_core.rendering import ContentScene, FontSet, RenderedContent
from ticker_core.rendering.templates import ImageTemplates
from ticker_core.rendering.pixels import TINY as TINY_FONT_MAP
from ticker_core.rendering.pixels import draw_hybrid_text, draw_tiny_text, normalize_special_chars

from .assets import RacingAssetService
from sports_ticker.providers.sports_display import racing_signal, racing_flag_pixel, racing_flag_code


PANEL_WIDTH = 384
PANEL_HEIGHT = 32


def _is_timed_session(session: object) -> bool:
    """Return whether a session is time trial, practice, or multi-stage qualifying."""
    name = str(session or "").lower()
    return any(
        keyword in name
        for keyword in (
            "qual",
            "fast",
            "top 12",
            "last chance",
            "hyperpole",
            "pole",
            "shootout",
            "prac",
            "fp",
            "warm",
            "shakedown",
            "test",
            "time trial",
        )
    )


def racing_flag_color(value: object) -> tuple[int, int, int]:
    """Return the panel color for one race control state."""
    return tuple(racing_signal(value, "")["color_rgb"])



@dataclass(slots=True)
class RacingRenderer:
    """Render all racing series from explicit data and assets."""

    fonts: FontSet
    assets: RacingAssetService
    _strip_cache: dict[tuple[object, ...], tuple[tuple[Image.Image, ...], Image.Image, int]] = field(default_factory=dict)
    _scroll_templates: ImageTemplates = field(default_factory=ImageTemplates, init=False, repr=False)
    _driver_card_cache: OrderedDict[tuple[object, ...], Image.Image] = field(default_factory=OrderedDict, init=False, repr=False)
    _visual_item: Mapping[str, Any] | None = field(default=None, init=False, repr=False)
    _visual_item_json: str | None = field(default=None, init=False, repr=False)
    _asset_item: Mapping[str, Any] | None = field(default=None, init=False, repr=False)
    _asset_revision: int | None = field(default=None, init=False, repr=False)
    _pinned_asset_state: tuple[object, ...] = field(default=(), init=False, repr=False)

    def visual_key(self, context: RenderContext, scene: ContentScene, asset_revision: int | None = None) -> object:
        """Invalidate animated racing scenes only when their own inputs change."""
        if scene.item is not self._visual_item:
            self._visual_item = scene.item
            self._visual_item_json = json.dumps(scene.item, sort_keys=True, default=str, separators=(",", ":"))
        if scene.item.get("sports_presentation") == "pinned":
            self._pinned_asset_key(scene.item, asset_revision)
            assets: object = self._pinned_asset_state
        else:
            assets = asset_revision
        return ("racing", self._visual_item_json, scene.mode, assets, int(context.now.timestamp() * 30))

    def render(self, context: RenderContext, scene: ContentScene) -> RenderedContent:
        """Render a racing scroll card or a full leaderboard."""
        if scene.item.get("sports_presentation") == "pinned":
            return RenderedContent(self._render_full(scene.item, scene.elapsed, context.now.timestamp()))
        return RenderedContent(self._render_scroll(scene.item, context.now.timestamp()))

    def _payload(self, item: Mapping[str, Any]) -> Mapping[str, Any]:
        sport = str(item.get("sport", "")).lower()
        if sport == "f1":
            return _mapping(item.get("f1"))
        if sport == "nascar":
            return _nascar_payload(_mapping(item.get("nascar")))
        if sport and sport in item:
            return _mapping(item.get(sport))
        return _mapping(item.get("indycar"))

    def _render_scroll(self, item: Mapping[str, Any], elapsed: float = 0) -> Image.Image:
        cards = _mapping(item.get("racing_display")).get("cards") or []
        if not cards:
            empty = Image.new("RGBA", (128, PANEL_HEIGHT), (0, 0, 0, 255))
            draw_tiny_text(ImageDraw.Draw(empty), 5, 12, "NO TIMING", (180, 210, 255))
            return empty
        strip = Image.new("RGBA", (128 * len(cards) + 6 * (len(cards) - 1), PANEL_HEIGHT), (0, 0, 0, 255))
        for index, card in enumerate(cards):
            signals = card.get("signals") or [racing_signal("UNKNOWN", "")]
            signal = signals[int(max(0, elapsed) // 2) % len(signals)]
            suffix = str(card.get("class_label") or "")
            if signal["code"] not in {"GREEN", "NONE", "CHECKERED"}:
                suffix += " " + str(signal["label"]) + str(signal.get("car") or signal.get("sector") or "")
            name = str(card.get("race_name") or "RACING").upper()
            while name and _tiny_width(name + " " + suffix) > 112:
                name = name[:-1]
            header = (name + " " + suffix).strip()
            visible_signal = _pulse_flag(signal, elapsed)
            key = (header, json.dumps(visible_signal, sort_keys=True, default=str))

            def build_header():
                image = Image.new("RGBA", (128, PANEL_HEIGHT), (0, 0, 0, 255))
                draw = ImageDraw.Draw(image)
                draw_tiny_text(draw, 1, 1, header, (255, 240, 150))
                _draw_mini_flag(draw, 116, 0, visible_signal)
                draw.line([(0, 7), (127, 7)], fill=(55, 76, 130))
                return image

            image = self._scroll_templates.render(key, build_header)
            draw = ImageDraw.Draw(image)
            rows = card.get("rows") or []
            if not rows:
                draw_tiny_text(draw, 3, 14, str(card.get("session") or "WAITING")[:28], (180, 210, 255))
                draw_tiny_text(draw, 3, 24, str(card.get("status") or "WAIT")[:28], (200, 200, 200))
            else:
                draw_tiny_text(draw, 1, 8, "P", (70, 90, 140))
                draw_tiny_text(draw, 10, 8, "CAR", (70, 90, 140))
                draw_tiny_text(draw, 90, 8, "MPH" if card.get("metric_type") == "mph" else "GAP", (70, 90, 140))
                for position, row in enumerate(rows[:3]):
                    y = 13 + position * 7
                    draw_tiny_text(draw, 1, y, str(row["position"]), tuple(row["position_rgb"]))
                    number = str(row["car"])
                    style = _mapping(row.get("number_style"))
                    draw_tiny_text(draw, 10, y, number, tuple(style.get("color_rgb") or (235, 235, 235)))
                    draw_tiny_text(draw, 13 + _tiny_width(number), y, str(row["name"]), (255, 255, 255))
                    metric = str(row.get("metric") or "")[:12]
                    draw_tiny_text(draw, max(60, 126 - _tiny_width(metric)), y, metric, tuple(row["metric_rgb"]))
            strip.paste(image, (index * 134, 0))
        return strip

    def _render_full(self, item: Mapping[str, Any], elapsed: float, signal_time: float) -> Image.Image:
        image = Image.new("RGBA", (PANEL_WIDTH, PANEL_HEIGHT), (0, 0, 0, 255))
        draw = ImageDraw.Draw(image)
        info_width = 84
        for x in range(info_width):
            draw.line([(x, 0), (x, PANEL_HEIGHT)], fill=(0, 20, 60, int(30 + 20 * x / info_width)))
        payload = self._payload(item)
        self._draw_info(draw, payload, item, info_width, elapsed, signal_time)
        self._draw_driver_panel(image, payload, item, info_width, elapsed)
        return image

    def _draw_info(self, draw: ImageDraw.ImageDraw, payload: Mapping[str, Any], item: Mapping[str, Any], width: int, elapsed: float, signal_time: float) -> None:
        name = _info_name(payload)
        session = str(payload.get("session_type") or "RACE").upper()
        state = str(item.get("state", "pre")).lower()
        flag = _display_flag(payload.get("flag"), state)
        signals = []
        identities = set()
        for card in _mapping(item.get("racing_display")).get("cards") or []:
            for signal in card.get("signals") or []:
                identity = (signal["code"], signal.get("scope"), signal.get("car"), signal.get("sector"))
                if identity not in identities:
                    identities.add(identity)
                    signals.append(signal)
        selected = signals[int(max(0, signal_time) // 2) % len(signals)] if signals else racing_signal(flag, str(item.get("sport") or ""))
        flag = selected["code"]
        draw.rectangle([0, 0, 2, PANEL_HEIGHT], fill=racing_flag_color(flag))
        _draw_flag(draw, width - 17, 1, _pulse_flag(selected, signal_time))
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
        lap = int(payload.get("lap") or 0)
        total_laps = int(payload.get("total_laps") or 0)
        time_to_go = str(payload.get("time_to_go") or "").strip()
        if lap > 0 and total_laps > 0:
            session_display = f"{lap}/{total_laps}"
        elif time_to_go and "00:00" not in time_to_go and time_to_go != "0":
            session_display = time_to_go[:11]
        else:
            session_display = session[:11]
        if selected["code"] not in {"GREEN", "NONE", "CHECKERED"}:
            target = str(selected["car"]) if selected.get("car") else "S" + str(selected["sector"]) if selected.get("sector") else ""
            session_display = (selected["label"] + " " + target).strip()
        draw_tiny_text(draw, 4, 8, session_display, (180, 210, 255))
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
        session = str(payload.get("session_name") or payload.get("session_type") or "").lower()
        metric = str(payload.get("qualifying_metric") or "").lower()
        timed = _is_timed_session(session) or metric in {"mph", "time"}
        f1 = str(item.get("sport") or "").lower() == "f1"
        asset_state = self._pinned_asset_key(item, self.assets.revision)
        key = (tuple(_driver_key(driver) for driver in drivers), timed, f1, metric, asset_state)
        cards, strip, strip_width = self._driver_strip(drivers, timed, f1, metric, key)
        if len(cards) == 1:
            panel.paste(cards[0], (max(0, (panel_width - cards[0].width) // 2), 1), cards[0])
        else:
            view = strip.crop((int(max(0, elapsed) * 20) % strip_width, 0, int(max(0, elapsed) * 20) % strip_width + panel_width, PANEL_HEIGHT))
            panel.alpha_composite(view)
        image.paste(panel, (x_offset, 0), panel)

    def _driver_strip(
        self,
        drivers: list[Mapping[str, Any]],
        qualifying: bool,
        f1: bool,
        metric: str,
        key: tuple[object, ...],
    ) -> tuple[tuple[Image.Image, ...], Image.Image, int]:
        cached = self._strip_cache.get(key)
        if cached is not None:
            return cached
        cards = tuple(self._driver_card(driver, qualifying, f1, metric) for driver in drivers)
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

    def _pinned_asset_key(self, item: Mapping[str, Any], revision: int | None = None) -> tuple[object, ...]:
        """Track prepared assets used by this pinned field, not the whole ticker."""
        current_revision = self.assets.revision if revision is None else revision
        if item is self._asset_item and current_revision == self._asset_revision:
            return self._pinned_asset_state
        self._asset_item = item
        self._asset_revision = current_revision
        payload = self._payload(item)
        sport = str(item.get("sport") or "").lower()
        if sport == "nascar":
            car_assets = (("nascar_car", (130, 20)), ("image", (120, 19)))
        elif sport == "imsa":
            car_assets = (("imsa_car", (120, 19)), ("image", (120, 19)))
        elif sport in {"f1", "wec"}:
            car_assets = (("car", (130, 20)), ("image", (120, 19)))
        else:
            car_assets = (("image", (120, 19)),)
        self._pinned_asset_state = tuple(
            (
                tuple(bool(self.assets.image(car_url, processor, size)) for processor, size in car_assets)
                if (car_url := str(driver.get("car_illustration") or ""))
                else (),
                tuple(
                    bool(self.assets.image(logo_url, "logo", size))
                    for size in ((18, 18), (21, 21))
                )
                if (logo_url := str(driver.get("team_logo") or ""))
                else (),
            )
            for driver in _drivers(payload)
        )
        return self._pinned_asset_state

    def _driver_card(self, driver: Mapping[str, Any], qualifying: bool, f1: bool, metric: str) -> Image.Image:
        base_key = (
            tuple(str(driver.get(key) or "") for key in (
                "pos", "name", "display_name", "class", "class_pos", "abbr", "car", "team",
                "team_logo", "car_illustration", "livery_primary", "livery_secondary",
            )),
            f1,
            self._pinned_asset_state,
        )
        card = self._driver_card_cache.get(base_key)
        if card is None:
            card = self._driver_card_base(driver, f1)
            self._driver_card_cache[base_key] = card
            while len(self._driver_card_cache) > 128:
                self._driver_card_cache.popitem(last=False)
        else:
            self._driver_card_cache.move_to_end(base_key)
        card = card.copy()
        draw = ImageDraw.Draw(card)
        position = str(driver.get("pos") or "")
        width = card.width
        is_mph = metric == "mph"
        if is_mph:
            right = str(driver.get("speed") or driver.get("qualifying_value") or driver.get("gap") or "")[:8]
        elif qualifying and not f1 and metric == "time":
            right = str(driver.get("best_time") or driver.get("qualifying_value") or driver.get("gap") or "")[:8]
        elif qualifying and f1:
            right = str(driver.get("gap") or driver.get("best_time") or "")[:8]
        elif qualifying:
            right = str(driver.get("speed") or driver.get("best_time") or driver.get("gap") or "")[:8]
        else:
            right = str(driver.get("gap") or driver.get("interval") or "")[:10]
        if right:
            draw_tiny_text(draw, max(4, width - _tiny_width(right) - 4), 23, right, (255, 215, 0) if position == "1" or right.upper() == "LEADER" else (140, 190, 255))
        return card

    def _driver_card_base(self, driver: Mapping[str, Any], f1: bool) -> Image.Image:
        """Render driver identity and images without frequently changing timing text."""
        position = str(driver.get("pos") or "")
        name = str(driver.get("display_name") or driver.get("name") or driver.get("abbr") or "???").strip()
        car_number = str(driver.get("car") or "").strip()
        place = _ordinal(position)
        if driver.get("class") and driver.get("class_pos"):
            place = f"{driver['class']} P{driver['class_pos']}"
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
        badge_card = bool(team_logo) and not car_image
        if badge_card:
            width = max(PANEL_HEIGHT - 7 + int(name_width) + 18, 80)
        else:
            width = max(132, int(name_width) + 24, int(_text_width(self.fonts.normal, place) + _text_width(self.fonts.normal, car_number)) + 18)
        card = Image.new("RGBA", (width, PANEL_HEIGHT - 2), (0, 0, 0, 0))
        draw = ImageDraw.Draw(card)
        primary, secondary = self._driver_colors(driver)
        draw.rectangle([0, 0, width - 1, card.height - 1], fill=(12, 12, 18), outline=(255, 215, 0) if position == "1" else (60, 60, 72))
        image = None
        if car_image:
            image = (
                self.assets.image(car_image, "nascar_car", (130, 20))
                or self.assets.image(car_image, "imsa_car", (120, 19))
                or self.assets.image(car_image, "car", (130, 20))
                or self.assets.image(car_image, "image", (120, 19))
            )
        drew = False
        if image is not None:
            car = image.convert("RGBA")
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
    """Keep absent and unknown live signals distinct from green."""
    if flag not in (None, ""):
        return racing_flag_code(flag)
    return "CHECKERED" if str(state).lower() == "post" else "NONE" if str(state).lower() == "pre" else "UNKNOWN"


def _flag_style(flag):
    return flag if isinstance(flag, Mapping) else racing_signal(flag, "")


def _pulse_flag(signal, elapsed):
    if signal.get("motion") == "waved" and int(max(0, elapsed) / .35) % 2:
        return {**signal, "color_rgb": [v // 3 for v in signal["color_rgb"]],
                "accent_rgb": [v // 3 for v in signal["accent_rgb"]]}
    return signal


def _draw_mini_flag(draw: ImageDraw.ImageDraw, x: int, y: int, flag) -> None:
    signal = _flag_style(flag)
    for row in range(6):
        for column in range(9):
            draw.point((x + column, y + row + 1), fill=racing_flag_pixel(signal, column, row, 9, 6))


def _draw_flag(draw: ImageDraw.ImageDraw, x: int, y: int, flag) -> None:
    signal = _flag_style(flag)
    draw.rectangle([x - 1, y - 1, x + 15, y + 10], fill=(6, 8, 12), outline=(120, 130, 145))
    for row in range(10):
        for column in range(15):
            draw.point((x + column, y + row), fill=racing_flag_pixel(signal, column, row, 15, 10))


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
    return tuple(str(driver.get(key) or "") for key in ("pos", "name", "display_name", "class", "class_pos", "abbr", "car", "team_logo", "car_illustration", "gap", "best_time", "interval", "speed", "livery_primary", "livery_secondary"))


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


def _brighten_if_dark(color: tuple[int, int, int]) -> tuple[int, int, int]:
    """Ensure text color is legible on a black matrix background without blurry outlines."""
    lum = 0.299 * color[0] + 0.587 * color[1] + 0.114 * color[2]
    if lum < 90:
        boost = int(90 - lum)
        return (min(255, color[0] + boost), min(255, color[1] + boost), min(255, color[2] + boost))
    return color


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
