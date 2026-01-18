import time
import threading
import json
import os
import sys
import re
import random
import string
import glob
from datetime import datetime as dt, timezone, timedelta
import requests
from requests.adapters import HTTPAdapter
import concurrent.futures
from flask import Flask, jsonify, request
from flask_cors import CORS
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# ================= SERVER VERSION =================
SERVER_VERSION = "v7"

# ================= CONFIGURATION =================
TICKER_DATA_DIR = "ticker_data"
if not os.path.exists(TICKER_DATA_DIR): os.makedirs(TICKER_DATA_DIR)
GLOBAL_CONFIG_FILE = "global_config.json"
STOCK_CACHE_FILE = "stock_cache.json"

# === MICRO-OPTIMIZED SETTINGS ===
SPORTS_UPDATE_INTERVAL = 5.0   # Target: Update every 5 seconds
STOCKS_UPDATE_INTERVAL = 30    # Update stocks every 30 seconds
WORKER_THREAD_COUNT = 10       # Safe limit for 1GB RAM
API_TIMEOUT = 3.0              # Hard timeout: Drop slow requests

data_lock = threading.Lock()

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
    "Accept": "application/json",
    "Cache-Control": "no-cache, no-store, must-revalidate",
    "Pragma": "no-cache",
    "Expires": "0"
}

# ================= LOGGING =================
class Tee(object):
    def __init__(self, name, mode):
        self.file = open(name, mode, buffering=1)
        self.stdout = sys.stdout; self._lock = threading.Lock()
    def write(self, data):
        with self._lock:
            self.file.write(data); self.file.flush(); self.stdout.write(data); self.stdout.flush()
    def flush(self):
        with self._lock: self.file.flush(); self.stdout.flush()

try:
    if not os.path.exists("ticker.log"): with open("ticker.log", "w") as f: f.write("--- Log Started ---\n")
    sys.stdout = Tee("ticker.log", "a")
except: pass

# ================= CACHE CLEANUP =================
if os.path.exists(STOCK_CACHE_FILE):
    try: os.remove(STOCK_CACHE_FILE)
    except: pass

def build_pooled_session(pool_size=10, retries=1):
    session = requests.Session()
    adapter = HTTPAdapter(pool_connections=pool_size, pool_maxsize=pool_size, max_retries=retries, pool_block=False)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session

# ================= LEAGUE DATA =================
FOTMOB_LEAGUE_MAP = {'soccer_epl': 47, 'soccer_fa_cup': 132, 'soccer_champ': 48, 'soccer_l1': 108, 'soccer_l2': 109, 'soccer_wc': 77, 'soccer_champions_league': 42, 'soccer_europa_league': 73}
AHL_API_KEYS = ["ccb91f29d6744675", "694cfeed58c932ee", "50c2cd9b5e18e390"]
TZ_OFFSETS = {"EST": -5, "EDT": -4, "CST": -6, "CDT": -5, "MST": -7, "MDT": -6, "PST": -8, "PDT": -7, "AST": -4, "ADT": -3}

