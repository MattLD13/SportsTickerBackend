"""Compose the pane strip used by hardware and public previews."""

from collections.abc import Iterable

from PIL import Image, ImageDraw


def compose_pane_strip(panes: Iterable[tuple[Image.Image | None, int]], height: int = 32) -> Image.Image:
    """Keep production pane widths and place one divider before each pane."""
    records = tuple(panes)
    image = Image.new("RGB", (max(1, sum(width for _, width in records)), height), "black")
    draw = ImageDraw.Draw(image)
    x = 0
    for pane, width in records:
        draw.line((x, 0, x, height - 1), fill=(45, 45, 45))
        if pane is not None:
            rgba = pane.convert("RGBA")
            image.paste(rgba, (x + 1, 0), rgba)
        x += width
    return image
