"""Define the shared weekly schedule rules."""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite

from .models import DISPLAY_MODES


SCHEDULE_DAY_GROUPS: tuple[str, ...] = ("weekdays", "weekends")
SCHEDULE_CONDITION_KINDS: tuple[str, ...] = ("live_games",)


def _timestamp(value: object) -> float:
    """Normalize one schedule timestamp."""

    result = float(value)
    if not isfinite(result) or result < 0:
        raise ValueError("schedule timestamps must be finite and non-negative")
    return result


@dataclass(frozen=True, slots=True)
class ScheduleBlock:
    """Represent one recurring time block in one day group."""

    id: str
    day_group: str
    start_minute: int
    end_minute: int
    mode: str
    enabled: bool = True
    created_at: float = 0.0
    updated_at: float = 0.0

    def __post_init__(self) -> None:
        """Normalize and validate one weekly time block."""

        identifier = str(self.id).strip()
        if not identifier:
            raise ValueError("schedule block id must not be empty")
        day_group = str(self.day_group).strip().lower()
        if day_group not in SCHEDULE_DAY_GROUPS:
            choices = ", ".join(SCHEDULE_DAY_GROUPS)
            raise ValueError(f"day_group must be one of: {choices}")
        start = _minute(self.start_minute, "start_minute")
        end = _minute(self.end_minute, "end_minute")
        if start >= end:
            raise ValueError("schedule block end_minute must be after start_minute")
        mode = str(self.mode).strip().lower()
        if mode not in DISPLAY_MODES:
            choices = ", ".join(DISPLAY_MODES)
            raise ValueError(f"schedule block mode must be one of: {choices}")
        object.__setattr__(self, "id", identifier)
        object.__setattr__(self, "day_group", day_group)
        object.__setattr__(self, "start_minute", start)
        object.__setattr__(self, "end_minute", end)
        object.__setattr__(self, "mode", mode)
        object.__setattr__(self, "enabled", bool(self.enabled))
        object.__setattr__(self, "created_at", _timestamp(self.created_at))
        object.__setattr__(self, "updated_at", _timestamp(self.updated_at))


@dataclass(frozen=True, slots=True)
class ScheduleCondition:
    """Represent one recurring live-data condition."""

    id: str
    kind: str
    threshold: int
    mode: str
    enabled: bool = True
    created_at: float = 0.0
    updated_at: float = 0.0

    def __post_init__(self) -> None:
        """Normalize and validate one live-data condition."""

        identifier = str(self.id).strip()
        if not identifier:
            raise ValueError("schedule condition id must not be empty")
        kind = str(self.kind).strip().lower()
        if kind not in SCHEDULE_CONDITION_KINDS:
            choices = ", ".join(SCHEDULE_CONDITION_KINDS)
            raise ValueError(f"condition kind must be one of: {choices}")
        try:
            threshold = int(self.threshold)
        except (TypeError, ValueError) as error:
            raise ValueError("condition threshold must be an integer") from error
        if isinstance(self.threshold, bool) or threshold < 1:
            raise ValueError("condition threshold must be at least 1")
        mode = str(self.mode).strip().lower()
        if mode not in DISPLAY_MODES:
            choices = ", ".join(DISPLAY_MODES)
            raise ValueError(f"condition mode must be one of: {choices}")
        object.__setattr__(self, "id", identifier)
        object.__setattr__(self, "kind", kind)
        object.__setattr__(self, "threshold", threshold)
        object.__setattr__(self, "mode", mode)
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
    "SCHEDULE_DAY_GROUPS",
    "ScheduleBlock",
    "ScheduleCondition",
]