# Full AHL Team Map
AHL_TEAMS = {
    "BRI": {"name": "Bridgeport Islanders", "color": "00539B", "id": "317"}, "CLT": {"name": "Charlotte Checkers", "color": "C8102E", "id": "384"}, "HFD": {"name": "Hartford Wolf Pack", "color": "0D2240", "id": "307"}, "HER": {"name": "Hershey Bears", "color": "4F2C1D", "id": "319"}, "LV":  {"name": "Lehigh Valley Phantoms", "color": "000000", "id": "313"}, "PRO": {"name": "Providence Bruins", "color": "000000", "id": "309"}, "SPR": {"name": "Springfield Thunderbirds", "color": "003087", "id": "411"}, "WBS": {"name": "W-B/Scranton", "color": "000000", "id": "316"}, "BEL": {"name": "Belleville Senators", "color": "C52032", "id": "413"}, "CLE": {"name": "Cleveland Monsters", "color": "041E42", "id": "373"}, "LAV": {"name": "Laval Rocket", "color": "00205B", "id": "415"}, "ROC": {"name": "Rochester Americans", "color": "00539B", "id": "323"}, "SYR": {"name": "Syracuse Crunch", "color": "003087", "id": "324"}, "TOR": {"name": "Toronto Marlies", "color": "00205B", "id": "335"}, "UTC": {"name": "Utica Comets", "color": "006341", "id": "390"}, "CHI": {"name": "Chicago Wolves", "color": "7C2529", "id": "330"}, "GR":  {"name": "Grand Rapids Griffins", "color": "BE1E2D", "id": "328"}, "IA":  {"name": "Iowa Wild", "color": "154734", "id": "389"}, "MB":  {"name": "Manitoba Moose", "color": "003E7E", "id": "321"}, "MIL": {"name": "Milwaukee Admirals", "color": "041E42", "id": "327"}, "RFD": {"name": "Rockford IceHogs", "color": "CE1126", "id": "372"}, "TEX": {"name": "Texas Stars", "color": "154734", "id": "380"}, "ABB": {"name": "Abbotsford Canucks", "color": "00744F", "id": "440"}, "BAK": {"name": "Bakersfield Condors", "color": "F47A38", "id": "402"}, "CGY": {"name": "Calgary Wranglers", "color": "C8102E", "id": "444"}, "CAL": {"name": "Calgary Wranglers", "color": "C8102E", "id": "444"}, "CV":  {"name": "Coachella Valley", "color": "D32027", "id": "445"}, "CVF": {"name": "Coachella Valley", "color": "D32027", "id": "445"}, "COL": {"name": "Colorado Eagles", "color": "003087", "id": "419"}, "HSK": {"name": "Henderson Silver Knights", "color": "111111", "id": "437"}, "ONT": {"name": "Ontario Reign", "color": "111111", "id": "403"}, "SD":  {"name": "San Diego Gulls", "color": "041E42", "id": "404"}, "SJ":  {"name": "San Jose Barracuda", "color": "006D75", "id": "405"}, "SJS": {"name": "San Jose Barracuda", "color": "006D75", "id": "405"}, "TUC": {"name": "Tucson Roadrunners", "color": "8C2633", "id": "412"}
}

