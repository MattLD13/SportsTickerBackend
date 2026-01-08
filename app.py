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
        # Sports
        'nfl': True, 'ncf_fbs': True, 'ncf_fcs': True, 'mlb': True, 'nhl': True, 'nba': True, 
        'soccer_epl': True, 'soccer_champ': True, 'soccer_l1': True, 'soccer_l2': True, 
        'soccer_wc': False, 'hockey_olympics': False, 
        'f1': True, 'nascar': True, 'indycar': True, 'wec': False, 'imsa': False,
        
        # Utilities
        'weather': False, 'clock': False,
        
        # Stock Categories (Expanded)
        'stock_movers': True, 'stock_indices': True, 'stock_tech': False, 
        'stock_ai': False, 'stock_consulting': False, 'stock_crypto': False,
        'stock_auto': False, 'stock_semi': False, 'stock_finance': False,
        'stock_energy': False, 'stock_pharma': False, 'stock_consumer': False,
        'stock_nyse': False, 'stock_etf': False, 'stock_commodities': False, 'stock_forex': False
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
ABBR_MAPPING = {
    'SJS': 'SJ', 'TBL': 'TB', 'LAK': 'LA', 'NJD': 'NJ', 'VGK': 'VEG', 'UTA': 'UTAH', 'WSH': 'WSH', 'MTL': 'MTL', 'CHI': 'CHI',
    'NY': 'NYK', 'NO': 'NOP', 'GS': 'GSW', 'SA': 'SAS'
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
        {'type': 'stock_ticker', 'sport': 'stock_tech', 'id': 'demo_tsla', 'status': 'TECH', 'state': 'in', 'is_shown': True,
         'home_abbr': 'TSLA', 'home_score': '184.86', 'away_score': '-1.38%', 'home_logo': 'https://raw.githubusercontent.com/nvstly/icons/main/ticker_icons/TSLA.png',
         'tourney_name': 'TECH', 'situation': {'change': '-2.54'}}
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

class StockFetcher:
    def __init__(self, api_key):
        self.api_key = api_key
        self.cache = {} 
        self.cursor = {} 
        self.last_fetch_times = {} 
        self.fetch_interval = 60 
        
        self.symbols = {
            'stock_indices': ["SPY", "QQQ", "DIA", "IWM", "VOO", "VTI", "IVV", "VEA", "VWO", "TLT", "EEM", "AGG"],
            'stock_tech': ["NVDA", "MSFT", "AAPL", "AMD", "META", "GOOG", "AMZN", "NFLX", "CRM", "ADBE", "CSCO", "INTC", "IBM", "ORCL", "UBER", "ABNB"],
            'stock_ai': ["NVDA", "SMCI", "PLTR", "AI", "GOOG", "MSFT", "AMD", "META", "PATH", "SNOW", "DDOG", "CRWD", "ZS", "PANW"],
            'stock_consulting': ["ACN", "IT", "BAH", "IBM", "SAP", "ORCL", "INFY", "WIT", "CTSH", "EPAM", "GIB", "CACI"],
            'stock_crypto': ["COIN", "MSTR", "MARA", "HOOD", "SQ", "RIOT", "CLSK", "HUT", "BITF", "CORZ", "CIFR", "WULF", "GREE"],
            'stock_auto': ["TSLA", "F", "GM", "TM", "HMC", "RIVN", "LCID", "STLA", "NIO", "XPEV", "LI", "RACE", "TTM"],
            'stock_semi': ["NVDA", "AMD", "INTC", "QCOM", "AVGO", "TXN", "MU", "TSM", "ASML", "LRCX", "AMAT", "ADI", "MRVL", "STM"],
            'stock_finance': ["JPM", "BAC", "GS", "MS", "WFC", "C", "V", "MA", "AXP", "BLK", "SCHW", "PYPL", "USB", "PNC", "TFC"],
            'stock_energy': ["XOM", "CVX", "SHEL", "BP", "COP", "SLB", "EOG", "PXD", "MPC", "PSX", "VLO", "OXY", "HAL", "KMI"],
            'stock_pharma': ["LLY", "JNJ", "PFE", "MRK", "ABBV", "AMGN", "GILD", "BIIB", "REGN", "VRTX", "BMY", "AZN", "SNY", "NVS"],
            'stock_consumer': ["WMT", "TGT", "COST", "HD", "LOW", "NKE", "SBUX", "MCD", "KO", "PEP", "PG", "CL", "KMB", "EL", "LULU"],
            'stock_nyse': ["JPM", "WMT", "PG", "XOM", "JNJ", "V", "MA", "HD", "LLY", "MRK", "KO", "PEP", "BAC", "CVX", "MCD", "DIS", "T", "VZ", "BA", "CAT", "GE", "MMM", "IBM", "GS", "MS", "AXP", "UNH", "CVX", "WFC"],
            'stock_etf': ["SPY", "QQQ", "DIA", "IWM", "VOO", "IVV", "VTI", "VEA", "VWO", "IEFA", "AGG", "BND", "GLD", "SLV", "GDX", "XLE", "XLF", "XLK", "XLV"],
            'stock_commodities': ["GLD", "SLV", "USO", "UNG", "DBC", "GSG", "CORN", "SOYB", "WEAT", "PPLT", "PALL", "CPER"],
            'stock_forex': ["EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD", "USDCHF", "NZDUSD", "EURGBP", "EURJPY", "GBPJPY"]
        }

    def get_logo_url(self, symbol):
        return f"https://raw.githubusercontent.com/nvstly/icons/main/ticker_icons/{symbol.upper()}.png"

    def fetch_movers(self):
        key = 'stock_movers'
        # Fetch every 5 minutes
        if time.time() - self.last_fetch_times.get(key, 0) < 300: return self.cache.get(key, [])
        try:
            url = f"https://www.alphavantage.co/query?function=TOP_GAINERS_LOSERS&apikey={self.api_key}"
            r = requests.get(url, timeout=10)
            data = r.json()
            results = []
            
            # PARSE ALL SECTIONS to get maximum data (~60 stocks)
            if "top_gainers" in data:
                for item in data["top_gainers"]:
                    results.append(self.format_stock_obj(item['ticker'], item['price'], item['change_percentage'], item['change_amount'], "TOP GAINER"))
            if "top_losers" in data:
                for item in data["top_losers"]:
                    results.append(self.format_stock_obj(item['ticker'], item['price'], item['change_percentage'], item['change_amount'], "TOP LOSER"))
            if "most_actively_traded" in data:
                for item in data["most_actively_traded"]:
                    results.append(self.format_stock_obj(item['ticker'], item['price'], item['change_percentage'], item['change_amount'], "ACTIVE"))
            
            self.cache[key] = results
            self.last_fetch_times[key] = time.time()
            return results
        except Exception as e: 
            print(f"Movers Error: {e}")
            return self.cache.get(key, [])

    def fetch_list(self, category_key):
        if category_key not in self.cache: self.cache[category_key] = []
        if category_key not in self.cursor: self.cursor[category_key] = 0
        
        # Round Robin Fetching: Fetch 2 stocks every 60 seconds
        if time.time() - self.last_fetch_times.get(category_key, 0) < self.fetch_interval: 
            return self.cache[category_key]
            
        sym_list = self.symbols.get(category_key, [])
        if not sym_list: return []
        
        # Determine next 2 symbols to fetch
        idx = self.cursor[category_key]
        batch = [sym_list[idx % len(sym_list)]]
        if len(sym_list) > 1:
            batch.append(sym_list[(idx + 1) % len(sym_list)])
            
        try:
            for sym in batch:
                if len(sym) == 6 and category_key == "stock_forex": 
                    # Use Currency endpoint for Forex if needed, or fallback to Quote
                    url = f"https://www.alphavantage.co/query?function=CURRENCY_EXCHANGE_RATE&from_currency={sym[:3]}&to_currency={sym[3:]}&apikey={self.api_key}"
                    r = requests.get(url, timeout=5)
                    d = r.json().get("Realtime Currency Exchange Rate", {})
                    if d:
                        obj = self.format_stock_obj(sym, d.get("05. Exchange Rate"), d.get("09. Ask Price"), "0.00", "FOREX")
                        obj['away_score'] = "" 
                        self.update_cache(category_key, sym, obj)
                else:
                    url = f"https://www.alphavantage.co/query?function=GLOBAL_QUOTE&symbol={sym}&apikey={self.api_key}"
                    r = requests.get(url, timeout=5)
                    data = r.json()
                    q = data.get("Global Quote", {})
                    if q:
                        label = category_key.split('_')[1].upper()
                        if label == "INDICES": label = "INDEX"
                        obj = self.format_stock_obj(q.get("01. symbol"), q.get("05. price"), q.get("10. change percent"), q.get("09. change"), label)
                        self.update_cache(category_key, sym, obj)
                time.sleep(1.1) 
            
            self.cursor[category_key] = (idx + 2) % len(sym_list)
            self.last_fetch_times[category_key] = time.time()
            return self.cache[category_key]
        except Exception as e: return self.cache.get(category_key, [])

    def update_cache(self, key, sym, obj):
        existing = next((i for i, x in enumerate(self.cache[key]) if x['home_abbr'] == sym), None)
        if existing is not None: self.cache[key][existing] = obj
        else: self.cache[key].append(obj)

    def format_stock_obj(self, symbol, price, change_pct, change_amt, status_lbl):
        logo = self.get_logo_url(symbol)
        if not change_pct: change_pct = "0.00%"
        if not change_amt: change_amt = "0.00"
        return {
            'type': 'stock_ticker',
            'sport': 'stock',
            'id': f"stk_{symbol}",
            'status': status_lbl, 
            'tourney_name': status_lbl,
            'state': 'in',
            'is_shown': True,
            'home_abbr': symbol,
            'home_score': str(float(price)) if price else "0.00",
            'away_score': str(change_pct),
            'home_logo': logo,
            'situation': {'change': str(change_amt)}, 
            'home_color': '#FFFFFF', 'away_color': '#FFFFFF'
        }

class SportsFetcher:
    def __init__(self, initial_loc):
        self.weather = WeatherFetcher(initial_loc)
        self.stocks = StockFetcher("JJIKCMZD4EPHMYF0")
        self.possession_cache = {} 
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

    # === NHL NATIVE FETCHER (RESTORED FROM OLD CODE) ===
    def fetch_shootout_details(self, game_id, away_id, home_id):
        try:
            url = f"https://api-web.nhle.com/v1/gamecenter/{game_id}/play-by-play"
            r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=3)
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

    def _fetch_nhl_native(self, games_list, target_date_str):
        with data_lock: 
            is_nhl = state['active_sports'].get('nhl', False)
            utc_offset = state.get('utc_offset', -5)
        if not is_nhl: return
        processed_ids = set()
        try:
            r = requests.get("https://api-web.nhle.com/v1/schedule/now", headers=HEADERS, timeout=5)
            if r.status_code != 200: return
            for d in r.json().get('gameWeek', []):
                day_games = d.get('games', [])
                is_target_date = (d.get('date') == target_date_str)
                has_active_games = any(g.get('gameState') in ['LIVE', 'CRIT'] for g in day_games)
                if is_target_date or has_active_games:
                    for g in day_games:
                        gid = g['id']
                        if gid in processed_ids: continue
                        processed_ids.add(gid)
                        h_ab = g['homeTeam']['abbrev']; a_ab = g['awayTeam']['abbrev']
                        h_sc = str(g['homeTeam'].get('score', 0)); a_sc = str(g['awayTeam'].get('score', 0))
                        st = g.get('gameState', 'OFF')
                        h_lg = self.get_corrected_logo('nhl', h_ab, f"https://a.espncdn.com/i/teamlogos/nhl/500/{h_ab.lower()}.png")
                        a_lg = self.get_corrected_logo('nhl', a_ab, f"https://a.espncdn.com/i/teamlogos/nhl/500/{a_ab.lower()}.png")
                        h_info = self.lookup_team_info_from_cache('nhl', h_ab)
                        a_info = self.lookup_team_info_from_cache('nhl', a_ab)
                        map_st = 'in' if st in ['LIVE', 'CRIT'] else ('pre' if st in ['PRE', 'FUT'] else 'post')
                        with data_lock:
                            mode = state['mode']; my_teams = state['my_teams']
                        is_shown = True
                        if mode == 'live' and map_st != 'in': is_shown = False
                        if mode == 'my_teams':
                            h_k = f"nhl:{h_ab}"; a_k = f"nhl:{a_ab}"
                            if (h_k not in my_teams and h_ab not in my_teams) and (a_k not in my_teams and a_ab not in my_teams): is_shown = False
                        
                        disp = "Scheduled"; pp = False; poss = ""; en = False; shootout_data = None 
                        utc_start = g.get('startTimeUTC', '') 
                        dur = self.calculate_game_timing('nhl', utc_start, 1, st)

                        if st in ['PRE', 'FUT'] and utc_start:
                             try:
                                 dt_obj = dt.fromisoformat(utc_start.replace('Z', '+00:00'))
                                 local = dt_obj.astimezone(timezone(timedelta(hours=utc_offset)))
                                 disp = local.strftime("%I:%M %p").lstrip('0')
                             except: pass
                        elif st in ['FINAL', 'OFF']:
                             disp = "FINAL"
                             pd = g.get('periodDescriptor', {})
                             if pd.get('periodType', '') == 'SHOOTOUT': disp = "FINAL S/O"

                        if map_st == 'in':
                            try:
                                r2 = requests.get(f"https://api-web.nhle.com/v1/gamecenter/{gid}/landing", headers=HEADERS, timeout=2)
                                if r2.status_code == 200:
                                    d2 = r2.json()
                                    h_sc = str(d2['homeTeam'].get('score', h_sc)); a_sc = str(d2['awayTeam'].get('score', a_sc))
                                    pd = d2.get('periodDescriptor', {})
                                    clk = d2.get('clock', {}); time_rem = clk.get('timeRemaining', '00:00')
                                    p_type = pd.get('periodType', '')
                                    if p_type == 'SHOOTOUT':
                                        disp = "S/O"; shootout_data = self.fetch_shootout_details(gid, 0, 0)
                                    else:
                                        p_num = pd.get('number', 1)
                                        if clk.get('inIntermission', False) or time_rem == "00:00":
                                            if p_num == 1: disp = "End 1st"
                                            elif p_num == 2: disp = "End 2nd"
                                            elif p_num == 3: disp = "End 3rd"
                                            else: disp = "Intermission"
                                        else:
                                            p_lbl = "OT" if p_num > 3 else f"P{p_num}"
                                            disp = f"{p_lbl} {time_rem}"
                                    
                                    sit_obj = d2.get('situation', {})
                                    if sit_obj and p_type != 'SHOOTOUT':
                                        sit = sit_obj.get('situationCode', '1551')
                                        ag = int(sit[0]); as_ = int(sit[1]); hs = int(sit[2]); hg = int(sit[3])
                                        if as_ > hs: pp=True; poss=a_ab
                                        elif hs > as_: pp=True; poss=h_ab
                                        en = (ag==0 or hg==0)
                            except: disp = "Live" 

                        games_list.append({
                            'type': 'scoreboard',
                            'sport': 'nhl', 'id': str(gid), 'status': disp, 'state': map_st, 'is_shown': is_shown,
                            'home_abbr': h_ab, 'home_score': h_sc, 'home_logo': h_lg, 'home_id': h_ab,
                            'away_abbr': a_ab, 'away_score': a_sc, 'away_logo': a_lg, 'away_id': a_ab,
                            'home_color': f"#{h_info['color']}", 'home_alt_color': f"#{h_info['alt_color']}",
                            'away_color': f"#{a_info['color']}", 'away_alt_color': f"#{a_info['alt_color']}",
                            'startTimeUTC': utc_start,
                            'estimated_duration': dur,
                            'situation': { 'powerPlay': pp, 'possession': poss, 'emptyNet': en, 'shootout': shootout_data }
                        })
        except: pass

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

        current_mode = conf.get('mode', 'all')
        
        # --- STRICT MODE ISOLATION ---
        
        # 1. WEATHER & CLOCK (Can coexist or be solo)
        if current_mode == 'weather' or conf['active_sports'].get('weather'):
            if conf['weather_location'] != self.weather.location_name: self.weather.update_coords(conf['weather_location'])
            w = self.weather.get_weather()
            if w: games.append(w)
            if current_mode == 'weather': # If strictly weather mode, return now
                with data_lock: state['current_games'] = games; return

        if current_mode == 'clock' or conf['active_sports'].get('clock'):
            games.append({'type':'clock','sport':'clock','id':'clk','is_shown':True})
            if current_mode == 'clock': 
                with data_lock: state['current_games'] = games; return

        # 2. STOCKS
        if current_mode == 'stocks' or current_mode == 'all':
            if conf['active_sports'].get('stock_movers'): games.extend(self.stocks.fetch_movers())
            # Fetch enabled lists
            stock_cats = ['stock_indices', 'stock_tech', 'stock_ai', 'stock_consulting', 'stock_crypto', 
                          'stock_auto', 'stock_semi', 'stock_finance', 'stock_energy', 'stock_pharma', 
                          'stock_consumer', 'stock_nyse', 'stock_etf', 'stock_commodities', 'stock_forex']
            for cat in stock_cats:
                if conf['active_sports'].get(cat): games.extend(self.stocks.fetch_list(cat))
            
            # If strictly stocks mode, return now (skip sports)
            if current_mode == 'stocks':
                with data_lock: state['current_games'] = games; return

        # 3. SPORTS
        if current_mode in ['sports', 'live', 'my_teams', 'all']:
            # --- PROCESS LEAGUES ---
            for league_key, config in self.leagues.items():
                if not conf['active_sports'].get(league_key, False): continue
                
                # Leaderboards (Racing)
                if config.get('type') == 'leaderboard': 
                    # Need time windows
                    utc_offset = conf.get('utc_offset', -5)
                    now_utc = dt.now(timezone.utc)
                    now_local = now_utc.astimezone(timezone(timedelta(hours=utc_offset)))
                    window_start_local = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
                    window_end_local = window_start_local + timedelta(days=1, hours=3)
                    window_start_utc = window_start_local.astimezone(timezone.utc)
                    window_end_utc = window_end_local.astimezone(timezone.utc)
                    self.fetch_leaderboard_event(league_key, config, games, conf, window_start_utc, window_end_utc)
                    continue

                # NHL NATIVE OVERRIDE
                target_date_str = dt.now().strftime("%Y-%m-%d")
                if conf['debug_mode'] and conf['custom_date']: target_date_str = conf['custom_date']
                
                if league_key == 'nhl' and not conf['debug_mode']:
                    prev_count = len(games)
                    self._fetch_nhl_native(games, target_date_str)
                    # If we got games from native, skip ESPN fetch for NHL
                    if len(games) > prev_count: continue 

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
                            # Re-calc time windows locally for sports loop
                            utc_offset = conf.get('utc_offset', -5)
                            now_utc = dt.now(timezone.utc)
                            now_local = now_utc.astimezone(timezone(timedelta(hours=utc_offset)))
                            window_start_local = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
                            window_end_local = window_start_local + timedelta(days=1, hours=3)
                            window_start_utc = window_start_local.astimezone(timezone.utc)
                            window_end_utc = window_end_local.astimezone(timezone.utc)
                            
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

                        # === SITUATION LOGIC ===
                        sit = comp.get('situation', {})
                        shootout_data = None
                        is_shootout = "Shootout" in s_disp or "Penalties" in s_disp or (gst == 'in' and st.get('period', 1) > 4 and 'hockey' in league_key)
                        
                        if is_shootout and 'soccer' in league_key:
                            shootout_data = self.fetch_shootout_details_soccer(e['id'], league_key)
                        
                        # POSSESSION (RESTORED OLD LOGIC)
                        poss_raw = sit.get('possession')
                        if poss_raw: self.possession_cache[e['id']] = poss_raw
                        elif gst in ['in', 'half'] and e['id'] in self.possession_cache: poss_raw = self.possession_cache[e['id']]
                        
                        if gst == 'pre' or gst == 'post' or gst == 'final' or s_disp == 'Halftime':
                            poss_raw = None
                            self.possession_cache.pop(e['id'], None)

                        poss_abbr = ""
                        if str(poss_raw) == str(h['team'].get('id')): poss_abbr = h_ab
                        elif str(poss_raw) == str(a['team'].get('id')): poss_abbr = a_ab
                        
                        down_text = sit.get('downDistanceText', '') if s_disp != "Halftime" else ''

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
                                'powerPlay': False, # ESPN doesn't give this easily, NHL is handled in native block above
                                'emptyNet': False
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
