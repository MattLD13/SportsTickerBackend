"""Define per-ticker weekly schedule rules and live sports conditions."""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Iterable

from .models import DISPLAY_MODES, SPORTS_FILTERS


SCHEDULE_WEEKDAYS: tuple[int, ...] = tuple(range(7))
SCHEDULE_DAY_NAMES: tuple[str, ...] = (
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
)
SCHEDULE_CONDITION_KINDS: tuple[str, ...] = ("live_games",)
SCHEDULE_CONDITION_OPERATORS: tuple[str, ...] = ("gt", "gte")


def _timestamp(value: object) -> float:
    """Normalize one schedule timestamp."""

    result = float(value)
    if not isfinite(result) or result < 0:
        raise ValueError("schedule timestamps must be finite and non-negative")
    return result


def _days(value: Iterable[object]) -> tuple[int, ...]:
    """Normalize one non-empty weekly day set."""

    values: list[int] = []
    for item in value:
        if isinstance(item, bool):
            raise ValueError("days_of_week must contain integers")
        try:
            day = int(item)
        except (TypeError, ValueError) as error:
            raise ValueError("days_of_week must contain integers") from error
        if day not in SCHEDULE_WEEKDAYS:
            raise ValueError("days_of_week values must be between 0 and 6")
        values.append(day)
    normalized = tuple(sorted(set(values)))
    if not normalized:
        raise ValueError("days_of_week must not be empty")
    return normalized


@dataclass(frozen=True, slots=True)
class ScheduleBlock:
    """Represent one recurring weekly block owned by one ticker."""

    id: str
    ticker_id: str
    days_of_week: tuple[int, ...]
    start_minute: int
    end_minute: int
    mode: str
    sports_filter: str | None = None
    enabled: bool = True
    created_at: float = 0.0
    updated_at: float = 0.0

    def __post_init__(self) -> None:
        """Normalize and validate one recurring weekly block."""

        identifier = str(self.id).strip()
        ticker_id = str(self.ticker_id).strip()
        if not identifier:
            raise ValueError("schedule block id must not be empty")
        if not ticker_id:
            raise ValueError("schedule block ticker_id must not be empty")
        start = _minute(self.start_minute, "start_minute")
        end = _minute(self.end_minute, "end_minute")
        if start >= end:
            raise ValueError("schedule block end_minute must be after start_minute")
        mode = str(self.mode).strip().lower()
        if mode not in DISPLAY_MODES:
            choices = ", ".join(DISPLAY_MODES)
            raise ValueError(f"schedule block mode must be one of: {choices}")
        sports_filter = None if self.sports_filter is None else str(self.sports_filter).strip().lower()
        if sports_filter == "":
            sports_filter = None
        if sports_filter is not None:
            if mode != "sports":
                raise ValueError("sports_filter requires sports mode")
            if sports_filter not in SPORTS_FILTERS:
                choices = ", ".join(SPORTS_FILTERS)
                raise ValueError(f"sports_filter must be one of: {choices}")
        object.__setattr__(self, "id", identifier)
        object.__setattr__(self, "ticker_id", ticker_id)
        object.__setattr__(self, "days_of_week", _days(self.days_of_week))
        object.__setattr__(self, "start_minute", start)
        object.__setattr__(self, "end_minute", end)
        object.__setattr__(self, "mode", mode)
        object.__setattr__(self, "sports_filter", sports_filter)
        object.__setattr__(self, "enabled", bool(self.enabled))
        object.__setattr__(self, "created_at", _timestamp(self.created_at))
        object.__setattr__(self, "updated_at", _timestamp(self.updated_at))


@dataclass(frozen=True, slots=True)
class ScheduleCondition:
    """Represent one recurring live-game condition owned by one ticker."""

    id: str
    ticker_id: str
    kind: str
    threshold: int
    operator: str = "gt"
    when_mode: str = "sports"
    action_sports_filter: str = "live"
    ignore_pinned: bool = True
    enabled: bool = True
    created_at: float = 0.0
    updated_at: float = 0.0

    def __post_init__(self) -> None:
        """Normalize and validate one live-game condition."""

        identifier = str(self.id).strip()
        ticker_id = str(self.ticker_id).strip()
        if not identifier:
            raise ValueError("schedule condition id must not be empty")
        if not ticker_id:
            raise ValueError("schedule condition ticker_id must not be empty")
        kind = str(self.kind).strip().lower()
        if kind not in SCHEDULE_CONDITION_KINDS:
            choices = ", ".join(SCHEDULE_CONDITION_KINDS)
            raise ValueError(f"condition kind must be one of: {choices}")
        operator = str(self.operator).strip().lower()
        if operator not in SCHEDULE_CONDITION_OPERATORS:
            choices = ", ".join(SCHEDULE_CONDITION_OPERATORS)
            raise ValueError(f"condition operator must be one of: {choices}")
        try:
            threshold = int(self.threshold)
        except (TypeError, ValueError) as error:
            raise ValueError("condition threshold must be an integer") from error
        if isinstance(self.threshold, bool) or threshold < 1:
            raise ValueError("condition threshold must be at least 1")
        when_mode = str(self.when_mode).strip().lower()
        if when_mode not in DISPLAY_MODES:
            choices = ", ".join(DISPLAY_MODES)
            raise ValueError(f"condition when_mode must be one of: {choices}")
        if when_mode != "sports":
            raise ValueError("live-game conditions require sports mode")
        action_filter = str(self.action_sports_filter).strip().lower()
        if action_filter != "live":
            raise ValueError("live-game conditions must switch to live sports")
        if not bool(self.ignore_pinned):
            raise ValueError("live-game conditions must not override pinned sports")
        object.__setattr__(self, "id", identifier)
        object.__setattr__(self, "ticker_id", ticker_id)
        object.__setattr__(self, "kind", kind)
        object.__setattr__(self, "threshold", threshold)
        object.__setattr__(self, "operator", operator)
        object.__setattr__(self, "when_mode", when_mode)
        object.__setattr__(self, "action_sports_filter", action_filter)
        object.__setattr__(self, "ignore_pinned", bool(self.ignore_pinned))
        object.__setattr__(self, "enabled", bool(self.enabled))
        object.__setattr__(self, "created_at", _timestamp(self.created_at))
        object.__setattr__(self, "updated_at", _timestamp(self.updated_at))


def _minute(value: object, name: str) -> int:
    """Normalize one minute offset within a local day."""

    if isinstance(value, bool):
        raise ValueError(f"{name} must be an integer minute")
    try:
        result = int(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"{name} must be an integer minute") from error
    if isinstance(value, float) and not value.is_integer():
        raise ValueError(f"{name} must be an integer minute")
    if not 0 <= result <= 1440:
        raise ValueError(f"{name} must be between 0 and 1440")
    return result


__all__ = [
    "SCHEDULE_CONDITION_KINDS",
    "SCHEDULE_CONDITION_OPERATORS",
    "SCHEDULE_DAY_NAMES",
    "SCHEDULE_WEEKDAYS",
    "ScheduleBlock",
    "ScheduleCondition",
]