LEAGUE_OPTIONS = [
    {'id': 'nfl', 'label': 'NFL', 'type': 'sport', 'default': True, 'fetch': {'path': 'football/nfl', 'team_params': {'limit': 100}, 'type': 'scoreboard'}},
    {'id': 'mlb', 'label': 'MLB', 'type': 'sport', 'default': True, 'fetch': {'path': 'baseball/mlb', 'team_params': {'limit': 100}, 'type': 'scoreboard'}},
    {'id': 'nhl', 'label': 'NHL', 'type': 'sport', 'default': True, 'fetch': {'path': 'hockey/nhl', 'team_params': {'limit': 100}, 'type': 'scoreboard'}},
    {'id': 'ahl', 'label': 'AHL', 'type': 'sport', 'default': True, 'fetch': {'type': 'ahl_native'}},
    {'id': 'nba', 'label': 'NBA', 'type': 'sport', 'default': True, 'fetch': {'path': 'basketball/nba', 'team_params': {'limit': 100}, 'type': 'scoreboard'}},
    {'id': 'ncf_fbs', 'label': 'NCAA FBS', 'type': 'sport', 'default': True, 'fetch': {'path': 'football/college-football', 'scoreboard_params': {'groups': '80'}, 'type': 'scoreboard'}},
    {'id': 'ncf_fcs', 'label': 'NCAA FCS', 'type': 'sport', 'default': True, 'fetch': {'path': 'football/college-football', 'scoreboard_params': {'groups': '81'}, 'type': 'scoreboard'}},
    {'id': 'march_madness', 'label': 'March Madness', 'type': 'sport', 'default': True, 'fetch': {'path': 'basketball/mens-college-basketball', 'scoreboard_params': {'groups': '100', 'limit': '100'}, 'type': 'scoreboard'}},
    {'id': 'soccer_epl', 'label': 'Premier League', 'type': 'sport', 'default': True, 'fetch': {'path': 'soccer/eng.1', 'team_params': {'limit': 50}, 'type': 'scoreboard'}},
    {'id': 'soccer_fa_cup','label': 'FA Cup', 'type': 'sport', 'default': True, 'fetch': {'path': 'soccer/eng.fa', 'type': 'scoreboard'}},
    {'id': 'soccer_champ', 'label': 'Championship', 'type': 'sport', 'default': True, 'fetch': {'path': 'soccer/eng.2', 'team_params': {'limit': 50}, 'type': 'scoreboard'}},
    {'id': 'soccer_l1', 'label': 'League One', 'type': 'sport', 'default': True, 'fetch': {'path': 'soccer/eng.3', 'team_params': {'limit': 50}, 'type': 'scoreboard'}},
    {'id': 'soccer_l2', 'label': 'League Two', 'type': 'sport', 'default': True, 'fetch': {'path': 'soccer/eng.4', 'team_params': {'limit': 50}, 'type': 'scoreboard'}},
    {'id': 'soccer_wc', 'label': 'FIFA World Cup', 'type': 'sport', 'default': True, 'fetch': {'path': 'soccer/fifa.world', 'team_params': {'limit': 100}, 'type': 'scoreboard'}},
    {'id': 'soccer_champions_league', 'label': 'Champions League', 'type': 'sport', 'default': True, 'fetch': {'path': 'soccer/uefa.champions', 'team_params': {'limit': 50}, 'type': 'scoreboard'}},
    {'id': 'soccer_europa_league', 'label': 'Europa League', 'type': 'sport', 'default': True, 'fetch': {'path': 'soccer/uefa.europa', 'team_params': {'limit': 200}, 'type': 'scoreboard'}},
    {'id': 'hockey_olympics', 'label': 'Olympic Hockey', 'type': 'sport', 'default': True, 'fetch': {'path': 'hockey/mens-olympic-hockey', 'type': 'scoreboard'}},
    {'id': 'f1', 'label': 'Formula 1', 'type': 'sport', 'default': True, 'fetch': {'path': 'racing/f1', 'type': 'leaderboard'}},
    {'id': 'nascar', 'label': 'NASCAR', 'type': 'sport', 'default': True, 'fetch': {'path': 'racing/nascar', 'type': 'leaderboard'}},
    {'id': 'weather', 'label': 'Weather', 'type': 'util', 'default': True},
    {'id': 'clock', 'label': 'Clock', 'type': 'util', 'default': True},
    {'id': 'stock_tech_ai', 'label': 'Tech Stocks', 'type': 'stock', 'default': True, 'stock_list': ["AAPL", "MSFT", "NVDA", "GOOGL", "AMZN"]},
    {'id': 'stock_momentum', 'label': 'Momentum Stocks', 'type': 'stock', 'default': False, 'stock_list': ["COIN", "HOOD", "DKNG", "RBLX", "GME"]}
]

