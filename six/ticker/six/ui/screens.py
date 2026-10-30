"""Draw the controller screens that are not content: no games, pairing, Wi-Fi setup, no link, updates, and connection loss."""
from __future__ import annotations

from datetime import datetime

from PIL import Image, ImageDraw

from ticker.six.platform.wifi import WiFiSetupState

from ticker.six.ui.frame import ContentScene, ItemKey, RenderContext, RenderedContent
from ticker.six.ui.text import FontSet, draw_tiny

WIDTH, HEIGHT = 384, 32
AMBER = (255, 170, 0)
FAILURES = {"rolled_back": "RESTORED", "download_failed": "OLD KEPT"}


class Screens:
    def __init__(self, fonts: FontSet) -> None:
        self._key = ItemKey("empty")
        self._fonts = fonts

    def visual_key(self, context: RenderContext, scene: ContentScene, asset_revision: int | None = None) -> object:
        # The minute rail moves one pixel for each 384th of a minute.
        return self._key(scene, asset_revision, int(context.now.timestamp() * 384 / 60.0))

    def render(self, context: RenderContext, scene: ContentScene) -> RenderedContent:
        """Draw the no-games screen for an item that marks empty content."""
        return RenderedContent(self.empty(context.now))

    def empty(self, now: datetime) -> Image.Image:
        """Draw a calendar icon, "NO GAMES", the date, the time, and the minute rail."""
        image = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 255))
        draw = ImageDraw.Draw(image)
        accent, muted, dots = (198, 198, 204), (104, 104, 112), (220, 220, 224)
        draw.rectangle((0, 0, WIDTH - 1, 0), fill=(38, 38, 44))
        draw.rectangle((8, 10, 23, 24), outline=muted)
        draw.line((8, 14, 23, 14), fill=accent)
        draw.line((12, 8, 12, 12), fill=accent)
        draw.line((19, 8, 19, 12), fill=accent)
        for x in (12, 16, 20):
            draw.point((x, 18), fill=dots)
        divider = 196
        draw.line((divider, 5, divider, 27), fill=(48, 48, 54))
        draw.text((32, 7), "NO GAMES", font=self._fonts.normal, fill=(245, 245, 248))
        draw.text((32, 19), "CHECK BACK LATER", font=self._fonts.tiny, fill=(142, 142, 150))
        clock = now.strftime("%I:%M %p").lstrip("0")
        clock_left = WIDTH - 1 - draw.textlength(clock, font=self._fonts.clock)
        day, date = now.strftime("%a").upper(), now.strftime("%b %d").upper()
        date_width = max(draw.textlength(day, font=self._fonts.tiny), draw.textlength(date, font=self._fonts.tiny))
        date_left = divider + 6
        if date_left + date_width + 6 > clock_left:
            date_left = max(divider + 6, int(clock_left - date_width - 6))
        draw.text((date_left, 6), day, font=self._fonts.tiny, fill=(150, 150, 158))
        draw.text((date_left, 16), date, font=self._fonts.tiny, fill=(150, 150, 158))
        draw.text((WIDTH - 1, -1), clock, font=self._fonts.clock, fill=(245, 245, 248), anchor="ra")
        seconds = now.second + now.microsecond / 1_000_000.0
        draw.rectangle((0, 31, WIDTH - 1, 31), fill=(42, 42, 48))
        draw.rectangle((0, 31, int(seconds / 60.0 * WIDTH), 31), fill=accent)
        return image

    def pairing(self, now: datetime, code: str | None) -> Image.Image:
        """Draw the pairing code, and a dot that blinks twice each second."""
        image = Image.new("RGB", (WIDTH, HEIGHT), "black")
        draw = ImageDraw.Draw(image)
        normal, huge = self._fonts.normal, self._fonts.huge
        draw.text(((WIDTH - draw.textlength("PAIR CODE", font=normal)) / 2, 0), "PAIR CODE", font=normal, fill=(255, 200, 0))
        spaced = "  ".join(code or "------")
        draw.text(((WIDTH - draw.textlength(spaced, font=huge)) / 2, 10), spaced, font=huge, fill="white")
        if int(now.timestamp() * 2) % 2 == 0:
            draw.ellipse((WIDTH - 8, 2, WIDTH - 3, 7), fill=(0, 200, 255))
        return image

    def wifi_setup(self, state: WiFiSetupState | None) -> Image.Image:
        """Draw the Wi-Fi setup state that the platform reports."""
        image = Image.new("RGB", (WIDTH, HEIGHT), "black")
        draw = ImageDraw.Draw(image)
        if state is None:
            title, detail, accent = "WIFI CHECK", "CHECKING CONNECTION", (120, 180, 220)
        elif state.internet_available:
            title, detail, accent = "WIFI ONLINE", "CONNECTING TO TICKER", (0, 220, 120)
        else:
            title, detail, accent = "OPEN TICKER CONTROL APP", f"PIN: {state.setup_code}", (255, 190, 0)
        draw.text((8, 2), title, font=self._fonts.normal, fill=accent)
        draw.text((8, 16), detail[:46], font=self._fonts.tiny, fill=(220, 220, 225))
        draw.rectangle((0, 31, WIDTH - 1, 31), fill=accent)
        return image

    def offline(self, now: datetime, offline_for: float) -> Image.Image:
        """Draw the date, the time, and how long the backend link has been down."""
        image = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 255))
        draw = ImageDraw.Draw(image)
        tiny = self._fonts.tiny
        date = now.strftime("%A %B %d").upper()
        draw.text(((WIDTH - draw.textlength(date, font=tiny)) / 2, -1), date, font=tiny, fill=(150, 150, 150))
        clock = now.strftime("%I:%M").lstrip("0")
        draw.text(((WIDTH - draw.textlength(clock, font=self._fonts.clock)) / 2, 4), clock, font=self._fonts.clock, fill=(210, 210, 210))
        right = WIDTH - 3
        age = offline_age(offline_for)
        draw.text((right - draw.textlength("NO LINK", font=tiny), 6), "NO LINK", font=tiny, fill=AMBER)
        draw.text((right - draw.textlength(age, font=tiny), 16), age, font=tiny, fill=(150, 110, 0))
        if int(now.timestamp() * 2) % 2 == 0:
            x = int(right - draw.textlength("NO LINK", font=tiny) - 6)
            draw.ellipse((x, 7, x + 3, 10), fill=AMBER)
        draw.rectangle((0, 31, WIDTH - 1, 31), fill=(90, 60, 0))
        return image


