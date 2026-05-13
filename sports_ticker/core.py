# ── Standard library ──
import csv
import concurrent.futures
import glob
import ipaddress
import io
import json
import math
import os
import random
import re
import string
import sys
import threading
import time
import traceback
import uuid
from datetime import datetime as dt, timezone, timedelta

try:
    from zoneinfo import ZoneInfo
except ImportError:
    ZoneInfo = None

# ── Third-party ──
import requests
from requests.adapters import HTTPAdapter
from flask import Flask, jsonify, make_response, request
from flask_cors import CORS
from dotenv import load_dotenv
try:
    import spotipy
    from spotipy.oauth2 import SpotifyOAuth
except ImportError:
    spotipy = None
    SpotifyOAuth = None
try:
    from google import genai
    from google.genai import types
except ImportError:
    genai = None
    types = None

# ── Flight tracking (optional) ──
try:
    import airportsdata
    AIRPORTS_DB = airportsdata.load('IATA')
    FLIGHT_TRACKING_AVAILABLE = True
except ImportError:
    AIRPORTS_DB = {}
    FLIGHT_TRACKING_AVAILABLE = False

# ── Logo color extraction (optional) ──
try:
    from PIL import Image as _PIL_Image
    PIL_AVAILABLE = True
except ImportError:
    _PIL_Image = None
    PIL_AVAILABLE = False

# Build reverse ICAO → IATA index once (replaces O(n) scan in lookup_and_auto_fill_airport)
_ICAO_TO_IATA_INDEX = {
    data.get('icao', '').upper(): iata
    for iata, data in AIRPORTS_DB.items()
    if data.get('icao')
}

try:
    from FlightRadar24.api import FlightRadar24API
    FR24_SDK_AVAILABLE = True
except ImportError:
    FR24_SDK_AVAILABLE = False

# Load environment variables
load_dotenv()

# ── Configure AI Service (Add near top of script) ──
GEMINI_KEY = os.getenv('GEMINI_API_KEY')

AI_CLIENT = None
AI_AVAILABLE = False

if GEMINI_KEY and genai is not None:
    try:
        # The new SDK uses a Client object
        AI_CLIENT = genai.Client(api_key=GEMINI_KEY)
        AI_AVAILABLE = True
    except:
        AI_AVAILABLE = False

# ================= MODULE-LEVEL LOOKUP TABLES =================
# Airline IATA <-> ICAO mapping
# Hardcoded fallback in case OpenFlights fetch fails at startup
_IATA_TO_ICAO_FALLBACK = {
    'DL': 'DAL', 'UA': 'UAL', 'AA': 'AAL', 'WN': 'SWA', 'B6': 'JBU',
    'AS': 'ASA', 'NK': 'NKS', 'F9': 'FFT', 'G4': 'AAY', 'SY': 'SCX',
    'HA': 'HAL', 'BA': 'BAW', 'LH': 'DLH', 'AF': 'AFR', 'KL': 'KLM',
    'EK': 'UAE', 'QR': 'QTR', 'VS': 'VIR', 'FR': 'RYR', 'U2': 'EZY',
    'AC': 'ACA', 'WS': 'WJA', 'EI': 'EIN', 'LY': 'ELY'}

def _build_airline_mappings():
    """Fetch comprehensive airline IATA<->ICAO from OpenFlights data. Falls back to hardcoded."""
    try:
        resp = requests.get(
            "https://raw.githubusercontent.com/jpatokal/openflights/master/data/airlines.dat",
            timeout=10
        )
        resp.raise_for_status()
        reader = csv.reader(io.StringIO(resp.text))
        iata_to_icao = {}
        for row in reader:
            if len(row) < 5:
                continue
            iata_code = row[3].strip()
            icao_code = row[4].strip()
            if (len(iata_code) == 2 and len(icao_code) == 3
                    and iata_code not in ('\\N', '-', '')
                    and icao_code not in ('\\N', '-', '')):
                iata_to_icao[iata_code.upper()] = icao_code.upper()
        if iata_to_icao:
            merged = dict(_IATA_TO_ICAO_FALLBACK)
            merged.update(iata_to_icao)
            print(f"[AIRLINE-DB] Loaded {len(merged)} airline IATA<->ICAO mappings from OpenFlights")
            return merged
    except Exception as e:
        print(f"[AIRLINE-DB] Could not fetch airline data ({e}), using {len(_IATA_TO_ICAO_FALLBACK)} hardcoded entries")
    return dict(_IATA_TO_ICAO_FALLBACK)

_IATA_TO_ICAO = _build_airline_mappings()

_ICAO_TO_IATA = {v: k for k, v in _IATA_TO_ICAO.items()}

