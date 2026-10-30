"""Draw one stock quote: the logo and symbol, the price, and the change in percent and dollars."""
from __future__ import annotations

from PIL import Image, ImageDraw

from ..frame import ContentScene, Logos, NoLogos, RenderContext, RenderedContent
from ..layers import ImageTemplates, image_key
from ..palette import STOCK_GAIN, STOCK_LOSS
from ..text import FontSet

WIDTH, HEIGHT, RIGHT = 128, 32, 126


class StockCard:
    def __init__(self, fonts: FontSet, logos: Logos | None = None) -> None:
        self._fonts = fonts
        self._logos = logos or NoLogos()
        self._layers = ImageTemplates()

    def render(self, context: RenderContext, scene: ContentScene) -> RenderedContent:
        kind = str(scene.item.get("type", "")).lower()
        if kind == "stock_ticker" or str(scene.item.get("sport", "")).lower().startswith("stock"):
            return RenderedContent(self.pane(scene.item))
        raise ValueError(f"StockCard cannot draw {kind!r}.")

    def pane(self, item: object) -> Image.Image:
        quote = item if isinstance(item, dict) else {}
        symbol = str(quote.get("home_abbr", "UNK"))
        if not symbol.startswith("$") and not any(char.isdigit() for char in symbol):
            symbol = "$" + symbol
        price = str(quote.get("home_score", "0.00"))
        price = price if price.startswith("$") else "$" + price
        percent = str(quote.get("away_score", "0.00%"))
        situation = quote.get("situation", {})
        amount = str((situation if isinstance(situation, dict) else {}).get("change", "0.00"))
        amount = amount.replace("-", "-$", 1) if amount.startswith("-") else amount if amount.startswith("$") else "$" + amount
        logo = self._logos.get(quote.get("home_logo"), (24, 24))
        rising = not percent.startswith("-")
        color = STOCK_GAIN if rising else STOCK_LOSS
        text_x = 28 if logo is not None else 2
        image = self._layers.render((symbol, image_key(logo)), lambda: self._symbol_layer(symbol, logo, text_x))
        draw = ImageDraw.Draw(image)
        draw.text((text_x, 11), price, font=self._fonts.huge, fill=color)
        percent_x = int(RIGHT - draw.textlength(percent, font=self._fonts.medium))
        _arrow(draw, percent_x - 6, 4, rising, color)
        draw.text((percent_x, -1), percent, font=self._fonts.medium, fill=color)
        # The dollar change shows only when it has room beside the price.
        if percent_x - 6 > text_x + draw.textlength(price, font=self._fonts.huge) + 6:
            draw.text((int(RIGHT - draw.textlength(amount, font=self._fonts.medium)), 15), amount, font=self._fonts.medium, fill=color)
        return image

    def _symbol_layer(self, symbol: str, logo: Image.Image | None, text_x: int) -> Image.Image:
        image = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 255))
        if logo is not None:
            image.paste(logo, (2, 4), logo)
        ImageDraw.Draw(image).text((text_x, -2), symbol, font=self._fonts.big, fill="white")
        return image


def _arrow(draw: ImageDraw.ImageDraw, x: int, y: int, up: bool, color: object) -> None:
    points = [(x + 2, y), (x, y + 4), (x + 4, y + 4)] if up else [(x, y), (x + 4, y), (x + 2, y + 4)]
    draw.polygon(points, fill=color)
