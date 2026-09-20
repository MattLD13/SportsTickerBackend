"""Render a simple team-color badge when a sports logo is missing."""

from __future__ import annotations

from collections.abc import Sequence

from PIL import Image, ImageDraw

from ticker_core.rendering.pixels import draw_hybrid_text, normalize_special_chars

_BADGE_MASK_SCALE = 4


def draw_missing_team_badge(
    image: Image.Image,
    xy: tuple[int, int],
    size: int,
    team_color: Sequence[int] | None,
    abbreviation: object,
) -> None:
    """Draw a smooth acronym badge where one team logo is missing."""

    if size < 8:
        return

    x, y = int(xy[0]), int(xy[1])
    color = _rgb(team_color)
    foreground = (250, 252, 255, 255) if _relative_luminance(color) < 0.18 else (8, 12, 18, 255)
    mask_size = size * _BADGE_MASK_SCALE
    mask = Image.new("L", (mask_size, mask_size), 0)
    mask_draw = ImageDraw.Draw(mask)
    inset = max(1, size // 16)
    radius = max(1, round((size - 2 * inset) * 0.22))
    mask_draw.rounded_rectangle(
        (
            inset * _BADGE_MASK_SCALE,
            inset * _BADGE_MASK_SCALE,
            (size - inset) * _BADGE_MASK_SCALE - 1,
            (size - inset) * _BADGE_MASK_SCALE - 1,
        ),
        radius=radius * _BADGE_MASK_SCALE,
        fill=255,
    )
    mask = mask.resize((size, size), Image.Resampling.LANCZOS)
    badge = Image.new("RGBA", (size, size), (*color, 255))
    image.paste(badge, (x, y), mask)

    label = _badge_label(abbreviation)
    letter_step = 4 if len(label) == 4 else 5
    text_width = (len(label) - 1) * letter_step + 4
    text_x = x + max(0, (size - text_width) // 2)
    text_y = y + (size - 6) // 2
    draw = ImageDraw.Draw(image, "RGBA")
    for index, character in enumerate(label):
        draw_hybrid_text(draw, text_x + index * letter_step, text_y, character, foreground)


def _badge_label(value: object) -> str:
    """Keep the supplied team code compact and safe for the ticker font."""

    normalized = normalize_special_chars(str(value or "")).strip().upper()
    compact = "".join(character for character in normalized if character.isalnum() or character in "-&")
    return compact[:4] or "?"


def _rgb(color: Sequence[int] | None) -> tuple[int, int, int]:
    """Return a safe RGB team color."""

    try:
        channels = tuple(max(0, min(255, int(channel))) for channel in color[:3]) if color else ()
    except (TypeError, ValueError):
        channels = ()
    if len(channels) != 3:
        return (86, 104, 132)
    return channels


def _relative_luminance(color: tuple[int, int, int]) -> float:
    """Measure badge fill luminance to select a readable acronym color."""

    channels = []
    for value in color:
        channel = value / 255
        channels.append(channel / 12.92 if channel <= 0.04045 else ((channel + 0.055) / 1.055) ** 2.4)
    return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2]