FBS_TEAMS = ["ALA","UGA","MICH","OSU","TEX","USC","ND","OU","CLEM","FSU","LSU","TENN","PENN","ORE","WASH","FLA","MIA","AUB","TAMU","OKST","WIS","UTAH","TCU","KSU","IOWA","UK","UNC","MISS","MSST","ARK","SC","MIZ","TECH","BAY","WVU","BYU","UCF","CIN","HOU","SMU","KU","ISU","OSU","WSU","ORST","STAN","CAL","UCLA","ASU","ARIZ","COLO","PITT","VT","UVA","GT","MIA","LOU","NCST","WAKE","DUKE","SYR","BC"] 
FCS_TEAMS = ["NDSU","SDSU","MONT","MTST","DEL","VILL","RICH","IDHO","FUR","HC","W&M","ELON","UNH","ALBY","RICH","CHAT","MER","SAM","ETSU","WEB","SAC","UCD"]
OLYMPIC_HOCKEY_TEAMS = [{"abbr":"CAN","logo":"https://a.espncdn.com/i/teamlogos/countries/500/can.png"},{"abbr":"USA","logo":"https://a.espncdn.com/i/teamlogos/countries/500/usa.png"},{"abbr":"SWE","logo":"https://a.espncdn.com/i/teamlogos/countries/500/swe.png"},{"abbr":"FIN","logo":"https://a.espncdn.com/i/teamlogos/countries/500/fin.png"}]
LOGO_OVERRIDES = {"NFL:HOU":"https://a.espncdn.com/i/teamlogos/nfl/500/hou.png", "NBA:HOU":"https://a.espncdn.com/i/teamlogos/nba/500/hou.png", "MLB:HOU":"https://a.espncdn.com/i/teamlogos/mlb/500/hou.png", "NFL:WAS":"https://a.espncdn.com/i/teamlogos/nfl/500/wsh.png", "NHL:UTA":"https://a.espncdn.com/i/teamlogos/nhl/500/utah.png"}
ABBR_MAPPING = {'SJS':'SJ','TBL':'TB','LAK':'LA','NJD':'NJ','VGK':'VEG','UTA':'UTAH','WSH':'WSH','MTL':'MTL','CHI':'CHI','NY':'NYK','NO':'NOP','GS':'GSW','SA':'SAS'}
SOCCER_COLOR_FALLBACK = {"arsenal":"EF0107","chelsea":"034694","liverpool":"C8102E","manchester city":"6CABDD","manchester united":"DA291C","tottenham":"FFFFFF","barcelona":"A50044","real madrid":"FEBE10","bayern":"DC052D","psg":"004170","juventus":"000000","milan":"FB090B","inter":"010E80"} 
SPORT_DURATIONS = {'nfl':195,'ncf_fbs':210,'ncf_fcs':195,'nba':150,'nhl':150,'mlb':180,'weather':60,'soccer':115}

default_state = { 'active_sports': {i['id']: i['default'] for i in LEAGUE_OPTIONS}, 'mode': 'all', 'my_teams': [], 'current_games': [], 'buffer_sports': [], 'buffer_stocks': [], 'all_teams_data': {}, 'debug_mode': False, 'custom_date': None, 'weather_city': "New York", 'weather_lat': 40.7128, 'weather_lon': -74.0060, 'utc_offset': -5, 'show_debug_options': False }
DEFAULT_TICKER_SETTINGS = { "brightness": 100, "scroll_speed": 0.03, "scroll_seamless": True, "inverted": False, "panel_count": 2, "live_delay_mode": False, "live_delay_seconds": 45 }

state = default_state.copy(); tickers = {} 

if os.path.exists(GLOBAL_CONFIG_FILE):
    try:
        with open(GLOBAL_CONFIG_FILE, 'r') as f: state.update(json.load(f))
    except: pass

for t_file in glob.glob(os.path.join(TICKER_DATA_DIR, "*.json")):
    try:
        with open(t_file, 'r') as f:
            t_data = json.load(f); tid = os.path.splitext(os.path.basename(t_file))[0]
            if 'settings' not in t_data: t_data['settings'] = DEFAULT_TICKER_SETTINGS.copy()
            tickers[tid] = t_data
    except: pass

def save_json_atomically(filepath, data):
    try:
        with open(f"{filepath}.tmp", 'w') as f: json.dump(data, f, indent=4)
        os.replace(f"{filepath}.tmp", filepath)
    except: pass

def save_global_config():
    with data_lock:
        save_json_atomically(GLOBAL_CONFIG_FILE, {'active_sports': state['active_sports'], 'mode': state['mode'], 'my_teams': state['my_teams'], 'weather_city': state['weather_city'], 'weather_lat': state['weather_lat'], 'weather_lon': state['weather_lon'], 'utc_offset': state['utc_offset']})

def save_specific_ticker(tid):
    if tid in tickers: save_json_atomically(os.path.join(TICKER_DATA_DIR, f"{tid}.json"), tickers[tid])

def generate_pairing_code():
    while True:
        code = ''.join(random.choices(string.digits, k=6))
        if code not in [t.get('pairing_code') for t in tickers.values()]: return code

def validate_logo_url(base_id):
    return f"https://assets.leaguestat.com/ahl/logos/50x50/{base_id}.png"

