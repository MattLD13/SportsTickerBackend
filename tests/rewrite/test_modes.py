import random

import pytest

from sports_ticker.domain import DisplaySettings
from sports_ticker.projections import data_api
from sports_ticker.projections.data_api import _SPORTS_ADS
from sports_ticker.projections import select_display_content
from ticker_core.protocol import TickerResponse
from ticker_core.runtime import classify_content
from ticker_core.modes import DisplayMode, display_mode

pytestmark = pytest.mark.critical


def test_campaign_catalog_uses_reviewed_copy() -> None:
    """Keep reviewed parody copy separate from sourced campaign copy."""

    spots = [spot for ad in _SPORTS_ADS for spot in ad["spots"]]
    copies = {str(spot["copy"]) for spot in spots}
    expected_parody = {
        "PLAY YOUR AD BREAK.",
        "ALL THE ADS YOU LOVE.",
        "NO SWEAT. SAME REGRET.",
        "IT'S ON. AGAIN.",
        "RUN YOUR AD BREAK.",
        "PLAYOFF PICKS. SURE.",
        "IN-PLAY. STILL LOSING.",
        "FANCASH? CASH-ISH.",
        "YOU DID IT. WE MADE ADS.",
        "FORECAST: MORE ADS.",
        "MORE THAN A NAME. AN AD.",
        "NO STRESS. JUST BAD BEATS.",
    }
    stale_copy = {
        "PLAY YOUR GAME",
        "ALL THE SPORTS YOU LOVE",
        "NO SWEAT BET",
        "IT'S ON",
        "RUN YOUR GAME",
        "GET IN THE ACTION",
        "PLAYOFF PICKS",
        "YOUR PALACE AWAITS",
        "NEVER ORDINARY",
        "IN-PLAY BETTING",
        "FANCASH? TAKES COINS.",
        "BET $5, GET $100",
        "YOU DID IT, FLORIDA",
        "HOMETOWN",
        "MORE FORECASTS.",
        "MORE THAN A NAME",
        "BOOST YOUR GAMEDAY",
        "NO-STRESS. BAD FONT.",
    }

    assert expected_parody <= copies
    assert not stale_copy & copies
    assert all(
        spot["source_url"] is None
        for spot in spots
        if spot["source_type"] == "parody"
    )


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
    with pytest.raises(ValueError):
        DisplaySettings(sports_filter="removed_filter")


def test_sports_filter_marks_cards_without_removing_them_from_the_app_feed() -> None:
    content = {
        "sports": [
            {"id": "live", "family": "sports", "kind": "scoreboard", "is_shown": True, "data": {"sport": "nfl", "state": "in", "away_abbr": "NYG", "home_abbr": "DAL"}},
            {"id": "scheduled", "family": "sports", "kind": "scoreboard", "is_shown": True, "data": {"sport": "nfl", "state": "pre", "away_abbr": "PHI", "home_abbr": "WAS"}},
        ]
    }
    live_only = select_display_content(content, {"mode": "sports", "sports_filter": "live"})
    my_teams = select_display_content(content, {"mode": "sports", "sports_filter": "my_teams", "my_teams": ["nfl:WAS"]})
    pinned = select_display_content(content, {"mode": "sports", "pinned_content_id": "scheduled"})

    assert [item["is_shown"] for item in live_only["sports"]] == [True, False]
    assert [item["is_shown"] for item in my_teams["sports"]] == [False, True]
    assert [item["is_shown"] for item in pinned["sports"]] == [False, True]

    response = TickerResponse.from_payload({
        "api_version": "v2",
        "snapshot": {"ticker_id": "ticker-1", "revision": 1, "observed_at": "2026-08-11T00:00:00+00:00", "stale": False},
        "settings": {"mode": "sports", "sports_presentation": "pinned", "pinned_content_id": "scheduled", "brightness": 100, "scroll_speed": 0.05, "inverted": False},
        "content": pinned,
        "events": {"alerts": [], "news": []},
        "health": {"provider": "test", "healthy": True, "error": None},
        "meta": {"pairing": {"paired": True, "code": None}},
    })
    classified = classify_content(response.content, "sports", sports_presentation="pinned", pinned_content_id="scheduled")

    assert [item.id for item in classified.static] == ["scheduled"]