# ── ICAO aircraft type code -> human-readable name normalization ──
# Covers common commercial types; used as fallback when FR24 details aren't available
_AIRCRAFT_TYPE_NAMES = {
    # Boeing 737
    'B731': 'Boeing 737-100', 'B732': 'Boeing 737-200', 'B733': 'Boeing 737-300',
    'B734': 'Boeing 737-400', 'B735': 'Boeing 737-500', 'B736': 'Boeing 737-600',
    'B737': 'Boeing 737-700', 'B738': 'Boeing 737-800', 'B739': 'Boeing 737-900',
    'B37M': 'Boeing 737 MAX 7', 'B38M': 'Boeing 737 MAX 8', 'B39M': 'Boeing 737 MAX 9',
    'B3XM': 'Boeing 737 MAX 10',
    # Boeing 747
    'B741': 'Boeing 747-100', 'B742': 'Boeing 747-200', 'B743': 'Boeing 747-300',
    'B744': 'Boeing 747-400', 'B748': 'Boeing 747-8', 'B74S': 'Boeing 747SP',
    # Boeing 757 / 767
    'B752': 'Boeing 757-200', 'B753': 'Boeing 757-300',
    'B762': 'Boeing 767-200', 'B763': 'Boeing 767-300', 'B764': 'Boeing 767-400',
    # Boeing 777
    'B772': 'Boeing 777-200', 'B77L': 'Boeing 777-200LR', 'B77W': 'Boeing 777-300ER',
    'B773': 'Boeing 777-300', 'B778': 'Boeing 777-8', 'B779': 'Boeing 777-9',
    # Boeing 787
    'B788': 'Boeing 787-8', 'B789': 'Boeing 787-9', 'B78X': 'Boeing 787-10',
    # Airbus A220
    'BCS1': 'Airbus A220-100', 'BCS3': 'Airbus A220-300',
    # Airbus A300 / A310
    'A30B': 'Airbus A300', 'A306': 'Airbus A300-600', 'A310': 'Airbus A310',
    # Airbus A318-A321
    'A318': 'Airbus A318', 'A319': 'Airbus A319', 'A320': 'Airbus A320',
    'A321': 'Airbus A321', 'A19N': 'Airbus A319neo', 'A20N': 'Airbus A320neo',
    'A21N': 'Airbus A321neo',
    # Airbus A330
    'A332': 'Airbus A330-200', 'A333': 'Airbus A330-300',
    'A338': 'Airbus A330-800neo', 'A339': 'Airbus A330-900neo',
    # Airbus A340
    'A342': 'Airbus A340-200', 'A343': 'Airbus A340-300',
    'A345': 'Airbus A340-500', 'A346': 'Airbus A340-600',
    # Airbus A350
    'A359': 'Airbus A350-900', 'A35K': 'Airbus A350-1000',
    # Airbus A380
    'A388': 'Airbus A380',
    # Embraer
    'E170': 'Embraer 170', 'E75L': 'Embraer 175', 'E75S': 'Embraer 175',
    'E190': 'Embraer 190', 'E195': 'Embraer 195',
    'E290': 'Embraer E190-E2', 'E295': 'Embraer E195-E2',
    # Bombardier / CRJ
    'CRJ1': 'CRJ-100', 'CRJ2': 'CRJ-200', 'CRJ7': 'CRJ-700', 'CRJ9': 'CRJ-900',
    'CRJX': 'CRJ-1000',
    # ATR / Turboprops
    'AT43': 'ATR 42-300', 'AT45': 'ATR 42-500', 'AT46': 'ATR 42-600',
    'AT72': 'ATR 72', 'AT76': 'ATR 72-600',
    'DH8A': 'Dash 8-100', 'DH8B': 'Dash 8-200', 'DH8C': 'Dash 8-300', 'DH8D': 'Dash 8-400',
    # Other common types
    'MD80': 'McDonnell Douglas MD-80', 'MD82': 'MD-82', 'MD83': 'MD-83',
    'MD88': 'MD-88', 'MD90': 'MD-90', 'MD11': 'MD-11',
    'DC10': 'DC-10', 'L101': 'Lockheed L-1011',
    'A225': 'Antonov An-225', 'A124': 'Antonov An-124',
    'C130': 'C-130 Hercules', 'C17': 'C-17 Globemaster',
    'GLF5': 'Gulfstream V', 'GLF6': 'Gulfstream G650', 'GLEX': 'Global Express',
    'LJ35': 'Learjet 35', 'LJ45': 'Learjet 45', 'LJ60': 'Learjet 60',
    'C560': 'Citation V', 'C680': 'Citation Sovereign', 'C750': 'Citation X',
    'E545': 'Embraer Legacy 450', 'E550': 'Embraer Praetor 600',
    'PC12': 'Pilatus PC-12', 'PC24': 'Pilatus PC-24',
    'BE20': 'Beechcraft King Air 200', 'BE30': 'Beechcraft King Air 350'}

def normalize_aircraft_type(icao_code, fr24_model=None):
    """Return human-readable aircraft name. Prefers FR24 detail model, falls back to local table."""
    if fr24_model:
        return fr24_model
    if icao_code:
        return _AIRCRAFT_TYPE_NAMES.get(icao_code.upper(), icao_code.upper())
    return ''

# ================= SERVER VERSION TAG =================
SERVER_VERSION = "v0.10 - Optimized"

# ── Section A: Logging ──
class Tee(object):
    # Set True to print [DEBUG] lines to console (mirrors state['debug_mode'])
    verbose_debug: bool = False

    def __init__(self, name, mode):
        self.file = open(name, mode, buffering=1, encoding='utf-8')
        self.original_stdout = sys.stdout
        self.original_stderr = sys.stderr
        self._lock = threading.Lock()
        self.stdout = self
        self.stderr = self

    def write(self, data):
        # Suppress [DEBUG] console spam unless debug_mode is on.
        # Always write to the log file so post-mortem analysis still works.
        if '[DEBUG]' in data and not Tee.verbose_debug:
            with self._lock:
                self.file.write(data)
                self.file.flush()
            return
        with self._lock:
            self.file.write(data)
            self.file.flush()
            try:
                self.original_stdout.write(data)
            except UnicodeEncodeError:
                self.original_stdout.write(data.encode('ascii', errors='replace').decode('ascii'))
            self.original_stdout.flush()

    def flush(self):
        with self._lock:
            self.file.flush()
            self.original_stdout.flush()

tee_instance = None
try:
    if not os.path.exists("ticker.log"):
        with open("ticker.log", "w") as f: f.write("--- Log Started ---\n")
    tee_instance = Tee("ticker.log", "a")
    sys.stdout = tee_instance
    sys.stderr = tee_instance
except Exception as e:
    print(f"Logging setup failed: {e}")

# ── Section B: Network / Session ──
def build_pooled_session(pool_size=20, retries=2):
    session = requests.Session()
    adapter = HTTPAdapter(pool_connections=pool_size, pool_maxsize=pool_size, max_retries=retries, pool_block=True)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session

# ── Section C: Constants / Timeouts ──
TICKER_DATA_DIR = "ticker_data"
if not os.path.exists(TICKER_DATA_DIR):
    os.makedirs(TICKER_DATA_DIR)
GLOBAL_CONFIG_FILE = "global_config.json"
STOCK_CACHE_FILE = "stock_cache.json"
GAME_CACHE_FILE = "game_cache.json"
AIRPORT_CACHE_FILE = "airport_name_cache.json"
AIRLINE_CACHE_FILE = "airline_code_cache.json"

SPORTS_UPDATE_INTERVAL = 5.0    
STOCKS_UPDATE_INTERVAL = 30     
WORKER_THREAD_COUNT = 10        
API_TIMEOUT = 7.0            

data_lock = threading.Lock()

HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Accept": "application/json",
    "Accept-Language": "en",
    "Referer": "https://www.fotmob.com/"
}

FOTMOB_LEAGUE_MAP = {
    'soccer_epl': 47, 'soccer_fa_cup': 132, 'soccer_champ': 48,
    'soccer_l1': 108, 'soccer_l2': 109, 'soccer_wc': 77,
    'soccer_champions_league': 42, 'soccer_europa_league': 73, 'soccer_mls': 130
}

TZ_OFFSETS = {
    "EST": -5, "EDT": -4, "CST": -6, "CDT": -5,
    "MST": -7, "MDT": -6, "PST": -8, "PDT": -7, "AST": -4, "ADT": -3
}

# ── Timeout constants (seconds) ──
TIMEOUTS = {
    'default': 7,   # general API calls (API_TIMEOUT)
    'quick':   3,   # NHL landing
    'stock':   5,   # Finnhub
    'slow':    10,  # FR24, open-meteo, FotMob
}

# ── Cache TTL constants (seconds) ──
CACHE_TTL = {
    'weather': 900,  # WeatherFetcher fresh threshold
    'flight':  600,  # StockFetcher stale check
    'stock':   30,   # STOCKS_UPDATE_INTERVAL
}

