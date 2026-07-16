#!/usr/bin/env python3
"""Render all full-bleed sport views with real-looking game data and proper logos."""

import os
import sys

from PIL import Image

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from tools.fetch_and_render import make_renderer, render_pin, save_image, prefetch_logos
from tools.mock_data_helper import make_mock_game

OUT_DIR = "previews/fullbleed_debug"

# ESPN CDN logo URL builder
def espn_logo(sport, abbr):
    abbr = abbr.lower()
    return f"https://a.espncdn.com/i/teamlogos/{sport}/500/{abbr}.png"

# FotMob-style soccer logos (EPL IDs)
SOCCER_LOGOS = {
    "ARS": "https://a.espncdn.com/i/teamlogos/soccer/500/359.png",   # Arsenal
    "MCI": "https://a.espncdn.com/i/teamlogos/soccer/500/382.png",   # Man City
    "BRA": "https://a.espncdn.com/i/teamlogos/countries/500/bra.png",
    "GER": "https://a.espncdn.com/i/teamlogos/countries/500/ger.png",
}

MOCK_GAMES = [
    # NFL: Chiefs (bright red) vs Bills (royal blue) — AFC Championship rematch
    # Ball at BUF 22 (red zone), 3rd & 6, Q4 2-minute drill
    make_mock_game(
        sport="nfl", game_id=4012345,
        away="BUF", home="KC",
        away_score=24, home_score=27,
        status="Q4 - 1:47", state="in",
        situation={
            "down": "3rd", "togo": "6", "yardline": "BUF 22",
            "possession": "KC",
            "downDistanceText": "3rd & 6 at BUF 22",
            "redZone": True,
        }
    ) | {
        "home_color": "#E31837", "away_color": "#00338D",
        "home_logo": espn_logo("nfl", "kc"),
        "away_logo": espn_logo("nfl", "buf"),
    },

    # NHL: Detroit Red Wings (red) vs Toronto Maple Leafs (blue) — red vs blue ice
    # PP for Detroit, 3rd period
    make_mock_game(
        sport="nhl", game_id=2025001,
        away="TOR", home="DET",
        away_score=1, home_score=3,
        status="3rd - 10:15", state="in",
        situation={
            "strength": "PP",
            "pp_team": "DET",
            "shots_away": "18", "shots_home": "28",
        }
    ) | {
        "home_color": "#CE1126", "away_color": "#003E7E",
        "home_logo": espn_logo("nhl", "det"),
        "away_logo": espn_logo("nhl", "tor"),
    },

    # NBA: LA Lakers (purple) vs Boston Celtics (green) — classic rivalry
    # Q4 crunch time under 2 minutes
    make_mock_game(
        sport="nba", game_id=2210045,
        away="BOS", home="LAL",
        away_score=108, home_score=110,
        status="Q4 - 1:12", state="in",
        situation={}
    ) | {
        "home_color": "#552583", "away_color": "#007A33",
        "home_logo": espn_logo("nba", "lal"),
        "away_logo": espn_logo("nba", "bos"),
    },

    # MLB: Cardinals (red) vs Cubs (blue) — NL Central classic
    # Bottom 9th, bases loaded, full count, 2 outs
    make_mock_game(
        sport="mlb", game_id=712345,
        away="CHC", home="STL",
        away_score=4, home_score=5,
        status="BOT 9", state="in",
        situation={
            "outs": "2", "balls": "3", "strikes": "2",
            "baserunners": [1, 1, 1],
            "pitcher_name": "Helsley", "pitcher_era": "1.91",
            "pitcher_pitches": "14", "pitcher_last_pitch": "98mph Fastball",
            "batter_name": "Suzuki", "batter_avg": ".285",
            "batter_hits": "2", "batter_at_bats": "4",
        }
    ) | {
        "home_color": "#C41E3A", "away_color": "#0E3386",
        "home_logo": espn_logo("mlb", "stl"),
        "away_logo": espn_logo("mlb", "chc"),
    },

    # Soccer: 2014 WC Semi — Germany 7-1 Brazil (the Mineirazo)
    make_mock_game(
        sport="soccer_wc", game_id=45678,
        away="GER", home="BRA",
        away_score=7, home_score=1,
        status="FT", state="post",
        situation={
            "goal_events": [
                {"player": "MULLER",   "time": "11'", "is_home": False, "own_goal": False},
                {"player": "KLOSE",    "time": "23'", "is_home": False, "own_goal": False},
                {"player": "KROOS",    "time": "24'", "is_home": False, "own_goal": False},
                {"player": "KROOS",    "time": "26'", "is_home": False, "own_goal": False},
                {"player": "KHEDIRA",  "time": "29'", "is_home": False, "own_goal": False},
                {"player": "SCHURLE",  "time": "69'", "is_home": False, "own_goal": False},
                {"player": "SCHURLE",  "time": "79'", "is_home": False, "own_goal": False},
                {"player": "OSCAR",    "time": "90'", "is_home": True,  "own_goal": False},
            ],
            "red_cards": [],
        }
    ) | {
        "home_color": "#009C3B", "away_color": "#000000",
        "home_logo": SOCCER_LOGOS["BRA"],
        "away_logo": SOCCER_LOGOS["GER"],
    },
]


