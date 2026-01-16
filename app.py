import time
import threading
import json
import os
import sys
import re
import random
import string
import glob  # <--- NEW: Required for folder scanning
from datetime import datetime as dt, timezone, timedelta
import requests
from requests.adapters import HTTPAdapter
import concurrent.futures
from flask import Flask, jsonify, request
from flask_cors import CORS
from dotenv import load_dotenv

# Load environment variables for Finnhub Keys
load_dotenv()

# ================= SERVER VERSION TAG =================
SERVER_VERSION = "v3.8_Folder_Storage_Update"

# ================= LOGGING SETUP =================
class Tee(object):
    def __init__(self, name, mode):
        self.file = open(name, mode, buffering=1)
        self.original_stdout = sys.stdout
        self.original_stderr = sys.stderr
        self._lock = threading.Lock()
        self.stdout = self
        self.stderr = self

    def write(self, data):
        with self._lock:
            self.file.write(data)
            self.file.flush()
            self.original_stdout.write(data)
            self.original_stdout.flush()

    def flush(self):
        with self._lock:
            self.file.flush()
            self.original_stdout.flush()

try:
    if not os.path.exists("ticker.log"):
        with open("ticker.log", "w") as f: f.write("--- Log Started ---\n")
    Tee("ticker.log", "a")
except Exception as e:
    print(f"Logging setup failed: {e}")

# ================= CACHE CLEANUP ON STARTUP =================
if os.path.exists("stock_cache.json"):
    try:
        print("🧹 Wiping old stock cache on startup...")
        os.remove("stock_cache.json")
    except: pass

def build_pooled_session(pool_size=20, retries=2):
    session = requests.Session()
    adapter = HTTPAdapter(pool_connections=pool_size, pool_maxsize=pool_size, max_retries=retries, pool_block=True)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session

# ================= CONFIGURATION & STORAGE =================
# NEW: Folder for individual ticker files
TICKER_DATA_DIR = "ticker_data"
if not os.path.exists(TICKER_DATA_DIR):
    os.makedirs(TICKER_DATA_DIR)

GLOBAL_CONFIG_FILE = "global_config.json"
STOCK_CACHE_FILE = "stock_cache.json"

# === TIMING ===
SPORTS_UPDATE_INTERVAL = 5        
STOCKS_UPDATE_INTERVAL = 15        

data_lock = threading.Lock()

# Headers for FotMob/ESPN
HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Accept": "application/json",
    "Accept-Language": "en",
    "Referer": "https://www.fotmob.com/"
}

# ================= FOTMOB MAPPING =================
FOTMOB_LEAGUE_MAP = {
    'soccer_epl': 47,
    'soccer_fa_cup': 132,
    'soccer_champ': 48,
    'soccer_l1': 108,
    'soccer_l2': 109,
    'soccer_wc': 77,
    'soccer_champions_league': 42,
    'soccer_europa_league': 73
}

# ================= AHL CONFIGURATION =================
AHL_API_KEYS = [
    "ccb91f29d6744675", "694cfeed58c932ee", "50c2cd9b5e18e390"
]

TZ_OFFSETS = {
    "EST": -5, "EDT": -4, "CST": -6, "CDT": -5,
    "MST": -7, "MDT": -6, "PST": -8, "PDT": -7, "AST": -4, "ADT": -3
}

# ================= AHL TEAMS (Official LeagueStat IDs) =================
AHL_TEAMS = {
    "BRI": {"name": "Bridgeport Islanders", "color": "00539B", "id": "317"},
    "CLT": {"name": "Charlotte Checkers", "color": "C8102E", "id": "384"},
    "CHA": {"name": "Charlotte Checkers", "color": "C8102E", "id": "384"},
    "HFD": {"name": "Hartford Wolf Pack", "color": "0D2240", "id": "307"},
    "HER": {"name": "Hershey Bears", "color": "4F2C1D", "id": "319"},
    "LV":  {"name": "Lehigh Valley Phantoms", "color": "000000", "id": "313"},
    "PRO": {"name": "Providence Bruins", "color": "000000", "id": "309"},
    "SPR": {"name": "Springfield Thunderbirds", "color": "003087", "id": "411"},
    "WBS": {"name": "W-B/Scranton", "color": "000000", "id": "316"},
    "BEL": {"name": "Belleville Senators", "color": "C52032", "id": "413"},
    "CLE": {"name": "Cleveland Monsters", "color": "041E42", "id": "373"},
    "LAV": {"name": "Laval Rocket", "color": "00205B", "id": "415"},
    "ROC": {"name": "Rochester Americans", "color": "00539B", "id": "323"},
    "SYR": {"name": "Syracuse Crunch", "color": "003087", "id": "324"},
    "TOR": {"name": "Toronto Marlies", "color": "00205B", "id": "335"},
    "UTC": {"name": "Utica Comets", "color": "006341", "id": "390"},
    "UTI": {"name": "Utica Comets", "color": "006341", "id": "390"},
    "CHI": {"name": "Chicago Wolves", "color": "7C2529", "id": "330"},
    "GR":  {"name": "Grand Rapids Griffins", "color": "BE1E2D", "id": "328"},
    "IA":  {"name": "Iowa Wild", "color": "154734", "id": "389"},
    "MB":  {"name": "Manitoba Moose", "color": "003E7E", "id": "321"},
    "MIL": {"name": "Milwaukee Admirals", "color": "041E42", "id": "327"},
    "RFD": {"name": "Rockford IceHogs", "color": "CE1126", "id": "372"},
    "TEX": {"name": "Texas Stars", "color": "154734", "id": "380"},
    "ABB": {"name": "Abbotsford Canucks", "color": "00744F", "id": "440"},
    "BAK": {"name": "Bakersfield Condors", "color": "F47A38", "id": "402"},
    "CGY": {"name": "Calgary Wranglers", "color": "C8102E", "id": "444"},
    "CAL": {"name": "Calgary Wranglers", "color": "C8102E", "id": "444"},
    "CV":  {"name": "Coachella Valley", "color": "D32027", "id": "445"},
    "CVF": {"name": "Coachella Valley", "color": "D32027", "id": "445"},
    "COL": {"name": "Colorado Eagles", "color": "003087", "id": "419"},
    "HSK": {"name": "Henderson Silver Knights", "color": "111111", "id": "437"},
    "ONT": {"name": "Ontario Reign", "color": "111111", "id": "403"},
    "SD":  {"name": "San Diego Gulls", "color": "041E42", "id": "404"},
    "SJ":  {"name": "San Jose Barracuda", "color": "006D75", "id": "405"},
    "SJS": {"name": "San Jose Barracuda", "color": "006D75", "id": "405"},
    "TUC": {"name": "Tucson Roadrunners", "color": "8C2633", "id": "412"},
}

# ================= MASTER LEAGUE REGISTRY =================
LEAGUE_OPTIONS = [
    # --- PRO SPORTS ---
    {'id': 'nfl',           'label': 'NFL',                 'type': 'sport', 'default': True,  'fetch': {'path': 'football/nfl', 'team_params': {'limit': 100}, 'type': 'scoreboard'}},
    {'id': 'mlb',           'label': 'MLB',                 'type': 'sport', 'default': True,  'fetch': {'path': 'baseball/mlb', 'team_params': {'limit': 100}, 'type': 'scoreboard'}},
    {'id': 'nhl',           'label': 'NHL',                 'type': 'sport', 'default': True,  'fetch': {'path': 'hockey/nhl', 'team_params': {'limit': 100}, 'type': 'scoreboard'}},
    {'id': 'ahl',           'label': 'AHL',                 'type': 'sport', 'default': True,  'fetch': {'type': 'ahl_native'}}, 
    {'id': 'nba',           'label': 'NBA',                 'type': 'sport', 'default': True,  'fetch': {'path': 'basketball/nba', 'team_params': {'limit': 100}, 'type': 'scoreboard'}},
    # --- COLLEGE SPORTS ---
    {'id': 'ncf_fbs',       'label': 'NCAA (FBS)', 'type': 'sport', 'default': True,  'fetch': {'path': 'football/college-football', 'scoreboard_params': {'groups': '80'}, 'type': 'scoreboard'}},
    {'id': 'ncf_fcs',       'label': 'NCAA (FCS)', 'type': 'sport', 'default': True,  'fetch': {'path': 'football/college-football', 'scoreboard_params': {'groups': '81'}, 'type': 'scoreboard'}},
    # --- SOCCER ---
    {'id': 'soccer_epl',    'label': 'Premier League',       'type': 'sport', 'default': True, 'fetch': {'path': 'soccer/eng.1', 'team_params': {'limit': 50}, 'type': 'scoreboard'}},
    {'id': 'soccer_fa_cup','label': 'FA Cup',                 'type': 'sport', 'default': True, 'fetch': {'path': 'soccer/eng.fa', 'type': 'scoreboard'}},
    {'id': 'soccer_champ', 'label': 'Championship',             'type': 'sport', 'default': True, 'fetch': {'path': 'soccer/eng.2', 'team_params': {'limit': 50}, 'type': 'scoreboard'}},
    {'id': 'soccer_l1',     'label': 'League One',              'type': 'sport', 'default': True, 'fetch': {'path': 'soccer/eng.3', 'team_params': {'limit': 50}, 'type': 'scoreboard'}},
    {'id': 'soccer_l2',     'label': 'League Two',              'type': 'sport', 'default': True, 'fetch': {'path': 'soccer/eng.4', 'team_params': {'limit': 50}, 'type': 'scoreboard'}},
    {'id': 'soccer_wc',     'label': 'FIFA World Cup',         'type': 'sport', 'default': True, 'fetch': {'path': 'soccer/fifa.world', 'team_params': {'limit': 100}, 'type': 'scoreboard'}},
    {'id': 'soccer_champions_league', 'label': 'Champions League', 'type': 'sport', 'default': True, 'fetch': {'path': 'soccer/uefa.champions', 'team_params': {'limit': 50}, 'type': 'scoreboard'}},
    {'id': 'soccer_europa_league',    'label': 'Europa League',    'type': 'sport', 'default': True, 'fetch': {'path': 'soccer/uefa.europa', 'team_params': {'limit': 200}, 'type': 'scoreboard'}},
    # --- OTHERS ---
    {'id': 'hockey_olympics', 'label': 'Olympic Hockey',   'type': 'sport', 'default': True,  'fetch': {'path': 'hockey/mens-olympic-hockey', 'type': 'scoreboard'}},
    # --- RACING ---
    {'id': 'f1',             'label': 'Formula 1',             'type': 'sport', 'default': True,  'fetch': {'path': 'racing/f1', 'type': 'leaderboard'}},
    {'id': 'nascar',         'label': 'NASCAR',                 'type': 'sport', 'default': True,  'fetch': {'path': 'racing/nascar', 'type': 'leaderboard'}},
    # --- UTILITIES ---
    {'id': 'weather',       'label': 'Weather',                'type': 'util',  'default': True},
    {'id': 'clock',         'label': 'Clock',                 'type': 'util',  'default': True},
    # --- STOCKS ---
    {'id': 'stock_tech_ai',    'label': 'Tech / AI Stocks',        'type': 'stock', 'default': True,  'stock_list': ["AAPL", "MSFT", "NVDA", "GOOGL", "AMZN", "META", "TSM", "AVGO", "ORCL", "CRM", "AMD", "IBM", "INTC", "QCOM", "CSCO", "ADBE", "TXN", "AMAT", "INTU", "NOW", "MU"]},
    {'id': 'stock_momentum',   'label': 'Momentum Stocks',         'type': 'stock', 'default': False, 'stock_list': ["COIN", "HOOD", "DKNG", "RBLX", "GME", "AMC", "MARA", "RIOT", "CLSK", "SOFI", "OPEN", "UBER", "DASH", "SHOP", "NET", "SQ", "PYPL", "AFRM", "UPST", "CVNA"]},
    {'id': 'stock_energy',          'label': 'Energy Stocks',         'type': 'stock', 'default': False, 'stock_list': ["XOM", "CVX", "COP", "EOG", "SLB", "MPC", "PSX", "VLO", "OXY", "KMI", "HAL", "BKR", "HES", "DVN", "OKE", "WMB", "CTRA", "FANG", "TTE", "BP"]},
    {'id': 'stock_finance',         'label': 'Financial Stocks',       'type': 'stock', 'default': False, 'stock_list': ["JPM", "BAC", "WFC", "C", "GS", "MS", "BLK", "AXP", "V", "MA", "SCHW", "USB", "PNC", "TFC", "BK", "COF", "SPGI", "MCO", "CB", "PGR"]},
    {'id': 'stock_consumer',        'label': 'Consumer Stocks',       'type': 'stock', 'default': False, 'stock_list': ["WMT", "COST", "TGT", "HD", "LOW", "MCD", "SBUX", "CMG", "NKE", "LULU", "KO", "PEP", "PG", "CL", "KMB", "DIS", "NFLX", "CMCSA", "HLT", "MAR"]},
]

# ================= DEFAULT STATE =================
default_state = {
    'active_sports': { item['id']: item['default'] for item in LEAGUE_OPTIONS },
    'mode': 'all', 
    'layout_mode': 'schedule',
    'my_teams': [], 
    'current_games': [],        
    'buffer_sports': [],
    'buffer_stocks': [],
    'all_teams_data': {}, 
    'debug_mode': False,
    'custom_date': None,
    'weather_city': "New York",
    'weather_lat': 40.7128,
    'weather_lon': -74.0060,
    'utc_offset': -5,
    'show_debug_options': False 
}