# ================= FLIGHT TRACKING CONSTANTS =================
KNOTS_TO_MPH = 1.15078
FLIGHTAWARE_API_KEY = os.getenv('FLIGHTAWARE_API_KEY', '')
BLUEBOARD_BASE = "https://theblueboard.co"
BLANK_LOGO_SENTINEL = "__blank_logo__"
BLANK_LOGO_URL = "https://upload.wikimedia.org/wikipedia/commons/5/59/Empty.png"

from .leagues import (
    MASTERS_LOGO_URL, PGA_CHAMPIONSHIP_LOGO_URL, PGA_TOUR_LOGO_URL,
    GOLF_TOURNAMENT_COLORS, PGA_TOUR_COLORS, _golf_tournament_colors,
    LEAGUE_OPTIONS, _LEAGUE_LABEL_MAP, _VALID_LEAGUE_IDS, _STOCK_LISTS,
    _LEAGUE_CATEGORY_ORDER, VALID_MODES, MODE_MIGRATIONS,
)

def get_city_name(iata_code):
    if not iata_code or not AIRPORTS_DB: return 'UNKNOWN'
    code = iata_code.strip().upper()
    if code in AIRPORTS_DB:
        return AIRPORTS_DB[code].get('city', code)
    return code

def _load_json_cache(filepath: str, label: str) -> dict:
    """Load a JSON cache file, returning its contents or an empty dict on failure."""
    if os.path.exists(filepath):
        try:
            with open(filepath, 'r') as f:
                data = json.load(f)
            print(f"📖 Loaded {len(data)} {label} from cache.")
            return data
        except Exception as e:
            print(f"⚠️ Error loading {label} cache: {e}")
    return {}

_ai_airport_cache: dict = _load_json_cache(AIRPORT_CACHE_FILE, "shortened airport names")
_ai_airline_cache: dict = _load_json_cache(AIRLINE_CACHE_FILE, "airline codes")

def ai_lookup_airline_codes(query_code: str):
    """
    Resolve an unknown airline code (2-letter IATA or 3-letter ICAO) via Gemini AI.
    Stores the result bidirectionally in AIRLINE_CACHE_FILE so AI is only called once per airline.
    Returns (icao_3, iata_2) or (None, None).
    """
    global _ai_airline_cache
    query_code = query_code.upper().strip()

    # Check persistent cache first (loaded from disk at startup)
    if query_code in _ai_airline_cache:
        partner = _ai_airline_cache[query_code]
        return (partner, query_code) if len(query_code) == 2 else (query_code, partner)

    if not AI_AVAILABLE or not AI_CLIENT:
        return None, None

    try:
        prompt = (
            f"What are the IATA (2-letter) and ICAO (3-letter) codes for the airline "
            f"identified by code '{query_code}'?\n"
            "Reply with ONLY: IATA ICAO (e.g. 'UA UAL'). If unknown, reply 'UNKNOWN'."
        )
        response = AI_CLIENT.models.generate_content(
            model='gemini-2.0-flash',
            contents=prompt,
            config=types.GenerateContentConfig(
                candidate_count=1, max_output_tokens=10, temperature=0.0
            )
        )
        text = (response.text or '').strip().upper()
        if text == 'UNKNOWN' or not text:
            return None, None
        parts = text.split()
        if len(parts) == 2 and len(parts[0]) == 2 and len(parts[1]) == 3:
            iata, icao = parts[0], parts[1]
            _ai_airline_cache[iata] = icao   # bidirectional
            _ai_airline_cache[icao] = iata
            save_json_atomically(AIRLINE_CACHE_FILE, _ai_airline_cache)
            print(f"[AIRLINE-AI] Resolved '{query_code}' → IATA={iata}, ICAO={icao}")
            return icao, iata
    except Exception as e:
        print(f"[AIRLINE-AI] Lookup failed for '{query_code}': {e}")
    return None, None

def get_airport_display_name(iata_code):
    """
    Uses AI to intelligently shorten airport names with persistent file caching.
    Saves results to airport_name_cache.json to avoid Gemini API quota limits.
    """
    if not iata_code or not AIRPORTS_DB: return 'UNKNOWN'
    code = iata_code.strip().upper()
    
    if code not in AIRPORTS_DB: return code

    data = AIRPORTS_DB[code]
    raw_name = data.get('name', code)
    city = data.get('city', '')
    
    # 1. Check Persistent Memory Cache
    cache_key = f"{code}_{raw_name}"
    if cache_key in _ai_airport_cache:
        return _ai_airport_cache[cache_key]

    # 2. Try AI Service (Gemini 2.0 Flash)
    if AI_AVAILABLE and AI_CLIENT:
        try:
            prompt = (
                f"Convert the airport name '{raw_name}' (City: {city}) into its common display name. \n"
                "Rules:\n"
                "1. STRIP: Remove words like 'International', 'Airport', 'Field', 'Intercontinental', 'Municipal'.\n"
                "2. REDUNDANCY: Remove the city name if it is just a descriptor (e.g. 'Denver Intl' -> 'Denver').\n"
                "3. PERSON NAMES: Always use the Full Name (First + Last). Do not shorten to surname only. \n"
                "   - CORRECT: 'George Bush', 'Harry Reid', 'Gerald Ford'\n"
                "   - INCORRECT: 'Bush', 'Reid', 'Ford'\n"
                "4. COLLOQUIAL: If the airport has a famous acronym or nickname, use that instead.\n"
                "   - Example: 'John F. Kennedy' -> 'JFK'\n"
                "   - Example: 'London Heathrow' -> 'Heathrow'\n"
                f"Input to process: {raw_name}"
            )
            
            response = AI_CLIENT.models.generate_content(
                model='gemini-2.0-flash', 
                contents=prompt,
                config=types.GenerateContentConfig(
                    candidate_count=1,
                    max_output_tokens=15,
                    temperature=0.1
                )
            )
            
            if response.text:
                short_name = response.text.strip()
                # Validation: ensure AI didn't return something bizarrely long
                if len(short_name) < len(raw_name) + 5:
                    _ai_airport_cache[cache_key] = short_name
                    save_json_atomically(AIRPORT_CACHE_FILE, _ai_airport_cache)
                    return short_name
                
        except Exception as e:
            if "429" in str(e):
                print(f"[AI] Quota hit (429) for {code}, using algorithmic fallback.")
            else:
                print(f"[AI] Failed to shorten {code}: {e}")

    # 3. Fallback: Algorithmic Cleaning (Used if AI is unavailable or fails)
    replacements = [
        " International Airport", " Intercontinental Airport", " Regional Airport",
        " International", " Intercontinental", " Municipal", 
        " Airport", " Intl", " Apt", " Field", " Air Force Base", " AFB"
    ]
    
    clean_name = raw_name
    for phrase in replacements:
        pattern = re.compile(re.escape(phrase), re.IGNORECASE)
        clean_name = pattern.sub("", clean_name)
        
    clean_name = clean_name.strip()
    
    # If the clean name starts with the city name, remove the redundancy
    if city and clean_name.lower().startswith(city.lower()):
        candidate = clean_name[len(city):].strip()
        if len(candidate) > 2:
            clean_name = candidate

    # Cache the algorithmic result too so we don't try AI again for this airport
    _ai_airport_cache[cache_key] = clean_name
    save_json_atomically(AIRPORT_CACHE_FILE, _ai_airport_cache)
    return clean_name

