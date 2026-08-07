#!/usr/bin/env python3
"""Score alerts shown the way they actually happen: on top of a live ticker.

Builds a real scrolling sports strip with the controller's own renderer, runs
it, then slams the alert over it and hands the scroll back afterwards. This is
the sequence the hardware performs — the strip is frozen for the duration and
revealed again by the closing shutters, so the scroll never loses its place.

    python tools/render_score_alert_overlay.py
    python tools/render_score_alert_overlay.py --team blues --no-gif
"""

from __future__ import annotations

import argparse
import os
import sys

from PIL import Image

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from tools.fetch_and_render import make_renderer, prefetch_logos, render_scroll, save_image  # noqa: E402
from tools.mock_data_helper import make_mock_game  # noqa: E402
from ticker_controller.config import PANEL_W, PANEL_H  # noqa: E402
from ticker_controller.modes.score_alert import WIPE_IN, score_alert_duration  # noqa: E402

OUT_DIR = "previews/score_alert_overlay"
FPS = 25
PRE_ROLL = 1.3         # seconds of ordinary scrolling before the alert
POST_ROLL = 1.4        # and after it
SCROLL_PX = 1.3        # pixels per frame — matches a 0.03s scroll_sleep


def espn_logo(sport: str, abbr: str) -> str:
    return f"https://a.espncdn.com/i/teamlogos/{sport}/500/{abbr.lower()}.png"


# The slate the ticker is scrolling through when the alerts land. Deliberately
# mixed-league, because that is what the strip looks like on a real evening.
STRIP_GAMES = [
    make_mock_game(sport="nhl", game_id=1, away="NJ", home="NYR",
                   away_score=1, home_score=2, status="P2 6:03", state="in",
                   situation={}) | {
        "home_color": "#0038A8", "away_color": "#CE1126",
        "home_logo": espn_logo("nhl", "nyr"), "away_logo": espn_logo("nhl", "nj")},
    make_mock_game(sport="mlb", game_id=2, away="CHC", home="STL",
                   away_score=2, home_score=3, status="V6", state="in",
                   situation={"outs": "1", "balls": "2", "strikes": "1"}) | {
        "home_color": "#C41E3A", "away_color": "#0E3386",
        "home_logo": espn_logo("mlb", "stl"), "away_logo": espn_logo("mlb", "chc")},
    make_mock_game(sport="nfl", game_id=3, away="DAL", home="NYG",
                   away_score=14, home_score=10, status="Q3 8:42", state="in",
                   situation={"possession": "NYG", "downDist": "2nd & 4"}) | {
        "home_color": "#0B2265", "away_color": "#041E42",
        "home_logo": espn_logo("nfl", "nyg"), "away_logo": espn_logo("nfl", "dal")},
    make_mock_game(sport="nhl", game_id=4, away="CHI", home="STL",
                   away_score=1, home_score=3, status="P3 11:47", state="in",
                   situation={}) | {
        "home_color": "#002F87", "away_color": "#CF0A2C",
        "home_logo": espn_logo("nhl", "stl"), "away_logo": espn_logo("nhl", "chi")},
    make_mock_game(sport="nba", game_id=5, away="BOS", home="NYK",
                   away_score=98, home_score=101, status="Q4 5:12", state="in",
                   situation={}) | {
        "home_color": "#006BB6", "away_color": "#007A33",
        "home_logo": espn_logo("nba", "nyk"), "away_logo": espn_logo("nba", "bos")},
]


def alert(**kwargs) -> dict:
    base = {"id": "overlay", "detail": "", "big": False, "points": 1}
    base.update(kwargs)
    return base


