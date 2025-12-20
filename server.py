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
    print("CRITICAL WARNING: valid_teams.py not found. Sorting will fail.")
    FBS_TEAMS = []
    FCS_TEAMS = []

# --- LOGO OVERRIDES (Strict Namespaced) ---
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
    "NFL:MIA": "https://a.espncdn.com/i/teamlogos/nfl/500/mia.png",
    
    # NBA
    "NBA:WSH": "https://a.espncdn.com/i/teamlogos/nba/500/was.png",
    "NBA:WAS": "https://a.espncdn.com/i/teamlogos/nba/500/was.png",
    "NBA:MIA": "https://a.espncdn.com/i/teamlogos/nba/500/mia.png",
    "NBA:HOU": "https://a.espncdn.com/i/teamlogos/nba/500/hou.png",
    "NBA:IND": "https://a.espncdn.com/i/teamlogos/nba/500/ind.png",
    
    # MLB
    "MLB:WSH": "https://a.espncdn.com/i/teamlogos/mlb/500/wsh.png",
    "MLB:WAS": "https://a.espncdn.com/i/teamlogos/mlb/500/wsh.png",
    "MLB:HOU": "https://a.espncdn.com/i/teamlogos/mlb/500/hou.png",
    "MLB:MIA": "https://a.espncdn.com/i/teamlogos/mlb/500/mia.png",

    # NCAA
    "NCF_FBS:CAL": "https://a.espncdn.com/i/teamlogos/ncaa/500/25.png",
    "NCF_FBS:OSU": "https://a.espncdn.com/i/teamlogos/ncaa/500/194.png",
    "NCF_FBS:ORST": "https://a.espncdn.com/i/teamlogos/ncaa/500/204.png",
    "NCF_FBS:MIA": "https://a.espncdn.com/i/teamlogos/ncaa/500/2390.png",
    "NCF_FBS:MIAMI": "https://a.espncdn.com/i/teamlogos/ncaa/500/2390.png",
    "NCF_FBS:HOU": "https://a.espncdn.com/i/teamlogos/ncaa/500/248.png",
    "NCF_FBS:IND": "https://a.espncdn.com/i/teamlogos/ncaa/500/84.png",
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
                "sport": "weather", "id": "weather_widget", "status": "Live", "home_abbr": f"{cur_temp}°", "away_abbr": self.location_name, "is_shown": True, "home_logo": "", "away_logo": "",
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

    def get_corrected_logo(self, league_key, abbr, default_logo):
        # Look up key like "NFL:HOU"
        key = f"{league_key.upper()}:{abbr}"
        return LOGO_OVERRIDES.get(key, default_logo)

    def fetch_all_teams(self):
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
                            
                            # Determine league for logo lookup
                            league_tag = 'ncf_fbs' if t_abbr in FBS_TEAMS else 'ncf_fcs'
                            
                            # APPLY FIX: Use namespaced lookup
                            t_logo = self.get_corrected_logo(league_tag, t_abbr, t_logo)

                            team_obj = {'abbr': t_abbr, 'logo': t_logo}
                            
                            if t_abbr in FBS_TEAMS:
                                teams_catalog['ncf_fbs'].append(team_obj)
                            elif t_abbr in FCS_TEAMS:
                                teams_catalog['ncf_fcs'].append(team_obj)
            
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
                            
                            # APPLY FIX: Use namespaced lookup
                            logo = self.get_corrected_logo(league_key, abbr, logo)
                            
                            catalog[league_key].append({'abbr': abbr, 'logo': logo})
        except: pass

    def _fetch_nhl_native(self, games_list, target_date_str):
        with data_lock:
            is_nhl_enabled = state['active_sports'].get('nhl', False)
        
        schedule_url = "https://api-web.nhle.com/v1/schedule/now"
        try:
            response = requests.get(schedule_url, timeout=5)
            if response.status_code != 200: return
            schedule_data = response.json()
        except: return

        for date_entry in schedule_data.get('gameWeek', []):
            if date_entry.get('date') != target_date_str: continue 
            for game in date_entry.get('games', []):
                self._process_single_nhl_game(game['id'], games_list, is_nhl_enabled)

    def _process_single_nhl_game(self, game_id, games_list, is_enabled):
        pbp_url = f"https://api-web.nhle.com/v1/gamecenter/{game_id}/play-by-play"
        try:
            r = requests.get(pbp_url, timeout=3)
            if r.status_code != 200: return
            data = r.json()
        except: return

        away_abbr = data['awayTeam']['abbrev']
        home_abbr = data['homeTeam']['abbrev']
        away_score = str(data['awayTeam'].get('score', 0))
        home_score = str(data['homeTeam'].get('score', 0))
        
        game_type = data.get('gameType', 2)
        is_playoff = (game_type == 3)

        # APPLY FIX: Use namespaced lookup
        away_logo = self.get_corrected_logo('nhl', away_abbr, f"https://a.espncdn.com/i/teamlogos/nhl/500/{away_abbr.lower()}.png")
        home_logo = self.get_corrected_logo('nhl', home_abbr, f"https://a.espncdn.com/i/teamlogos/nhl/500/{home_abbr.lower()}.png")

        game_state = data.get('gameState', 'OFF') 
        mapped_state = 'in' if game_state in ['LIVE', 'CRIT'] else 'post'
        if game_state in ['PRE', 'FUT']: mapped_state = 'pre'

        with data_lock:
            mode = state['mode']
            my_teams = state['my_teams']
        
        is_shown = is_enabled
        if is_shown:
            if mode == 'live' and mapped_state != 'in': is_shown = False
            if mode == 'my_teams':
                h_key = f"nhl:{home_abbr}"; a_key = f"nhl:{away_abbr}"
                h_match = (h_key in my_teams) or (home_abbr in my_teams)
                a_match = (a_key in my_teams) or (away_abbr in my_teams)
                if not h_match and not a_match: is_shown = False

        clock = data.get('clock', {})
        time_rem = clock.get('timeRemaining', '00:00')
        period = data.get('periodDescriptor', {}).get('number', 1)
        
        period_label = f"P{period}"
        if period == 4: period_label = "OT"
        elif period > 4: period_label = "2OT" if is_playoff else "S/O"
        
        if game_state == 'FINAL' or game_state == 'OFF': status_disp = "FINAL"
        elif game_state in ['PRE', 'FUT']: 
            raw_time = data.get('startTimeUTC', '')
            if raw_time:
                try:
                    utc_dt = dt.strptime(raw_time, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
                    local_dt = utc_dt + timedelta(hours=TIMEZONE_OFFSET)
                    status_disp = local_dt.strftime("%I:%M %p").lstrip('0') 
                except: status_disp = "Scheduled"
            else: status_disp = "Scheduled"
        elif clock.get('inIntermission'): status_disp = f"{period_label} INT"
        else:
            if period > 4 and not is_playoff: status_disp = "S/O"
            else: status_disp = f"{period_label} {time_rem}"

        sit_code = data.get('situation', {}).get('situationCode', '1551')
        try:
            away_goalie = int(sit_code[0]); away_skaters = int(sit_code[1])
            home_skaters = int(sit_code[2]); home_goalie = int(sit_code[3])
        except: away_goalie, away_skaters, home_skaters, home_goalie = 1, 5, 5, 1

        is_pp = False; possession = ""; is_empty_net = False
        if away_skaters > home_skaters: is_pp = True; possession = away_abbr 
        elif home_skaters > away_skaters: is_pp = True; possession = home_abbr
        if away_goalie == 0 or home_goalie == 0: is_empty_net = True

        game_obj = {
            'sport': 'nhl', 'id': str(game_id), 'status': status_disp, 'state': mapped_state,
            'is_shown': is_shown, 'is_playoff': is_playoff,
            'home_abbr': home_abbr, 'home_score': home_score, 'home_logo': home_logo, 'home_id': home_abbr, 
            'away_abbr': away_abbr, 'away_score': away_score, 'away_logo': away_logo, 'away_id': away_abbr,
            'period': period, 
            'situation': { 'powerPlay': is_pp, 'possession': possession, 'emptyNet': is_empty_net }
        }
        games_list.append(game_obj)

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
                    
                    status_obj = event.get('status', {})
                    status_type = status_obj.get('type', {})
                    status_state = status_type.get('state', 'pre')
                    
                    keep_date = (status_state == 'in') or (game_date_str == target_date_str)
                    if league_key == 'mlb' and not keep_date: continue
                    if not keep_date: continue

                    comp = event['competitions'][0]; home = comp['competitors'][0]; away = comp['competitors'][1]
                    home_abbr = home['team']['abbreviation']; away_abbr = away['team']['abbreviation']
                    
                    # STRICT FILTER FOR COLLEGE GAMES
                    if league_key == 'ncf_fbs':
                        if home_abbr not in FBS_TEAMS and away_abbr not in FBS_TEAMS: continue
                    elif league_key == 'ncf_fcs':
                        if home_abbr not in FCS_TEAMS and away_abbr not in FCS_TEAMS: continue

                    is_shown = True
                    if local_config['mode'] == 'live' and status_state not in ['in', 'half']: is_shown = False
                    elif local_config['mode'] == 'my_teams':
                        h_key = f"{league_key}:{home_abbr}"; a_key = f"{league_key}:{away_abbr}"
                        if (h_key not in local_config['my_teams'] and home_abbr not in local_config['my_teams']) and \
                           (a_key not in local_config['my_teams'] and away_abbr not in local_config['my_teams']): is_shown = False
                    
                    # Logic for Display
                    raw_status = status_type.get('shortDetail', 'Scheduled')
                    period = status_obj.get('period', 1)
                    clock = status_obj.get('displayClock', '')
                    is_halftime = (status_state == 'half') or (period == 2 and clock == '0:00')

                    if is_halftime: status_disp = "HALFTIME"; status_state = 'half' 
                    elif status_state == 'in' and ('football' in config['path'] or league_key == 'nba'):
                        prefix = f"Q{period}"
                        if 'football' in config['path']:
                            if period == 5: prefix = "OT"
                            elif period > 5: prefix = f"{period-4}OT"
                        elif league_key == 'nba':
                            if period >= 5: prefix = f"OT{period-4}"
                        if clock: status_disp = f"{prefix} - {clock}"
                        else: status_disp = f"{prefix}" 
                    else:
                        status_disp = raw_status.replace("Final", "FINAL").replace(" EST", "").replace(" EDT", "").replace("/OT", "")
                        if " - " in status_disp: status_disp = status_disp.split(" - ")[-1]

                    # Logos
                    home_logo_url = home['team'].get('logo', '')
                    away_logo_url = away['team'].get('logo', '')
                    
                    # APPLY FIX: Namespaced Lookup
                    home_logo_url = self.get_corrected_logo(league_key, home_abbr, home_logo_url)
                    away_logo_url = self.get_corrected_logo(league_key, away_abbr, away_logo_url)

                    # Situation
                    sit = comp.get('situation', {})
                    game_obj = {
                        'sport': league_key, 'id': event['id'], 'status': status_disp, 'state': status_state, 'is_shown': is_shown, 
                        'home_abbr': home_abbr, 'home_score': home.get('score', '0'), 'home_logo': home_logo_url, 'home_id': home.get('id'),
                        'away_abbr': away_abbr, 'away_score': away.get('score', '0'), 'away_logo': away_logo_url, 'away_id': away.get('id'),
                        'period': period,
                        'situation': {}
                    }
                    if status_state == 'in' and not is_halftime:
                        if 'football' in config['path']:
                            game_obj['situation'] = { 'possession': sit.get('possession', ''), 'downDist': sit.get('downDistanceText', ''), 'isRedZone': sit.get('isRedZone', False) }
                        elif league_key == 'mlb':
                            game_obj['situation'] = { 'balls': sit.get('balls', 0), 'strikes': sit.get('strikes', 0), 'outs': sit.get('outs', 0), 'onFirst': sit.get('onFirst', False), 'onSecond': sit.get('onSecond', False), 'onThird': sit.get('onThird', False) }
                    
                    games.append(game_obj)
            except Exception as e: print(f"Err {league_key}: {e}")

        with data_lock: state['current_games'] = games

fetcher = SportsFetcher()
def background_updater():
    fetcher.fetch_all_teams()
    while True: fetcher.get_real_games(); time.sleep(UPDATE_INTERVAL)

# ================= FLASK API =================
app = Flask(__name__)

@app.route('/')
def dashboard(): return "Ticker Server Running"

@app.route('/api/ticker')
def get_ticker():
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
    t = threading.Thread(target=background_updater); t.daemon = True; t.start()
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 5000)))