def test_campaign_parody_ad_is_server_enabled_at_45_seconds(monkeypatch) -> None:
    content = {
        "sports": [
            {
                "id": f"game-{index}",
                "family": "sports",
                "kind": "scoreboard",
                "is_shown": True,
                "data": {"sport": "nfl", "state": "in", "away_abbr": "NYG", "home_abbr": "DAL"},
            }
            for index in range(36)
        ]
    }

    disabled = select_display_content(content, {"mode": "sports", "sports_filter": "all"})
    assert all(item["kind"] != "fan_duel_joke_ad" for item in disabled["sports"])

    random_seed = 0

    def next_randomizer() -> random.Random:
        nonlocal random_seed
        random_seed += 1
        return random.Random(random_seed)

    monkeypatch.setattr(data_api, "_sports_ad_rng", next_randomizer)

    enabled = select_display_content(
        content,
        {
            "mode": "sports",
            "sports_filter": "all",
            "live_delay_mode": True,
            "live_delay_seconds": 45,
        },
    )
    ads = [item for item in enabled["sports"] if item["kind"] == "fan_duel_joke_ad"]
    assert len(ads) == 12
    assert [item["id"] for item in ads] == [
        f"sports:real-campaign-ad-{index}"
        for index in range(1, 13)
    ]
    assert [index for index, item in enumerate(enabled["sports"]) if item["kind"] == "fan_duel_joke_ad"] == [
        4 * index + 3 for index in range(12)
    ]
    assert all(item["is_shown"] is True for item in ads)
    assert len({item["data"]["headline"] for item in ads}) == 12
    assert len({item["data"]["tagline"] for item in ads}) == 12
    ad_brands = [item["data"]["headline"] for item in ads]
    assert all(
        brand not in ad_brands[max(0, index - 3):index]
        for index, brand in enumerate(ad_brands)
    )
    assert all(item["data"]["campaign"] for item in ads)
    assert all(item["data"]["style"] for item in ads)
    assert all(item["data"]["source_type"] in {"official", "ad_archive", "parody"} for item in ads)
    assert all(
        item["data"]["source_type"] == "parody"
        or item["data"]["source_url"].startswith("https://")
        for item in ads
    )
    assert any(item["data"]["source_type"] == "parody" for item in ads)
    assert all(item["data"]["detail"] == "PARODY" for item in ads)
    assert all(item["data"]["tagline"] != "KALSHI" for item in ads)
    assert all("TYPO" not in item["data"]["tagline"] for item in ads)
    assert all("{" not in item["data"]["tagline"] for item in ads)

    repeat = select_display_content(
        content,
        {
            "mode": "sports",
            "sports_filter": "all",
            "live_delay_mode": True,
            "live_delay_seconds": 45,
        },
    )
    repeat_ads = [item for item in repeat["sports"] if item["kind"] == "fan_duel_joke_ad"]
    assert [item["data"]["tagline"] for item in repeat_ads] != [item["data"]["tagline"] for item in ads]

    expanded = select_display_content(
        {
            "sports": content["sports"] + [
                {
                    "id": f"game-extra-{index}",
                    "family": "sports",
                    "kind": "scoreboard",
                    "is_shown": True,
                    "data": {"sport": "nfl", "state": "in", "away_abbr": "NYG", "home_abbr": "DAL"},
                }
                for index in range(36)
            ]
        },
        {
            "mode": "sports",
            "sports_filter": "all",
            "live_delay_mode": True,
            "live_delay_seconds": 45,
        },
    )
    twelve_ads = [item for item in expanded["sports"] if item["kind"] == "fan_duel_joke_ad"]
    assert len(twelve_ads) == 24
    assert [index for index, item in enumerate(expanded["sports"])
        if item["kind"] == "fan_duel_joke_ad"
    ] == [4 * index + 3 for index in range(24)]
    expected_brands = {
        "POLYMARKET",
        "FANDUEL",
        "DRAFTKINGS",
        "BETMGM",
        "PRIZEPICKS",
        "UNDERDOG",
        "CAESARS SPORTSBOOK",
        "BET365",
        "FANATICS SPORTSBOOK",
        "HARD ROCK BET",
        "KALSHI",
        "BALLY BET",
    }
    assert set(item["data"]["headline"] for item in twelve_ads[:12]) == expected_brands
    assert set(item["data"]["headline"] for item in twelve_ads[12:]) == expected_brands
    twelve_brands = [item["data"]["headline"] for item in twelve_ads]
    assert all(
        brand not in twelve_brands[max(0, index - 3):index]
        for index, brand in enumerate(twelve_brands)
    )

    toggle_off = select_display_content(
        content,
        {
            "mode": "sports",
            "sports_filter": "all",
            "fan_duel_joke_ad": False,
            "live_delay_mode": True,
            "live_delay_seconds": 45,
        },
    )
    assert [item["kind"] for item in toggle_off["sports"]].count("fan_duel_joke_ad") == 12

    disabled_delay = select_display_content(
        content,
        {
            "mode": "sports",
            "sports_filter": "all",
            "fan_duel_joke_ad": True,
            "live_delay_mode": True,
            "live_delay_seconds": 60,
        },
    )
    assert all(item["kind"] != "fan_duel_joke_ad" for item in disabled_delay["sports"])

    disabled_mode = select_display_content(
        content,
        {
            "mode": "sports",
            "sports_filter": "all",
            "fan_duel_joke_ad": True,
            "live_delay_mode": False,
            "live_delay_seconds": 45,
        },
    )
    assert all(item["kind"] != "fan_duel_joke_ad" for item in disabled_mode["sports"])

    pinned = select_display_content(
        content,
        {
            "mode": "sports",
            "sports_filter": "all",
            "pinned_content_id": "game-0",
            "fan_duel_joke_ad": True,
            "live_delay_mode": True,
            "live_delay_seconds": 45,
        },
    )
    assert all(item["kind"] != "fan_duel_joke_ad" for item in pinned["sports"])
