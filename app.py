import time
import threading
import json
import os
import re
from datetime import datetime as dt, timezone, timedelta
import requests
from flask import Flask, jsonify, request, render_template_string

# ================= CONFIGURATION =================
CONFIG_FILE = "ticker_config.json"
UPDATE_INTERVAL = 5
data_lock = threading.Lock()

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
    "Cache-Control": "no-cache, no-store, must-revalidate",
    "Pragma": "no-cache",
    "Expires": "0"
}

# ================= DEFAULT STATE =================
default_state = {
    'active_sports': { 
        'nfl': True, 'ncf_fbs': True, 'ncf_fcs': True, 
        'mlb': True, 'nhl': True, 'nba': True, 
        'soccer_epl': True, 'soccer_mls': True, 'golf': True, # ADDED NEW SPORTS
        'weather': False, 'clock': False 
    },
    'mode': 'all', 
    'layout_mode': 'schedule',
    'scroll_seamless': False,
    'my_teams': ["NYG", "NYY", "NJD", "NYK", "LAL", "BOS", "KC", "BUF", "LEH", "LIV", "MCI"], # Added soccer teams
    'current_games': [],
    'all_teams_data': {}, 
    'debug_mode': False,
    'custom_date': None,
    'brightness': 0.5,
    'scroll_speed': 5,
    'inverted': False,
    'panel_count': 2,
    'test_pattern': False,
    'reboot_requested': False,
    'weather_location': "New York",
    'utc_offset': -5 
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
                'layout_mode': state['layout_mode'],
                'scroll_seamless': state['scroll_seamless'], 
                'my_teams': state['my_teams'],
                'brightness': state['brightness'],
                'scroll_speed': state['scroll_speed'],
                'inverted': state['inverted'],
                'panel_count': state['panel_count'],
                'weather_location': state['weather_location'],
                'utc_offset': state['utc_offset']
            }
        with open(CONFIG_FILE, 'w') as f:
            json.dump(export_data, f)
    except: pass

# ==========================================
# TEAMS LISTS & MAPPINGS
# ==========================================
# (Existing FBS/FCS Lists omitted for brevity - keep them as they were in previous code)
FBS_TEAMS = ["AF", "AKR", "ALA", "APP", "ARIZ", "ASU", "ARK", "ARST", "ARMY", "AUB", "BALL", "BAY", "BOIS", "BC", "BGSU", "BUF", "BYU", "CAL", "CMU", "CLT", "CIN", "CLEM", "CCU", "COLO", "CSU", "CONN", "DEL", "DUKE", "ECU", "EMU", "FAU", "FIU", "FLA", "FSU", "FRES", "GASO", "GAST", "GT", "UGA", "HAW", "HOU", "ILL", "IND", "IOWA", "ISU", "JXST", "JMU", "KAN", "KSU", "KENN", "KENT", "UK", "LIB", "ULL", "LT", "LOU", "LSU", "MAR", "MD", "MASS", "MEM", "MIA", "M-OH", "MICH", "MSU", "MTSU", "MINN", "MSST", "MIZ", "MOST", "NAVY", "NCST", "NEB", "NEV", "UNM", "NMSU", "UNC", "UNT", "NIU", "NU", "ND", "OHIO", "OSU", "OU", "OKST", "ODU", "MISS", "ORE", "ORST", "PSU", "PITT", "PUR", "RICE", "RUTG", "SAM", "SDSU", "SJSU", "SMU", "USA", "SC", "USF", "USM", "STAN", "SYR", "TCU", "TEM", "TENN", "TEX", "TA&M", "TXST", "TTU", "TOL", "TROY", "TULN", "TLSA", "UAB", "UCF", "UCLA", "ULM", "UMASS", "UNLV", "USC", "UTAH", "USU", "UTEP", "UTSA", "VAN", "UVA", "VT", "WAKE", "WASH", "WSU", "WVU", "WKU", "WMU", "WIS", "WYO"]
FCS_TEAMS = ["ACU", "AAMU", "ALST", "UALB", "ALCN", "UAPB", "APSU", "BCU", "BRWN", "BRY", "BUCK", "BUT", "CP", "CAM", "CARK", "CCSU", "CHSO", "UTC", "CIT", "COLG", "COLU", "COR", "DART", "DAV", "DAY", "DSU", "DRKE", "DUQ", "EIU", "EKU", "ETAM", "EWU", "ETSU", "ELON", "FAMU", "FOR", "FUR", "GWEB", "GTWN", "GRAM", "HAMP", "HARV", "HC", "HCU", "HOW", "IDHO", "IDST", "ILST", "UIW", "INST", "JKST", "LAF", "LAM", "LEH", "LIN", "LIU", "ME", "MRST", "MCN", "MER", "MERC", "MRMK", "MVSU", "MONM", "MONT", "MTST", "MORE", "MORG", "MUR", "UNH", "NHVN", "NICH", "NORF", "UNA", "NCAT", "NCCU", "UND", "NDSU", "NAU", "UNCO", "UNI", "NWST", "PENN", "PRST", "PV", "PRES", "PRIN", "URI", "RICH", "RMU", "SAC", "SHU", "SFPA", "SAM", "USD", "SELA", "SEMO", "SDAK", "SDST", "SCST", "SOU", "SIU", "SUU", "STMN", "SFA", "STET", "STO", "STBK", "TAR", "TNST", "TNTC", "TXSO", "TOW", "UCD", "UTM", "UTU", "UTRGV", "VAL", "VILL", "VMI", "WAG", "WEB", "WGA", "WCU", "WIU", "W&M", "WOF", "YALE", "YSU"]

