"""Keep small sports marks legible on each local display background."""

from __future__ import annotations

from PIL import Image, ImageFilter


_CONTRAST_RATIO_THRESHOLD = 2.0
_COLOR_DISTANCE_THRESHOLD_SQUARED = 96 * 96
_MIN_VISIBLE_FRACTION = 0.30
_KEYLINE_COLORS = ((244, 247, 250), (8, 12, 18))


def paste_team_logo(canvas: Image.Image, logo: Image.Image, xy: tuple[int, int]) -> bool:
    """Paste a logo and add a one-pixel keyline only when local contrast stays low."""

    mark = logo.convert("RGBA")
    x, y = int(xy[0]), int(xy[1])
    width, height = mark.size
    background = canvas.crop((x, y, x + width, y + height)).convert("RGBA")
    mark_pixels = mark.load()
    background_pixels = background.load()

    visible_pairs: list[tuple[tuple[int, int, int], tuple[int, int, int]]] = []
    for py in range(height):
        for px in range(width):
            red, green, blue, alpha = mark_pixels[px, py]
            if alpha >= 160:
                under = background_pixels[px, py]
                visible_pairs.append(((red, green, blue), (under[0], under[1], under[2])))

    if visible_pairs and _needs_keyline(visible_pairs):
        line_color = _keyline_color(visible_pairs)
        edge = mark.getchannel("A").filter(ImageFilter.MaxFilter(3))
        keyline = Image.new("RGBA", mark.size, (*line_color, 255))
        canvas.paste(keyline, (x, y), edge)
        added_keyline = True
    else:
        added_keyline = False

    canvas.paste(mark, (x, y), mark)
    return added_keyline


def _needs_keyline(
    visible_pairs: list[tuple[tuple[int, int, int], tuple[int, int, int]]],
) -> bool:
    """Measure the share of the logo that contrasts with the pixels below it."""

    contrasted = sum(
        1
        for mark, background in visible_pairs
        if _is_contrasting(mark, background)
    )
    return contrasted / len(visible_pairs) < _MIN_VISIBLE_FRACTION


def _is_contrasting(mark: tuple[int, int, int], background: tuple[int, int, int]) -> bool:
    """Count readable luminance or saturated-colour differences."""

    if _contrast_ratio(mark, background) >= _CONTRAST_RATIO_THRESHOLD:
        return True
    distance_squared = sum((mark[channel] - background[channel]) ** 2 for channel in range(3))
    return distance_squared >= _COLOR_DISTANCE_THRESHOLD_SQUARED


def _relative_luminance(color: tuple[int, int, int]) -> float:
    """Return the standard linear-light luminance for one sRGB pixel."""

    channels = []
    for value in color:
        channel = value / 255
        channels.append(channel / 12.92 if channel <= 0.04045 else ((channel + 0.055) / 1.055) ** 2.4)
    return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2]


def _contrast_ratio(first: tuple[int, int, int], second: tuple[int, int, int]) -> float:
    """Return the WCAG luminance contrast ratio for two sRGB pixels."""

    first_luminance = _relative_luminance(first)
    second_luminance = _relative_luminance(second)
    lighter = max(first_luminance, second_luminance)
    darker = min(first_luminance, second_luminance)
    return (lighter + 0.05) / (darker + 0.05)


def _keyline_color(
    visible_pairs: list[tuple[tuple[int, int, int], tuple[int, int, int]]],
) -> tuple[int, int, int]:
    """Choose a light or dark keyline that separates from both mark and background."""

    count = len(visible_pairs)
    mark_mean = tuple(sum(mark[channel] for mark, _ in visible_pairs) // count for channel in range(3))
    background_mean = tuple(sum(background[channel] for _, background in visible_pairs) // count for channel in range(3))

    def score(candidate: tuple[int, int, int]) -> int:
        mark_distance = max(abs(candidate[channel] - mark_mean[channel]) for channel in range(3))
        background_distance = max(abs(candidate[channel] - background_mean[channel]) for channel in range(3))
        return min(mark_distance, background_distance)

    return max(_KEYLINE_COLORS, key=score)
