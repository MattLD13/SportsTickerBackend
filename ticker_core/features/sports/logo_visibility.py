"""Keep small sports marks legible on each local display background."""

from __future__ import annotations

from enum import Enum

from PIL import Image, ImageChops, ImageFilter


_CONTRAST_RATIO_THRESHOLD = 2.0
_COLOR_DISTANCE_THRESHOLD_SQUARED = 12 * 12
_FULL_COLOR_DISTANCE_THRESHOLD_SQUARED = 32 * 32
_SCROLL_MIN_CONTRASTING_FRACTION = 0.20
_FULL_MIN_CONTRASTING_FRACTION = 0.25
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
    distance_squared = (
        _FULL_COLOR_DISTANCE_THRESHOLD_SQUARED
        if outline_mode is LogoOutlineMode.FULL
        else _COLOR_DISTANCE_THRESHOLD_SQUARED
    )
    selected_outline = getattr(logo, "logo_rendering_outline", None)
    if selected_outline in {"off", "inner", "auto"}:
        cutoff = float(getattr(logo, "logo_rendering_cutoff", 0.0))
        needs_outline = selected_outline == "inner" or (
            selected_outline == "auto" and mean_edge_brightness(mark) <= cutoff
        )
        canvas.paste(mark, (x, y), mark)
        if needs_outline:
            contour = _inner_contour_mask(mark)
            if selected_outline == "auto":
                blending, _, _ = _classify_edges(mark, background, distance_squared)
                needed = ImageChops.lighter(_dark_pixel_mask(mark, cutoff), blending)
                contour = _contour_segments(contour, needed)
            keyline = Image.new("RGBA", mark.size, (244, 247, 250, 255))
            canvas.paste(keyline, (x, y), contour)
        return needs_outline

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
        and _needs_keyline(edge_pairs, min_contrasting_fraction, distance_squared)
        and _needs_keyline(visible_pairs, min_contrasting_fraction, distance_squared)
    ):
        blending, visible, blending_pairs = _classify_edges(mark, background, distance_squared)
        line_color = _keyline_color(blending_pairs)
        edge = ImageChops.multiply(
            mark.getchannel("A").filter(ImageFilter.MaxFilter(3)),
            _keyline_reach(blending, visible),
        )
        keyline = Image.new("RGBA", mark.size, (*line_color, 255))
        canvas.paste(keyline, (x, y), edge)
        added_keyline = True
    else:
        added_keyline = False

    canvas.paste(mark, (x, y), mark)
    return added_keyline


def _inner_contour_mask(mark: Image.Image) -> Image.Image:
    """Trace every silhouette boundary one opaque pixel inside the mark."""
    silhouette = mark.getchannel("A").point(lambda value: 255 if value >= _ALPHA_THRESHOLD else 0)
    padded = Image.new("L", (mark.width + 2, mark.height + 2), 0)
    padded.paste(silhouette, (1, 1))
    eroded = padded.filter(ImageFilter.MinFilter(3)).crop((1, 1, mark.width + 1, mark.height + 1))
    return ImageChops.subtract(silhouette, eroded)


def _dark_pixel_mask(mark: Image.Image, cutoff: float) -> Image.Image:
    """Select the pixels that have a brightness at or below the darkness cutoff."""
    brightness = mark.convert("RGB").convert("L", matrix=(0.2126, 0.7152, 0.0722, 0))
    return brightness.point(lambda value: 255 if value <= cutoff else 0)


def _contour_segments(contour: Image.Image, needed: Image.Image) -> Image.Image:
    """Keep the contour runs that need a keyline as clean segments.

    A contour pixel between two selected contour pixels joins the segment. A
    selected pixel with no selected contour neighbor is a speck and stays unlined.
    """

    segments = ImageChops.multiply(contour, needed)
    bridged = ImageChops.multiply(contour, _neighbor_count(segments).point(lambda count: 255 if count >= 2 else 0))
    segments = ImageChops.lighter(segments, bridged)
    return ImageChops.multiply(segments, _neighbor_count(segments).point(lambda count: 255 if count >= 1 else 0))


def _neighbor_count(mask: Image.Image) -> Image.Image:
    """Count the selected pixels in the eight neighbors of each pixel."""
    padded = Image.new("L", (mask.width + 2, mask.height + 2), 0)
    padded.paste(mask.point(lambda value: 1 if value else 0), (1, 1))
    counted = padded.filter(ImageFilter.Kernel((3, 3), (1, 1, 1, 1, 0, 1, 1, 1, 1), scale=1))
    return counted.crop((1, 1, mask.width + 1, mask.height + 1))


def _classify_edges(
    mark: Image.Image,
    background: Image.Image,
    minimum_distance_squared: int,
) -> tuple[Image.Image, Image.Image, list[tuple[tuple[int, int, int], tuple[int, int, int]]]]:
    """Split opaque edge pixels into blending and visible masks against the pixels below them."""

    width, height = mark.size
    mark_pixels = mark.load()
    background_pixels = background.load()
    blending = Image.new("L", mark.size, 0)
    visible = Image.new("L", mark.size, 0)
    blending_pixels, visible_pixels = blending.load(), visible.load()
    pairs = []
    for y in range(height):
        for x in range(width):
            red, green, blue, alpha = mark_pixels[x, y]
            if alpha < _ALPHA_THRESHOLD or not _is_edge_pixel(mark_pixels, x, y, width, height):
                continue
            under = background_pixels[x, y][:3]
            if _is_contrasting((red, green, blue), under, minimum_distance_squared):
                visible_pixels[x, y] = 255
                continue
            blending_pixels[x, y] = 255
            pairs.append(((red, green, blue), under))
    return blending, visible, pairs


def _keyline_reach(blending: Image.Image, visible: Image.Image) -> Image.Image:
    """Limit the keyline to the pixels nearest a blending edge segment.

    The keyline covers the soft logo fringe two pixels out. A pixel two pixels
    out stays clear when a visible edge pixel is nearer to it.
    """

    near = blending.filter(ImageFilter.MaxFilter(3))
    far = ImageChops.subtract(
        blending.filter(ImageFilter.MaxFilter(5)),
        visible.filter(ImageFilter.MaxFilter(3)),
    )
    return ImageChops.lighter(near, far)


def mean_edge_brightness(mark: Image.Image) -> float:
    """Return the mean sRGB brightness along the visible logo silhouette."""
    pairs = _logo_edge_pairs(mark.convert("RGBA"), Image.new("RGBA", mark.size, (0, 0, 0, 255)))
    if not pairs:
        return 255.0
    return sum(0.2126 * color[0] + 0.7152 * color[1] + 0.0722 * color[2] for color, _ in pairs) / len(pairs)


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
    minimum_distance_squared: int,
) -> bool:
    """Measure the share of the logo that contrasts with the pixels below it."""

    contrasted = sum(
        1
        for mark, background in visible_pairs
        if _is_contrasting(mark, background, minimum_distance_squared)
    )
    return contrasted / len(visible_pairs) < min_contrasting_fraction


def _is_contrasting(
    mark: tuple[int, int, int],
    background: tuple[int, int, int],
    minimum_distance_squared: int,
) -> bool:
    """Count readable luminance or saturated-colour differences."""

    if _contrast_ratio(mark, background) >= _CONTRAST_RATIO_THRESHOLD:
        return True
    distance_squared = sum((mark[channel] - background[channel]) ** 2 for channel in range(3))
    return distance_squared >= minimum_distance_squared


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
