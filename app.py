import time
import threading
import json
import os
import sys
import re
import random
import string
from datetime import datetime as dt, timezone, timedelta
import requests
from flask import Flask, jsonify, request, render_template_string
from flask_cors import CORS

# ================= LOGGING SETUP =================
class Tee(object):
    def __init__(self, name, mode):
        self.file = open(name, mode)
        self.stdout = sys.stdout
        self.stdout = self
        self.stderr = self
    def write(self, data):
        self.file.write(data)
        self.stdout.write(data)
        self.file.flush()
        self.stdout.flush()
    def flush(self):
        self.file.flush()
        self.stdout.flush()

try:
    if not os.path.exists("ticker.log"):
        with open("ticker.log", "w") as f: f.write("--- Log Started ---\n")
    Tee("ticker.log", "a")
except Exception as e:
    print(f"Logging setup failed: {e}")

# ================= CONFIGURATION =================
CONFIG_FILE = "ticker_config.json"
TICKER_REGISTRY_FILE = "tickers.json" 
UPDATE_INTERVAL = 5 
data_lock = threading.Lock()

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
    "Cache-Control": "no-cache"
}

# ================= DEFAULT STATE =================
default_state = {
    'active_sports': { 
        'nfl': True, 'ncf_fbs': True, 'ncf_fcs': True, 'mlb': True, 'nhl': True, 'nba': True, 
        'soccer_epl': True,         # Premier League
        'soccer_champ': False,      # EFL Championship
        'soccer_l1': False,         # EFL League One
        'soccer_l2': False,         # EFL League Two
        'soccer_wc': False,         # FIFA World Cup
        'hockey_olympics': False,   # Olympic Hockey
        'f1': True, 'nascar': True, 'indycar': True, 'wec': False, 'imsa': False,
        'weather': False, 'clock': False 
    },
    'mode': 'all', 
    'layout_mode': 'schedule',
    'my_teams': [], 
    'current_games': [],
    'all_teams_data': {}, 
    'debug_mode': False,
    'demo_mode': False,
    'custom_date': None,
    'weather_location': "New York",
    'utc_offset': -5,
    'scroll_seamless': True, 
    'scroll_speed': 5,
    'brightness': 100,
    'show_debug_options': True 
}

DEFAULT_TICKER_SETTINGS = {
    "brightness": 100,
    "scroll_speed": 0.03,
    "scroll_seamless": True,
    "inverted": False,
    "panel_count": 2
}

state = default_state.copy()
tickers = {} 

# --- LOAD CONFIG ---
if os.path.exists(CONFIG_FILE):
    try:
        with open(CONFIG_FILE, 'r') as f:
            loaded = json.load(f)
            for k, v in loaded.items():
                if k == 'show_debug_options': continue 
                if k in state:
                    if isinstance(state[k], dict) and isinstance(v, dict): state[k].update(v)
                    else: state[k] = v
    except Exception as e:
        print(f"Error loading config: {e}")

# --- LOAD TICKERS ---
if os.path.exists(TICKER_REGISTRY_FILE):
    try:
        with open(TICKER_REGISTRY_FILE, 'r') as f:
            tickers = json.load(f)
            print(f"Loaded {len(tickers)} paired tickers.")
    except Exception as e:
        print(f"Error loading tickers: {e}")

def save_json_atomically(filepath, data):
    temp = f"{filepath}.tmp"
    try:
        with open(temp, 'w') as f:
            json.dump(data, f, indent=4)
        os.replace(temp, filepath)
    except Exception as e:
        print(f"Failed to save {filepath}: {e}")

def save_config_file():
    try:
        with data_lock:
            export_data = {
                'active_sports': state['active_sports'], 
                'mode': state['mode'], 
                'layout_mode': state['layout_mode'],
                'my_teams': state['my_teams'],
                'weather_location': state['weather_location'],
                'utc_offset': state['utc_offset'],
                'demo_mode': state.get('demo_mode', False),
                'scroll_seamless': state.get('scroll_seamless', True),
                'show_debug_options': state.get('show_debug_options', True)
            }
            tickers_snap = tickers.copy()
        
        save_json_atomically(CONFIG_FILE, export_data)
        save_json_atomically(TICKER_REGISTRY_FILE, tickers_snap)
    except Exception as e:
        print(f"Save error: {e}")

