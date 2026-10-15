"""Draw a changing game clock over a cached scoreboard pane."""

from PIL import Image, ImageDraw

from ticker_core.rendering.pixels import draw_hybrid_text


def draw_clock_header(frame: Image.Image, card_x: int, card_width: int, label: str) -> None:
    """Replace only the centered header text while keeping the pane surface cached."""

    text = str(label or "").upper()[:12]
    header_width = min(64, card_width - 48)
    if not text or header_width <= 0:
        return
    left = card_x + (card_width - header_width) // 2
    draw = ImageDraw.Draw(frame)
    draw.rectangle((left, 0, left + header_width - 1, 6), fill=(0, 0, 0))
    text_x = card_x + (card_width - len(text) * 5) // 2
    draw_hybrid_text(draw, text_x + 1, 2, text, (8, 8, 8))
    draw_hybrid_text(draw, text_x, 1, text, (255, 240, 150))