ALERTS = {
    "rangers": alert(
        sport="nhl", kind="power_play", headline="POWER PLAY GOAL", detail="PANARIN",
        status="P2 6:03", team_abbr="NYR", team_color="#0038A8", team_alt_color="#CE1126",
        opp_abbr="NJ", home_abbr="NYR", away_abbr="NJ", home_score=3, away_score=1,
        team_logo=espn_logo("nhl", "nyr"),
    ),
    "giants": alert(
        sport="nfl", kind="rushing_td", headline="RUSHING TD", detail="BARKLEY",
        points=6, status="Q3 8:42", team_abbr="NYG", team_color="#0B2265",
        team_alt_color="#A71930", opp_abbr="DAL", home_abbr="NYG", away_abbr="DAL",
        home_score=17, away_score=14, team_logo=espn_logo("nfl", "nyg"),
    ),
    "cardinals": alert(
        sport="mlb", kind="three_run_hr", headline="3-RUN HOMER", detail="GOLDSCHMIDT",
        points=3, big=True, status="Bottom 6", team_abbr="STL", team_color="#C41E3A",
        team_alt_color="#0C2340", opp_abbr="CHC", home_abbr="STL", away_abbr="CHC",
        home_score=6, away_score=2, team_logo=espn_logo("mlb", "stl"),
    ),
    "blues": alert(
        sport="nhl", kind="hat_trick", headline="HAT TRICK", detail="KYROU",
        big=True, status="P3 11:47", team_abbr="STL", team_color="#002F87",
        team_alt_color="#FCB514", opp_abbr="CHI", home_abbr="STL", away_abbr="CHI",
        home_score=4, away_score=1, team_logo=espn_logo("nhl", "stl"),
    ),
}


def build_sequence(r, strip, payload, start_offset):
    """Frames for scroll → alert → scroll, as one continuous take."""
    span = max(1, strip.width - PANEL_W)
    frames = []

    def scroll_frame(offset):
        x = int(offset) % span
        return strip.crop((x, 0, x + PANEL_W, PANEL_H)).convert("RGB")

    offset = start_offset
    for _ in range(int(PRE_ROLL * FPS)):
        frames.append(scroll_frame(offset))
        offset += SCROLL_PX

    # The strip stops here and this exact frame is what the shutters open over.
    frozen = scroll_frame(offset)
    duration = score_alert_duration(payload)
    for i in range(int(duration * FPS)):
        frames.append(r.draw_score_alert(payload, i / FPS, frozen).convert("RGB"))

    for _ in range(int(POST_ROLL * FPS)):
        frames.append(scroll_frame(offset))
        offset += SCROLL_PX

    return frames


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", default=OUT_DIR)
    parser.add_argument("--team", default="", help="Render only one of: " + ", ".join(ALERTS))
    parser.add_argument("--scale", type=int, default=3)
    parser.add_argument("--no-gif", action="store_true")
    args = parser.parse_args()

    os.makedirs(args.out_dir, exist_ok=True)
    r = make_renderer("sports")
    prefetch_logos(r, STRIP_GAMES)
    for payload in ALERTS.values():
        for size in ((24, 24), (16, 16)):
            r.download_and_process_logo(payload["team_logo"], size)

    strip = render_scroll(r, STRIP_GAMES)
    print(f"Built scrolling strip: {strip.width}x{strip.height}")

    wanted = [args.team] if args.team else list(ALERTS)
    stills = []
    for name in wanted:
        payload = ALERTS[name]
        # Start each team at a different point in the slate so the ticker
        # underneath is not the same two cards every time.
        start = (list(ALERTS).index(name) * 137) % max(1, strip.width - PANEL_W)
        frames = build_sequence(r, strip, payload, start)

        # The moment worth looking at: shutters half open, ticker still visible
        # at both edges, headline mid-flip behind them.
        mid_wipe = int((PRE_ROLL + WIPE_IN * 0.55) * FPS)
        save_image(frames[mid_wipe], os.path.join(args.out_dir, f"{name}_wipe.png"))
        settled = int((PRE_ROLL + 1.6) * FPS)
        save_image(frames[settled], os.path.join(args.out_dir, f"{name}.png"))
        stills.extend([frames[mid_wipe], frames[settled]])

        if args.no_gif:
            continue
        scaled = [f.resize((PANEL_W * args.scale, PANEL_H * args.scale),
                           Image.Resampling.NEAREST) for f in frames]
        path = os.path.join(args.out_dir, f"{name}.gif")
        scaled[0].save(path, save_all=True, append_images=scaled[1:],
                       duration=int(1000 / FPS), loop=0)
        print(f"Saved {path} ({len(scaled)} frames)")

    s = args.scale
    sheet = Image.new("RGB", (PANEL_W * s, (PANEL_H * s + 8) * len(stills)), (18, 18, 20))
    for i, still in enumerate(stills):
        sheet.paste(still.resize((PANEL_W * s, PANEL_H * s), Image.Resampling.NEAREST),
                    (0, i * (PANEL_H * s + 8)))
    save_image(sheet, os.path.join(args.out_dir, "_overlay.png"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