def generate_pairing_code():
    while True:
        code = ''.join(random.choices(string.digits, k=6))
        active_codes = [t.get('pairing_code') for t in tickers.values() if not t.get('paired')]
        if code not in active_codes:
            return code

# ================= TEAMS & LOGOS =================
# HARDCODED LISTS
FBS_TEAMS = ["AF", "AKR", "ALA", "APP", "ARIZ", "ASU", "ARK", "ARST", "ARMY", "AUB", "BALL", "BAY", "BOIS", "BC", "BGSU", "BUF", "BYU", "CAL", "CMU", "CLT", "CIN", "CLEM", "CCU", "COLO", "CSU", "CONN", "DEL", "DUKE", "ECU", "EMU", "FAU", "FIU", "FLA", "FSU", "FRES", "GASO", "GAST", "GT", "UGA", "HAW", "HOU", "ILL", "IND", "IOWA", "ISU", "JXST", "JMU", "KAN", "KSU", "KENN", "KENT", "UK", "LIB", "ULL", "LT", "LOU", "LSU", "MAR", "MD", "MASS", "MEM", "MIA", "M-OH", "MICH", "MSU", "MTSU", "MINN", "MSST", "MIZ", "MOST", "NAVY", "NCST", "NEB", "NEV", "UNM", "NMSU", "UNC", "UNT", "NIU", "NU", "ND", "OHIO", "OSU", "OU", "OKST", "ODU", "MISS", "ORE", "ORST", "PSU", "PITT", "PUR", "RICE", "RUTG", "SAM", "SDSU", "SJSU", "SMU", "USA", "SC", "USF", "USM", "STAN", "SYR", "TCU", "TEM", "TENN", "TEX", "TA&M", "TXST", "TTU", "TOL", "TROY", "TULN", "TLSA", "UAB", "UCF", "UCLA", "ULM", "UMASS", "UNLV", "USC", "UTAH", "USU", "UTEP", "UTSA", "VAN", "UVA", "VT", "WAKE", "WASH", "WSU", "WVU", "WKU", "WMU", "WIS", "WYO"]
FCS_TEAMS = ["ACU", "AAMU", "ALST", "UALB", "ALCN", "UAPB", "APSU", "BCU", "BRWN", "BRY", "BUCK", "BUT", "CP", "CAM", "CARK", "CCSU", "CHSO", "UTC", "CIT", "COLG", "COLU", "COR", "DART", "DAV", "DAY", "DSU", "DRKE", "DUQ", "EIU", "EKU", "ETAM", "EWU", "ETSU", "ELON", "FAMU", "FOR", "FUR", "GWEB", "GTWN", "GRAM", "HAMP", "HARV", "HC", "HCU", "HOW", "IDHO", "IDST", "ILST", "UIW", "INST", "JKST", "LAF", "LAM", "LEH", "LIN", "LIU", "ME", "MRST", "MCN", "MER", "MERC", "MRMK", "MVSU", "MONM", "MONT", "MTST", "MORE", "MORG", "MUR", "UNH", "NHVN", "NICH", "NORF", "UNA", "NCAT", "NCCU", "UND", "NDSU", "NAU", "UNCO", "UNI", "NWST", "PENN", "PRST", "PV", "PRES", "PRIN", "URI", "RICH", "RMU", "SAC", "SHU", "SFPA", "SAM", "USD", "SELA", "SEMO", "SDAK", "SDST", "SCST", "SOU", "SIU", "SUU", "STMN", "SFA", "STET", "STO", "STBK", "TAR", "TNST", "TNTC", "TXSO", "TOW", "UCD", "UTM", "UTM", "UTRGV", "VAL", "VILL", "VMI", "WAG", "WEB", "WGA", "WCU", "WIU", "W&M", "WOF", "YALE", "YSU"]