MOCK_NASCAR = {
    "id": "nascar_mock",
    "type": "racing",
    "sport": "nascar",
    "state": "in",
    "status": "LIVE",
    "is_shown": True,
    "away_abbr": "Coca-Cola 600",
    "home_abbr": "Race",
    "nascar": {
        "event_name": "Coca-Cola 600",
        "short_name": "Coca-Cola 600",
        "track_name": "Charlotte Motor Speedway",
        "session_type": "Race",
        "session_name": "Race",
        "lap": 142,
        "total_laps": 200,
        "laps_remaining": 58,
        "caution": False,
        "flag": "GREEN",
        "drivers": [
            {"pos": 1,  "name": "Kyle Larson",    "abbr": "LAR", "car": "5",  "team_logo": "https://cf.nascar.com/data/images/carbadges/1/5.png",  "livery_primary": "#F5A623", "livery_secondary": "#111111", "gap": "Leader",   "car_illustration": ""},
            {"pos": 2,  "name": "Ryan Blaney",    "abbr": "BLA", "car": "12", "team_logo": "https://cf.nascar.com/data/images/carbadges/1/12.png", "livery_primary": "#003EAC", "livery_secondary": "#111111", "gap": "+0.412s",  "car_illustration": ""},
            {"pos": 3,  "name": "Denny Hamlin",   "abbr": "HAM", "car": "11", "team_logo": "https://cf.nascar.com/data/images/carbadges/1/11.png", "livery_primary": "#CC0000", "livery_secondary": "#111111", "gap": "+1.087s",  "car_illustration": ""},
            {"pos": 4,  "name": "Chase Elliott",  "abbr": "ELL", "car": "9",  "team_logo": "https://cf.nascar.com/data/images/carbadges/1/9.png",  "livery_primary": "#F5A623", "livery_secondary": "#111111", "gap": "+1.934s",  "car_illustration": ""},
            {"pos": 5,  "name": "Joey Logano",    "abbr": "LOG", "car": "22", "team_logo": "https://cf.nascar.com/data/images/carbadges/1/22.png", "livery_primary": "#003EAC", "livery_secondary": "#111111", "gap": "+2.751s",  "car_illustration": ""},
            {"pos": 6,  "name": "Martin Truex Jr","abbr": "TRU", "car": "19", "team_logo": "https://cf.nascar.com/data/images/carbadges/1/19.png", "livery_primary": "#CC0000", "livery_secondary": "#111111", "gap": "+3.642s",  "car_illustration": ""},
            {"pos": 7,  "name": "Brad Keselowski","abbr": "KES", "car": "6",  "team_logo": "https://cf.nascar.com/data/images/carbadges/1/6.png",  "livery_primary": "#003EAC", "livery_secondary": "#111111", "gap": "+4.508s",  "car_illustration": ""},
            {"pos": 8,  "name": "Tyler Reddick",  "abbr": "RED", "car": "45", "team_logo": "https://cf.nascar.com/data/images/carbadges/1/45.png", "livery_primary": "#CC0000", "livery_secondary": "#111111", "gap": "+5.329s",  "car_illustration": ""},
        ],
    },
}