DEFAULT_TICKER_SETTINGS = {
    "brightness": 100,
    "scroll_speed": 0.03,
    "scroll_seamless": True,
    "inverted": False,
    "panel_count": 2,
    "live_delay_mode": False,
    "live_delay_seconds": 45
}

# ================= NEW LOAD LOGIC =================
state = default_state.copy()
tickers = {} 

# 1. Load Global Config (Defaults)
if os.path.exists(GLOBAL_CONFIG_FILE):
    try:
        with open(GLOBAL_CONFIG_FILE, 'r') as f:
            loaded = json.load(f)
            # Update state but preserve defaults
            for k, v in loaded.items():
                if k in state:
                    if isinstance(state[k], dict) and isinstance(v, dict):
                        state[k].update(v)
                    else:
                        state[k] = v
    except Exception as e:
        print(f"⚠️ Error loading global config: {e}")

# 2. Load Individual Ticker Files (Robust)
ticker_files = glob.glob(os.path.join(TICKER_DATA_DIR, "*.json"))
print(f"📂 Found {len(ticker_files)} saved tickers in '{TICKER_DATA_DIR}'")

for t_file in ticker_files:
    try:
        with open(t_file, 'r') as f:
            t_data = json.load(f)
            tid = os.path.splitext(os.path.basename(t_file))[0]
            
            # Repair missing keys on load
            if 'settings' not in t_data: t_data['settings'] = DEFAULT_TICKER_SETTINGS.copy()
            if 'my_teams' not in t_data: t_data['my_teams'] = []
            if 'clients' not in t_data: t_data['clients'] = []
            
            tickers[tid] = t_data
    except Exception as e:
        print(f"❌ Failed to load ticker file {t_file}: {e}")


# ================= NEW SAVE FUNCTIONS =================
def save_json_atomically(filepath, data):
    """Safe atomic write helper"""
    temp = f"{filepath}.tmp"
    try:
        with open(temp, 'w') as f:
            json.dump(data, f, indent=4)
        os.replace(temp, filepath)
    except Exception as e:
        print(f"Write error for {filepath}: {e}")

def save_global_config():
    """Saves only the global server settings (weather, sports mode, etc)"""
    try:
        with data_lock:
            # Create a clean copy of state to save
            export_data = {
                'active_sports': state['active_sports'],
                'mode': state['mode'],
                'my_teams': state['my_teams'], # Global default teams
                'weather_city': state['weather_city'],
                'weather_lat': state['weather_lat'],
                'weather_lon': state['weather_lon'],
                'utc_offset': state['utc_offset']
            }
        
        # Atomic Write
        temp = f"{GLOBAL_CONFIG_FILE}.tmp"
        with open(temp, 'w') as f:
            json.dump(export_data, f, indent=4)
        os.replace(temp, GLOBAL_CONFIG_FILE)
    except Exception as e:
        print(f"Error saving global config: {e}")

def save_specific_ticker(tid):
    """Saves ONLY the specified ticker to its own file"""
    if tid not in tickers: return
    
    try:
        data = tickers[tid]
        filepath = os.path.join(TICKER_DATA_DIR, f"{tid}.json")
        temp = f"{filepath}.tmp"
        
        with open(temp, 'w') as f:
            json.dump(data, f, indent=4)
        os.replace(temp, filepath)
        print(f"💾 Saved Ticker: {tid}")
    except Exception as e:
        print(f"Error saving ticker {tid}: {e}")

def save_specific_ticker(tid):
    """Saves ONLY the specified ticker to its own file"""
    if tid not in tickers: return
    try:
        data = tickers[tid]
        filepath = os.path.join(TICKER_DATA_DIR, f"{tid}.json")
        save_json_atomically(filepath, data)
        print(f"💾 Saved Ticker: {tid}")
    except Exception as e:
        print(f"Error saving ticker {tid}: {e}")

def save_config_file():
    """Legacy wrapper: saves global config"""
    save_global_config()

def generate_pairing_code():
    while True:
        code = ''.join(random.choices(string.digits, k=6))
        active_codes = [t.get('pairing_code') for t in tickers.values() if not t.get('paired')]
        if code not in active_codes: return code

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

SOCCER_ABBR_OVERRIDES = {
    "Arsenal": "ARS", "Aston Villa": "AVL", "Bournemouth": "BOU", "Brentford": "BRE",
    "Brighton": "BHA", "Brighton & Hove Albion": "BHA", "Burnley": "BUR", "Chelsea": "CHE",
    "Crystal Palace": "CRY", "Everton": "EVE", "Fulham": "FUL", "Ipswich": "IPS", "Ipswich Town": "IPS",
    "Leeds": "LEE", "Leeds United": "LEE", "Leicester": "LEI", "Leicester City": "LEI",
    "Liverpool": "LIV", "Luton": "LUT", "Luton Town": "LUT", "Man City": "MCI", "Manchester City": "MCI",
    "Man Utd": "MUN", "Manchester United": "MUN", "Newcastle": "NEW", "Newcastle United": "NEW",
    "Nottm Forest": "NFO", "Nottingham Forest": "NFO", "Sheffield Utd": "SHU", "Sheffield United": "SHU",
    "Southampton": "SOU", "Spurs": "TOT", "Tottenham": "TOT", "Tottenham Hotspur": "TOT",
    "West Ham": "WHU", "West Ham United": "WHU", "Wolves": "WOL", "Wolverhampton": "WOL",
    "Blackburn": "BLA", "Blackburn Rovers": "BLA", "Bristol City": "BRC", "Cardiff": "CAR", "Cardiff City": "CAR",
    "Coventry": "COV", "Coventry City": "COV", "Derby": "DER", "Derby County": "DER",
    "Hull": "HUL", "Hull City": "HUL", "Middlesbrough": "MID", "Millwall": "MIL",
    "Norwich": "NOR", "Norwich City": "NOR", "Oxford": "OXF", "Oxford United": "OXF",
    "Plymouth": "PLY", "Plymouth Argyle": "PLY", "Portsmouth": "POR", "Preston": "PNE", "Preston North End": "PNE",
    "QPR": "QPR", "Queens Park Rangers": "QPR", "Sheffield Wed": "SHW", "Sheffield Wednesday": "SHW",
    "Stoke": "STK", "Stoke City": "STK", "Sunderland": "SUN", "Swansea": "SWA", "Swansea City": "SWA",
    "Watford": "WAT", "West Brom": "WBA", "West Bromwich Albion": "WBA",
    "Barnsley": "BAR", "Birmingham": "BIR", "Birmingham City": "BIR", "Blackpool": "BPL",
    "Bolton": "BOL", "Bolton Wanderers": "BOL", "Bristol Rovers": "BRR", "Burton": "BRT", "Burton Albion": "BRT",
    "Cambridge": "CAM", "Cambridge United": "CAM", "Charlton": "CHA", "Charlton Athletic": "CHA",
    "Crawley": "CRA", "Crawley Town": "CRA", "Exeter": "EXE", "Exeter City": "EXE",
    "Huddersfield": "HUD", "Huddersfield Town": "HUD", "Leyton Orient": "LEY", "Lincoln": "LIN", "Lincoln City": "LIN",
    "Mansfield": "MAN", "Mansfield Town": "MAN", "Northampton": "NOR", "Northampton Town": "NOR",
    "Peterborough": "PET", "Peterborough United": "PET", "Reading": "REA", "Rotherham": "ROT", "Rotherham United": "ROT",
    "Shrewsbury": "SHR", "Shrewsbury Town": "SHR", "Stevenage": "STE", "Stockport": "STO", "Stockport County": "STO",
    "Wigan": "WIG", "Wigan Athletic": "WIG", "Wrexham": "WRE", "Wycombe": "WYC", "Wycombe Wanderers": "WYC",
    "Accrington": "ACC", "Accrington Stanley": "ACC", "AFC Wimbledon": "WIM", "Barrow": "BRW",
    "Bradford": "BRA", "Bradford City": "BRA", "Bromley": "BRO", "Carlisle": "CAR", "Carlisle United": "CAR",
    "Cheltenham": "CHE", "Cheltenham Town": "CHE", "Chesterfield": "CHF", "Colchester": "COL", "Colchester United": "COL",
    "Crewe": "CRE", "Crewe Alexandra": "CRE", "Doncaster": "DON", "Doncaster Rovers": "DON",
    "Fleetwood": "FLE", "Fleetwood Town": "FLE", "Gillingham": "GIL", "Grimsby": "GRI", "Grimsby Town": "GRI",
    "Harrogate": "HAR", "Harrogate Town": "HAR", "MK Dons": "MKD", "Morecambe": "MOR",
    "Newport": "NEW", "Newport County": "NEW", "Notts Co": "NCO", "Notts County": "NCO",
    "Port Vale": "POR", "Salford": "SAL", "Salford City": "SAL", "Swindon": "SWI", "Swindon Town": "SWI",
    "Tranmere": "TRA", "Tranmere Rovers": "TRA", "Walsall": "WAL"
}

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
ABBR_MAPPING = {
    'SJS': 'SJ', 'TBL': 'TB', 'LAK': 'LA', 'NJD': 'NJ', 'VGK': 'VEG', 'UTA': 'UTAH', 'WSH': 'WSH', 'MTL': 'MTL', 'CHI': 'CHI',
    'NY': 'NYK', 'NO': 'NOP', 'GS': 'GSW', 'SA': 'SAS'
}

SOCCER_COLOR_FALLBACK = {
    "arsenal": "EF0107", "aston villa": "95BFE5", "bournemouth": "DA291C", "brentford": "E30613", "brighton": "0057B8",
    "chelsea": "034694", "crystal palace": "1B458F", "everton": "003399", "fulham": "FFFFFF", "ipswich": "3A64A3",
    "leicester": "0053A0", "liverpool": "C8102E", "manchester city": "6CABDD", "man city": "6CABDD",
    "manchester united": "DA291C", "man utd": "DA291C", "newcastle": "FFFFFF", "nottingham": "DD0000",
    "southampton": "D71920", "tottenham": "FFFFFF", "west ham": "7A263A", "whu": "7A263A", "wes": "7A263A", "wolves": "FDB913",
    "sunderland": "FF0000", "sheffield united": "EE2737", "burnley": "6C1D45", "luton": "F78F1E", 
    "leeds": "FFCD00", "west brom": "122F67", "wba": "122F67", "watford": "FBEE23", "norwich": "FFF200", "hull": "F5A91D",
    "stoke": "E03A3E", "middlesbrough": "E03A3E", "coventry": "00AEEF", "preston": "FFFFFF", "bristol city": "E03A3E",
    "portsmouth": "001489", "derby": "FFFFFF", "blackburn": "009EE0", "sheffield wed": "0E00F0", "oxford": "F1C40F",
    "qpr": "0053A0", "swansea": "FFFFFF", "cardiff": "0070B5", "millwall": "001E4D", "plymouth": "003A26",
    "grimsby": "FFFFFF", "gri": "FFFFFF", "wrexham": "D71920", "birmingham": "0000FF", "huddersfield": "0072CE", "stockport": "005DA4", 
    "lincoln": "D71920", "reading": "004494", "blackpool": "F68712", "peterborough": "005090",
    "charlton": "Dadd22", "bristol rovers": "003399", "shrewsbury": "0066CC", "leyton orient": "C70000",
    "mansfield": "F5A91D", "wycombe": "88D1F1", "bolton": "FFFFFF", "barnsley": "D71920", "rotherham": "D71920",
    "wigan": "0000FF", "exeter": "D71920", "crawley": "D71920", "northampton": "800000", "cambridge": "FDB913",
    "burton": "FDB913", "port vale": "FFFFFF", "walsall": "D71920", "doncaster": "D71920", "notts county": "FFFFFF",
    "gillingham": "0000FF", "mk dons": "FFFFFF", "chesterfield": "0000FF", "barrow": "FFFFFF", "bradford": "F5A91D",
    "afc wimbledon": "0000FF", "bromley": "000000", "colchester": "0000FF", "crewe": "D71920", "harrogate": "FDB913",
    "morecambe": "D71920", "newport": "F5A91D", "salford": "D71920", "swindon": "D71920", "tranmere": "FFFFFF",
    "barcelona": "A50044", "real madrid": "FEBE10", "atlético": "CB3524", "bayern": "DC052D", "dortmund": "FDE100",
    "psg": "004170", "juventus": "FFFFFF", "milan": "FB090B", "inter": "010E80", "napoli": "003B94",
    "ajax": "D2122E", "feyenoord": "FF0000", "psv": "FF0000", "benfica": "FF0000", "porto": "00529F", 
    "sporting": "008000", "celtic": "008000", "rangers": "0000FF", "braga": "E03A3E", "sc braga": "E03A3E"
}

SPORT_DURATIONS = {
    'nfl': 195, 'ncf_fbs': 210, 'ncf_fcs': 195,
    'nba': 150, 'nhl': 150, 'mlb': 180, 'weather': 60, 'soccer': 115
}

# ================= FETCHING LOGIC =================