# OLYMPIC HOCKEY (Manual to ensure they appear)
OLYMPIC_HOCKEY_TEAMS = [
    {"abbr": "CAN", "logo": "https://a.espncdn.com/i/teamlogos/countries/500/can.png", "color": "FF0000", "alt_color": "000000"},
    {"abbr": "USA", "logo": "https://a.espncdn.com/i/teamlogos/countries/500/usa.png", "color": "002868", "alt_color": "BF0A30"},
    {"abbr": "SWE", "logo": "https://a.espncdn.com/i/teamlogos/countries/500/swe.png", "color": "FECC00", "alt_color": "006AA7"},
    {"abbr": "FIN", "logo": "https://a.espncdn.com/i/teamlogos/countries/500/fin.png", "color": "003580", "alt_color": "FFFFFF"},
    {"abbr": "RUS", "logo": "https://a.espncdn.com/i/teamlogos/countries/500/rus.png", "color": "D52B1E", "alt_color": "0039A6"},
    {"abbr": "CZE", "logo": "https://a.espncdn.com/i/teamlogos/countries/500/cze.png", "color": "D7141A", "alt_color": "11457E"},
    {"abbr": "GER", "logo": "https://a.espncdn.com/i/teamlogos/countries/500/ger.png", "color": "FFCE00", "alt_color": "000000"},
    {"abbr": "SUI", "logo": "https://a.espncdn.com/i/teamlogos/countries/500/sui.png", "color": "D52B1E", "alt_color": "FFFFFF"},
    {"abbr": "SVK", "logo": "https://a.espncdn.com/i/teamlogos/countries/500/svk.png", "color": "0B4EA2", "alt_color": "EE1C25"},
    {"abbr": "LAT", "logo": "https://a.espncdn.com/i/teamlogos/countries/500/lat.png", "color": "9E3039", "alt_color": "FFFFFF"},
    {"abbr": "DEN", "logo": "https://a.espncdn.com/i/teamlogos/countries/500/den.png", "color": "C60C30", "alt_color": "FFFFFF"},
    {"abbr": "CHN", "logo": "https://a.espncdn.com/i/teamlogos/countries/500/chn.png", "color": "EE1C25", "alt_color": "FFFF00"}
]

LOGO_OVERRIDES = {
    "NFL:HOU": "https://a.espncdn.com/i/teamlogos/nfl/500/hou.png", 
    "NFL:WAS": "https://a.espncdn.com/i/teamlogos/nfl/500/wsh.png",
    "MLB:WAS": "https://a.espncdn.com/i/teamlogos/mlb/500/wsh.png",
    "NHL:UTA": "https://a.espncdn.com/i/teamlogos/nhl/500/utah.png",
    "NCF_FBS:WASH": "https://a.espncdn.com/i/teamlogos/ncaa/500/264.png"
}

SPORT_DURATIONS = {
    'nfl': 195, 'ncf_fbs': 210, 'ncf_fcs': 195,
    'nba': 150, 'nhl': 150, 'mlb': 180, 'weather': 60, 
    'soccer_epl': 115, 'soccer_champ': 115, 'soccer_l1': 115, 'soccer_l2': 115, 
    'soccer_wc': 130, 'hockey_olympics': 150
}

