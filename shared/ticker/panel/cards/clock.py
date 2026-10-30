"""Draw the full-panel clock: the date, the time, and a rail that fills once each minute."""
from __future__ import annotations

from datetime import datetime

from PIL import Image, ImageDraw

from ticker.panel.frame import ContentScene, ItemKey, RenderContext, RenderedContent
from ticker.panel.layers import ImageTemplates
from ticker.panel.palette import CLOCK_DATE, CLOCK_PROGRESS, CLOCK_RAIL, SCORE_TEXT
from ticker.panel.text import FontSet

WIDTH, HEIGHT = 384, 32


class ClockCard:
    def __init__(self, fonts: FontSet) -> None:
        self._key = ItemKey("clock")
        self._date_font, self._time_font = fonts.tiny, fonts.clock
        # The date changes once a day, so its layer comes from a small template cache.
        self._dates = ImageTemplates(capacity=2, max_bytes=128 * 1024)

    def visual_key(self, context: RenderContext, scene: ContentScene, asset_revision: int | None = None) -> object:
        # The time shows whole seconds.
        return self._key(scene, asset_revision, int(context.now.timestamp()))

    def render(self, context: RenderContext, scene: ContentScene) -> RenderedContent:
        return RenderedContent(self.frame(context.now))

    def frame(self, now: datetime) -> Image.Image:
        date = now.strftime("%A %B %d").upper()
        image = self._dates.render(date, lambda: self._date_layer(date))
        draw = ImageDraw.Draw(image)
        time = now.strftime("%I:%M:%S").lstrip("0")
        draw.text(((WIDTH - draw.textlength(time, font=self._time_font)) / 2, 4), time, font=self._time_font, fill=SCORE_TEXT)
        seconds = now.second + now.microsecond / 1_000_000.0
        draw.rectangle((0, 31, WIDTH, 31), fill=CLOCK_RAIL)
        draw.rectangle((0, 31, int(seconds / 60.0 * WIDTH), 31), fill=CLOCK_PROGRESS)
        return image

    def _date_layer(self, date: str) -> Image.Image:
        image = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 255))
        draw = ImageDraw.Draw(image)
        draw.text(((WIDTH - draw.textlength(date, font=self._date_font)) / 2, -1), date, font=self._date_font, fill=CLOCK_DATE)
        return image