def validate_logo_url(base_id):
    """Checks if the _90 logo exists; falls back to standard if not."""
    url_90 = f"https://assets.leaguestat.com/ahl/logos/50x50/{base_id}_90.png"
    try:
        r = requests.head(url_90, timeout=1)
        if r.status_code == 200:
            return url_90
    except: pass
    return f"https://assets.leaguestat.com/ahl/logos/50x50/{base_id}.png"

class WeatherFetcher:
    def __init__(self, initial_lat=40.7128, initial_lon=-74.0060, city="New York"):
        self.lat = initial_lat
        self.lon = initial_lon
        self.city_name = city
        self.last_fetch = 0
        self.cache = None
        # Use pooled session for Weather too
        self.session = build_pooled_session(pool_size=10)

    def update_config(self, city=None, lat=None, lon=None):
        if lat is not None: self.lat = lat
        if lon is not None: self.lon = lon
        if city is not None: self.city_name = city
        self.last_fetch = 0 

    def get_weather_icon(self, wmo_code):
        code = int(wmo_code)
        if code == 0: return 'sun'
        if code in [1, 2, 3, 45, 48]: return 'cloud'
        if code in [51, 53, 55, 56, 57, 61, 63, 65, 66, 67, 80, 81, 82]: return 'rain'
        if code in [71, 73, 75, 77, 85, 86]: return 'snow'
        if code in [95, 96, 99]: return 'storm'
        return 'cloud'

    def get_day_name(self, date_str):
        try:
            date_obj = dt.strptime(date_str, '%Y-%m-%d')
            return date_obj.strftime('%a').upper()
        except: return "DAY"

    def get_weather(self):
        if time.time() - self.last_fetch < 900 and self.cache: return self.cache
        
        try:
            w_url = f"https://api.open-meteo.com/v1/forecast?latitude={self.lat}&longitude={self.lon}&current=temperature_2m,weather_code&daily=weather_code,temperature_2m_max,temperature_2m_min,uv_index_max&temperature_unit=fahrenheit&timezone=auto"
            w_res = self.session.get(w_url, timeout=5).json()

            a_url = f"https://air-quality-api.open-meteo.com/v1/air-quality?latitude={self.lat}&longitude={self.lon}&current=us_aqi"
            a_res = self.session.get(a_url, timeout=5).json()

            current_temp = int(round(w_res['current']['temperature_2m']))
            current_code = w_res['current']['weather_code']
            current_icon = self.get_weather_icon(current_code)
            
            aqi = a_res.get('current', {}).get('us_aqi', 0)
            uv = w_res['daily']['uv_index_max'][0]

            forecast_list = []
            daily = w_res['daily']
            
            for i in range(0, 5): 
                f_day = {
                    "day": self.get_day_name(daily['time'][i]),
                    "icon": self.get_weather_icon(daily['weather_code'][i]),
                    "high": int(round(daily['temperature_2m_max'][i])),
                    "low": int(round(daily['temperature_2m_min'][i]))
                }
                forecast_list.append(f_day)

            self.cache = {
                "type": "weather",
                "sport": "weather",
                "id": "weather_main",
                "away_abbr": self.city_name.upper(), 
                "home_abbr": str(current_temp), 
                "situation": {
                    "icon": current_icon,
                    "stats": {
                        "aqi": str(aqi),
                        "uv": str(uv)
                    },
                    "forecast": forecast_list
                },
                "home_score": str(current_temp),
                "away_score": "0",
                "status": "Active",
                "is_shown": True
            }
            self.last_fetch = time.time()
            return self.cache

        except Exception as e:
            print(f"Weather fetch failed: {e}")
            return None

# === NEW STOCK FETCHER (Using Finnhub) ===
class StockFetcher:
    def __init__(self):
        self.market_cache = {}
        self.last_fetch = 0
        self.update_interval = STOCKS_UPDATE_INTERVAL
        
        # === ROBUST KEY LOADING ===
        possible_keys = [
            os.getenv('FINNHUB_API_KEY'), # Fallback
            os.getenv('FINNHUB_KEY_1'),
            os.getenv('FINNHUB_KEY_2'),
            os.getenv('FINNHUB_KEY_3'),
            os.getenv('FINNHUB_KEY_4'),
            os.getenv('FINNHUB_KEY_5')
        ]
        self.api_keys = list(set([k for k in possible_keys if k and len(k) > 10]))
        
        if not self.api_keys:
            print("⚠️ FATAL: No Finnhub API keys found! Check .env file.")
            self.safe_sleep_time = 60
        else:
            self.safe_sleep_time = 1.1 / len(self.api_keys)
            print(f"✅ Loaded {len(self.api_keys)} API Keys. Stock Speed: {self.safe_sleep_time:.2f}s per request.")

        self.current_key_index = 0
        self.session = requests.Session()
        self.lists = { item['id']: item['stock_list'] for item in LEAGUE_OPTIONS if item['type'] == 'stock' and 'stock_list' in item }
        self.ETF_DOMAINS = {"QQQ": "invesco.com", "SPY": "spdrs.com", "IWM": "ishares.com", "DIA": "statestreet.com"}
        self.load_cache()

    def load_cache(self):
        if os.path.exists(STOCK_CACHE_FILE):
            try:
                with open(STOCK_CACHE_FILE, 'r') as f: self.market_cache = json.load(f)
            except: pass

    def save_cache(self):
        try: save_json_atomically(STOCK_CACHE_FILE, self.market_cache)
        except: pass

    def get_logo_url(self, symbol):
        sym = symbol.upper()
        if sym in self.ETF_DOMAINS: return f"https://logo.clearbit.com/{self.ETF_DOMAINS[sym]}"
        clean_sym = sym.replace('.', '-')
        return f"https://financialmodelingprep.com/image-stock/{clean_sym}.png"

    def _get_next_key(self):
        if not self.api_keys: return None
        key = self.api_keys[self.current_key_index]
        self.current_key_index = (self.current_key_index + 1) % len(self.api_keys)
        return key

    # === HYBRID FETCHER: Tries Quote first, falls back to Candle for After Hours ===
    def _fetch_single_stock(self, symbol):
        api_key = self._get_next_key()
        if not api_key: return None
        
        # 1. Try Standard Quote (Cheaper)
        try:
            r = self.session.get("https://finnhub.io/api/v1/quote", params={'symbol': symbol, 'token': api_key}, timeout=5)
            if r.status_code == 429: time.sleep(2); return None
            r.raise_for_status()
            data = r.json()
            
            # Check for stale data (older than 10 mins)
            ts = data.get('t', 0)
            now_ts = time.time()
            is_stale = (now_ts - ts) > 600
            
            # If fresh, use it
            if not is_stale and data.get('c', 0) > 0:
                price = data.get('c', 0); change_raw = data.get('d', 0); change_pct = data.get('dp', 0)
                return {
                    'symbol': symbol,
                    'price': f"{price:.2f}",
                    'change_amt': f"{'+' if change_raw >= 0 else ''}{change_raw:.2f}",
                    'change_pct': f"{'+' if change_pct >= 0 else ''}{change_pct:.2f}%"
                }
            
            # 2. Fallback to Candle (Expensive but accurate for After Hours)
            # Only use if stale and after 4pm ET
            if is_stale:
                # Get last 30 minutes candles
                to_time = int(now_ts)
                from_time = to_time - 1800 
                c_url = "https://finnhub.io/api/v1/stock/candle"
                c_params = {'symbol': symbol, 'resolution': '1', 'from': from_time, 'to': to_time, 'token': api_key}
                
                c_r = self.session.get(c_url, params=c_params, timeout=5)
                c_data = c_r.json()
                
                if c_data.get('s') == 'ok' and c_data.get('c'):
                    latest_close = c_data['c'][-1]
                    # Calculate change from PREVIOUS CLOSE (from quote endpoint)
                    prev_close = data.get('pc', latest_close)
                    change_raw = latest_close - prev_close
                    change_pct = (change_raw / prev_close) * 100
                    
                    return {
                        'symbol': symbol,
                        'price': f"{latest_close:.2f}",
                        'change_amt': f"{'+' if change_raw >= 0 else ''}{change_raw:.2f}",
                        'change_pct': f"{'+' if change_pct >= 0 else ''}{change_pct:.2f}%"
                    }
            
            # If all else fails, return the stale quote (better than nothing)
            if data.get('c', 0) > 0:
                price = data.get('c', 0); change_raw = data.get('d', 0); change_pct = data.get('dp', 0)
                return {
                    'symbol': symbol,
                    'price': f"{price:.2f}",
                    'change_amt': f"{'+' if change_raw >= 0 else ''}{change_raw:.2f}",
                    'change_pct': f"{'+' if change_pct >= 0 else ''}{change_pct:.2f}%"
                }

        except Exception as e:
            return None
        return None

    def update_market_data(self, active_lists):
        if time.time() - self.last_fetch < self.update_interval: return
        target_symbols = set()
        for list_key in active_lists:
            if list_key in self.lists: target_symbols.update(self.lists[list_key])
        if not target_symbols: return
        
        updated_count = 0
        for symbol in list(target_symbols):
            res = self._fetch_single_stock(symbol)
            if res:
                self.market_cache[res['symbol']] = {'price': res['price'], 'change_amt': res['change_amt'], 'change_pct': res['change_pct']}
                updated_count += 1
            time.sleep(self.safe_sleep_time) 

        if updated_count > 0:
            self.last_fetch = time.time()
            self.save_cache()

    def get_stock_obj(self, symbol, label):
        data = self.market_cache.get(symbol)
        if not data: return None
        return {
            'type': 'stock_ticker', 'sport': 'stock', 'id': f"stk_{symbol}", 'status': label, 'tourney_name': label,
            'state': 'in', 'is_shown': True, 'home_abbr': symbol, 
            'home_score': data['price'], 'away_score': data['change_pct'],
            'home_logo': self.get_logo_url(symbol), 'situation': {'change': data['change_amt']}, 
            'home_color': '#FFFFFF', 'away_color': '#FFFFFF'
        }

    def get_list(self, list_key):
        res = []
        label_item = next((item for item in LEAGUE_OPTIONS if item['id'] == list_key), None)
        label = label_item['label'] if label_item else "MARKET"
        for sym in self.lists.get(list_key, []):
            obj = self.get_stock_obj(sym, label)
            if obj: res.append(obj)
        return res