# === DEMO DATA GENERATOR ===
def generate_demo_data():
    return [
        {
            'type': 'scoreboard', 'sport': 'nhl', 'id': 'demo_so', 'status': 'S/O', 'state': 'in', 'is_shown': True,
            'home_abbr': 'NYR', 'home_score': '3', 'home_logo': 'https://a.espncdn.com/i/teamlogos/nhl/500/nyr.png', 'home_color': '#0038A8', 'home_alt_color': '#CE1126',
            'away_abbr': 'NJD', 'away_score': '3', 'away_logo': 'https://a.espncdn.com/i/teamlogos/nhl/500/nj.png', 'away_color': '#CE1126', 'away_alt_color': '#000000',
            'startTimeUTC': dt.now(timezone.utc).isoformat(), 'estimated_duration': 150,
            'situation': {
                'shootout': { 'away': ['goal', 'miss', 'miss'], 'home': ['miss', 'goal', 'pending'] }
            }
        },
        {
            'type': 'scoreboard', 'sport': 'soccer_wc', 'id': 'demo_wc_pens', 'status': 'Pens', 'state': 'in', 'is_shown': True,
            'home_abbr': 'ARG', 'home_score': '3', 'home_logo': 'https://a.espncdn.com/i/teamlogos/soccer/500/202.png', 'home_color': '#75AADB', 'home_alt_color': '#FFFFFF',
            'away_abbr': 'FRA', 'away_score': '3', 'away_logo': 'https://a.espncdn.com/i/teamlogos/soccer/500/478.png', 'away_color': '#002395', 'away_alt_color': '#ED2939',
            'startTimeUTC': dt.now(timezone.utc).isoformat(), 'estimated_duration': 140,
            'situation': { 
                'shootout': { 'away': ['goal', 'miss', 'goal', 'miss'], 'home': ['goal', 'goal', 'goal', 'goal'] },
                'possession': '' 
            },
            'tourney_name': 'Final'
        }
    ]

# ================= FETCHING LOGIC =================