def lookup_and_auto_fill_airport(airport_code_input):
    """
    Takes either IATA (3-char) or ICAO (4-char) airport code and returns complete airport info.
    Returns: {'iata': 'ABE', 'icao': 'KABE', 'name': 'Lehigh Valley International Airport'}
    """
    if not airport_code_input or not AIRPORTS_DB:
        return {'iata': '', 'icao': '', 'name': ''}
    
    code = airport_code_input.strip().upper()
    
    # Try direct IATA lookup (most common case)
    if code in AIRPORTS_DB:
        airport_data = AIRPORTS_DB[code]
        iata = code
        icao = airport_data.get('icao', f'K{code}' if len(code) == 3 else '')
        name = airport_data.get('name', airport_data.get('city', code))
        return {'iata': iata, 'icao': icao, 'name': name}
    
    # Try ICAO lookup via pre-built reverse index (O(1) instead of O(n))
    if len(code) == 4:
        iata_code = _ICAO_TO_IATA_INDEX.get(code)
        if iata_code and iata_code in AIRPORTS_DB:
            airport_data = AIRPORTS_DB[iata_code]
            name = airport_data.get('name', airport_data.get('city', iata_code))
            return {'iata': iata_code, 'icao': code, 'name': name}
    
    # If not found, return empty
    return {'iata': '', 'icao': '', 'name': ''}

def haversine(lat1, lon1, lat2, lon2):
    R = 3440.065
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat/2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon/2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
    return R * c

# ── Section D: Data Tables ──
# LEAGUE_OPTIONS and related structures live in leagues.py — imported above.


def _auto_category_for_option(item: dict) -> str:
    t = item.get('type')
    if t != 'sport':
        return str(t or 'other')

    league_id = str(item.get('id', ''))
    path = str((item.get('fetch') or {}).get('path', '')).lower()

    if league_id.startswith('soccer_') or path.startswith('soccer/'):
        return 'soccer'
    if path.startswith('football/'):
        return 'football'
    if path.startswith('basketball/'):
        return 'basketball'
    if path.startswith('baseball/'):
        return 'baseball'
    if path.startswith('hockey/'):
        return 'hockey'
    return 'other'


def _league_sort_key(item: dict):
    category = _auto_category_for_option(item)
    return (
        _LEAGUE_CATEGORY_ORDER.get(category, 99),
        str(item.get('label', '')).lower(),
    )

# Pre-compiled regex and frozensets for hot-path checks
_TIME_RE = re.compile(r'\d+:\d+')
_ACTIVE_STATES = frozenset({'in', 'half', 'crit'})
SPORTS_MODE_FAMILY = ('sports', 'live', 'my_teams', 'sports_full', 'soccer_full')
NON_SCOREBOARD_TYPES = ('music', 'clock', 'weather', 'stock_ticker', 'flight_visitor', 'masters')
HIDDEN_STATUS_KEYWORDS = frozenset({"postponed", "suspended", "canceled", "ppd"})

def normalize_mode(mode, fallback='sports'):
    normalized = MODE_MIGRATIONS.get(mode, mode)
    return normalized if normalized in VALID_MODES else fallback


def _normalize_single_pin(pinned_game=None, pinned_games=None):
    single = ''
    if isinstance(pinned_games, list):
        cleaned = [str(x).strip() for x in pinned_games if str(x).strip()]
        if cleaned:
            single = cleaned[-1]
    if not single and pinned_game is not None:
        single = str(pinned_game).strip()
    return single, ([single] if single else [])


def _game_sort_key(x):
    t = x.get('type', '')
    if t == 'clock':
        prio = 0
    elif t == 'weather':
        prio = 1
    else:
        s = str(x.get('status', ''))
        sl = s.lower()
        if any(k in sl for k in HIDDEN_STATUS_KEYWORDS):
            prio = 4
        elif "FINAL" in s.upper() or sl == "fin":
            prio = 3
        else:
            prio = 2
    return (prio, x.get('startTimeUTC') or '9999', x.get('sport', ''), x.get('home_abbr', ''), x.get('away_abbr', ''), str(x.get('id') or '0'))


# VALID_MODES and MODE_MIGRATIONS live in leagues.py — imported above.