# === ROBUST SPORTS FETCHER (From Old Code) ===
class SportsFetcher:
    def __init__(self, initial_city, initial_lat, initial_lon):
        self.weather = WeatherFetcher(initial_lat=initial_lat, initial_lon=initial_lon, city=initial_city)
        # Using NEW STOCK FETCHER HERE
        self.stocks = StockFetcher()
        self.possession_cache = {} 
        self.base_url = 'http://site.api.espn.com/apis/site/v2/sports/'
        # Use Pooled session
        self.session = build_pooled_session(pool_size=50)
        self.executor = concurrent.futures.ThreadPoolExecutor(max_workers=10) 
        
        # === HISTORY BUFFER FOR PER-TICKER DELAY ===
        self.history_buffer = [] # List of tuples: (timestamp, data_snapshot)
        self.consecutive_empty_fetches = 0

        # === ADDED FOR AHL ===
        self.ahl_cached_key = None
        self.ahl_key_expiry = 0
        # =====================
        
        self.leagues = { 
            item['id']: item['fetch'] 
            for item in LEAGUE_OPTIONS 
            if item['type'] == 'sport' and 'fetch' in item 
        }

    def get_corrected_logo(self, league_key, abbr, default_logo):
        return LOGO_OVERRIDES.get(f"{league_key.upper()}:{abbr}", default_logo)

    def lookup_team_info_from_cache(self, league, abbr, name=None):
        search_abbr = ABBR_MAPPING.get(abbr, abbr)
        
        # 0. Check Hardcoded Fallback for Soccer first (fixes broken colors for big teams)
        if 'soccer' in league:
            name_check = name.lower() if name else ""
            abbr_check = search_abbr.lower()
            for k, v in SOCCER_COLOR_FALLBACK.items():
                if k in name_check or k == abbr_check:
                        return {'color': v, 'alt_color': '444444'}

        try:
            with data_lock:
                teams = state['all_teams_data'].get(league, [])
                
                # 1. Try Exact Abbreviation Match
                for t in teams:
                    if t['abbr'] == search_abbr:
                        return {'color': t.get('color', '000000'), 'alt_color': t.get('alt_color', '444444')}
                
                # 2. Try Name Match (Fuzzy) if name provided
                if name:
                    name_lower = name.lower()
                    for t in teams:
                        t_name = t.get('name', '').lower()
                        t_short = t.get('shortName', '').lower()
                        
                        if (name_lower in t_name) or (t_name in name_lower) or \
                           (name_lower in t_short) or (t_short in name_lower):
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

    def _fetch_simple_league(self, league_key, catalog):
        config = self.leagues[league_key]
        if 'team_params' not in config: return
        try:
            r = self.session.get(f"{self.base_url}{config['path']}/teams", params=config['team_params'], headers=HEADERS, timeout=10)
            data = r.json()
            if 'sports' in data:
                for sport in data['sports']:
                    for league in sport['leagues']:
                        for item in league.get('teams', []):
                            abbr = item['team'].get('abbreviation', 'unk')
                            
                            # === FORCE SCOPED ID (Standardization) ===
                            # This ensures the App receives "nfl:NYG", not just "NYG"
                            scoped_id = f"{league_key}:{abbr}"
                            
                            clr = item['team'].get('color', '000000')
                            alt = item['team'].get('alternateColor', '444444')
                            logo = item['team'].get('logos', [{}])[0].get('href', '')
                            logo = self.get_corrected_logo(league_key, abbr, logo)
                            
                            name = item['team'].get('displayName', '')
                            short_name = item['team'].get('shortDisplayName', '')

                            if not any(x.get('id') == scoped_id for x in catalog[league_key]):
                                catalog[league_key].append({
                                    'abbr': abbr, 
                                    'id': scoped_id,  # <--- CRITICAL CHANGE
                                    'logo': logo, 
                                    'color': clr, 
                                    'alt_color': alt, 
                                    'name': name,
                                    'shortName': short_name
                                })
        except Exception as e: print(f"Error fetching teams for {league_key}: {e}")

    def fetch_all_teams(self):
        try:
            teams_catalog = {k: [] for k in self.leagues.keys()}
            
            # 1. AHL (Already Scoped in previous step, but ensuring call)
            self._fetch_ahl_teams_reference(teams_catalog)

            # 2. Olympic Hockey
            for t in OLYMPIC_HOCKEY_TEAMS:
                teams_catalog['hockey_olympics'].append({
                    'abbr': t['abbr'], 
                    'id': f"hockey_olympics:{t['abbr']}", # Force Scope
                    'logo': t['logo'], 
                    'color': '000000', 
                    'alt_color': '444444'
                })

            # 3. College Football (FBS/FCS)
            url = f"{self.base_url}football/college-football/teams"
            r = self.session.get(url, params={'limit': 1000, 'groups': '80,81'}, headers=HEADERS, timeout=10) 
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
                                scoped_id = f"ncf_fbs:{t_abbr}"
                                if not any(x['id'] == scoped_id for x in teams_catalog['ncf_fbs']):
                                    teams_catalog['ncf_fbs'].append({'abbr': t_abbr, 'id': scoped_id, 'logo': t_logo, 'color': t_clr, 'alt_color': t_alt})
                            
                            elif t_abbr in FCS_TEAMS:
                                t_logo = self.get_corrected_logo('ncf_fcs', t_abbr, t_logo)
                                scoped_id = f"ncf_fcs:{t_abbr}"
                                if not any(x['id'] == scoped_id for x in teams_catalog['ncf_fcs']):
                                    teams_catalog['ncf_fcs'].append({'abbr': t_abbr, 'id': scoped_id, 'logo': t_logo, 'color': t_clr, 'alt_color': t_alt})

            # 4. Standard Leagues
            futures = []
            leagues_to_fetch = [
                'nfl', 'mlb', 'nhl', 'nba',
                'soccer_epl', 'soccer_fa_cup', 'soccer_champ', 'soccer_l1', 'soccer_l2', 'soccer_wc', 'soccer_champions_league', 'soccer_europa_league'
            ]
            for lk in leagues_to_fetch:
                if lk in self.leagues:
                    futures.append(self.executor.submit(self._fetch_simple_league, lk, teams_catalog))
            concurrent.futures.wait(futures)

            with data_lock: state['all_teams_data'] = teams_catalog
        except Exception as e: print(f"Global Team Fetch Error: {e}")
            
    # ================= NEW AHL METHODS =================
    def _get_ahl_key(self):
        if self.ahl_cached_key and time.time() < self.ahl_key_expiry:
            return self.ahl_cached_key

        # Try to detect key
        for key in AHL_API_KEYS:
            try:
                params = {"feed": "modulekit", "view": "seasons", "key": key, "client_code": "ahl", "lang": "en", "fmt": "json", "league_id": 4}
                r = self.session.get("https://lscluster.hockeytech.com/feed/index.php", params=params, timeout=3)
                if r.status_code == 200:
                    data = r.json()
                    if "SiteKit" in data or "Seasons" in data:
                        self.ahl_cached_key = key
                        self.ahl_key_expiry = time.time() + 7200 # Cache for 2 hours
                        return key
            except: continue
        return AHL_API_KEYS[0] # Fallback

    def _fetch_ahl_teams_reference(self, catalog):
        """Fetch Official AHL Teams with Scoped IDs (ahl:LV)"""
        if 'ahl' not in self.leagues: return
        
        catalog['ahl'] = []
        seen_ids = set() 
        
        for code, meta in AHL_TEAMS.items():
            t_id = meta.get('id')
            if t_id and t_id in seen_ids: continue
            if t_id: seen_ids.add(t_id)

            # Standard Logo URL
            logo_url = f"https://assets.leaguestat.com/ahl/logos/50x50/{t_id}.png" if t_id else ""

            # === FIX: SCOPED ID ===
            # We now prepend 'ahl:' to the ID so it never clashes with NFL
            scoped_id = f"ahl:{code}"
            
            catalog['ahl'].append({
                'abbr': code, 
                'id': scoped_id,  # <--- CHANGED THIS
                'real_id': t_id,
                'logo': logo_url, 
                'color': meta.get('color', '000000'), 
                'alt_color': '444444', 
                'name': meta.get('name', code), 
                'shortName': meta.get('name', code).split(" ")[-1]
            })

    def check_shootout(self, game, summary=None):
        """
        Check if a game ended in a shootout using multiple detection methods.
        Adapted from the working reference code.
        """
        # Check 1: Game summary fields (most reliable)
        if summary:
            if summary.get("hasShootout"): return True
            if summary.get("shootoutDetails"): return True
            
            # Check for shootout section in summary
            so_section = (
                summary.get("shootout") or summary.get("Shootout") or 
                summary.get("shootOut") or summary.get("SO")
            )
            if so_section: return True
            
            # Check summary status for shootout keywords
            summary_status = str(
                summary.get("gameStatusString") or summary.get("gameStatus") or 
                summary.get("status") or ""
            ).lower()
            if "so" in summary_status or "shootout" in summary_status or "s/o" in summary_status:
                return True
        
        # Check 2: Period data from game scorebar object
        period = str(game.get("Period", "") or game.get("period", ""))
        period_name = str(game.get("PeriodNameShort", "") or game.get("periodNameShort", "")).upper()
        
        # Period 5 = shootout in hockey
        if period == "5": return True
        
        # PeriodNameShort == "SO" indicates shootout
        if period_name == "SO" or "SHOOTOUT" in period_name: return True
        
        # Check 3: Status string keywords in scorebar object
        status = str(
            game.get("GameStatusString") or game.get("game_status") or 
            game.get("GameStatusStringLong") or ""
        ).lower()
        
        if "so" in status or "shootout" in status or "s/o" in status:
            return True
            
        return False

    def _fetch_ahl(self, conf, visible_start_utc, visible_end_utc):
        games_found = []
        if not conf['active_sports'].get('ahl', False): return []

        try:
            key = self._get_ahl_key()
            
            # Fetch Scorebar
            req_date = visible_start_utc.astimezone(timezone(timedelta(hours=conf.get('utc_offset', -5)))).strftime("%Y-%m-%d")

            params = {
                "feed": "modulekit", "view": "scorebar", "key": key,
                "client_code": "ahl", "lang": "en", "fmt": "json", 
                "league_id": 4, "site_id": 0
            }
            
            r = self.session.get("https://lscluster.hockeytech.com/feed/index.php", params=params, timeout=5)
            if r.status_code != 200: return []
            
            data = r.json()
            scorebar = data.get("SiteKit", {}).get("Scorebar", [])

            # Get reference to pre-validated teams list for Logos
            ahl_refs = state['all_teams_data'].get('ahl', [])

            for g in scorebar:
                # 1. Date Filter
                g_date_str = g.get("Date", "")
                
                gid = g.get("ID")
                h_code = g.get("HomeCode", "").upper()
                a_code = g.get("VisitorCode", "").upper()
                h_sc = str(g.get("HomeGoals", "0"))
                a_sc = str(g.get("VisitorGoals", "0"))
                
                # --- TIME PARSING (ISO8601) ---
                parsed_utc = ""
                iso_date = g.get("GameDateISO8601", "")
                if iso_date:
                    try:
                        dt_obj = dt.fromisoformat(iso_date)
                        parsed_utc = dt_obj.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                    except: pass
                
                if not parsed_utc:
                    raw_time = (g.get("GameTime") or g.get("Time") or "").strip()
                    parsed_utc = f"{g_date_str}T00:00:00Z" # Fallback
                    try:
                        tm_match = re.search(r"(\d+:\d+)\s*(am|pm)(?:\s*([A-Z]+))?", raw_time, re.IGNORECASE)
                        if tm_match:
                            time_str, meridiem, tz_str = tm_match.groups()
                            offset = -5
                            if tz_str: offset = TZ_OFFSETS.get(tz_str.upper(), -5)
                            dt_obj = dt.strptime(f"{g_date_str} {time_str} {meridiem}", "%Y-%m-%d %I:%M %p")
                            dt_obj = dt_obj.replace(tzinfo=timezone(timedelta(hours=offset)))
                            parsed_utc = dt_obj.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                    except: pass
                
                if g_date_str != req_date: continue

                # --- STATUS PARSING ---
                raw_status = g.get("GameStatusString", "")
                status_lower = raw_status.lower()
                period_str = str(g.get("Period", ""))
                
                disp = "Scheduled"; gst = "pre"

                if "final" in status_lower:
                    gst = "post"
                    
                    # === INTEGRATED SHOOTOUT CHECK ===
                    summary_data = None
                    try:
                        sum_params = {
                            "feed": "statviewfeed", "view": "gameSummary", "key": key,
                            "client_code": "ahl", "lang": "en", "fmt": "json", "game_id": gid
                        }
                        r_sum = self.session.get("https://lscluster.hockeytech.com/feed/index.php", params=sum_params, timeout=4)
                        if r_sum.status_code == 200:
                            text = r_sum.text.strip()
                            if text.startswith("(") and text.endswith(")"):
                                text = text[1:-1]
                            summary_data = json.loads(text)
                    except: pass

                    is_shootout = self.check_shootout(g, summary_data)
                    
                    if is_shootout:
                        disp = "FINAL S/O"
                    elif period_str == "4" or "ot" in status_lower or "overtime" in status_lower:
                        disp = "FINAL OT"
                    else:
                        if summary_data and (summary_data.get("hasOvertime") or "OT" in str(summary_data.get("periodNameShort", "")).upper()):
                             disp = "FINAL OT"
                        else:
                             disp = "FINAL"

                # === FIX: DETECT TIME-ONLY STRINGS AS PRE-GAME ===
                # We check for "scheduled", "pre", OR if the string looks like "7:00 pm"
                # We also exclude strings that contain period info (1st, 2nd, 3rd, OT) to avoid catching live clocks
                elif "scheduled" in status_lower or "pre" in status_lower or (re.search(r'\d+:\d+', status_lower) and "1st" not in status_lower and "2nd" not in status_lower and "3rd" not in status_lower and "ot" not in status_lower):
                    gst = "pre"
                    try:
                         if iso_date:
                            local_dt = dt.fromisoformat(iso_date).astimezone(timezone(timedelta(hours=conf.get('utc_offset', -5))))
                            disp = local_dt.strftime("%I:%M %p").lstrip('0')
                         else:
                             raw_time_clean = (g.get("GameTime") or "").strip()
                             # Simple cleanup to ensure it looks like "7:00 PM"
                             disp = raw_time_clean.split(" ")[0] + " " + raw_time_clean.split(" ")[1]
                    except: disp = "Scheduled"
                else:
                    gst = "in"
                    # Live Logic
                    if "intermission" in status_lower:
                        if "1st" in status_lower: disp = "End 1st"
                        elif "2nd" in status_lower: disp = "End 2nd"
                        elif "3rd" in status_lower: disp = "End 3rd"
                        else: disp = "INT"
                    else:
                        m = re.search(r'(\d+:\d+)\s*(1st|2nd|3rd|ot|overtime)', raw_status, re.IGNORECASE)
                        if m:
                            clk = m.group(1); prd = m.group(2).lower()
                            p_lbl = "OT" if "ot" in prd else f"P{prd[0]}"
                            disp = f"{p_lbl} {clk}"
                        else: disp = raw_status

                # --- MODE FILTER ---
                is_shown = True
                if conf['mode'] == 'live' and gst != 'in': is_shown = False
                elif conf['mode'] == 'my_teams':
                    h_name_chk = AHL_TEAMS.get(h_code, {}).get("name", "")
                    a_name_chk = AHL_TEAMS.get(a_code, {}).get("name", "")
                    match_found = False
                    for team_ref in conf['my_teams']:
                        if team_ref in [h_code, a_code, h_name_chk, a_name_chk]:
                            match_found = True; break
                    if not match_found: is_shown = False

                # --- LOGO LOOKUP ---
                h_obj = next((t for t in ahl_refs if t['abbr'] == h_code), None)
                a_obj = next((t for t in ahl_refs if t['abbr'] == a_code), None)
                
                if not h_obj:
                    h_meta_raw = AHL_TEAMS.get(h_code)
                    if h_meta_raw: h_obj = next((t for t in ahl_refs if t.get('real_id') == h_meta_raw.get('id')), None)
                if not a_obj:
                    a_meta_raw = AHL_TEAMS.get(a_code)
                    if a_meta_raw: a_obj = next((t for t in ahl_refs if t.get('real_id') == a_meta_raw.get('id')), None)
                
                h_logo = h_obj['logo'] if h_obj else ""
                a_logo = a_obj['logo'] if a_obj else ""
                
                h_meta = AHL_TEAMS.get(h_code, {"color": "000000"})
                a_meta = AHL_TEAMS.get(a_code, {"color": "000000"})

                games_found.append({
                    'type': 'scoreboard', 'sport': 'ahl', 'id': f"ahl_{gid}",
                    'status': disp, 'state': gst, 'is_shown': is_shown,
                    'home_abbr': h_code, 'home_score': h_sc, 'home_logo': h_logo,
                    'away_abbr': a_code, 'away_score': a_sc, 'away_logo': a_logo,
                    'home_color': f"#{h_meta.get('color','000000')}", 'away_color': f"#{a_meta.get('color','000000')}",
                    'home_alt_color': '#444444', 'away_alt_color': '#444444',
                    'startTimeUTC': parsed_utc, 'situation': {}
                })
        except Exception as e:
            print(f"AHL Fetch Error: {e}")
        
        return games_found
    # ===============================================

    # === NHL NATIVE FETCHER ===
    def fetch_shootout_details(self, game_id, away_id, home_id):
        try:
            url = f"https://api-web.nhle.com/v1/gamecenter/{game_id}/play-by-play"
            r = self.session.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=3)
            if r.status_code != 200: return None
            data = r.json(); plays = data.get("plays", [])
            native_away = data.get("awayTeam", {}).get("id")
            native_home = data.get("homeTeam", {}).get("id")
            results = {'away': [], 'home': []}
            for play in plays:
                if play.get("periodDescriptor", {}).get("periodType") != "SO": continue
                type_key = play.get("typeDescKey")
                if type_key not in {"goal", "shot-on-goal", "missed-shot"}: continue
                details = play.get("details", {})
                team_id = details.get("eventOwnerTeamId")
                res_code = "goal" if type_key == "goal" else "miss"
                if team_id == native_away: results['away'].append(res_code)
                elif team_id == native_home: results['home'].append(res_code)
            return results
        except: return None

    def _fetch_nhl_landing(self, gid):
        try:
            r = self.session.get(f"https://api-web.nhle.com/v1/gamecenter/{gid}/landing", headers=HEADERS, timeout=2)
            if r.status_code == 200: return r.json()
        except: pass
        return None

    def _fetch_nhl_native(self, conf, window_start_utc, window_end_utc, visible_start_utc, visible_end_utc):
        games_found = []
        is_nhl = conf['active_sports'].get('nhl', False)
        if not is_nhl: return []
        
        processed_ids = set()
        try:
            r = self.session.get("https://api-web.nhle.com/v1/schedule/now", headers=HEADERS, timeout=5)
            if r.status_code != 200: return []
            
            landing_futures = {} 

            for d in r.json().get('gameWeek', []):
                for g in d.get('games', []):
                    try:
                        g_utc = g.get('startTimeUTC')
                        if not g_utc: continue
                        g_dt = dt.fromisoformat(g_utc.replace('Z', '+00:00'))
                        if not (window_start_utc <= g_dt <= window_end_utc): continue
                    except: continue

                    gid = g['id']
                    if gid in processed_ids: continue
                    processed_ids.add(gid)
                    
                    st = g.get('gameState', 'OFF')
                    if st in ['LIVE', 'CRIT', 'FINAL', 'OFF']:
                        landing_futures[gid] = self.executor.submit(self._fetch_nhl_landing, gid)
            
            processed_ids.clear() 
            for d in r.json().get('gameWeek', []):
                for g in d.get('games', []):
                    try:
                        g_utc = g.get('startTimeUTC')
                        if not g_utc: continue
                        g_dt = dt.fromisoformat(g_utc.replace('Z', '+00:00'))
                        
                        if g_dt < visible_start_utc or g_dt >= visible_end_utc:
                            st = g.get('gameState', 'OFF')
                            if st not in ['LIVE', 'CRIT']:
                                continue
                    except: continue

                    gid = g['id']
                    if gid in processed_ids: continue
                    processed_ids.add(gid)

                    st = g.get('gameState', 'OFF')
                    map_st = 'in' if st in ['LIVE', 'CRIT'] else ('pre' if st in ['PRE', 'FUT'] else 'post')

                    h_ab = g['homeTeam']['abbrev']; a_ab = g['awayTeam']['abbrev']
                    h_sc = str(g['homeTeam'].get('score', 0)); a_sc = str(g['awayTeam'].get('score', 0))
                    
                    h_lg = self.get_corrected_logo('nhl', h_ab, f"https://a.espncdn.com/i/teamlogos/nhl/500/{h_ab.lower()}.png")
                    a_lg = self.get_corrected_logo('nhl', a_ab, f"https://a.espncdn.com/i/teamlogos/nhl/500/{a_ab.lower()}.png")
                    h_info = self.lookup_team_info_from_cache('nhl', h_ab)
                    a_info = self.lookup_team_info_from_cache('nhl', a_ab)
                    
                    mode = conf['mode']; my_teams = conf['my_teams']
                    is_shown = True
                    if mode == 'live' and map_st != 'in': is_shown = False
                    if mode == 'my_teams':
                        h_k = f"nhl:{h_ab}"; a_k = f"nhl:{a_ab}"
                        if (h_k not in my_teams and h_ab not in my_teams) and (a_k not in my_teams and a_ab not in my_teams): is_shown = False
                    
                    if st in ['SUSP', 'SUSPENDED', 'PPD', 'POSTPONED']:
                        is_shown = False
                        map_st = 'post'

                    disp = "Scheduled"; pp = False; poss = ""; en = False; shootout_data = None 
                    dur = self.calculate_game_timing('nhl', g_utc, 1, st)
                    
                    g_local = g_dt.astimezone(timezone(timedelta(hours=conf.get('utc_offset', -5))))

                    if st in ['PRE', 'FUT']:
                          try: disp = g_local.strftime("%I:%M %p").lstrip('0')
                          except: pass
                    elif st in ['FINAL', 'OFF']:
                          disp = "FINAL"
                          pd = g.get('periodDescriptor', {})
                          if pd.get('periodType', '') == 'SHOOTOUT' or pd.get('number', 0) >= 5: disp = "FINAL S/O"
                          elif pd.get('periodType', '') == 'OT' or pd.get('number', 0) == 4: disp = "FINAL OT"

                    if gid in landing_futures:
                        try:
                            d2 = landing_futures[gid].result()
                            if d2:
                                h_sc = str(d2['homeTeam'].get('score', h_sc)); a_sc = str(d2['awayTeam'].get('score', a_sc))
                                pd = d2.get('periodDescriptor', {})
                                clk = d2.get('clock', {}); time_rem = clk.get('timeRemaining', '00:00')
                                p_type = pd.get('periodType', '')
                                
                                if st in ['FINAL', 'OFF']:
                                    p_num_final = pd.get('number', 3)
                                    if p_type == 'SHOOTOUT' or p_num_final >= 5: disp = "FINAL S/O"
                                    elif p_type == 'OT' or p_num_final == 4: disp = "FINAL OT"
                                
                                p_num = pd.get('number', 1)

                                if p_type == 'SHOOTOUT' or p_num >= 5:
                                    if map_st == 'in': disp = "S/O"
                                    shootout_data = self.fetch_shootout_details(gid, 0, 0)
                                else:
                                    if map_st == 'in':
                                        if clk.get('inIntermission', False) or time_rem == "00:00":
                                            if p_num == 1: disp = "End 1st"
                                            elif p_num == 2: disp = "End 2nd"
                                            elif p_num == 3: disp = "End 3rd"
                                            else: disp = "End OT"
                                        else:
                                            if p_num == 4:
                                                p_lbl = "OT"
                                            else:
                                                p_lbl = f"P{p_num}"
                                            
                                            disp = f"{p_lbl} {time_rem}"
                                    
                                sit_obj = d2.get('situation', {})
                                if sit_obj:
                                    sit = sit_obj.get('situationCode', '1551')
                                    ag = int(sit[0]); as_ = int(sit[1]); hs = int(sit[2]); hg = int(sit[3])
                                    if as_ > hs: pp=True; poss=a_ab
                                    elif hs > as_: pp=True; poss=h_ab
                                    en = (ag==0 or hg==0)
                        except: pass 

                    if "FINAL" in disp:
                        shootout_data = None

                    games_found.append({
                        'type': 'scoreboard',
                        'sport': 'nhl', 'id': str(gid), 'status': disp, 'state': map_st, 'is_shown': is_shown,
                        'home_abbr': h_ab, 'home_score': h_sc, 'home_logo': h_lg, 'home_id': h_ab,
                        'away_abbr': a_ab, 'away_score': a_sc, 'away_logo': a_lg, 'away_id': a_ab,
                        'home_color': f"#{h_info['color']}", 'home_alt_color': f"#{h_info['alt_color']}",
                        'away_color': f"#{a_info['color']}", 'away_alt_color': f"#{a_info['alt_color']}",
                        'startTimeUTC': g_utc,
                        'estimated_duration': dur,
                        'situation': { 'powerPlay': pp, 'possession': poss, 'emptyNet': en, 'shootout': shootout_data }
                    })
            return games_found
        except: return []

    # === FOTMOB SOCCER FETCHER ===
    
    # -- Helpers from working script --
    def parse_side_list(self, side_list):
        seq = []
        for attempt in side_list or []:
            if not isinstance(attempt, dict):
                seq.append("pending")
                continue
            result = (attempt.get("result") or attempt.get("outcome") or "").lower()
            if result in {"goal", "scored", "score", "converted"}:
                seq.append("goal")
                continue
            if result in {"miss", "missed", "failed", "saved", "fail"}:
                seq.append("miss")
                continue
            if attempt.get("scored") is True:
                seq.append("goal")
                continue
            if attempt.get("scored") is False:
                seq.append("miss")
                continue
            seq.append("pending")
        return seq

    def parse_shootout(self, raw, home_id=None, away_id=None, general_home=None, general_away=None):
        if not raw:
            return [], [], None, None

        pen_home_score = raw.get("homeScore") if isinstance(raw, dict) else None
        pen_away_score = raw.get("awayScore") if isinstance(raw, dict) else None

        for hk, ak in (("home", "away"), ("homeTeam", "awayTeam"), ("homePenalties", "awayPenalties")):
            if hk in raw or ak in raw:
                return (
                    self.parse_side_list(raw.get(hk) or []),
                    self.parse_side_list(raw.get(ak) or []),
                    pen_home_score,
                    pen_away_score,
                )

        seq = raw.get("sequence") if isinstance(raw, dict) else raw if isinstance(raw, list) else []
        home_seq, away_seq = [], []
        for attempt in seq or []:
            if not isinstance(attempt, dict):
                continue
            team_id = attempt.get("teamId") or attempt.get("team")
            side = attempt.get("side") or attempt.get("teamSide")
            is_home = False
            if team_id is not None:
                is_home = team_id in {home_id, general_home} if home_id or general_home else False
                if not is_home:
                    is_home = team_id not in {away_id, general_away} if (home_id or general_home) else False
            elif isinstance(side, str):
                is_home = side.lower() in {"home", "h"}

            parsed = self.parse_side_list([attempt])[0]
            (home_seq if is_home else away_seq).append(parsed)

        return home_seq, away_seq, pen_home_score, pen_away_score

    def parse_shootout_events(self, events_container, home_id=None, away_id=None, general_home=None, general_away=None):
        if not isinstance(events_container, dict):
            return [], [], None, None

        pen_events = events_container.get("penaltyShootoutEvents") or []
        home_seq, away_seq = [], []
        pen_home_score = pen_away_score = None

        def classify(event):
            text = (event.get("result") or event.get("outcome") or event.get("type") or "").lower()
            if "goal" in text: return "goal"
            if "miss" in text or "fail" in text or "save" in text: return "miss"
            if event.get("scored") is True: return "goal"
            if event.get("scored") is False: return "miss"
            return "pending"

        for ev in pen_events:
            if not isinstance(ev, dict): continue

            score = ev.get("penShootoutScore")
            if isinstance(score, (list, tuple)) and len(score) >= 2:
                pen_home_score, pen_away_score = score[0], score[1]

            is_home = None
            if ev.get("isHome") is not None:
                is_home = bool(ev.get("isHome"))
            if is_home is None:
                team_id = ev.get("teamId") or (ev.get("shotmapEvent") or {}).get("teamId")
                if team_id is not None:
                    if home_id or general_home:
                        is_home = team_id in {home_id, general_home}
                    elif away_id or general_away:
                        is_home = team_id not in {away_id, general_away}
            if is_home is None:
                side = ev.get("side")
                if isinstance(side, str):
                    is_home = side.lower().startswith("h")
            if is_home is None:
                is_home = True

            outcome = classify(ev)
            (home_seq if is_home else away_seq).append(outcome)

        return home_seq, away_seq, pen_home_score, pen_away_score

    def _fetch_fotmob_details(self, match_id, home_id=None, away_id=None):
        try:
            url = f"https://www.fotmob.com/api/matchDetails?matchId={match_id}"
            resp = self.session.get(url, headers=HEADERS, timeout=10)
            resp.raise_for_status()
            payload = resp.json()
            
            info = payload.get("general", {})
            general_home = (info.get("homeTeam") or {}).get("id")
            general_away = (info.get("awayTeam") or {}).get("id")

            containers = [
                payload.get("shootout"),
                payload.get("content", {}).get("shootout"),
                payload.get("content", {}).get("penaltyShootout"),
            ]
            
            home_shootout, away_shootout = [], []
            for raw in containers:
                h, a, _, _ = self.parse_shootout(raw, home_id, away_id, general_home, general_away)
                if h or a:
                    home_shootout, away_shootout = h, a
                    break
            
            if not home_shootout and not away_shootout and payload.get("content", {}).get("matchFacts"):
                events_container = payload["content"].get("matchFacts", {}).get("events")
                h, a, _, _ = self.parse_shootout_events(events_container, home_id, away_id, general_home, general_away)
                if h or a:
                    home_shootout, away_shootout = h, a
                    
            if home_shootout or away_shootout:
                return {'home': home_shootout, 'away': away_shootout}
            return None
        except: return None

    # --- Helper for Robust Score Parsing ---
    def _parse_score_str(self, score_str):
        if not score_str or "-" not in str(score_str):
            return None, None
        try:
            home_raw, away_raw = [part.strip() for part in str(score_str).split("-", 1)]
            home_val = int(home_raw) if home_raw.isdigit() else None
            away_val = int(away_raw) if away_raw.isdigit() else None
            return home_val, away_val
        except Exception:
            return None, None

    # --- Helper for Live Clock with Seconds ---
    def _format_live_clock(self, status: dict, fallback_text: str = "") -> str | None:
        """Format live match time as MM:SS' or base+extra:SS' when in added time."""

        def _render_clock(minutes: int, seconds: int, max_time: int | None) -> str:
            if max_time is not None and minutes > max_time:
                extra_total = minutes * 60 + seconds - max_time * 60
                extra_min, extra_sec = divmod(extra_total, 60)
                return f"{max_time}+{extra_min:02d}:{extra_sec:02d}'"
            return f"{minutes:02d}:{seconds:02d}'"

        if not isinstance(status, dict):
            return None

        live_time = status.get("liveTime") or status.get("live_time") or {}
        max_time = None
        if isinstance(live_time, dict):
            max_time_raw = live_time.get("maxTime") or live_time.get("max_time")
            if isinstance(max_time_raw, (int, float)) or (isinstance(max_time_raw, str) and max_time_raw.isdigit()):
                max_time = int(float(max_time_raw))

            long_val = live_time.get("long") or live_time.get("clock") or live_time.get("elapsed")
            if long_val:
                text = str(long_val)
                plus_match = re.match(r"\s*(\d+)\+(\d+)(?::(\d{1,2}))?", text)
                if plus_match:
                    base = int(plus_match.group(1))
                    extra_min = int(plus_match.group(2))
                    extra_sec = int(plus_match.group(3) or 0)
                    return f"{base}+{extra_min:02d}:{extra_sec:02d}'"

                clock_match = re.match(r"\s*(\d+):(\d{1,2})", text)
                if clock_match:
                    minutes = int(clock_match.group(1))
                    seconds = int(clock_match.group(2))
                    return _render_clock(minutes, seconds, max_time)

            # Explicit minute/second fields if present
            minute_val = live_time.get("minute")
            second_val = live_time.get("second")
            if minute_val is not None and second_val is not None:
                try:
                    minutes = int(minute_val)
                    seconds = int(second_val)
                    return _render_clock(minutes, seconds, max_time)
                except Exception:
                    pass

            short_val = live_time.get("short")
            if short_val:
                short_match = re.match(r"\s*(\d+)(?:\+(\d+))?'", str(short_val))
                if short_match:
                    base = int(short_match.group(1))
                    extra = int(short_match.group(2) or 0)
                    if extra:
                        return f"{base}+{extra:02d}:00'"
                    return f"{base:02d}:00'"

        if fallback_text:
            text = str(fallback_text)
            text_match = re.search(r"(\d+)(?:\+(\d+))?'", text)
            if text_match:
                base = int(text_match.group(1))
                extra = int(text_match.group(2) or 0)
                if extra:
                    return f"{base}+{extra:02d}:00'"
                return f"{base:02d}:00'"

        return None

    def _extract_matches(self, sections, internal_id, conf, start_window, end_window, visible_start_utc, visible_end_utc):
        matches = []
        for section in sections:
            candidate_matches = section.get("matches") if isinstance(section, dict) else None
            if candidate_matches is None: candidate_matches = [section]
            
            for match in candidate_matches:
                if not isinstance(match, dict): continue
                
                status = match.get("status") or {}
                kickoff = status.get("utcTime") or match.get("time")
                if not kickoff: continue
                
                # --- TIME WINDOW CHECK ---
                try:
                    match_dt = dt.fromisoformat(kickoff.replace('Z', '+00:00'))
                    if not (start_window <= match_dt <= end_window): continue
                except: continue

                mid = match.get("id")
                h_name = match.get("home", {}).get("name") or "Home"
                a_name = match.get("away", {}).get("name") or "Away"
                
                # --- ABBREVIATION LOGIC ---
                h_ab = SOCCER_ABBR_OVERRIDES.get(h_name, h_name[:3].upper())
                a_ab = SOCCER_ABBR_OVERRIDES.get(a_name, a_name[:3].upper())
                
                finished = bool(status.get("finished"))
                started = bool(status.get("started"))
                reason = (status.get("reason") or {}).get("short") or ""
                
                # === ROBUST SCORE EXTRACTION LOGIC ===
                home_score = (match.get("home") or {}).get("score")
                away_score = (match.get("away") or {}).get("score")

                # 1. Check status.score / status.current
                status_score = status.get("score") or status.get("current") or {}
                if isinstance(status_score, dict):
                    if home_score is None: home_score = status_score.get("home")
                    if away_score is None: away_score = status_score.get("away")
                    
                    # 2. Check FT / Fulltime
                    for key in ("ft", "fulltime"):
                        ft_score = status_score.get(key)
                        if isinstance(ft_score, (list, tuple)) and len(ft_score) >= 2:
                            if home_score is None: home_score = ft_score[0]
                            if away_score is None: away_score = ft_score[1]
                elif isinstance(status_score, (list, tuple)) and len(status_score) >= 2:
                    if home_score is None: home_score = status_score[0]
                    if away_score is None: away_score = status_score[1]

                # 3. String Fallback
                score_str_sources = [
                    status.get("scoreStr"),
                    (match.get("home") or {}).get("scoreStr"),
                    (match.get("away") or {}).get("scoreStr"),
                    status.get("statusText") if "-" in str(status.get("statusText", "")) else None 
                ]

                for s_str in score_str_sources:
                    if home_score is not None and away_score is not None: break
                    h_val, a_val = self._parse_score_str(s_str)
                    if home_score is None: home_score = h_val
                    if away_score is None: away_score = a_val

                final_home_score = str(home_score) if home_score is not None else "0"
                final_away_score = str(away_score) if away_score is not None else "0"
                # ======================================

                # Determine state/status
                gst = 'pre'
                
                try:
                    k_dt = dt.fromisoformat(kickoff.replace('Z', '+00:00'))
                    local_k = k_dt.astimezone(timezone(timedelta(hours=conf.get('utc_offset', -5))))
                    disp = local_k.strftime("%I:%M %p").lstrip('0')
                except:
                    disp = kickoff.split("T")[1][:5]

                if started and not finished:
                    gst = 'in'
                    # Use the new seconds-aware formatter
                    clock_str = self._format_live_clock(status, match.get("status_text"))
                    if clock_str:
                        disp = clock_str
                    else:
                        disp = "In Progress"
                    
                    # ----------------------------------------------------
                    # FIX: Handle Extra Time Break (105+ Added) correctly
                    # ----------------------------------------------------
                    # 1. Get Current Minute Safely
                    current_minute = 0
                    try:
                        current_minute = int((status.get("liveTime") or {}).get("minute", 0))
                    except: pass

                    # 2. Check for Halftime / Breaks (including PET which some feeds use for break)
                    raw_status_text = str(status.get("statusText", ""))
                    is_ht = (
                        reason == "HT" 
                        or raw_status_text == "HT" 
                        or "Halftime" in raw_status_text
                        or status.get("liveTime", {}).get("short") == "HT"
                        or reason == "PET" 
                    )
                    
                    if is_ht:
                        if current_minute >= 105:
                            disp = "HT ET"
                        else:
                            disp = "HALF"
                    # ----------------------------------------------------

                elif finished:
                    gst = 'post'
                    disp = "Final" 
                    if "AET" in reason: disp = "Final AET"
                    if "Pen" in reason or (status.get("reason") and "Pen" in str(status.get("reason"))):
                        disp = "FIN"

                elif status.get("cancelled"):
                    gst = 'post'
                    disp = "Postponed"
                
                if "Postponed" in reason or "PPD" in reason:
                    gst = 'post'
                    disp = "Postponed"

                # === HIDE FINAL GAMES BEFORE CUTOFF ===
                if match_dt < visible_start_utc or match_dt >= visible_end_utc:
                      if gst != 'in': continue
                # =======================================

                # Shootout check
                is_shootout = False
                if "Pen" in reason or (gst == 'in' and "Pen" in str(status)) or disp == "FIN":
                    is_shootout = True
                    if gst == 'in': disp = "Pens"
                
                shootout_data = None
                if is_shootout:
                    shootout_data = self._fetch_fotmob_details(mid, match.get("home", {}).get("id"), match.get("away", {}).get("id"))

                # Filtering (Mode)
                is_shown = True
                if conf['mode'] == 'live' and gst != 'in': is_shown = False
                elif conf['mode'] == 'my_teams':
                    # Strict My Teams Logic for Soccer
                    h_k = f"{internal_id}:{h_ab}"; a_k = f"{internal_id}:{a_ab}"
                    match_found = False
                    for team_ref in conf['my_teams']:
                        if team_ref == h_k or team_ref == a_k or team_ref == h_ab or team_ref == a_ab:
                            match_found = True; break
                    if not match_found: is_shown = False
                
                if "Postponed" in disp or "PPD" in reason or status.get("cancelled"):
                    is_shown = False

                # Build Game Object
                h_id = match.get("home", {}).get("id")
                a_id = match.get("away", {}).get("id")

                h_info = self.lookup_team_info_from_cache(internal_id, h_ab, h_name)
                a_info = self.lookup_team_info_from_cache(internal_id, a_ab, a_name)
                
                matches.append({
                    'type': 'scoreboard',
                    'sport': internal_id, 
                    'id': str(mid), 
                    'status': disp, 
                    'state': gst, 
                    'is_shown': is_shown,
                    'home_abbr': h_ab, 'home_score': final_home_score, 
                    'home_logo': f"https://images.fotmob.com/image_resources/logo/teamlogo/{h_id}.png",
                    'away_abbr': a_ab, 'away_score': final_away_score, 
                    'away_logo': f"https://images.fotmob.com/image_resources/logo/teamlogo/{a_id}.png",
                    'home_color': f"#{h_info['color']}", 'home_alt_color': f"#{h_info['alt_color']}",
                    'away_color': f"#{a_info['color']}", 'away_alt_color': f"#{a_info['alt_color']}",
                    'startTimeUTC': kickoff,
                    'estimated_duration': 115,
                    'situation': { 'possession': '', 'shootout': shootout_data }
                })
        return matches

    def _fetch_fotmob_league(self, league_id, internal_id, conf, start_window, end_window, visible_start_utc, visible_end_utc):
        try:
            url = "https://www.fotmob.com/api/leagues"
            last_sections = []
            
            # Iterate types like working script
            for l_type in ("cup", "league", None):
                # --- CACHE BUSTING: Added timestamp param ---
                params = {"id": league_id, "tab": "matches", "timeZone": "UTC", "type": l_type, "_": int(time.time())}
                
                try:
                    resp = self.session.get(url, params=params, headers=HEADERS, timeout=10)
                    resp.raise_for_status()
                    payload = resp.json()
                    
                    sections = payload.get("matches", {}).get("allMatches", [])
                    if not sections:
                        sections = payload.get("fixtures", {}).get("allMatches", [])
                    
                    last_sections = sections
                    # Pass the UTC window here
                    matches = self._extract_matches(sections, internal_id, conf, start_window, end_window, visible_start_utc, visible_end_utc)
                    if matches: return matches
                except: continue
            
            # Fallback if loop finishes empty
            if last_sections:
                 return self._extract_matches(last_sections, internal_id, conf, start_window, end_window, visible_start_utc, visible_end_utc)
            return []
        except Exception as e:
            print(f"FotMob League {league_id} error: {e}")
            return []

    # Helper function for threaded execution
    def fetch_single_league(self, league_key, config, conf, window_start_utc, window_end_utc, utc_offset, visible_start_utc, visible_end_utc):
        local_games = []
        if not conf['active_sports'].get(league_key, False): return []

        # Racing Leaderboard
        if config.get('type') == 'leaderboard':
            return local_games

        # ESPN Scoreboard
        try:
            curr_p = config.get('scoreboard_params', {}).copy()
            
            now_utc = dt.now(timezone.utc)
            now_local = now_utc.astimezone(timezone(timedelta(hours=utc_offset)))
            
            yesterday_str = (now_local - timedelta(days=1)).strftime("%Y%m%d")
            tomorrow_str = (now_local + timedelta(days=1)).strftime("%Y%m%d")
            
            if conf['debug_mode'] and conf['custom_date']:
                curr_p['dates'] = conf['custom_date'].replace('-', '')
            else:
                curr_p['dates'] = f"{yesterday_str}-{tomorrow_str}"
            
            r = self.session.get(f"{self.base_url}{config['path']}/scoreboard", params=curr_p, headers=HEADERS, timeout=5)
            data = r.json()
            
            events = data.get('events', [])
            if not events:
                leagues = data.get('leagues', [])
                if leagues and len(leagues) > 0:
                    events = leagues[0].get('events', [])
            
            for e in events:
                utc_str = e['date'].replace('Z', '')
                st = e.get('status', {})
                tp = st.get('type', {})
                gst = tp.get('state', 'pre')
                
                try:
                    game_dt = dt.fromisoformat(utc_str).replace(tzinfo=timezone.utc)
                    if gst != 'in' and gst != 'half':
                        if not (window_start_utc <= game_dt <= window_end_utc): continue
                    
                    if game_dt < visible_start_utc or game_dt >= visible_end_utc:
                          if gst not in ['in', 'half']:
                              continue
                except: continue

                comp = e['competitions'][0]
                h = comp['competitors'][0]
                a = comp['competitors'][1]
                h_ab = h['team'].get('abbreviation', 'UNK')
                a_ab = a['team'].get('abbreviation', 'UNK')
                
                if league_key == 'ncf_fbs' and h_ab not in FBS_TEAMS and a_ab not in FBS_TEAMS: continue
                if league_key == 'ncf_fcs' and h_ab not in FCS_TEAMS and a_ab not in FCS_TEAMS: continue

                # === CHANGED: Default is_shown to True. Filtering happens in get_ticker_data ===
                is_shown = True 
                
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

                is_suspended = False
                susp_keywords = ["Suspended", "Postponed", "Canceled", "Delayed", "PPD"]
                for kw in susp_keywords:
                    if kw in s_disp:
                        is_suspended = True
                        break
                
                if is_suspended:
                    is_shown = False

                if not is_suspended:
                    if gst == 'pre':
                        try: s_disp = game_dt.astimezone(timezone(timedelta(hours=utc_offset))).strftime("%I:%M %p").lstrip('0')
                        except: pass
                    elif gst == 'in' or gst == 'half':
                        clk = st.get('displayClock', '0:00').replace("'", "")
                        if gst == 'half' or (p == 2 and clk == '0:00' and 'football' in config['path']): s_disp = "Halftime"
                        elif 'hockey' in config['path'] and clk == '0:00':
                                if p == 1: s_disp = "End 1st"
                                elif p == 2: s_disp = "End 2nd"
                                elif p == 3: s_disp = "End 3rd"
                                else: s_disp = "Intermission"
                        else:
                            if 'soccer' in config['path']:
                                in_extra = p >= 3 or 'ET' in tp.get('shortDetail', '')
                                if in_extra:
                                    if gst == 'half' or tp.get('shortDetail') in ['Halftime', 'HT', 'ET HT']: s_disp = "ET HT"
                                    else: s_disp = f"ET {clk}'"
                                else:
                                    s_disp = f"{clk}'"
                                    if gst == 'half' or tp.get('shortDetail') in ['Halftime', 'HT']: s_disp = "Half"
                            elif 'basketball' in config['path']:
                                if p > 4: s_disp = f"OT{p-4 if p-4>1 else ''} {clk}"
                                else: s_disp = f"Q{p} {clk}"
                            elif 'football' in config['path']:
                                if p > 4: s_disp = f"OT{p-4 if p-4>1 else ''} {clk}"
                                else: s_disp = f"Q{p} {clk}"
                            elif 'hockey' in config['path']:
                                if p > 3: s_disp = f"OT{p-3 if p-3>1 else ''} {clk}"
                                else: s_disp = f"P{p} {clk}"
                            elif 'baseball' in config['path']:
                                short_detail = tp.get('shortDetail', s_disp)
                                s_disp = short_detail.replace(" - ", " ").replace("Inning", "In")
                            else: s_disp = f"P{p} {clk}"

                s_disp = s_disp.replace("Final", "FINAL").replace("/OT", " OT").replace("/SO", " S/O")
                s_disp = s_disp.replace("End of ", "End ").replace(" Quarter", "").replace(" Inning", "").replace(" Period", "")

                if "FINAL" in s_disp:
                    if league_key == 'nhl':
                        if "SO" in s_disp or "Shootout" in s_disp or p >= 5: s_disp = "FINAL S/O"
                        elif p >= 4 and "OT" not in s_disp: s_disp = f"FINAL OT{p-3 if p-3>1 else ''}"
                    elif league_key in ['nba', 'nfl', 'ncf_fbs', 'ncf_fcs'] and p > 4 and "OT" not in s_disp:
                         s_disp = f"FINAL OT{p-4 if p-4>1 else ''}"

                sit = comp.get('situation', {})
                shootout_data = None
                is_shootout = "Shootout" in s_disp or "Penalties" in s_disp or "S/O" in s_disp or (gst == 'in' and st.get('period', 1) > 4 and 'hockey' in league_key)
                
                poss_raw = sit.get('possession')
                if poss_raw: self.possession_cache[e['id']] = poss_raw
                elif gst in ['in', 'half'] and e['id'] in self.possession_cache: poss_raw = self.possession_cache[e['id']]
                
                if gst == 'pre' or gst == 'post' or gst == 'final' or s_disp == 'Halftime' or is_suspended:
                    poss_raw = None
                    self.possession_cache.pop(e['id'], None)

                poss_abbr = ""
                if str(poss_raw) == str(h['team'].get('id')): poss_abbr = h_ab
                elif str(poss_raw) == str(a['team'].get('id')): poss_abbr = a_ab
                
                down_text = sit.get('downDistanceText') or sit.get('shortDownDistanceText') or ''
                if s_disp == "Halftime": down_text = ''

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
                        'powerPlay': False, 
                        'emptyNet': False
                    }
                }
                if league_key == 'mlb':
                    game_obj['situation'].update({'balls': sit.get('balls', 0), 'strikes': sit.get('strikes', 0), 'outs': sit.get('outs', 0), 
                        'onFirst': sit.get('onFirst', False), 'onSecond': sit.get('onSecond', False), 'onThird': sit.get('onThird', False)})
                local_games.append(game_obj)
        except Exception as e: print(f"Error fetching {league_key}: {e}")
        return local_games

    def update_buffer_sports(self):
        all_games = []
        with data_lock: 
            conf = state.copy()

        # 1. WEATHER & CLOCK (Simple, fast)
        if conf['active_sports'].get('weather'):
            if (conf['weather_lat'] != self.weather.lat or 
                conf['weather_lon'] != self.weather.lon or 
                conf['weather_city'] != self.weather.city_name):
                self.weather.update_config(city=conf['weather_city'], lat=conf['weather_lat'], lon=conf['weather_lon'])
            w = self.weather.get_weather()
            if w: all_games.append(w)

        if conf['active_sports'].get('clock'):
            all_games.append({'type':'clock','sport':'clock','id':'clk','is_shown':True})

        # 2. SPORTS (Parallelized)
        if conf['mode'] in ['sports', 'live', 'my_teams', 'all']:
            # Calculate Time Windows once
            utc_offset = conf.get('utc_offset', -5)
            now_utc = dt.now(timezone.utc)
            now_local = now_utc.astimezone(timezone(timedelta(hours=utc_offset)))
            
            # --- DATE LOGIC UPDATE (3:00 AM Switch with Strict Start/End) ---
            if now_local.hour < 3:
                # "Yesterday's Games" mode (Late Night Viewing)
                visible_start_local = (now_local - timedelta(days=1)).replace(hour=10, minute=0, second=0, microsecond=0)
                visible_end_local = now_local.replace(hour=3, minute=0, second=0, microsecond=0)
            else:
                # "Today's Games" mode (Morning/Day Viewing)
                visible_start_local = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
                visible_end_local = (now_local + timedelta(days=1)).replace(hour=3, minute=0, second=0, microsecond=0)
            
            visible_start_utc = visible_start_local.astimezone(timezone.utc)
            visible_end_utc = visible_end_local.astimezone(timezone.utc)
            
            # Windows for Fetching
            window_start_local = now_local - timedelta(hours=30)
            window_end_local = now_local + timedelta(hours=48)
            
            window_start_utc = window_start_local.astimezone(timezone.utc)
            window_end_utc = window_end_local.astimezone(timezone.utc)
            
            futures = []

            # === ADDED AHL ===
            if conf['active_sports'].get('ahl', False):
                futures.append(self.executor.submit(self._fetch_ahl, conf, visible_start_utc, visible_end_utc))
            
            # A. NHL Native Special Case
            if conf['active_sports'].get('nhl', False) and not conf['debug_mode']:
                futures.append(self.executor.submit(self._fetch_nhl_native, conf, window_start_utc, window_end_utc, visible_start_utc, visible_end_utc))
            
            # B. FOTMOB SOCCER (Batched by League ID)
            for internal_id, fid in FOTMOB_LEAGUE_MAP.items():
                if conf['active_sports'].get(internal_id, False):
                        futures.append(self.executor.submit(self._fetch_fotmob_league, fid, internal_id, conf, window_start_utc, window_end_utc, visible_start_utc, visible_end_utc))

            # C. All other ESPN leagues
            for league_key, config in self.leagues.items():
                if league_key == 'nhl' and not conf['debug_mode']: continue 
                if league_key.startswith('soccer_'): continue
                if league_key == 'ahl': continue

                futures.append(self.executor.submit(
                    self.fetch_single_league, 
                    league_key, config, conf, window_start_utc, window_end_utc, utc_offset, visible_start_utc, visible_end_utc
                ))
            
            for f in concurrent.futures.as_completed(futures):
                try:
                    res = f.result()
                    if res: all_games.extend(res)
                except Exception as e: print(f"League fetch error: {e}")

        # === SAFETY FIX: Prevent "Crash into Stocks" ===
        sports_count = len([g for g in all_games if g.get('type') == 'scoreboard'])
        
        with data_lock:
            prev_buffer = state.get('buffer_sports', [])
            prev_sports_count = len([g for g in prev_buffer if g.get('type') == 'scoreboard'])

        if sports_count == 0 and prev_sports_count > 0:
            self.consecutive_empty_fetches += 1
            if self.consecutive_empty_fetches < 3:
                prev_pure_sports = [g for g in prev_buffer if g.get('type') == 'scoreboard']
                utils = [g for g in all_games if g.get('type') != 'scoreboard']
                all_games = prev_pure_sports + utils
            else:
                self.consecutive_empty_fetches = 0
        else:
            self.consecutive_empty_fetches = 0

        # ==========================================================
        # === TIME NORMALIZATION (Fixes AHL Sorting Issue) ===
        # ==========================================================
        for g in all_games:
            ts = g.get('startTimeUTC')
            if ts and isinstance(ts, str):
                try:
                    # 1. Parse whatever format the API gave us (handles 'Z' or no 'Z', seconds or no seconds)
                    d = dt.fromisoformat(ts.replace('Z', '+00:00'))
                    # 2. Overwrite with STRICT uniform format including seconds
                    g['startTimeUTC'] = d.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                except: pass

        # === FIX FOR JUMPING: SORT SPORTS GAMES ===
        all_games.sort(key=lambda x: (
            0 if x.get('type') == 'clock' else
            1 if x.get('type') == 'weather' else
            4 if any(k in str(x.get('status', '')).lower() for k in ["postponed", "cancelled", "canceled", "suspended", "ppd"]) else
            3 if "FINAL" in str(x.get('status', '')).upper() or "FIN" == str(x.get('status', '')) else
            2, # Active
            x.get('startTimeUTC', '9999'), # Now normalized, safe to sort as string
            x.get('sport', ''),
            x.get('id', '0')
        ))

        # === HISTORY BUFFER UPDATE ===
        now_ts = time.time()
        self.history_buffer.append((now_ts, all_games))
        cutoff_time = now_ts - 120
        self.history_buffer = [x for x in self.history_buffer if x[0] > cutoff_time]
        
        with data_lock: 
            state['buffer_sports'] = all_games
            self.merge_buffers()

    def get_snapshot_for_delay(self, delay_seconds):
        # 1. If delay is 0 or negative, return latest
        if delay_seconds <= 0 or not self.history_buffer:
            with data_lock:
                return state.get('current_games', [])
        
        # 2. Find closest snapshot
        target_time = time.time() - delay_seconds
        closest = min(self.history_buffer, key=lambda x: abs(x[0] - target_time))
        # closest is (timestamp, list_of_games)
        
        # 3. We need to apply the filtering logic (Stocks/Weather merge) to this snapshot too
        # But 'merge_buffers' relies on global state buffers.
        # To avoid complexity, we assume the sports snapshot is what changes, 
        # and we merge it with the *current* stock buffer (stocks don't need second-by-second delay usually)
        sports_snap = closest[1]
        
        with data_lock:
            stocks_snap = state.get('buffer_stocks', [])
            mode = state['mode']
        
        # Reuse merge logic manually
        utils = [g for g in sports_snap if g.get('type') == 'weather' or g.get('sport') == 'clock']
        pure_sports = [g for g in sports_snap if g not in utils]
        
        if mode == 'stocks': return stocks_snap
        elif mode == 'weather': return [g for g in utils if g.get('type') == 'weather']
        elif mode == 'clock': return [g for g in utils if g.get('sport') == 'clock']
        elif mode in ['sports', 'live', 'my_teams']: return pure_sports
        else: return pure_sports # Removed utils from here

    def update_buffer_stocks(self):
        games = []
        with data_lock: conf = state.copy()
        
        if conf['mode'] in ['stocks', 'all']:
            # Dynamically get stock lists from LEAGUE_OPTIONS
            cats = [item['id'] for item in LEAGUE_OPTIONS if item['type'] == 'stock']
            
            for cat in cats:
                if conf['active_sports'].get(cat): games.extend(self.stocks.get_list(cat))
        
        with data_lock:
            state['buffer_stocks'] = games
            self.merge_buffers()

    def merge_buffers(self):
        mode = state['mode']
        final_list = []
        
        # Raw buffers (Latest)
        sports_buffer = state.get('buffer_sports', [])
        stocks_buffer = state.get('buffer_stocks', [])
        
        utils = [g for g in sports_buffer if g.get('type') == 'weather' or g.get('sport') == 'clock']
        pure_sports = [g for g in sports_buffer if g not in utils]

        if mode == 'stocks': final_list = stocks_buffer
        elif mode == 'weather': final_list = [g for g in utils if g.get('type') == 'weather']
        elif mode == 'clock': final_list = [g for g in utils if g.get('sport') == 'clock']
        elif mode in ['sports', 'live', 'my_teams']: final_list = pure_sports
        else: final_list = pure_sports # Removed utils from here

        state['current_games'] = final_list

