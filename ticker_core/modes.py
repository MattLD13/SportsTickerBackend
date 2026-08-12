"""Define the complete user-facing display modes."""

from ticker_core._enum import StrEnum


class DisplayMode(StrEnum):
    """Name one selectable ticker mode."""

    SPORTS = "sports"
    SPORTS_FULL = "sports_full"
    WEATHER = "weather"
    MUSIC = "music"
    FLIGHTS = "flights"
    CLOCK = "clock"


def display_mode(value: object) -> DisplayMode:
    """Validate one user-facing mode value."""
    try:
        return DisplayMode(str(value).strip().lower())
    except ValueError as error:
        raise ValueError(f"Unknown display mode {value!r}.") from error
