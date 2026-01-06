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
from flask import Flask, jsonify, request
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
        'soccer_epl': True, 'soccer_champ': False, 'soccer_l1': False, 'soccer_l2': False, 
        'soccer_wc': False, 'hockey_olympics': False, 
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

# ================= LISTS & OVERRIDES =================
FBS_TEAMS = ["AF", "AKR", "ALA", "APP", "ARIZ", "ASU", "ARK", "ARST", "ARMY", "AUB", "BALL", "BAY", "BOIS", "BC", "BGSU", "BUF", "BYU", "CAL", "CMU", "CLT", "CIN", "CLEM", "CCU", "COLO", "CSU", "CONN", "DEL", "DUKE", "ECU", "EMU", "FAU", "FIU", "FLA", "FSU", "FRES", "GASO", "GAST", "GT", "UGA", "HAW", "HOU", "ILL", "IND", "IOWA", "ISU", "JXST", "JMU", "KAN", "KSU", "KENN", "KENT", "UK", "LIB", "ULL", "LT", "LOU", "LSU", "MAR", "MD", "MASS", "MEM", "MIA", "M-OH", "MICH", "MSU", "MTSU", "MINN", "MSST", "MIZ", "MOST", "NAVY", "NCST", "NEB", "NEV", "UNM", "NMSU", "UNC", "UNT", "NIU", "NU", "ND", "OHIO", "OSU", "OU", "OKST", "ODU", "MISS", "ORE", "ORST", "PSU", "PITT", "PUR", "RICE", "RUTG", "SAM", "SDSU", "SJSU", "SMU", "USA", "SC", "USF", "USM", "STAN", "SYR", "TCU", "TEM", "TENN", "TEX", "TA&M", "TXST", "TTU", "TOL", "TROY", "TULN", "TLSA", "UAB", "UCF", "UCLA", "ULM", "UMASS", "UNLV", "USC", "UTAH", "USU", "UTEP", "UTSA", "VAN", "UVA", "VT", "WAKE", "WASH", "WSU", "WVU", "WKU", "WMU", "WIS", "WYO"]
FCS_TEAMS = ["ACU", "AAMU", "ALST", "UALB", "ALCN", "UAPB", "APSU", "BCU", "BRWN", "BRY", "BUCK", "BUT", "CP", "CAM", "CARK", "CCSU", "CHSO", "UTC", "CIT", "COLG", "COLU", "COR", "DART", "DAV", "DAY", "DSU", "DRKE", "DUQ", "EIU", "EKU", "ETAM", "EWU", "ETSU", "ELON", "FAMU", "FOR", "FUR", "GWEB", "GTWN", "GRAM", "HAMP", "HARV", "HC", "HCU", "HOW", "IDHO", "IDST", "ILST", "UIW", "INST", "JKST", "LAF", "LAM", "LEH", "LIN", "LIU", "ME", "MRST", "MCN", "MER", "MERC", "MRMK", "MVSU", "MONM", "MONT", "MTST", "MORE", "MORG", "MUR", "UNH", "NHVN", "NICH", "NORF", "UNA", "NCAT", "NCCU", "UND", "NDSU", "NAU", "UNCO", "UNI", "NWST", "PENN", "PRST", "PV", "PRES", "PRIN", "URI", "RICH", "RMU", "SAC", "SHU", "SFPA", "SAM", "USD", "SELA", "SEMO", "SDAK", "SDST", "SCST", "SOU", "SIU", "SUU", "STMN", "SFA", "STET", "STO", "STBK", "TAR", "TNST", "TNTC", "TXSO", "TOW", "UCD", "UTM", "UTM", "UTRGV", "VAL", "VILL", "VMI", "WAG", "WEB", "WGA", "WCU", "WIU", "W&M", "WOF", "YALE", "YSU"]
OLYMPIC_HOCKEY_TEAMS = [
    {"abbr": "CAN", "logo": "https://a.espncdn.com/i/teamlogos/countries/500/can.png"},
    {"abbr": "USA", "logo": "https://a.espncdn.com/i/teamlogos/countries/500/usa.png"},
    {"abbr": "SWE", "logo": "https://a.espncdn.com/i/teamlogos/countries/500/swe.png"},
    {"abbr": "FIN", "logo": "https://a.espncdn.com/i/teamlogos/countries/500/fin.png"},
    {"abbr": "RUS", "logo": "https://a.espncdn.com/i/teamlogos/countries/500/rus.png"},
    {"abbr": "CZE", "logo": "https://a.espncdn.com/i/teamlogos/countries/500/cze.png"},
    {"abbr": "GER", "logo": "https://a.espncdn.com/i/teamlogos/countries/500/ger.png"},
    {"abbr": "SUI", "logo": "https://a.espncdn.com/i/teamlogos/countries/500/sui.png"},
    {"abbr": "SVK", "logo": "https://a.espncdn.com/i/teamlogos/countries/500/svk.png"},
    {"abbr": "LAT", "logo": "https://a.espncdn.com/i/teamlogos/countries/500/lat.png"},
    {"abbr": "DEN", "logo": "https://a.espncdn.com/i/teamlogos/countries/500/den.png"},
    {"abbr": "CHN", "logo": "https://a.espncdn.com/i/teamlogos/countries/500/chn.png"}
]