class WeatherFetcher:
    def __init__(self, initial_loc):
        self.lat = 40.7128; self.lon = -74.0060; self.location_name = "New York"
        self.last_fetch = 0; self.cache = None
        if initial_loc: self.update_coords(initial_loc)

    def update_coords(self, location_query):
        try:
            r = requests.get(f"https://geocoding-api.open-meteo.com/v1/search?name={str(location_query).strip()}&count=1&language=en&format=json", timeout=5)
            d = r.json()
            if 'results' in d and len(d['results']) > 0:
                res = d['results'][0]
                self.lat = res['latitude']; self.lon = res['longitude']
                self.location_name = res['name']; self.last_fetch = 0 
        except: pass

    def get_weather(self):
        if time.time() - self.last_fetch < 900 and self.cache: return self.cache
        try:
            r = requests.get(f"https://api.open-meteo.com/v1/forecast?latitude={self.lat}&longitude={self.lon}&current=temperature_2m,weather_code,is_day&daily=temperature_2m_max,temperature_2m_min,uv_index_max&temperature_unit=fahrenheit&timezone=auto", timeout=5)
            d = r.json()
            c = d.get('current', {}); dl = d.get('daily', {})
            high = int(dl['temperature_2m_max'][0]); low = int(dl['temperature_2m_min'][0]); uv = float(dl['uv_index_max'][0])
            
            code = c.get('weather_code', 0); is_day = c.get('is_day', 1)
            icon = "cloud"
            if code in [0, 1]: icon = "sun" if is_day else "moon"
            elif code in [51, 53, 55, 61, 63, 65, 80, 81, 82]: icon = "rain"
            elif code in [71, 73, 75, 77, 85, 86]: icon = "snow"
            elif code in [95, 96, 99]: icon = "storm"

            w_obj = {
                "type": "weather", "sport": "weather", "id": "weather_widget", "status": "Live",
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
            'nfl': { 'path': 'football/nfl', 'team_params': {'limit': 100}, 'type': 'scoreboard' },
            'mlb': { 'path': 'baseball/mlb', 'team_params': {'limit': 100}, 'type': 'scoreboard' },
            'nhl': { 'path': 'hockey/nhl', 'team_params': {'limit': 100}, 'type': 'scoreboard' },
            'nba': { 'path': 'basketball/nba', 'team_params': {'limit': 100}, 'type': 'scoreboard' },
            
            # SOCCER LEAGUES (Dynamic Fetch)
            'soccer_epl':   { 'path': 'soccer/eng.1', 'team_params': {'limit': 50}, 'type': 'scoreboard' },
            'soccer_champ': { 'path': 'soccer/eng.2', 'team_params': {'limit': 50}, 'type': 'scoreboard' },
            'soccer_l1':    { 'path': 'soccer/eng.3', 'team_params': {'limit': 50}, 'type': 'scoreboard' },
            'soccer_l2':    { 'path': 'soccer/eng.4', 'team_params': {'limit': 50}, 'type': 'scoreboard' },
            'soccer_wc':    { 'path': 'soccer/fifa.world', 'team_params': {'limit': 100}, 'type': 'scoreboard' },
            
            # COLLEGE (Config only for scoreboard, teams handled manually below)
            'ncf_fbs': { 'path': 'football/college-football', 'scoreboard_params': {'groups': '80'}, 'type': 'scoreboard' },
            'ncf_fcs': { 'path': 'football/college-football', 'scoreboard_params': {'groups': '81'}, 'type': 'scoreboard' },
            
            # OLYMPIC HOCKEY (Config only for scoreboard, teams handled manually)
            'hockey_olympics': { 'path': 'hockey/mens-olympic-hockey', 'type': 'scoreboard' },
            
            'f1': { 'path': 'racing/f1', 'type': 'leaderboard' },
            'nascar': { 'path': 'racing/nascar', 'type': 'leaderboard' },
            'indycar': { 'path': 'racing/indycar', 'type': 'leaderboard' },
            'wec': { 'path': 'racing/wec', 'type': 'leaderboard' },
            'imsa': { 'path': 'racing/imsa', 'type': 'leaderboard' }
        }

    def get_corrected_logo(self, league_key, abbr, default_logo):
        return LOGO_OVERRIDES.get(f"{league_key.upper()}:{abbr}", default_logo)

    def _fetch_simple_league(self, league_key, catalog):
        config = self.leagues[league_key]
        if 'team_params' not in config: return
        try:
            r = requests.get(f"{self.base_url}{config['path']}/teams", params=config['team_params'], headers=HEADERS, timeout=10)
            data = r.json()
            if 'sports' in data:
                for sport in data['sports']:
                    for league in sport['leagues']:
                        for item in league.get('teams', []):
                            abbr = item['team'].get('abbreviation', 'unk')
                            clr = item['team'].get('color', '000000')
                            alt = item['team'].get('alternateColor', '444444')
                            logo = item['team'].get('logos', [{}])[0].get('href', '')
                            logo = self.get_corrected_logo(league_key, abbr, logo)
                            if not any(x['abbr'] == abbr for x in catalog[league_key]):
                                catalog[league_key].append({'abbr': abbr, 'logo': logo, 'color': clr, 'alt_color': alt})
        except: pass

    def fetch_all_teams(self):
        """Builds team catalog."""
        try:
            teams_catalog = {k: [] for k in self.leagues.keys()}
            print("Starting Team Fetch...")
            
            # 1. HARDCODE OLYMPIC HOCKEY
            for t in OLYMPIC_HOCKEY_TEAMS:
                teams_catalog['hockey_olympics'].append(t)

            # 2. FETCH COLLEGE FOOTBALL (Logic from old code: Fetch Raw -> Filter)
            # This is the logic you requested be restored.
            url = f"{self.base_url}football/college-football/teams"
            r = requests.get(url, params={'limit': 1000, 'groups': '80,81'}, headers=HEADERS, timeout=10) 
            data = r.json()
            if 'sports' in data:
                for sport in data['sports']:
                    for league in sport['leagues']:
                        for item in league.get('teams', []):
                            t_abbr = item['team'].get('abbreviation', 'unk')
                            t_clr = item['team'].get('color', '000000')
                            t_alt = item['team'].get('alternateColor', '444444')
                            logos = item['team'].get('logos', [])
                            t_logo = logos[0].get('href', '') if len(logos) > 0 else ''
                            
                            league_tag = 'ncf_fbs' if t_abbr in FBS_TEAMS else 'ncf_fcs'
                            t_logo = self.get_corrected_logo(league_tag, t_abbr, t_logo)
                            
                            team_obj = {'abbr': t_abbr, 'logo': t_logo, 'color': t_clr, 'alt_color': t_alt}
                            
                            if t_abbr in FBS_TEAMS:
                                if not any(x['abbr'] == t_abbr for x in teams_catalog['ncf_fbs']):
                                    teams_catalog['ncf_fbs'].append(team_obj)
                            elif t_abbr in FCS_TEAMS:
                                if not any(x['abbr'] == t_abbr for x in teams_catalog['ncf_fcs']):
                                    teams_catalog['ncf_fcs'].append(team_obj)

            # 3. FETCH PRO LEAGUES & SOCCER (Dynamic)
            for league_key in ['nfl', 'mlb', 'nhl', 'nba', 'soccer_epl', 'soccer_champ', 'soccer_l1', 'soccer_l2', 'soccer_wc']:
                 self._fetch_simple_league(league_key, teams_catalog)

            with data_lock:
                state['all_teams_data'] = teams_catalog
                print(f"Teams Loaded. NFL: {len(teams_catalog['nfl'])}, FBS: {len(teams_catalog['ncf_fbs'])}, OLY: {len(teams_catalog['hockey_olympics'])}")
        except Exception as e: print(f"Global Team Fetch Error: {e}")

    def fetch_shootout_details(self, game_id, sport='nhl'):
        try:
            path_part = "hockey/nhl" if sport == 'nhl' else "soccer/eng.1"
            if 'soccer' in sport: path_part = f"soccer/{sport.replace('soccer_','')}"
            if sport == 'hockey_olympics': path_part = "hockey/mens-olympic-hockey"

            url = f"https://site.api.espn.com/apis/site/v2/sports/{path_part}/summary?event={game_id}"
            r = requests.get(url, headers=HEADERS, timeout=3)
            if r.status_code != 200: return None
            data = r.json()
            
            results = {'away': [], 'home': []}
            
            if 'hockey' in sport:
                plays = data.get("shootout", [])
                if not plays: return None
                for p in plays:
                    res = "goal" if p.get("result") == "made" else "miss"
                    if p.get("homeAway") == "home": results['home'].append(res)
                    else: results['away'].append(res)
            else:
                shootout_plays = data.get("shootout", [])
                if not shootout_plays: return None
                for p in shootout_plays:
                    is_goal = p.get("result") == "scored" or "Goal" in p.get("text", "")
                    res = "goal" if is_goal else "miss"
                    if p.get("homeAway") == "home": results['home'].append(res)
                    else: results['away'].append(res)

            return results
        except: return None

    def get_real_games(self):
        games = []
        with data_lock: 
            conf = state.copy()
            if conf.get('demo_mode', False):
                state['current_games'] = generate_demo_data()
                return

        utc_offset = conf.get('utc_offset', -4)
        now_local = dt.now(timezone(timedelta(hours=utc_offset)))
        target_date_str = conf['custom_date'] if (conf['debug_mode'] and conf['custom_date']) else now_local.strftime("%Y-%m-%d")
        
        if conf['active_sports'].get('weather'):
            if conf['weather_location'] != self.weather.location_name: self.weather.update_coords(conf['weather_location'])
            w = self.weather.get_weather()
            if w: games.append(w)
        
        if conf['active_sports'].get('clock'):
            games.append({'type':'clock','sport':'clock','id':'clk','is_shown':True})

        for league_key, config in self.leagues.items():
            if not conf['active_sports'].get(league_key, False): continue
            
            if config.get('type') == 'leaderboard':
                self.fetch_leaderboard_event(league_key, config, games, conf)
                continue

            try:
                curr_p = config.get('scoreboard_params', {}).copy()
                curr_p['dates'] = target_date_str.replace('-', '')
                r = requests.get(f"{self.base_url}{config['path']}/scoreboard", params=curr_p, headers=HEADERS, timeout=5)
                data = r.json()
                
                for e in data.get('events', []):
                    utc_str = e['date'].replace('Z', '')
                    st = e.get('status', {}); tp = st.get('type', {}); gst = tp.get('state', 'pre')
                    
                    game_date = dt.fromisoformat(utc_str).replace(tzinfo=timezone.utc).astimezone(timezone(timedelta(hours=utc_offset))).strftime("%Y-%m-%d")
                    if gst != 'in' and game_date != target_date_str: continue

                    comp = e['competitions'][0]; h = comp['competitors'][0]; a = comp['competitors'][1]
                    h_ab = h['team'].get('abbreviation', 'UNK'); a_ab = a['team'].get('abbreviation', 'UNK')
                    
                    if league_key == 'ncf_fbs' and h_ab not in FBS_TEAMS and a_ab not in FBS_TEAMS: continue
                    if league_key == 'ncf_fcs' and h_ab not in FCS_TEAMS and a_ab not in FCS_TEAMS: continue

                    is_shown = True
                    if conf['mode'] == 'live' and gst not in ['in', 'half']: is_shown = False
                    elif conf['mode'] == 'my_teams':
                        hk = f"{league_key}:{h_ab}"; ak = f"{league_key}:{a_ab}"
                        in_my = (hk in conf['my_teams'] or h_ab in conf['my_teams'] or ak in conf['my_teams'] or a_ab in conf['my_teams'])
                        if not in_my: is_shown = False

                    h_lg = self.get_corrected_logo(league_key, h_ab, h['team'].get('logo',''))
                    a_lg = self.get_corrected_logo(league_key, a_ab, a['team'].get('logo',''))
                    h_clr = h['team'].get('color', '000000'); h_alt = h['team'].get('alternateColor', 'ffffff')
                    a_clr = a['team'].get('color', '000000'); a_alt = a['team'].get('alternateColor', 'ffffff')

                    h_score = h.get('score','0')
                    a_score = a.get('score','0')
                    if 'soccer' in league_key:
                        h_score = re.sub(r'\s*\(.*?\)', '', h_score)
                        a_score = re.sub(r'\s*\(.*?\)', '', a_score)

                    s_disp = tp.get('shortDetail', 'TBD')
                    if gst == 'pre':
                        try: s_disp = dt.fromisoformat(utc_str).replace(tzinfo=timezone.utc).astimezone(timezone(timedelta(hours=utc_offset))).strftime("%I:%M %p").lstrip('0')
                        except: pass
                    elif 'soccer' in league_key and (gst == 'in' or gst == 'half'):
                        clk = st.get('displayClock', '0:00').replace("'", "")
                        s_disp = f"{clk}'"
                        if gst == 'half': s_disp = "Half"

                    sit = comp.get('situation', {})
                    shootout_data = None
                    is_shootout = "Shootout" in s_disp or "Penalties" in s_disp or (gst == 'in' and st.get('period', 1) > 4 and 'hockey' in league_key)
                    if is_shootout:
                        shootout_data = self.fetch_shootout_details(e['id'], league_key)
                    
                    poss = sit.get('possession', '')
                    if gst == 'pre' or gst == 'post' or 'soccer' in league_key: poss = ''

                    game_obj = {
                        'type': 'scoreboard', 'sport': league_key, 'id': e['id'], 
                        'status': s_disp, 'state': gst, 'is_shown': is_shown,
                        'home_abbr': h_ab, 'home_score': h_score, 'home_logo': h_lg,
                        'away_abbr': a_ab, 'away_score': a_score, 'away_logo': a_lg,
                        'home_color': f"#{h_clr}", 'home_alt_color': f"#{h_alt}",
                        'away_color': f"#{a_clr}", 'away_alt_color': f"#{a_alt}",
                        'startTimeUTC': e['date'],
                        'situation': { 
                            'possession': poss, 
                            'isRedZone': sit.get('isRedZone', False),
                            'shootout': shootout_data
                        }
                    }
                    games.append(game_obj)
            except Exception as e: print(f"Error fetching {league_key}: {e}")

        with data_lock: state['current_games'] = games

