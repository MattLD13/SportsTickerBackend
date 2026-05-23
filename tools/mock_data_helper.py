#!/usr/bin/env python3
"""SportsTicker Mock Data Helper CLI.

A developer utility to inject high-fidelity mock scores, weather, stocks,
and flights directly into local cache files (game_cache.json, stock_cache.json)
for immediate rendering debug without live internet requirements.

Usage:
  python tools/mock_data_helper.py --mode all
  python tools/mock_data_helper.py --mode nfl --status "in" --home NYG --away PHI
  python tools/mock_data_helper.py --mode stocks
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone, timedelta

GAME_CACHE_FILE = "game_cache.json"
STOCK_CACHE_FILE = "stock_cache.json"

# Curated harmonious color fallbacks
SPORTS_COLORS = {
    "nfl": {"NYG": "#0B2265", "PHI": "#004C54", "DAL": "#003594", "NE": "#002244"},
    "nhl": {"NYR": "#0038A8", "NJD": "#CE1126", "BOS": "#FFB81C", "CHI": "#CF0A2C"},
    "mlb": {"NYY": "#0C2340", "BOS": "#BD3039", "LAD": "#005A9C", "SF": "#FD5A1E"},
    "nba": {"LAL": "#552583", "BOS": "#007A33", "GSW": "#1D428A", "CHI": "#CE1126"},
    "soccer": {"ARS": "#EF0107", "CHE": "#034694", "MUN": "#DA291C", "MCI": "#6CABDD"},
}

DEFAULT_LOGOS = {
    "NYG": "https://upload.wikimedia.org/wikipedia/commons/6/60/New_York_Giants_logo.svg",
    "PHI": "https://upload.wikimedia.org/wikipedia/commons/e/e6/Philadelphia_Eagles_logo.svg",
    "NYR": "https://upload.wikimedia.org/wikipedia/commons/a/ae/New_York_Rangers.svg",
    "NJD": "https://upload.wikimedia.org/wikipedia/commons/9/9f/New_Jersey_Devils_logo.svg",
    "NYY": "https://upload.wikimedia.org/wikipedia/commons/2/25/New_York_Yankees_logo.svg",
    "BOS": "https://upload.wikimedia.org/wikipedia/commons/d/d4/Boston_Red_Sox_logo.svg",
    "LAL": "https://upload.wikimedia.org/wikipedia/commons/3/3c/Los_Angeles_Lakers_logo.svg",
    "ARS": "https://upload.wikimedia.org/wikipedia/commons/b/b5/Arsenal_FC.svg",
    "MCI": "https://upload.wikimedia.org/wikipedia/commons/e/eb/Manchester_City_FC_badge.svg",
}


def make_mock_game(sport, game_id, away, home, away_score, home_score, status, state, situation=None):
    now_utc = datetime.now(timezone.utc)
    start_time = (now_utc - timedelta(hours=2)).isoformat() if state == "in" else (now_utc + timedelta(hours=3)).isoformat()
    
    home_logo = DEFAULT_LOGOS.get(home, "https://upload.wikimedia.org/wikipedia/commons/5/59/Empty.png")
    away_logo = DEFAULT_LOGOS.get(away, "https://upload.wikimedia.org/wikipedia/commons/5/59/Empty.png")
    
    colors = SPORTS_COLORS.get(sport, {})
    home_color = colors.get(home, "#222222")
    away_color = colors.get(away, "#333333")

    return {
        "type": "game",
        "sport": sport,
        "id": str(game_id),
        "status": status,
        "state": state,
        "away_abbr": away,
        "home_abbr": home,
        "away_score": str(away_score),
        "home_score": str(home_score),
        "away_logo": away_logo,
        "home_logo": home_logo,
        "away_color": away_color,
        "home_color": home_color,
        "startTimeUTC": start_time,
        "situation": situation or {},
        "is_shown": True
    }


def get_mock_payloads(mode, state_opt, away_abbr, home_abbr):
    games = []
    
    is_in_progress = state_opt == "in"
    
    # --- NFL MOCK ---
    if mode in ("nfl", "all"):
        sit = {"down": "3rd", "togo": "4", "yardline": "NYG 32", "possession": home_abbr or "NYG"} if is_in_progress else {}
        games.append(make_mock_game(
            sport="nfl",
            game_id=4012345,
            away=away_abbr or "PHI",
            home=home_abbr or "NYG",
            away_score=24 if is_in_progress else 0,
            home_score=20 if is_in_progress else 0,
            status="Q4 - 2:00" if is_in_progress else "8:15 PM",
            state="in" if is_in_progress else "pre",
            situation=sit
        ))
        
    # --- NHL MOCK ---
    if mode in ("nhl", "all"):
        sit = {"strength": "PP", "shots_away": "18", "shots_home": "24"} if is_in_progress else {}
        games.append(make_mock_game(
            sport="nhl",
            game_id=2025001,
            away=away_abbr or "NJD",
            home=home_abbr or "NYR",
            away_score=1 if is_in_progress else 0,
            home_score=3 if is_in_progress else 0,
            status="3rd - 10:15" if is_in_progress else "7:00 PM",
            state="in" if is_in_progress else "pre",
            situation=sit
        ))

    # --- MLB MOCK ---
    if mode in ("mlb", "all"):
        sit = {"outs": "2", "balls": "3", "strikes": "2", "baserunners": [1, 0, 1]} if is_in_progress else {}
        games.append(make_mock_game(
            sport="mlb",
            game_id=712345,
            away=away_abbr or "BOS",
            home=home_abbr or "NYY",
            away_score=4 if is_in_progress else 0,
            home_score=5 if is_in_progress else 0,
            status="BOT 9" if is_in_progress else "1:05 PM",
            state="in" if is_in_progress else "pre",
            situation=sit
        ))

    # --- NBA MOCK ---
    if mode in ("nba", "all"):
        sit = {"timeouts_away": "1", "timeouts_home": "2"} if is_in_progress else {}
        games.append(make_mock_game(
            sport="nba",
            game_id=2210045,
            away=away_abbr or "BOS",
            home=home_abbr or "LAL",
            away_score=102 if is_in_progress else 0,
            home_score=105 if is_in_progress else 0,
            status="Q4 - 0:12" if is_in_progress else "10:30 PM",
            state="in" if is_in_progress else "pre",
            situation=sit
        ))

    # --- SOCCER MOCK ---
    if mode in ("soccer", "all"):
        sit = {"stoppage_time": "3"} if is_in_progress else {}
        games.append(make_mock_game(
            sport="soccer_pl",
            game_id=45678,
            away=away_abbr or "MCI",
            home=home_abbr or "ARS",
            away_score=1 if is_in_progress else 0,
            home_score=2 if is_in_progress else 0,
            status="90+2'" if is_in_progress else "12:30 PM",
            state="in" if is_in_progress else "pre",
            situation=sit
        ))

    # --- GOLF MOCK ---
    if mode in ("golf", "all"):
        games.append({
            "type": "golf",
            "sport": "golf",
            "id": "golf_leaderboard",
            "status": "Round 3",
            "state": "in",
            "tourney_name": "PGA Championship",
            "is_shown": True,
            "home_abbr": "LEADERBOARD",
            "situation": {
                "leaders": [
                    {"name": "S. Scheffler", "score": "-14", "thru": "F", "pos": "1"},
                    {"name": "X. Schauffele", "score": "-12", "thru": "16", "pos": "2"},
                    {"name": "R. McIlroy", "score": "-10", "thru": "F", "pos": "3"},
                ]
            }
        })

    # --- WEATHER MOCK ---
    if mode in ("weather", "all"):
        games.append({
            "type": "weather",
            "sport": "weather",
            "id": "weather_main",
            "away_abbr": "NEW YORK",
            "home_abbr": "72",
            "situation": {
                "icon": "sun",
                "stats": {
                    "aqi": "34", "uv": "8.0", "feels": "74", "wind": "8", "humidity": "45"
                },
                "forecast": [
                    {"day": "TODAY", "icon": "sun", "high": 75, "low": 58},
                    {"day": "SUN", "icon": "cloud", "high": 70, "low": 60},
                    {"day": "MON", "icon": "rain", "high": 68, "low": 54},
                ]
            },
            "home_score": "72",
            "away_score": "0",
            "status": "Active",
            "is_shown": True
        })

    # --- FLIGHT VISITOR MOCK ---
    if mode in ("flights", "all"):
        games.append({
            "type": "flight_visitor",
            "sport": "flight_tracker",
            "id": "flight_visitor_main",
            "status": "EN ROUTE",
            "home_abbr": "UA123",
            "away_abbr": "EWR",
            "home_score": "450",  # speed mph
            "away_score": "35000", # altitude ft
            "situation": {
                "guest_name": "John Doe",
                "flight_number": "UA123",
                "origin": "SFO",
                "destination": "EWR",
                "aircraft_type": "B772",
                "lat": "40.5", "lon": "-75.2",
                "progress_percent": "85",
                "eta": "10:30 PM",
                "minutes_remaining": "25"
            },
            "is_shown": True
        })

    return games


def main():
    parser = argparse.ArgumentParser(description="Mock Ticker Data CLI Helper.")
    parser.add_argument(
        "--mode",
        choices=("nfl", "nhl", "mlb", "nba", "soccer", "golf", "weather", "flights", "stocks", "all"),
        default="all",
        help="Category or sport of mock scores to generate."
    )
    parser.add_argument("--status", choices=("pre", "in"), default="in", help="Match state (pre-match or in-progress).")
    parser.add_argument("--home", default="", help="Override Home team abbreviation.")
    parser.add_argument("--away", default="", help="Override Away team abbreviation.")
    parser.add_argument("--clean", action="store_true", help="Delete cache files instead of injecting.")
    args = parser.parse_args()

    # --- CLEAN PATH ---
    if args.clean:
        for file in (GAME_CACHE_FILE, STOCK_CACHE_FILE):
            if os.path.exists(file):
                os.remove(file)
                print(f"  [CLEANED] Deleted: {file}")
            else:
                print(f"  [CLEAN] {file} was already clean.")
        return 0

    # --- STOCKS PATH ---
    if args.mode == "stocks":
        stocks_payload = {
            "AAPL": {"price": "182.50", "change_amt": "+2.40", "change_pct": "+1.35%"},
            "MSFT": {"price": "415.60", "change_amt": "-1.20", "change_pct": "-0.29%"},
            "TSLA": {"price": "178.40", "change_amt": "+8.90", "change_pct": "+5.25%"},
            "NVDA": {"price": "950.10", "change_amt": "+24.50", "change_pct": "+2.65%"},
        }
        with open(STOCK_CACHE_FILE, "w") as f:
            json.dump(stocks_payload, f, indent=4)
        print(f"[SAVED] Injected mock stock prices to: {STOCK_CACHE_FILE}")
        return 0

    # --- SPORTS / WIDGETS PATH ---
    games = get_mock_payloads(args.mode, args.status, args.away, args.home)
    
    # Keep existing games if file exists and we are not overwriting everything
    existing_games = []
    if args.mode != "all" and os.path.exists(GAME_CACHE_FILE):
        try:
            with open(GAME_CACHE_FILE, "r") as f:
                existing_games = json.load(f)
                if not isinstance(existing_games, list):
                    existing_games = []
        except Exception:
            pass

    # Filter out games matching the injected sport to avoid duplicates
    sport_to_inject = args.mode if args.mode != "soccer" else "soccer_pl"
    filtered_existing = [
        g for g in existing_games
        if g.get("sport", "").lower() != sport_to_inject and g.get("type") != args.mode
    ]

    final_games = filtered_existing + games
    with open(GAME_CACHE_FILE, "w") as f:
        json.dump(final_games, f, indent=4)

    print(f"[SAVED] Successfully injected {len(games)} mock items to: {GAME_CACHE_FILE}")
    for g in games:
        desc = f"[{g['sport'].upper()}] {g.get('away_abbr', '')} @ {g.get('home_abbr', '')} ({g.get('status', '')})" if g.get('type') == 'game' else f"[{g['type'].upper()}] {g.get('away_abbr', '')}"
        print(f"  -> {desc}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
