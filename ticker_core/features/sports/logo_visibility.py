"""Keep small sports marks legible on each local display background."""

from __future__ import annotations

from enum import Enum

from PIL import Image, ImageFilter


_CONTRAST_RATIO_THRESHOLD = 2.0
_COLOR_DISTANCE_THRESHOLD_SQUARED = 12 * 12
_SCROLL_MIN_CONTRASTING_FRACTION = 0.30
_FULL_MIN_CONTRASTING_FRACTION = 0.20
_KEYLINE_COLORS = ((244, 247, 250), (8, 12, 18))
_ALPHA_THRESHOLD = 160
_NEIGHBOR_OFFSETS = (
    (-1, -1), (0, -1), (1, -1),
    (-1, 0), (1, 0),
    (-1, 1), (0, 1), (1, 1),
)


class LogoOutlineMode(str, Enum):
    """Select the display-specific logo outline policy."""

    SCROLL = "scroll"
    FULL = "full"


def paste_team_logo(
    canvas: Image.Image,
    logo: Image.Image,
    xy: tuple[int, int],
    *,
    outline_mode: LogoOutlineMode = LogoOutlineMode.SCROLL,
) -> bool:
    """Paste a logo and apply the selected display outline policy."""

    mark = logo.convert("RGBA")
    outline_mode = LogoOutlineMode(outline_mode)
    x, y = int(xy[0]), int(xy[1])
    width, height = mark.size
    background = canvas.crop((x, y, x + width, y + height)).convert("RGBA")
    edge_pairs = _logo_edge_pairs(mark, background)
    visible_pairs = _logo_pixel_pairs(mark, background)
    min_contrasting_fraction = (
        _FULL_MIN_CONTRASTING_FRACTION
        if outline_mode is LogoOutlineMode.FULL
        else _SCROLL_MIN_CONTRASTING_FRACTION
    )
    if (
        edge_pairs
        and visible_pairs
        and _needs_keyline(edge_pairs, min_contrasting_fraction)
        and _needs_keyline(visible_pairs, min_contrasting_fraction)
    ):
        line_color = _keyline_color(edge_pairs)
        edge = mark.getchannel("A").filter(ImageFilter.MaxFilter(3))
        keyline = Image.new("RGBA", mark.size, (*line_color, 255))
        canvas.paste(keyline, (x, y), edge)
        added_keyline = True
    else:
        added_keyline = False

    canvas.paste(mark, (x, y), mark)
    return added_keyline


def _logo_edge_pairs(
    mark: Image.Image,
    background: Image.Image,
) -> list[tuple[tuple[int, int, int], tuple[int, int, int]]]:
    """Compare opaque logo edges with the pixels below them."""

    width, height = mark.size
    mark_pixels = mark.load()
    background_pixels = background.load()
    pairs = []
    for y in range(height):
        for x in range(width):
            red, green, blue, alpha = mark_pixels[x, y]
            if alpha < _ALPHA_THRESHOLD or not _is_edge_pixel(mark_pixels, x, y, width, height):
                continue
            under = background_pixels[x, y]
            pairs.append(((red, green, blue), (under[0], under[1], under[2])))
    return pairs


def _logo_pixel_pairs(
    mark: Image.Image,
    background: Image.Image,
) -> list[tuple[tuple[int, int, int], tuple[int, int, int]]]:
    """Compare opaque logo pixels with the pixels below them."""

    mark_pixels = mark.load()
    background_pixels = background.load()
    pairs = []
    for y in range(mark.height):
        for x in range(mark.width):
            red, green, blue, alpha = mark_pixels[x, y]
            if alpha < _ALPHA_THRESHOLD:
                continue
            under = background_pixels[x, y]
            pairs.append(((red, green, blue), (under[0], under[1], under[2])))
    return pairs


def _is_edge_pixel(pixels, x: int, y: int, width: int, height: int) -> bool:
    """Return true when an opaque pixel touches transparency or the logo edge."""

    for dx, dy in _NEIGHBOR_OFFSETS:
        nx, ny = x + dx, y + dy
        if nx < 0 or nx >= width or ny < 0 or ny >= height:
            return True
        if pixels[nx, ny][3] < _ALPHA_THRESHOLD:
            return True
    return False


def _needs_keyline(
    visible_pairs: list[tuple[tuple[int, int, int], tuple[int, int, int]]],
    min_contrasting_fraction: float,
) -> bool:
    """Measure the share of the logo that contrasts with the pixels below it."""

    contrasted = sum(
        1
        for mark, background in visible_pairs
        if _is_contrasting(mark, background)
    )
    return contrasted / len(visible_pairs) < min_contrasting_fraction


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
    edge_pairs: list[tuple[tuple[int, int, int], tuple[int, int, int]]],
) -> tuple[int, int, int]:
    """Choose a light or dark keyline that separates from both mark and background."""

    count = len(edge_pairs)
    mark_mean = tuple(sum(mark[channel] for mark, _ in edge_pairs) // count for channel in range(3))
    background_mean = tuple(sum(background[channel] for _, background in edge_pairs) // count for channel in range(3))

    def score(candidate: tuple[int, int, int]) -> int:
        mark_distance = max(abs(candidate[channel] - mark_mean[channel]) for channel in range(3))
        background_distance = max(abs(candidate[channel] - background_mean[channel]) for channel in range(3))
        return min(mark_distance, background_distance)

    return max(_KEYLINE_COLORS, key=score)