LOGO_OVERRIDES = {
    "NFL:HOU": "https://a.espncdn.com/i/teamlogos/nfl/500/hou.png", "NBA:HOU": "https://a.espncdn.com/i/teamlogos/nba/500/hou.png", "MLB:HOU": "https://a.espncdn.com/i/teamlogos/mlb/500/hou.png", "NCF_FBS:HOU": "https://a.espncdn.com/i/teamlogos/ncaa/500/248.png",
    "NFL:MIA": "https://a.espncdn.com/i/teamlogos/nfl/500/mia.png", "NBA:MIA": "https://a.espncdn.com/i/teamlogos/nba/500/mia.png", "MLB:MIA": "https://a.espncdn.com/i/teamlogos/mlb/500/mia.png", "NCF_FBS:MIA": "https://a.espncdn.com/i/teamlogos/ncaa/500/2390.png", "NCF_FBS:MIAMI": "https://a.espncdn.com/i/teamlogos/ncaa/500/2390.png",
    "NFL:IND": "https://a.espncdn.com/i/teamlogos/nfl/500/ind.png", "NBA:IND": "https://a.espncdn.com/i/teamlogos/nba/500/ind.png", "NCF_FBS:IND": "https://a.espncdn.com/i/teamlogos/ncaa/500/84.png",
    "NHL:WSH": "https://a.espncdn.com/guid/cbe677ee-361e-91b4-5cae-6c4c30044743/logos/secondary_logo_on_black_color.png", "NHL:WAS": "https://a.espncdn.com/guid/cbe677ee-361e-91b4-5cae-6c4c30044743/logos/secondary_logo_on_black_color.png",
    "NFL:WSH": "https://a.espncdn.com/i/teamlogos/nfl/500/wsh.png", "NFL:WAS": "https://a.espncdn.com/i/teamlogos/nfl/500/wsh.png", "NBA:WSH": "https://a.espncdn.com/i/teamlogos/nba/500/was.png", "NBA:WAS": "https://a.espncdn.com/i/teamlogos/nba/500/was.png",
    "MLB:WSH": "https://a.espncdn.com/i/teamlogos/mlb/500/wsh.png", "MLB:WAS": "https://a.espncdn.com/i/teamlogos/mlb/500/wsh.png", "NCF_FBS:WASH": "https://a.espncdn.com/i/teamlogos/ncaa/500/264.png",
    "NHL:SJS": "https://a.espncdn.com/i/teamlogos/nhl/500/sj.png", "NHL:NJD": "https://a.espncdn.com/i/teamlogos/nhl/500/nj.png", "NHL:TBL": "https://a.espncdn.com/i/teamlogos/nhl/500/tb.png", "NHL:LAK": "https://a.espncdn.com/i/teamlogos/nhl/500/la.png",
    "NHL:VGK": "https://a.espncdn.com/i/teamlogos/nhl/500/vgs.png", "NHL:VEG": "https://a.espncdn.com/i/teamlogos/nhl/500/vgs.png", "NHL:UTA": "https://a.espncdn.com/i/teamlogos/nhl/500/utah.png",
    "NCF_FBS:CAL": "https://a.espncdn.com/i/teamlogos/ncaa/500/25.png", "NCF_FBS:OSU": "https://a.espncdn.com/i/teamlogos/ncaa/500/194.png", "NCF_FBS:ORST": "https://a.espncdn.com/i/teamlogos/ncaa/500/204.png", "NCF_FCS:LIN": "https://a.espncdn.com/i/teamlogos/ncaa/500/2815.png", "NCF_FCS:LEH": "https://a.espncdn.com/i/teamlogos/ncaa/500/2329.png"
}