class WeatherFetcher:
    def __init__(self, initial_lat=40.7128, initial_lon=-74.0060, city="New York"):
        self.lat = initial_lat; self.lon = initial_lon; self.city_name = city; self.last_fetch = 0; self.cache = None
        self.session = build_pooled_session(pool_size=5)

    def update_config(self, city=None, lat=None, lon=None):
        if lat: self.lat = lat
        if lon: self.lon = lon
        if city: self.city_name = city
        self.last_fetch = 0 

    def get_weather_icon(self, c):
        c = int(c)
        if c == 0: return 'sun'
        if c in [1, 2, 3, 45, 48]: return 'cloud'
        if c in [51, 53, 55, 56, 57, 61, 63, 65, 66, 67, 80, 81, 82]: return 'rain'
        if c in [71, 73, 75, 77, 85, 86]: return 'snow'
        if c in [95, 96, 99]: return 'storm'
        return 'cloud'

    def get_weather(self):
        if time.time() - self.last_fetch < 900 and self.cache: return self.cache
        try:
            w = self.session.get(f"https://api.open-meteo.com/v1/forecast?latitude={self.lat}&longitude={self.lon}&current=temperature_2m,weather_code&daily=weather_code,temperature_2m_max,temperature_2m_min,uv_index_max&temperature_unit=fahrenheit&timezone=auto", timeout=API_TIMEOUT).json()
            cur = w['current']; daily = w['daily']
            f_list = [{"day": dt.strptime(daily['time'][i], '%Y-%m-%d').strftime('%a').upper(), "icon": self.get_weather_icon(daily['weather_code'][i]), "high": int(round(daily['temperature_2m_max'][i])), "low": int(round(daily['temperature_2m_min'][i]))} for i in range(5)]
            
            self.cache = {
                "type": "weather", "sport": "weather", "id": "weather_main", "away_abbr": self.city_name.upper(), 
                "home_abbr": str(int(round(cur['temperature_2m']))), "home_score": str(int(round(cur['temperature_2m']))),
                "situation": {"icon": self.get_weather_icon(cur['weather_code']), "stats": {"aqi": "0", "uv": str(daily['uv_index_max'][0])}, "forecast": f_list},
                "is_shown": True
            }
            self.last_fetch = time.time(); return self.cache
        except: return None

class StockFetcher:
    def __init__(self):
        self.market_cache = {}; self.last_fetch = 0; self.session = requests.Session()
    def update_market_data(self, l): pass # Disabled for safety on micro instance
    def get_list(self, k): return []

