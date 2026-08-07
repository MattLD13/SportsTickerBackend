#!/usr/bin/env python3
"""Render the scrolling NFL card so the possession football can be eyeballed."""

import os
import sys

from PIL import Image

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from tools.fetch_and_render import make_renderer, prefetch_logos, save_image
from tools.mock_data_helper import make_mock_game

OUT_PATH = "previews/possession_football.png"
ZOOM = 4


def espn_logo(abbr):
    return f"https://a.espncdn.com/i/teamlogos/nfl/500/{abbr.lower()}.png"


def nfl_card(game_id, possessor, down_dist, red_zone=False):
    return make_mock_game(
        sport="nfl", game_id=game_id,
        away="BUF", home="KC",
        away_score=24, home_score=27,
        status="Q4 1:47", state="in",
        situation={
            "possession": possessor,
            "downDist": down_dist,
            "isRedZone": red_zone,
        },
    ) | {
        "home_color": "#E31837", "away_color": "#00338D",
        "home_logo": espn_logo("kc"), "away_logo": espn_logo("buf"),
    }


def main():
    games = [
        nfl_card(4012345, "KC", "1st & 10"),
        nfl_card(4012346, "BUF", "3rd & 6", red_zone=True),
    ]
    renderer = make_renderer("sports")
    prefetch_logos(renderer, games)

    cards = [renderer.draw_single_game(g).convert("RGB") for g in games]
    gap = 4
    strip = Image.new(
        "RGB",
        (sum(c.width for c in cards) + gap * (len(cards) - 1), cards[0].height),
        (0, 0, 0),
    )
    x = 0
    for card in cards:
        strip.paste(card, (x, 0))
        x += card.width + gap

    save_image(strip.resize((strip.width * ZOOM, strip.height * ZOOM), Image.NEAREST), OUT_PATH)


if __name__ == "__main__":
    raise SystemExit(main())