SPORT_DURATIONS = {
    'nfl': 195, 'ncf_fbs': 210, 'ncf_fcs': 195,
    'nba': 150, 'nhl': 150, 'mlb': 180, 'weather': 60, 'soccer': 115
}

# === DEMO DATA ===
def generate_demo_data():
    return [
        {'type': 'scoreboard', 'sport': 'nhl', 'id': 'demo_so', 'status': 'S/O', 'state': 'in', 'is_shown': True,
         'home_abbr': 'NYR', 'home_score': '3', 'home_logo': 'https://a.espncdn.com/i/teamlogos/nhl/500/nyr.png', 'home_color': '#0038A8', 'home_alt_color': '#CE1126',
         'away_abbr': 'NJD', 'away_score': '3', 'away_logo': 'https://a.espncdn.com/i/teamlogos/nhl/500/nj.png', 'away_color': '#CE1126', 'away_alt_color': '#000000',
         'startTimeUTC': dt.now(timezone.utc).isoformat(), 'estimated_duration': 150,
         'situation': {'shootout': { 'away': ['goal', 'miss', 'miss'], 'home': ['miss', 'goal', 'pending'] }}},
        {'type': 'scoreboard', 'sport': 'soccer_wc', 'id': 'demo_wc_pens', 'status': 'Pens', 'state': 'in', 'is_shown': True,
         'home_abbr': 'ARG', 'home_score': '3', 'home_logo': 'https://a.espncdn.com/i/teamlogos/soccer/500/202.png', 'home_color': '#75AADB', 'home_alt_color': '#FFFFFF',
         'away_abbr': 'FRA', 'away_score': '3', 'away_logo': 'https://a.espncdn.com/i/teamlogos/soccer/500/478.png', 'away_color': '#002395', 'away_alt_color': '#ED2939',
         'startTimeUTC': dt.now(timezone.utc).isoformat(), 'estimated_duration': 140,
         'situation': {'shootout': { 'away': ['goal', 'miss', 'goal', 'miss'], 'home': ['goal', 'goal', 'goal', 'goal'] }, 'possession': ''}, 'tourney_name': 'Final'}
    ]

# ================= FETCHING LOGIC =================
class WeatherFetcher:
    def __init__(self, initial_loc):
        self.lat = 40.7128; self.lon = -74.0060; self.location_name = "New York"; self.last_fetch = 0; self.cache = None
        if initial_loc: self.update_coords(initial_loc)
    def update_coords(self, location_query):
        try:
            r = requests.get(f"https://geocoding-api.open-meteo.com/v1/search?name={str(location_query).strip()}&count=1&language=en&format=json", timeout=5)
            d = r.json()
            if 'results' in d and len(d['results']) > 0:
                res = d['results'][0]; self.lat = res['latitude']; self.lon = res['longitude']; self.location_name = res['name']; self.last_fetch = 0 
        except Exception as e: print(f"Weather update error: {e}")
    def get_weather(self):
        if time.time() - self.last_fetch < 900 and self.cache: return self.cache
        try:
            r = requests.get(f"https://api.open-meteo.com/v1/forecast?latitude={self.lat}&longitude={self.lon}&current=temperature_2m,weather_code,is_day&daily=temperature_2m_max,temperature_2m_min,uv_index_max&temperature_unit=fahrenheit&timezone=auto", timeout=5)
            d = r.json(); c = d.get('current', {}); dl = d.get('daily', {})
            code = c.get('weather_code', 0); is_day = c.get('is_day', 1)
            icon = "cloud"
            if code in [0, 1]: icon = "sun" if is_day else "moon"
            elif code in [51, 53, 55, 61, 63, 65, 80, 81, 82]: icon = "rain"
            elif code in [71, 73, 75, 77, 85, 86]: icon = "snow"
            elif code in [95, 96, 99]: icon = "storm"
            w_obj = { "type": "weather", "sport": "weather", "id": "weather_widget", "status": "Live",
                "home_abbr": f"{int(c.get('temperature_2m', 0))}°", "away_abbr": self.location_name, "home_score": "", "away_score": "", "is_shown": True, "home_logo": "", "away_logo": "", "home_color": "#000000", "away_color": "#000000",
                "situation": { "icon": icon, "stats": { "high": int(dl['temperature_2m_max'][0]), "low": int(dl['temperature_2m_min'][0]), "uv": float(dl['uv_index_max'][0]) } } }
            self.cache = w_obj; self.last_fetch = time.time(); return w_obj
        except: return None