# Initialize Global Fetcher
fetcher = SportsFetcher(
    initial_city=state['weather_city'], 
    initial_lat=state['weather_lat'], 
    initial_lon=state['weather_lon']
)

def sports_worker():
    try: fetcher.fetch_all_teams()
    except: pass
    while True: 
        try: fetcher.update_buffer_sports()
        except: pass
        time.sleep(SPORTS_UPDATE_INTERVAL)

def stocks_worker():
    while True:
        try: 
            with data_lock:
                active_cats = [k for k, v in state['active_sports'].items() if k.startswith('stock_') and v]
            fetcher.stocks.update_market_data(active_cats)
            fetcher.update_buffer_stocks()
        except Exception as e: 
            print(f"Stock worker error: {e}")
        # Dynamic sleep is handled inside update_market_data, but we need a small loop delay if no stocks active
        time.sleep(1)

# ================= FLASK API =================
app = Flask(__name__)
CORS(app) 

@app.route('/api/config', methods=['POST'])
def api_config():
    try:
        new_data = request.json
        if not isinstance(new_data, dict): return jsonify({"error": "Invalid payload"}), 400
        
        target_id = new_data.get('ticker_id') or request.args.get('id')
        if not target_id:
            cid = request.headers.get('X-Client-ID')
            if cid:
                for tid, t_data in tickers.items():
                    if cid in t_data.get('clients', []):
                        target_id = tid
                        break
        
        if not target_id and len(tickers) == 1: target_id = list(tickers.keys())[0]

        with data_lock:
            # === 1. BUILD LOOKUP TABLE (The "Cheat Sheet") ===
            # This maps "NYG" -> "nfl:NYG", "NYY" -> "mlb:NYY"
            abbr_to_scoped = {}
            if 'all_teams_data' in state:
                for league, teams in state['all_teams_data'].items():
                    for t in teams:
                        # Map the simple abbr to the complex ID
                        if 'abbr' in t and 'id' in t:
                            abbr_to_scoped[t['abbr']] = t['id']
            
            # Manual Overrides for tricky ones
            abbr_to_scoped["LV"] = "ahl:LV"
            abbr_to_scoped["NY"] = "nba:NY" # Default NY to Knicks if ambiguous
            # =================================================

            if new_data.get('weather_city'): 
                fetcher.weather.update_config(city=new_data['weather_city'], lat=new_data.get('weather_lat'), lon=new_data.get('weather_lon'))
            
            allowed_keys = {'active_sports', 'mode', 'layout_mode', 'my_teams', 'debug_mode', 'custom_date', 'weather_city', 'weather_lat', 'weather_lon', 'utc_offset'}
            
            for k, v in new_data.items():
                if k not in allowed_keys: continue
                
                # === TEAM SAVING WITH SMART LOOKUP ===
                if k == 'my_teams' and isinstance(v, list):
                    cleaned = []
                    seen = set()
                    for e in v:
                        if e:
                            k_str = str(e).strip()
                            
                            # A. If it's already correct (has colon), keep it.
                            if ":" in k_str:
                                if k_str not in seen:
                                    seen.add(k_str)
                                    cleaned.append(k_str)
                                continue

                            # B. If it's OLD (no colon), try to LOOK IT UP.
                            if k_str in abbr_to_scoped:
                                fixed_id = abbr_to_scoped[k_str]
                                if fixed_id not in seen:
                                    seen.add(fixed_id)
                                    cleaned.append(fixed_id)
                                    print(f"🔧 Auto-Fixed: {k_str} -> {fixed_id}")
                            else:
                                print(f"⚠️ Could not identify team: {k_str} (Dropped)")
                    
                    if target_id:
                        if 'my_teams' not in tickers[target_id]: tickers[target_id]['my_teams'] = []
                        tickers[target_id]['my_teams'] = cleaned
                        print(f"✅ SAVED for {target_id}: {cleaned}")
                    else:
                        state['my_teams'] = cleaned
                    continue

                if k == 'active_sports' and isinstance(v, dict): 
                    state['active_sports'].update(v)
                    continue
                
                if v is not None: state[k] = v
            
            fetcher.merge_buffers()
        
        if target_id: save_specific_ticker(target_id)
        else: save_global_config()
        
        current_teams = tickers[target_id].get('my_teams', []) if target_id else state['my_teams']
        return jsonify({"status": "ok", "saved_teams": current_teams, "ticker_id": target_id})
        
    except Exception as e:
        print(f"Config Error: {e}") 
        return jsonify({"error": "Failed"}), 500

