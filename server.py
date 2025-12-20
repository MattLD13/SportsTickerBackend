import time
import threading
import json
import os
import re
from datetime import datetime as dt, timezone, timedelta
import requests
from flask import Flask, jsonify, request

# ================= CONFIGURATION =================
TIMEZONE_OFFSET = -5  # EST/EDT
CONFIG_FILE = "ticker_config.json"
UPDATE_INTERVAL = 15

# Thread lock
data_lock = threading.Lock()

# --- LOGO OVERRIDES ---
LOGO_OVERRIDES = {
    # NHL
    "NHL:SJS": "https://a.espncdn.com/i/teamlogos/nhl/500/sj.png",
    "NHL:NJD": "https://a.espncdn.com/i/teamlogos/nhl/500/nj.png",
    "NHL:TBL": "https://a.espncdn.com/i/teamlogos/nhl/500/tb.png",
    "NHL:LAK": "https://a.espncdn.com/i/teamlogos/nhl/500/la.png",
    "NHL:VGK": "https://a.espncdn.com/i/teamlogos/nhl/500/vgs.png",
    "NHL:VEG": "https://a.espncdn.com/i/teamlogos/nhl/500/vgs.png",
    "NHL:UTA": "https://a.espncdn.com/i/teamlogos/nhl/500/utah.png",
    "NHL:WSH": "https://a.espncdn.com/guid/cbe677ee-361e-91b4-5cae-6c4c30044743/logos/secondary_logo_on_black_color.png",
    "NHL:WAS": "https://a.espncdn.com/guid/cbe677ee-361e-91b4-5cae-6c4c30044743/logos/secondary_logo_on_black_color.png",

    # NFL
    "NFL:WSH": "https://a.espncdn.com/i/teamlogos/nfl/500/wsh.png",
    "NFL:WAS": "https://a.espncdn.com/i/teamlogos/nfl/500/wsh.png",
    "NFL:HOU": "https://a.espncdn.com/i/teamlogos/nfl/500/hou.png",
    "NFL:IND": "https://a.espncdn.com/i/teamlogos/nfl/500/ind.png",

    # NCAA FBS
    "NCF_FBS:CAL": "https://a.espncdn.com/i/teamlogos/ncaa/500/25.png",
    "NCF_FBS:OSU": "https://a.espncdn.com/i/teamlogos/ncaa/500/194.png",
    "NCF_FBS:ORST": "https://a.espncdn.com/i/teamlogos/ncaa/500/204.png",
    "NCF_FBS:MIA": "https://a.espncdn.com/i/teamlogos/ncaa/500/2390.png",
    "NCF_FBS:MIAMI": "https://a.espncdn.com/i/teamlogos/ncaa/500/2390.png",
    "NCF_FBS:HOU": "https://a.espncdn.com/i/teamlogos/ncaa/500/248.png",
    "NCF_FBS:IND": "https://a.espncdn.com/i/teamlogos/ncaa/500/84.png",

    # NCAA FCS
    "NCF_FCS:LIN": "https://a.espncdn.com/i/teamlogos/ncaa/500/2815.png",
    "NCF_FCS:LEH": "https://a.espncdn.com/i/teamlogos/ncaa/500/2329.png"
}

# ================= DEFAULT STATE =================
default_state = {
    'active_sports': { 'nfl': True, 'ncf_fbs': True, 'ncf_fcs': True },
    'mode': 'all',
    'scroll_seamless': False,
    'my_teams': [],
    'current_games': [],
    'all_teams_data': {},
    'debug_mode': False,
    'custom_date': None,
    'brightness': 0.5,
    'inverted': False,
    'panel_count': 2,
    'test_pattern': False,
    'reboot_requested': False,
    'weather_location': "New York"
}

state = default_state.copy()

# Load config
if os.path.exists(CONFIG_FILE):
    try:
        with open(CONFIG_FILE, 'r') as f:
            loaded = json.load(f)
            for k, v in loaded.items():
                if k in state:
                    if isinstance(state[k], dict) and isinstance(v, dict):
                        state[k].update(v)
                    else:
                        state[k] = v
        state['test_pattern'] = False
        state['reboot_requested'] = False
    except: pass

