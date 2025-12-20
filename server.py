import time
import threading
import json
import os
import subprocess 
import re
from datetime import datetime as dt, timezone, timedelta
import requests
from flask import Flask, jsonify, request

# ================= CONFIGURATION =================
TIMEZONE_OFFSET = -5  # Set to -5 for EST/EDT
CONFIG_FILE = "ticker_config.json"
UPDATE_INTERVAL = 15

# Thread Lock for safety
data_lock = threading.Lock()

# --- LOGO OVERRIDES (League-Specific) ---
LOGO_OVERRIDES = {
    # (your existing logo overrides)
}

# ================= DEFAULT STATE =================
default_state = {
    'active_sports': { 'nfl': True, 'ncf_fbs': True, 'ncf_fcs': True, 'mlb': True, 'nhl': True, 'nba': True, 'weather': False, 'clock': False },
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

class WeatherFetcher:
    def __init__(self):
        self.lat = 40.7128
        self.lon = -74.0060
        self.location_name = "New York"
        self.last_fetch = 0
        self.cache = None

    # (weather methods unchanged)

class SportsFetcher:
    def __init__(self):
        self.weather = WeatherFetcher()
        self.base_url = 'http://site.api.espn.com/apis/site/v2/sports/'
        self.leagues = {
            'nfl': { 'path': 'football/nfl', 'scoreboard_params': {}, 'team_params': {'limit': 100} },
            'ncf_fbs': { 'path': 'football/college-football', 'scoreboard_params': {'groups': '80', 'limit': 100}, 'team_params': {'limit': 1000} },
            'ncf_fcs': { 'path': 'football/college-football', 'scoreboard_params': {'groups': '81', 'limit': 100}, 'team_params': {'limit': 1000} },
            'mlb': { 'path': 'baseball/mlb', 'scoreboard_params': {}, 'team_params': {'limit': 100} },
            'nhl': { 'path': 'hockey/nhl', 'scoreboard_params': {}, 'team_params': {'limit': 100} },
            'nba': { 'path': 'basketball/nba', 'scoreboard_params': {}, 'team_params': {'limit': 100} }
        }
        self.last_weather_loc = ""

    def get_corrected_logo(self, league_key, abbr, default_logo):
        key = f"{league_key.upper()}:{abbr}"
        if key in LOGO_OVERRIDES:
            return LOGO_OVERRIDES[key]
        return default_logo

    def _get_college_team_sets(self):
        fbs_set = set()
        fcs_set = set()

        # Fetch FBS teams
        try:
            r = requests.get(f"{self.base_url}football/college-football/teams", params={'groups': '80', 'limit': 1000}, timeout=10)
            data = r.json()
            for sport in data.get('sports', []):
                for league in sport.get('leagues', []):
                    for item in league.get('teams', []):
                        abbr = item['team'].get('abbreviation', None)
                        if abbr:
                            fbs_set.add(abbr)
        except: pass

        # Fetch FCS teams
        try:
            r = requests.get(f"{self.base_url}football/college-football/teams", params={'groups': '81', 'limit': 1000}, timeout=10)
            data = r.json()
            for sport in data.get('sports', []):
                for league in sport.get('leagues', []):
                    for item in league.get('teams', []):
                        abbr = item['team'].get('abbreviation', None)
                        if abbr:
                            fcs_set.add(abbr)
        except: pass

        return fbs_set, fcs_set

    def fetch_all_teams(self):
        try:
            teams_catalog = {k: [] for k in self.leagues.keys()}
            for league_key in ['nfl', 'mlb', 'nhl', 'nba']:
                self._fetch_simple_league(league_key, teams_catalog)

            fbs_set, fcs_set = self._get_college_team_sets()

            try:
                r = requests.get(f"{self.base_url}football/college-football/teams", params={'limit': 1000}, timeout=10)
                data = r.json()
                if 'sports' in data:
                    for sport in data['sports']:
                        for league in sport['leagues']:
                            for item in league.get('teams', []):
                                try:
                                    t_abbr = item['team'].get('abbreviation', 'unk')
                                    logos = item['team'].get('logos', [])
                                    t_logo = logos[0].get('href', '') if logos else ''
                                    league_type = 'ncf_fcs' if t_abbr in fcs_set else 'ncf_fbs'
                                    t_logo = self.get_corrected_logo(league_type, t_abbr, t_logo)
                                    teams_catalog[league_type].append({'abbr': t_abbr, 'logo': t_logo})
                                except:
                                    continue
            except: pass

            with data_lock:
                state['all_teams_data'] = teams_catalog
        except Exception as e:
            print(e)

    # (the rest of SportsFetcher unchanged)

fetcher = SportsFetcher()

def background_updater():
    fetcher.fetch_all_teams()
    while True:
        fetcher.get_real_games()
        time.sleep(UPDATE_INTERVAL)
        with data_lock:
            if state.get('reboot_requested'): pass 

app = Flask(__name__)

# (Flask routes unchanged)

if __name__ == "__main__":
    t = threading.Thread(target=background_updater)
    t.daemon = True
    t.start()
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
