"""Render stock and system panels without controller inheritance."""

from __future__ import annotations

import math
from datetime import datetime
from typing import Protocol

from PIL import Image, ImageDraw

from ticker_core.context import RenderContext
from ticker_core.platform.wifi import WiFiSetupState
from ticker_core.rendering import ContentScene, FontSet, RenderedContent

from .primitives import PANEL_H, PANEL_W, tiny_text


class LogoSource(Protocol):
    """Return cached logo images without network work."""

    def get(self, value: object, size: tuple[int, int]) -> Image.Image | None:
        """Return one cached image if it exists."""


class EmptyLogoSource:
    """Return no logo when the runtime has no local asset."""

    def get(self, value: object, size: tuple[int, int]) -> Image.Image | None:
        """Return no image."""
        return None


def offline_elapsed_label(seconds: float) -> str:
    """Format the link age for the offline panel."""
    value = int(max(0, seconds))
    if value < 60:
        return f"{value}S"
    if value < 3600:
        return f"{value // 60}M"
    if value < 86400:
        return f"{value // 3600}H"
    return f"{value // 86400}D"


class UtilityRenderer:
    """Render utility content and runtime status scenes."""

    def __init__(self, fonts: FontSet, logos: LogoSource | None = None) -> None:
        self._fonts = fonts
        self._logos = logos or EmptyLogoSource()

    def render(self, context: RenderContext, scene: ContentScene) -> RenderedContent:
        """Render a utility content item."""
        item_type = str(scene.item.get("type", "")).lower()
        sport = str(scene.item.get("sport", "")).lower()
        if scene.item.get("no_games"):
            return RenderedContent(self.empty(context))
        if item_type == "stock_ticker" or sport.startswith("stock"):
            return RenderedContent(self.stock(scene.item))
        if item_type == "leaderboard":
            return RenderedContent(self.leaderboard(scene.item))
        raise ValueError(f"UtilityRenderer cannot render {item_type!r}.")

    def stock(self, item: object) -> Image.Image:
        """Render the compact stock card."""
        game = item if isinstance(item, dict) else {}
        image = Image.new("RGBA", (128, PANEL_H), (0, 0, 0, 255))
        draw = ImageDraw.Draw(image)
        symbol = str(game.get("home_abbr", "UNK"))
        if not symbol.startswith("$") and not any(char.isdigit() for char in symbol):
            symbol = "$" + symbol
        price = str(game.get("home_score", "0.00"))
        if not price.startswith("$"):
            price = "$" + price
        change_pct = str(game.get("away_score", "0.00%"))
        situation = game.get("situation", {})
        situation = situation if isinstance(situation, dict) else {}
        change_amt = str(situation.get("change", "0.00"))
        if not change_amt.startswith("$") and not change_amt.startswith("-"):
            change_amt = "$" + change_amt
        if change_amt.startswith("-"):
            change_amt = change_amt.replace("-", "-$", 1)
        logo = self._logos.get(game.get("home_logo"), (24, 24))
        is_up = not change_pct.startswith("-")
        color = (0, 255, 0) if is_up else (255, 0, 0)
        if logo is not None:
            image.paste(logo, (2, 4), logo)
        x_text_start = 28 if logo is not None else 2
        draw.text((x_text_start, -2), symbol, font=self._fonts.big, fill="white")
        draw.text((x_text_start, 11), price, font=self._fonts.huge, fill=color)
        right = 126
        pct_width = draw.textlength(change_pct, font=self._fonts.medium)
        pct_x = int(right - pct_width)
        self._arrow(draw, pct_x - 6, 4, is_up, color)
        draw.text((pct_x, -1), change_pct, font=self._fonts.medium, fill=color)
        price_width = draw.textlength(price, font=self._fonts.huge)
        if pct_x - 6 > x_text_start + price_width + 6:
            amount_width = draw.textlength(change_amt, font=self._fonts.medium)
            draw.text((int(right - amount_width), 15), change_amt, font=self._fonts.medium, fill=color)
        return image

    def leaderboard(self, item: object) -> Image.Image:
        """Render the compact racing leaderboard card."""
        game = item if isinstance(item, dict) else {}
        image = Image.new("RGBA", (64, PANEL_H), (0, 0, 0, 255))
        draw = ImageDraw.Draw(image)
        sport = str(game.get("sport", "")).lower()
        accent = (100, 100, 100)
        if "f1" in sport:
            accent = (255, 0, 0)
        elif "nascar" in sport:
            accent = (255, 215, 0)
        elif "indy" in sport:
            accent = (0, 144, 255)
        draw.rectangle((0, 0, 63, 7), fill=(20, 20, 20))
        draw.line((0, 8, 63, 8), fill=accent)
        name = str(game.get("tourney_name", "")).upper().replace("GRAND PRIX", "GP").replace("TT", "").strip()[:14]
        tiny_text(draw, (64 - len(name) * 5) // 2, 1, name, (220, 220, 220), self._fonts.tiny)
        leaders = game.get("leaders", [])
        for index, player in enumerate(leaders[:3] if isinstance(leaders, list) else []):
            data = player if isinstance(player, dict) else {}
            rank_color = ((255, 215, 0), (192, 192, 192), (205, 127, 50))[index]
            name = str(data.get("name", "UNK"))[:3].upper()
            score = str(data.get("score", ""))
            display = "LDR" if "LEADER" in score.upper() else score
            y = 10 + index * 8
            tiny_text(draw, 1, y, index + 1, rank_color, self._fonts.tiny)
            tiny_text(draw, 8, y, name, "white", self._fonts.tiny)
            tiny_text(draw, 63 - len(display) * 5, y, display, (255, 100, 100), self._fonts.tiny)
        return image

    def update(self, context: RenderContext, step: str = "Updating...", progress: float | None = None, version: str = "") -> Image.Image:
        """Render the update progress panel."""
        image = Image.new("RGBA", (PANEL_W, PANEL_H), (0, 0, 0, 255))
        draw = ImageDraw.Draw(image)
        t = context.now.timestamp()
        bar_x = int((t * 80) % (PANEL_W + 60)) - 30
        for bx in range(bar_x, bar_x + 60):
            if 0 <= bx < PANEL_W:
                value = int((1.0 - abs(bx - (bar_x + 30)) / 30.0) * 80)
                draw.point((bx, 0), fill=(0, value, value))
        cx, cy = 10, 16
        for index in range(8):
            angle = index * math.pi / 4 + t * 3
            x = int(cx + math.cos(angle) * 7)
            y = int(cy + math.sin(angle) * 7)
            brightness = int(100 + 155 * ((math.sin(angle - t * 3) + 1) / 2))
            draw.point((x, y), fill=(0, brightness, brightness))
        draw.ellipse((cx - 2, cy - 2, cx + 2, cy + 2), fill=(0, 180, 180))
        label = str(step).upper()
        label_width = draw.textlength(label, font=self._fonts.normal)
        draw.text((int((PANEL_W - label_width) / 2), 1), label, font=self._fonts.normal, fill=(200, 220, 220))
        if version:
            value = f"→ {version}"
            width = draw.textlength(value, font=self._fonts.tiny)
            pulse = int(150 + 80 * math.sin(t * 2))
            draw.text((int((PANEL_W - width) / 2), 13), value, font=self._fonts.tiny, fill=(0, pulse, pulse))
        else:
            for index in range(5):
                y = 20 + int(math.sin(t * 4 + index * 0.6) * 3)
                x = PANEL_W // 2 - 12 + index * 6
                draw.ellipse((x, y, x + 2, y + 2), fill=(0, 200, 255))
        draw.rectangle((0, 31, PANEL_W - 1, 31), fill=(20, 20, 20))
        if progress is None:
            start = int((t * 100) % (PANEL_W + 80)) - 80
            for bx in range(start, start + 80):
                if 0 <= bx < PANEL_W:
                    draw.point((bx, 31), fill=(0, 180, 80))
        else:
            draw.rectangle((0, 31, int(max(0.0, min(1.0, progress)) * PANEL_W), 31), fill=(0, 200, 100))
        return image

    def update_overlay(self, frame: Image.Image, progress: float, version: str = "") -> Image.Image:
        """Overlay one compact update status and progress bar on a base frame."""

        image = frame.convert("RGBA")
        overlay = Image.new("RGBA", image.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)
        left, top, right, bottom = PANEL_W - 128, 19, PANEL_W - 3, 30
        draw.rounded_rectangle((left, top, right, bottom), radius=2, fill=(0, 0, 0, 225))
        tiny_text(draw, left + 4, top + 1, "UPDATING", (100, 220, 255), self._fonts.tiny)
        if version:
            text = version.upper()[-10:]
            tiny_text(draw, right - len(text) * 5 - 3, top + 1, text, (185, 195, 210), self._fonts.tiny)
        bar_left, bar_top, bar_right = left + 4, bottom - 3, right - 4
        draw.rectangle((bar_left, bar_top, bar_right, bottom - 1), fill=(25, 55, 65, 255))
        width = bar_right - bar_left
        fill = bar_left + round(width * max(0.0, min(1.0, progress)))
        draw.rectangle((bar_left, bar_top, fill, bottom - 1), fill=(0, 200, 120, 255))
        image.alpha_composite(overlay)
        return image.convert("RGB")

    def pairing(self, context: RenderContext, code: str | None) -> Image.Image:
        """Render the pairing panel."""
        image = Image.new("RGB", (PANEL_W, PANEL_H), "black")
        draw = ImageDraw.Draw(image)
        value = code or "------"
        header = "PAIR CODE"
        draw.text(((PANEL_W - draw.textlength(header, font=self._fonts.normal)) / 2, 0), header, font=self._fonts.normal, fill=(255, 200, 0))
        spaced = "  ".join(value)
        draw.text(((PANEL_W - draw.textlength(spaced, font=self._fonts.huge)) / 2, 10), spaced, font=self._fonts.huge, fill="white")
        if int(context.now.timestamp() * 2) % 2 == 0:
            draw.ellipse((PANEL_W - 8, 2, PANEL_W - 3, 7), fill=(0, 200, 255))
        return image

    def wifi_setup(self, context: RenderContext, state: WiFiSetupState | None) -> Image.Image:
        """Render the platform-owned Wi-Fi setup status without performing I/O."""

        image = Image.new("RGB", (PANEL_W, PANEL_H), "black")
        draw = ImageDraw.Draw(image)
        if state is None:
            title = "WIFI CHECK"
            detail = "CHECKING CONNECTION"
            accent = (120, 180, 220)
        elif state.internet_available:
            title = "WIFI ONLINE"
            detail = "CONNECTING TO TICKER"
            accent = (0, 220, 120)
        else:
            title = "OPEN TICKER CONTROL APP"
            detail = f"PIN: {state.setup_code}"
            accent = (255, 190, 0)
        draw.text((8, 2), title, font=self._fonts.normal, fill=accent)
        draw.text((8, 16), detail[:46], font=self._fonts.tiny, fill=(220, 220, 225))
        draw.rectangle((0, 31, PANEL_W - 1, 31), fill=accent)
        return image

    def offline(self, context: RenderContext, offline_for: float) -> Image.Image:
        """Render the backend link-loss panel."""
        image = Image.new("RGBA", (PANEL_W, PANEL_H), (0, 0, 0, 255))
        draw = ImageDraw.Draw(image)
        amber = (255, 170, 0)
        date = context.now.strftime("%A %B %d").upper()
        draw.text(((PANEL_W - draw.textlength(date, font=self._fonts.tiny)) / 2, -1), date, font=self._fonts.tiny, fill=(150, 150, 150))
        clock = context.now.strftime("%I:%M").lstrip("0")
        draw.text(((PANEL_W - draw.textlength(clock, font=self._fonts.clock)) / 2, 4), clock, font=self._fonts.clock, fill=(210, 210, 210))
        right = PANEL_W - 3
        label = "NO LINK"
        elapsed = offline_elapsed_label(offline_for)
        draw.text((right - draw.textlength(label, font=self._fonts.tiny), 6), label, font=self._fonts.tiny, fill=amber)
        draw.text((right - draw.textlength(elapsed, font=self._fonts.tiny), 16), elapsed, font=self._fonts.tiny, fill=(150, 110, 0))
        if int(context.now.timestamp() * 2) % 2 == 0:
            x = int(right - draw.textlength(label, font=self._fonts.tiny) - 6)
            draw.ellipse((x, 7, x + 3, 10), fill=amber)
        draw.rectangle((0, 31, PANEL_W - 1, 31), fill=(90, 60, 0))
        return image

    def empty(self, context: RenderContext) -> Image.Image:
        """Render a clock-led no-games panel."""
        image = Image.new("RGBA", (PANEL_W, PANEL_H), (0, 0, 0, 255))
        draw = ImageDraw.Draw(image)
        accent = (198, 198, 204)
        muted = (104, 104, 112)
        draw.rectangle((0, 0, PANEL_W - 1, 0), fill=(38, 38, 44))

        icon_left, icon_top, icon_right, icon_bottom = 8, 10, 23, 24
        draw.rectangle((icon_left, icon_top, icon_right, icon_bottom), outline=muted)
        draw.line((icon_left, icon_top + 4, icon_right, icon_top + 4), fill=accent)
        draw.line((icon_left + 4, icon_top - 2, icon_left + 4, icon_top + 2), fill=accent)
        draw.line((icon_right - 4, icon_top - 2, icon_right - 4, icon_top + 2), fill=accent)
        draw.point((icon_left + 4, icon_top + 8), fill=(220, 220, 224))
        draw.point((icon_left + 8, icon_top + 8), fill=(220, 220, 224))
        draw.point((icon_left + 12, icon_top + 8), fill=(220, 220, 224))

        divider_x = 196
        draw.line((divider_x, 5, divider_x, 27), fill=(48, 48, 54))
        left = 32
        draw.text((left, 7), "NO GAMES", font=self._fonts.normal, fill=(245, 245, 248))
        draw.text((left, 19), "CHECK BACK LATER", font=self._fonts.tiny, fill=(142, 142, 150))

        date_day = context.now.strftime("%a").upper()
        date_month_day = context.now.strftime("%b %d").upper()
        draw.text((207, 6), date_day, font=self._fonts.tiny, fill=(150, 150, 158))
        draw.text((207, 16), date_month_day, font=self._fonts.tiny, fill=(150, 150, 158))
        clock = context.now.strftime("%I:%M %p").lstrip("0")
        draw.text((PANEL_W - 8, -1), clock, font=self._fonts.clock, fill=(245, 245, 248), anchor="ra")

        total_seconds = context.now.second + (context.now.microsecond / 1_000_000.0)
        progress_width = int((total_seconds / 60.0) * PANEL_W)
        draw.rectangle((0, 31, PANEL_W - 1, 31), fill=(42, 42, 48))
        draw.rectangle((0, 31, progress_width, 31), fill=accent)
        return image

    @staticmethod
    def _arrow(draw: ImageDraw.ImageDraw, x: int, y: int, up: bool, color: object) -> None:
        if up:
            draw.polygon([(x + 2, y), (x, y + 4), (x + 4, y + 4)], fill=color)
        else:
            draw.polygon([(x, y), (x + 4, y), (x + 2, y + 4)], fill=color)