class SportsFetcher:
    def __init__(self, initial_city, initial_lat, initial_lon):
        self.weather = WeatherFetcher(initial_lat=initial_lat, initial_lon=initial_lon, city=initial_city)
        self.stocks = StockFetcher()
        self.base_url = 'http://site.api.espn.com/apis/site/v2/sports/'
        self.session = build_pooled_session(pool_size=15)
        self.executor = concurrent.futures.ThreadPoolExecutor(max_workers=WORKER_THREAD_COUNT)
        
        self.history_buffer = []
        self.final_game_cache = {} 
        self.league_next_update = {} 
        self.league_last_data = {}
        
        self.ahl_cached_key = None; self.ahl_key_expiry = 0
        self.leagues = { i['id']: i['fetch'] for i in LEAGUE_OPTIONS if i['type'] == 'sport' and 'fetch' in i }

    def get_corrected_logo(self, league_key, abbr, default_logo):
        return LOGO_OVERRIDES.get(f"{league_key.upper()}:{abbr}", default_logo)

    def lookup_team_info(self, league, abbr):
        abbr = ABBR_MAPPING.get(abbr, abbr)
        try:
            for t in state['all_teams_data'].get(league, []):
                if t['abbr'] == abbr: return {'color': t.get('color', '000000'), 'alt_color': t.get('alt_color', '444444')}
        except: pass
        return {'color': '000000', 'alt_color': '444444'}

    def _calculate_next_update(self, games):
        """Returns TIMESTAMP when we should next fetch this league"""
        if not games: return 0
        now = time.time()
        earliest_start = None
        
        for g in games:
            # IF ACTIVE, FETCH NOW (return 0)
            if g['state'] in ['in', 'half', 'crit']: return 0
            
            if g['state'] == 'pre':
                try:
                    ts = dt.fromisoformat(g['startTimeUTC'].replace('Z', '+00:00')).timestamp()
                    if earliest_start is None or ts < earliest_start: earliest_start = ts
                except: pass
        
        # IF FUTURE GAMES EXIST
        if earliest_start:
            wake_time = earliest_start - 60 # Wake up 60s before start
            if wake_time > now: return wake_time
            return 0
            
        # ALL FINAL -> Sleep 60s
        return now + 60

    def calculate_game_timing(self, sport, start, period, status):
        dur = SPORT_DURATIONS.get(sport, 180)
        if "OT" in str(status) or "S/O" in str(status) or period > 4: dur += 20
        return dur

    def _fetch_ahl_teams_reference(self, catalog):
        catalog['ahl'] = []
        for c, m in AHL_TEAMS.items(): catalog['ahl'].append({'abbr': c, 'id': f"ahl:{c}", 'color': m['color'], 'name': m['name']})

    def fetch_all_teams(self):
        cat = {k: [] for k in self.leagues.keys()}
        self._fetch_ahl_teams_reference(cat)
        for t in OLYMPIC_HOCKEY_TEAMS: cat['hockey_olympics'].append({'abbr': t['abbr'], 'id': f"hockey_olympics:{t['abbr']}", 'logo': t['logo'], 'color': '000000'})
        fs = []
        for lk in ['nfl', 'mlb', 'nhl', 'nba', 'march_madness', 'soccer_epl']:
            if lk in self.leagues: fs.append(self.executor.submit(self._fetch_simple_league, lk, cat))
        concurrent.futures.wait(fs, timeout=10)
        with data_lock: state['all_teams_data'] = cat

    def _fetch_simple_league(self, league_key, catalog):
        cfg = self.leagues[league_key]; 
        if 'team_params' not in cfg: return
        try:
            r = self.session.get(f"{self.base_url}{cfg['path']}/teams", params=cfg['team_params'], headers=HEADERS, timeout=API_TIMEOUT)
            data = r.json()
            for s in data.get('sports', []):
                for l in s.get('leagues', []):
                    for t in l.get('teams', []):
                        tm = t['team']; abbr = tm.get('abbreviation', 'unk'); sid = f"{league_key}:{abbr}"
                        if not any(x['id'] == sid for x in catalog[league_key]):
                            catalog[league_key].append({'abbr': abbr, 'id': sid, 'logo': self.get_corrected_logo(league_key, abbr, tm.get('logos', [{}])[0].get('href', '')), 'color': tm.get('color', '000000'), 'alt_color': tm.get('alternateColor', '444444'), 'name': tm.get('displayName', '')})
        except: pass

    def _fetch_ahl(self, conf, visible_start_utc, visible_end_utc):
        if not conf['active_sports'].get('ahl', False): return []
        now = time.time()
        if now < self.league_next_update.get('ahl', 0): return self.league_last_data.get('ahl', [])
        
        try:
            r = self.session.get("https://lscluster.hockeytech.com/feed/index.php", params={"feed": "modulekit", "view": "scorebar", "key": AHL_API_KEYS[0], "client_code": "ahl", "lang": "en", "fmt": "json", "league_id": 4, "site_id": 0}, timeout=API_TIMEOUT)
            if r.status_code != 200: return []
            data = r.json(); scorebar = data.get("SiteKit", {}).get("Scorebar", []); games = []
            
            req_date = visible_start_utc.strftime("%Y-%m-%d")
            for g in scorebar:
                if g.get("Date") != req_date: continue
                gid = g.get("ID")
                if f"ahl_{gid}" in self.final_game_cache:
                    games.append(self.final_game_cache[f"ahl_{gid}"]); continue
                
                h_code = g.get("HomeCode").upper(); a_code = g.get("VisitorCode").upper()
                st_raw = g.get("GameStatusString",""); gst = 'pre'; disp = st_raw
                if "final" in st_raw.lower(): gst = 'post'; disp = "FINAL"
                elif "progress" in st_raw.lower() or "period" in st_raw.lower(): gst = 'in'
                
                obj = {
                    'type': 'scoreboard', 'sport': 'ahl', 'id': f"ahl_{gid}", 'status': disp, 'state': gst, 'is_shown': True,
                    'home_abbr': h_code, 'home_score': str(g.get("HomeGoals",0)), 'away_abbr': a_code, 'away_score': str(g.get("VisitorGoals",0)),
                    'home_color': '#000000', 'away_color': '#000000', 'startTimeUTC': f"{req_date}T00:00:00Z", 'situation': {}
                }
                games.append(obj)
                if gst == 'post': self.final_game_cache[f"ahl_{gid}"] = obj
                
            self.league_next_update['ahl'] = self._calculate_next_update(games)
            self.league_last_data['ahl'] = games
            return games
        except: return []

    def fetch_single_league(self, league_key, config, conf, utc_offset):
        games = []
        try:
            curr_p = config.get('scoreboard_params', {}).copy()
            curr_p['dates'] = (dt.now(timezone.utc) + timedelta(hours=utc_offset)).strftime("%Y%m%d")
            
            r = self.session.get(f"{self.base_url}{config['path']}/scoreboard", params=curr_p, headers=HEADERS, timeout=API_TIMEOUT)
            data = r.json()
            events = data.get('events', []) or (data.get('leagues', [{}])[0].get('events', []))
            
            for e in events:
                gid = str(e['id'])
                if gid in self.final_game_cache:
                    games.append(self.final_game_cache[gid]); continue
                
                st = e.get('status', {}); tp = st.get('type', {}); gst = tp.get('state', 'pre')
                
                h = e['competitions'][0]['competitors'][0]; a = e['competitions'][0]['competitors'][1]
                h_ab = h['team'].get('abbreviation', 'UNK'); a_ab = a['team'].get('abbreviation', 'UNK')
                h_info = self.lookup_team_info(league_key, h_ab); a_info = self.lookup_team_info(league_key, a_ab)
                
                disp = tp.get('shortDetail', 'TBD')
                if gst == 'in': disp = f"{st.get('displayClock','0:00').replace('\'','')} - P{st.get('period',1)}"
                if "Final" in disp or gst == 'post': disp = "FINAL"

                obj = {
                    'type': 'scoreboard', 'sport': league_key, 'id': gid, 'status': disp, 'state': gst, 'is_shown': True,
                    'home_abbr': h_ab, 'home_score': h.get('score','0'), 'home_logo': self.get_corrected_logo(league_key, h_ab, h['team'].get('logo','')),
                    'away_abbr': a_ab, 'away_score': a.get('score','0'), 'away_logo': self.get_corrected_logo(league_key, a_ab, a['team'].get('logo','')),
                    'home_color': f"#{h_info['color']}", 'away_color': f"#{a_info['color']}",
                    'startTimeUTC': e['date'], 'situation': {}
                }
                games.append(obj)
                if gst == 'post': self.final_game_cache[gid] = obj
        except: pass
        return games

    def update_buffer_sports(self):
        all_games = []; futures = {}
        with data_lock: conf = state.copy()
        
        now = time.time()

        if conf['active_sports'].get('weather'):
            if (conf['weather_lat'] != self.weather.lat or conf['weather_lon'] != self.weather.lon or conf['weather_city'] != self.weather.city_name):
                self.weather.update_config(city=conf['weather_city'], lat=conf['weather_lat'], lon=conf['weather_lon'])
            w = self.weather.get_weather(); 
            if w: all_games.append(w)
        if conf['active_sports'].get('clock'): all_games.append({'type':'clock','sport':'clock','id':'clk','is_shown':True})

        if conf['mode'] in ['sports', 'live', 'my_teams', 'all']:
            utc_off = conf.get('utc_offset', -5)
            # Time Windows
            now_local = dt.now(timezone.utc).astimezone(timezone(timedelta(hours=utc_off)))
            vis_start = now_local.replace(hour=0,minute=0); vis_end = now_local.replace(hour=23,minute=59)

            for lk, cfg in self.leagues.items():
                if not conf['active_sports'].get(lk): continue
                if lk == 'nhl' and not conf['debug_mode']: continue 
                
                if now < self.league_next_update.get(lk, 0):
                    if lk in self.league_last_data: all_games.extend(self.league_last_data[lk])
                    continue
                
                f = self.executor.submit(self.fetch_single_league, lk, cfg, conf, utc_off)
                futures[f] = lk

            if conf['active_sports'].get('ahl'):
                f = self.executor.submit(self._fetch_ahl, conf, vis_start, vis_end)
                futures[f] = 'ahl'

            done, _ = concurrent.futures.wait(futures.keys(), timeout=API_TIMEOUT)
            for f in done:
                lk = futures[f]
                try: 
                    res = f.result()
                    if res: 
                        all_games.extend(res)
                        self.league_last_data[lk] = res
                        self.league_next_update[lk] = self._calculate_next_update(res)
                except: pass

        all_games.sort(key=lambda x: (0 if x['type']=='clock' else 1 if x['type']=='weather' else 3 if 'FINAL' in str(x.get('status','')) else 2, x.get('startTimeUTC','9999')))
        
        with data_lock: 
            state['buffer_sports'] = all_games
            state['current_games'] = all_games

