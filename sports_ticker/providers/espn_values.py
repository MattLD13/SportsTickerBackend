"""Read shared ESPN payload values for the ESPN provider modules."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
import re
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .payloads import as_mapping as _mapping


def _event_competition(payload: Any) -> Mapping[str, Any]:
    """Read one competition from an ESPN event response."""

    source = _mapping(payload)
    header = _mapping(source.get("header"))
    return _first_mapping(header.get("competitions") or source.get("competitions"))


def _merge_mapping(
    base: Mapping[str, Any],
    overlay: Mapping[str, Any],
) -> dict[str, Any]:
    """Overlay nonempty source fields while retaining scoreboard fields."""

    merged = dict(base)
    for key, value in overlay.items():
        if value is not None and (not isinstance(value, Mapping) or value):
            merged[key] = value
    return merged


def _display_timezone(value: str) -> ZoneInfo:
    """Use the ticker time zone or the established New York default."""

    try:
        return ZoneInfo(value.strip() or "America/New_York")
    except ZoneInfoNotFoundError:
        return ZoneInfo("America/New_York")


def _event_time(value: object) -> datetime | None:
    """Read one ESPN event start time as a UTC datetime."""

    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)


def _competitors(value: Any) -> tuple[Mapping[str, Any], ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise TypeError("competition competitors must be an array")
    return tuple(item for item in value if isinstance(item, Mapping))


def _find_side(competitors: Sequence[Mapping[str, Any]], side: str) -> Mapping[str, Any]:
    for competitor in competitors:
        if str(competitor.get("homeAway", "")).strip().lower() == side:
            return competitor
    index = 0 if side == "home" else 1
    return competitors[index] if len(competitors) > index else {}


def _score_number(value: Any) -> int | None:
    """Read one scoreboard score, or return None when the source has no number."""

    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _sequence(value: Any) -> tuple[Any, ...]:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return tuple(value)
    return ()


def _hex_color(value: Any) -> str:
    """Return a renderer-ready six digit color or an empty value."""

    text = _text(value).strip().lstrip("#")
    if len(text) != 6:
        return ""
    try:
        int(text, 16)
    except ValueError:
        return ""
    return f"#{text.upper()}"


_SCHEDULED_DATE_PREFIX = re.compile(r"^\d{1,2}/\d{1,2}\s*-\s*")


_SCHEDULED_TIME = re.compile(r"(?P<time>\d{1,2}:\d{2})\s*(?P<meridiem>[AP]M)\b")


def _first_mapping(value: Any) -> Mapping[str, Any]:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)) and value:
        return _mapping(value[0])
    return {}


def _text(value: Any, default: str = "") -> str:
    return default if value is None else str(value)