@app.route('/leagues', methods=['GET'])
def get_league_options():
    # Return just the static list of supported leagues/stocks
    league_meta = []
    for item in LEAGUE_OPTIONS:
         league_meta.append({
             'id': item['id'], 
             'label': item['label'], 
             'type': item['type'],
             'enabled': state['active_sports'].get(item['id'], False)
         })
    return jsonify(league_meta)

@app.route('/data', methods=['GET'])
def get_ticker_data():
    ticker_id = request.args.get('id')
    if not ticker_id: return jsonify({"error": "No ID"}), 400
    
    if ticker_id not in tickers:
        tickers[ticker_id] = { "paired": False, "clients": [], "settings": DEFAULT_TICKER_SETTINGS.copy(), "pairing_code": generate_pairing_code(), "last_seen": time.time(), "name": "New Ticker", "my_teams": [] }
        save_specific_ticker(ticker_id)
    else: 
        tickers[ticker_id]['last_seen'] = time.time()
    
    rec = tickers[ticker_id]
    if not rec.get('clients'): return jsonify({"status": "pairing", "code": rec['pairing_code']})
    
    t_settings = rec['settings']
    delay_seconds = t_settings.get('live_delay_seconds', 0) if t_settings.get('live_delay_mode') else 0
    games_for_ticker = fetcher.get_snapshot_for_delay(delay_seconds)
    
    with data_lock:
        global_mode = state['mode']
        my_teams_list = rec.get('my_teams', state['my_teams'])
        
        conf = { 
            "active_sports": state['active_sports'], 
            "mode": global_mode, 
            "weather": state['weather_city']
        }
    
    visible_games = []
    
    for g in games_for_ticker:
        should_show = True
        if not g.get('is_shown', True): pass 

        if global_mode == 'live':
             if g.get('state') not in ['in', 'half']: should_show = False
             
        elif global_mode == 'my_teams':
            sport = g.get('sport')
            h_abbr = str(g.get('home_abbr', '')).upper()
            a_abbr = str(g.get('away_abbr', '')).upper()
            
            # === STANDARDIZED SCOPED ID CHECK ===
            # Since all teams are now saved as "nfl:NYG", we just construct that ID and check.
            h_scoped = f"{sport}:{h_abbr}"
            a_scoped = f"{sport}:{a_abbr}"
            
            in_home = h_scoped in my_teams_list
            in_away = a_scoped in my_teams_list
            
            if not (in_home or in_away): should_show = False
            # ====================================

        status_lower = str(g.get('status', '')).lower()
        if any(k in status_lower for k in ["postponed", "suspended", "canceled", "ppd"]):
            should_show = False

        if should_show:
            visible_games.append(g)
    
    return jsonify({ 
        "status": "ok", 
        "version": SERVER_VERSION,
        "global_config": conf, 
        "local_config": rec['settings'], 
        "content": { "sports": visible_games } 
    })
    
