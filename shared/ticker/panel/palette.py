"""Own the LED colors of the Six and the shared Mini drawing data, and classify team colors."""

from __future__ import annotations

from collections.abc import Iterable

BACKGROUND = (0, 0, 0)
HEADER_RULE = (55, 76, 130)
PLAYOFF_RULE = (192, 192, 192)
FINALS_RULE = (255, 215, 0)
STATUS_TEXT = (255, 240, 150)
SCORE_TEXT = (255, 255, 255)
PLAY_TEXT = (0, 200, 60)
RED_ZONE_TEXT = (235, 70, 70)
RED_ZONE_BORDER = (255, 40, 40)
POWER_PLAY = (255, 220, 0)
EMPTY_NET = (255, 100, 100)
MUTED_TEXT = (200, 210, 225)
INACTIVE = (45, 45, 45)
BALL = (60, 200, 60)
STRIKE = (255, 140, 40)
OUT = (210, 70, 70)
BASE = (255, 200, 55)
RANK = (255, 220, 80)
TOURNAMENT_SEED = (66, 117, 199)
CLOCK_DATE = (200, 200, 200)
CLOCK_RAIL = (30, 30, 30)
CLOCK_PROGRESS = (0, 200, 255)
STOCK_GAIN = (0, 255, 0)
STOCK_LOSS = (255, 0, 0)

MINI_LOGO_SIZE = 16


def sports_rule_color(stage: object, default=HEADER_RULE):
    """Return the shared rule color for an explicit competition stage."""
    if type(stage) is not int:
        return default
    return FINALS_RULE if stage == 2 else PLAYOFF_RULE if stage == 1 else default


def pane_divider_colors(stages: Iterable[object]) -> list[tuple[int, int, int]]:
    """Color both pane boundaries and give finals priority at a shared boundary."""
    stages = tuple(stages)
    colors = []
    for index, stage in enumerate(stages):
        adjacent = (stages[index - 1], stage)
        selected = max(value if type(value) is int and value in (0, 1, 2) else 0 for value in adjacent)
        colors.append(sports_rule_color(selected, INACTIVE))
    return colors


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