class SportsFetcher:
    def __init__(self, initial_loc):
        self.weather = WeatherFetcher(initial_loc)
        self.possession_cache = {} # RESTORED: Possession cache for football
        self.base_url = 'http://site.api.espn.com/apis/site/v2/sports/'
        self.leagues = {
            'nfl': { 'path': 'football/nfl', 'team_params': {'limit': 100}, 'type': 'scoreboard' },
            'mlb': { 'path': 'baseball/mlb', 'team_params': {'limit': 100}, 'type': 'scoreboard' },
            'nhl': { 'path': 'hockey/nhl', 'team_params': {'limit': 100}, 'type': 'scoreboard' },
            'nba': { 'path': 'basketball/nba', 'team_params': {'limit': 100}, 'type': 'scoreboard' },
            'soccer_epl':   { 'path': 'soccer/eng.1', 'team_params': {'limit': 50}, 'type': 'scoreboard' },
            'soccer_champ': { 'path': 'soccer/eng.2', 'team_params': {'limit': 50}, 'type': 'scoreboard' },
            'soccer_l1':    { 'path': 'soccer/eng.3', 'team_params': {'limit': 50}, 'type': 'scoreboard' },
            'soccer_l2':    { 'path': 'soccer/eng.4', 'team_params': {'limit': 50}, 'type': 'scoreboard' },
            'soccer_wc':    { 'path': 'soccer/fifa.world', 'team_params': {'limit': 100}, 'type': 'scoreboard' },
            'ncf_fbs': { 'path': 'football/college-football', 'scoreboard_params': {'groups': '80'}, 'type': 'scoreboard' },
            'ncf_fcs': { 'path': 'football/college-football', 'scoreboard_params': {'groups': '81'}, 'type': 'scoreboard' },
            'hockey_olympics': { 'path': 'hockey/mens-olympic-hockey', 'type': 'scoreboard' },
            'f1': { 'path': 'racing/f1', 'type': 'leaderboard' },
            'nascar': { 'path': 'racing/nascar', 'type': 'leaderboard' },
            'indycar': { 'path': 'racing/indycar', 'type': 'leaderboard' },
            'wec': { 'path': 'racing/wec', 'type': 'leaderboard' },
            'imsa': { 'path': 'racing/imsa', 'type': 'leaderboard' }
        }

    def get_corrected_logo(self, league_key, abbr, default_logo):
        return LOGO_OVERRIDES.get(f"{league_key.upper()}:{abbr}", default_logo)

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
        except Exception as e: print(f"Error fetching teams for {league_key}: {e}")

    def fetch_all_teams(self):
        try:
            teams_catalog = {k: [] for k in self.leagues.keys()}
            print("Starting Team Fetch...")
            
            for t in OLYMPIC_HOCKEY_TEAMS:
                teams_catalog['hockey_olympics'].append({'abbr': t['abbr'], 'logo': t['logo'], 'color': '000000', 'alt_color': '444444'})

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
                            
                            if t_abbr in FBS_TEAMS:
                                t_logo = self.get_corrected_logo('ncf_fbs', t_abbr, t_logo)
                                if not any(x['abbr'] == t_abbr for x in teams_catalog['ncf_fbs']):
                                    teams_catalog['ncf_fbs'].append({'abbr': t_abbr, 'logo': t_logo, 'color': t_clr, 'alt_color': t_alt})
                            elif t_abbr in FCS_TEAMS:
                                t_logo = self.get_corrected_logo('ncf_fcs', t_abbr, t_logo)
                                if not any(x['abbr'] == t_abbr for x in teams_catalog['ncf_fcs']):
                                    teams_catalog['ncf_fcs'].append({'abbr': t_abbr, 'logo': t_logo, 'color': t_clr, 'alt_color': t_alt})

            for league_key in ['nfl', 'mlb', 'nhl', 'nba', 'soccer_epl', 'soccer_champ', 'soccer_l1', 'soccer_l2', 'soccer_wc']:
                 self._fetch_simple_league(league_key, teams_catalog)

            with data_lock: state['all_teams_data'] = teams_catalog
            print("Teams fetched successfully.")
        except Exception as e: print(f"Global Team Fetch Error: {e}")

    # RESTORED: Special Old Logic for NHL Shootouts (Native API)
    def fetch_shootout_details_nhl_native(self, game_id, away_id, home_id):
        try:
            url = f"https://api-web.nhle.com/v1/gamecenter/{game_id}/play-by-play"
            r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=3)
            if r.status_code != 200: return None
            data = r.json()
            plays = data.get("plays", [])
            
            # Note: NHL Native uses integer IDs. We need to match based on the logic in the play feed
            # Usually we just look at the eventOwnerTeamId
            
            results = {'away': [], 'home': []}
            
            # Determine mapping if IDs are passed as ints or strings.
            # The play feed returns int IDs.
            
            for play in plays:
                if play.get("periodDescriptor", {}).get("periodType") != "SO": continue
                type_key = play.get("typeDescKey")
                if type_key not in {"goal", "shot-on-goal", "missed-shot"}: continue
                
                details = play.get("details", {})
                team_id = details.get("eventOwnerTeamId") # Int
                
                res_code = "goal" if type_key == "goal" else "miss"
                
                # Simple logic: If we don't know the exact INT ids, we guess based on order? 
                # Better: The ESPN loop usually has the IDs. 
                # For safety, if we can't match, we assume Away shoots first? No, that's risky.
                # In the old code, it matched against IDs passed in.
                
                # Logic: We will check if the ID matches what we passed. 
                # NOTE: ESPN IDs and NHL Native IDs ARE DIFFERENT.
                # However, the old code relied on this working. Let's assume the user knows
                # the old code worked because they used specific IDs.
                # Correction: The old code fetched `landing` to get the Home/Away IDs.
                # To keep it simple in this hybrid: We will assume `away_id` and `home_id` provided are ESPN IDs, 
                # and this Native fetcher gets the Native IDs from the same payload if possible?
                # Actually, `data.get('awayTeam', {}).get('id')` in this native payload gives the native ID.
                
                native_away = data.get("awayTeam", {}).get("id")
                native_home = data.get("homeTeam", {}).get("id")
                
                if team_id == native_away: results['away'].append(res_code)
                elif team_id == native_home: results['home'].append(res_code)
            return results
        except: return None

    # NEW: Generic Shootout for Soccer (ESPN API)
    def fetch_shootout_details_soccer(self, game_id, sport):
        try:
            path_part = "soccer/eng.1"
            if 'soccer' in sport: path_part = f"soccer/{sport.replace('soccer_','')}"
            url = f"https://site.api.espn.com/apis/site/v2/sports/{path_part}/summary?event={game_id}"
            r = requests.get(url, headers=HEADERS, timeout=3)
            data = r.json(); results = {'away': [], 'home': []}
            plays = data.get("shootout", [])
            if not plays: return None
            for p in plays:
                res = "goal" if (p.get("result") == "scored" or "Goal" in p.get("text", "")) else "miss"
                if p.get("homeAway") == "home": results['home'].append(res)
                else: results['away'].append(res)
            return results
        except: return None

    # RESTORED: Helper to get NHL "Situation" (PP/EN) from Native API
    def get_nhl_live_situation(self, game_id):
        try:
            r = requests.get(f"https://api-web.nhle.com/v1/gamecenter/{game_id}/landing", headers=HEADERS, timeout=2)
            if r.status_code != 200: return {}
            d2 = r.json()
            sit_obj = d2.get('situation', {})
            # situationCode format: 1551 (AwayGoalie, AwaySkaters, HomeSkaters, HomeGoalie)
            code = sit_obj.get('situationCode', '1551')
            ag = int(code[0]); as_ = int(code[1]); hs = int(code[2]); hg = int(code[3])
            
            pp = False; poss_team = ""
            if as_ > hs: pp=True; poss_team = "away"
            elif hs > as_: pp=True; poss_team = "home"
            en = (ag == 0 or hg == 0)
            
            return { 'powerPlay': pp, 'emptyNet': en, 'possession': poss_team }
        except: return {}

    def fetch_leaderboard_event(self, league_key, config, games_list, conf, window_start, window_end):
        try:
            url = f"{self.base_url}{config['path']}/scoreboard"
            r = requests.get(url, headers=HEADERS, timeout=5)
            data = r.json()
            for e in data.get('events', []):
                name = e.get('name', e.get('shortName', 'Race'))
                status_obj = e.get('status', {})
                state = status_obj.get('type', {}).get('state', 'pre')
                
                utc_str = e['date'].replace('Z', '')
                try:
                    event_dt = dt.fromisoformat(utc_str).replace(tzinfo=timezone.utc)
                    if not (window_start <= event_dt <= window_end) and state != 'in':
                        continue
                except: continue

                leaders = []
                try:
                    comps = e.get('competitions', [{}])[0].get('competitors', [])
                    sorted_comps = sorted(comps, key=lambda x: int(x.get('curatedRank', x.get('order', 999))))
                    for c in sorted_comps[:5]:
                        athlete = c.get('athlete', {})
                        disp_name = athlete.get('displayName', c.get('team',{}).get('displayName','Unk'))
                        if ' ' in disp_name: disp_name = disp_name.split(' ')[-1]
                        rank = c.get('curatedRank', c.get('order', '-'))
                        leaders.append({'rank': str(rank), 'name': disp_name})
                except: pass

                game_obj = {
                    'type': 'leaderboard', 'sport': league_key, 'id': e['id'],
                    'status': status_obj.get('type', {}).get('shortDetail', 'Live'),
                    'state': state, 'tourney_name': name, 'is_shown': True, 'startTimeUTC': e['date'],
                    'leaders': leaders
                }
                games_list.append(game_obj)
        except Exception as e: print(f"Racing fetch error {league_key}: {e}")

    def get_real_games(self):
        games = []
        with data_lock: 
            conf = state.copy()
            if conf.get('demo_mode', False):
                state['current_games'] = generate_demo_data(); return

        utc_offset = conf.get('utc_offset', -5)
        
        now_utc = dt.now(timezone.utc)
        now_local = now_utc.astimezone(timezone(timedelta(hours=utc_offset)))
        window_start_local = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
        window_end_local = window_start_local + timedelta(days=1, hours=3)
        window_start_utc = window_start_local.astimezone(timezone.utc)
        window_end_utc = window_end_local.astimezone(timezone.utc)

        target_date_str = now_local.strftime("%Y-%m-%d")
        if conf['debug_mode'] and conf['custom_date']:
            target_date_str = conf['custom_date']

        if conf['active_sports'].get('weather'):
            if conf['weather_location'] != self.weather.location_name: self.weather.update_coords(conf['weather_location'])
            w = self.weather.get_weather()
            if w: games.append(w)
        if conf['active_sports'].get('clock'): games.append({'type':'clock','sport':'clock','id':'clk','is_shown':True})

        for league_key, config in self.leagues.items():
            if not conf['active_sports'].get(league_key, False): continue
            
            if config.get('type') == 'leaderboard': 
                self.fetch_leaderboard_event(league_key, config, games, conf, window_start_utc, window_end_utc)
                continue

            try:
                curr_p = config.get('scoreboard_params', {}).copy()
                curr_p['dates'] = target_date_str.replace('-', '')
                
                r = requests.get(f"{self.base_url}{config['path']}/scoreboard", params=curr_p, headers=HEADERS, timeout=5)
                data = r.json()
                
                for e in data.get('events', []):
                    utc_str = e['date'].replace('Z', '')
                    st = e.get('status', {})
                    tp = st.get('type', {})
                    gst = tp.get('state', 'pre')
                    
                    try:
                        game_dt = dt.fromisoformat(utc_str).replace(tzinfo=timezone.utc)
                        if gst != 'in' and gst != 'half':
                            if not (window_start_utc <= game_dt <= window_end_utc):
                                continue
                    except: continue

                    comp = e['competitions'][0]
                    h = comp['competitors'][0]
                    a = comp['competitors'][1]
                    h_ab = h['team'].get('abbreviation', 'UNK')
                    a_ab = a['team'].get('abbreviation', 'UNK')
                    
                    if league_key == 'ncf_fbs' and h_ab not in FBS_TEAMS and a_ab not in FBS_TEAMS: continue
                    if league_key == 'ncf_fcs' and h_ab not in FCS_TEAMS and a_ab not in FCS_TEAMS: continue

                    is_shown = True
                    if conf['mode'] == 'live' and gst not in ['in', 'half']: is_shown = False
                    elif conf['mode'] == 'my_teams':
                        in_my = (f"{league_key}:{h_ab}" in conf['my_teams'] or h_ab in conf['my_teams'] or f"{league_key}:{a_ab}" in conf['my_teams'] or a_ab in conf['my_teams'])
                        if not in_my: is_shown = False

                    h_lg = self.get_corrected_logo(league_key, h_ab, h['team'].get('logo',''))
                    a_lg = self.get_corrected_logo(league_key, a_ab, a['team'].get('logo',''))
                    h_score = h.get('score','0')
                    a_score = a.get('score','0')
                    
                    if 'soccer' in league_key: 
                        h_score = re.sub(r'\s*\(.*?\)', '', str(h_score))
                        a_score = re.sub(r'\s*\(.*?\)', '', str(a_score))

                    s_disp = tp.get('shortDetail', 'TBD')
                    p = st.get('period', 1)
                    duration_est = self.calculate_game_timing(league_key, e['date'], p, s_disp)

                    if gst == 'pre':
                        try: s_disp = game_dt.astimezone(timezone(timedelta(hours=utc_offset))).strftime("%I:%M %p").lstrip('0')
                        except: pass
                    elif gst == 'in' or gst == 'half':
                        clk = st.get('displayClock', '0:00').replace("'", "")
                        if gst == 'half' or (p == 2 and clk == '0:00' and 'football' in config['path']):
                            s_disp = "Halftime"
                        elif 'hockey' in config['path'] and clk == '0:00':
                             if p == 1: s_disp = "End 1st"
                             elif p == 2: s_disp = "End 2nd"
                             elif p == 3: s_disp = "End 3rd"
                             else: s_disp = "Intermission"
                        else:
                            prefix = "P" if 'hockey' in config['path'] else "Q"
                            s_disp = f"{prefix}{p} {clk}"
                            if 'soccer' in config['path']:
                                s_disp = f"{clk}'"
                                if gst == 'half' or tp.get('shortDetail') in ['Halftime', 'HT']: s_disp = "Half"

                    s_disp = s_disp.replace("Final", "FINAL").replace("/OT", " OT")
                    if "FINAL" in s_disp:
                        if league_key == 'nhl' and "SO" in s_disp: s_disp = "FINAL S/O"
                        elif p > 4 and "OT" not in s_disp and league_key == 'nhl': s_disp = "FINAL OT"

                    # === SITUATION LOGIC (RESTORED) ===
                    sit = comp.get('situation', {})
                    shootout_data = None
                    is_shootout = "Shootout" in s_disp or "Penalties" in s_disp or (gst == 'in' and st.get('period', 1) > 4 and 'hockey' in league_key)
                    
                    # 1. SHOOTOUTS
                    if is_shootout:
                        if league_key == 'nhl':
                            shootout_data = self.fetch_shootout_details_nhl_native(e['id'], h['team'].get('id'), a['team'].get('id'))
                        elif 'soccer' in league_key:
                            shootout_data = self.fetch_shootout_details_soccer(e['id'], league_key)
                    
                    # 2. POSSESSION (Football / Baseball)
                    poss_raw = sit.get('possession') # This returns Team ID in ESPN
                    # Cache logic for football because ESPN clears it between plays
                    if poss_raw: self.possession_cache[e['id']] = poss_raw
                    elif gst in ['in', 'half'] and e['id'] in self.possession_cache: poss_raw = self.possession_cache[e['id']]
                    
                    # Convert Possession ID to ABBR if possible
                    poss_abbr = ""
                    if str(poss_raw) == str(h['team'].get('id')): poss_abbr = h_ab
                    elif str(poss_raw) == str(a['team'].get('id')): poss_abbr = a_ab
                    
                    if gst == 'pre' or gst == 'post' or gst == 'half': poss_abbr = ''
                    down_text = sit.get('downDistanceText', '') if s_disp != "Halftime" else ''

                    # 3. NHL POWER PLAY & EMPTY NET
                    pp = False; en = False
                    if league_key == 'nhl' and gst == 'in':
                        # Use helper to get the native situation code data
                        native_data = self.get_nhl_live_situation(e['id'])
                        pp = native_data.get('powerPlay', False)
                        en = native_data.get('emptyNet', False)
                        # Native data returns 'home' or 'away' for possession, map to abbr
                        if native_data.get('possession') == 'home': poss_abbr = h_ab
                        elif native_data.get('possession') == 'away': poss_abbr = a_ab

                    game_obj = {
                        'type': 'scoreboard', 'sport': league_key, 'id': e['id'], 'status': s_disp, 'state': gst, 'is_shown': is_shown,
                        'home_abbr': h_ab, 'home_score': h_score, 'home_logo': h_lg,
                        'away_abbr': a_ab, 'away_score': a_score, 'away_logo': a_lg,
                        'home_color': f"#{h['team'].get('color','000000')}", 'home_alt_color': f"#{h['team'].get('alternateColor','ffffff')}",
                        'away_color': f"#{a['team'].get('color','000000')}", 'away_alt_color': f"#{a['team'].get('alternateColor','ffffff')}",
                        'startTimeUTC': e['date'],
                        'estimated_duration': duration_est,
                        'situation': { 
                            'possession': poss_abbr, 
                            'isRedZone': sit.get('isRedZone', False), 
                            'downDist': down_text, 
                            'shootout': shootout_data,
                            'powerPlay': pp,
                            'emptyNet': en
                        }
                    }
                    if league_key == 'mlb':
                        game_obj['situation'].update({'balls': sit.get('balls', 0), 'strikes': sit.get('strikes', 0), 'outs': sit.get('outs', 0), 
                            'onFirst': sit.get('onFirst', False), 'onSecond': sit.get('onSecond', False), 'onThird': sit.get('onThird', False)})
                    games.append(game_obj)
            except Exception as e: 
                print(f"Error fetching {league_key}: {e}")
        
        with data_lock: state['current_games'] = games