@app.route('/pair', methods=['POST'])
def pair_ticker():
    cid = request.headers.get('X-Client-ID')
    code = request.json.get('code')
    friendly_name = request.json.get('name', 'My Ticker')
    
    if not cid or not code: return jsonify({"success": False}), 400
    
    for uid, rec in tickers.items():
        if rec.get('pairing_code') == code:
            if cid not in rec['clients']: rec['clients'].append(cid)
            rec['paired'] = True
            rec['name'] = friendly_name
            
            # === FIX: Save to specific file ===
            save_specific_ticker(uid)
            
            return jsonify({"success": True, "ticker_id": uid})
            
    return jsonify({"success": False}), 404

@app.route('/pair/id', methods=['POST'])
def pair_ticker_by_id():
    cid = request.headers.get('X-Client-ID')
    tid = request.json.get('id')
    friendly_name = request.json.get('name', 'My Ticker')
    
    if not cid or not tid: return jsonify({"success": False}), 400
    
    if tid in tickers:
        if cid not in tickers[tid]['clients']: tickers[tid]['clients'].append(cid)
        tickers[tid]['paired'] = True
        tickers[tid]['name'] = friendly_name
        
        # === FIX: Save to specific file ===
        save_specific_ticker(tid)
        
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
    
    # Update memory
    tickers[tid]['settings'].update(request.json)
    
    # === FIX: Save to specific file ===
    save_specific_ticker(tid)
    
    return jsonify({"success": True})