ABBR_MAPPING = {
    'SJS': 'SJ', 'TBL': 'TB', 'LAK': 'LA', 'NJD': 'NJ', 'VGK': 'VEG', 'UTA': 'UTAH', 'WSH': 'WSH', 'MTL': 'MTL', 'CHI': 'CHI',
    'NY': 'NYK', 'NO': 'NOP', 'GS': 'GSW', 'SA': 'SAS',
    'TOT': 'TOT', 'ARS': 'ARS', 'LIV': 'LIV', 'MCI': 'MCI', 'MUN': 'MUN', 'CHE': 'CHE' # Soccer mappings
}

LOGO_OVERRIDES = {
    # ... (Keep existing overrides) ...
    "SOCCER_EPL:TOT": "https://a.espncdn.com/i/teamlogos/soccer/500/367.png",
    "SOCCER_EPL:ARS": "https://a.espncdn.com/i/teamlogos/soccer/500/359.png",
    "SOCCER_EPL:LIV": "https://a.espncdn.com/i/teamlogos/soccer/500/364.png"
}

# Standard Game Lengths (minutes)
SPORT_DURATIONS = {
    'nfl': 195, 'ncf_fbs': 210, 'ncf_fcs': 195,
    'nba': 150, 'nhl': 150, 'mlb': 180, 'weather': 60,
    'soccer_epl': 110, 'soccer_mls': 110, 'golf': 720 # Golf lasts all day
}

class WeatherFetcher:
    # ... (Keep existing WeatherFetcher class exactly as is) ...
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
                "home_color": "#000000", "away_color": "#000000",
                "situation": { "icon": icon, "stats": { "high": high, "low": low, "uv": uv } }
            }
            self.cache = w_obj; self.last_fetch = time.time(); return w_obj
        except: return None

