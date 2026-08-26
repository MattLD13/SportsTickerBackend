from __future__ import annotations

import pytest

from sports_ticker.providers.normalization import normalize_content


pytestmark = pytest.mark.critical


def test_sports_logo_override_updates_top_level_and_nested_display_urls() -> None:
    """Use one centralized override URL in every scoreboard logo projection."""

    content = normalize_content(
        [
            {
                "id": "mlb-game",
                "family": "sports",
                "kind": "scoreboard",
                "data": {
                    "sport": "baseball",
                    "away_abbr": "NYY",
                    "home_abbr": "COL",
                    "away_logo": "https://old.example/yankees.png",
                    "home_logo": "https://old.example/rockies.png",
                    "display": {
                        "away": {"label": "NYY", "logo": "https://old.example/yankees.png"},
                        "home": {"label": "COL", "logo": "https://old.example/rockies.png"},
                    },
                },
            }
        ],
        {},
    )

    game = content[0].data
    assert game["away_logo"].endswith("New_York_Yankees_logo.svg.png")
    assert game["home_logo"].endswith("Colorado_Rockies_logo.svg.png")
    assert game["display"]["away"]["logo"] == game["away_logo"]
    assert game["display"]["home"]["logo"] == game["home_logo"]