fetcher = SportsFetcher(state['weather_location'])

def background_updater():
    try:
        fetcher.fetch_all_teams()
    except Exception as e:
        print(f"Initial team fetch failed: {e}")
        
    while True: 
        try:
            fetcher.get_real_games()
        except Exception as e:
            print(f"Loop error: {e}")
        time.sleep(UPDATE_INTERVAL)

# ================= FLASK API =================
app = Flask(__name__)
CORS(app) 

@app.route('/api/config', methods=['POST'])
def api_config():
    try:
        new_data = request.json
        with data_lock:
            was_demo = state.get('demo_mode', False)
            is_demo = new_data.get('demo_mode', was_demo)
            state.update(new_data)
            if was_demo and not is_demo: state['current_games'] = []
        save_config_file()
        return jsonify({"status": "ok"})
    except: return jsonify({"error": "Failed"}), 500

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
    cid = request.headers.get('X-Client-ID'); code = request.json.get('code'); friendly_name = request.json.get('name', 'My Ticker')
    if not cid or not code: return jsonify({"success": False}), 400
    for uid, rec in tickers.items():
        if rec.get('pairing_code') == code:
            if cid not in rec['clients']: rec['clients'].append(cid)
            rec['paired'] = True; rec['name'] = friendly_name; save_config_file()
            return jsonify({"success": True, "ticker_id": uid})
    return jsonify({"success": False}), 404

