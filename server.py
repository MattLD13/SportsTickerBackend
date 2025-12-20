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

# ==========================================
# FBS ABBREVIATIONS
# ==========================================
FBS_TEAMS = [
    "AF", "AKR", "ALA", "APP", "ARIZ", "ASU", "ARK", "ARST", "ARMY", "AUB", 
    "BALL", "BAY", "BOIS", "BC", "BGSU", "BUF", "BYU", "CAL", "CMU", "CLT", 
    "CIN", "CLEM", "CCU", "COLO", "CSU", "CONN", "DEL", "DUKE", "ECU", "EMU", 
    "FAU", "FIU", "FLA", "FSU", "FRES", "GASO", "GAST", "GT", "UGA", "HAW", 
    "HOU", "ILL", "IND", "IOWA", "ISU", "JXST", "JMU", "KAN", "KSU", "KENN", 
    "KENT", "UK", "LIB", "ULL", "LT", "LOU", "LSU", "MAR", "MD", "MASS", "MEM", 
    "MIA", "M-OH", "MICH", "MSU", "MTSU", "MINN", "MSST", "MIZ", "MOST", 
    "NAVY", "NCST", "NEB", "NEV", "UNM", "NMSU", "UNC", "UNT", "NIU", "NU", 
    "ND", "OHIO", "OSU", "OU", "OKST", "ODU", "MISS", "ORE", "ORST", "PSU", 
    "PITT", "PUR", "RICE", "RUTG", "SAM", "SDSU", "SJSU", "SMU", "USA", "SC", 
    "USF", "USM", "STAN", "SYR", "TCU", "TEM", "TENN", "TEX", "TA&M", "TXST", 
    "TTU", "TOL", "TROY", "TULN", "TLSA", "UAB", "UCF", "UCLA", "ULM", "UMASS", 
    "UNLV", "USC", "UTAH", "USU", "UTEP", "UTSA", "VAN", "UVA", "VT", "WAKE", 
    "WASH", "WSU", "WVU", "WKU", "WMU", "WIS", "WYO"
]