FBS_TEAMS = {"AF", "AKR", "ALA", "APP", "ARIZ", "ASU", "ARK", "ARST", "ARMY", "AUB", "BALL", "BAY", "BOIS", "BC", "BGSU", "BUF", "BYU", "CAL", "CMU", "CLT", "CIN", "CLEM", "CCU", "COLO", "CSU", "CONN", "DEL", "DUKE", "ECU", "EMU", "FAU", "FIU", "FLA", "FSU", "FRES", "GASO", "GAST", "GT", "UGA", "HAW", "HOU", "ILL", "IND", "IOWA", "ISU", "JXST", "JMU", "KAN", "KSU", "KENN", "KENT", "UK", "LIB", "ULL", "LT", "LOU", "LSU", "MAR", "MD", "MASS", "MEM", "MIA", "M-OH", "MICH", "MSU", "MTSU", "MINN", "MSST", "MIZ", "MOST", "NAVY", "NCST", "NEB", "NEV", "UNM", "NMSU", "UNC", "UNT", "NIU", "NU", "ND", "OHIO", "OSU", "OU", "OKST", "ODU", "MISS", "ORE", "ORST", "PSU", "PITT", "PUR", "RICE", "RUTG", "SAM", "SDSU", "SJSU", "SMU", "USA", "SC", "USF", "USM", "STAN", "SYR", "TCU", "TEM", "TENN", "TEX", "TA&M", "TXST", "TTU", "TOL", "TROY", "TULN", "TLSA", "UAB", "UCF", "UCLA", "ULM", "UMASS", "UNLV", "USC", "UTAH", "USU", "UTEP", "UTSA", "VAN", "UVA", "VT", "WAKE", "WASH", "WSU", "WVU", "WKU", "WMU", "WIS", "WYO"}
FCS_TEAMS = {"ACU", "AAMU", "ALST", "UALB", "ALCN", "UAPB", "APSU", "BCU", "BRWN", "BRY", "BUCK", "BUT", "CP", "CAM", "CARK", "CCSU", "CHSO", "UTC", "CIT", "COLG", "COLU", "COR", "DART", "DAV", "DAY", "DSU", "DRKE", "DUQ", "EIU", "EKU", "ETAM", "EWU", "ETSU", "ELON", "FAMU", "FOR", "FUR", "GWEB", "GTWN", "GRAM", "HAMP", "HARV", "HC", "HCU", "HOW", "IDHO", "IDST", "ILST", "UIW", "INST", "JKST", "LAF", "LAM", "LEH", "LIN", "LIU", "ME", "MRST", "MCN", "MER", "MERC", "MRMK", "MVSU", "MONM", "MONT", "MTST", "MORE", "MORG", "MUR", "UNH", "NHVN", "NICH", "NORF", "UNA", "NCAT", "NCCU", "UND", "NDSU", "NAU", "UNCO", "UNI", "NWST", "PENN", "PRST", "PV", "PRES", "PRIN", "URI", "RICH", "RMU", "SAC", "SHU", "SFPA", "SAM", "USD", "SELA", "SEMO", "SDAK", "SDST", "SCST", "SOU", "SIU", "SUU", "STMN", "SFA", "STET", "STO", "STBK", "TAR", "TNST", "TNTC", "TXSO", "TOW", "UCD", "UTM", "UTM", "UTRGV", "VAL", "VILL", "VMI", "WAG", "WEB", "WGA", "WCU", "WIU", "W&M", "WOF", "YALE", "YSU"}

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
    "NCF_FBS:CAL": "https://a.espncdn.com/i/teamlogos/ncaa/500/25.png", "NCF_FBS:OSU": "https://a.espncdn.com/i/teamlogos/ncaa/500/194.png", "NCF_FBS:ORST": "https://a.espncdn.com/i/teamlogos/ncaa/500/204.png", "NCF_FCS:LIN": "https://a.espncdn.com/i/teamlogos/ncaa/500/2815.png", "NCF_FCS:LEH": "https://a.espncdn.com/i/teamlogos/ncaa/500/2329.png",
    "MLB:SD": "https://a.espncdn.com/guid/4dec648c-3eb9-055c-aebc-2711f30975a0/logos/primary_logo_on_primary_color.png", "MARCH_MADNESS:IOWA": "https://a.espncdn.com/guid/b7840e2f-6236-e764-2cae-20286a0829e7/logos/primary_logo_on_black_color.png", "MLB:NYY":"https://raw.githubusercontent.com/MattLD13/PoopTracker/refs/heads/main/New_York_Yankees_logo.svg.png?token=GHSAT0AAAAAADYJKBTDDNFOD3RYPUBH2LUG2PS4A6A",
    "MLB:NYY": "https://raw.githubusercontent.com/MattLD13/PoopTracker/refs/heads/main/New_York_Yankees_logo.svg.png", "MLB:COL": "https://raw.githubusercontent.com/MattLD13/PoopTracker/refs/heads/main/Colorado_Rockies_logo.svg.png",

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

# WMO weather condition codes → human-readable labels (used by FlightTracker.fetch_airport_weather)
WMO_DESCRIPTIONS = {
    0: "CLEAR SKY", 1: "MAINLY CLEAR", 2: "PARTLY CLOUDY", 3: "OVERCAST",
    45: "FOG", 48: "RIME FOG",
    51: "LIGHT DRIZZLE", 53: "DRIZZLE", 55: "HEAVY DRIZZLE",
    56: "FREEZING DRIZZLE", 57: "FREEZING DRIZZLE",
    61: "LIGHT RAIN", 63: "RAIN", 65: "HEAVY RAIN",
    66: "FREEZING RAIN", 67: "FREEZING RAIN",
    71: "LIGHT SNOW", 73: "SNOW", 75: "HEAVY SNOW",
    77: "SNOW GRAINS",
    80: "LIGHT SHOWERS", 81: "SHOWERS", 82: "HEAVY SHOWERS",
    85: "SNOW SHOWERS", 86: "HEAVY SNOW SHOWERS",
    95: "THUNDERSTORM", 96: "THUNDERSTORM/HAIL", 99: "THUNDERSTORM/HAIL"}

# ── Section E: Default State ──
default_state = {
    'active_sports': { item['id']: item['default'] for item in LEAGUE_OPTIONS },
    'mode': 'sports', 
    'layout_mode': 'schedule',
    'my_teams': [], 
    'current_games': [],
    'all_teams_data': {},
    'debug_mode': False,
    'custom_date': None,
    # Test mode — all off by default; toggled via /api/debug or /api/config
    'test_mode':        False,   # master switch (enables all subsystems)
    'test_spotify':     False,   # simulate Spotify playback
    'test_stocks':      False,   # simulate stock prices
    'test_sports_date': False,   # use custom_date for sports fetch
    'test_flights':     False,   # verbose flight debug logging
    'weather_city': "New York",
    'weather_lat': 40.7128,
    'weather_lon': -74.0060,
    'utc_offset': -5,
    'show_debug_options': False,
    # Flight tracking
    'track_flight_id': '',
    'track_guest_name': '',
    'airport_code_icao': 'KEWR',
    'airport_code_iata': 'EWR',
    'airport_name': 'Newark',
    'airline_filter': ''
}

DEFAULT_TICKER_SETTINGS = {
    "brightness": 100,
    "scroll_speed": 0.03,
    "scroll_seamless": True,
    "inverted": False,
    "panel_count": 2,
    "live_delay_mode": False,
    "live_delay_seconds": 45,
    "utc_offset": -5,
    "timezone_name": ""
}

# ── Section F: Boot / Config Load ──
state = default_state.copy()

tickers = {} 

# 1. Load Global Config — single pass with inline cleanup
if os.path.exists(GLOBAL_CONFIG_FILE):
    try:
        with open(GLOBAL_CONFIG_FILE, 'r') as f:
            config_data = json.load(f)
        # Migrate and clean legacy keys in-memory first
        config_data['mode'] = MODE_MIGRATIONS.get(config_data.get('mode', 'sports'), config_data.get('mode', 'sports'))
        # Handle legacy flights+submode combos bidirectionally
        if config_data.get('flight_submode') == 'track':
            config_data['mode'] = 'flight_tracker'
        elif config_data.get('flight_submode') == 'airport' and config_data.get('mode') == 'flight_tracker':
            config_data['mode'] = 'flights'
        config_data.pop('flight_submode', None)
        config_data['airline_filter'] = ''
        # Apply to state
        for k, v in config_data.items():
            if k in state:
                if isinstance(state[k], dict) and isinstance(v, dict):
                    state[k].update(v)
                else:
                    state[k] = v
        # If config had stale keys, persist the cleaned version
        if 'flight_submode' in config_data or config_data.get('airline_filter', '') != '':
            with open(GLOBAL_CONFIG_FILE, 'w') as _f:
                json.dump(config_data, _f, indent=4)
            print("🧹 Migrated legacy keys in global config")
    except Exception as e:
        print(f"⚠️ Error loading global config: {e}")