@app.route('/api/state')
def api_state():
    # Return latest games for the UI
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

# === LOGS ENDPOINT (Auto-scrolling HTML) ===
@app.route('/errors', methods=['GET'])
def get_logs():
    log_file = "ticker.log"
    if not os.path.exists(log_file):
        return "Log file not found", 404
    
    try:
        file_size = os.path.getsize(log_file)
        read_size = min(file_size, 102400) # Read last 100KB
        
        log_content = ""
        with open(log_file, 'rb') as f:
            if file_size > read_size:
                f.seek(file_size - read_size)
            data = f.read()
            log_content = data.decode('utf-8', errors='replace')

        # Auto-scrolling HTML wrapper
        html_response = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>Server Logs</title>
            <meta http-equiv="refresh" content="10">
            <style>
                body {{ background-color: #1e1e1e; color: #00ff00; font-family: 'Courier New', monospace; margin: 0; padding: 20px; }}
                pre {{ white-space: pre-wrap; word-wrap: break-word; }}
            </style>
            <script>
                window.onload = function() {{
                    window.scrollTo(0, document.body.scrollHeight);
                }};
            </script>
        </head>
        <body>
            <h3>Last {read_size / 1024:.0f}KB of Logs (Auto-scrolled)</h3>
            <pre>{log_content}</pre>
        </body>
        </html>
        """
        
        response = app.response_class(response=html_response, status=200, mimetype='text/html')
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
        return response

    except Exception as e:
        return f"Error reading log: {str(e)}", 500
@app.route('/api/my_teams', methods=['GET'])
def check_my_teams():
    """
    Usage: 
      Global check: GET /api/my_teams
      Ticker check: GET /api/my_teams?id=YOUR_TICKER_ID
    """
    ticker_id = request.args.get('id')
    
    with data_lock:
        # 1. Global Fallback Check
        global_teams = state.get('my_teams', [])

        if not ticker_id:
            return jsonify({
                "status": "ok",
                "scope": "Global (Default)",
                "count": len(global_teams),
                "teams": global_teams
            })

        # 2. Ticker Specific Check
        if ticker_id in tickers:
            rec = tickers[ticker_id]
            specific_teams = rec.get('my_teams', [])
            
            # Logic: If specific_teams is empty, the ticker uses global_teams
            using_fallback = len(specific_teams) == 0
            effective = global_teams if using_fallback else specific_teams

            return jsonify({
                "status": "ok",
                "ticker_id": ticker_id,
                "scope": "Ticker Specific",
                "using_global_fallback": using_fallback,
                "saved_specifically_for_ticker": specific_teams,
                "what_the_ticker_actually_sees": effective
            })
        
        return jsonify({"error": "Ticker ID not found"}), 404

@app.route('/')
def root(): return "Ticker Server Running"

if __name__ == "__main__":
    # Start separate threads
    threading.Thread(target=sports_worker, daemon=True).start()
    threading.Thread(target=stocks_worker, daemon=True).start()
    
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 5000)))
