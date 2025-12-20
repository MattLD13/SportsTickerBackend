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
    # --- NHL FIXES ---
    "NHL:SJS": "https://a.espncdn.com/i/teamlogos/nhl/500/sj.png",
    "NHL:NJD": "https://a.espncdn.com/i/teamlogos/nhl/500/nj.png",
    "NHL:TBL": "https://a.espncdn.com/i/teamlogos/nhl/500/tb.png",
    "NHL:LAK": "https://a.espncdn.com/i/teamlogos/nhl/500/la.png",
    "NHL:VGK": "https://a.espncdn.com/i/teamlogos/nhl/500/vgs.png", 
    "NHL:VEG": "https://a.espncdn.com/i/teamlogos/nhl/500/vgs.png",
    "NHL:UTA": "https://a.espncdn.com/i/teamlogos/nhl/500/utah.png",
    "NHL:WSH": "https://a.espncdn.com/guid/cbe677ee-361e-91b4-5cae-6c4c30044743/logos/secondary_logo_on_black_color.png",
    "NHL:WAS": "https://a.espncdn.com/guid/cbe677ee-361e-91b4-5cae-6c4c30044743/logos/secondary_logo_on_black_color.png",
    # --- NFL FIXES ---
    "NFL:WSH": "https://a.espncdn.com/i/teamlogos/nfl/500/wsh.png",
    "NFL:WAS": "https://a.espncdn.com/i/teamlogos/nfl/500/wsh.png",
    # --- MLB FIXES ---
    "MLB:WSH": "https://a.espncdn.com/i/teamlogos/mlb/500/wsh.png",
    "MLB:WAS": "https://a.espncdn.com/i/teamlogos/mlb/500/wsh.png",
    # --- NBA FIXES ---
    "NBA:WSH": "https://a.espncdn.com/i/teamlogos/nba/500/was.png",
    "NBA:WAS": "https://a.espncdn.com/i/teamlogos/nba/500/was.png",
    "NBA:UTA": "https://a.espncdn.com/i/teamlogos/nba/500/utah.png",
    "NBA:NOP": "https://a.espncdn.com/i/teamlogos/nba/500/no.png",
    # --- NCAA FIXES handled dynamically ---
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

# Load Config Safely
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

    # Weather update_coords, get_icon, get_weather methods remain unchanged
    # ... (omitted here for brevity; they are exactly as in your original code)

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

    # ---------- NEW: Dynamic FBS/FCS team sets ----------
    def _get_college_team_sets(self):
        fbs_set = set()
        fcs_set = set()
        try:
            r = requests.get(f"{self.base_url}football/college-football/teams", params={'groups': '80', 'limit': 1000}, timeout=10)
            data = r.json()
            for sport in data.get('sports', []):
                for league in sport.get('leagues', []):
                    for item in league.get('teams', []):
                        abbr = item['team'].get('abbreviation', None)
                        if abbr: fbs_set.add(abbr)
        except: pass
        try:
            r = requests.get(f"{self.base_url}football/college-football/teams", params={'groups': '81', 'limit': 1000}, timeout=10)
            data = r.json()
            for sport in data.get('sports', []):
                for league in sport.get('leagues', []):
                    for item in league.get('teams', []):
                        abbr = item['team'].get('abbreviation', None)
                        if abbr: fcs_set.add(abbr)
        except: pass
        return fbs_set, fcs_set

    # ---------- FETCH ALL TEAMS ----------
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
                                except: continue
            except: pass

            with data_lock:
                state['all_teams_data'] = teams_catalog
        except Exception as e:
            print(e)

    # ---------- SIMPLE LEAGUE FETCH ----------
    def _fetch_simple_league(self, league_key, catalog):
        config = self.leagues[league_key]
        url = f"{self.base_url}{config['path']}/teams"
        try:
            r = requests.get(url, params=config['team_params'], timeout=10)
            data = r.json()
            if 'sports' in data:
                for sport in data['sports']:
                    for league in sport['leagues']:
                        for item in league.get('teams', []):
                            abbr = item['team'].get('abbreviation', 'unk')
                            logo = item['team'].get('logos', [{}])[0].get('href', '')
                            logo = self.get_corrected_logo(league_key, abbr, logo)
                            catalog[league_key].append({'abbr': abbr, 'logo': logo})
        except: pass

    # The rest of SportsFetcher (NHL, get_real_games, etc.) remains unchanged
    # ...

