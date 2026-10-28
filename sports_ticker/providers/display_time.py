"""Resolve the time zone that provider content uses for local display times."""

from __future__ import annotations

from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


def display_timezone(value: object) -> ZoneInfo:
    """Use the ticker time zone, or New York when it is empty or unknown."""
    try:
        return ZoneInfo(str(value).strip() or "America/New_York")
    except ZoneInfoNotFoundError:
        return ZoneInfo("America/New_York")