class SportsFetcher:
    def __init__(self, initial_loc):
        self.weather = WeatherFetcher(initial_loc)
        self.base_url = 'http://site.api.espn.com/apis/site/v2/sports/'
        self.possession_cache = {}  
        self.leagues = {
            'nfl': { 'path': 'football/nfl', 'scoreboard_params': {}, 'team_params': {'limit': 100} },
            'ncf_fbs': { 'path': 'football/college-football', 'scoreboard_params': {'groups': '80', 'limit': 100}, 'team_params': {'groups': '80', 'limit': 1000} },
            'ncf_fcs': { 'path': 'football/college-football', 'scoreboard_params': {'groups': '81', 'limit': 100}, 'team_params': {'groups': '81', 'limit': 1000} },
            'mlb': { 'path': 'baseball/mlb', 'scoreboard_params': {}, 'team_params': {'limit': 100} },
            'nhl': { 'path': 'hockey/nhl', 'scoreboard_params': {}, 'team_params': {'limit': 100} },
            'nba': { 'path': 'basketball/nba', 'scoreboard_params': {}, 'team_params': {'limit': 100} },
            # NEW LEAGUES
            'soccer_epl': { 'path': 'soccer/eng.1', 'scoreboard_params': {}, 'team_params': {} },
            'soccer_mls': { 'path': 'soccer/usa.1', 'scoreboard_params': {}, 'team_params': {} }
        }

    def get_corrected_logo(self, league_key, abbr, default_logo):
        key = f"{league_key.upper()}:{abbr}"
        return LOGO_OVERRIDES.get(key, default_logo)

    # ... (Keep existing helper methods: lookup_team_info_from_cache, calculate_game_timing, fetch_all_teams, _fetch_simple_league, _fetch_nhl_native) ...
    def lookup_team_info_from_cache(self, league, abbr):
        search_abbr = ABBR_MAPPING.get(abbr, abbr)
        try:
            with data_lock:
                teams = state['all_teams_data'].get(league, [])
                for t in teams:
                    if t['abbr'] == search_abbr:
                        return {'color': t.get('color', '000000'), 'alt_color': t.get('alt_color', '444444')}
        except: pass
        return {'color': '000000', 'alt_color': '444444'}

    def calculate_game_timing(self, sport, start_utc, period, status_detail):
        duration = SPORT_DURATIONS.get(sport, 180) 
        ot_padding = 0
        if 'OT' in str(status_detail) or 'S/O' in str(status_detail):
            if sport in ['nba', 'nfl', 'ncf_fbs', 'ncf_fcs']:
                ot_count = 1
                if '2OT' in status_detail: ot_count = 2
                elif '3OT' in status_detail: ot_count = 3
                ot_padding = ot_count * 20
            elif sport == 'nhl':
                ot_padding = 20
            elif sport == 'mlb' and period > 9:
                ot_padding = (period - 9) * 20
        return duration + ot_padding

    def fetch_all_teams(self):
        # (Keep existing implementation)
        pass 

    def _fetch_simple_league(self, league_key, catalog):
        # (Keep existing implementation)
        pass
        
    def _fetch_nhl_native(self, games_list, target_date_str):
        # (Keep existing implementation)
        pass

    # === NEW GOLF FETCH LOGIC ===
    def _fetch_golf(self, games_list):
        if not state['active_sports'].get('golf', False): return
        
        try:
            r = requests.get(f"{self.base_url}golf/pga/scoreboard", headers=HEADERS, timeout=5)
            data = r.json()
            
            for event in data.get('events', []):
                # Golf "Game" Object
                status = event.get('status', {}).get('type', {}).get('shortDetail', 'TBD')
                state_code = event.get('status', {}).get('type', {}).get('state', '')
                
                # Check if active or recently finished
                if state_code not in ['in', 'post']: continue

                tourney_name = event.get('shortName', 'PGA Tour')
                
                leaders = []
                # Parse Competitors (Leaderboard)
                comps = event.get('competitions', [{}])[0].get('competitors', [])
                
                # Sort by order (rank) and take top 4
                sorted_comps = sorted(comps, key=lambda x: int(x.get('curPosition', 999) if str(x.get('curPosition',999)).isdigit() else 999))
                
                for c in sorted_comps[:4]: # Get Top 4
                    athlete = c.get('athlete', {})
                    score = c.get('score', {}).get('displayValue', 'E')
                    rank = c.get('curPosition', '-')
                    name = athlete.get('displayName', 'Unknown')
                    # Shorten names (Scheffler -> Scheffler)
                    last_name = athlete.get('lastName', name)
                    
                    leaders.append({
                        'rank': rank,
                        'name': last_name,
                        'score': score
                    })

                if leaders:
                    games_list.append({
                        'sport': 'golf',
                        'id': event['id'],
                        'status': status,
                        'state': state_code,
                        'is_shown': True,
                        # Specific fields for Golf UI
                        'tourney_name': tourney_name,
                        'leaders': leaders,
                        'home_abbr': 'PGA', 'away_abbr': 'GOLF', # Dummies for filters
                        'home_score': '', 'away_score': '',
                        'home_logo': '', 'away_logo': '',
                        'home_color': '#005500', 'away_color': '#FFFFFF'
                    })
        except: pass

    def get_real_games(self):
        games = []
        with data_lock: conf = state.copy()
        utc_offset = conf.get('utc_offset', -4)

        if conf['active_sports'].get('clock'):
            with data_lock: state['current_games'] = [{'sport':'clock','id':'clk','is_shown':True}]; return
        if conf['active_sports'].get('weather'):
            if conf['weather_location'] != self.weather.location_name: self.weather.update_coords(conf['weather_location'])
            w = self.weather.get_weather()
            if w: 
                with data_lock: state['current_games'] = [w]; return

        # 1. Fetch Golf (Special case)
        self._fetch_golf(games)

        # 2. Fetch Team Sports
        req_params = {}
        now_local = dt.now(timezone(timedelta(hours=utc_offset)))
        if conf['debug_mode'] and conf['custom_date']:
            target_date_str = conf['custom_date']
        else:
            # Logic: If it's 3AM, get yesterday's late games too. 
            if now_local.hour < 4: query_date = now_local - timedelta(days=1)
            else: query_date = now_local
            target_date_str = query_date.strftime("%Y-%m-%d")

        req_params['dates'] = target_date_str.replace('-', '')

        for league_key, config in self.leagues.items():
            if not conf['active_sports'].get(league_key, False): continue
            
            # Hybrid NHL
            if league_key == 'nhl' and not conf['debug_mode']:
                prev_count = len(games)
                self._fetch_nhl_native(games, target_date_str)
                if len(games) > prev_count: continue 

            try:
                curr_p = config['scoreboard_params'].copy(); curr_p.update(req_params)
                r = requests.get(f"{self.base_url}{config['path']}/scoreboard", params=curr_p, headers=HEADERS, timeout=5)
                data = r.json()
                
                for e in data.get('events', []):
                    utc_str = e['date'].replace('Z', '') 
                    utc_start_iso = e['date']
                    
                    game_dt_utc = dt.fromisoformat(utc_str).replace(tzinfo=timezone.utc)
                    game_dt_server = game_dt_utc.astimezone(timezone(timedelta(hours=utc_offset)))
                    game_date_str = game_dt_server.strftime("%Y-%m-%d")
                    
                    st = e.get('status', {}); tp = st.get('type', {}); gst = tp.get('state', 'pre')
                    
                    keep_date = (gst == 'in') or (game_date_str == target_date_str)
                    if league_key == 'mlb' and not keep_date: continue
                    if not keep_date: continue

                    comp = e['competitions'][0]; h = comp['competitors'][0]; a = comp['competitors'][1]
                    h_ab = h['team']['abbreviation']; a_ab = a['team']['abbreviation']
                    
                    # College filters
                    if league_key == 'ncf_fbs':
                        if h_ab not in FBS_TEAMS and a_ab not in FBS_TEAMS: continue
                    elif league_key == 'ncf_fcs':
                        if h_ab not in FCS_TEAMS and a_ab not in FCS_TEAMS: continue

                    is_shown = True
                    if conf['mode'] == 'live' and gst not in ['in', 'half']: is_shown = False
                    elif conf['mode'] == 'my_teams':
                        hk = f"{league_key}:{h_ab}"; ak = f"{league_key}:{a_ab}"
                        if (hk not in conf['my_teams'] and h_ab not in conf['my_teams']) and \
                           (ak not in conf['my_teams'] and a_ab not in conf['my_teams']): is_shown = False

                    h_lg = self.get_corrected_logo(league_key, h_ab, h['team'].get('logo',''))
                    a_lg = self.get_corrected_logo(league_key, a_ab, a['team'].get('logo',''))

                    h_clr = h['team'].get('color', '000000')
                    h_alt = h['team'].get('alternateColor', 'ffffff')
                    a_clr = a['team'].get('color', '000000')
                    a_alt = a['team'].get('alternateColor', 'ffffff')

                    s_disp = tp.get('shortDetail', 'TBD')
                    p = st.get('period', 1)
                    
                    dur = self.calculate_game_timing(league_key, utc_start_iso, p, s_disp)

                    if gst == 'pre':
                        try:
                            s_disp = game_dt_server.strftime("%I:%M %p").lstrip('0')
                        except: s_disp = "Scheduled"
                    elif gst == 'in' or gst == 'half':
                        clk = st.get('displayClock', '')
                        if gst == 'half' or (p == 2 and clk == '0:00' and 'football' in config['path']):
                            s_disp = "Halftime"
                            is_halftime = True
                        elif 'hockey' in config['path'] and clk == '0:00':
                             # (NHL Logic omitted for brevity, same as before)
                             s_disp = "Intermission"
                        elif 'soccer' in league_key:
                            s_disp = f"{clk}'" # 45'
                        else:
                            s_disp = f"P{p} {clk}" if 'hockey' in config['path'] else f"Q{p} {clk}"
                    else:
                        s_disp = s_disp.replace("Final", "FINAL").replace("/OT", " OT").replace("/SO", " S/O").replace("Full Time", "FT")

                    sit = comp.get('situation', {})
                    is_halftime = (s_disp == "Halftime")

                    curr_poss = sit.get('possession')
                    if curr_poss: self.possession_cache[e['id']] = curr_poss
                    
                    if gst == 'pre': curr_poss = '' 
                    elif is_halftime or gst in ['post', 'final']:
                         curr_poss = '' 
                         self.possession_cache[e['id']] = '' 
                    else:
                         if not curr_poss: curr_poss = self.possession_cache.get(e['id'], '')
                    
                    game_obj = {
                        'sport': league_key, 'id': e['id'], 'status': s_disp, 'state': gst, 'is_shown': is_shown,
                        'home_abbr': h_ab, 'home_score': h.get('score','0'), 'home_logo': h_lg,
                        'home_id': h.get('id'), 
                        'away_abbr': a_ab, 'away_score': a.get('score','0'), 'away_logo': a_lg,
                        'away_id': a.get('id'), 
                        'home_color': f"#{h_clr}", 'home_alt_color': f"#{h_alt}",
                        'away_color': f"#{a_clr}", 'away_alt_color': f"#{a_alt}",
                        'startTimeUTC': utc_start_iso, 
                        'estimated_duration': dur,
                        'period': p,
                        'situation': { 
                            'possession': curr_poss, 
                            'isRedZone': sit.get('isRedZone', False), 
                            'downDist': sit.get('downDistanceText', '') 
                        }
                    }
                    games.append(game_obj)
            except: pass
        
        with data_lock: state['current_games'] = games