# ==========================================
# FCS ABBREVIATIONS
# ==========================================
FCS_TEAMS = [
    "ACU", "AAMU", "ALST", "UALB", "ALCN", "UAPB", "APSU", "BCU", "BRWN", 
    "BRY", "BUCK", "BUT", "CP", "CAM", "CARK", "CCSU", "CHSO", "UTC", "CIT", 
    "COLG", "COLU", "COR", "DART", "DAV", "DAY", "DSU", "DRKE", "DUQ", "EIU", 
    "EKU", "ETAM", "EWU", "ETSU", "ELON", "FAMU", "FOR", "FUR", "GWEB", 
    "GTWN", "GRAM", "HAMP", "HARV", "HC", "HCU", "HOW", "IDHO", "IDST", 
    "ILST", "UIW", "INST", "JKST", "LAF", "LAM", "LEH", "LIN", "LIU", 
    "ME", "MRST", "MCN", "MER", "MERC", "MRMK", "MVSU", "MONM", "MONT", 
    "MTST", "MORE", "MORG", "MUR", "UNH", "NHVN", "NICH", "NORF", "UNA", 
    "NCAT", "NCCU", "UND", "NDSU", "NAU", "UNCO", "UNI", "NWST", "PENN", 
    "PRST", "PV", "PRES", "PRIN", "URI", "RICH", "RMU", "SAC", "SHU", 
    "SFPA", "SAM", "USD", "SELA", "SEMO", "SDAK", "SDST", "SCST", "SOU", 
    "SIU", "SUU", "STMN", "SFA", "STET", "STO", "STBK", "TAR", "TNST", 
    "TNTC", "TXSO", "TOW", "UCD", "UTM", "UTU", "UTRGV", "VAL", "VILL", "VMI", 
    "WAG", "WEB", "WGA", "WCU", "WIU", "W&M", "WOF", "YALE", "YSU"
]

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
        if re.fullmatch(r'\d{5}', clean_query):
            try:
                r = requests.get(f"https://api.zippopotam.us/us/{clean_query}", timeout=5)
                if r.status_code == 200:
                    d = r.json(); p = d['places'][0]
                    self.lat = float(p['latitude']); self.lon = float(p['longitude'])
                    self.location_name = p['place name']; self.last_fetch = 0
                    return
            except: pass
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
        
        # FIXED: FULL LEAGUE DICTIONARY RESTORED
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
        try:
            teams_catalog = {k: [] for k in self.leagues.keys()}
            
            # 1. Fetch Standard Leagues
            for lg_key in ['nfl', 'mlb', 'nhl', 'nba']:
                self._fetch_simple_league(lg_key, teams_catalog)

            # 2. Fetch College Football (FBS & FCS) and Sort
            # We fetch all College Football teams, then sort them into buckets
            cfb_teams_raw = []
            for grp in ['80', '81']: 
                try:
                    r = requests.get(f"{self.base_url}football/college-football/teams", params={'limit':1000, 'groups':grp}, timeout=10)
                    for item in r.json().get('sports', [{}])[0].get('leagues', [{}])[0].get('teams', []):
                        cfb_teams_raw.append(item['team'])
                except: pass
            
            # Sort into FBS/FCS buckets
            for t in cfb_teams_raw:
                abbr = t.get('abbreviation', 'UNK')
                logo = t.get('logos', [{}])[0].get('href', '')
                
                if abbr in FBS_TEAMS:
                    logo = self.get_corrected_logo('ncf_fbs', abbr, logo)
                    # Deduplicate
                    if not any(x['abbr'] == abbr for x in teams_catalog['ncf_fbs']):
                        teams_catalog['ncf_fbs'].append({'abbr': abbr, 'logo': logo})
                elif abbr in FCS_TEAMS:
                    logo = self.get_corrected_logo('ncf_fcs', abbr, logo)
                    if not any(x['abbr'] == abbr for x in teams_catalog['ncf_fcs']):
                        teams_catalog['ncf_fcs'].append({'abbr': abbr, 'logo': logo})

            with data_lock:
                state['all_teams_data'] = teams_catalog
        except Exception as e: 
            print(f"Catalog Error: {e}")

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
                h_match = (h_key in my_teams); a_match = (a_key in my_teams)
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
        with data_lock: conf = state.copy()
        
        if conf['active_sports'].get('clock'):
            with data_lock: state['current_games'] = [{'sport':'clock','id':'clk','is_shown':True}]; return
        if conf['active_sports'].get('weather'):
            if conf['weather_location'] != self.weather.location_name: self.weather.update_coords(conf['weather_location'])
            w = self.weather.get_weather()
            if w: 
                with data_lock: state['current_games'] = [w]; return

        target_date = conf['custom_date'] if (conf['debug_mode'] and conf['custom_date']) else dt.now(timezone(timedelta(hours=TIMEZONE_OFFSET))).strftime("%Y-%m-%d")
        
        for league_key in self.leagues.keys():
            if not conf['active_sports'].get(league_key): continue
            
            # Path Logic
            config = self.leagues[league_key]
            path = config['path']
            params = config['scoreboard_params'].copy()
            if conf['debug_mode']: params['dates'] = target_date.replace('-','')
            
            try:
                # NHL Native
                if league_key == 'nhl' and not conf['debug_mode']:
                    self._fetch_nhl_native(games, target_date)
                    continue

                r = requests.get(f"{self.base_url}{path}/scoreboard", params=params, timeout=5)
                data = r.json()
                
                for e in data.get('events', []):
                    status = e.get('status', {}); type_s = status.get('type', {})
                    state_game = type_s.get('state', 'pre')
                    
                    if conf['mode'] == 'live' and state_game not in ['in','half']: continue
                    
                    h = e['competitions'][0]['competitors'][0]; a = e['competitions'][0]['competitors'][1]
                    h_ab = h['team']['abbreviation']; a_ab = a['team']['abbreviation']
                    
                    if conf['mode'] == 'my_teams':
                        h_id = f"{league_key}:{h_ab}"; a_id = f"{league_key}:{a_ab}"
                        h_match = (h_id in conf['my_teams'])
                        a_match = (a_id in conf['my_teams'])
                        if not h_match and not a_match: continue
                    
                    h_logo = self.get_corrected_logo(league_key, h_ab, h['team'].get('logo', ''))
                    a_logo = self.get_corrected_logo(league_key, a_ab, a['team'].get('logo', ''))
                    
                    s_disp = type_s.get('shortDetail', 'TBD')
                    if state_game == 'in':
                        p = status.get('period', 1); clk = status.get('displayClock', '')
                        s_disp = f"P{p} {clk}" if 'hockey' in path else f"Q{p} {clk}"
                    
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