# Global teams are always empty; teams are stored per-ticker only
state['my_teams'] = []

# Reconcile active_sports against current LEAGUE_OPTIONS:
# remove deprecated keys, add any new ones with their defaults
_valid_league_ids = {item['id'] for item in LEAGUE_OPTIONS}
_deprecated_leagues = []
for _k in list(state['active_sports'].keys()):
    if _k not in _valid_league_ids:
        del state['active_sports'][_k]
        _deprecated_leagues.append(_k)
for _item in LEAGUE_OPTIONS:
    if _item['id'] not in state['active_sports']:
        state['active_sports'][_item['id']] = _item['default']

# If deprecated leagues were removed, persist the cleaned state (deferred until save_global_config is defined)
if _deprecated_leagues:
    print(f"🧹 Removed deprecated leagues: {', '.join(_deprecated_leagues)}")
_deprecated_leagues_pending_save = bool(_deprecated_leagues)

# Ensure mode is valid
state['mode'] = MODE_MIGRATIONS.get(state.get('mode', 'sports'), state.get('mode', 'sports'))
if state['mode'] not in VALID_MODES:
    state['mode'] = 'sports'
state['airline_filter'] = ''

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
            for _sk, _sv in DEFAULT_TICKER_SETTINGS.items():
                t_data['settings'].setdefault(_sk, _sv)
            t_data['settings'].pop('active_sports', None)  # active_sports is global-only; strip stale per-ticker copy
            if 'my_teams' not in t_data: t_data['my_teams'] = None
            elif t_data.get('my_teams') == []: t_data['my_teams'] = None  # migrate old unconfigured tickers
            if 'clients' not in t_data: t_data['clients'] = []
            
            tickers[tid] = t_data
    except Exception as e:
        print(f"❌ Failed to load ticker file {t_file}: {e}")

# Pre-populate current_games from cache so display works immediately on restart
if os.path.exists(GAME_CACHE_FILE):
    try:
        with open(GAME_CACHE_FILE, 'r') as _gcf:
            _cached = json.load(_gcf)
        if isinstance(_cached, list) and _cached:
            # Re-apply logo overrides so stale cache entries reflect the current dict.
            for _g in _cached:
                _sport = _g.get('sport', '').upper()
                if not _sport:
                    continue
                for _side in ('home', 'away'):
                    _abbr = _g.get(f'{_side}_abbr', '')
                    if _abbr:
                        _override = LOGO_OVERRIDES.get(f'{_sport}:{_abbr}')
                        if _override:
                            _g[f'{_side}_logo'] = _override
            state['current_games'] = _cached
            print(f"📦 Loaded {len(_cached)} cached games from {GAME_CACHE_FILE}")
    except Exception as _e:
        print(f"⚠️ Could not load game cache: {_e}")


# ── Section G: Save Helpers ──
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
                # my_teams intentionally omitted — always [] globally; stored per-ticker only
                'weather_city': state['weather_city'],
                'weather_lat': state['weather_lat'],
                'weather_lon': state['weather_lon'],
                'utc_offset': state['utc_offset'],
                # Flight tracking
                'track_flight_id': state.get('track_flight_id', ''),
                'track_guest_name': state.get('track_guest_name', ''),
                'airport_code_icao': state.get('airport_code_icao', 'KEWR'),
                'airport_code_iata': state.get('airport_code_iata', 'EWR'),
                'airport_name': state.get('airport_name', 'Newark'),
                'airline_filter': '',  # Always empty - support all airlines
            }
        
        # Atomic Write
        save_json_atomically(GLOBAL_CONFIG_FILE, export_data)
    except Exception as e:
        print(f"Error saving global config: {e}")

if _deprecated_leagues_pending_save:
    save_global_config()

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
        active_codes = {t.get('pairing_code') for t in tickers.values() if not t.get('paired')}
        if code not in active_codes: return code

def create_ticker_record(name="Ticker", client_id=None, paired=True):
    """Create a ticker record with the same defaults used by registration/autocreate paths."""
    rec = {
        "name": name,
        "settings": DEFAULT_TICKER_SETTINGS.copy(),
        "my_teams": None,
        "clients": [client_id] if client_id else [],
        "paired": paired,
        "pairing_code": generate_pairing_code(),
        "last_seen": time.time()
    }
    rec['settings']['mode'] = state.get('mode', 'sports')
    return rec

def find_ticker_id_for_client(client_id):
    if not client_id:
        return None
    for tid, rec in tickers.items():
        if client_id in rec.get('clients', []):
            return tid
    return None

def resolve_ticker_id(explicit_id=None, client_id=None, allow_single=True):
    ticker_id = explicit_id or find_ticker_id_for_client(client_id)
    if not ticker_id and allow_single and len(tickers) == 1:
        ticker_id = list(tickers.keys())[0]
    return ticker_id

def pair_client_to_ticker(rec, client_id, friendly_name=None):
    if client_id and client_id not in rec.get('clients', []):
        rec.setdefault('clients', []).append(client_id)
    rec['paired'] = True
    if friendly_name is not None:
        rec['name'] = friendly_name

# ================= UTILITIES =================

def safe_get(obj, *keys, default=None):
    """
    Defensive nested dict traversal.
    safe_get(d, 'a', 'b', 'c') is equivalent to the chain:
        ((d.get('a') or {}).get('b') or {}).get('c')
    Returns `default` if any level is missing, None, or not a dict.
    """
    cur = obj
    for key in keys:
        if not isinstance(cur, dict):
            return default
        cur = cur.get(key)
        if cur is None:
            return default
    return cur if cur is not None else default


def parse_iso(s: str) -> dt:
    """
    Parse an ISO 8601 datetime string, handling the trailing 'Z' that
    Python < 3.11 fromisoformat() rejects.
    """
    if not s:
        raise ValueError("Empty datetime string")
    return dt.fromisoformat(s.replace('Z', '+00:00'))


_IP_TZ_CACHE = {}
_IP_TZ_CACHE_TTL = 12 * 3600