def update_overlay(frame: Image.Image, progress: float, version: str = "", *, failure_status: str = "") -> Image.Image:
    """Draw the update box and its progress bar in the bottom right corner of a frame."""
    image = frame.convert("RGBA")
    overlay = Image.new("RGBA", image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    left, top, right, bottom = WIDTH - 128, 19, WIDTH - 3, 30
    draw.rounded_rectangle((left, top, right, bottom), radius=2, fill=(0, 0, 0, 225))
    failed = bool(failure_status)
    draw_tiny(draw, left + 4, top + 1, "UPDATE FAILED" if failed else "UPDATING", (255, 75, 75) if failed else (100, 220, 255))
    if failed:
        label = FAILURES[failure_status]
        draw_tiny(draw, right - len(label) * 5 - 3, top + 1, label, (190, 160, 160))
    elif version:
        text = version.upper()[-10:]
        draw_tiny(draw, right - len(text) * 5 - 3, top + 1, text, (185, 195, 210))
    bar_left, bar_top, bar_right = left + 4, bottom - 3, right - 4
    draw.rectangle((bar_left, bar_top, bar_right, bottom - 1), fill=(25, 55, 65, 255))
    if failed:
        draw.rectangle((bar_left, bar_top, bar_right, bottom - 1), fill=(125, 30, 30, 255))
    else:
        filled = bar_left + round((bar_right - bar_left) * max(0.0, min(1.0, progress)))
        draw.rectangle((bar_left, bar_top, filled, bottom - 1), fill=(0, 200, 120, 255))
    image.alpha_composite(overlay)
    return image.convert("RGB")


def offline_age(seconds: float) -> str:
    """Return the link-loss age in seconds, minutes, hours, or days."""
    value = int(max(0, seconds))
    if value < 60:
        return f"{value}S"
    if value < 3600:
        return f"{value // 60}M"
    if value < 86400:
        return f"{value // 3600}H"
    return f"{value // 86400}D"


def connection_lost(frame: Image.Image) -> Image.Image:
    """Return the frame with a crossed server icon in the top right corner."""
    image = frame.convert("RGBA")
    overlay = Image.new("RGBA", image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    left = image.width - 12
    draw.rounded_rectangle((left, 0, image.width - 1, 9), radius=2, fill=(0, 0, 0, 215))
    draw.rectangle((left + 2, 2, left + 8, 7), outline=(210, 215, 225, 255))
    draw.line((left + 3, 4, left + 7, 4), fill=(100, 110, 125, 255))
    draw.point((left + 3, 6), fill=(255, 180, 20, 255))
    draw.line((left + 1, 8, left + 10, 0), fill=(255, 70, 70, 255), width=2)
    image.alpha_composite(overlay)
    return image.convert("RGB")