fetcher = SportsFetcher(state['weather_location'])

def background_updater():
    fetcher.fetch_all_teams()
    while True: fetcher.get_real_games(); time.sleep(UPDATE_INTERVAL)

# ================= FLASK API =================
app = Flask(__name__)

@app.route('/')
def root():
    # Update HTML to include checkboxes for Soccer and Golf
    html = """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Game Schedule</title>
        <style>
             body { font-family: sans-serif; background: #121212; color: white; padding: 20px; }
             .toggle-row { display: flex; justify-content: space-between; margin-bottom: 10px; }
             input[type="text"] { width: 100%; padding: 8px; margin-bottom: 20px; }
             button { width: 100%; padding: 10px; background: #007bff; color: white; border: none; }
        </style>
    </head>
    <body>
        <h2>Settings</h2>
        
        <h3>My Teams</h3>
        <input type="text" id="inp_teams" placeholder="NYG, NYY...">

        <h3>Leagues</h3>
        <div class="toggle-row"><span>NFL</span><input type="checkbox" id="chk_nfl"></div>
        <div class="toggle-row"><span>NBA</span><input type="checkbox" id="chk_nba"></div>
        <div class="toggle-row"><span>NHL</span><input type="checkbox" id="chk_nhl"></div>
        <div class="toggle-row"><span>MLB</span><input type="checkbox" id="chk_mlb"></div>
        <div class="toggle-row"><span>EPL (Soccer)</span><input type="checkbox" id="chk_soccer_epl"></div>
        <div class="toggle-row"><span>MLS (Soccer)</span><input type="checkbox" id="chk_soccer_mls"></div>
        <div class="toggle-row"><span>PGA (Golf)</span><input type="checkbox" id="chk_golf"></div>
        <div class="toggle-row"><span>NCAA FBS</span><input type="checkbox" id="chk_ncf_fbs"></div>
        
        <h3>Device</h3>
        <div class="toggle-row"><span>Speed (1-10)</span><input type="number" id="inp_speed" min="1" max="10"></div>
        
        <button onclick="saveSettings()">Save</button>

        <script>
            async function loadState() {
                const res = await fetch('/api/state');
                const data = await res.json();
                const s = data.settings;
                document.getElementById('inp_teams').value = (s.my_teams || []).join(', ');
                document.getElementById('chk_nfl').checked = s.active_sports.nfl;
                document.getElementById('chk_nba').checked = s.active_sports.nba;
                document.getElementById('chk_nhl').checked = s.active_sports.nhl;
                document.getElementById('chk_mlb').checked = s.active_sports.mlb;
                document.getElementById('chk_soccer_epl').checked = s.active_sports.soccer_epl;
                document.getElementById('chk_soccer_mls').checked = s.active_sports.soccer_mls;
                document.getElementById('chk_golf').checked = s.active_sports.golf;
                document.getElementById('chk_ncf_fbs').checked = s.active_sports.ncf_fbs;
                document.getElementById('inp_speed').value = s.scroll_speed;
            }

            async function saveSettings() {
                const payload = {
                    active_sports: {
                        nfl: document.getElementById('chk_nfl').checked,
                        nba: document.getElementById('chk_nba').checked,
                        nhl: document.getElementById('chk_nhl').checked,
                        mlb: document.getElementById('chk_mlb').checked,
                        soccer_epl: document.getElementById('chk_soccer_epl').checked,
                        soccer_mls: document.getElementById('chk_soccer_mls').checked,
                        golf: document.getElementById('chk_golf').checked,
                        ncf_fbs: document.getElementById('chk_ncf_fbs').checked,
                        weather: false, clock: false
                    },
                    my_teams: document.getElementById('inp_teams').value.split(',').map(s=>s.trim()).filter(s=>s),
                    scroll_speed: parseInt(document.getElementById('inp_speed').value)
                };
                await fetch('/api/config', { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(payload) });
                alert('Saved!');
            }
            loadState();
        </script>
    </body>
    </html>
    """
    return render_template_string(html)

@app.route('/api/ticker')
def api_ticker():
    with data_lock: d = state.copy()
    offset_sec = d.get('utc_offset', -4) * 3600
    
    raw_games = d['current_games']
    processed_games = []
    
    for g in raw_games:
        if not g.get('is_shown', True): continue
        processed_games.append(g.copy())

    return jsonify({
        'meta': {
            'time': dt.now(timezone(timedelta(seconds=offset_sec))).strftime("%I:%M %p"), 
            'count': len(processed_games), 
            'scroll_seamless': d['scroll_seamless'], 
            'brightness': d['brightness'], 
            'scroll_speed': d.get('scroll_speed', 5), 
            'inverted': d['inverted'], 
            'panel_count': d['panel_count'], 
            'test_pattern': d['test_pattern'], 
            'reboot_requested': d['reboot_requested'],
            'utc_offset_seconds': offset_sec 
        }, 
        'games': processed_games
    })

# ... (Keep existing /api/state, /api/teams, /api/config, /api/debug, /api/hardware routes) ...
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

if __name__ == "__main__":
    threading.Thread(target=background_updater, daemon=True).start()
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 5000)))
