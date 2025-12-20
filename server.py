import time
import threading
import json
import os
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

# --- LOAD VALID TEAMS (STRICT SORTING IMPROVEMENT) ---
# This checks if the file exists. If it does, it uses strict sorting.
# If not, it falls back to ESPN's default grouping.
try:
    from valid_teams import FBS_TEAMS, FCS_TEAMS
    VALID_TEAMS_LOADED = True
except ImportError:
    print("Warning: valid_teams.py not found. Strict sorting disabled.")
    VALID_TEAMS_LOADED = False
    FBS_TEAMS = []
    FCS_TEAMS = []

# --- LOGO OVERRIDES (League-Specific) ---
LOGO_OVERRIDES = {
    # --- NHL ---
    "NHL:SJS": "https://a.espncdn.com/i/teamlogos/nhl/500/sj.png",
    "NHL:NJD": "https://a.espncdn.com/i/teamlogos/nhl/500/nj.png",
    "NHL:TBL": "https://a.espncdn.com/i/teamlogos/nhl/500/tb.png",
    "NHL:LAK": "https://a.espncdn.com/i/teamlogos/nhl/500/la.png",
    "NHL:VGK": "https://a.espncdn.com/i/teamlogos/nhl/500/vgs.png", 
    "NHL:VEG": "https://a.espncdn.com/i/teamlogos/nhl/500/vgs.png",
    "NHL:UTA": "https://a.espncdn.com/i/teamlogos/nhl/500/utah.png",
    "NHL:WSH": "https://a.espncdn.com/guid/cbe677ee-361e-91b4-5cae-6c4c30044743/logos/secondary_logo_on_black_color.png",
    "NHL:WAS": "https://a.espncdn.com/guid/cbe677ee-361e-91b4-5cae-6c4c30044743/logos/secondary_logo_on_black_color.png",
    
    # --- NFL ---
    "NFL:WSH": "https://a.espncdn.com/i/teamlogos/nfl/500/wsh.png",
    "NFL:WAS": "https://a.espncdn.com/i/teamlogos/nfl/500/wsh.png",
    
    # --- MLB ---
    "MLB:WSH": "https://a.espncdn.com/i/teamlogos/mlb/500/wsh.png",
    "MLB:WAS": "https://a.espncdn.com/i/teamlogos/mlb/500/wsh.png",
    
    # --- NBA ---
    "NBA:WSH": "https://a.espncdn.com/i/teamlogos/nba/500/was.png",
    "NBA:WAS": "https://a.espncdn.com/i/teamlogos/nba/500/was.png",
    "NBA:UTA": "https://a.espncdn.com/i/teamlogos/nba/500/utah.png",
    "NBA:MIA": "https://a.espncdn.com/i/teamlogos/nba/500/mia.png",
    
    # --- NCAA FBS ---
    "NCF_FBS:CAL": "https://a.espncdn.com/i/teamlogos/ncaa/500/25.png",
    "NCF_FBS:OSU": "https://a.espncdn.com/i/teamlogos/ncaa/500/194.png",
    "NCF_FBS:ORST": "https://a.espncdn.com/i/teamlogos/ncaa/500/204.png",
    "NCF_FBS:MIA": "https://a.espncdn.com/i/teamlogos/ncaa/500/2390.png",
    "NCF_FBS:MIAMI": "https://a.espncdn.com/i/teamlogos/ncaa/500/2390.png",
    "NCF_FBS:HOU": "https://a.espncdn.com/i/teamlogos/ncaa/500/248.png",
    "NCF_FBS:IND": "https://a.espncdn.com/i/teamlogos/ncaa/500/84.png",
    
    # --- NCAA FCS ---
    "NCF_FCS:LIN": "https://a.espncdn.com/i/teamlogos/ncaa/500/2815.png",
    "NCF_FCS:LEH": "https://a.espncdn.com/i/teamlogos/ncaa/500/2329.png"
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
        # Ensure critical flags start False
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
    except: pass

class WeatherFetcher:
    def __init__(self, initial_loc):
        self.lat = 40.7128; self.lon = -74.0060; self.location_name = "New York"
        self.last_fetch = 0; self.cache = None
        if initial_loc: self.update_coords(initial_loc)

    def update_coords(self, location_query):
        clean_query = str(location_query).strip()
        if not clean_query: return
        # Zip
        if re.fullmatch(r'\d{5}', clean_query):
            try:
                r = requests.get(f"https://api.zippopotam.us/us/{clean_query}", timeout=5)
                if r.status_code == 200:
                    d = r.json(); p = d['places'][0]
                    self.lat = float(p['latitude']); self.lon = float(p['longitude'])
                    self.location_name = p['place name']; self.last_fetch = 0
                    return
            except: pass
        # City
        try:
            r = requests.get(f"https://geocoding-api.open-meteo.com/v1/search?name={clean_query}&count=1&language=en&format=json", timeout=5)
            d = r.json()
            if 'results' in d and len(d['results']) > 0:
                res = d['results'][0]
                self.lat = res['latitude']; self.lon = res['longitude']
                self.location_name = res['name']; self.last_fetch = 0 
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
            r = requests.get(f"https://api.open-meteo.com/v1/forecast?latitude={self.lat}&longitude={self.lon}&current=temperature_2m,weather_code,is_day&daily=temperature_2m_max,temperature_2m_min,uv_index_max&temperature_unit=fahrenheit&timezone=auto", timeout=5)
            d = r.json()
            c = d.get('current', {}); dl = d.get('daily', {})
            
            icon = self.get_icon(c.get('weather_code', 0), c.get('is_day', 1))
            high = int(dl['temperature_2m_max'][0]); low = int(dl['temperature_2m_min'][0]); uv = float(dl['uv_index_max'][0])
            
            w_obj = {
                "sport": "weather", "id": "weather_widget", "status": "Live",
                "home_abbr": f"{int(c.get('temperature_2m', 0))}°", "away_abbr": self.location_name,
                "home_score": "", "away_score": "", "is_shown": True, "home_logo": "", "away_logo": "",
                "situation": { "icon": icon, "stats": { "high": high, "low": low, "uv": uv } }
            }
            self.cache = w_obj; self.last_fetch = time.time(); return w_obj
        except: return None

class SportsFetcher:
    def __init__(self, initial_loc):
        self.weather = WeatherFetcher(initial_loc)
        self.base_url = 'http://site.api.espn.com/apis/site/v2/sports/'
        
        # Explicitly define all leagues so they don't get skipped
        self.leagues = {
            'nfl': { 'path': 'football/nfl', 'scoreboard_params': {}, 'team_params': {'limit': 100} },
            'ncf_fbs': { 'path': 'football/college-football', 'scoreboard_params': {'groups': '80', 'limit': 100}, 'team_params': {'groups': '80', 'limit': 1000} },
            'ncf_fcs': { 'path': 'football/college-football', 'scoreboard_params': {'groups': '81', 'limit': 100}, 'team_params': {'groups': '81', 'limit': 1000} },
            'mlb': { 'path': 'baseball/mlb', 'scoreboard_params': {}, 'team_params': {'limit': 100} },
            'nhl': { 'path': 'hockey/nhl', 'scoreboard_params': {}, 'team_params': {'limit': 100} },
            'nba': { 'path': 'basketball/nba', 'scoreboard_params': {}, 'team_params': {'limit': 100} }
        }

    def get_corrected_logo(self, league_key, abbr, default_logo):
        key = f"{league_key.upper()}:{abbr}"
        return LOGO_OVERRIDES.get(key, default_logo)

    def fetch_all_teams(self):
        teams_catalog = {}
        for lg in self.leagues.keys(): teams_catalog[lg] = []
        
        for league_key, config in self.leagues.items():
            try:
                r = requests.get(f"{self.base_url}{config['path']}/teams", params=config['team_params'], timeout=10)
                data = r.json()
                
                # Handle College Data Structure vs Pro
                if 'college-football' in config['path']:
                    # College structure is Sports -> Leagues -> Teams
                    if 'sports' in data:
                        for sport in data['sports']:
                            for league in sport['leagues']:
                                for item in league.get('teams', []):
                                    t = item['team']
                                    abbr = t.get('abbreviation', 'UNK')
                                    logo = t.get('logos', [{}])[0].get('href', '')
                                    logo = self.get_corrected_logo(league_key, abbr, logo)
                                    
                                    # --- STRICT SORTING IMPROVEMENT ---
                                    # If valid_teams.py is loaded, reject teams that don't belong in this group
                                    if VALID_TEAMS_LOADED:
                                        if league_key == 'ncf_fbs' and abbr not in FBS_TEAMS:
                                            continue
                                        if league_key == 'ncf_fcs' and abbr not in FCS_TEAMS:
                                            continue

                                    teams_catalog[league_key].append({'abbr': abbr, 'logo': logo})
                else:
                    # Pro structure is Sports -> Leagues -> Teams
                    if 'sports' in data:
                        for sport in data['sports']:
                            for league in sport['leagues']:
                                for item in league.get('teams', []):
                                    t = item['team']
                                    abbr = t.get('abbreviation', 'UNK')
                                    logo = t.get('logos', [{}])[0].get('href', '')
                                    logo = self.get_corrected_logo(league_key, abbr, logo)
                                    teams_catalog[league_key].append({'abbr': abbr, 'logo': logo})
            except: pass

        with data_lock:
            state['all_teams_data'] = teams_catalog

    def get_real_games(self):
        games = []
        with data_lock: conf = state.copy()
        
        if conf['active_sports'].get('clock'):
            with data_lock: state['current_games'] = [{'sport':'clock','id':'clk','is_shown':True}]; return
        if conf['active_sports'].get('weather'):
            if conf['weather_location'] != self.weather.location_name: self.weather.update_coords(conf['weather_location'])
            w = self.weather.get_weather()
            if w: 
                with data_lock: state['current_games'] = [w]; return

        # --- DATE LOGIC ---
        if conf['debug_mode'] and conf['custom_date']:
            target_date_str = conf['custom_date']
            req_params = {'dates': target_date_str.replace('-','')}
        else:
            local_now = dt.now(timezone(timedelta(hours=TIMEZONE_OFFSET)))
            target_date_str = local_now.strftime("%Y-%m-%d")
            req_params = {'dates': target_date_str.replace('-','')}
        
        for league_key, config in self.leagues.items():
            if not conf['active_sports'].get(league_key): continue
            
            path = config['path']
            current_params = config['scoreboard_params'].copy()
            current_params.update(req_params)
            
            try:
                # NHL Native Override logic
                if league_key == 'nhl' and not conf['debug_mode']:
                    self._fetch_nhl_native(games, target_date_str)
                    continue

                r = requests.get(f"{self.base_url}{path}/scoreboard", params=current_params, timeout=5)
                data = r.json()
                
                for e in data.get('events', []):
                    status = e.get('status', {}); type_s = status.get('type', {})
                    state_game = type_s.get('state', 'pre')
                    
                    h = e['competitions'][0]['competitors'][0]; a = e['competitions'][0]['competitors'][1]
                    h_ab = h['team']['abbreviation']; a_ab = a['team']['abbreviation']

                    # --- STRICT FILTERING IMPROVEMENT ---
                    # Ensure game belongs in the requested bucket
                    if VALID_TEAMS_LOADED:
                        if league_key == 'ncf_fbs':
                            if h_ab not in FBS_TEAMS and a_ab not in FBS_TEAMS: continue
                        elif league_key == 'ncf_fcs':
                            if h_ab not in FCS_TEAMS and a_ab not in FCS_TEAMS: continue
                    
                    if conf['mode'] == 'live' and state_game not in ['in','half']: continue
                    
                    if conf['mode'] == 'my_teams':
                        h_id = f"{league_key}:{h_ab}"; a_id = f"{league_key}:{a_ab}"
                        h_match = (h_id in conf['my_teams']) or (h_ab in conf['my_teams'])
                        a_match = (a_id in conf['my_teams']) or (a_ab in conf['my_teams'])
                        if not h_match and not a_match: continue
                    
                    h_logo = self.get_corrected_logo(league_key, h_ab, h['team'].get('logo', ''))
                    a_logo = self.get_corrected_logo(league_key, a_ab, a['team'].get('logo', ''))
                    
                    # --- DATE FORMAT FIX ---
                    raw_status = type_s.get('shortDetail', 'TBD')
                    if state_game == 'pre' and ' - ' not in raw_status:
                        try:
                            game_date = e.get('date', '') # UTC string
                            utc_dt = dt.strptime(game_date, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
                            local_dt = utc_dt.astimezone(timezone(timedelta(hours=TIMEZONE_OFFSET)))
                            s_disp = local_dt.strftime("%I:%M %p").lstrip('0')
                        except: s_disp = raw_status
                    elif state_game == 'in':
                        p = status.get('period', 1); clk = status.get('displayClock', '')
                        s_disp = f"P{p} {clk}" if 'hockey' in path else f"Q{p} {clk}"
                    else:
                        s_disp = raw_status.replace("Final", "FINAL").replace("/OT", " OT")
                    
                    sit = e['competitions'][0].get('situation', {})
                    games.append({
                        'sport': league_key, 'id': e['id'], 'status': s_disp, 'state': state_game,
                        'is_shown': True,
                        'home_abbr': h_ab, 'home_score': h.get('score','0'), 'home_logo': h_logo,
                        'away_abbr': a_ab, 'away_score': a.get('score','0'), 'away_logo': a_logo,
                        'situation': { 'possession': sit.get('possession'), 'isRedZone': sit.get('isRedZone'), 'downDist': sit.get('downDistanceText') }
                    })
            except: pass
            
        with data_lock: state['current_games'] = games

    def _fetch_nhl_native(self, games_list, target_date_str):
        # Native NHL logic preserved for speed/accuracy if desired
        with data_lock:
            mode = state['mode']; my_teams = state['my_teams']
            
        try:
            r = requests.get("https://api-web.nhle.com/v1/schedule/now", timeout=5)
            if r.status_code != 200: return
            data = r.json()
            
            for day in data.get('gameWeek', []):
                if day['date'] != target_date_str: continue
                for g in day.get('games', []):
                    try:
                        gd = requests.get(f"https://api-web.nhle.com/v1/gamecenter/{g['id']}/play-by-play", timeout=3).json()
                        h = gd['homeTeam']; a = gd['awayTeam']
                        h_ab = h['abbrev']; a_ab = a['abbrev']
                        
                        if mode == 'my_teams':
                            h_key = f"NHL:{h_ab}"; a_key = f"NHL:{a_ab}"
                            if (h_key not in my_teams) and (a_key not in my_teams) and (h_ab not in my_teams) and (a_ab not in my_teams): continue
                        
                        state_game = 'pre'
                        if gd['gameState'] in ['LIVE','CRIT']: state_game = 'in'
                        elif gd['gameState'] in ['FINAL','OFF']: state_game = 'post'
                        
                        if mode == 'live' and state_game != 'in': continue

                        # Status
                        if state_game == 'pre':
                            try:
                                utc_dt = dt.strptime(gd['startTimeUTC'], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
                                s_disp = utc_dt.astimezone(timezone(timedelta(hours=TIMEZONE_OFFSET))).strftime("%I:%M %p").lstrip('0')
                            except: s_disp = "Scheduled"
                        elif state_game == 'in':
                            p = gd['periodDescriptor']['number']
                            pd = "P" + str(p)
                            if p > 3: pd = "OT"
                            rem = gd['clock']['timeRemaining']
                            s_disp = f"{pd} {rem}"
                        else: s_disp = "FINAL"

                        h_logo = self.get_corrected_logo('nhl', h_ab, h.get('logo', ''))
                        a_logo = self.get_corrected_logo('nhl', a_ab, a.get('logo', ''))
                        
                        if not h_logo or 'http' not in h_logo: h_logo = f"https://a.espncdn.com/i/teamlogos/nhl/500/{h_ab.lower()}.png"
                        if not a_logo or 'http' not in a_logo: a_logo = f"https://a.espncdn.com/i/teamlogos/nhl/500/{a_ab.lower()}.png"
                        
                        h_logo = self.get_corrected_logo('nhl', h_ab, h_logo)
                        a_logo = self.get_corrected_logo('nhl', a_ab, a_logo)

                        games_list.append({
                            'sport': 'nhl', 'id': str(g['id']), 'status': s_disp, 'state': state_game, 'is_shown': True,
                            'home_abbr': h_ab, 'home_score': str(h.get('score',0)), 'home_logo': h_logo,
                            'away_abbr': a_ab, 'away_score': str(a.get('score',0)), 'away_logo': a_logo,
                            'situation': {}
                        })
                    except: pass
        except: pass

fetcher = SportsFetcher(state['weather_location'])

def background_updater():
    fetcher.fetch_all_teams()
    while True:
        fetcher.get_real_games()
        time.sleep(UPDATE_INTERVAL)
        with data_lock:
            if state.get('test_pattern') and time.time() - state.get('test_pattern_ts', 0) > 60:
                state['test_pattern'] = False

app = Flask(__name__)

@app.route('/')
def dashboard(): return "Ticker Server Online"

@app.route('/api/ticker')
def ticker_api():
    with data_lock: d = state.copy()
    return jsonify({'meta': {'time': dt.now().strftime("%I:%M %p"), 'scroll_seamless': d['scroll_seamless'], 'brightness': d['brightness'], 'inverted': d['inverted'], 'panel_count': d['panel_count'], 'test_pattern': d['test_pattern'], 'reboot_requested': d['reboot_requested']}, 'games': d['current_games']})

@app.route('/api/state')
def state_api():
    with data_lock: return jsonify({'settings': state, 'games': state['current_games']})

@app.route('/api/teams')
def teams_api():
    with data_lock: return jsonify(state['all_teams_data'])

@app.route('/api/config', methods=['POST'])
def config_api():
    with data_lock: state.update(request.json)
    save_config_file()
    threading.Thread(target=fetcher.get_real_games).start()
    return jsonify({"status": "ok"})

@app.route('/api/hardware', methods=['POST'])
def hardware_api():
    d = request.json
    if d.get('action') == 'reboot':
        with data_lock: state['reboot_requested'] = True
        threading.Timer(10, lambda: state.update({'reboot_requested': False})).start()
    elif d.get('action') == 'test_pattern':
        with data_lock: 
            state['test_pattern'] = not state['test_pattern']
            state['test_pattern_ts'] = time.time()
    else:
        with data_lock: state.update(d)
        save_config_file()
    return jsonify({"status": "ok", "settings": state})

if __name__ == "__main__":
    threading.Thread(target=background_updater, daemon=True).start()
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 5000)))
