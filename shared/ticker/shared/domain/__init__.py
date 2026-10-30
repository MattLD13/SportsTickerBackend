"""Canonical backend domain models."""

from ticker.shared.domain.models import (
    CONTENT_FAMILIES,
    DISPLAY_MODES,
    SPORTS_FILTERS,
    SPORTS_PRESENTATIONS,
    ContentItem,
    DisplaySettings,
)
from ticker.shared.domain.events import Event, News, NewsEvent, OverlayEvent, ScoreAlert, ScoreAlertEvent
from ticker.shared.domain.snapshot import SnapshotContent, SnapshotEvents, TickerSnapshot
from ticker.shared.domain.schedule import (
    SCHEDULE_CONDITION_KINDS,
    SCHEDULE_CONDITION_OPERATORS,
    SCHEDULE_DAY_NAMES,
    SCHEDULE_WEEKDAYS,
    ScheduleBlock,
    ScheduleCondition,
)

__all__ = [
    "ContentItem",
    "CONTENT_FAMILIES",
    "DISPLAY_MODES",
    "DisplaySettings",
    "Event",
    "News",
    "NewsEvent",
    "OverlayEvent",
    "ScoreAlert",
    "ScoreAlertEvent",
    "SnapshotContent",
    "SnapshotEvents",
    "TickerSnapshot",
    "SCHEDULE_CONDITION_KINDS",
    "SCHEDULE_CONDITION_OPERATORS",
    "SCHEDULE_DAY_NAMES",
    "SCHEDULE_WEEKDAYS",
    "ScheduleBlock",
    "ScheduleCondition",
    "SPORTS_PRESENTATIONS",
    "SPORTS_FILTERS",
]