fetcher = SportsFetcher(state['weather_city'], state['weather_lat'], state['weather_lon'])

def sports_worker():
    print(f"🚀 Micro Worker Started ({SPORTS_UPDATE_INTERVAL}s)")
    while True:
        try: fetcher.update_buffer_sports()
        except Exception as e: print(f"Worker Error: {e}"); time.sleep(1)
        time.sleep(SPORTS_UPDATE_INTERVAL)

def stocks_worker():
    while True:
        try: 
            with data_lock: cats = [k for k,v in state['active_sports'].items() if k.startswith('stock_') and v]
            fetcher.stocks.update_market_data(cats); fetcher.update_buffer_stocks()
        except: pass
        time.sleep(30)

# ================= API =================
app = Flask(__name__); CORS(app)

@app.route('/data', methods=['GET'])
def get_data():
    tid = request.args.get('id')
    if not tid and len(tickers) == 1: tid = list(tickers.keys())[0]
    
    if not tid or tid not in tickers:
        return jsonify({"status":"ok", "global_config": state, "local_config": DEFAULT_TICKER_SETTINGS, "content": {"sports": state.get('current_games',[])}})
    
    rec = tickers[tid]; rec['last_seen'] = time.time()
    
    if not rec.get('paired'):
        if not rec.get('pairing_code'): rec['pairing_code'] = generate_pairing_code(); save_specific_ticker(tid)
        return jsonify({"status": "pairing", "code": rec['pairing_code']})

    g_conf = {"mode": rec['settings'].get('mode', 'all')}
    if rec.get('reboot_requested'): g_conf['reboot'] = True
    if rec.get('update_requested'): g_conf['update'] = True
    
    return jsonify({"status":"ok", "global_config": g_conf, "local_config": rec['settings'], "content": {"sports": state.get('current_games',[])}})

