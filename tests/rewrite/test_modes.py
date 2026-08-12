import pytest

from ticker_core.modes import DisplayMode, display_mode


def test_only_six_user_modes_exist():
    assert tuple(DisplayMode) == (
        DisplayMode.SPORTS,
        DisplayMode.SPORTS_FULL,
        DisplayMode.WEATHER,
        DisplayMode.MUSIC,
        DisplayMode.FLIGHTS,
        DisplayMode.CLOCK,
    )
    with pytest.raises(ValueError):
        display_mode("nascar_full")
