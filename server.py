import time
import threading
import json
import os
import subprocess 
from datetime import datetime as dt, timezone, timedelta
import requests
from flask import Flask, jsonify, request

# ================= CONFIGURATION =================
TIMEZONE_OFFSET = -5  # Set to -5 for EST/EDT
CONFIG_FILE = "ticker_config.json"
UPDATE_INTERVAL = 15

# Thread Lock for safety
data_lock = threading.Lock()

# --- LOAD VALID TEAMS ---
try:
    from valid_teams import FBS_TEAMS, FCS_TEAMS
except ImportError:
    print("Warning: valid_teams.py not found. Sorting will fail.")
    FBS_TEAMS = []
    FCS_TEAMS = []

# --- LOGO OVERRIDES (Server-Side) ---
LOGO_OVERRIDES = {
    "SJS": "https://a.espncdn.com/i/teamlogos/nhl/500/sj.png",
    "SJ":  "https://a.espncdn.com/i/teamlogos/nhl/500/sj.png",
    "NJD": "https://a.espncdn.com/i/teamlogos/nhl/500/nj.png",
    "NJ":  "https://a.espncdn.com/i/teamlogos/nhl/500/nj.png",
    "TBL": "https://a.espncdn.com/i/teamlogos/nhl/500/tb.png",
    "TB":  "https://a.espncdn.com/i/teamlogos/nhl/500/tb.png",
    "LAK": "https://a.espncdn.com/i/teamlogos/nhl/500/la.png",
    "LA":  "https://a.espncdn.com/i/teamlogos/nhl/500/la.png",
    "VGK": "https://a.espncdn.com/i/teamlogos/nhl/500/vgs.png", 
    "VEG": "https://a.espncdn.com/i/teamlogos/nhl/500/vgs.png",
    "VGS": "https://a.espncdn.com/i/teamlogos/nhl/500/vgs.png",
    "UTA": "https://a.espncdn.com/i/teamlogos/nhl/500/utah.png",
    "UT":  "https://a.espncdn.com/i/teamlogos/nhl/500/utah.png",
    "WSH": "https://a.espncdn.com/guid/cbe677ee-361e-91b4-5cae-6c4c30044743/logos/secondary_logo_on_black_color.png",
    "WAS": "https://a.espncdn.com/guid/cbe677ee-361e-91b4-5cae-6c4c30044743/logos/secondary_logo_on_black_color.png",
    "CAL": "https://a.espncdn.com/i/teamlogos/ncaa/500/25.png",
    "OSU": "https://a.espncdn.com/i/teamlogos/ncaa/500/194.png",
    "ORST": "https://a.espncdn.com/i/teamlogos/ncaa/500/204.png",
    "LIN": "https://a.espncdn.com/i/teamlogos/ncaa/500/2815.png",
    "LEH": "https://a.espncdn.com/i/teamlogos/ncaa/500/2329.png",
    "IND": "https://a.espncdn.com/i/teamlogos/ncaa/500/84.png",
    "HOU": "https://a.espncdn.com/i/teamlogos/ncaa/500/248.png",
    "MIA": "https://a.espncdn.com/i/teamlogos/ncaa/500/2390.png",
    "MIAMI": "https://a.espncdn.com/i/teamlogos/ncaa/500/2390.png"
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
                    if isinstance(state[k], dict) and isinstance(v, dict): state[k].update(v)
                    else: state[k] = v
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
    except Exception as e: print(f"Save Config Error: {e}")

class WeatherFetcher:
    def __init__(self):
        self.lat = 40.7128; self.lon = -74.0060; self.location_name = "New York"
        self.last_fetch = 0; self.cache = None
    
    def update_coords(self, location_query):
        try:
            url = f"https://geocoding-api.open-meteo.com/v1/search?name={location_query}&count=1&language=en&format=json"
            r = requests.get(url, timeout=5)
            data = r.json()
            if 'results' in data and len(data['results']) > 0:
                res = data['results'][0]
                self.lat = res['latitude']; self.lon = res['longitude']; self.location_name = res['name']; self.last_fetch = 0 
        except: pass

    def get_icon(self, code, is_day=1):
        if code in [0, 1]: return "sun" if is_day else "moon"
        elif code in [2]: return "partly_cloudy"
        elif code in [3]: return "cloud"
        elif code in [45, 48]: return "fog"
        elif code in [51, 53, 55, 61, 63, 65, 80, 81, 82]: return "rain"
        elif code in [71, 73, 75, 77, 85, 86]: return "snow"
        elif code in [95, 96, 99]: return "storm"
        return "cloud"

    def get_weather(self):
        if time.time() - self.last_fetch < 900 and self.cache: return self.cache
        try:
            url = f"https://api.open-meteo.com/v1/forecast?latitude={self.lat}&longitude={self.lon}&current=temperature_2m,weather_code,is_day&daily=weather_code,temperature_2m_max,temperature_2m_min,uv_index_max&temperature_unit=fahrenheit&timezone=auto"
            r = requests.get(url, timeout=5); data = r.json()
            curr = data.get('current', {}); daily = data.get('daily', {})
            cur_temp = int(curr.get('temperature_2m', 0)); cur_code = curr.get('weather_code', 0); is_day = curr.get('is_day', 1)
            forecast = []
            days = daily.get('time', []); codes = daily.get('weather_code', []); maxs = daily.get('temperature_2m_max', []); mins = daily.get('temperature_2m_min', [])
            for i in range(1, 4):
                if i < len(days):
                    dt_obj = dt.strptime(days[i], "%Y-%m-%d")
                    forecast.append({ "day": dt_obj.strftime("%a").upper(), "high": int(maxs[i]), "low": int(mins[i]), "icon": self.get_icon(codes[i], 1) })
            weather_obj = {
                "sport": "weather", "id": "weather_widget", "status": "Live", "home_abbr": f"{cur_temp}°", "away_abbr": self.location_name, "is_shown": True,
                "situation": { "icon": self.get_icon(cur_code, is_day), "is_day": is_day, "stats": { "high": int(daily['temperature_2m_max'][0]), "low": int(daily['temperature_2m_min'][0]), "uv": float(daily['uv_index_max'][0]), "aqi": "MOD" }, "forecast": forecast }
            }
            self.cache = weather_obj; self.last_fetch = time.time(); return weather_obj
        except: return None

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

    def fetch_all_teams(self):
        # Fetch all teams once and SORT them strictly using valid_teams.py
        try:
            teams_catalog = {k: [] for k in self.leagues.keys()}
            
            # 1. Pro Sports (Simple Fetch)
            for league_key in ['nfl', 'mlb', 'nhl', 'nba']:
                self._fetch_simple_league(league_key, teams_catalog)

            # 2. College Football (Strict Sort)
            url = f"{self.base_url}football/college-football/teams"
            r = requests.get(url, params={'limit': 1000}, timeout=10)
            data = r.json()
            if 'sports' in data:
                for sport in data['sports']:
                    for league in sport['leagues']:
                        for item in league.get('teams', []):
                            t_abbr = item['team'].get('abbreviation', 'unk')
                            logos = item['team'].get('logos', [])
                            t_logo = logos[0].get('href', '') if len(logos) > 0 else ''
                            if t_abbr in LOGO_OVERRIDES: t_logo = LOGO_OVERRIDES[t_abbr]

                            team_obj = {'abbr': t_abbr, 'logo': t_logo}
                            
                            # STRICT SORTING LOGIC
                            if t_abbr in FBS_TEAMS:
                                teams_catalog['ncf_fbs'].append(team_obj)
                            elif t_abbr in FCS_TEAMS:
                                teams_catalog['ncf_fcs'].append(team_obj)
                            # Teams not in either list are ignored
            
            with data_lock:
                state['all_teams_data'] = teams_catalog
        except Exception as e: print(f"Team Fetch Error: {e}")

    def _fetch_simple_league(self, league_key, catalog):
        config = self.leagues[league_key]
        try:
            r = requests.get(f"{self.base_url}{config['path']}/teams", params=config['team_params'], timeout=10)
            data = r.json()
            if 'sports' in data:
                for sport in data['sports']:
                    for league in sport['leagues']:
                        for item in league.get('teams', []):
                            abbr = item['team'].get('abbreviation', 'unk')
                            logo = item['team'].get('logos', [{}])[0].get('href', '')
                            if abbr in LOGO_OVERRIDES: logo = LOGO_OVERRIDES[abbr]
                            catalog[league_key].append({'abbr': abbr, 'logo': logo})
        except: pass

    def get_real_games(self):
        games = []
        with data_lock: local_config = state.copy()

        # CLOCK & WEATHER
        if local_config['active_sports'].get('clock', False):
            games.append({'sport': 'clock', 'id': 'clock_widget', 'is_shown': True})
            with data_lock: state['current_games'] = games; return
        if local_config['active_sports'].get('weather', False):
            if local_config['weather_location'] != self.last_weather_loc:
                self.weather.update_coords(local_config['weather_location'])
                self.last_weather_loc = local_config['weather_location']
            w_obj = self.weather.get_weather()
            if w_obj: games.append(w_obj)
            with data_lock: state['current_games'] = games; return
        
        # SPORTS
        req_params = {}
        if local_config['debug_mode'] and local_config['custom_date']:
            target_date_str = local_config['custom_date']
            req_params['dates'] = target_date_str.replace('-', '')
        else:
            target_date_str = (dt.now(timezone.utc) + timedelta(hours=TIMEZONE_OFFSET)).strftime("%Y-%m-%d")
        
        for league_key, config in self.leagues.items():
            if not local_config['active_sports'].get(league_key, False): continue
            
            # NHL Native
            if league_key == 'nhl':
                self._fetch_nhl_native(games, target_date_str); continue

            try:
                current_params = config['scoreboard_params'].copy()
                current_params.update(req_params)
                r = requests.get(f"{self.base_url}{config['path']}/scoreboard", params=current_params, timeout=3)
                data = r.json()
                
                for event in data.get('events', []):
                    utc_str = event['date'].replace('Z', '')
                    game_date_str = (dt.fromisoformat(utc_str).replace(tzinfo=timezone.utc) + timedelta(hours=TIMEZONE_OFFSET)).strftime("%Y-%m-%d")
                    status_state = event.get('status', {}).get('type', {}).get('state', 'pre')
                    
                    keep_date = (status_state == 'in') or (game_date_str == target_date_str)
                    if league_key == 'mlb' and not keep_date: continue
                    if not keep_date: continue

                    comp = event['competitions'][0]; home = comp['competitors'][0]; away = comp['competitors'][1]
                    home_abbr = home['team']['abbreviation']; away_abbr = away['team']['abbreviation']
                    
                    # STRICT FILTER FOR COLLEGE GAMES
                    # If this is a college league, only show it if the teams match the lists
                    if league_key == 'ncf_fbs':
                        if home_abbr not in FBS_TEAMS and away_abbr not in FBS_TEAMS: continue
                    elif league_key == 'ncf_fcs':
                        if home_abbr not in FCS_TEAMS and away_abbr not in FCS_TEAMS: continue

                    is_shown = True
                    if local_config['mode'] == 'live' and status_state not in ['in', 'half']: is_shown = False
                    elif local_config['mode'] == 'my_teams':
                        h_key = f"{league_key}:{home_abbr}"; a_key = f"{league_key}:{away_abbr}"
                        if h_key not in local_config['my_teams'] and home_abbr not in local_config['my_teams'] and \
                           a_key not in local_config['my_teams'] and away_abbr not in local_config['my_teams']: is_shown = False
                    
                    # Logic for Display
                    status_disp = event['status']['type']['shortDetail'].replace("Final", "FINAL").replace("/OT", "")
                    if " - " in status_disp: status_disp = status_disp.split(" - ")[-1]
                    
                    # Situation
                    sit = comp.get('situation', {})
                    game_obj = {
                        'sport': league_key, 'id': event['id'], 'status': status_disp, 'state': status_state, 'is_shown': is_shown, 
                        'home_abbr': home_abbr, 'home_score': home.get('score', '0'), 'home_logo': home['team'].get('logo', ''),
                        'away_abbr': away_abbr, 'away_score': away.get('score', '0'), 'away_logo': away['team'].get('logo', ''),
                        'situation': {}
                    }
                    if status_state == 'in' and 'football' in config['path']:
                        game_obj['situation'] = { 'possession': sit.get('possession', ''), 'downDist': sit.get('downDistanceText', ''), 'isRedZone': sit.get('isRedZone', False) }
                    
                    games.append(game_obj)
            except Exception as e: print(f"Err {league_key}: {e}")

        with data_lock: state['current_games'] = games

    def _fetch_nhl_native(self, games_list, target_date_str):
        # (NHL Code Omitted for brevity, identical to previous)
        pass

fetcher = SportsFetcher()
def background_updater():
    fetcher.fetch_all_teams()
    while True: fetcher.get_real_games(); time.sleep(UPDATE_INTERVAL)

app = Flask(__name__)
@app.route('/')
def dashboard(): return "Ticker Server Running"
@app.route('/api/ticker')
def get_ticker():
    with data_lock: v_games = [g for g in state['current_games'] if g.get('is_shown', True)]
    return jsonify({'meta': {'time': dt.now(timezone.utc).strftime("%I:%M %p"), 'count': len(v_games)}, 'games': v_games})
@app.route('/api/teams')
def get_teams(): 
    with data_lock: return jsonify(state['all_teams_data'])
# ... (rest of API endpoints same as before) ...

if __name__ == "__main__":
    t = threading.Thread(target=background_updater); t.daemon = True; t.start()
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 5000)))