@app.route('/api/config', methods=['POST'])
def api_config():
    d = request.json
    tid = d.get('ticker_id') or list(tickers.keys())[0]
    with data_lock:
        if d.get('weather_city'): fetcher.weather.update_config(city=d['weather_city'], lat=d.get('weather_lat'), lon=d.get('weather_lon'))
        for k, v in d.items():
            if k in state: state[k] = v
            if tid in tickers and k in tickers[tid]['settings']: tickers[tid]['settings'][k] = v
        fetcher.merge_buffers()
    if tid: save_specific_ticker(tid)
    else: save_global_config()
    return jsonify({"status": "ok"})

@app.route('/api/hardware', methods=['POST'])
def hardware():
    a = request.json.get('action'); tid = request.json.get('ticker_id')
    if a == 'update':
        with data_lock:
            for t in tickers.values(): t['update_requested'] = True
        threading.Timer(60, lambda: [t.update({'update_requested':False}) for t in tickers.values()]).start()
        return jsonify({"status": "ok", "message": "Updating Fleet"})
    return jsonify({"status": "ignored"})

@app.route('/')
def root(): return f"Ticker Server {SERVER_VERSION} Running"

if __name__ == "__main__":
    threading.Thread(target=sports_worker, daemon=True).start()
    threading.Thread(target=stocks_worker, daemon=True).start()
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 5000)))