fetcher = SportsFetcher(state['weather_location'])

def background_updater():
    fetcher.fetch_all_teams()
    while True: fetcher.get_real_games(); time.sleep(UPDATE_INTERVAL)

# ================= FLASK API =================
app = Flask(__name__)
CORS(app) 

@app.route('/data', methods=['GET'])
def get_ticker_data():
    ticker_id = request.args.get('id')
    if not ticker_id: return jsonify({"error": "No ID"}), 400
    
    if ticker_id not in tickers:
        tickers[ticker_id] = { "paired": False, "clients": [], "settings": DEFAULT_TICKER_SETTINGS.copy(), "pairing_code": generate_pairing_code(), "last_seen": time.time(), "name": "New Ticker" }
        save_config_file()
    else: tickers[ticker_id]['last_seen'] = time.time()

    rec = tickers[ticker_id]
    if not rec.get('clients'): return jsonify({"status": "pairing", "code": rec['pairing_code']})

    with data_lock:
        games = [g for g in state['current_games'] if g['is_shown']]
        conf = { "active_sports": state['active_sports'], "mode": state['mode'], "weather": state['weather_location'] }
    
    return jsonify({ "status": "ok", "global_config": conf, "local_config": rec['settings'], "content": { "sports": games } })

@app.route('/pair', methods=['POST'])
def pair_ticker():
    cid = request.headers.get('X-Client-ID')
    code = request.json.get('code')
    friendly_name = request.json.get('name', 'My Ticker')
    
    if not cid or not code: return jsonify({"success": False, "message": "Missing info"}), 400
    
    for uid, rec in tickers.items():
        if rec.get('pairing_code') == code:
            if cid not in rec['clients']: rec['clients'].append(cid)
            rec['paired'] = True
            rec['name'] = friendly_name
            save_config_file()
            return jsonify({"success": True, "ticker_id": uid})
    return jsonify({"success": False, "message": "Invalid code"}), 404