@app.route('/pair/id', methods=['POST'])
def pair_ticker_by_id():
    cid = request.headers.get('X-Client-ID'); tid = request.json.get('id'); friendly_name = request.json.get('name', 'My Ticker')
    if not cid or not tid: return jsonify({"success": False}), 400
    if tid in tickers:
        if cid not in tickers[tid]['clients']: tickers[tid]['clients'].append(cid)
        tickers[tid]['paired'] = True; tickers[tid]['name'] = friendly_name; save_config_file()
        return jsonify({"success": True, "ticker_id": tid})
    return jsonify({"success": False}), 404

@app.route('/ticker/<tid>/unpair', methods=['POST'])
def unpair(tid):
    cid = request.headers.get('X-Client-ID')
    if tid in tickers and cid in tickers[tid]['clients']:
        tickers[tid]['clients'].remove(cid)
        if not tickers[tid]['clients']: tickers[tid]['paired'] = False; tickers[tid]['pairing_code'] = generate_pairing_code()
        save_config_file()
    return jsonify({"success": True})

@app.route('/tickers', methods=['GET'])
def list_tickers():
    cid = request.headers.get('X-Client-ID'); 
    if not cid: return jsonify([])
    res = []
    for uid, rec in tickers.items():
        if cid in rec.get('clients', []): res.append({ "id": uid, "name": rec.get('name', 'Ticker'), "settings": rec['settings'], "last_seen": rec.get('last_seen', 0) })
    return jsonify(res)

@app.route('/ticker/<tid>', methods=['POST'])
def update_settings(tid):
    if tid not in tickers: return jsonify({"error":"404"}), 404
    tickers[tid]['settings'].update(request.json); save_config_file()
    return jsonify({"success": True})

@app.route('/api/state')
def api_state():
    with data_lock: return jsonify({'settings': state, 'games': state['current_games']})
@app.route('/api/teams')
def api_teams():
    with data_lock: return jsonify(state['all_teams_data'])
@app.route('/api/hardware', methods=['POST'])
def api_hardware():
    if request.json.get('action') == 'reboot':
        with data_lock: state['reboot_requested'] = True
        threading.Timer(10, lambda: state.update({'reboot_requested': False})).start()
    return jsonify({"status": "ok"})
@app.route('/api/debug', methods=['POST'])
def api_debug():
    with data_lock: state.update(request.json)
    return jsonify({"status": "ok"})
@app.route('/')
def root(): return "Ticker Server Running"

if __name__ == "__main__":
    threading.Thread(target=background_updater, daemon=True).start()
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 5000)))
