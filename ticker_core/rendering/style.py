"""Own shared LED colors for the main ticker and generated Mini drawing data."""

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