def _extract_client_ip(req) -> str | None:
    def _normalize_public_ip(raw: str) -> str | None:
        raw_ip = (raw or '').strip()
        if not raw_ip:
            return None

        # IPv4-mapped IPv6 format: ::ffff:1.2.3.4
        if raw_ip.lower().startswith('::ffff:'):
            raw_ip = raw_ip[7:]
        # Strip zone index from IPv6 if present
        if '%' in raw_ip:
            raw_ip = raw_ip.split('%', 1)[0]

        try:
            ip_obj = ipaddress.ip_address(raw_ip)
            if any([
                ip_obj.is_private,
                ip_obj.is_loopback,
                ip_obj.is_link_local,
                ip_obj.is_reserved,
                ip_obj.is_multicast,
                ip_obj.is_unspecified,
            ]):
                return None
            return str(ip_obj)
        except Exception:
            return None

    header_candidates = [
        'CF-Connecting-IP',
        'X-Forwarded-For',
        'X-Real-IP',
    ]
    for h in header_candidates:
        v = (req.headers.get(h) or '').strip()
        if v:
            # Prefer first public IP in the chain.
            for part in v.split(','):
                pub = _normalize_public_ip(part)
                if pub:
                    return pub

    return _normalize_public_ip(req.remote_addr or '')


def _utc_offset_hours_for_timezone(tz_name: str | None) -> float | None:
    if not tz_name or not ZoneInfo:
        return None
    try:
        now_local = dt.now(ZoneInfo(tz_name))
        off = now_local.utcoffset()
        if off is None:
            return None
        return round(off.total_seconds() / 3600.0, 2)
    except Exception:
        return None


def _extract_timezone_from_request_headers(req) -> tuple[str | None, float | None]:
    tz_raw = str(
        req.headers.get('X-Ticker-Timezone')
        or req.headers.get('X-Timezone')
        or req.args.get('timezone_name')
        or req.args.get('tz')
        or ''
    ).strip()
    off_raw = (
        req.headers.get('X-Ticker-Utc-Offset')
        or req.headers.get('X-UTC-Offset')
        or req.args.get('utc_offset')
        or req.args.get('offset')
    )

    tz_name = None
    if tz_raw:
        if ZoneInfo:
            try:
                ZoneInfo(tz_raw)
                tz_name = tz_raw
            except Exception:
                tz_name = None
        # Allow non-IANA fallback (e.g. EDT) if no ZoneInfo validation possible.
        if tz_name is None and len(tz_raw) <= 64:
            tz_name = tz_raw

    offset = None
    if off_raw is not None:
        try:
            offset = round(float(off_raw), 2)
            if offset < -14 or offset > 14:
                offset = None
        except Exception:
            offset = None

    if offset is None and tz_name:
        offset = _utc_offset_hours_for_timezone(tz_name)

    return tz_name, offset


def _lookup_timezone_for_ip(ip_addr: str) -> tuple[str | None, float | None]:
    now_ts = time.time()
    cached = _IP_TZ_CACHE.get(ip_addr)
    if cached and (now_ts - cached.get('ts', 0) < _IP_TZ_CACHE_TTL):
        return cached.get('timezone'), cached.get('offset')

    try:
        url = f"https://ip-api.com/json/{ip_addr}"
        params = {"fields": "status,timezone,offset,message,query"}
        resp = requests.get(url, params=params, timeout=TIMEOUTS.get('quick', 3))
        data = resp.json() if resp.ok else {}
        if data.get('status') == 'success' and data.get('timezone'):
            tz_name = str(data.get('timezone')).strip()
            offset_raw = data.get('offset')
            offset_hours = round(float(offset_raw) / 3600.0, 2) if isinstance(offset_raw, (int, float)) else None
            if offset_hours is None:
                offset_hours = _utc_offset_hours_for_timezone(tz_name)
            _IP_TZ_CACHE[ip_addr] = {
                'timezone': tz_name,
                'offset': offset_hours,
                'ts': now_ts}
            return tz_name, offset_hours
    except Exception as e:
        print(f"[TZ] ip-api lookup failed for {ip_addr}: {e}")

    return None, None


def _lookup_timezone_for_current_connection() -> tuple[str | None, float | None, str | None]:
    """
    Fallback when request IP appears private/local (e.g. LAN app usage).
    ip-api resolves timezone for the current outbound connection IP.
    """
    cache_key = '__self__'
    now_ts = time.time()
    cached = _IP_TZ_CACHE.get(cache_key)
    if cached and (now_ts - cached.get('ts', 0) < _IP_TZ_CACHE_TTL):
        return cached.get('timezone'), cached.get('offset'), cached.get('query')

    try:
        url = "https://ip-api.com/json/"
        params = {"fields": "status,query,timezone,offset,message"}
        resp = requests.get(url, params=params, timeout=TIMEOUTS.get('quick', 3))
        data = resp.json() if resp.ok else {}
        if data.get('status') == 'success' and data.get('timezone'):
            tz_name = str(data.get('timezone')).strip()
            query_ip = str(data.get('query') or '').strip() or None
            offset_raw = data.get('offset')
            offset_hours = round(float(offset_raw) / 3600.0, 2) if isinstance(offset_raw, (int, float)) else None
            if offset_hours is None:
                offset_hours = _utc_offset_hours_for_timezone(tz_name)

            _IP_TZ_CACHE[cache_key] = {
                'timezone': tz_name,
                'offset': offset_hours,
                'query': query_ip,
                'ts': now_ts}
            return tz_name, offset_hours, query_ip
    except Exception as e:
        print(f"[TZ] ip-api self lookup failed: {e}")

    return None, None, None


def _lookup_timezone_for_latlon(lat: float, lon: float) -> tuple[str | None, float | None]:
    """
    Fallback resolver using open-meteo timezone=auto from lat/lon.
    Useful when client IP/header timezone is unavailable.
    """
    try:
        lat_f = float(lat)
        lon_f = float(lon)
    except Exception:
        return None, None

    cache_key = f"__latlon__:{round(lat_f, 3)},{round(lon_f, 3)}"
    now_ts = time.time()
    cached = _IP_TZ_CACHE.get(cache_key)
    if cached and (now_ts - cached.get('ts', 0) < _IP_TZ_CACHE_TTL):
        return cached.get('timezone'), cached.get('offset')

    try:
        url = "https://api.open-meteo.com/v1/forecast"
        params = {
            "latitude": lat_f,
            "longitude": lon_f,
            "current": "temperature_2m",
            "timezone": "auto"}
        resp = requests.get(url, params=params, timeout=TIMEOUTS.get('quick', 3))
        data = resp.json() if resp.ok else {}
        tz_name = str(data.get('timezone') or '').strip()
        if not tz_name:
            return None, None

        off = _utc_offset_hours_for_timezone(tz_name)
        _IP_TZ_CACHE[cache_key] = {
            'timezone': tz_name,
            'offset': off,
            'ts': now_ts}
        return tz_name, off
    except Exception as e:
        print(f"[TZ] lat/lon timezone lookup failed ({lat_f},{lon_f}): {e}")
        return None, None


