"""Compose the pane strip used by hardware and public previews."""

from collections.abc import Iterable

from PIL import Image, ImageDraw

from .style import INACTIVE


def compose_pane_strip(
    panes: Iterable[tuple[Image.Image | None, int]],
    height: int = 32,
    *,
    divider_colors: Iterable[tuple[int, int, int]] | None = None,
) -> Image.Image:
    """Keep production pane widths and place one divider before each pane."""
    records = tuple(panes)
    colors = tuple(divider_colors) if divider_colors is not None else (INACTIVE,) * len(records)
    if len(colors) != len(records):
        raise ValueError("Each pane must have one divider color.")
    image = Image.new("RGB", (max(1, sum(width for _, width in records)), height), "black")
    draw = ImageDraw.Draw(image)
    x = 0
    for (pane, width), color in zip(records, colors):
        draw.line((x, 0, x, height - 1), fill=color)
        if pane is not None:
            rgba = pane.convert("RGBA")
            image.paste(rgba, (x + 1, 0), rgba)
        x += width
    return image
