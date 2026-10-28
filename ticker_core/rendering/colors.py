"""Classify and parse panel colors for Six renderers."""

from __future__ import annotations


def parse_hex_color(value):
    """Parse one RGB hex value."""
    try:
        value = str(value or "").strip().lstrip("#")
        if len(value) == 6:
            return tuple(int(value[index:index + 2], 16) for index in (0, 2, 4))
    except ValueError:
        pass
    return None


def is_near_black(color, lum_threshold=24, max_threshold=42, chroma_threshold=16):
    """Identify colours that disappear on the panel."""
    if not color or len(color) < 3:
        return True
    red, green, blue = (int(value) for value in color[:3])
    luma = 0.2126 * red + 0.7152 * green + 0.0722 * blue
    return (max(red, green, blue) <= max_threshold and luma <= lum_threshold) or (max(red, green, blue) <= max_threshold + 6 and luma <= lum_threshold + 4 and max(red, green, blue) - min(red, green, blue) <= chroma_threshold)


def is_near_white(color, lum_threshold=236, min_channel_threshold=226):
    """Identify colours that remove contrast."""
    if not color or len(color) < 3:
        return False
    red, green, blue = (int(value) for value in color[:3])
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue >= lum_threshold or min(red, green, blue) >= min_channel_threshold


def relative_luminance(color: tuple[int, int, int]) -> float:
    """Return the standard linear-light luminance for one sRGB pixel."""

    channels = []
    for value in color:
        channel = value / 255
        channels.append(channel / 12.92 if channel <= 0.04045 else ((channel + 0.055) / 1.055) ** 2.4)
    return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2]
