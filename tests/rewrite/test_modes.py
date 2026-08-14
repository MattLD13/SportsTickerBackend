import pytest

from sports_ticker.domain import DisplaySettings
from ticker_core.modes import DisplayMode, display_mode


def test_user_modes_have_one_explicit_owner():
    assert tuple(DisplayMode) == (
        DisplayMode.SPORTS,
        DisplayMode.WEATHER,
        DisplayMode.MUSIC,
        DisplayMode.FLIGHTS,
        DisplayMode.AIRPORTS,
        DisplayMode.STOCK,
        DisplayMode.CLOCK,
    )
    with pytest.raises(ValueError):
        display_mode("nascar_full")
    with pytest.raises(ValueError):
        DisplaySettings(mode="removed_mode")