fetcher = SportsFetcher()

def background_updater():
    fetcher.fetch_all_teams()
    while True:
        fetcher.get_real_games()
        time.sleep(UPDATE_INTERVAL)
        with data_lock:
            if state.get('reboot_requested'): pass 

app = Flask(__name__)

@app.route('/')
def dashboard(): return "Ticker Server is Running"

@app.route('/api/ticker')
def get_ticker_data():
    with data_lock:
        local_state = state.copy()
    visible_games = [g for g in local_state['current_games'] if g.get('is_shown', True)]
    return jsonify({
        'meta': { 
            'time': dt.now(timezone.utc).strftime("%I:%M %p"), 
            'count': len(visible_games), 
            'speed': 0.02, 
            'scroll_seamless': local_state.get('scroll_seamless', False),
            'brightness': local_state.get('brightness', 0.5),
            'inverted': local_state.get('inverted', False),
            'panel_count': local_state.get('panel_count', 2),
            'test_pattern': local_state.get('test_pattern', False),
            'reboot_requested': local_state.get('reboot_requested', False)
        },
        'games': visible_games
    })

@app.route('/api/state')
def get_full_state():
    with data_lock:
        return jsonify({'settings': state, 'games': state['current_games']})

@app.route('/api/teams')
def get_teams():
    with data_lock:
        return jsonify(state['all_teams_data'])

@app.route('/api/config', methods=['POST'])
def update_config():
    d = request.json
    with data_lock:
        if 'mode' in d: state['mode'] = d['mode']
        if 'active_sports' in d: state['active_sports'] = d['active_sports']
        if 'scroll_seamless' in d: state['scroll_seamless'] = d['scroll_seamless']
        if 'my_teams' in d: state['my_teams'] = d['my_teams']
        if 'weather_location' in d: state['weather_location'] = d['weather_location']
    
    save_config_file()
    threading.Thread(target=fetcher.get_real_games).start()
    return jsonify({"status": "ok", "settings": state})

@app.route('/api/debug', methods=['POST'])
def set_debug():
    d = request.json
    with data_lock:
        if 'debug_mode' in d: state['debug_mode'] = d['debug_mode']
        if 'custom_date' in d: state['custom_date'] = d['custom_date']
    fetcher.get_real_games()
    return jsonify({"status": "ok"})

@app.route('/api/hardware', methods=['POST'])
def hardware_control():
    data = request.json
    action = data.get('action')

    if action == 'reboot':
        with data_lock: state['reboot_requested'] = True
        def clear_reboot():
            time.sleep(10)
            with data_lock: state['reboot_requested'] = False
        threading.Thread(target=clear_reboot).start()
        return jsonify({"status": "ok", "message": "Reboot command sent to Ticker"})

    if action == 'test_pattern':
        with data_lock: state['test_pattern'] = not state.get('test_pattern', False)
        return jsonify({"status": "ok", "test_pattern": state['test_pattern']})

    updated = False
    with data_lock:
        if 'brightness' in data: 
            state['brightness'] = float(data['brightness']); updated = True
        if 'inverted' in data: 
            state['inverted'] = bool(data['inverted']); updated = True
        if 'panel_count' in data: 
            state['panel_count'] = int(data['panel_count']); updated = True
        if 'weather_location' in data:
            state['weather_location'] = data['weather_location']; updated = True

    if updated: save_config_file()
    return jsonify({"status": "ok", "settings": state})

if __name__ == "__main__":
    t = threading.Thread(target=background_updater)
    t.daemon = True
    t.start()
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
