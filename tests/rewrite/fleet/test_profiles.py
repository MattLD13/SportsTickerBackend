from __future__ import annotations

import pytest

from sports_ticker.fleet import TickerProfile


def test_full_profile_has_six_panel_geometry() -> None:
    profile = TickerProfile.from_mapping({"product_family": "full"})

    assert profile.display.width == 384
    assert profile.display.panel_count == 6
    assert "weather" in profile.capabilities.modes


def test_legacy_normal_profile_reads_as_full() -> None:
    profile = TickerProfile.from_mapping({"product_family": "normal"})

    assert profile.product_family == "full"


def test_mini_profile_has_one_panel_and_sports_only() -> None:
    profile = TickerProfile.from_mapping({"product_family": "mini"})

    assert profile.display.width == 64
    assert profile.display.panel_count == 1
    assert profile.capabilities.modes == ("sports",)


def test_custom_profile_requires_geometry() -> None:
    with pytest.raises(ValueError, match="custom profiles need display"):
        TickerProfile.from_mapping({"product_family": "custom"})
