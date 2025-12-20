import time
import threading
import json
import os
import subprocess 
from datetime import datetime as dt, timezone, timedelta
import requests
from flask import Flask, jsonify, request

# ================= CONFIGURATION =================
TIMEZONE_OFFSET = -5 
CONFIG_FILE = "ticker_config.json"
UPDATE_INTERVAL = 8

try:
    from valid_teams import FBS_TEAMS, FCS_TEAMS
except ImportError:
    FBS_TEAMS = []
    FCS_TEAMS = []

# --- LOGO OVERRIDES ---
LOGO_OVERRIDES = {
    "SJS": "https://a.espncdn.com/i/teamlogos/nhl/500/sj.png",
    "NJD": "https://a.espncdn.com/i/teamlogos/nhl/500/nj.png",
    "TBL": "https://a.espncdn.com/i/teamlogos/nhl/500/tb.png",
    "LAK": "https://a.espncdn.com/i/teamlogos/nhl/500/la.png",
    "VGK": "https://a.espncdn.com/i/teamlogos/nhl/500/vgs.png", 
    "VEG": "https://a.espncdn.com/i/teamlogos/nhl/500/vgs.png",
    "WSH": "https://a.espncdn.com/guid/cbe677ee-361e-91b4-5cae-6c4c30044743/logos/secondary_logo_on_black_color.png",
    "WAS": "https://a.espncdn.com/guid/cbe677ee-361e-91b4-5cae-6c4c30044743/logos/secondary_logo_on_black_color.png",
    "UTA": "https://a.espncdn.com/i/teamlogos/nhl/500/utah.png",
    "CAL": "https://a.espncdn.com/i/teamlogos/ncaa/500/25.png",
    "OSU": "https://a.espncdn.com/i/teamlogos/ncaa/500/194.png",
    "ORST": "https://a.espncdn.com/i/teamlogos/ncaa/500/204.png",
    "LIN": "https://a.espncdn.com/i/teamlogos/ncaa/500/2815.png",
    "LEH": "https://a.espncdn.com/i/teamlogos/ncaa/500/2329.png"
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
            if 'active_sports' in loaded: state['active_sports'].update(loaded['active_sports'])
            if 'mode' in loaded: state['mode'] = loaded['mode']
            if 'scroll_seamless' in loaded: state['scroll_seamless'] = loaded['scroll_seamless']
            if 'my_teams' in loaded: state['my_teams'] = loaded['my_teams']
            if 'brightness' in loaded: state['brightness'] = loaded['brightness']
            if 'inverted' in loaded: state['inverted'] = loaded['inverted']
            if 'panel_count' in loaded: state['panel_count'] = loaded['panel_count']
            if 'weather_location' in loaded: state['weather_location'] = loaded['weather_location']
    except: pass

class WeatherFetcher:
    def __init__(self):
        self.lat = 40.7128 # Default NY
        self.lon = -74.0060
        self.location_name = "New York"
        self.last_fetch = 0
        self.cache = None

    def update_coords(self, location_query):
        try:
            url = f"https://geocoding-api.open-meteo.com/v1/search?name={location_query}&count=1&language=en&format=json"
            r = requests.get(url, timeout=5)
            data = r.json()
            if 'results' in data and len(data['results']) > 0:
                res = data['results'][0]
                self.lat = res['latitude']
                self.lon = res['longitude']
                self.location_name = res['name']
                self.last_fetch = 0 
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
            # Fetch Current + Daily Forecast + UV
            url = f"https://api.open-meteo.com/v1/forecast?latitude={self.lat}&longitude={self.lon}&current=temperature_2m,weather_code,is_day&daily=weather_code,temperature_2m_max,temperature_2m_min,uv_index_max&temperature_unit=fahrenheit&timezone=auto"
            r = requests.get(url, timeout=5)
            data = r.json()
            
            curr = data.get('current', {})
            daily = data.get('daily', {})
            
            # Current
            cur_temp = int(curr.get('temperature_2m', 0))
            cur_code = curr.get('weather_code', 0)
            is_day = curr.get('is_day', 1)
            cur_icon = self.get_icon(cur_code, is_day)
            
            # Today's High/Low/UV
            high = int(daily['temperature_2m_max'][0])
            low = int(daily['temperature_2m_min'][0])
            uv = float(daily['uv_index_max'][0])
            
            # Forecast (Next 3 Days)
            forecast = []
            days = daily.get('time', [])
            codes = daily.get('weather_code', [])
            maxs = daily.get('temperature_2m_max', [])
            mins = daily.get('temperature_2m_min', [])
            
            for i in range(1, 4): # Days 1, 2, 3
                if i < len(days):
                    dt_obj = dt.strptime(days[i], "%Y-%m-%d")
                    day_name = dt_obj.strftime("%a").upper()
                    f_icon = self.get_icon(codes[i], 1)
                    forecast.append({
                        "day": day_name,
                        "high": int(maxs[i]),
                        "low": int(mins[i]),
                        "icon": f_icon
                    })

            weather_obj = {
                "sport": "weather",
                "id": "weather_widget",
                "status": "Live",
                "home_abbr": f"{cur_temp}°",
                "away_abbr": self.location_name,
                "home_score": "", "away_score": "",
                "is_shown": True,
                "home_logo": "", "away_logo": "",
                "situation": {
                    "icon": cur_icon,
                    "is_day": is_day,
                    "stats": { "high": high, "low": low, "uv": uv, "aqi": "MOD" }, # Mocking AQI for simplicity
                    "forecast": forecast
                }
            }
            self.cache = weather_obj
            self.last_fetch = time.time()
            return weather_obj
        except Exception as e: 
            print(f"Weather Error: {e}")
            return None

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
        # ... (Same as before, trimmed for brevity)
        pass 

    def _fetch_simple_league(self, league_key, catalog):
        # ... (Same as before)
        pass

    def _fetch_nhl_native(self, games_list, target_date_str):
        # ... (Same as before)
        pass

    def _process_single_nhl_game(self, game_id, games_list, is_enabled):
        # ... (Same as before - make sure to keep the override logic)
        pass

    # ... (Keep all existing helper methods) ...

    def get_real_games(self):
        games = []
        
        # --- CLOCK MODE CHECK ---
        if state['active_sports'].get('clock', False):
            games.append({'sport': 'clock', 'id': 'clock_widget', 'is_shown': True})
            state['current_games'] = games
            return

        # --- WEATHER MODE CHECK ---
        if state['active_sports'].get('weather', False):
            if state['weather_location'] != self.last_weather_loc:
                self.weather.update_coords(state['weather_location'])
                self.last_weather_loc = state['weather_location']
            
            w_obj = self.weather.get_weather()
            if w_obj: games.append(w_obj)
            state['current_games'] = games
            return
        
        # --- SPORTS MODE (Standard) ---
        # ... (Keep existing sports logic) ...
        # For brevity in this response, I'm assuming you keep the sports fetching loop here.
        state['current_games'] = [] # Placeholder if sports logic isn't pasted, ensure you keep the loop!

fetcher = SportsFetcher()

# ... (Rest of Flask app code remains the same) ...
# Ensure you copy the FULL SportsFetcher logic from previous turn if replacing file completely.
# For the purpose of this request, I focused on the WeatherFetcher updates above.
# The main change is the `get_weather` method returning forecast data.

def background_updater():
    # fetcher.fetch_all_teams() 
    while True:
        fetcher.get_real_games()
        time.sleep(UPDATE_INTERVAL)
        if state.get('reboot_requested'):
             time.sleep(15)
             state['reboot_requested'] = False

app = Flask(__name__)

@app.route('/')
def dashboard(): return "Ticker Server is Running"

@app.route('/api/ticker')
def get_ticker_data():
    visible_games = [g for g in state['current_games'] if g.get('is_shown', True)]
    return jsonify({
        'meta': { 
            'time': dt.now(timezone.utc).strftime("%I:%M %p"), 
            'count': len(visible_games), 
            'speed': 0.02, 
            'scroll_seamless': state.get('scroll_seamless', False),
            'brightness': state.get('brightness', 0.5),
            'inverted': state.get('inverted', False),
            'panel_count': state.get('panel_count', 2),
            'test_pattern': state.get('test_pattern', False),
            'reboot_requested': state.get('reboot_requested', False)
        },
        'games': visible_games
    })

@app.route('/api/state')
def get_full_state(): return jsonify({'settings': state, 'games': state['current_games']})

@app.route('/api/teams')
def get_teams(): return jsonify(state['all_teams_data'])

@app.route('/api/config', methods=['POST'])
def update_config():
    d = request.json
    if 'mode' in d: state['mode'] = d['mode']
    if 'active_sports' in d: state['active_sports'] = d['active_sports']
    if 'scroll_seamless' in d: state['scroll_seamless'] = d['scroll_seamless']
    if 'my_teams' in d: state['my_teams'] = d['my_teams']
    
    try:
        with open(CONFIG_FILE, 'w') as f:
            json.dump({
                'active_sports': state['active_sports'], 
                'mode': state['mode'], 
                'scroll_seamless': state['scroll_seamless'], 
                'my_teams': state['my_teams'],
                'brightness': state['brightness'],
                'inverted': state['inverted'],
                'panel_count': state['panel_count'],
                'weather_location': state['weather_location']
            }, f)
    except: pass
    
    threading.Thread(target=fetcher.get_real_games).start()
    return jsonify({"status": "ok", "settings": state})

@app.route('/api/debug', methods=['POST'])
def set_debug():
    d = request.json
    if 'debug_mode' in d: state['debug_mode'] = d['debug_mode']
    if 'custom_date' in d: state['custom_date'] = d['custom_date']
    fetcher.get_real_games()
    return jsonify({"status": "ok"})

@app.route('/api/hardware', methods=['POST'])
def hardware_control():
    data = request.json
    action = data.get('action')

    if action == 'reboot':
        state['reboot_requested'] = True
        return jsonify({"status": "ok", "message": "Reboot command sent to Ticker"})

    if action == 'test_pattern':
        state['test_pattern'] = not state.get('test_pattern', False)
        return jsonify({"status": "ok", "test_pattern": state['test_pattern']})

    updated = False
    if 'brightness' in data: 
        state['brightness'] = float(data['brightness']); updated = True
    if 'inverted' in data: 
        state['inverted'] = bool(data['inverted']); updated = True
    if 'panel_count' in data: 
        state['panel_count'] = int(data['panel_count']); updated = True
    if 'weather_location' in data:
        state['weather_location'] = data['weather_location']; updated = True

    if updated:
        try:
            with open(CONFIG_FILE, 'w') as f:
                json.dump({
                    'active_sports': state['active_sports'], 
                    'mode': state['mode'], 
                    'scroll_seamless': state['scroll_seamless'], 
                    'my_teams': state['my_teams'],
                    'brightness': state['brightness'],
                    'inverted': state['inverted'],
                    'panel_count': state['panel_count'],
                    'weather_location': state['weather_location']
                }, f)
        except: pass

    return jsonify({"status": "ok", "settings": state})

if __name__ == "__main__":
    t = threading.Thread(target=background_updater)
    t.daemon = True
    t.start()
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