@app.route('/pair/id', methods=['POST'])
def pair_ticker_by_id():
    cid = request.headers.get('X-Client-ID')
    tid = request.json.get('id')
    friendly_name = request.json.get('name', 'My Ticker')
    
    if not cid or not tid: return jsonify({"success": False, "message": "Missing info"}), 400
    
    if tid in tickers:
        if cid not in tickers[tid]['clients']: tickers[tid]['clients'].append(cid)
        tickers[tid]['paired'] = True
        tickers[tid]['name'] = friendly_name
        save_config_file()
        return jsonify({"success": True, "ticker_id": tid})
    return jsonify({"success": False, "message": "Ticker ID not found"}), 404

@app.route('/ticker/<tid>/unpair', methods=['POST'])
def unpair(tid):
    cid = request.headers.get('X-Client-ID')
    if tid in tickers and cid in tickers[tid]['clients']:
        tickers[tid]['clients'].remove(cid)
        if not tickers[tid]['clients']:
            tickers[tid]['paired'] = False
            tickers[tid]['pairing_code'] = generate_pairing_code()
        save_config_file()
    return jsonify({"success": True})

@app.route('/tickers', methods=['GET'])
def list_tickers():
    cid = request.headers.get('X-Client-ID')
    if not cid: return jsonify([])
    res = []
    for uid, rec in tickers.items():
        if cid in rec.get('clients', []):
            res.append({ 
                "id": uid, 
                "name": rec.get('name', 'Ticker'), 
                "settings": rec['settings'], 
                "last_seen": rec.get('last_seen', 0) 
            })
    return jsonify(res)

@app.route('/ticker/<tid>', methods=['POST'])
def update_settings(tid):
    if tid not in tickers: return jsonify({"error":"404"}), 404
    tickers[tid]['settings'].update(request.json)
    save_config_file()
    return jsonify({"success": True})

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
    return jsonify({"status": "ok"})

@app.route('/api/hardware', methods=['POST'])
def api_hardware():
    d = request.json
    if d.get('action') == 'reboot':
        with data_lock: state['reboot_requested'] = True
        threading.Timer(10, lambda: state.update({'reboot_requested': False})).start()
    return jsonify({"status": "ok"})

@app.route('/api/debug', methods=['POST'])
def api_debug():
    with data_lock: state.update(request.json)
    return jsonify({"status": "ok"})

@app.route('/')
def root():
    return "Ticker Server Running"

if __name__ == "__main__":
    threading.Thread(target=background_updater, daemon=True).start()
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 5000)))
