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
data_lock = threading.Lock()

# ==========================================
# FBS ABBREVIATIONS (Full List)
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
# FCS ABBREVIATIONS (Full List)
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

# --- STRICT LEAGUE-SPECIFIC LOGO OVERRIDES ---
LOGO_OVERRIDES = {
    # === HOUSTON ===
    "NFL:HOU": "https://a.espncdn.com/i/teamlogos/nfl/500/hou.png",       # Texans
    "NBA:HOU": "https://a.espncdn.com/i/teamlogos/nba/500/hou.png",       # Rockets
    "MLB:HOU": "https://a.espncdn.com/i/teamlogos/mlb/500/hou.png",       # Astros
    "NCF_FBS:HOU": "https://a.espncdn.com/i/teamlogos/ncaa/500/248.png",  # Cougars

    # === MIAMI ===
    "NFL:MIA": "https://a.espncdn.com/i/teamlogos/nfl/500/mia.png",       # Dolphins
    "NBA:MIA": "https://a.espncdn.com/i/teamlogos/nba/500/mia.png",       # Heat
    "MLB:MIA": "https://a.espncdn.com/i/teamlogos/mlb/500/mia.png",       # Marlins
    "NCF_FBS:MIA": "https://a.espncdn.com/i/teamlogos/ncaa/500/2390.png", # Hurricanes
    "NCF_FBS:MIAMI": "https://a.espncdn.com/i/teamlogos/ncaa/500/2390.png",

    # === INDIANA ===
    "NFL:IND": "https://a.espncdn.com/i/teamlogos/nfl/500/ind.png",       # Colts
    "NBA:IND": "https://a.espncdn.com/i/teamlogos/nba/500/ind.png",       # Pacers
    "NCF_FBS:IND": "https://a.espncdn.com/i/teamlogos/ncaa/500/84.png",   # Hoosiers

    # === WASHINGTON ===
    "NHL:WSH": "https://a.espncdn.com/guid/cbe677ee-361e-91b4-5cae-6c4c30044743/logos/secondary_logo_on_black_color.png",
    "NHL:WAS": "https://a.espncdn.com/guid/cbe677ee-361e-91b4-5cae-6c4c30044743/logos/secondary_logo_on_black_color.png",
    "NFL:WSH": "https://a.espncdn.com/i/teamlogos/nfl/500/wsh.png",       # Commanders
    "NFL:WAS": "https://a.espncdn.com/i/teamlogos/nfl/500/wsh.png",
    "NBA:WSH": "https://a.espncdn.com/i/teamlogos/nba/500/was.png",       # Wizards
    "NBA:WAS": "https://a.espncdn.com/i/teamlogos/nba/500/was.png",
    "MLB:WSH": "https://a.espncdn.com/i/teamlogos/mlb/500/wsh.png",       # Nationals
    "MLB:WAS": "https://a.espncdn.com/i/teamlogos/mlb/500/wsh.png",
    "NCF_FBS:WASH": "https://a.espncdn.com/i/teamlogos/ncaa/500/264.png", # Huskies

    # === NHL SPECIFIC FIXES ===
    "NHL:SJS": "https://a.espncdn.com/i/teamlogos/nhl/500/sj.png",
    "NHL:NJD": "https://a.espncdn.com/i/teamlogos/nhl/500/nj.png",
    "NHL:TBL": "https://a.espncdn.com/i/teamlogos/nhl/500/tb.png",
    "NHL:LAK": "https://a.espncdn.com/i/teamlogos/nhl/500/la.png",
    "NHL:VGK": "https://a.espncdn.com/i/teamlogos/nhl/500/vgs.png", 
    "NHL:VEG": "https://a.espncdn.com/i/teamlogos/nhl/500/vgs.png",
    "NHL:UTA": "https://a.espncdn.com/i/teamlogos/nhl/500/utah.png",

    # === NCAA FIXES ===
    "NCF_FBS:CAL": "https://a.espncdn.com/i/teamlogos/ncaa/500/25.png",
    "NCF_FBS:OSU": "https://a.espncdn.com/i/teamlogos/ncaa/500/194.png",
    "NCF_FBS:ORST": "https://a.espncdn.com/i/teamlogos/ncaa/500/204.png",
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
        self.leagues = {
            'nfl': { 'path': 'football/nfl', 'scoreboard_params': {}, 'team_params': {'limit': 100} },
            'mlb': { 'path': 'baseball/mlb', 'scoreboard_params': {}, 'team_params': {'limit': 100} },
            'nhl': { 'path': 'hockey/nhl', 'scoreboard_params': {}, 'team_params': {'limit': 100} },
            'nba': { 'path': 'basketball/nba', 'scoreboard_params': {}, 'team_params': {'limit': 100} }
        }

    def get_corrected_logo(self, league_key, abbr, default_logo):
        key = f"{league_key.upper()}:{abbr}"
        return LOGO_OVERRIDES.get(key, default_logo)

    def fetch_all_teams(self):
        teams_catalog = {'nfl':[], 'mlb':[], 'nhl':[], 'nba':[], 'ncf_fbs':[], 'ncf_fcs':[]}
        
        # 1. Pro Sports (Simple)
        for league_key in ['nfl', 'mlb', 'nhl', 'nba']:
            config = self.leagues[league_key]
            try:
                r = requests.get(f"{self.base_url}{config['path']}/teams", params=config['team_params'], timeout=10)
                d = r.json()
                if 'sports' in d:
                    for t in d['sports'][0]['leagues'][0]['teams']:
                        abbr = t['team'].get('abbreviation', 'UNK')
                        logo = t['team'].get('logos', [{}])[0].get('href', '')
                        logo = self.get_corrected_logo(league_key, abbr, logo)
                        teams_catalog[league_key].append({'abbr': abbr, 'logo': logo})
            except: pass

        # 2. College Football - FBS (Group 80)
        try:
            r = requests.get(f"{self.base_url}football/college-football/teams", params={'limit':1000, 'groups': '80'}, timeout=10)
            d = r.json()
            if 'sports' in d:
                for t in d['sports'][0]['leagues'][0]['teams']:
                    abbr = t['team'].get('abbreviation', 'UNK')
                    logo = t['team'].get('logos', [{}])[0].get('href', '')
                    logo = self.get_corrected_logo('ncf_fbs', abbr, logo)
                    teams_catalog['ncf_fbs'].append({'abbr': abbr, 'logo': logo})
        except: pass

        # 3. College Football - FCS (Group 81)
        try:
            r = requests.get(f"{self.base_url}football/college-football/teams", params={'limit':1000, 'groups': '81'}, timeout=10)
            d = r.json()
            if 'sports' in d:
                for t in d['sports'][0]['leagues'][0]['teams']:
                    abbr = t['team'].get('abbreviation', 'UNK')
                    logo = t['team'].get('logos', [{}])[0].get('href', '')
                    logo = self.get_corrected_logo('ncf_fcs', abbr, logo)
                    teams_catalog['ncf_fcs'].append({'abbr': abbr, 'logo': logo})
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

        target_date_str = (dt.now(timezone(timedelta(hours=TIMEZONE_OFFSET)))).strftime("%Y-%m-%d")
        if conf['debug_mode'] and conf['custom_date']: target_date_str = conf['custom_date']
        req_params = {'dates': target_date_str.replace('-','')}

        # === FETCH LOOP ===
        # Pro Leagues
        for league_key in ['nfl', 'mlb', 'nhl', 'nba']:
            if not conf['active_sports'].get(league_key): continue
            
            # NHL Native Exception
            if league_key == 'nhl' and not conf['debug_mode']:
                self._fetch_nhl_native(games, target_date_str); continue

            path = self.leagues[league_key]['path']
            try:
                self._fetch_games_generic(games, league_key, path, req_params, conf, target_date_str)
            except: pass

        # College FBS
        if conf['active_sports'].get('ncf_fbs'):
            try:
                fbs_params = req_params.copy(); fbs_params['groups'] = '80'
                self._fetch_games_generic(games, 'ncf_fbs', 'football/college-football', fbs_params, conf, target_date_str)
            except: pass

        # College FCS
        if conf['active_sports'].get('ncf_fcs'):
            try:
                fcs_params = req_params.copy(); fcs_params['groups'] = '81'
                self._fetch_games_generic(games, 'ncf_fcs', 'football/college-football', fcs_params, conf, target_date_str)
            except: pass
        
        with data_lock: state['current_games'] = games

    def _fetch_games_generic(self, games, league_key, path, params, conf, target_date_str):
        r = requests.get(f"{self.base_url}{path}/scoreboard", params=params, timeout=5)
        data = r.json()
        for e in data.get('events', []):
            try:
                utc_s = e['date'].replace('Z','')
                g_dt = dt.fromisoformat(utc_s).replace(tzinfo=timezone.utc)
                local_dt = g_dt.astimezone(timezone(timedelta(hours=TIMEZONE_OFFSET)))
                g_date = local_dt.strftime("%Y-%m-%d")
            except: g_date = target_date_str

            st = e.get('status', {}); tp = st.get('type', {}); gst = tp.get('state', 'pre')
            if g_date != target_date_str and gst not in ['in','half']: continue
            if league_key == 'mlb' and g_date != target_date_str: continue

            comp = e['competitions'][0]; h = comp['competitors'][0]; a = comp['competitors'][1]
            h_ab = h['team']['abbreviation']; a_ab = a['team']['abbreviation']

            is_shown = True
            if conf['mode'] == 'live' and gst not in ['in', 'half']: is_shown = False
            elif conf['mode'] == 'my_teams':
                hk = f"{league_key}:{h_ab}"; ak = f"{league_key}:{a_ab}"
                if (hk not in conf['my_teams'] and h_ab not in conf['my_teams']) and \
                   (ak not in conf['my_teams'] and a_ab not in conf['my_teams']): is_shown = False

            h_lg = self.get_corrected_logo(league_key, h_ab, h['team'].get('logo',''))
            a_lg = self.get_corrected_logo(league_key, a_ab, a['team'].get('logo',''))

            s_disp = tp.get('shortDetail', 'TBD')
            if gst == 'pre':
                try: s_disp = local_dt.strftime("%I:%M %p").lstrip('0')
                except: pass
            elif gst == 'in':
                p = st.get('period', 1); clk = st.get('displayClock', '')
                s_disp = f"P{p} {clk}" if 'hockey' in path else f"Q{p} {clk}"
            else:
                s_disp = s_disp.replace("Final", "FINAL").replace("/OT", " OT")

            sit = comp.get('situation', {})
            games.append({
                'sport': league_key, 'id': e['id'], 'status': s_disp, 'state': gst, 'is_shown': is_shown,
                'home_abbr': h_ab, 'home_score': h.get('score','0'), 'home_logo': h_lg,
                'away_abbr': a_ab, 'away_score': a.get('score','0'), 'away_logo': a_lg,
                'situation': { 'possession': sit.get('possession'), 'isRedZone': sit.get('isRedZone'), 'downDist': sit.get('downDistanceText') }
            })

    def _fetch_nhl_native(self, games_list, target_date_str):
        with data_lock:
            mode = state['mode']; my_teams = state['my_teams']
        try:
            r = requests.get("https://api-web.nhle.com/v1/schedule/now", timeout=5)
            if r.status_code != 200: return
            for d in r.json().get('gameWeek', []):
                if d.get('date') == target_date_str:
                    for g in d.get('games', []):
                        try:
                            gd = requests.get(f"https://api-web.nhle.com/v1/gamecenter/{g['id']}/play-by-play", timeout=3).json()
                            h_ab = gd['homeTeam']['abbrev']; a_ab = gd['awayTeam']['abbrev']
                            
                            is_shown = True
                            if mode == 'live' and gd['gameState'] not in ['LIVE','CRIT']: is_shown = False
                            if mode == 'my_teams':
                                if (f"nhl:{h_ab}" not in my_teams and h_ab not in my_teams) and (f"nhl:{a_ab}" not in my_teams and a_ab not in my_teams): is_shown = False
                            
                            st = gd.get('gameState', 'OFF'); map_st = 'in' if st in ['LIVE', 'CRIT'] else ('pre' if st in ['PRE', 'FUT'] else 'post')
                            if map_st == 'pre':
                                u = dt.strptime(gd['startTimeUTC'], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
                                disp = u.astimezone(timezone(timedelta(hours=TIMEZONE_OFFSET))).strftime("%I:%M %p").lstrip('0')
                            elif map_st == 'in':
                                pd = gd['periodDescriptor']; p = pd['number']; pl = f"P{p}" if p<=3 else "OT"; tm = gd['clock']['timeRemaining']; disp = f"{pl} {tm}"
                            else: disp = "FINAL"

                            h_lg = self.get_corrected_logo('nhl', h_ab, f"https://a.espncdn.com/i/teamlogos/nhl/500/{h_ab.lower()}.png")
                            a_lg = self.get_corrected_logo('nhl', a_ab, f"https://a.espncdn.com/i/teamlogos/nhl/500/{a_ab.lower()}.png")

                            games_list.append({
                                'sport': 'nhl', 'id': str(g['id']), 'status': disp, 'state': map_st, 'is_shown': is_shown,
                                'home_abbr': h_ab, 'home_score': str(gd['homeTeam'].get('score',0)), 'home_logo': h_lg,
                                'away_abbr': a_ab, 'away_score': str(gd['awayTeam'].get('score',0)), 'away_logo': a_lg,
                                'situation': {}
                            })
                        except: pass
        except: pass

fetcher = SportsFetcher(state['weather_location'])

def background_updater():
    fetcher.fetch_all_teams()
    while True: fetcher.get_real_games(); time.sleep(UPDATE_INTERVAL)

# ================= FLASK API =================
app = Flask(__name__)

@app.route('/')
def root(): return "Ticker Server Online"

@app.route('/api/ticker')
def api_ticker():
    with data_lock: d = state.copy()
    vis = [g for g in d['current_games'] if g.get('is_shown', True)]
    return jsonify({'meta': {'time': dt.now().strftime("%I:%M %p"), 'count': len(vis), 'scroll_seamless': d['scroll_seamless'], 'brightness': d['brightness'], 'inverted': d['inverted'], 'panel_count': d['panel_count'], 'test_pattern': d['test_pattern'], 'reboot_requested': d['reboot_requested']}, 'games': vis})

@app.route('/api/state')
def api_state():
    with data_lock: return jsonify({'settings': state, 'games': state['current_games']})

@app.route('/api/teams')
def api_teams():
    with data_lock: return jsonify(state['all_teams_data'])

@app.route('/api/config', methods=['POST'])
def api_config():
    with data_lock: state.update(request.json)
    save_config_file()
    threading.Thread(target=fetcher.get_real_games).start()
    return jsonify({"status": "ok"})

@app.route('/api/debug', methods=['POST'])
def api_debug():
    with data_lock: state.update(request.json)
    fetcher.get_real_games()
    return jsonify({"status": "ok"})

@app.route('/api/hardware', methods=['POST'])
def api_hardware():
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