SCROLL_SOCCER = make_mock_game(
    sport="soccer_pl", game_id=99999,
    away="MCI", home="ARS",
    away_score=1, home_score=2,
    status="90+2'", state="in",
    situation={
        "red_cards": [
            {"player": "RODRI",   "time": "45+2'", "is_home": False},
            {"player": "WALKER",  "time": "71'",   "is_home": False},
            {"player": "GVARDIOL","time": "78'",   "is_home": False},
            {"player": "DOKU",    "time": "82'",   "is_home": False},
            {"player": "SILVA",   "time": "88'",   "is_home": False},
        ],
    }
) | {
    "home_color": "#EF0107", "away_color": "#6CABDD",
    "home_logo": SOCCER_LOGOS["ARS"],
    "away_logo": SOCCER_LOGOS["MCI"],
}


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    renderer = make_renderer("sports_full")

    # Pre-download all logos so they appear in the renders
    print("Prefetching logos...")
    prefetch_logos(renderer, MOCK_GAMES)
    print("Done. Rendering...")

    labels = ["nfl", "nhl", "nba", "mlb", "soccer"]
    for label, game in zip(labels, MOCK_GAMES):
        out_path = os.path.join(OUT_DIR, f"{label}.png")
        try:
            frame = render_pin(renderer, game)
            save_image(frame, out_path)
        except Exception as exc:
            print(f"  ERROR rendering {label}: {exc}")
            import traceback; traceback.print_exc()

    # NASCAR full-bleed — render multiple frames to show the scrolling driver strip
    print("Prefetching NASCAR carbadges...")
    prefetch_logos(nascar_renderer := make_renderer("nascar"), [MOCK_NASCAR])
    nascar_gif_frames = []
    nascar_gif_path = os.path.join(OUT_DIR, "nascar_full.gif")
    try:
        for _ in range(60):
            frame = render_pin(nascar_renderer, MOCK_NASCAR)
            upscaled = frame.resize((frame.width * 4, frame.height * 4), Image.Resampling.NEAREST)
            nascar_gif_frames.append(upscaled)
        nascar_gif_frames[0].save(
            nascar_gif_path,
            save_all=True,
            append_images=nascar_gif_frames[1:],
            duration=50,
            loop=0,
        )
        print(f"Saved {nascar_gif_path} ({len(nascar_gif_frames)} frames)")
        # Also save a static snapshot
        save_image(render_pin(nascar_renderer, MOCK_NASCAR), os.path.join(OUT_DIR, "nascar.png"))
    except Exception as exc:
        print(f"  ERROR rendering NASCAR: {exc}")
        import traceback; traceback.print_exc()

    # Scroll card test
    from ticker_controller.stadium import StadiumRenderer
    scroll_renderer = StadiumRenderer(logo_cache=renderer.logo_cache)
    prefetch_logos(renderer, [SCROLL_SOCCER])
    try:
        scroll_img, _ = scroll_renderer.render(SCROLL_SOCCER)
        save_image(scroll_img.convert("RGB"), os.path.join(OUT_DIR, "soccer_scroll.png"))
    except Exception as exc:
        print(f"  ERROR rendering scroll: {exc}")
        import traceback; traceback.print_exc()


if __name__ == "__main__":
    main()