def _get_ticker_timezone_context(rec: dict) -> tuple[str, float]:
    settings = rec.get('settings', {}) if isinstance(rec, dict) else {}
    tz_name = str(settings.get('timezone_name') or rec.get('timezone_name') or '').strip()

    offset = settings.get('utc_offset', None)
    try:
        offset = float(offset)
    except Exception:
        offset = None

    # Prefer live offset from IANA timezone so DST changes (e.g. -5 -> -4)
    # apply immediately without waiting for an IP change.
    if tz_name:
        live_offset = _utc_offset_hours_for_timezone(tz_name)
        if live_offset is not None:
            offset = live_offset
    if offset is None:
        offset = float(state.get('utc_offset', -5))

    return tz_name, offset


def _apply_ticker_timezone(rec: dict, tz_name: str | None, offset: float | None) -> bool:
    """Apply timezone/offset to a ticker record. Returns True if anything changed."""
    settings = rec.setdefault('settings', {})
    changed = False
    if tz_name and settings.get('timezone_name') != tz_name:
        settings['timezone_name'] = tz_name
        changed = True
    if offset is not None and settings.get('utc_offset') != offset:
        settings['utc_offset'] = offset
        changed = True
    if tz_name and rec.get('timezone_name') != tz_name:
        rec['timezone_name'] = tz_name
        changed = True
    return changed


def _maybe_update_ticker_timezone_from_request(ticker_id: str, req):
    if not ticker_id or ticker_id not in tickers:
        return

    rec = tickers[ticker_id]

    # Prefer timezone provided by the ticker device itself.
    hdr_tz, hdr_offset = _extract_timezone_from_request_headers(req)
    if hdr_tz or hdr_offset is not None:
        changed = _apply_ticker_timezone(rec, hdr_tz, hdr_offset)
        if changed:
            off_txt = f"UTC{hdr_offset:+}" if isinstance(hdr_offset, (int, float)) else "UTC?"
            print(f"[TZ] Ticker {ticker_id} timezone set from ticker headers: {hdr_tz or 'unknown'} ({off_txt})")
            save_specific_ticker(ticker_id)
        # If only offset was provided (no timezone name), continue to fallbacks
        # so we can still resolve and persist a canonical timezone_name.
        if hdr_tz:
            return

    ip_addr = _extract_client_ip(req)

    # If request appears local/private, fall back to current public egress IP.
    if not ip_addr:
        tz_name, offset, query_ip = _lookup_timezone_for_current_connection()
        if tz_name:
            if offset is None:
                offset = _utc_offset_hours_for_timezone(tz_name)

            changed = _apply_ticker_timezone(rec, tz_name, offset)
            if query_ip and rec.get('last_ip') != query_ip:
                rec['last_ip'] = query_ip
                changed = True

            if changed:
                off_txt = f"UTC{offset:+}" if isinstance(offset, (int, float)) else "UTC?"
                print(f"[TZ] Ticker {ticker_id} timezone set to {tz_name} ({off_txt}) from fallback IP {query_ip or 'unknown'}")
                save_specific_ticker(ticker_id)

    prev_ip = str(rec.get('last_ip', '')).strip()
    prev_tz = str(rec.get('settings', {}).get('timezone_name', '')).strip()

    if ip_addr == prev_ip and prev_tz:
        # IP unchanged: still refresh offset from timezone to follow DST.
        off = _utc_offset_hours_for_timezone(prev_tz)
        if off is not None and rec.get('settings', {}).get('utc_offset') != off:
            rec['settings']['utc_offset'] = off
            print(f"[TZ] Ticker {ticker_id} offset refreshed from timezone {prev_tz}: UTC{off:+}")
            save_specific_ticker(ticker_id)
        return

    if ip_addr:
        tz_name, offset = _lookup_timezone_for_ip(ip_addr)
        if tz_name:
            if offset is None:
                offset = _utc_offset_hours_for_timezone(tz_name)

            changed = _apply_ticker_timezone(rec, tz_name, offset)
            if rec.get('last_ip') != ip_addr:
                rec['last_ip'] = ip_addr
                changed = True

            if changed:
                off_txt = f"UTC{offset:+}" if isinstance(offset, (int, float)) else "UTC?"
                print(f"[TZ] Ticker {ticker_id} timezone set to {tz_name} ({off_txt}) from IP {ip_addr}")
                save_specific_ticker(ticker_id)

    # Final fallback: derive timezone from configured weather coordinates.
    settings = rec.setdefault('settings', {})
    lat = settings.get('weather_lat', state.get('weather_lat'))
    lon = settings.get('weather_lon', state.get('weather_lon'))
    ll_tz, ll_off = _lookup_timezone_for_latlon(lat, lon)
    if not ll_tz:
        return

    ll_changed = _apply_ticker_timezone(rec, ll_tz, ll_off)
    if ll_changed:
        off_txt = f"UTC{ll_off:+}" if isinstance(ll_off, (int, float)) else "UTC?"
        print(f"[TZ] Ticker {ticker_id} timezone set from weather coords ({lat},{lon}): {ll_tz} ({off_txt})")
        save_specific_ticker(ticker_id)


def _apply_timezone_to_game_times(games: list, tz_name: str = '', utc_offset: float = -5.0):
    if not isinstance(games, list):
        return

    tz_obj = None
    if tz_name and ZoneInfo:
        try:
            tz_obj = ZoneInfo(tz_name)
        except Exception:
            tz_obj = None

    try:
        offset_hours = float(utc_offset)
    except Exception:
        offset_hours = -5.0

    fallback_tz = timezone(timedelta(hours=offset_hours))

    for g in games:
        if not isinstance(g, dict):
            continue
        if g.get('state') != 'pre':
            continue
        start_utc = g.get('startTimeUTC')
        if not start_utc:
            continue
        try:
            game_dt = parse_iso(start_utc)
            local_dt = game_dt.astimezone(tz_obj) if tz_obj else game_dt.astimezone(fallback_tz)
            g['status'] = local_dt.strftime("%I:%M %p").lstrip('0')
        except Exception:
            continue


def _blank_logo_url_for_request(req) -> str:
    """Return the configured transparent placeholder logo URL."""
    return BLANK_LOGO_URL


def _materialize_blank_logo_urls(games: list, req):
    """Replace sentinel logo values with a real URL the app can load."""
    if not isinstance(games, list):
        return
    blank_url = _blank_logo_url_for_request(req)
    for g in games:
        if not isinstance(g, dict):
            continue
        if g.get('home_logo') == BLANK_LOGO_SENTINEL:
            g['home_logo'] = blank_url
        if g.get('away_logo') == BLANK_LOGO_SENTINEL:
            g['away_logo'] = blank_url


def fetch_json(session, url, *, timeout=None, params=None, headers=None):
    """
    Safe HTTP GET returning parsed JSON. Raises on non-2xx status.
    Uses TIMEOUTS['default'] if timeout is not specified.
    """
    r = session.get(
        url,
        params=params or {},
        headers=headers or {},
        timeout=timeout or TIMEOUTS['default']
    )
    r.raise_for_status()
    return r.json()
