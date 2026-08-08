#!/usr/bin/env python3
"""Render the my-teams score alert takeover for a spread of real scoring plays.

Writes a still from the middle of the hold phase plus an animated GIF of the
whole sequence (slam in, hold, slam out) for each alert.

    python tools/render_score_alerts.py --out-dir previews/score_alerts
"""

from __future__ import annotations

import argparse
import os
import sys

from PIL import Image

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from tools.fetch_and_render import make_renderer, save_image  # noqa: E402
from ticker_controller.modes.score_alert import WIPE_IN, score_alert_duration  # noqa: E402

OUT_DIR = "previews/score_alerts"
FPS = 30


def espn_logo(sport: str, abbr: str) -> str:
    return f"https://a.espncdn.com/i/teamlogos/{sport}/500/{abbr.lower()}.png"


def alert(**kwargs) -> dict:
    base = {
        "id": "preview",
        "detail": "",
        "big": False,
        "points": 1,
        "status": "",
    }
    base.update(kwargs)
    return base


ALERTS = [
    ("mlb_grand_slam", alert(
        sport="mlb", kind="grand_slam", headline="GRAND SLAM", detail="JUDGE - 441 FT - 41ST HR",
        points=4, big=True, status="BOT 7",
        team_abbr="NYY", team_color="#132448", team_alt_color="#C4CED3",
        opp_abbr="BOS", home_abbr="NYY", away_abbr="BOS",
        home_score=9, away_score=3, team_logo=espn_logo("mlb", "nyy"),
    )),
    ("mlb_solo_hr", alert(
        sport="mlb", kind="solo_hr", headline="SOLO HOME RUN", detail="SOTO - 397 FT - 12TH HR",
        points=1, status="TOP 4",
        team_abbr="NYY", team_color="#132448", team_alt_color="#C4CED3",
        opp_abbr="TOR", home_abbr="TOR", away_abbr="NYY",
        home_score=2, away_score=3, team_logo=espn_logo("mlb", "nyy"),
    )),
    ("nfl_rushing_td", alert(
        sport="nfl", kind="rushing_td", headline="RUSHING TD", detail="BARKLEY",
        points=6, status="Q3 8:42",
        team_abbr="NYG", team_color="#0B2265", team_alt_color="#A71930",
        opp_abbr="DAL", home_abbr="NYG", away_abbr="DAL",
        home_score=17, away_score=14, team_logo=espn_logo("nfl", "nyg"),
    )),
    ("nfl_pick_six", alert(
        sport="nfl", kind="pick_six", headline="PICK SIX", detail="RAMSEY",
        points=6, big=True, status="Q4 2:11",
        team_abbr="SF", team_color="#AA0000", team_alt_color="#B3995D",
        opp_abbr="SEA", home_abbr="SEA", away_abbr="SF",
        home_score=20, away_score=27, team_logo=espn_logo("nfl", "sf"),
    )),
    ("nhl_power_play", alert(
        sport="nhl", kind="power_play", headline="POWER PLAY GOAL", detail="PANARIN",
        points=1, status="P2 6:03",
        team_abbr="NYR", team_color="#0038A8", team_alt_color="#CE1126",
        opp_abbr="NJ", home_abbr="NYR", away_abbr="NJ",
        home_score=3, away_score=1, team_logo=espn_logo("nhl", "nyr"),
    )),
    ("nhl_hat_trick", alert(
        sport="nhl", kind="hat_trick", headline="HAT TRICK", detail="MATTHEWS",
        points=1, big=True, status="P3 11:47",
        team_abbr="TOR", team_color="#00205B", team_alt_color="#FFFFFF",
        opp_abbr="MTL", home_abbr="MTL", away_abbr="TOR",
        home_score=2, away_score=4, team_logo=espn_logo("nhl", "tor"),
    )),
    ("nba_three", alert(
        sport="nba", kind="three", headline="3-POINTER", detail="CURRY",
        points=3, status="Q4 3:19",
        team_abbr="GS", team_color="#1D428A", team_alt_color="#FFC72C",
        opp_abbr="LAL", home_abbr="GS", away_abbr="LAL",
        home_score=112, away_score=108, team_logo=espn_logo("nba", "gs"),
    )),
    # Longest headline in the vocabulary, with a long name under it — the case
    # that decides whether the layout needs a marquee.
    ("nhl_shorthanded", alert(
        sport="nhl", kind="shorthanded", headline="SHORTHANDED GOAL", detail="BERGERON",
        points=1, big=True, status="P1 14:22",
        team_abbr="BOS", team_color="#FFB81C", team_alt_color="#000000",
        opp_abbr="TB", home_abbr="TB", away_abbr="BOS",
        home_score=0, away_score=1, team_logo=espn_logo("nhl", "bos"),
    )),
    ("nfl_two_point", alert(
        sport="nfl", kind="two_point", headline="2-PT CONVERSION",
        points=2, status="Q4 0:38",
        team_abbr="PHI", team_color="#004C54", team_alt_color="#A5ACAF",
        opp_abbr="WSH", home_abbr="PHI", away_abbr="WSH",
        home_score=28, away_score=27, team_logo=espn_logo("nfl", "phi"),
    )),
    ("soccer_goal", alert(
        sport="soccer_epl", kind="goal", headline="GOAL", detail="SAKA",
        points=1, status="67'",
        team_abbr="ARS", team_color="#EF0107", team_alt_color="#063672",
        opp_abbr="MCI", home_abbr="ARS", away_abbr="MCI",
        home_score=2, away_score=1,
        team_logo="https://a.espncdn.com/i/teamlogos/soccer/500/359.png",
    )),
]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", default=OUT_DIR)
    parser.add_argument("--scale", type=int, default=3, help="GIF upscale factor")
    parser.add_argument("--no-gif", action="store_true")
    args = parser.parse_args()

    os.makedirs(args.out_dir, exist_ok=True)
    renderer = make_renderer("sports")

    for _, payload in ALERTS:
        renderer.download_and_process_logo(payload.get("team_logo"), (24, 24))

    for name, payload in ALERTS:
        still = renderer.draw_score_alert(payload, WIPE_IN + 1.0)
        save_image(still, os.path.join(args.out_dir, f"{name}.png"))

        if args.no_gif:
            continue
        duration = score_alert_duration(payload)
        frames = []
        for i in range(int(duration * FPS)):
            frame = renderer.draw_score_alert(payload, i / FPS)
            frames.append(frame.resize(
                (frame.width * args.scale, frame.height * args.scale),
                Image.Resampling.NEAREST,
            ))
        gif_path = os.path.join(args.out_dir, f"{name}.gif")
        frames[0].save(gif_path, save_all=True, append_images=frames[1:],
                       duration=int(1000 / FPS), loop=0)
        print(f"Saved {gif_path} ({len(frames)} frames)")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