def save_config_file():
    try:
        with data_lock:
            export_data = {
                'active_sports': state['active_sports'],
                'mode': state['mode'],
                'scroll_seamless': state['scroll_seamless'],
                'my_teams': state['my_teams'],
                'brightness': state['brightness'],
                'inverted': state['inverted'],
                'panel_count': state['panel_count'],
                'weather_location': state['weather_location']
            }
        with open(CONFIG_FILE, 'w') as f:
            json.dump(export_data, f)
    except Exception as e:
        print(f"Save Config Error: {e}")

# ================= WEATHER FETCHER =================
class WeatherFetcher:
    def __init__(self, initial_loc):
        self.lat = 40.7128
        self.lon = -74.0060
        self.location_name = "New York"
        self.last_fetch = 0
        self.cache = None

    def get_weather(self):
        # minimal dummy for now
        return {
            "sport": "weather",
            "id": "weather_widget",
            "status": "Live",
            "home_abbr": "70°",
            "away_abbr": self.location_name,
            "is_shown": True
        }

# ================= SPORTS FETCHER =================
class SportsFetcher:
    def __init__(self):
        self.weather = WeatherFetcher("New York")
        self.base_url = "http://site.api.espn.com/apis/site/v2/sports/"
        self.leagues = {
            "nfl": {"path": "football/nfl", "team_params": {"limit": 100}},
            "ncf_fbs": {"path": "football/college-football", "team_params": {"groups": "80", "limit": 1000}},
            "ncf_fcs": {"path": "football/college-football", "team_params": {"groups": "81", "limit": 1000}}
        }

    def get_corrected_logo(self, league, abbr, default_logo):
        key = f"{league.upper()}:{abbr}"
        return LOGO_OVERRIDES.get(key, default_logo)

    def fetch_all_teams(self):
        catalog = {k: [] for k in self.leagues.keys()}
        for league, cfg in self.leagues.items():
            try:
                url = f"{self.base_url}{cfg['path']}/teams"
                r = requests.get(url, params=cfg['team_params'], timeout=10)
                data = r.json()
                if "sports" not in data: continue
                for sport in data['sports']:
                    for league_data in sport.get("leagues", []):
                        if cfg['team_params'].get("groups") and str(league_data.get("groupId")) != str(cfg['team_params']['groups']):
                            continue
                        for item in league_data.get("teams", []):
                            team = item.get("team", {})
                            abbr = team.get("abbreviation", "UNK")
                            logo = team.get("logos", [{}])[0].get("href", "")
                            logo = self.get_corrected_logo(league, abbr, logo)
                            catalog[league].append({"abbr": abbr, "logo": logo})
            except Exception as e:
                print(f"Error fetching {league}: {e}")
        with data_lock:
            state["all_teams_data"] = catalog

    def get_real_games(self):
        # minimal dummy for now
        games = []
        with data_lock:
            if state['active_sports'].get("ncf_fbs", False):
                for t in state["all_teams_data"].get("ncf_fbs", []):
                    games.append({"sport": "ncf_fbs", "id": t["abbr"], "home_abbr": t["abbr"], "away_abbr": "VS", "home_logo": t["logo"], "away_logo": ""})
            if state['active_sports'].get("ncf_fcs", False):
                for t in state["all_teams_data"].get("ncf_fcs", []):
                    games.append({"sport": "ncf_fcs", "id": t["abbr"], "home_abbr": t["abbr"], "away_abbr": "VS", "home_logo": t["logo"], "away_logo": ""})
        with data_lock:
            state["current_games"] = games

fetcher = SportsFetcher()

def background_updater():
    fetcher.fetch_all_teams()
    while True:
        fetcher.get_real_games()
        time.sleep(UPDATE_INTERVAL)

# ================= FLASK SERVER =================
app = Flask(__name__)

@app.route('/')
def dashboard(): return "Ticker Server is Running"

@app.route('/api/teams')
def get_teams():
    with data_lock:
        return jsonify(state["all_teams_data"])

@app.route('/api/ticker')
def get_ticker_data():
    with data_lock:
        return jsonify({"games": state["current_games"]})

@app.route('/api/state')
def get_full_state():
    with data_lock:
        return jsonify(state)

# ================= MAIN =================
if __name__ == "__main__":
    t = threading.Thread(target=background_updater)
    t.daemon = True
    t.start()
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
