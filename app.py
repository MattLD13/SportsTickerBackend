# ── Standard library ──
import csv
import concurrent.futures
import glob
import hmac
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
import uuid
from html import escape
from datetime import datetime as dt, timezone, timedelta

try:
    from zoneinfo import ZoneInfo
except ImportError:
    ZoneInfo = None

# ── Third-party ──
import requests
from requests.adapters import HTTPAdapter
from flask import Flask, jsonify, make_response, redirect, request, session
from flask_cors import CORS
from dotenv import load_dotenv
import spotipy
from spotipy.oauth2 import SpotifyOAuth
from google import genai
from google.genai import types

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

if GEMINI_KEY:
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
    'AC': 'ACA', 'WS': 'WJA', 'EI': 'EIN', 'LY': 'ELY',
}

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
    'BE20': 'Beechcraft King Air 200', 'BE30': 'Beechcraft King Air 350',
}

def normalize_aircraft_type(icao_code, fr24_model=None):
    """Return human-readable aircraft name. Prefers FR24 detail model, falls back to local table."""
    if fr24_model:
        return fr24_model
    if icao_code:
        return _AIRCRAFT_TYPE_NAMES.get(icao_code.upper(), icao_code.upper())
    return ''

# ================= SERVER VERSION TAG =================
SERVER_VERSION = "v0.9-Madness"

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
            self.original_stdout.write(data)
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
POOP_TRACKER_STATE_FILE = os.path.join(TICKER_DATA_DIR, "pooptracker_state.json")
POOP_ADMIN_PASSWORD_FILE = os.path.join(TICKER_DATA_DIR, ".poop_admin_password")


def _default_poop_admin_password():
    return ''.join(chr(x) for x in (97, 100, 109, 105, 110))


def _load_poop_admin_password():
    env_value = (os.getenv('POOP_ADMIN_PASSWORD') or '').strip()
    if env_value:
        return env_value

    if os.path.exists(POOP_ADMIN_PASSWORD_FILE):
        try:
            with open(POOP_ADMIN_PASSWORD_FILE, 'r', encoding='utf-8') as f:
                value = f.read().strip()
            if value:
                return value
        except Exception as e:
            print(f"Poop admin password read error: {e}")

    seeded_value = _default_poop_admin_password()
    try:
        with open(POOP_ADMIN_PASSWORD_FILE, 'w', encoding='utf-8') as f:
            f.write(seeded_value)
    except Exception as e:
        print(f"Poop admin password write error: {e}")
    return seeded_value


POOP_ADMIN_PASSWORD = _load_poop_admin_password()

# Only this ticker can see/select poop_fetcher mode.
POOP_FETCHER_MODE_TICKER_ID = "722c59f4-fce3-4735-b072-faaa2f579a0a"

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

def get_city_name(iata_code):
    if not iata_code or not AIRPORTS_DB: return 'UNKNOWN'
    code = iata_code.strip().upper()
    if code in AIRPORTS_DB:
        return AIRPORTS_DB[code].get('city', code)
    return code

# Initialize cache
_ai_airport_cache = {}

def load_airport_cache():
    global _ai_airport_cache
    if os.path.exists(AIRPORT_CACHE_FILE):
        try:
            with open(AIRPORT_CACHE_FILE, 'r') as f:
                _ai_airport_cache = json.load(f)
            print(f"📖 Loaded {len(_ai_airport_cache)} shortened airport names from cache.")
        except Exception as e:
            print(f"⚠️ Error loading airport cache: {e}")

def save_airport_cache():
    try:
        # Atomic save to prevent corruption
        temp_file = f"{AIRPORT_CACHE_FILE}.tmp"
        with open(temp_file, 'w') as f:
            json.dump(_ai_airport_cache, f, indent=4)
        os.replace(temp_file, AIRPORT_CACHE_FILE)
    except Exception as e:
        print(f"⚠️ Error saving airport cache: {e}")

# Load the cache immediately upon script start
load_airport_cache()

# ── Airline code cache (IATA ↔ ICAO, AI-resolved, persisted to disk) ──
_ai_airline_cache: dict = {}   # bidirectional: "UA"→"UAL" and "UAL"→"UA"

def load_airline_cache():
    global _ai_airline_cache
    if os.path.exists(AIRLINE_CACHE_FILE):
        try:
            with open(AIRLINE_CACHE_FILE, 'r') as f:
                _ai_airline_cache = json.load(f)
            print(f"📖 Loaded {len(_ai_airline_cache)} airline codes from cache.")
        except Exception as e:
            print(f"⚠️ Error loading airline cache: {e}")

def save_airline_cache():
    try:
        temp_file = f"{AIRLINE_CACHE_FILE}.tmp"
        with open(temp_file, 'w') as f:
            json.dump(_ai_airline_cache, f, indent=4)
        os.replace(temp_file, AIRLINE_CACHE_FILE)
    except Exception as e:
        print(f"⚠️ Error saving airline cache: {e}")

load_airline_cache()

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
            save_airline_cache()
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
                    save_airport_cache()
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
    save_airport_cache()
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
LEAGUE_OPTIONS = [
    {'id': 'nfl', 'label': 'NFL', 'type': 'sport', 'default': True, 'fetch': {'path': 'football/nfl', 'team_params': {'limit': 100}, 'type': 'scoreboard'}},
    {'id': 'mlb', 'label': 'MLB', 'type': 'sport', 'default': True, 'fetch': {'path': 'baseball/mlb', 'team_params': {'limit': 100}, 'type': 'scoreboard'}},
    {'id': 'nhl', 'label': 'NHL', 'type': 'sport', 'default': True, 'fetch': {'path': 'hockey/nhl', 'team_params': {'limit': 100}, 'type': 'scoreboard'}},
    {'id': 'nba', 'label': 'NBA', 'type': 'sport', 'default': True, 'fetch': {'path': 'basketball/nba', 'team_params': {'limit': 100}, 'type': 'scoreboard'}},
    {'id': 'ncf_fbs', 'label': 'NCAA (FBS)', 'type': 'sport', 'default': True, 'fetch': {'path': 'football/college-football', 'scoreboard_params': {'groups': '80'}, 'type': 'scoreboard'}},
    {'id': 'ncf_fcs', 'label': 'NCAA (FCS)', 'type': 'sport', 'default': True, 'fetch': {'path': 'football/college-football', 'scoreboard_params': {'groups': '81'}, 'type': 'scoreboard'}},
    {'id': 'march_madness', 'label': 'March Madness', 'type': 'sport', 'default': True, 'fetch': {'path': 'basketball/mens-college-basketball', 'scoreboard_params': {'groups': '100', 'limit': '100'}, 'type': 'scoreboard'}},
    {'id': 'soccer_epl', 'label': 'Premier League', 'type': 'sport', 'default': True, 'fetch': {'path': 'soccer/eng.1', 'team_params': {'limit': 50}, 'type': 'scoreboard'}},
    {'id': 'soccer_fa_cup','label': 'FA Cup', 'type': 'sport', 'default': True, 'fetch': {'path': 'soccer/eng.fa', 'type': 'scoreboard'}},
    {'id': 'soccer_champ', 'label': 'Championship', 'type': 'sport', 'default': True, 'fetch': {'path': 'soccer/eng.2', 'team_params': {'limit': 50}, 'type': 'scoreboard'}},
    {'id': 'soccer_l1', 'label': 'League One', 'type': 'sport', 'default': True, 'fetch': {'path': 'soccer/eng.3', 'team_params': {'limit': 50}, 'type': 'scoreboard'}},
    {'id': 'soccer_l2', 'label': 'League Two', 'type': 'sport', 'default': True, 'fetch': {'path': 'soccer/eng.4', 'team_params': {'limit': 50}, 'type': 'scoreboard'}},
    {'id': 'soccer_wc', 'label': 'FIFA World Cup', 'type': 'sport', 'default': True, 'fetch': {'path': 'soccer/fifa.world', 'team_params': {'limit': 100}, 'type': 'scoreboard'}},
    {'id': 'soccer_champions_league', 'label': 'Champions League', 'type': 'sport', 'default': True, 'fetch': {'path': 'soccer/uefa.champions', 'team_params': {'limit': 50}, 'type': 'scoreboard'}},
    {'id': 'soccer_europa_league', 'label': 'Europa League', 'type': 'sport', 'default': True, 'fetch': {'path': 'soccer/uefa.europa', 'team_params': {'limit': 200}, 'type': 'scoreboard'}},
    {'id': 'soccer_mls', 'label': 'MLS', 'type': 'sport', 'default': True, 'fetch': {'path': 'soccer/usa.1', 'team_params': {'limit': 100}, 'type': 'scoreboard'}},
    #{'id': 'wbc', 'label': 'WBC', 'type': 'sport', 'default': True, 'fetch': {'path': 'baseball/world-baseball-classic', 'type': 'scoreboard'}},
    #{'id': 'f1', 'label': 'Formula 1', 'type': 'sport', 'default': True, 'fetch': {'path': 'racing/f1', 'type': 'leaderboard'}},
    #{'id': 'nascar', 'label': 'NASCAR', 'type': 'sport', 'default': True, 'fetch': {'path': 'racing/nascar', 'type': 'leaderboard'}},
    {'id': 'weather', 'label': 'Weather', 'type': 'util', 'default': True},
    {'id': 'clock', 'label': 'Clock', 'type': 'util', 'default': True},
    {'id': 'music', 'label': 'Music', 'type': 'util', 'default': True},
    {'id': 'poop_fetcher', 'label': 'Poop Fetcher', 'type': 'util', 'default': False},
    {'id': 'flight_tracker', 'label': 'Flight Tracker', 'type': 'util', 'default': False},
    {'id': 'flight_airport', 'label': 'Airport Activity', 'type': 'util', 'default': False},
    {'id': 'stock_tech_ai', 'label': 'Tech / AI Stocks', 'type': 'stock', 'default': True, 'stock_list': ["AAPL", "MSFT", "NVDA", "GOOGL", "AMZN", "META", "TSM", "AVGO", "ORCL", "CRM", "AMD", "IBM", "INTC", "QCOM", "CSCO", "ADBE", "TXN", "AMAT", "INTU", "NOW", "MU"]},
    {'id': 'stock_momentum', 'label': 'Momentum Stocks', 'type': 'stock', 'default': False, 'stock_list': ["COIN", "HOOD", "DKNG", "RBLX", "GME", "AMC", "MARA", "RIOT", "CLSK", "SOFI", "OPEN", "UBER", "DASH", "SHOP", "NET", "SQ", "PYPL", "AFRM", "UPST", "CVNA"]},
    {'id': 'stock_energy', 'label': 'Energy Stocks', 'type': 'stock', 'default': False, 'stock_list': ["XOM", "CVX", "COP", "EOG", "SLB", "MPC", "PSX", "VLO", "OXY", "KMI", "HAL", "BKR", "HES", "DVN", "OKE", "WMB", "CTRA", "FANG", "TTE", "BP"]},
    {'id': 'stock_finance', 'label': 'Financial Stocks', 'type': 'stock', 'default': False, 'stock_list': ["JPM", "BAC", "WFC", "C", "GS", "MS", "BLK", "AXP", "V", "MA", "SCHW", "USB", "PNC", "TFC", "BK", "COF", "SPGI", "MCO", "CB", "PGR"]},
    {'id': 'stock_consumer', 'label': 'Consumer Stocks', 'type': 'stock', 'default': False, 'stock_list': ["WMT", "COST", "TGT", "HD", "LOW", "MCD", "SBUX", "CMG", "NKE", "LULU", "KO", "PEP", "PG", "CL", "KMB", "DIS", "NFLX", "CMCSA", "HLT", "MAR"]},
]

# Pre-built label lookup from LEAGUE_OPTIONS (replaces next() linear scan in get_list)
_LEAGUE_LABEL_MAP = {item['id']: item['label'] for item in LEAGUE_OPTIONS}
# Authoritative set of valid league IDs — used to reject stale keys from clients/config
_VALID_LEAGUE_IDS = frozenset(item['id'] for item in LEAGUE_OPTIONS)
# Pre-built stock list index — LEAGUE_OPTIONS is constant, no need to rebuild per StockFetcher init
_STOCK_LISTS = {
    item['id']: item['stock_list']
    for item in LEAGUE_OPTIONS
    if item['type'] == 'stock' and 'stock_list' in item
}

# Pre-compiled regex and frozensets for hot-path checks
_TIME_RE = re.compile(r'\d+:\d+')
_ACTIVE_STATES = frozenset({'in', 'half', 'crit'})
_SUSP_KEYWORDS = frozenset(["postponed", "suspended", "canceled", "ppd"])


def _game_sort_key(x):
    t = x.get('type', '')
    if t == 'clock':
        prio = 0
    elif t == 'weather':
        prio = 1
    else:
        s = str(x.get('status', ''))
        sl = s.lower()
        if any(k in sl for k in _SUSP_KEYWORDS):
            prio = 4
        elif "FINAL" in s.upper() or sl == "fin":
            prio = 3
        else:
            prio = 2
    return (prio, x.get('startTimeUTC') or '9999', x.get('sport', ''), x.get('home_abbr', ''), x.get('away_abbr', ''), str(x.get('id') or '0'))


# Valid mode set — no 'all', no 'flight2', no 'flight_submode'
VALID_MODES = {'sports', 'sports_full', 'live', 'my_teams', 'stocks', 'weather', 'music', 'clock', 'flights', 'flight_tracker', 'poop_fetcher'}


def _is_poop_fetcher_mode_allowed(ticker_id):
    return str(ticker_id or '').strip() == str(POOP_FETCHER_MODE_TICKER_ID).strip()

# Legacy mode migration map applied at load time and on /api/config writes
MODE_MIGRATIONS = {'all': 'sports', 'flight2': 'flight_tracker'}

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
    "MLB:SD": "https://a.espncdn.com/guid/4dec648c-3eb9-055c-aebc-2711f30975a0/logos/primary_logo_on_primary_color.png", "MARCH_MADNESS:IOWA": "https://a.espncdn.com/guid/b7840e2f-6236-e764-2cae-20286a0829e7/logos/primary_logo_on_black_color.png"
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
    95: "THUNDERSTORM", 96: "THUNDERSTORM/HAIL", 99: "THUNDERSTORM/HAIL",
}

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
for _k in list(state['active_sports'].keys()):
    if _k not in _valid_league_ids:
        del state['active_sports'][_k]
for _item in LEAGUE_OPTIONS:
    if _item['id'] not in state['active_sports']:
        state['active_sports'][_item['id']] = _item['default']

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
                'ts': now_ts,
            }
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
                'ts': now_ts,
            }
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
            "timezone": "auto",
        }
        resp = requests.get(url, params=params, timeout=TIMEOUTS.get('quick', 3))
        data = resp.json() if resp.ok else {}
        tz_name = str(data.get('timezone') or '').strip()
        if not tz_name:
            return None, None

        off = _utc_offset_hours_for_timezone(tz_name)
        _IP_TZ_CACHE[cache_key] = {
            'timezone': tz_name,
            'offset': off,
            'ts': now_ts,
        }
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


def _maybe_update_ticker_timezone_from_request(ticker_id: str, req):
    if not ticker_id or ticker_id not in tickers:
        return

    rec = tickers[ticker_id]

    # Prefer timezone provided by the ticker device itself.
    hdr_tz, hdr_offset = _extract_timezone_from_request_headers(req)
    if hdr_tz or hdr_offset is not None:
        changed = False
        settings = rec.setdefault('settings', {})
        if hdr_tz and settings.get('timezone_name') != hdr_tz:
            settings['timezone_name'] = hdr_tz
            changed = True
        if hdr_offset is not None and settings.get('utc_offset') != hdr_offset:
            settings['utc_offset'] = hdr_offset
            changed = True
        if hdr_tz and rec.get('timezone_name') != hdr_tz:
            rec['timezone_name'] = hdr_tz
            changed = True

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

            changed = False
            settings = rec.setdefault('settings', {})
            if settings.get('timezone_name') != tz_name:
                settings['timezone_name'] = tz_name
                changed = True
            if offset is not None and settings.get('utc_offset') != offset:
                settings['utc_offset'] = offset
                changed = True
            if rec.get('timezone_name') != tz_name:
                rec['timezone_name'] = tz_name
                changed = True
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

            changed = False
            settings = rec.setdefault('settings', {})
            if settings.get('timezone_name') != tz_name:
                settings['timezone_name'] = tz_name
                changed = True
            if offset is not None and settings.get('utc_offset') != offset:
                settings['utc_offset'] = offset
                changed = True
            if rec.get('timezone_name') != tz_name:
                rec['timezone_name'] = tz_name
                changed = True
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

    ll_changed = False
    if settings.get('timezone_name') != ll_tz:
        settings['timezone_name'] = ll_tz
        ll_changed = True
    if ll_off is not None and settings.get('utc_offset') != ll_off:
        settings['utc_offset'] = ll_off
        ll_changed = True
    if rec.get('timezone_name') != ll_tz:
        rec['timezone_name'] = ll_tz
        ll_changed = True

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


# ================= TEST MODE =================

_SENTINEL = object()  # used to distinguish "not passed" from None in TestMode.configure

class TestMode:
    """
    Centralized simulation / debug mode manager.

    In production this class is completely inert (all flags False by default).

    Usage examples:
        TestMode.configure(enabled=True)              # turn on all subsystems
        TestMode.configure(stocks=True)               # stocks-only test
        TestMode.configure(enabled=False)             # turn everything off
        TestMode.is_enabled('spotify')                # → bool
        TestMode.get_custom_date()                    # → 'YYYYMMDD' or None
        TestMode.get_fake_playlist()                  # → list of song dicts
        TestMode.get_fake_stock_price('AAPL')         # → {base, change, pct}
        TestMode.status()                             # → dict snapshot for /api/debug
    """

    _enabled: bool = False
    _subsystems: dict = {
        'spotify':     False,   # simulate Spotify playback
        'stocks':      False,   # simulate stock prices
        'sports_date': False,   # override sports date with custom_date
        'flights':     False,   # verbose flight debug logging
    }
    _custom_date: str | None = None

    # Simulation data lives here — not scattered in individual class constructors
    _FAKE_PLAYLIST = [
        {
            "name": "Simulated Song", "artist": "The Test Band",
            "cover": "https://upload.wikimedia.org/wikipedia/commons/thumb/c/c1/Google_%22G%22_logo.svg/768px-Google_%22G%22_logo.svg.png",
            "duration": 180.0
        },
        {
            "name": "Coding All Night", "artist": "Dev Team",
            "cover": "https://upload.wikimedia.org/wikipedia/commons/thumb/9/99/Unofficial_JavaScript_logo_2.svg/1024px-Unofficial_JavaScript_logo_2.svg.png",
            "duration": 240.0
        },
        {
            "name": "Offline Mode", "artist": "No Wifi",
            "cover": "https://upload.wikimedia.org/wikipedia/commons/thumb/e/e4/Visual_Editor_-_Icon_-_No-connection.svg/1024px-Visual_Editor_-_Icon_-_No-connection.svg.png",
            "duration": 120.0
        },
    ]

    @classmethod
    def configure(cls, *, enabled=None, custom_date=_SENTINEL, **subsystems):
        """
        Update test mode settings.
        - enabled=True  → flip all subsystems on at once
        - enabled=False → turn all off
        - Individual kwargs (spotify=True, stocks=False) control per-subsystem
        - custom_date='YYYY-MM-DD' sets the sports date override string
        """
        if custom_date is not _SENTINEL:
            cls._custom_date = custom_date

        if enabled is True:
            cls._enabled = True
            for k in cls._subsystems:
                cls._subsystems[k] = True
        elif enabled is False:
            cls._enabled = False
            for k in cls._subsystems:
                cls._subsystems[k] = False

        for k, v in subsystems.items():
            if k in cls._subsystems:
                cls._subsystems[k] = bool(v)
                if v:
                    cls._enabled = True  # any subsystem on → globally enabled

    @classmethod
    def is_enabled(cls, subsystem: str) -> bool:
        """Return True if the named subsystem simulation is active."""
        return cls._subsystems.get(subsystem, False)

    @classmethod
    def get_custom_date(cls) -> str | None:
        """Return the date override as a YYYYMMDD string, or None if not active."""
        if cls._custom_date and cls.is_enabled('sports_date'):
            return cls._custom_date.replace('-', '')
        return None

    @classmethod
    def get_fake_playlist(cls):
        """Return the simulated Spotify playlist."""
        return cls._FAKE_PLAYLIST

    @classmethod
    def get_fake_stock_price(cls, symbol: str) -> dict:
        """
        Return deterministic, slowly-fluctuating fake price data for a symbol.
        Logic originally lived in StockFetcher._fetch_single_stock.
        """
        base_price = sum(ord(c) for c in symbol) % 200 + 50
        variation = (time.time() % 600) / 100.0
        current_price = base_price + math.sin(variation + len(symbol)) * 5
        change = math.sin(variation * 2) * 2.5
        pct = (change / base_price) * 100
        return {'base': current_price, 'change': change, 'pct': pct}

    @classmethod
    def status(cls) -> dict:
        """Snapshot of current test mode state, exposed by /api/debug GET."""
        return {
            'enabled': cls._enabled,
            'subsystems': dict(cls._subsystems),
            'custom_date': cls._custom_date,
        }


class SpotifyFetcher(threading.Thread):
    def __init__(self):
        super().__init__()
        self.daemon = True
        self._lock = threading.Lock()
        
        self.client_id = os.getenv('SPOTIFY_CLIENT_ID')
        self.client_secret = os.getenv('SPOTIFY_CLIENT_SECRET')

        # --- INTERNAL CACHE ---
        self.cached_current_id = None
        self.cached_current_cover = ""
        self.cached_queue_covers = [] 

        # --- STATE ---
        self.state = {
            "is_playing": False,
            "name": "Waiting for Music...",
            "artist": "",
            "cover": "",          
            "last_cover": "",     
            "next_covers": [],    
            "duration": 0,
            "progress": 0,
            "last_fetch_ts": time.time()
        }

    def get_cached_state(self):
        with self._lock: 
            return self.state.copy()

    def run_simulation(self):
        """Runs a fake loop when no API keys are present or test_spotify is enabled."""
        print("⚠️ Spotify: no API keys or test mode active — starting MUSIC SIMULATION.")
        idx = 0
        while True:
            playlist = TestMode.get_fake_playlist()
            song = playlist[idx]

            next_1 = playlist[(idx + 1) % len(playlist)]
            next_2 = playlist[(idx + 2) % len(playlist)]

            start_time = time.time()

            with self._lock:
                self.state.update({
                    "is_playing": True,
                    "name": song['name'],
                    "artist": song['artist'],
                    "cover": song['cover'],
                    "last_cover": playlist[(idx - 1) % len(playlist)]['cover'],
                    "next_covers": [next_1['cover'], next_2['cover']],
                    "duration": song['duration'],
                    "progress": 0,
                    "last_fetch_ts": start_time
                })

            # Simulate playback: update progress every second for 20s, then advance
            for _ in range(20):
                time.sleep(1)
                with self._lock:
                    self.state['progress'] = time.time() - start_time
                    self.state['last_fetch_ts'] = time.time()

            idx = (idx + 1) % len(playlist)

    def run(self):
        # Run simulation if keys are missing OR test_spotify is explicitly enabled
        if not self.client_id or not self.client_secret or TestMode.is_enabled('spotify'):
            self.run_simulation()
            return

        print("✅ Spotify Adaptive Polling Started")

        sp = None
        while not sp:
            try:
                auth_manager = SpotifyOAuth(
                    client_id=self.client_id,
                    client_secret=self.client_secret,
                    redirect_uri="http://127.0.0.1:8888/callback",
                    scope="user-read-playback-state user-read-currently-playing",
                    open_browser=False,
                    cache_path=".spotify_token"
                )
                sp = spotipy.Spotify(auth_manager=auth_manager)
            except Exception as e:
                print(f"Spotify Init Failed (Retrying in 5s): {e}")
                time.sleep(5)
        
        current_delay = 1.0

        while True:
            try:
                current = None
                fetch_success = False

                try:
                    current = sp.current_user_playing_track()
                    fetch_success = True
                except Exception as e:
                    # STAGE 3: Error/Long Polling (>5s)
                    print(f"Spotify API Error: {e}")
                    current_delay = 5.0

                if fetch_success:
                    if current and current.get('item'):
                        item = current['item']
                        is_playing = current.get('is_playing', False)
                        progress_ms = current.get('progress_ms', 0)

                        current_id = item.get('id')
                        current_cover = item['album']['images'][0]['url'] if item.get('album',{}).get('images') else ""

                        # Only fetch heavy queue data if the song changed
                        if self.cached_current_id != current_id:
                            self.state['last_cover'] = self.cached_current_cover
                            try:
                                queue_data = sp.queue()
                                new_queue = []
                                if queue_data and 'queue' in queue_data:
                                    for q_track in queue_data['queue'][:3]:
                                        if q_track.get('album') and q_track['album'].get('images'):
                                            new_queue.append(q_track['album']['images'][0]['url'])
                                        else:
                                            new_queue.append("")
                                self.cached_queue_covers = new_queue
                            except: pass # Queue fetch failures shouldn't crash the loop

                        self.cached_current_id = current_id
                        self.cached_current_cover = current_cover

                        with self._lock:
                            self.state.update({
                                "is_playing": is_playing,
                                "name": item.get('name', 'Unknown'),
                                "artist": ", ".join(a['name'] for a in item.get('artists', [])),
                                "cover": current_cover,
                                "next_covers": self.cached_queue_covers,
                                "duration": item.get('duration_ms', 0) / 1000.0,
                                "progress": progress_ms / 1000.0,
                                "last_fetch_ts": time.time()
                            })

                        # STAGE 1 vs STAGE 2
                        # Quick Polling (0.6s) if playing, Medium (1.5s) if paused
                        current_delay = 0.6 if is_playing else 1.5

                    elif current is None:
                        # STAGE 2: No Content / Idle (3s)
                        with self._lock:
                            self.state['is_playing'] = False
                        current_delay = 3.0

            except Exception as e:
                print(f"Spotify Critical Loop Error: {e}")
                current_delay = 10.0 # Long backoff for critical failures

            time.sleep(current_delay)

class WeatherFetcher:
    def __init__(self, initial_lat=40.7128, initial_lon=-74.0060, city="New York"):
        self.lat = initial_lat
        self.lon = initial_lon
        self.city_name = city
        self.last_fetch = 0
        self.cache = None
        self.session = build_pooled_session(pool_size=10)

    def update_config(self, city=None, lat=None, lon=None):
        try:
            if lat is not None: self.lat = float(lat)
            if lon is not None: self.lon = float(lon)
            if city is not None: self.city_name = str(city)
            self.last_fetch = 0 # Force refresh
            print(f"✅ Weather config updated: {self.city_name} ({self.lat}, {self.lon})")
        except Exception as e:
            print(f"⚠️ Error updating weather config: {e}")

    def get_weather_icon(self, wmo_code):
        try:
            code = int(wmo_code)
        except:
            return 'cloud'
            
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
        # 1. Return Cache if fresh (< 15 mins)
        if time.time() - self.last_fetch < CACHE_TTL['weather'] and self.cache:
            return self.cache
        
        try:
            # 2. Validate coordinates
            if self.lat is None or self.lon is None:
                print("❌ Weather Error: Invalid Coordinates (None)")
                return self.cache

            # 3. Fetch Forecast (Independent Step)
            w_data = {}
            try:
                w_url = f"https://api.open-meteo.com/v1/forecast?latitude={self.lat}&longitude={self.lon}&current=temperature_2m,weather_code&daily=weather_code,temperature_2m_max,temperature_2m_min,uv_index_max&temperature_unit=fahrenheit&timezone=auto"
                w_resp = self.session.get(w_url, timeout=TIMEOUTS['slow'])
                if w_resp.status_code == 200:
                    w_data = w_resp.json()
                else:
                    print(f"⚠️ Weather API Error: {w_resp.status_code} - {w_resp.text}")
                    return self.cache # Keep showing old data if fetch fails
            except Exception as e:
                print(f"⚠️ Weather Connection Failed: {e}")
                return self.cache

            # 4. Fetch Air Quality (Separate Step - Fail Safe)
            aqi = 0
            try:
                a_url = f"https://air-quality-api.open-meteo.com/v1/air-quality?latitude={self.lat}&longitude={self.lon}&current=us_aqi"
                a_resp = self.session.get(a_url, timeout=TIMEOUTS['stock'])
                if a_resp.status_code == 200:
                    a_data = a_resp.json()
                    aqi = a_data.get('current', {}).get('us_aqi', 0)
            except Exception:
                pass # If AQI fails, just show 0, don't crash the widget

            # 5. Parse Data
            current = w_data.get('current', {})
            daily = w_data.get('daily', {})

            if not current:
                print("⚠️ Weather Error: Missing 'current' data in response")
                return self.cache

            current_temp = int(round(current.get('temperature_2m', 0)))
            current_code = current.get('weather_code', 0)
            current_icon = self.get_weather_icon(current_code)
            
            uv = 0
            if 'uv_index_max' in daily and len(daily['uv_index_max']) > 0:
                uv = daily['uv_index_max'][0]

            forecast_list = []
            if 'time' in daily:
                days_count = len(daily['time'])
                # Safe loop that won't crash if API returns fewer days than expected
                for i in range(min(5, days_count)): 
                    try:
                        f_day = {
                            "day": self.get_day_name(daily['time'][i]),
                            "icon": self.get_weather_icon(daily['weather_code'][i]),
                            "high": int(round(daily['temperature_2m_max'][i])),
                            "low": int(round(daily['temperature_2m_min'][i]))
                        }
                        forecast_list.append(f_day)
                    except: continue

            # 6. Build Object
            self.cache = {
                "type": "weather",
                "sport": "weather",
                "id": "weather_main",
                "away_abbr": str(self.city_name).upper(), 
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
            print(f"❌ Critical Weather Error: {e}")
            return self.cache

class StockFetcher:
    def __init__(self):
        self.market_cache = {}
        self.last_fetch = 0
        self.update_interval = STOCKS_UPDATE_INTERVAL
        
        possible_keys = [
            os.getenv('FINNHUB_API_KEY'), 
            os.getenv('FINNHUB_KEY_1'),
            os.getenv('FINNHUB_KEY_2'),
            os.getenv('FINNHUB_KEY_3'),
            os.getenv('FINNHUB_KEY_4'),
            os.getenv('FINNHUB_KEY_5')
        ]
        self.api_keys = list(set([k for k in possible_keys if k and len(k) > 10]))
        
        # --- SIMULATION MODE ---
        self.simulated = False
        if not self.api_keys:
            print("⚠️ No Finnhub Keys found. Starting STOCK SIMULATION mode.")
            self.simulated = True
            self.safe_sleep_time = 0.1
        else:
            self.safe_sleep_time = 1.1 / len(self.api_keys)
            print(f"✅ Loaded {len(self.api_keys)} API Keys. Stock Speed: {self.safe_sleep_time:.2f}s per request.")

        self.current_key_index = 0
        self.session = build_pooled_session(pool_size=4, retries=1)
        self.lists = _STOCK_LISTS
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

    @staticmethod
    def _make_stock_result(symbol, price, change_raw, change_pct):
        return {
            'symbol': symbol,
            'price': f"{price:.2f}",
            'change_amt': f"{'+' if change_raw >= 0 else ''}{change_raw:.2f}",
            'change_pct': f"{'+' if change_pct >= 0 else ''}{change_pct:.2f}%"
        }

    def _fetch_single_stock(self, symbol):
        # Run simulation if keys are absent OR test_stocks is explicitly enabled
        if self.simulated or TestMode.is_enabled('stocks'):
            r = TestMode.get_fake_stock_price(symbol)
            return self._make_stock_result(symbol, r['base'], r['change'], r['pct'])

        api_key = self._get_next_key()
        if not api_key: return None

        try:
            r = self.session.get("https://finnhub.io/api/v1/quote", params={'symbol': symbol, 'token': api_key}, timeout=TIMEOUTS['stock'])
            if r.status_code == 429: time.sleep(2); return None
            r.raise_for_status()
            data = r.json()

            ts = data.get('t', 0)
            now_ts = time.time()
            is_stale = (now_ts - ts) > CACHE_TTL['stock']

            if not is_stale and data.get('c', 0) > 0:
                return self._make_stock_result(symbol, data['c'], data.get('d', 0), data.get('dp', 0))

            if is_stale:
                to_time = int(now_ts)
                from_time = to_time - 1800
                c_r = self.session.get(
                    "https://finnhub.io/api/v1/stock/candle",
                    params={'symbol': symbol, 'resolution': '1', 'from': from_time, 'to': to_time, 'token': api_key},
                    timeout=TIMEOUTS['stock']
                )
                c_data = c_r.json()
                if c_data.get('s') == 'ok' and c_data.get('c'):
                    latest_close = c_data['c'][-1]
                    prev_close = data.get('pc', latest_close)
                    change_raw = latest_close - prev_close
                    change_pct = (change_raw / prev_close) * 100
                    return self._make_stock_result(symbol, latest_close, change_raw, change_pct)

            if data.get('c', 0) > 0:
                return self._make_stock_result(symbol, data['c'], data.get('d', 0), data.get('dp', 0))

        except Exception:
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
            if not self.simulated:
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
        label = _LEAGUE_LABEL_MAP.get(list_key, "MARKET")
        for sym in self.lists.get(list_key, []):
            obj = self.get_stock_obj(sym, label)
            if obj: res.append(obj)
        return res

class FlightTracker:
    def __init__(self):
        self.session = build_pooled_session(pool_size=10)
        self.lock = threading.Lock()
        self.visitor_flight = None
        self.airport_arrivals = []
        self.airport_departures = []
        self.airport_weather = {"temp": "--", "cond": "LOADING"}
        self.track_flight_id = ""
        self.track_guest_name = ""
        self.airport_code_icao = ""
        self.airport_code_iata = ""
        self.airport_name = ""
        self.airline_filter = ""
        self.last_visitor_fetch = 0
        self.last_airport_fetch = 0
        self.running = True
        self._force_refresh = False
        # Event to force immediate fetch when config changes
        self.wake_event = threading.Event()
        # Initialize FlightRadarAPI SDK if available
        self.fr_api = FlightRadar24API() if FR24_SDK_AVAILABLE else None
    
    def force_update(self):
        """Signal the flights_worker to immediately fetch new data."""
        self._force_refresh = True
        self.wake_event.set()
    
    def log(self, cat, msg):
        # Suppress DEBUG-category output unless test_flights is on
        if cat == 'DEBUG' and not TestMode.is_enabled('flights'):
            return
        print(f"[{dt.now().strftime('%H:%M:%S')}] {cat:<12} | {msg}")
    
    def fetch_fr24_schedule(self, mode='arrivals'):
        """Includes delayed flights and sorts by closest arrival/departure time."""
        if not self.airport_code_iata:
            return []
        try:
            timestamp = int(time.time())
            url = f"https://api.flightradar24.com/common/v1/airport.json?code={self.airport_code_iata}&plugin[]=schedule&plugin-setting[schedule][mode]={mode}&plugin-setting[schedule][timestamp]={timestamp}&page=1&limit=100"
            headers = {'User-Agent': 'Mozilla/5.0', 'Accept': 'application/json'}
            
            res = self.session.get(url, headers=headers, timeout=TIMEOUTS['slow'])
            if res.status_code != 200:
                return []
            
            data = res.json()
            schedule = safe_get(data, 'result', 'response', 'airport', 'pluginData', 'schedule', mode, default={})

            if not schedule or 'data' not in schedule:
                return []
            
            processed_list = []
            for flight in schedule['data']:
                try:
                    f_data = safe_get(flight, 'flight', default={})
                    status_text = safe_get(f_data, 'status', 'generic', 'status', 'text', default='').lower()

                    # 1. Extract timestamps first so delay can gate the filter
                    time_info = safe_get(f_data, 'time', default={})
                    t_bucket = 'arrival' if mode == 'arrivals' else 'departure'

                    sched_ts = safe_get(time_info, 'scheduled', t_bucket) or 0
                    est_ts   = (safe_get(time_info, 'estimated', t_bucket)
                                or safe_get(time_info, 'other', t_bucket))

                    sort_ts = est_ts if est_ts else sched_ts
                    if sort_ts == 0: continue  # skip if absolutely no time data

                    # Detect delay: status text OR estimated 15+ min later than scheduled
                    is_delayed = (
                        'delay' in status_text or
                        (sched_ts and est_ts and
                         isinstance(sched_ts, (int, float)) and isinstance(est_ts, (int, float)) and
                         (est_ts - sched_ts) >= 900)
                    )

                    # 2. Validate the flight actually operates at this airport
                    # FR24 occasionally returns flights that route through but don't originate/terminate here
                    if mode == 'arrivals':
                        dest_iata = safe_get(f_data, 'airport', 'destination', 'code', 'iata', default='')
                        if dest_iata and dest_iata.upper() != self.airport_code_iata.upper():
                            continue
                    else:
                        origin_iata = safe_get(f_data, 'airport', 'origin', 'code', 'iata', default='')
                        if origin_iata and origin_iata.upper() != self.airport_code_iata.upper():
                            continue

                    # 3. Filter finished flights — delayed flights always pass through
                    if not is_delayed:
                        if mode == 'arrivals' and status_text == 'landed': continue
                        if mode == 'departures' and status_text == 'departed': continue

                    # 4. Build display identifier — prefer ICAO callsign (3-letter) over IATA flight number
                    callsign   = safe_get(f_data, 'identification', 'callsign', default='').strip()
                    iata_num   = safe_get(f_data, 'identification', 'number', 'default', default='').strip()
                    alt_num    = safe_get(f_data, 'identification', 'number', 'alternative', default='').strip()
                    airline_icao = safe_get(f_data, 'airline', 'code', 'icao', default='').strip()
                    airline_iata = safe_get(f_data, 'airline', 'code', 'iata', default='').strip()

                    if callsign:
                        # e.g. "UAE210", "UAL264" — already in 3-letter ICAO format
                        display_id = callsign
                    elif iata_num and airline_icao:
                        # Strip IATA prefix and replace with ICAO: "EK210" → "UAE210"
                        num_only = iata_num[len(airline_iata):] if (airline_iata and iata_num.startswith(airline_iata)) else iata_num
                        display_id = f"{airline_icao}{num_only}"
                    elif iata_num:
                        display_id = iata_num
                    elif alt_num:
                        display_id = alt_num
                    else:
                        continue  # no usable identifier

                    display_status = "DELAYED" if is_delayed else ("ARRIVING" if mode == 'arrivals' else "DEPARTING")

                    city_key = 'origin' if mode == 'arrivals' else 'destination'
                    city_code = safe_get(f_data, 'airport', city_key, 'code', 'iata', default='')
                    
                    entry = {
                        'id': display_id,
                        'status_label': display_status,
                        'sort_time': sort_ts
                    }
                    if mode == 'arrivals':
                        entry['from'] = get_airport_display_name(city_code)
                    else:
                        entry['to'] = get_airport_display_name(city_code)
                        
                    processed_list.append(entry)
                except:
                    continue
            
            # Deduplicate: same airline + same city + same departure minute = same flight
            # (EK210 and UAE36K are identical — one is the IATA number, the other the ICAO callsign)
            seen_keys = set()
            deduped = []
            for entry in processed_list:
                city = entry.get('to') or entry.get('from') or ''
                time_bucket = round(entry['sort_time'] / 60)  # bucket by minute
                key = (time_bucket, city)
                if key not in seen_keys:
                    seen_keys.add(key)
                    deduped.append(entry)
            processed_list = deduped

            # Sort by time so the closest 2 flights are selected
            processed_list.sort(key=lambda x: x['sort_time'])

            return processed_list[:2] # Return only the 2 closest flights
            
        except Exception as e:
            self.log("ERROR", f"FR24 Schedule: {e}")
            return []
    
    def parse_flight_code(self, flight_code):
        """
        Parse flight code and return (icao_code, iata_code, flight_num)
        Examples: 
        B61004 -> ('JBU', 'B6', '1004')
        JBU1004 -> ('JBU', 'B6', '1004')
        NK1149 -> ('NKS', 'NK', '1149')
        UA72 -> ('UAL', 'UA', '72')
        """
        flight_code = flight_code.replace(" ", "").upper()

        # Try 3-letter ICAO code first (JBU1004, UAL72)
        if len(flight_code) >= 4:
            potential_icao = flight_code[:3]
            if potential_icao in _ICAO_TO_IATA:
                return potential_icao, _ICAO_TO_IATA[potential_icao], flight_code[3:]

        # Try 2-character IATA code (B61004, UA72, NK1149)
        if len(flight_code) >= 3:
            potential_iata = flight_code[:2]
            if potential_iata in _IATA_TO_ICAO:
                return _IATA_TO_ICAO[potential_iata], potential_iata, flight_code[2:]

        # AI fallback — try both prefix lengths (3-letter ICAO first, then 2-letter IATA)
        for prefix_len in (3, 2):
            if len(flight_code) > prefix_len:
                prefix = flight_code[:prefix_len]
                icao, iata = ai_lookup_airline_codes(prefix)
                if icao and iata:
                    return icao, iata, flight_code[prefix_len:]

        raise ValueError(f"Invalid flight code format: {flight_code}")

    def fetch_airport_weather(self):
        if not self.airport_code_iata: return {"temp": "--", "cond": "UNKNOWN"}
        try:
            # Use airport lat/lon from airportsdata for accurate weather
            lat, lon = None, None
            if AIRPORTS_DB and self.airport_code_iata in AIRPORTS_DB:
                ap = AIRPORTS_DB[self.airport_code_iata]
                lat, lon = ap.get('lat'), ap.get('lon')
            
            if lat is None or lon is None:
                self.log("WEATHER", f"No coordinates for {self.airport_code_iata}")
                return {"temp": "--", "cond": "UNKNOWN"}
            
            # Use Open-Meteo (same API as main weather widget) — free, no key, reliable
            url = (f"https://api.open-meteo.com/v1/forecast?"
                   f"latitude={lat}&longitude={lon}"
                   f"&current=temperature_2m,weather_code"
                   f"&temperature_unit=fahrenheit&timezone=auto")
            
            self.log("WEATHER", f"Fetching weather from Open-Meteo for {self.airport_code_iata} ({lat},{lon})")
            res = self.session.get(url, timeout=TIMEOUTS['slow'])
            if res.status_code == 200:
                data = res.json()
                current = data.get('current', {})
                temp_f = current.get('temperature_2m')
                wmo_code = current.get('weather_code', -1)
                cond = WMO_DESCRIPTIONS.get(wmo_code, "UNKNOWN")
                if temp_f is not None:
                    return {"temp": f"{int(round(temp_f))}F", "cond": cond}
        except Exception as e:
            self.log("ERROR", f"Airport weather fetch failed: {e}")
        return {"temp": "--", "cond": "UNKNOWN"}
    
    def fetch_airport_activity(self):
        try:
            target_iata = self.airport_code_iata
            if not target_iata:
                return
            self.log("DEBUG", f"Starting airport fetch for {target_iata}")

            # Fetch arrivals, departures, and weather in parallel
            with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
                f_arr = pool.submit(self.fetch_fr24_schedule, 'arrivals')
                f_dep = pool.submit(self.fetch_fr24_schedule, 'departures')
                f_wx  = pool.submit(self.fetch_airport_weather)
                arrivals   = f_arr.result()
                departures = f_dep.result()
                weather    = f_wx.result()

            # Single airport-change guard after all three complete
            if self.airport_code_iata != target_iata:
                self.log("DEBUG", f"Airport changed mid-fetch, discarding results")
                return

            with self.lock:
                self.airport_arrivals = arrivals
                self.airport_departures = departures
                self.airport_weather = weather
            self.log("AIRPORT", f"{target_iata}: {len(arrivals)} arr, {len(departures)} dep | Weather: {weather['temp']}")
        except Exception as e:
            self.log("ERROR", f"Airport Loop: {e}")
    
    def fetch_visitor_tracking(self):
        if not self.track_flight_id: return
        
        try:
            self.log("TRACKER", f"Fetching flight: {self.track_flight_id}")
            fr24_data = self.fetch_fr24_flight(self.track_flight_id)
            
            if fr24_data:
                dest = fr24_data['destination']
                origin = fr24_data['origin']
                
                speed_mph = int(fr24_data['speed_kts'] * 1.15078)
                is_live = fr24_data['is_live']
                delay_min = fr24_data.get('delay_min')
                status_text = (fr24_data.get('status_text') or '').lower()
                is_delayed = (delay_min is not None and delay_min >= 15) or ('delay' in status_text)
                status = 'delayed' if is_delayed else ('en-route' if is_live else 'scheduled')
                eta_str = "DELAYED" if is_delayed else ("EN ROUTE" if is_live else "SCHEDULED")
                
                dist = 0
                progress = 0
                
                if is_live and dest in AIRPORTS_DB:
                    to_airport = AIRPORTS_DB[dest]
                    lat, lon = fr24_data['latitude'], fr24_data['longitude']
                    
                    if lat and lon:
                        dist_nm = haversine(lat, lon, to_airport['lat'], to_airport['lon'])
                        dist = int(dist_nm * 1.15078)
                        
                        if origin in AIRPORTS_DB:
                            from_airport = AIRPORTS_DB[origin]
                            total_dist = haversine(from_airport['lat'], from_airport['lon'], 
                                                   to_airport['lat'], to_airport['lon'])
                            dist_from = haversine(from_airport['lat'], from_airport['lon'], lat, lon)
                            
                            if total_dist > 0:
                                progress = max(0, min(100, int((dist_from / total_dist) * 100)))
                        
                        est_arr = fr24_data.get('est_arr')
                        if est_arr:
                            remaining_secs = est_arr - int(time.time())
                            if remaining_secs > 0:
                                mins = int(remaining_secs / 60)
                                h, m = divmod(mins, 60)
                                eta_str = f"{h}H {m}M" if h > 0 else f"{m} MIN"
                            else:
                                eta_str = "LANDING"
                        elif speed_mph > 0:
                            mins = int((dist / speed_mph) * 60)
                            h, m = divmod(mins, 60)
                            eta_str = f"{h}H {m}M" if h > 0 else f"{m} MIN"

                with self.lock:
                    self.visitor_flight = {
                        'type': 'flight_visitor',
                        'sport': 'flight',
                        'id': self.track_flight_id,
                        'guest_name': self.track_guest_name or self.track_flight_id,
                        'route': f"{origin} > {dest}",
                        'origin_city': get_airport_display_name(origin), # Shortened Name
                        'dest_city': get_airport_display_name(dest),     # Shortened Name
                        'alt': fr24_data['altitude'],
                        'dist': dist,
                        'eta_str': eta_str,
                        'speed': speed_mph,
                        'progress': progress,
                        'status': status,
                        'delay_min': delay_min,
                        'is_delayed': is_delayed,
                        'is_live': is_live,
                        'aircraft_type': fr24_data.get('aircraft_type', ''),
                        'aircraft_code': fr24_data.get('aircraft_code', ''),
                        'is_shown': True
                    }
                self.log("TRACKER", f"{self.track_flight_id} (FR24) {status} | {fr24_data['altitude']}ft")
                return
            else:
                self.log("TRACKER", f"No FR24 match for {self.track_flight_id}")
                
            # Fallback
            with self.lock:
                self.visitor_flight = {
                    'type': 'flight_visitor',
                    'sport': 'flight',
                    'id': self.track_flight_id,
                    'guest_name': self.track_guest_name or self.track_flight_id,
                    'route': "UNK > UNK",
                    'origin_city': "UNKNOWN",
                    'dest_city': "UNKNOWN",
                    'alt': 0, 'dist': 0, 'eta_str': "PENDING", 'speed': 0, 'progress': 0,
                    'status': "pending", 'is_shown': True
                }

        except Exception as e:
            self.log("ERROR", f"Visitor Tracking: {e}")

    def fetch_fr24_flight(self, flight_id):
        """Fetch flight data using FlightRadarAPI SDK"""
        try:
            if not self.fr_api: 
                self.log("ERROR", "FlightRadar24 API not initialized")
                return None

            def _parse_ts(value):
                if isinstance(value, dict):
                    for key in ['utc', 'unix', 'time', 'timestamp']:
                        if key in value:
                            value = value.get(key)
                            break
                try:
                    return int(value)
                except Exception:
                    return None

            def _get_time(time_info, bucket, point):
                block = time_info.get(bucket) or {}
                raw = block.get(point)
                return _parse_ts(raw)

            def _extract_delay_minutes(details):
                if not details:
                    return None, "", None
                time_info = details.get('time') or {}
                sched_arr = _get_time(time_info, 'scheduled', 'arrival')
                est_arr = (_get_time(time_info, 'estimated', 'arrival') or
                           _get_time(time_info, 'real', 'arrival') or
                           _get_time(time_info, 'actual', 'arrival'))
                sched_dep = _get_time(time_info, 'scheduled', 'departure')
                est_dep = (_get_time(time_info, 'estimated', 'departure') or
                           _get_time(time_info, 'real', 'departure') or
                           _get_time(time_info, 'actual', 'departure'))
                delay_min = None
                if sched_arr and est_arr:
                    delay_min = max(0, int((est_arr - sched_arr) / 60))
                elif sched_dep and est_dep:
                    delay_min = max(0, int((est_dep - sched_dep) / 60))

                status_block = details.get('status') or {}
                status_text = str(
                    status_block.get('text') or
                    status_block.get('description') or
                    status_block.get('status') or
                    details.get('statusText') or ''
                )
                return delay_min, status_text, est_arr
            
            # Parse the flight code
            icao, iata, flight_num = self.parse_flight_code(flight_id)
            
            self.log("INFO", f"Searching for flight {flight_id} (ICAO: {icao}, IATA: {iata}, #: {flight_num})")
            
            # Try airline-filtered search first
            try:
                flights = self.fr_api.get_flights(airline=icao)
                if flights:
                    self.log("INFO", f"Got {len(flights)} {icao} flights from API")
            except Exception as e:
                self.log("DEBUG", f"Airline filter failed, trying all flights: {e}")
                flights = self.fr_api.get_flights()
                if flights:
                    self.log("INFO", f"Got {len(flights)} total flights from API")
            
            if not flights:
                self.log("WARNING", f"No flights returned by API - service may be down")
                return None
            
            # Build search variants
            search_strings = [
                f"{icao}{flight_num}",      # UAL72, JBU1004
                f"{iata}{flight_num}",      # UA72, B61004
            ]
            
            # Add zero-padded variants for short flight numbers
            if len(flight_num) < 4:
                search_strings.extend([
                    f"{icao}{flight_num.zfill(4)}",  # UAL0072
                    f"{iata}{flight_num.zfill(4)}",  # UA0072
                ])
            
            # Search for the flight
            target_flight = None
            
            for flight in flights:
                f_num = (flight.number or "").upper().replace(" ", "")
                f_call = (flight.callsign or "").upper().replace(" ", "")
                
                for search_str in search_strings:
                    if search_str in [f_num, f_call]:
                        target_flight = flight
                        self.log("INFO", f"✓ Found {flight_id}: {f_num} ({f_call})")
                        break
                
                if target_flight:
                    break
            
            if not target_flight:
                self.log("WARNING", f"Flight {flight_id} not found - may not be airborne right now")
                self.log("DEBUG", f"Searched for: {search_strings}")
                return None
            
            # Get detailed information if available
            details = None
            try:
                details = self.fr_api.get_flight_details(target_flight)
                target_flight.set_flight_details(details)
            except Exception as e:
                self.log("DEBUG", f"Could not get detailed info: {e}")

            delay_min, status_text, est_arr = _extract_delay_minutes(details)

            # Aircraft type: prefer detailed model from FR24, fall back to ICAO type code normalization
            fr24_model = getattr(target_flight, 'aircraft_model', None) or ''
            icao_type = getattr(target_flight, 'aircraft_code', None) or ''
            aircraft_type = normalize_aircraft_type(icao_type, fr24_model if fr24_model else None)
            if aircraft_type:
                self.log("INFO", f"Aircraft type for {flight_id}: {aircraft_type} (code: {icao_type})")

            return {
                'flight_id': flight_id,
                'origin': target_flight.origin_airport_iata or 'UNK',
                'destination': target_flight.destination_airport_iata or 'UNK',
                'latitude': target_flight.latitude,
                'longitude': target_flight.longitude,
                'altitude': target_flight.altitude or 0,
                'speed_kts': target_flight.ground_speed or 0,
                'is_live': (target_flight.altitude or 0) > 0,
                'delay_min': delay_min,
                'status_text': status_text,
                'est_arr': est_arr,
                'aircraft_type': aircraft_type,
                'aircraft_code': icao_type
            }
            
        except ValueError as e:
            self.log("ERROR", f"Invalid flight code '{flight_id}': {e}")
            return None
        except Exception as e:
            self.log("ERROR", f"Error fetching flight {flight_id}: {e}")
            return None
    
    def get_visitor_object(self):
        with self.lock:
            return self.visitor_flight.copy() if self.visitor_flight else None
    
    def get_airport_objects(self):
        with self.lock:
            result = []
            self.log("DEBUG", f"get_airport_objects called - arrivals: {len(self.airport_arrivals)}, departures: {len(self.airport_departures)}")
            result.append({
                'type': 'flight_weather', 'sport': 'flight', 'id': 'airport_wx',
                'home_abbr': self.airport_name or self.airport_code_icao,
                'away_abbr': self.airport_weather['temp'], 'status': self.airport_weather['cond'], 'is_shown': True
            })
            for i, arr in enumerate(self.airport_arrivals[:2]):
                # Use specific status if available, else fallback
                st = arr.get('status_label', 'ARRIVING')
                result.append({'type': 'flight_arrival', 'sport': 'flight', 'id': f"arr_{i}", 'status': st, 'home_abbr': arr['from'], 'away_abbr': arr['id'], 'is_shown': True})
            for i, dep in enumerate(self.airport_departures[:2]):
                st = dep.get('status_label', 'DEPARTING')
                result.append({'type': 'flight_departure', 'sport': 'flight', 'id': f"dep_{i}", 'status': st, 'home_abbr': dep['to'], 'away_abbr': dep['id'], 'is_shown': True})
            return result

class SportsFetcher:
    def __init__(self, initial_city, initial_lat, initial_lon):
        self.weather = WeatherFetcher(initial_lat=initial_lat, initial_lon=initial_lon, city=initial_city)
        self.stocks = StockFetcher()
        self.possession_cache = {} 
        self.base_url = 'http://site.api.espn.com/apis/site/v2/sports/'
        
        # CHANGE 1: Reduce Pool Size to 15 (Save RAM)
        self.session = build_pooled_session(pool_size=15)
        
        # CHANGE 2: Use Configured Thread Count (10)
        self.executor = concurrent.futures.ThreadPoolExecutor(max_workers=WORKER_THREAD_COUNT)
        
        # CHANGE 3: Add New Caches for Smart Sleep
        self.history_buffer = [] 
        self.final_game_cache = {}      # Stores finished games so we don't re-fetch
        self.league_next_update = {}    # Stores "Wake Up" time for sleeping leagues
        self.league_last_data = {}      # Stores last data for sleeping leagues
        
        self.consecutive_empty_fetches = 0
        self._mlb_player_cache = {}   # playerId (int/str) → last name string
        self._mlb_summary_cache = {}  # gameId -> {'ts': float, 'data': dict}
        self._mlb_gamepk_cache = {}   # espn_gid -> mlb gamePk (or None on miss)
        self._mlb_challenge_cache = {}  # gamePk -> {'ts': float, 'home': int|None, 'away': int|None}
        # abbr-keyed index rebuilt in fetch_all_teams — O(1) team lookups
        self._teams_abbr_index: dict = {}  # league -> {abbr -> team_entry}
        # Per-mode content buffers: mode_name → list[game_obj]
        # Sports/live/my_teams share the same raw buffer; filtering happens in /data.
        self._mode_buffers: dict = {}
        self._mode_buffer_lock = threading.Lock()
        
        self.leagues = { 
            item['id']: item['fetch'] 
            for item in LEAGUE_OPTIONS 
            if item['type'] == 'sport' and 'fetch' in item 
        }

    def _calculate_next_update(self, games):
        """Returns TIMESTAMP when we should next fetch this league"""
        if not games: return 0 
        now = time.time()
        earliest_start = None
        
        for g in games:
            # If ACTIVE (In/Half/Crit) -> Fetch Immediately (0)
            if g['state'] in ['in', 'half', 'crit']: return 0
            
            # If SCHEDULED -> Track earliest start time
            if g['state'] == 'pre':
                try:
                    ts = parse_iso(g['startTimeUTC']).timestamp()
                    if earliest_start is None or ts < earliest_start: earliest_start = ts
                except: pass
        
        # If games are in future, sleep until 60s before start
        if earliest_start:
            wake_time = earliest_start - 60 
            if wake_time > now: return wake_time
            return 0
            
        # If all FINAL -> Sleep 60s
        return now + 60

    def get_corrected_logo(self, league_key, abbr, default_logo):
        return LOGO_OVERRIDES.get(f"{league_key.upper()}:{abbr}", default_logo)

    def _extract_color_from_logo(self, logo_url):
        """Download the team logo and return the dominant non-white, non-transparent color as a hex string, or None on failure."""
        if not logo_url or not PIL_AVAILABLE:
            return None
        try:
            r = self.session.get(logo_url, timeout=5)
            r.raise_for_status()
            img = _PIL_Image.open(io.BytesIO(r.content)).convert('RGBA')
            img = img.resize((64, 64))
            freq = {}
            for px in img.getdata():
                r_val, g_val, b_val, a_val = px
                if a_val < 128:
                    continue
                brightness = (r_val + g_val + b_val) / 3
                if brightness > 240:
                    continue
                # Quantize to reduce noise
                key = (r_val // 32 * 32, g_val // 32 * 32, b_val // 32 * 32)
                freq[key] = freq.get(key, 0) + 1
            if not freq:
                return None
            best = max(freq, key=freq.get)
            return '{:02X}{:02X}{:02X}'.format(*best)
        except Exception:
            return None

    def lookup_team_info_from_cache(self, league, abbr, name=None, logo=None):
        search_abbr = ABBR_MAPPING.get(abbr, abbr)

        if 'soccer' in league:
            name_check = name.lower() if name else ""
            abbr_check = search_abbr.lower()
            for k, v in SOCCER_COLOR_FALLBACK.items():
                if k in name_check or k == abbr_check:
                    return {'color': v, 'alt_color': '444444'}

        try:
            # O(1) abbr lookup via pre-built index
            league_idx = self._teams_abbr_index.get(league, {})
            t = league_idx.get(search_abbr)
            if t:
                return {'color': t.get('color', '000000'), 'alt_color': t.get('alt_color', '444444')}

            # Fallback: name-based scan (rare — only for teams without standard abbr)
            if name:
                name_lower = name.lower()
                with data_lock:
                    teams = state['all_teams_data'].get(league, [])
                for t in teams:
                    t_name = t.get('name', '').lower()
                    t_short = t.get('shortName', '').lower()
                    if (name_lower in t_name) or (t_name in name_lower) or \
                       (name_lower in t_short) or (t_short in name_lower):
                        return {'color': t.get('color', '000000'), 'alt_color': t.get('alt_color', '444444')}
        except: pass
        logo_color = self._extract_color_from_logo(logo)
        return {'color': logo_color or '000000', 'alt_color': '444444'}

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

    def _fetch_simple_league(self, league_key, catalog, seen_ids):
        config = self.leagues[league_key]
        if 'team_params' not in config: return
        try:
            r = self.session.get(f"{self.base_url}{config['path']}/teams", params=config['team_params'], headers=HEADERS, timeout=TIMEOUTS['slow'])
            data = r.json()
            if 'sports' in data:
                for sport in data['sports']:
                    for league in sport['leagues']:
                        for item in league.get('teams', []):
                            abbr = item['team'].get('abbreviation', 'unk')
                            scoped_id = f"{league_key}:{abbr}"
                            if scoped_id in seen_ids[league_key]:
                                continue
                            seen_ids[league_key].add(scoped_id)

                            clr = item['team'].get('color', '000000')
                            alt = item['team'].get('alternateColor', '444444')
                            logo = item['team'].get('logos', [{}])[0].get('href', '')
                            logo = self.get_corrected_logo(league_key, abbr, logo)
                            name = item['team'].get('displayName', '')
                            short_name = item['team'].get('shortDisplayName', '')

                            catalog[league_key].append({
                                'abbr': abbr,
                                'id': scoped_id,
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
            # Per-league seen-ID sets for O(1) deduplication (replaces any() linear scan)
            seen_ids: dict = {k: set() for k in self.leagues.keys()}

            # NCAA college teams — O(1) dedup via seen_ids sets
            ncf_seen = {'ncf_fbs': set(), 'ncf_fcs': set()}
            url = f"{self.base_url}football/college-football/teams"
            r = self.session.get(url, params={'limit': 1000, 'groups': '80,81'}, headers=HEADERS, timeout=TIMEOUTS['slow'])
            data = r.json()
            if 'sports' in data:
                for sport in data['sports']:
                    for league in sport['leagues']:
                        for item in league.get('teams', []):
                            t_abbr = item['team'].get('abbreviation', 'unk')
                            t_clr = item['team'].get('color', '000000')
                            t_alt = item['team'].get('alternateColor', '444444')
                            logos = item['team'].get('logos', [])
                            t_logo = logos[0].get('href', '') if logos else ''

                            if t_abbr in FBS_TEAMS:
                                scoped_id = f"ncf_fbs:{t_abbr}"
                                if scoped_id not in ncf_seen['ncf_fbs']:
                                    ncf_seen['ncf_fbs'].add(scoped_id)
                                    t_logo = self.get_corrected_logo('ncf_fbs', t_abbr, t_logo)
                                    teams_catalog['ncf_fbs'].append({'abbr': t_abbr, 'id': scoped_id, 'logo': t_logo, 'color': t_clr, 'alt_color': t_alt})
                            elif t_abbr in FCS_TEAMS:
                                scoped_id = f"ncf_fcs:{t_abbr}"
                                if scoped_id not in ncf_seen['ncf_fcs']:
                                    ncf_seen['ncf_fcs'].add(scoped_id)
                                    t_logo = self.get_corrected_logo('ncf_fcs', t_abbr, t_logo)
                                    teams_catalog['ncf_fcs'].append({'abbr': t_abbr, 'id': scoped_id, 'logo': t_logo, 'color': t_clr, 'alt_color': t_alt})

            futures = []
            leagues_to_fetch = [
                'nfl', 'mlb', 'nhl', 'nba', 'march_madness',
                'soccer_epl', 'soccer_fa_cup', 'soccer_champ', 'soccer_l1', 'soccer_l2', 'soccer_wc', 'soccer_champions_league', 'soccer_europa_league', 'soccer_mls'
            ]
            for lk in leagues_to_fetch:
                if lk in self.leagues:
                    futures.append(self.executor.submit(self._fetch_simple_league, lk, teams_catalog, seen_ids))
            concurrent.futures.wait(futures)

            # Build abbr-keyed index for O(1) lookup in lookup_team_info_from_cache
            new_index = {
                league: {entry['abbr']: entry for entry in entries}
                for league, entries in teams_catalog.items()
            }

            with data_lock:
                state['all_teams_data'] = teams_catalog
            self._teams_abbr_index = new_index
        except Exception as e: print(f"Global Team Fetch Error: {e}")
            
    def check_shootout(self, game, summary=None):
        if summary:
            if summary.get("hasShootout"): return True
            if summary.get("shootoutDetails"): return True
            
            so_section = (
                summary.get("shootout") or summary.get("Shootout") or 
                summary.get("shootOut") or summary.get("SO")
            )
            if so_section: return True
            
            summary_status = str(
                summary.get("gameStatusString") or summary.get("gameStatus") or 
                summary.get("status") or ""
            ).lower()
            if "so" in summary_status or "shootout" in summary_status or "s/o" in summary_status:
                return True
        
        period = str(game.get("Period", "") or game.get("period", ""))
        period_name = str(game.get("PeriodNameShort", "") or game.get("periodNameShort", "")).upper()
        
        if period == "5": return True
        if period_name == "SO" or "SHOOTOUT" in period_name: return True
        
        status = str(
            game.get("GameStatusString") or game.get("game_status") or 
            game.get("GameStatusStringLong") or ""
        ).lower()
        
        if "so" in status or "shootout" in status or "s/o" in status:
            return True
            
        return False

    def fetch_shootout_details(self, game_id, away_id, home_id):
        try:
            url = f"https://api-web.nhle.com/v1/gamecenter/{game_id}/play-by-play"
            r = self.session.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=TIMEOUTS['quick'])
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
            r = self.session.get(f"https://api-web.nhle.com/v1/gamecenter/{gid}/landing", headers=HEADERS, timeout=TIMEOUTS['quick'])
            if r.status_code == 200: return r.json()
        except: pass
        return None

    def _fetch_nhl_native(self, conf, window_start_utc, window_end_utc, visible_start_utc, visible_end_utc):
        games_found = []
        is_nhl = conf['active_sports'].get('nhl', False)
        if not is_nhl: return []
        
        processed_ids = set()
        try:
            r = self.session.get("https://api-web.nhle.com/v1/schedule/now", headers=HEADERS, timeout=TIMEOUTS['stock'])
            if r.status_code != 200: return []

            landing_futures = {}
            _local_tz = timezone(timedelta(hours=conf.get('utc_offset', -5)))

            for d in r.json().get('gameWeek', []):
                for g in d.get('games', []):
                    try:
                        # Filter out non-NHL events (e.g. 9 = Olympics, 6 = World Cup)
                        # Keep 1 (Preseason), 2 (Regular Season), 3 (Playoffs), 4 (All-Star)
                        if int(g.get('gameType', 2)) not in [1, 2, 3, 4]:
                            continue

                        g_utc = g.get('startTimeUTC')
                        if not g_utc: continue
                        g_dt = parse_iso(g_utc)
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
                        # Filter out non-NHL events here as well
                        if int(g.get('gameType', 2)) not in [1, 2, 3, 4]:
                            continue

                        g_utc = g.get('startTimeUTC')
                        if not g_utc: continue
                        g_dt = parse_iso(g_utc)

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

                    # === FIX: NORMALIZE ABBREVIATIONS FOR MY TEAMS COMPATIBILITY ===
                    raw_h = g['homeTeam']['abbrev']; raw_a = g['awayTeam']['abbrev']
                    h_ab = ABBR_MAPPING.get(raw_h, raw_h) # Translates LAK -> LA
                    a_ab = ABBR_MAPPING.get(raw_a, raw_a) # Translates TBL -> TB
                    # === FIX END ===

                    h_sc = str(g['homeTeam'].get('score', 0)); a_sc = str(g['awayTeam'].get('score', 0))
                    
                    h_lg = self.get_corrected_logo('nhl', h_ab, f"https://a.espncdn.com/i/teamlogos/nhl/500/{h_ab.lower()}.png")
                    a_lg = self.get_corrected_logo('nhl', a_ab, f"https://a.espncdn.com/i/teamlogos/nhl/500/{a_ab.lower()}.png")
                    h_info = self.lookup_team_info_from_cache('nhl', h_ab, logo=h_lg)
                    a_info = self.lookup_team_info_from_cache('nhl', a_ab, logo=a_lg)
                    
                    if st in ['SUSP', 'SUSPENDED', 'PPD', 'POSTPONED']:
                        map_st = 'post'

                    disp = "Scheduled"; pp = False; poss = ""; en = False; shootout_data = None 
                    dur = self.calculate_game_timing('nhl', g_utc, 1, st)
                    
                    g_local = g_dt.astimezone(_local_tz)

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
                        'sport': 'nhl', 'id': str(gid), 'status': disp, 'state': map_st, 'is_shown': True,
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
            resp = self.session.get(url, headers=HEADERS, timeout=TIMEOUTS['slow'])
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

    def _format_live_clock(self, status: dict, fallback_text: str = "") -> str | None:
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
        _local_tz = timezone(timedelta(hours=conf.get('utc_offset', -5)))
        for section in sections:
            candidate_matches = section.get("matches") if isinstance(section, dict) else None
            if candidate_matches is None: candidate_matches = [section]
            
            for match in candidate_matches:
                if not isinstance(match, dict): continue
                
                status = match.get("status") or {}
                kickoff = status.get("utcTime") or match.get("time")
                if not kickoff: continue
                
                try:
                    match_dt = parse_iso(kickoff)
                    if not (start_window <= match_dt <= end_window): continue
                except: continue

                mid = match.get("id")
                h_name = match.get("home", {}).get("name") or "Home"
                a_name = match.get("away", {}).get("name") or "Away"
                
                h_ab = SOCCER_ABBR_OVERRIDES.get(h_name, h_name[:3].upper())
                a_ab = SOCCER_ABBR_OVERRIDES.get(a_name, a_name[:3].upper())
                
                finished = bool(status.get("finished"))
                started = bool(status.get("started"))
                reason = (status.get("reason") or {}).get("short") or ""
                
                home_score = (match.get("home") or {}).get("score")
                away_score = (match.get("away") or {}).get("score")

                status_score = status.get("score") or status.get("current") or {}
                if isinstance(status_score, dict):
                    if home_score is None: home_score = status_score.get("home")
                    if away_score is None: away_score = status_score.get("away")
                    
                    for key in ("ft", "fulltime"):
                        ft_score = status_score.get(key)
                        if isinstance(ft_score, (list, tuple)) and len(ft_score) >= 2:
                            if home_score is None: home_score = ft_score[0]
                            if away_score is None: away_score = ft_score[1]
                elif isinstance(status_score, (list, tuple)) and len(status_score) >= 2:
                    if home_score is None: home_score = status_score[0]
                    if away_score is None: away_score = status_score[1]

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

                gst = 'pre'
                
                try:
                    k_dt = parse_iso(kickoff)
                    local_k = k_dt.astimezone(_local_tz)
                    disp = local_k.strftime("%I:%M %p").lstrip('0')
                except:
                    disp = kickoff.split("T")[1][:5]

                if started and not finished:
                    gst = 'in'
                    clock_str = self._format_live_clock(status, match.get("status_text"))
                    if clock_str:
                        disp = clock_str
                    else:
                        disp = "In Progress"
                    
                    current_minute = 0
                    try:
                        current_minute = int((status.get("liveTime") or {}).get("minute", 0))
                    except: pass

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

                if match_dt < visible_start_utc or match_dt >= visible_end_utc:
                      if gst != 'in': continue

                is_shootout = False
                if "Pen" in reason or (gst == 'in' and "Pen" in str(status)) or disp == "FIN":
                    is_shootout = True
                    if gst == 'in': disp = "Pens"
                
                shootout_data = None
                if is_shootout:
                    shootout_data = self._fetch_fotmob_details(mid, match.get("home", {}).get("id"), match.get("away", {}).get("id"))

                is_shown = True
                if "Postponed" in disp or "PPD" in reason or status.get("cancelled"):
                    is_shown = False

                h_id = match.get("home", {}).get("id")
                a_id = match.get("away", {}).get("id")
                h_fotmob_logo = f"https://images.fotmob.com/image_resources/logo/teamlogo/{h_id}.png" if h_id else None
                a_fotmob_logo = f"https://images.fotmob.com/image_resources/logo/teamlogo/{a_id}.png" if a_id else None

                h_info = self.lookup_team_info_from_cache(internal_id, h_ab, h_name, logo=h_fotmob_logo)
                a_info = self.lookup_team_info_from_cache(internal_id, a_ab, a_name, logo=a_fotmob_logo)
                
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
            
            for l_type in ("cup", "league", None):
                params = {"id": league_id, "tab": "matches", "timeZone": "UTC", "type": l_type, "_": int(time.time())}
                
                try:
                    resp = self.session.get(url, params=params, headers=HEADERS, timeout=TIMEOUTS['slow'])
                    resp.raise_for_status()
                    payload = resp.json()
                    
                    sections = payload.get("matches", {}).get("allMatches", [])
                    if not sections:
                        sections = payload.get("fixtures", {}).get("allMatches", [])
                    
                    last_sections = sections
                    matches = self._extract_matches(sections, internal_id, conf, start_window, end_window, visible_start_utc, visible_end_utc)
                    if matches: return matches
                except: continue
            
            if last_sections:
                 return self._extract_matches(last_sections, internal_id, conf, start_window, end_window, visible_start_utc, visible_end_utc)
            return []
        except Exception as e:
            print(f"FotMob League {league_id} error: {e}")
            return []

    def fetch_single_league(self, league_key, config, conf, window_start_utc, window_end_utc, utc_offset, visible_start_utc, visible_end_utc):
        local_games = []

        if config.get('type') == 'leaderboard':
            return local_games

        try:
            curr_p = config.get('scoreboard_params', {}).copy()
            
            # CHANGE B: DATE OPTIMIZATION
            now_local = dt.now(timezone.utc).astimezone(timezone(timedelta(hours=utc_offset)))
            
            custom = TestMode.get_custom_date()
            if custom:
                curr_p['dates'] = custom
            else:
                # If before 3AM, fetch yesterday's games so finals persist
                if now_local.hour < 3:
                    fetch_date = now_local - timedelta(days=1)
                else:
                    fetch_date = now_local
                curr_p['dates'] = fetch_date.strftime("%Y%m%d")
            
            # --- FIX: CACHE BUSTER ---
            # Forces ESPN's CDN to return live data instead of a stale cached file
            curr_p['_'] = int(time.time() * 1000)
            
            r = self.session.get(f"{self.base_url}{config['path']}/scoreboard", params=curr_p, headers=HEADERS, timeout=TIMEOUTS['default'])
            data = r.json()
            
            events = data.get('events', [])
            if not events:
                leagues = data.get('leagues', [])
                if leagues and len(leagues) > 0:
                    events = leagues[0].get('events', [])
            
            for e in events:
                gid = str(e['id'])

                # CHANGE A: CACHE CHECK (with date guard)
                if gid in self.final_game_cache:
                    cached = self.final_game_cache[gid]
                    try:
                        cached_dt = parse_iso(cached.get('startTimeUTC', ''))
                        if visible_start_utc <= cached_dt <= visible_end_utc:
                            local_games.append(cached)
                            continue
                        else:
                            del self.final_game_cache[gid]
                    except:
                        del self.final_game_cache[gid]
                
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

                # Seed Extraction Logic for March Madness
                h_seed = h.get('curatedRank', {}).get('current', '')
                a_seed = a.get('curatedRank', {}).get('current', '')
                if h_seed == 99: h_seed = ""
                if a_seed == 99: a_seed = ""

                h_lg = self.get_corrected_logo(league_key, h_ab, h['team'].get('logo',''))
                a_lg = self.get_corrected_logo(league_key, a_ab, a['team'].get('logo',''))
                
                h_clr = h['team'].get('color')
                a_clr = a['team'].get('color')
                h_alt = h['team'].get('alternateColor')
                a_alt = a['team'].get('alternateColor')

                # Force fallback to our hardcoded colors for missing ESPN data
                if not h_clr or h_clr == '000000' or not a_clr or a_clr == '000000':
                    h_info = self.lookup_team_info_from_cache(league_key, h_ab, logo=h_lg)
                    a_info = self.lookup_team_info_from_cache(league_key, a_ab, logo=a_lg)
                    h_clr = h_clr if h_clr and h_clr != '000000' else h_info.get('color', '000000')
                    a_clr = a_clr if a_clr and a_clr != '000000' else a_info.get('color', '000000')
                    h_alt = h_alt if h_alt else h_info.get('alt_color', 'ffffff')
                    a_alt = a_alt if a_alt else a_info.get('alt_color', 'ffffff')
                else:
                    h_clr = h_clr or '000000'
                    a_clr = a_clr or '000000'
                    h_alt = h_alt or 'ffffff'
                    a_alt = a_alt or 'ffffff'

                h_score = h.get('score','0')
                a_score = a.get('score','0')
                if 'soccer' in league_key: 
                    h_score = re.sub(r'\s*\(.*?\)', '', str(h_score))
                    a_score = re.sub(r'\s*\(.*?\)', '', str(a_score))

                s_disp = tp.get('shortDetail', 'TBD')
                p = st.get('period', 1)
                duration_est = self.calculate_game_timing(league_key, e['date'], p, s_disp)

                # --- FIX: ROBUST STATE INFERENCE ---
                # ESPN sometimes fails to switch 'state' to 'in', leaving it stuck as 'pre'.
                if gst == 'pre' and any(x in s_disp for x in ['1st', '2nd', '3rd', 'OT', 'Half', 'Qtr', 'Inning']):
                    if "FINAL" not in s_disp.upper():
                        gst = 'in'

                is_suspended = False
                susp_keywords = ["Suspended", "Postponed", "Canceled", "Delayed", "PPD"]
                for kw in susp_keywords:
                    if kw in s_disp:
                        is_suspended = True
                        break
                
                if not is_suspended:
                    if gst == 'pre':
                        try: s_disp = game_dt.astimezone(timezone(timedelta(hours=utc_offset))).strftime("%I:%M %p").lstrip('0')
                        except: pass
                    elif gst == 'in' or gst == 'half':
                        clk = st.get('displayClock', '0:00').replace("'", "")
                        
                        # --- FIX: EXTRACT CLOCK FROM DETAIL IF ESPN LEAVES IT BLANK ---
                        if (not clk or clk == '0:00') and ':' in s_disp:
                            m = re.search(r'(\d{1,2}:\d{2})', s_disp)
                            if m: clk = m.group(1)

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
                                if p > 4:
                                    s_disp = f"OT{p-4 if p-4>1 else ''} {clk}"
                                elif league_key == 'march_madness' and p <= 2:
                                    s_disp = f"H{p} {clk}"
                                else:
                                    s_disp = f"Q{p} {clk}"
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
                
                poss_raw = sit.get('possession')
                if poss_raw: self.possession_cache[e['id']] = poss_raw
                elif gst in ('in', 'half'):
                    _cached_poss = self.possession_cache.get(e['id'])
                    if _cached_poss is not None: poss_raw = _cached_poss
                
                if gst == 'pre' or gst == 'post' or gst == 'final' or s_disp == 'Halftime' or is_suspended:
                    poss_raw = None
                    self.possession_cache.pop(e['id'], None)

                poss_abbr = ""
                if str(poss_raw) == str(h['team'].get('id')): poss_abbr = h_ab
                elif str(poss_raw) == str(a['team'].get('id')): poss_abbr = a_ab
                
                down_text = sit.get('downDistanceText') or sit.get('shortDownDistanceText') or ''
                if s_disp == "Halftime": down_text = ''

                game_obj = {
                    'type': 'scoreboard', 'sport': league_key, 'id': gid, 'status': s_disp, 'state': gst, 'is_shown': True,
                    'home_abbr': h_ab, 'home_score': h_score, 'home_logo': h_lg,
                    'away_abbr': a_ab, 'away_score': a_score, 'away_logo': a_lg,
                    'home_color': f"#{h_clr}", 'home_alt_color': f"#{h_alt}",
                    'away_color': f"#{a_clr}", 'away_alt_color': f"#{a_alt}",
                    'startTimeUTC': e['date'],
                    'estimated_duration': duration_est,
                    
                    # MARCH MADNESS SPECIFIC FIELDS
                    'home_seed': str(h_seed),
                    'away_seed': str(a_seed),
                    
                    'situation': {
                        'possession': poss_abbr,
                        'isRedZone': sit.get('isRedZone', False),
                        'downDist': down_text,
                        'yardLine': sit.get('yardLine'),
                        'yardsToGo': sit.get('distance'),
                        'possessionTeam': sit.get('possessionText', ''),
                        'shootout': shootout_data,
                        'powerPlay': False,
                        'emptyNet': False
                    }
                }
                if league_key == 'mlb':
                    _bat_obj = sit.get('batter') or {}
                    _pit_obj = sit.get('pitcher') or {}
                    _bat_pid = self._mlb_player_id_from_obj(_bat_obj)
                    _pit_pid = self._mlb_player_id_from_obj(_pit_obj)
                    _batter_name = self._mlb_resolve_person_name(
                        _bat_obj,
                        _bat_pid,
                        sit.get('batterName') or sit.get('batter_name') or ''
                    )
                    _pitcher_name = self._mlb_resolve_person_name(
                        _pit_obj,
                        _pit_pid,
                        sit.get('pitcherName') or sit.get('pitcher_name') or ''
                    )
                    _mlb_stats = self._mlb_extract_situation_stats(sit, _bat_obj, _pit_obj)
                    _batter_avg = _mlb_stats.get('batter_avg', '')
                    _batter_h = _mlb_stats.get('batter_h', '')
                    _batter_ab = _mlb_stats.get('batter_ab', '')
                    _pitcher_pitches = _mlb_stats.get('pitcher_pitches', 0)
                    _last_pitch_speed = _mlb_stats.get('last_pitch_speed', 0)
                    _last_pitch_type = _mlb_stats.get('last_pitch_type', '')
                    _last_pitch_type_abbr = _mlb_stats.get('last_pitch_type_abbr', _last_pitch_type)
                    _last_pitch_type_full = _mlb_stats.get('last_pitch_type_full', '')
                    game_obj['situation'].update({
                        'balls': sit.get('balls', 0), 'strikes': sit.get('strikes', 0), 'outs': sit.get('outs', 0),
                        'onFirst': bool(sit.get('onFirst', False)), 'onSecond': bool(sit.get('onSecond', False)), 'onThird': bool(sit.get('onThird', False)),
                        'batter_name': _batter_name, 'batter_avg': _batter_avg,
                        'batter_h': _batter_h, 'batter_ab': _batter_ab,
                        'pitcher_name': _pitcher_name, 'pitcher_pitches': _pitcher_pitches,
                        'last_pitch_speed': _last_pitch_speed,
                        'last_pitch_type': _last_pitch_type,
                        'last_pitch_type_abbr': _last_pitch_type_abbr,
                        'last_pitch_type_full': _last_pitch_type_full,
                    })

                    # ESPN scoreboard often omits MLB batter/pitcher stat fields.
                    # Enrich from per-game summary for live/half games when these are blank.
                    if gst in ('in', 'half'):
                        need_enrich = (
                            not game_obj['situation'].get('batter_avg')
                            or not game_obj['situation'].get('batter_h')
                            or not game_obj['situation'].get('batter_ab')
                            or int(game_obj['situation'].get('pitcher_pitches', 0) or 0) == 0
                            or int(game_obj['situation'].get('last_pitch_speed', 0) or 0) == 0
                            or not game_obj['situation'].get('last_pitch_type')
                        )
                        if need_enrich:
                            _enriched = self._mlb_enrich_live_from_summary(gid, game_obj['situation'])
                            if _enriched:
                                game_obj['situation'].update(_enriched)

                        # Fetch manager challenge counts from MLB Stats API (cached 60s).
                        _gamepk = self._mlb_get_gamepk(
                            gid,
                            h_ab,
                            a_ab,
                            e['date'],
                            h['team'].get('id'),
                            a['team'].get('id'),
                        )
                        _h_rem, _h_used, _a_rem, _a_used = self._mlb_get_challenges(_gamepk)
                        game_obj['home_challenges'] = _h_rem
                        game_obj['home_challenges_used'] = _h_used
                        game_obj['away_challenges'] = _a_rem
                        game_obj['away_challenges_used'] = _a_used
                
                if is_suspended: game_obj['is_shown'] = False
                
                local_games.append(game_obj)
                
                # CHANGE C: SAVE FINAL GAMES TO CACHE
                if gst == 'post' and "FINAL" in s_disp:
                    self.final_game_cache[gid] = game_obj

        except Exception as e: print(f"Error fetching {league_key}: {e}")
        return local_games

    def _mlb_abbr_candidates(self, abbr):
        """Return MLB abbreviation aliases so ESPN and Stats API values can match."""
        val = str(abbr or '').strip().upper()
        if not val:
            return set()
        aliases = {
            'ARI': {'ARI', 'AZ'},
            'AZ': {'AZ', 'ARI'},
            'WSH': {'WSH', 'WAS'},
            'WAS': {'WAS', 'WSH'},
        }
        return aliases.get(val, {val})

    def _mlb_get_gamepk(self, espn_gid, home_abbr, away_abbr, date_utc_str, home_team_id=None, away_team_id=None):
        """Resolve MLB Stats API gamePk for an ESPN game, cached per espn_gid."""
        gid = str(espn_gid)
        if gid in self._mlb_gamepk_cache:
            return self._mlb_gamepk_cache[gid]

        home_abbr_set = self._mlb_abbr_candidates(home_abbr)
        away_abbr_set = self._mlb_abbr_candidates(away_abbr)
        home_id = str(home_team_id) if home_team_id is not None else ''
        away_id = str(away_team_id) if away_team_id is not None else ''
        target_dt = None
        try:
            target_dt = parse_iso(str(date_utc_str or ''))
        except Exception:
            target_dt = None

        # Build candidate dates: the UTC date and the day before (US evening games)
        dates_to_try = []
        try:
            date_part = str(date_utc_str or '')[:10]
            if date_part:
                from datetime import date as _date, timedelta as _td
                d = _date.fromisoformat(date_part)
                dates_to_try = [str(d), str(d - _td(days=1)), str(d + _td(days=1))]
        except Exception:
            pass

        candidates = []
        candidate_index = 0
        for date_str in dates_to_try:
            try:
                r = self.session.get(
                    'https://statsapi.mlb.com/api/v1/schedule',
                    params={'sportId': '1', 'date': date_str, 'hydrate': 'team'},
                    timeout=5,
                )
                if r.status_code != 200:
                    continue
                for date_obj in r.json().get('dates', []):
                    for game in date_obj.get('games', []):
                        pk = game.get('gamePk')
                        t = game.get('teams', {})
                        h_team = t.get('home', {}).get('team', {})
                        a_team = t.get('away', {}).get('team', {})

                        h = (h_team.get('abbreviation') or '').upper()
                        a = (a_team.get('abbreviation') or '').upper()
                        h_id = str(h_team.get('id') or '')
                        a_id = str(a_team.get('id') or '')

                        id_match = bool(home_id and away_id and h_id == home_id and a_id == away_id)
                        abbr_match = bool(h in home_abbr_set and a in away_abbr_set)

                        if id_match or abbr_match:
                            game_dt = None
                            try:
                                game_dt = parse_iso(str(game.get('gameDate') or ''))
                            except Exception:
                                game_dt = None
                            if target_dt and game_dt:
                                score = abs((game_dt - target_dt).total_seconds())
                            else:
                                score = float(candidate_index)
                            candidates.append((score, candidate_index, pk))
                            candidate_index += 1
            except Exception:
                pass

        if candidates:
            best_pk = sorted(candidates, key=lambda x: (x[0], x[1]))[0][2]
            self._mlb_gamepk_cache[gid] = best_pk
            return best_pk
        return None  # Don't cache None — retry on next poll until found

    def _mlb_get_challenges(self, gamepk, max_age=60):
        """Return (home_rem, home_used, away_rem, away_used) from MLB Stats API, cached 60s."""
        def _safe_int(v):
            try:
                return int(v)
            except (TypeError, ValueError):
                return None

        def _normalize_pair(rem_val, used_val, default_remaining=2):
            rem = _safe_int(rem_val)
            used = _safe_int(used_val)
            if rem is None and used is None:
                return default_remaining, 0
            if rem is None:
                rem = max(0, default_remaining - max(0, used or 0))
            if used is None:
                used = max(0, default_remaining - max(0, rem or 0))
            return max(0, rem), max(0, used)

        if not gamepk:
            return 2, 0, 2, 0
        pk_str = str(gamepk)
        now = time.time()
        cached = self._mlb_challenge_cache.get(pk_str)
        if cached and (now - cached.get('ts', 0) < max_age):
            h_rem, h_used = _normalize_pair(cached.get('home_rem'), cached.get('home_used'))
            a_rem, a_used = _normalize_pair(cached.get('away_rem'), cached.get('away_used'))
            return h_rem, h_used, a_rem, a_used
        try:
            r = self.session.get(
                f'https://statsapi.mlb.com/api/v1.1/game/{gamepk}/feed/live',
                timeout=5,
            )
            if r.status_code == 200:
                game_data = r.json().get('gameData', {})
                abs_ch = game_data.get('absChallenges', {})
                review = game_data.get('review', {})

                h_rem = h_used = a_rem = a_used = None

                # Prefer ABS challenge counts when present (teams start with 2).
                if isinstance(abs_ch, dict) and abs_ch.get('hasChallenges'):
                    h_abs = abs_ch.get('home', {})
                    a_abs = abs_ch.get('away', {})
                    h_rem, h_used = _normalize_pair(h_abs.get('remaining'), h_abs.get('usedFailed'))
                    a_rem, a_used = _normalize_pair(a_abs.get('remaining'), a_abs.get('usedFailed'))
                else:
                    h = review.get('home', {}) if isinstance(review, dict) else {}
                    a = review.get('away', {}) if isinstance(review, dict) else {}
                    h_rem, h_used = _normalize_pair(h.get('remaining'), h.get('used'))
                    a_rem, a_used = _normalize_pair(a.get('remaining'), a.get('used'))

                entry = {
                    'ts': now,
                    'home_rem': h_rem,
                    'home_used': h_used,
                    'away_rem': a_rem,
                    'away_used': a_used,
                }
                self._mlb_challenge_cache[pk_str] = entry
                return entry['home_rem'], entry['home_used'], entry['away_rem'], entry['away_used']
        except Exception:
            pass

        # Fallback to stale cache entry when API call fails; otherwise 2 remaining, 0 used.
        if cached:
            h_rem, h_used = _normalize_pair(cached.get('home_rem'), cached.get('home_used'))
            a_rem, a_used = _normalize_pair(cached.get('away_rem'), cached.get('away_used'))
            return h_rem, h_used, a_rem, a_used
        return 2, 0, 2, 0

    def _mlb_player_last_name(self, player_id):
        """Return last name for an MLB player ID, using cache + ESPN athletes API."""
        if not player_id:
            return ''
        pid = str(player_id)
        if pid in self._mlb_player_cache:
            return self._mlb_player_cache[pid]
        # Try ESPN core API first, then site API fallback
        urls = [
            f"https://sports.core.api.espn.com/v2/sports/baseball/leagues/mlb/athletes/{pid}",
            f"{self.base_url}baseball/mlb/athletes/{pid}",
        ]
        for url in urls:
            try:
                r = self.session.get(url, headers=HEADERS, timeout=5)
                if r.status_code == 200:
                    ath = r.json()
                    full = (ath.get('shortName') or ath.get('displayName')
                            or ath.get('fullName') or ath.get('lastName', ''))
                    if '. ' in full:
                        full = full.split('. ', 1)[1]
                    name = full.upper()
                    self._mlb_player_cache[pid] = name
                    return name
            except Exception:
                pass
        self._mlb_player_cache[pid] = ''   # cache miss so we don't retry every tick
        return ''

    def _mlb_player_id_from_obj(self, person_obj):
        """Extract an MLB player ID from a batter/pitcher object, handling ESPN variants."""
        if not isinstance(person_obj, dict):
            return ''

        pid = person_obj.get('playerId') or person_obj.get('id')
        if pid:
            return str(pid)

        ath = person_obj.get('athlete')
        if isinstance(ath, dict):
            ath_id = ath.get('id') or ath.get('playerId')
            if ath_id:
                return str(ath_id)

        ref = person_obj.get('$ref')
        if isinstance(ref, str):
            m = re.search(r'/athletes/(\d+)', ref)
            if m:
                return m.group(1)

        return ''

    def _mlb_inline_name_from_obj(self, person_obj):
        """Read a usable display/last name directly from an ESPN person object."""
        if not isinstance(person_obj, dict):
            return ''

        for key in ('lastName', 'displayName', 'shortName', 'fullName', 'name'):
            val = person_obj.get(key)
            if val:
                name = str(val).strip()
                if '. ' in name:
                    name = name.split('. ', 1)[1]
                return name.upper()

        ath = person_obj.get('athlete')
        if isinstance(ath, dict):
            for key in ('lastName', 'displayName', 'shortName', 'fullName', 'name'):
                val = ath.get(key)
                if val:
                    name = str(val).strip()
                    if '. ' in name:
                        name = name.split('. ', 1)[1]
                    return name.upper()

        return ''

    def _mlb_resolve_person_name(self, person_obj, person_id=None, fallback_name=''):
        """Resolve batter/pitcher name from ID first, then fallback name/object text."""
        if person_id:
            by_id = self._mlb_player_last_name(person_id)
            if by_id:
                return by_id

        if fallback_name:
            return str(fallback_name).strip().upper()

        return self._mlb_inline_name_from_obj(person_obj)

    def _mlb_find_stat_value(self, data, wanted_keys):
        """Depth-first search for the first non-empty key in nested ESPN stat payloads."""
        if isinstance(data, dict):
            for k, v in data.items():
                if k in wanted_keys and v not in (None, ''):
                    return v
            for v in data.values():
                found = self._mlb_find_stat_value(v, wanted_keys)
                if found not in (None, ''):
                    return found
        elif isinstance(data, (list, tuple)):
            for item in data:
                found = self._mlb_find_stat_value(item, wanted_keys)
                if found not in (None, ''):
                    return found
        return None

    def _mlb_int(self, value, default=0):
        try:
            if value in (None, ''):
                return default
            return int(float(value))
        except Exception:
            return default

    def _mlb_normalize_pitch_type(self, pitch_type):
        """Return normalized (abbr, full_name) for MLB pitch types."""
        raw_abbr = ''
        raw_full = ''

        if isinstance(pitch_type, dict):
            raw_abbr = str(pitch_type.get('abbreviation') or '').strip().upper()
            raw_full = str(pitch_type.get('text') or pitch_type.get('displayValue') or '').strip()
        elif isinstance(pitch_type, str):
            p = pitch_type.strip()
            if p and len(p) <= 4 and ' ' not in p and '-' not in p:
                raw_abbr = p.upper()
            else:
                raw_full = p

        full_l = raw_full.lower()

        official_full = {
            'FF': 'Four-Seam Fastball',
            'FT': 'Two-Seam Fastball / Sinker',
            'FC': 'Cutter (Fastball-cutter)',
            'FA': 'Fastball (general)',
            'FS': 'Splitter / Split-fingered Fastball',
            'SF': 'Splitter / Split-fingered Fastball',
            'SI': 'Sinker',
            'SL': 'Slider',
            'CB': 'Curveball',
            'CU': 'Curveball',
            'KC': 'Knuckle Curve',
            'SC': 'Screwball',
            'ST': 'Sweeper',
            'CH': 'Changeup',
            'EP': 'Eephus',
            'FO': 'Forkball',
            'KN': 'Knuckleball',
            'UN': 'Unidentified / Unknown',
            'XX': 'Unidentified / Unknown',
            'PO': 'Pitchout',
            'GY': 'Gyroball',
            'NP': 'No Pitch',
        }

        # Pass through official abbreviations as-is.
        abbr = raw_abbr if raw_abbr in official_full else ''
        if not abbr:
            if 'four-seam' in full_l or '4-seam' in full_l:
                abbr = 'FF'
            elif 'two-seam' in full_l or '2-seam' in full_l:
                abbr = 'FT'
            elif 'sinker' in full_l:
                abbr = 'SI'
            elif 'cutter' in full_l:
                abbr = 'FC'
            elif 'slider' in full_l:
                abbr = 'SL'
            elif 'sweeper' in full_l:
                abbr = 'ST'
            elif 'knuckle curve' in full_l:
                abbr = 'KC'
            elif 'curve' in full_l:
                abbr = 'CB'
            elif 'screwball' in full_l:
                abbr = 'SC'
            elif 'change' in full_l:
                abbr = 'CH'
            elif 'eephus' in full_l:
                abbr = 'EP'
            elif 'forkball' in full_l:
                abbr = 'FO'
            elif 'split' in full_l:
                abbr = 'SF'
            elif 'knuckleball' in full_l:
                abbr = 'KN'
            elif 'pitchout' in full_l:
                abbr = 'PO'
            elif 'gyro' in full_l:
                abbr = 'GY'
            elif 'no pitch' in full_l:
                abbr = 'NP'
            elif 'unknown' in full_l or 'unidentified' in full_l:
                abbr = 'UN'
            elif 'fastball' in full_l:
                abbr = 'FA'

        full = official_full.get(abbr, '')
        if not full and raw_full:
            full = raw_full

        return abbr, full

    def _mlb_extract_situation_stats(self, sit, batter_obj=None, pitcher_obj=None, full_data=None):
        """Extract batter/pitcher live stats from diverse ESPN MLB situation payload shapes."""
        sit = sit or {}
        batter_obj = batter_obj or (sit.get('batter') or {})
        pitcher_obj = pitcher_obj or (sit.get('pitcher') or {})

        batter_avg = self._mlb_find_stat_value(
            [sit.get('batterStats'), sit, batter_obj],
            {'avg', 'average', 'battingAverage'}
        )
        batter_h = self._mlb_find_stat_value(
            [sit.get('batterStats'), sit, batter_obj],
            {'hits', 'h'}
        )
        batter_ab = self._mlb_find_stat_value(
            [sit.get('batterStats'), sit, batter_obj],
            {'atBats', 'ab'}
        )
        pitcher_pitches = self._mlb_find_stat_value(
            [sit.get('pitcherStats'), sit, pitcher_obj],
            {'pitchCount', 'numberOfPitches', 'pitches', 'totalPitches'}
        )

        lp = sit.get('lastPlay') or sit.get('lastPitch') or {}

        # ESPN often provides situation.lastPlay as only {'id': '...'} while
        # pitchVelocity/pitchType live in the matching object under data['plays'].
        if isinstance(lp, dict) and isinstance(full_data, dict):
            has_speed = self._mlb_find_stat_value(lp, {'pitchVelocity', 'velocity', 'speed'}) not in (None, '')
            pt_val = lp.get('pitchType')
            has_type = bool(pt_val)
            if not (has_speed and has_type):
                lp_id = str(lp.get('id') or '')
                plays = full_data.get('plays') if isinstance(full_data.get('plays'), list) else []
                if plays:
                    resolved = None
                    if lp_id:
                        for p in plays:
                            if str((p or {}).get('id', '')) == lp_id:
                                resolved = p
                                break
                    if resolved is None:
                        resolved = plays[-1]
                    if isinstance(resolved, dict):
                        lp = resolved

        last_pitch_speed = 0
        last_pitch_type_abbr = ''
        last_pitch_type_full = ''
        if isinstance(lp, dict):
            spd_val = (
                lp.get('pitchVelocity')
                or lp.get('velocity')
                or lp.get('speed')
                or self._mlb_find_stat_value(lp, {'pitchVelocity', 'velocity', 'speed'})
            )
            last_pitch_speed = self._mlb_int(spd_val, 0)
            pt = lp.get('pitchType')
            if not pt:
                pt = {
                    'abbreviation': lp.get('pitchTypeAbbreviation'),
                    'text': lp.get('pitchTypeText')
                }
            last_pitch_type_abbr, last_pitch_type_full = self._mlb_normalize_pitch_type(pt)

        return {
            'batter_avg': str(batter_avg).strip() if batter_avg not in (None, '') else '',
            'batter_h': str(batter_h).strip() if batter_h not in (None, '') else '',
            'batter_ab': str(batter_ab).strip() if batter_ab not in (None, '') else '',
            'pitcher_pitches': self._mlb_int(pitcher_pitches, 0),
            'last_pitch_speed': last_pitch_speed,
            # Keep legacy key for compatibility; value is normalized abbreviation.
            'last_pitch_type': last_pitch_type_abbr,
            'last_pitch_type_abbr': last_pitch_type_abbr,
            'last_pitch_type_full': last_pitch_type_full,
        }

    def _mlb_extract_boxscore_stats(self, data, batter_id=None, pitcher_id=None):
        """Extract batter/pitcher line stats from ESPN MLB boxscore payload variants."""
        result = {
            'batter_avg': '',
            'batter_h': '',
            'batter_ab': '',
            'pitcher_pitches': 0,
        }

        bid = str(batter_id or '')
        pid = str(pitcher_id or '')
        box = (data or {}).get('boxscore') or {}

        # Variant A: boxscore.players[*].statistics[*] with block.keys + athlete.stats[] values.
        for team in (box.get('players') or []):
            for block in (team.get('statistics') or []):
                keys = [str(k) for k in (block.get('keys') or [])]
                for ath in (block.get('athletes') or []):
                    aid = str((ath.get('athlete') or {}).get('id') or '')
                    vals = [str(v) if v is not None else '' for v in (ath.get('stats') or [])]
                    if not aid or not vals:
                        continue

                    by_key = {}
                    for i, k in enumerate(keys):
                        if i < len(vals):
                            by_key[k] = vals[i]

                    if aid == bid:
                        result['batter_avg'] = result['batter_avg'] or by_key.get('avg') or by_key.get('average') or by_key.get('battingAverage') or ''
                        result['batter_h'] = result['batter_h'] or by_key.get('hits') or ''
                        result['batter_ab'] = result['batter_ab'] or by_key.get('atBats') or ''

                        h_ab = by_key.get('hits-atBats') or by_key.get('h-ab') or ''
                        if h_ab and ('-' in h_ab or '/' in h_ab):
                            parts = re.split(r'[-/]', h_ab)
                            if len(parts) >= 2:
                                if not result['batter_h']:
                                    result['batter_h'] = str(parts[0]).strip()
                                if not result['batter_ab']:
                                    result['batter_ab'] = str(parts[1]).strip()

                    if aid == pid:
                        pc = by_key.get('pitches') or by_key.get('numberOfPitches') or by_key.get('pitchCount') or ''
                        if not pc:
                            pc_st = by_key.get('pitches-strikes') or by_key.get('pitchCount-strikes') or ''
                            if isinstance(pc_st, str) and '-' in pc_st:
                                pc = pc_st.split('-', 1)[0]
                        if pc not in (None, ''):
                            result['pitcher_pitches'] = self._mlb_int(pc, result['pitcher_pitches'])

        # Variant B: older boxscore.teams[*].statistics[*].athletes with named stat rows.
        for team_box in (box.get('teams') or []):
            for stat_block in (team_box.get('statistics') or []):
                for ath in (stat_block.get('athletes') or []):
                    aid = str((ath.get('athlete') or {}).get('id') or '')
                    if not aid:
                        continue
                    stat_map = {}
                    for s in (ath.get('stats') or []):
                        k = s.get('name')
                        if not k:
                            continue
                        stat_map[k] = s.get('displayValue') or s.get('value') or ''

                    if aid == pid:
                        pc = stat_map.get('pitchCount') or stat_map.get('numberOfPitches')
                        if pc not in (None, ''):
                            result['pitcher_pitches'] = self._mlb_int(pc, result['pitcher_pitches'])
                    if aid == bid:
                        result['batter_avg'] = stat_map.get('avg') or result['batter_avg']
                        result['batter_h'] = stat_map.get('hits') or result['batter_h']
                        result['batter_ab'] = stat_map.get('atBats') or result['batter_ab']

        return result

    def _mlb_get_summary(self, game_id, max_age=12):
        """Return cached MLB summary payload for a game, refreshing every max_age seconds."""
        gid = str(game_id)
        now = time.time()
        cached = self._mlb_summary_cache.get(gid)
        if cached and (now - cached.get('ts', 0) < max_age):
            return cached.get('data')

        try:
            url = f"{self.base_url}baseball/mlb/summary"
            r = self.session.get(url, params={'event': gid}, headers=HEADERS, timeout=TIMEOUTS['default'])
            if r.status_code == 200:
                data = r.json()
                self._mlb_summary_cache[gid] = {'ts': now, 'data': data}
                return data
        except Exception:
            pass
        return None

    def _mlb_enrich_live_from_summary(self, game_id, current_sit):
        """Fill missing live MLB fields from the per-game summary endpoint."""
        data = self._mlb_get_summary(game_id)
        if not data:
            return {}

        current_sit = current_sit or {}
        comp = (data.get('header', {}).get('competitions') or [{}])[0]
        bsit = data.get('situation') or comp.get('situation') or {}

        bat_obj = bsit.get('batter') or {}
        pit_obj = bsit.get('pitcher') or {}
        bat_pid = self._mlb_player_id_from_obj(bat_obj)
        pit_pid = self._mlb_player_id_from_obj(pit_obj)

        batter_name = self._mlb_resolve_person_name(
            bat_obj,
            bat_pid,
            bsit.get('batterName') or bsit.get('batter_name') or current_sit.get('batter_name', '')
        )
        pitcher_name = self._mlb_resolve_person_name(
            pit_obj,
            pit_pid,
            bsit.get('pitcherName') or bsit.get('pitcher_name') or current_sit.get('pitcher_name', '')
        )

        stats = self._mlb_extract_situation_stats(bsit, bat_obj, pit_obj, data)
        batter_avg = stats.get('batter_avg', '') or current_sit.get('batter_avg', '')
        batter_h = stats.get('batter_h', '') or current_sit.get('batter_h', '')
        batter_ab = stats.get('batter_ab', '') or current_sit.get('batter_ab', '')
        pitcher_pitches = stats.get('pitcher_pitches', 0) or current_sit.get('pitcher_pitches', 0)
        last_pitch_speed = stats.get('last_pitch_speed', 0) or current_sit.get('last_pitch_speed', 0)
        last_pitch_type_abbr = (
            stats.get('last_pitch_type_abbr', '')
            or stats.get('last_pitch_type', '')
            or current_sit.get('last_pitch_type_abbr', '')
            or current_sit.get('last_pitch_type', '')
        )
        last_pitch_type_full = stats.get('last_pitch_type_full', '') or current_sit.get('last_pitch_type_full', '')

        # Secondary stats source: boxscore athletes (supports ESPN players+keys/stats shape).
        box_stats = self._mlb_extract_boxscore_stats(data, bat_pid, pit_pid)
        batter_avg = box_stats.get('batter_avg') or batter_avg
        batter_h = box_stats.get('batter_h') or batter_h
        batter_ab = box_stats.get('batter_ab') or batter_ab
        pitcher_pitches = box_stats.get('pitcher_pitches') or pitcher_pitches

        return {
            'balls': bsit.get('balls', current_sit.get('balls', 0)),
            'strikes': bsit.get('strikes', current_sit.get('strikes', 0)),
            'outs': bsit.get('outs', current_sit.get('outs', 0)),
            'onFirst': bool(bsit.get('onFirst', current_sit.get('onFirst', False))),
            'onSecond': bool(bsit.get('onSecond', current_sit.get('onSecond', False))),
            'onThird': bool(bsit.get('onThird', current_sit.get('onThird', False))),
            'batter_name': batter_name or current_sit.get('batter_name', ''),
            'batter_avg': str(batter_avg).strip() if batter_avg not in (None, '') else '',
            'batter_h': str(batter_h).strip() if batter_h not in (None, '') else '',
            'batter_ab': str(batter_ab).strip() if batter_ab not in (None, '') else '',
            'pitcher_name': pitcher_name or current_sit.get('pitcher_name', ''),
            'pitcher_pitches': self._mlb_int(pitcher_pitches, 0),
            'last_pitch_speed': self._mlb_int(last_pitch_speed, 0),
            'last_pitch_type': str(last_pitch_type_abbr or '').strip(),
            'last_pitch_type_abbr': str(last_pitch_type_abbr or '').strip(),
            'last_pitch_type_full': str(last_pitch_type_full or '').strip(),
        }

    def fetch_pinned_game(self, pinned_str, conf, visible_start_utc, visible_end_utc):
        """
        Fetches ONLY the pinned game, bypassing all other league fetches.
        pinned_str format: "league:game_id" (e.g., "nfl:401547378" or "soccer_epl:423141")
        """
        try:
            league_key, game_id = pinned_str.split(':', 1)
            league_key = league_key.lower()
        except ValueError:
            print("Invalid pinned game format. Use 'league:game_id'")
            return []

        utc_offset = conf.get('utc_offset', -5)

        # 0. NHL Native Pinned Game (handles NHL gamecenter IDs like 2025020978)
        if league_key == 'nhl':
            try:
                native = self._fetch_nhl_landing(game_id)
                if native:
                    st = str(native.get('gameState', 'OFF')).upper()
                    map_st = 'in' if st in ['LIVE', 'CRIT'] else ('pre' if st in ['PRE', 'FUT'] else 'post')

                    g_utc = native.get('startTimeUTC', '')
                    raw_h = native.get('homeTeam', {}).get('abbrev', 'UNK')
                    raw_a = native.get('awayTeam', {}).get('abbrev', 'UNK')
                    h_ab = ABBR_MAPPING.get(raw_h, raw_h)
                    a_ab = ABBR_MAPPING.get(raw_a, raw_a)

                    h_sc = str(native.get('homeTeam', {}).get('score', 0))
                    a_sc = str(native.get('awayTeam', {}).get('score', 0))

                    h_lg = self.get_corrected_logo('nhl', h_ab, f"https://a.espncdn.com/i/teamlogos/nhl/500/{h_ab.lower()}.png")
                    a_lg = self.get_corrected_logo('nhl', a_ab, f"https://a.espncdn.com/i/teamlogos/nhl/500/{a_ab.lower()}.png")
                    h_info = self.lookup_team_info_from_cache('nhl', h_ab, logo=h_lg)
                    a_info = self.lookup_team_info_from_cache('nhl', a_ab, logo=a_lg)

                    disp = "Scheduled"
                    pp = False
                    poss = ""
                    en = False
                    shootout_data = None

                    pd = native.get('periodDescriptor', {})
                    clk = native.get('clock', {})
                    p_num = int(pd.get('number', 1) or 1)
                    p_type = str(pd.get('periodType', '')).upper()
                    time_rem = clk.get('timeRemaining', '00:00')

                    if map_st == 'pre':
                        try:
                            g_dt = parse_iso(g_utc)
                            disp = g_dt.astimezone(timezone(timedelta(hours=utc_offset))).strftime("%I:%M %p").lstrip('0')
                        except:
                            pass
                    elif map_st == 'post':
                        disp = "FINAL"
                        if p_type == 'SHOOTOUT' or p_num >= 5:
                            disp = "FINAL S/O"
                        elif p_type == 'OT' or p_num == 4:
                            disp = "FINAL OT"
                    else:
                        if p_type == 'SHOOTOUT' or p_num >= 5:
                            disp = "S/O"
                            shootout_data = self.fetch_shootout_details(game_id, 0, 0)
                        elif clk.get('inIntermission', False) or time_rem == "00:00":
                            if p_num == 1:
                                disp = "End 1st"
                            elif p_num == 2:
                                disp = "End 2nd"
                            elif p_num == 3:
                                disp = "End 3rd"
                            else:
                                disp = "End OT"
                        else:
                            p_lbl = "OT" if p_num == 4 else f"P{p_num}"
                            disp = f"{p_lbl} {time_rem}"

                    sit_obj = native.get('situation', {})
                    if sit_obj:
                        sit = sit_obj.get('situationCode', '1551')
                        if len(sit) >= 4 and sit.isdigit():
                            ag = int(sit[0])
                            as_ = int(sit[1])
                            hs = int(sit[2])
                            hg = int(sit[3])
                            if as_ > hs:
                                pp = True
                                poss = a_ab
                            elif hs > as_:
                                pp = True
                                poss = h_ab
                            en = (ag == 0 or hg == 0)

                    if "FINAL" in disp:
                        shootout_data = None

                    return [{
                        'type': 'scoreboard',
                        'sport': 'nhl', 'id': str(game_id), 'status': disp, 'state': map_st, 'is_shown': True,
                        'home_abbr': h_ab, 'home_score': h_sc, 'home_logo': h_lg, 'home_id': h_ab,
                        'away_abbr': a_ab, 'away_score': a_sc, 'away_logo': a_lg, 'away_id': a_ab,
                        'home_color': f"#{h_info['color']}", 'home_alt_color': f"#{h_info['alt_color']}",
                        'away_color': f"#{a_info['color']}", 'away_alt_color': f"#{a_info['alt_color']}",
                        'startTimeUTC': g_utc,
                        'estimated_duration': self.calculate_game_timing('nhl', g_utc, p_num, disp),
                        'situation': {
                            'powerPlay': pp,
                            'possession': poss,
                            'emptyNet': en,
                            'shootout': shootout_data
                        }
                    }]
            except Exception as e:
                print(f"NHL Pinned Game Error: {e}")

        # 1. FotMob (Soccer) Pinned Game
        if league_key in FOTMOB_LEAGUE_MAP:
            try:
                url = f"https://www.fotmob.com/api/matchDetails?matchId={game_id}"
                resp = self.session.get(url, headers=HEADERS, timeout=TIMEOUTS['slow'])
                if resp.status_code == 200:
                    payload = resp.json()
                    general = payload.get("general", {})
                    header = payload.get("header", {})
                    status_obj = header.get("status", {})
                    
                    # Convert matchDetails into the standard FotMob 'matches' array format 
                    mock_match = {
                        "id": game_id,
                        "home": {"id": general.get("homeTeam", {}).get("id"), "name": general.get("homeTeam", {}).get("name")},
                        "away": {"id": general.get("awayTeam", {}).get("id"), "name": general.get("awayTeam", {}).get("name")},
                        "status": {
                            "utcTime": general.get("matchTimeUTC"),
                            "finished": status_obj.get("finished"),
                            "started": status_obj.get("started"),
                            "cancelled": status_obj.get("cancelled"),
                            "scoreStr": status_obj.get("scoreStr"),
                            "reason": status_obj.get("reason"),
                            "liveTime": status_obj.get("liveTime")
                        }
                    }
                    
                    # Pass a massive time window so it passes normal time filters
                    huge_start = dt(1970, 1, 1, tzinfo=timezone.utc)
                    huge_end = dt(2099, 1, 1, tzinfo=timezone.utc)
                    return self._extract_matches([mock_match], league_key, conf, huge_start, huge_end, huge_start, huge_end)
            except Exception as e:
                print(f"FotMob Pinned Game Error: {e}")
                return []

        # 2. ESPN Pinned Game (NFL, NBA, MLB, NHL, NCAA)
        config = self.leagues.get(league_key)
        path = config.get('path') if config else None
        if not path:
            paths = {
                'nfl': 'football/nfl', 'mlb': 'baseball/mlb', 'nhl': 'hockey/nhl', 'nba': 'basketball/nba',
                'ncf_fbs': 'football/college-football', 'ncf_fcs': 'football/college-football',
                'march_madness': 'basketball/mens-college-basketball'
            }
            path = paths.get(league_key)

        if not path:
            print(f"Unsupported pinned game league: {league_key}")
            return []

        try:
            url = f"{self.base_url}{path}/summary?event={game_id}"
            r = self.session.get(url, headers=HEADERS, timeout=TIMEOUTS['default'])
            if r.status_code != 200:
                return []
            
            data = r.json()
            header = data.get('header', {})
            comp = header.get('competitions', [{}])[0]
            
            e_date = comp.get('date', '')
            st = comp.get('status', {})
            tp = st.get('type', {})
            gst = tp.get('state', 'pre')

            # Extract competitors
            competitors = comp.get('competitors', [])
            h = next((c for c in competitors if c.get('homeAway') == 'home'), competitors[0] if competitors else {})
            a = next((c for c in competitors if c.get('homeAway') == 'away'), competitors[1] if len(competitors) > 1 else {})

            h_ab = h.get('team', {}).get('abbreviation', 'UNK')
            a_ab = a.get('team', {}).get('abbreviation', 'UNK')

            h_lg = self.get_corrected_logo(league_key, h_ab, h.get('team', {}).get('logos', [{}])[0].get('href', ''))
            a_lg = self.get_corrected_logo(league_key, a_ab, a.get('team', {}).get('logos', [{}])[0].get('href', ''))

            h_clr = h.get('team', {}).get('color', '000000')
            a_clr = a.get('team', {}).get('color', '000000')
            h_alt = h.get('team', {}).get('alternateColor', 'ffffff')
            a_alt = a.get('team', {}).get('alternateColor', 'ffffff')

            if not h_clr or h_clr == '000000' or not a_clr or a_clr == '000000':
                h_info = self.lookup_team_info_from_cache(league_key, h_ab, logo=h_lg)
                a_info = self.lookup_team_info_from_cache(league_key, a_ab, logo=a_lg)
                h_clr = h_clr if h_clr and h_clr != '000000' else h_info.get('color', '000000')
                a_clr = a_clr if a_clr and a_clr != '000000' else a_info.get('color', '000000')
                h_alt = h_alt if h_alt else h_info.get('alt_color', 'ffffff')
                a_alt = a_alt if a_alt else a_info.get('alt_color', 'ffffff')

            h_score = h.get('score', '0')
            a_score = a.get('score', '0')

            s_disp = tp.get('shortDetail', 'TBD')
            p = st.get('period', 1)

            # State Inference
            if gst == 'pre' and any(x in s_disp for x in ['1st', '2nd', '3rd', 'OT', 'Half', 'Qtr', 'Inning']):
                if "FINAL" not in s_disp.upper():
                    gst = 'in'

            is_suspended = any(kw in s_disp for kw in ["Suspended", "Postponed", "Canceled", "Delayed", "PPD"])

            if not is_suspended:
                if gst == 'pre':
                    try: 
                        game_dt = parse_iso(e_date)
                        s_disp = game_dt.astimezone(timezone(timedelta(hours=utc_offset))).strftime("%I:%M %p").lstrip('0')
                    except: pass
                elif gst in ['in', 'half']:
                    clk = st.get('displayClock', '0:00').replace("'", "")
                    if (not clk or clk == '0:00') and ':' in s_disp:
                        m = re.search(r'(\d{1,2}:\d{2})', s_disp)
                        if m: clk = m.group(1)

                    if gst == 'half' or (p == 2 and clk == '0:00' and 'football' in path): s_disp = "Halftime"
                    elif 'hockey' in path and clk == '0:00':
                        s_disp = "End 1st" if p == 1 else "End 2nd" if p == 2 else "End 3rd" if p == 3 else "Intermission"
                    else:
                        if 'basketball' in path:
                            if p > 4:
                                s_disp = f"OT{p-4 if p-4>1 else ''} {clk}"
                            elif league_key == 'march_madness' and p <= 2:
                                s_disp = f"H{p} {clk}"
                            else:
                                s_disp = f"Q{p} {clk}"
                        elif 'football' in path:
                            s_disp = f"OT{p-4 if p-4>1 else ''} {clk}" if p > 4 else f"Q{p} {clk}"
                        elif 'hockey' in path:
                            s_disp = f"OT{p-3 if p-3>1 else ''} {clk}" if p > 3 else f"P{p} {clk}"
                        elif 'baseball' in path:
                            s_disp = tp.get('shortDetail', s_disp).replace(" - ", " ").replace("Inning", "In")
                        else: s_disp = f"P{p} {clk}"

            s_disp = s_disp.replace("Final", "FINAL").replace("/OT", " OT").replace("/SO", " S/O")
            s_disp = s_disp.replace("End of ", "End ").replace(" Quarter", "").replace(" Inning", "").replace(" Period", "")

            # Possessions & Situations
            sit_data = data.get('drives', {}).get('current', {}) if 'football' in path else {}
            # For football, also check the competition situation (has full downDistanceText with position)
            comp_sit = comp.get('situation', {}) if 'football' in path else {}
            poss_raw = comp_sit.get('possession') or (sit_data.get('team', {}).get('id') if sit_data else None)

            balls, strikes, outs, onFirst, onSecond, onThird = 0, 0, 0, False, False, False
            batter_name = pitcher_name = batter_avg = batter_h = batter_ab = last_pitch_type = ''
            pitcher_pitches = last_pitch_speed = 0
            if 'baseball' in path and data.get('situation'):
                bsit = data['situation']
                balls = bsit.get('balls', 0)
                strikes = bsit.get('strikes', 0)
                outs = bsit.get('outs', 0)
                onFirst = bool(bsit.get('onFirst', False))
                onSecond = bool(bsit.get('onSecond', False))
                onThird = bool(bsit.get('onThird', False))

                # ESPN summary gives bare {playerId: N} — look up names via athletes API
                _bat_obj = bsit.get('batter') or {}
                _pit_obj = bsit.get('pitcher') or {}
                _bat_pid = self._mlb_player_id_from_obj(_bat_obj)
                _pit_pid = self._mlb_player_id_from_obj(_pit_obj)
                poss_raw = None   # batter team unavailable in summary; determine from inning
                batter_name = self._mlb_resolve_person_name(
                    _bat_obj,
                    _bat_pid,
                    bsit.get('batterName') or bsit.get('batter_name') or ''
                )
                pitcher_name = self._mlb_resolve_person_name(
                    _pit_obj,
                    _pit_pid,
                    bsit.get('pitcherName') or bsit.get('pitcher_name') or ''
                )

                _mlb_stats = self._mlb_extract_situation_stats(bsit, _bat_obj, _pit_obj, data)
                batter_avg = _mlb_stats.get('batter_avg', '')
                batter_h = _mlb_stats.get('batter_h', '')
                batter_ab = _mlb_stats.get('batter_ab', '')
                pitcher_pitches = _mlb_stats.get('pitcher_pitches', 0)
                last_pitch_speed = _mlb_stats.get('last_pitch_speed', 0)
                last_pitch_type = _mlb_stats.get('last_pitch_type', '')
                last_pitch_type_abbr = _mlb_stats.get('last_pitch_type_abbr', last_pitch_type)
                last_pitch_type_full = _mlb_stats.get('last_pitch_type_full', '')

                _box_stats = self._mlb_extract_boxscore_stats(data, _bat_pid, _pit_pid)
                batter_avg = _box_stats.get('batter_avg') or batter_avg
                batter_h = _box_stats.get('batter_h') or batter_h
                batter_ab = _box_stats.get('batter_ab') or batter_ab
                pitcher_pitches = _box_stats.get('pitcher_pitches') or pitcher_pitches

            poss_abbr = ""
            if str(poss_raw) == str(h.get('team', {}).get('id')): poss_abbr = h_ab
            elif str(poss_raw) == str(a.get('team', {}).get('id')): poss_abbr = a_ab
            # comp_sit possession may already be an abbreviation
            if not poss_abbr and str(poss_raw).upper() == h_ab: poss_abbr = h_ab
            elif not poss_abbr and str(poss_raw).upper() == a_ab: poss_abbr = a_ab

            # Prefer competition situation downDistanceText (includes position "at TEAM YARD")
            down_text = (comp_sit.get('downDistanceText') or comp_sit.get('shortDownDistanceText')
                         or sit_data.get('shortDownDistanceText') or sit_data.get('description') or '')
            if s_disp == "Halftime": down_text = ''
            is_rz = comp_sit.get('isRedZone', False) or sit_data.get('isRedZone', False)

            game_obj = {
                'type': 'scoreboard', 'sport': league_key, 'id': game_id, 'status': s_disp, 'state': gst, 'is_shown': not is_suspended,
                'home_abbr': h_ab, 'home_score': h_score, 'home_logo': h_lg, 'home_id': h.get('team', {}).get('id'),
                'away_abbr': a_ab, 'away_score': a_score, 'away_logo': a_lg, 'away_id': a.get('team', {}).get('id'),
                'home_color': f"#{h_clr}", 'home_alt_color': f"#{h_alt}",
                'away_color': f"#{a_clr}", 'away_alt_color': f"#{a_alt}",
                'startTimeUTC': e_date,
                'estimated_duration': 180,
                'situation': {
                    'possession': poss_abbr,
                    'isRedZone': is_rz,
                    'downDist': down_text,
                    'yardLine': comp_sit.get('yardLine'),
                    'yardsToGo': comp_sit.get('distance'),
                    'possessionTeam': comp_sit.get('possessionText', ''),
                    'shootout': None,
                    'powerPlay': False,
                    'emptyNet': False,
                    'balls': balls, 'strikes': strikes, 'outs': outs,
                    'onFirst': onFirst, 'onSecond': onSecond, 'onThird': onThird,
                    'batter_name': batter_name, 'batter_avg': batter_avg,
                    'batter_h': batter_h, 'batter_ab': batter_ab,
                    'pitcher_name': pitcher_name, 'pitcher_pitches': pitcher_pitches,
                    'last_pitch_speed': last_pitch_speed,
                    'last_pitch_type': last_pitch_type,
                    'last_pitch_type_abbr': last_pitch_type_abbr,
                    'last_pitch_type_full': last_pitch_type_full,
                }
            }

            if 'baseball' in (path or '') and gst in ('in', 'half'):
                try:
                    _gpk = self._mlb_get_gamepk(
                        str(game_id),
                        h_ab,
                        a_ab,
                        e_date,
                        h.get('team', {}).get('id'),
                        a.get('team', {}).get('id'),
                    )
                    _hr, _hu, _ar, _au = self._mlb_get_challenges(_gpk)
                except Exception:
                    _hr = _hu = _ar = _au = 0
                game_obj['home_challenges'] = _hr
                game_obj['home_challenges_used'] = _hu
                game_obj['away_challenges'] = _ar
                game_obj['away_challenges_used'] = _au

            return [game_obj]

        except Exception as e:
            print(f"ESPN Pinned Game Error: {e}")
            return []

    def get_music_object(self):
        if not state['active_sports'].get('music', False): return None
        s_data = spotify_fetcher.get_cached_state()
        
        # If no data or explicit "Waiting for Music" state, return placeholder
        if not s_data or s_data.get('name') == "Waiting for Music...":
            return None

        is_playing = s_data.get('is_playing', False)
        
        # INTERPOLATION: Only add elapsed time if Spotify says it is currently playing
        elapsed = 0
        if is_playing:
            elapsed = time.time() - s_data.get('last_fetch_ts', time.time())
        
        prog = min(s_data['progress'] + elapsed, s_data['duration'])
        
        cur_m, cur_s = divmod(int(prog), 60)
        tot_m, tot_s = divmod(int(s_data['duration']), 60)
        
        # Clearer status string for the ticker
        if is_playing:
            status_str = f"{cur_m}:{cur_s:02d} / {tot_m}:{tot_s:02d}"
        else:
            status_str = f"PAUSED {cur_m}:{cur_s:02d}"

        return {
            'type': 'music', 
            'sport': 'music', 
            'id': 'spotify_now',
            'status': status_str, 
            'state': 'in' if is_playing else 'paused',
            'is_shown': True, 
            'home_abbr': s_data.get('artist', 'Unknown'),
            'away_abbr': s_data.get('name', 'Unknown'),
            'home_logo': s_data.get('cover', ''),
            'situation': {
                'progress': prog,
                'duration': s_data['duration'],
                'is_playing': is_playing,
                'fetch_ts': time.time()
            }
        }

    # ── Per-mode buffer builders ────────────────────────────────────────────

    def _filter_and_sort_games(self, all_games, visible_start_utc, visible_end_utc):
        """Apply 3AM cutoff window filter and sort by priority."""
        filtered = []
        for g in all_games:
            g_type = g.get('type', '')
            g_sport = g.get('sport', '')
            if g_type in ['clock', 'weather', 'music'] or g_sport in ['clock', 'weather', 'music', 'flight']:
                filtered.append(g)
                continue
            state_val = g.get('state', '')
            status_val = str(g.get('status', '')).upper()
            if state_val in ['in', 'half', 'crit']:
                filtered.append(g)
                continue
            if state_val == 'pre':
                filtered.append(g)
                continue
            if state_val == 'post' or 'FINAL' in status_val:
                try:
                    game_dt = parse_iso(g.get('startTimeUTC', ''))
                    if visible_start_utc <= game_dt < visible_end_utc:
                        filtered.append(g)
                except Exception:
                    filtered.append(g)
                continue
            filtered.append(g)
        filtered.sort(key=_game_sort_key)
        return filtered

    def _build_sports_buffer(self):
        """Fetch all active sports leagues and return sorted game list."""
        with data_lock:
            conf = {
                'active_sports': state.get('active_sports', {}),
                'mode': state.get('mode', 'sports'),
                'utc_offset': state.get('utc_offset', -5),
                'debug_mode': state.get('debug_mode', False),
                'custom_date': state.get('custom_date'),
            }

            # Special pinned-game poller inputs (sports_full): collect active pins
            # and merge fresh pinned objects into the normal sports snapshot.
            active_pins = []
            seen_pins = set()
            for _t in tickers.values():
                _s = _t.get('settings', {})
                single_pin, pin_list = _normalize_single_pin(
                    pinned_game=_s.get('pinned_game'),
                    pinned_games=_s.get('pinned_games', [])
                )
                for _p in pin_list:
                    _pn = str(_p).strip().lower()
                    if _pn and _pn not in seen_pins:
                        seen_pins.add(_pn)
                        active_pins.append(_p)
            
        all_games = []
        utc_offset = conf.get('utc_offset', -5)
        now_utc = dt.now(timezone.utc)
        now_local = now_utc.astimezone(timezone(timedelta(hours=utc_offset)))
        
        # Visibility Windows
        if now_local.hour < 3:
            visible_start_local = (now_local - timedelta(days=1)).replace(hour=10, minute=0, second=0, microsecond=0)
            visible_end_local = now_local.replace(hour=3, minute=0, second=0, microsecond=0)
        else:
            visible_start_local = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
            visible_end_local = (now_local + timedelta(days=1)).replace(hour=3, minute=0, second=0, microsecond=0)
        
        visible_start_utc = visible_start_local.astimezone(timezone.utc)
        visible_end_utc = visible_end_local.astimezone(timezone.utc)
        window_start_utc = (now_local - timedelta(hours=30)).astimezone(timezone.utc)
        window_end_utc = (now_local + timedelta(hours=48)).astimezone(timezone.utc)

        futures = {}
        for internal_id, fid in FOTMOB_LEAGUE_MAP.items():
            f = self.executor.submit(self._fetch_fotmob_league, fid, internal_id, conf, window_start_utc, window_end_utc, visible_start_utc, visible_end_utc)
            futures[f] = internal_id

        if not conf['debug_mode']:
            f = self.executor.submit(self._fetch_nhl_native, conf, window_start_utc, window_end_utc, visible_start_utc, visible_end_utc)
            futures[f] = 'nhl_native'

        for league_key, config in self.leagues.items():
            if league_key == 'nhl' or league_key.startswith('soccer_'): continue
            f = self.executor.submit(self.fetch_single_league, league_key, config, conf, window_start_utc, window_end_utc, utc_offset, visible_start_utc, visible_end_utc)
            futures[f] = league_key
        
        partial = {lk: self.league_last_data.get(lk, []) for lk in futures.values()}
        deadline = time.time() + API_TIMEOUT

        for future in concurrent.futures.as_completed(list(futures.keys())):
            lk = futures[future]
            try:
                res = future.result(timeout=0)
                if res:
                    partial[lk] = res
                    self.league_last_data[lk] = res
            except Exception: pass
            interim_all = []
            for games in partial.values(): interim_all.extend(games)
            interim = self._filter_and_sort_games(interim_all, visible_start_utc, visible_end_utc)
            with data_lock:
                if interim or not state.get('current_games'): state['current_games'] = interim
            if time.time() >= deadline: break

        all_games = []
        for games in partial.values(): all_games.extend(games)

        # Pinned refresh merge: poll only pinned games and merge them into the
        # normal sports feed so sports_full gets a fresh focused game while
        # retaining all other scores from the standard poller.
        if active_pins:
            pinned_futures = {
                self.executor.submit(self.fetch_pinned_game, p, conf, visible_start_utc, visible_end_utc): p
                for p in active_pins
            }
            merged_index = {(str(g.get('sport', '')), str(g.get('id', ''))): i for i, g in enumerate(all_games)}
            for pf in concurrent.futures.as_completed(list(pinned_futures.keys())):
                try:
                    pin_games = pf.result(timeout=0)
                except Exception:
                    pin_games = []
                for pg in pin_games or []:
                    key = (str(pg.get('sport', '')), str(pg.get('id', '')))
                    if key in merged_index:
                        all_games[merged_index[key]] = pg
                    else:
                        merged_index[key] = len(all_games)
                        all_games.append(pg)

        return self._filter_and_sort_games(all_games, visible_start_utc, visible_end_utc)

    def _build_stocks_buffer(self):
        with data_lock:
            active_sports = dict(state['active_sports'])
        games = []
        for item in LEAGUE_OPTIONS:
            if item['type'] == 'stock':
                games.extend(self.stocks.get_list(item['id']))
        return games

    def _build_weather_buffer(self):
        with data_lock:
            city = state['weather_city']
            lat  = state['weather_lat']
            lon  = state['weather_lon']
        if lat != self.weather.lat or lon != self.weather.lon or city != self.weather.city_name:
            self.weather.update_config(city=city, lat=lat, lon=lon)
        w = self.weather.get_weather()
        if w:
            return [w]
        return [{
            'type': 'weather',
            'sport': 'weather',
            'id': 'weather_loading',
            'away_abbr': str(city or 'WEATHER').upper(),
            'home_abbr': '--',
            'situation': {
                'icon': 'cloud',
                'stats': {'aqi': '--', 'uv': '--'},
                'forecast': []
            },
            'home_score': '--',
            'away_score': '0',
            'status': 'LOADING',
            'is_shown': True
        }]

    def _build_music_buffer(self):
        obj = self.get_music_object()
        return [obj] if obj else []

    def _build_clock_buffer(self):
        return [{'type': 'clock', 'sport': 'clock', 'id': 'clk', 'is_shown': True}]

    def _build_flights_buffer(self):
        if not flight_tracker:
            return []
        return flight_tracker.get_airport_objects()

    def _build_flight_tracker_buffer(self):
        if not flight_tracker:
            return []
        obj = flight_tracker.get_visitor_object()
        return [obj] if obj else []

    def _build_poop_fetcher_buffer(self):
        return [poop_fetcher.get_mode_object()]

    # ── Central update dispatcher ──────────────────────────────────────────

    def update_current_games(self):
        """Build and cache content buffers for every mode currently needed by any ticker."""
        with data_lock:
            global_mode = state.get('mode', 'sports')
            # Collect all modes currently in use across all tickers
            needed: set = {global_mode}
            for t in tickers.values():
                m = t.get('settings', {}).get('mode')
                if m and m in VALID_MODES:
                    needed.add(m)
            

        _dispatch = {
            'sports':         self._build_sports_buffer,
            'live':           self._build_sports_buffer,
            'my_teams':       self._build_sports_buffer,
            'stocks':         self._build_stocks_buffer,
            'weather':        self._build_weather_buffer,
            'music':          self._build_music_buffer,
            'clock':          self._build_clock_buffer,
            'flights':        self._build_flights_buffer,
            'flight_tracker': self._build_flight_tracker_buffer,
            'poop_fetcher':   self._build_poop_fetcher_buffer,
        }

        sports_built = False
        for mode in needed:
            is_sports = mode in ('sports', 'live', 'my_teams', 'sports_full')

            if is_sports and sports_built:
                # All three sports-like modes share the same raw buffer; already built.
                continue

            builder = _dispatch.get(mode, self._build_sports_buffer)
            result = builder()

            if is_sports:
                sports_built = True
                # Store under all sports-like keys (filtering is done in /data)
                for sm in ('sports', 'live', 'my_teams', 'sports_full'):
                    self._set_mode_buffer(sm, result)

                # Maintain history buffer for live-delay
                snap = (time.time(), result[:])
                self.history_buffer.append(snap)
                if len(self.history_buffer) > 120:
                    self.history_buffer = self.history_buffer[-120:]

                # Persist non-empty sports games so they survive server restarts
                if result:
                    try:
                        save_json_atomically(GAME_CACHE_FILE, result)
                    except Exception:
                        pass
            else:
                self._set_mode_buffer(mode, result)

        # Keep global state['current_games'] in sync with the global mode
        # (for backward compat with any code that reads it directly)
        with self._mode_buffer_lock:
            global_result = self._mode_buffers.get(global_mode, [])
        is_global_sports = global_mode in ('sports', 'live', 'my_teams', 'sports_full')
        with data_lock:
            if global_result or not is_global_sports or not state.get('current_games'):
                state['current_games'] = global_result

    def get_snapshot_for_delay(self, delay_seconds):
        """Return current games, optionally from history buffer for live-delay."""
        with self._mode_buffer_lock:
            latest_sports = list(self._mode_buffers.get('sports', []))

        if delay_seconds <= 0:
            if latest_sports:
                return latest_sports
            with data_lock:
                return list(state.get('current_games', []))

        if not self.history_buffer:
            if latest_sports:
                return latest_sports
            with data_lock:
                return list(state.get('current_games', []))

        target_time = time.time() - delay_seconds
        chosen = None
        for ts, snapshot in reversed(self.history_buffer):
            if ts <= target_time:
                chosen = snapshot
                break

        if chosen is None and self.history_buffer:
            chosen = self.history_buffer[0][1]

        if chosen is None:
            return latest_sports

        return chosen

    def _set_mode_buffer(self, mode: str, result: list):
        """Store result in per-mode buffer. Also syncs global buffer when mode matches global."""
        with self._mode_buffer_lock:
            self._mode_buffers[mode] = result
        # Keep global state['current_games'] in sync for backward compat
        with data_lock:
            if state.get('mode') == mode:
                if result or not state.get('current_games'):
                    state['current_games'] = result

    def get_mode_snapshot(self, mode: str, delay_seconds: float = 0) -> list:
        """Return buffered content for the given mode.
        Sports modes with delay use the history buffer for live-delay support.
        All other modes always return current data (delay is ignored).
        """
        if mode in ('sports', 'live', 'my_teams', 'sports_full'):
            return self.get_snapshot_for_delay(delay_seconds)
        with self._mode_buffer_lock:
            return list(self._mode_buffers.get(mode, []))

# Restore TestMode from persisted state (only active when debug_mode is on)
if state.get('debug_mode'):
    TestMode.configure(
        enabled=state.get('test_mode', False),
        spotify=state.get('test_spotify', False),
        stocks=state.get('test_stocks', False),
        sports_date=state.get('test_sports_date', False),
        flights=state.get('test_flights', False),
        custom_date=state.get('custom_date'),
    )
    if tee_instance is not None:
        Tee.verbose_debug = True

# Initialize Global Fetcher
fetcher = SportsFetcher(
    initial_city=state['weather_city'], 
    initial_lat=state['weather_lat'], 
    initial_lon=state['weather_lon']
)

# Initialize Spotify Fetcher
spotify_fetcher = SpotifyFetcher()
spotify_fetcher.start()

# Initialize Flight Tracker
# FlightTracker itself has no dependency on airportsdata — that package is only
# used by lookup_and_auto_fill_airport() for code validation. Always create the
# tracker so that flights/flight_tracker modes work even without airportsdata.
try:
    flight_tracker = FlightTracker()
    flight_tracker.track_flight_id = state.get('track_flight_id', '')
    flight_tracker.track_guest_name = state.get('track_guest_name', '')
    flight_tracker.airport_code_icao = state.get('airport_code_icao', 'KEWR')
    flight_tracker.airport_code_iata = state.get('airport_code_iata', 'EWR')
    flight_tracker.airport_name = state.get('airport_name', 'Newark')
    flight_tracker.airline_filter = ''  # Force empty - support all airlines
except Exception as e:
    print(f"⚠️ FlightTracker init failed: {e}")
    flight_tracker = None

# ── Section K: Worker Threads ──
def _any_ticker_needs(*modes):
    """Return True if the global state or any paired ticker is in one of the given modes."""
    mode_set = set(modes)
    with data_lock:
        # Pinned game override: force sports_full behavior whenever any pin exists.
        if 'sports_full' in mode_set:
            for t in tickers.values():
                s = t.get('settings', {})
                if s.get('pinned_game'):
                    return True
                t_pins = s.get('pinned_games', [])
                if isinstance(t_pins, list) and any(str(p).strip() for p in t_pins):
                    return True

        if state.get('mode') in mode_set:
            return True
        for t in tickers.values():
            if t.get('paired') and t.get('settings', {}).get('mode') in mode_set:
                return True
    return False

def _normalize_single_pin(pinned_game=None, pinned_games=None):
    single = ''

    if isinstance(pinned_games, list):
        cleaned = [str(x).strip() for x in pinned_games if str(x).strip()]
        if cleaned:
            single = cleaned[-1]

    if not single and pinned_game is not None:
        single = str(pinned_game).strip()

    return single, ([single] if single else [])

def sports_worker():
    try: fetcher.fetch_all_teams()
    except Exception as e: print(f"Team fetch error: {e}")

    while True:
        try:
            start_time = time.time()
            if _any_ticker_needs('sports', 'live', 'my_teams', 'sports_full'):
                try:
                    fetcher.update_current_games()
                except Exception as e:
                    print(f"Sports Worker Error: {e}")
            execution_time = time.time() - start_time
            time.sleep(max(0, SPORTS_UPDATE_INTERVAL - execution_time))
        except Exception as e:
            print(f"Sports Worker Fatal Error (recovering): {e}")
            time.sleep(SPORTS_UPDATE_INTERVAL)

def stocks_worker():
    _cached_active_key = None
    while True:
        try:
            if _any_ticker_needs('stocks'):
                with data_lock:
                    active_sports = state['active_sports']
                active_key = frozenset(k for k, v in active_sports.items() if k.startswith('stock_') and v)
                if active_key != _cached_active_key:
                    _cached_active_key = active_key
                fetcher.stocks.update_market_data(list(_cached_active_key))
                fetcher.update_current_games()
        except Exception as e:
            print(f"Stock worker error: {e}")
        time.sleep(1)

def music_worker():
    while True:
        try:
            if _any_ticker_needs('music'):
                try:
                    fetcher.update_current_games()
                except Exception as e:
                    print(f"Music Worker Error: {e}")
        except Exception as e:
            print(f"Music worker error: {e}")
        time.sleep(1)

def flights_worker():
    if not flight_tracker:
        if TestMode.is_enabled('flights'):
            print("[DEBUG] flights_worker: No flight_tracker available")
        return
    if TestMode.is_enabled('flights'):
        print("[DEBUG] flights_worker: Starting")
    while True:
        start_time = time.time()
        try:
            forced = getattr(flight_tracker, '_force_refresh', False)
            if forced:
                flight_tracker._force_refresh = False
                if TestMode.is_enabled('flights'):
                    print("[DEBUG] flights_worker: Force refresh triggered")

            with data_lock:
                mode = state['mode']

            did_fetch = False
            
            # 1. Airport Data: Fetch if in flights mode or forced
            if mode == 'flights' or forced:
                if flight_tracker.airport_code_iata:
                    if forced or time.time() - flight_tracker.last_airport_fetch >= 30:
                        flight_tracker.fetch_airport_activity()
                        flight_tracker.last_airport_fetch = time.time()
                        did_fetch = True

            # 2. Visitor Tracking: Fetch if ID exists (Persistent) or mode is explicitly flight_tracker
            # This ensures we keep repolling even if mode is turned 'off' (switched to sports)
            if flight_tracker.track_flight_id:
                if forced or time.time() - flight_tracker.last_visitor_fetch >= 30:
                    flight_tracker.fetch_visitor_tracking()
                    flight_tracker.last_visitor_fetch = time.time()
                    did_fetch = True

            if did_fetch or forced:
                try: fetcher.update_current_games()
                except: pass
        except Exception as e:
            print(f"Flight worker error: {e}")

        execution_time = time.time() - start_time
        flight_tracker.wake_event.wait(timeout=max(0, 5 - execution_time))
        flight_tracker.wake_event.clear()


class PoopFetecher:
    """Lightweight connection registry for PoopTracker app clients."""

    def __init__(self):
        self._lock = threading.Lock()
        self._clients = {}
        self._entries = []
        self._last_prune_ts = 0
        self._load_state()

    def _load_state(self):
        if not os.path.exists(POOP_TRACKER_STATE_FILE):
            return
        try:
            with open(POOP_TRACKER_STATE_FILE, 'r', encoding='utf-8') as f:
                raw = json.load(f)
            self._clients = raw.get('clients', {}) if isinstance(raw.get('clients'), dict) else {}
            self._entries = raw.get('entries', []) if isinstance(raw.get('entries'), list) else []
        except Exception as e:
            print(f"Poop state load error: {e}")

    def _save_state(self):
        try:
            payload = {
                'clients': self._clients,
                'entries': self._entries,
            }
            temp_file = f"{POOP_TRACKER_STATE_FILE}.tmp"
            with open(temp_file, 'w', encoding='utf-8') as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
            os.replace(temp_file, POOP_TRACKER_STATE_FILE)
        except Exception as e:
            print(f"Poop state save error: {e}")

    def _iso_now(self):
        return dt.now(timezone.utc).isoformat()

    def _parse_iso_utc(self, value):
        if not value:
            return None
        try:
            parsed = dt.fromisoformat(str(value).replace('Z', '+00:00'))
            if parsed.tzinfo is None:
                return parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc)
        except Exception:
            return None

    def _prune_entries_locked(self, retention_days=60):
        now = dt.now(timezone.utc)
        cutoff = now - timedelta(days=retention_days)
        before = len(self._entries)
        kept = []
        for entry in self._entries:
            ts = self._parse_iso_utc(entry.get('timestamp'))
            if ts is None:
                continue
            if ts >= cutoff:
                kept.append(entry)
        pruned = before - len(kept)
        if pruned > 0:
            self._entries = kept
            self._save_state()
            print(f"Poop entries pruned: {pruned} older than {retention_days} days")
        self._last_prune_ts = time.time()

    def _maybe_prune_entries_locked(self):
        if (time.time() - self._last_prune_ts) >= 6 * 3600:
            self._prune_entries_locked(retention_days=60)

    def register_client(self, client_id, name):
        safe_name = (name or '').strip() or 'PoopTracker User'
        with self._lock:
            self._maybe_prune_entries_locked()
            existing = self._clients.get(client_id, {})
            self._clients[client_id] = {
                'name': safe_name,
                'connected_at': existing.get('connected_at', self._iso_now()),
                'last_seen': self._iso_now()
            }
            self._save_state()
        return self._clients[client_id]

    def heartbeat(self, client_id):
        with self._lock:
            self._maybe_prune_entries_locked()
            if client_id in self._clients:
                self._clients[client_id]['last_seen'] = self._iso_now()
                self._save_state()
                return self._clients[client_id]
        return None

    def log_poop(self, client_id):
        with self._lock:
            self._maybe_prune_entries_locked()
            if client_id not in self._clients:
                return None
            entry = {
                'id': f"{client_id}-{uuid.uuid4()}",
                'user_id': client_id,
                'timestamp': self._iso_now(),
            }
            self._entries.append(entry)
            self._save_state()
            return entry

    def get_state(self):
        with self._lock:
            self._maybe_prune_entries_locked()
            users = [
                {'id': cid, 'name': data.get('name', 'PoopTracker User')}
                for cid, data in self._clients.items()
            ]
            users.sort(key=lambda u: (u.get('name') or '').lower())
            return {
                'users': users,
                'entries': list(self._entries),
            }

    def set_user_name(self, client_id, name):
        safe_name = (name or '').strip()
        if not safe_name:
            return False
        with self._lock:
            self._maybe_prune_entries_locked()
            if client_id not in self._clients:
                return False
            self._clients[client_id]['name'] = safe_name
            self._clients[client_id]['last_seen'] = self._iso_now()
            self._save_state()
            return True

    def remove_client(self, client_id, delete_entries=True):
        with self._lock:
            if client_id not in self._clients:
                return False
            del self._clients[client_id]
            if delete_entries:
                self._entries = [e for e in self._entries if e.get('user_id') != client_id]
            self._save_state()
            return True

    def add_entry(self, client_id, timestamp=None):
        with self._lock:
            self._maybe_prune_entries_locked()
            if client_id not in self._clients:
                self._clients[client_id] = {
                    'name': 'PoopTracker User',
                    'connected_at': self._iso_now(),
                    'last_seen': self._iso_now(),
                }
            entry = {
                'id': f"{client_id}-{uuid.uuid4()}",
                'user_id': client_id,
                'timestamp': timestamp or self._iso_now(),
            }
            self._entries.append(entry)
            self._save_state()
            return entry

    def delete_entry(self, entry_id):
        with self._lock:
            self._maybe_prune_entries_locked()
            before = len(self._entries)
            self._entries = [e for e in self._entries if e.get('id') != entry_id]
            deleted = len(self._entries) < before
            if deleted:
                self._save_state()
            return deleted

    def set_user_entry_count(self, client_id, target_count):
        with self._lock:
            self._maybe_prune_entries_locked()
            if client_id not in self._clients:
                return False, 0

            target = max(0, int(target_count))
            user_entries = [e for e in self._entries if e.get('user_id') == client_id]
            other_entries = [e for e in self._entries if e.get('user_id') != client_id]

            if target < len(user_entries):
                user_entries = sorted(
                    user_entries,
                    key=lambda e: self._parse_iso_utc(e.get('timestamp')) or dt.min.replace(tzinfo=timezone.utc),
                    reverse=True,
                )[:target]
            elif target > len(user_entries):
                to_add = target - len(user_entries)
                now = dt.now(timezone.utc)
                for i in range(to_add):
                    user_entries.append({
                        'id': f"{client_id}-{uuid.uuid4()}",
                        'user_id': client_id,
                        'timestamp': (now - timedelta(seconds=(to_add - i))).isoformat(),
                    })

            self._entries = other_entries + user_entries
            self._entries.sort(key=lambda e: self._parse_iso_utc(e.get('timestamp')) or dt.min.replace(tzinfo=timezone.utc))
            self._save_state()
            return True, len(user_entries)

    def get_mode_object(self):
        with self._lock:
            connected_count = len(self._clients)
        return {
            'type': 'poop_fetcher',
            'sport': 'poop_fetcher',
            'id': 'poop_fetcher_status',
            'home_abbr': 'POOP',
            'away_abbr': str(connected_count),
            'status': f'{connected_count} CONNECTED',
            'is_shown': True
        }


PoopFetcher = PoopFetecher
poop_fetcher = PoopFetecher()

# ── Section L: Flask Routes ──
app = Flask(__name__)
CORS(app)
app.secret_key = os.getenv('POOP_ADMIN_SESSION_SECRET') or os.getenv('FLASK_SECRET_KEY') or uuid.uuid4().hex
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'


def _poop_admin_authorized():
    if bool(session.get('poop_admin_ok')):
        return True
    # Basic fallback: if session signing is unstable across workers/restarts,
    # allow a simple cookie gate for this non-sensitive admin dashboard.
    return request.cookies.get('poop_admin_basic') == '1'


def _poop_admin_guard():
    if _poop_admin_authorized():
        return None
    return jsonify({"success": False, "message": "Unauthorized"}), 401


@app.route('/api/poop/health', methods=['GET'])
def poop_health():
    return jsonify({"success": True, "message": "PoopTracker server is ready"})


@app.route('/api/poop/register', methods=['POST'])
def poop_register():
    try:
        payload = request.json or {}
        name = payload.get('name', '')
        client_id = request.headers.get('X-Client-ID') or str(uuid.uuid4())
        rec = poop_fetcher.register_client(client_id, name)
        return jsonify({
            "success": True,
            "client_id": client_id,
            "name": rec.get('name', 'PoopTracker User')
        })
    except Exception as e:
        print(f"Poop register error: {e}")
        return jsonify({"success": False, "message": "Server error"}), 500


@app.route('/api/poop/state', methods=['GET'])
def poop_state():
    try:
        state = poop_fetcher.get_state()
        return jsonify({
            "success": True,
            "users": state.get('users', []),
            "entries": state.get('entries', []),
        })
    except Exception as e:
        print(f"Poop state error: {e}")
        return jsonify({"success": False, "message": "Server error"}), 500


@app.route('/api/poop/log', methods=['POST'])
def poop_log():
    try:
        client_id = request.headers.get('X-Client-ID', '').strip()
        if not client_id:
            return jsonify({"success": False, "message": "Missing client ID"}), 400

        entry = poop_fetcher.log_poop(client_id)
        if entry is None:
            return jsonify({"success": False, "message": "Client not registered"}), 404
        return jsonify({"success": True, "entry": entry})
    except Exception as e:
        print(f"Poop log error: {e}")
        return jsonify({"success": False, "message": "Server error"}), 500


@app.route('/poop/admin', methods=['GET'])
def poop_admin_dashboard():
    authed = _poop_admin_authorized()
    status = request.args.get('status', '').strip()

    if not authed:
        msg = ""
        if status == 'bad_password':
            msg = '<p class="bad">Invalid password.</p>'
        html = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Poop Admin</title>
  <style>
    body {{ margin:0; font-family: ui-sans-serif, system-ui, sans-serif; background:#0f172a; color:#e5e7eb; }}
    .wrap {{ max-width: 760px; margin: 0 auto; padding: 20px; }}
    .card {{ background:#111827; border:1px solid #334155; border-radius: 14px; padding: 16px; }}
    input, button {{ border-radius: 10px; border:1px solid #334155; background:#0b1220; color:#e5e7eb; padding:10px 12px; }}
    .row {{ display:flex; gap:8px; align-items:center; }}
    .bad {{ color:#ef4444; }}
  </style>
</head>
<body>
  <div class="wrap">
    <h1>Poop Admin Dashboard</h1>
    <div class="card">
      <h2>Login</h2>
      <form class="row" method="POST" action="/poop/admin/login">
        <input name="password" type="password" placeholder="Password" required />
        <button type="submit">Sign In</button>
      </form>
      {msg}
    </div>
  </div>
</body></html>"""
        return html, 200, {'Content-Type': 'text/html; charset=utf-8'}

    state = poop_fetcher.get_state()
    users = state.get('users', [])
    entries = sorted(state.get('entries', []), key=lambda e: str(e.get('timestamp', '')), reverse=True)
    count_by_user = {}
    for e in entries:
        uid = str(e.get('user_id', ''))
        count_by_user[uid] = count_by_user.get(uid, 0) + 1

    users_rows = []
    for u in users:
        uid = escape(str(u.get('id', '')))
        uname = escape(str(u.get('name', 'PoopTracker User')))
        current_count = count_by_user.get(str(u.get('id', '')), 0)
        users_rows.append(
            f"<tr><td>{uid}</td><td><form method='POST' action='/poop/admin/user' class='row'>"
            f"<input type='hidden' name='client_id' value='{uid}' />"
            f"<input name='name' value='{uname}' required />"
            f"<button type='submit'>Save</button></form></td>"
            f"<td>{current_count}</td><td><form method='POST' action='/poop/admin/user/count' class='row'>"
            f"<input type='hidden' name='client_id' value='{uid}' />"
            f"<input name='count' type='number' min='0' value='{current_count}' required style='width:100px' />"
            f"<button type='submit'>Set</button></form></td>"
            f"<td><form method='POST' action='/poop/admin/user/delete' "
            f"onsubmit=\"return confirm('Remove {uname} and all their entries?')\">"
            f"<input type='hidden' name='client_id' value='{uid}' />"
            f"<button type='submit' style='color:#ef4444'>Remove</button></form></td></tr>"
        )

    user_options = ''.join(
        f"<option value='{escape(str(u.get('id', '')))}'>{escape(str(u.get('name', 'PoopTracker User')))}</option>"
        for u in users
    )

    entry_rows = []
    for e in entries:
        eid = escape(str(e.get('id', '')))
        user_id = escape(str(e.get('user_id', '')))
        ts = escape(str(e.get('timestamp', '')))
        entry_rows.append(
            f"<tr><td>{user_id}</td><td>{ts}</td><td>{eid}</td><td>"
            f"<form method='POST' action='/poop/admin/entry/delete'>"
            f"<input type='hidden' name='entry_id' value='{eid}' />"
            f"<button type='submit'>Delete</button></form></td></tr>"
        )

    html = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Poop Admin</title>
  <style>
    body {{ margin:0; font-family: ui-sans-serif, system-ui, sans-serif; background:#0f172a; color:#e5e7eb; }}
    .wrap {{ max-width: 1080px; margin: 0 auto; padding: 20px; }}
    .card {{ background:#111827; border:1px solid #334155; border-radius: 14px; padding: 16px; margin-bottom: 14px; }}
    h1,h2 {{ margin:0 0 10px; }}
    input, select, button {{ border-radius: 10px; border:1px solid #334155; background:#0b1220; color:#e5e7eb; padding:10px 12px; }}
    .row {{ display:flex; gap:8px; align-items:center; flex-wrap:wrap; }}
    table {{ width:100%; border-collapse: collapse; }}
    th, td {{ text-align:left; padding:8px; border-bottom:1px solid #334155; font-size: 14px; vertical-align: top; }}
  </style>
</head>
<body>
  <div class="wrap">
    <div class="row" style="justify-content:space-between">
      <h1>Poop Admin Dashboard</h1>
      <form method="POST" action="/poop/admin/logout"><button type="submit">Logout</button></form>
    </div>

    <div class="card">
      <h2>Add Entry</h2>
      <form class="row" method="POST" action="/poop/admin/entry/add">
        <select name="client_id" required>{user_options}</select>
        <button type="submit">Add Poop</button>
      </form>
    </div>

    <div class="card">
      <h2>Users</h2>
            <table><tr><th>ID</th><th>Name</th><th>Poops</th><th>Set Count</th><th>Remove</th></tr>{''.join(users_rows)}</table>
    </div>

    <div class="card">
      <h2>Entries</h2>
      <table><tr><th>User</th><th>Timestamp</th><th>ID</th><th>Action</th></tr>{''.join(entry_rows)}</table>
    </div>
  </div>
</body></html>"""
    return html, 200, {'Content-Type': 'text/html; charset=utf-8'}


@app.route('/api/poop/admin/login', methods=['POST'])
def poop_admin_login():
    try:
        payload = request.get_json(silent=True) or request.form or {}
        supplied = str(payload.get('password') or '').strip()
        default_password = _default_poop_admin_password()
        if hmac.compare_digest(supplied, POOP_ADMIN_PASSWORD) or hmac.compare_digest(supplied, default_password):
            session['poop_admin_ok'] = True
            response = make_response(jsonify({"success": True}))
            response.set_cookie(
                'poop_admin_basic',
                '1',
                max_age=60 * 60 * 24 * 30,
                httponly=True,
                samesite='Lax',
            )
            return response
        return jsonify({"success": False, "message": "Invalid password"}), 401
    except Exception as e:
        print(f"Poop admin login error: {e}")
        return jsonify({"success": False, "message": "Server error"}), 500


@app.route('/poop/admin/login', methods=['POST'])
def poop_admin_login_form():
    supplied = str(request.form.get('password') or '').strip()
    default_password = _default_poop_admin_password()
    if hmac.compare_digest(supplied, POOP_ADMIN_PASSWORD) or hmac.compare_digest(supplied, default_password):
        session['poop_admin_ok'] = True
        response = make_response(redirect('/poop/admin'))
        response.set_cookie(
            'poop_admin_basic',
            '1',
            max_age=60 * 60 * 24 * 30,
            httponly=True,
            samesite='Lax',
        )
        return response
    return redirect('/poop/admin?status=bad_password')


@app.route('/poop/admin/logout', methods=['POST'])
def poop_admin_logout_form():
    session.pop('poop_admin_ok', None)
    response = make_response(redirect('/poop/admin'))
    response.delete_cookie('poop_admin_basic')
    return response


@app.route('/poop/admin/user', methods=['POST'])
def poop_admin_user_update_form():
    if not _poop_admin_authorized():
        return redirect('/poop/admin')
    client_id = str(request.form.get('client_id') or '').strip()
    name = str(request.form.get('name') or '').strip()
    if client_id and name:
        poop_fetcher.set_user_name(client_id, name)
    return redirect('/poop/admin')


@app.route('/poop/admin/user/count', methods=['POST'])
def poop_admin_user_count_form():
    if not _poop_admin_authorized():
        return redirect('/poop/admin')
    client_id = str(request.form.get('client_id') or '').strip()
    count_raw = str(request.form.get('count') or '').strip()
    try:
        target_count = int(count_raw)
    except Exception:
        target_count = 0
    if client_id:
        poop_fetcher.set_user_entry_count(client_id, target_count)
    return redirect('/poop/admin')


@app.route('/poop/admin/user/delete', methods=['POST'])
def poop_admin_user_delete_form():
    if not _poop_admin_authorized():
        return redirect('/poop/admin')
    client_id = str(request.form.get('client_id') or '').strip()
    if client_id:
        poop_fetcher.remove_client(client_id, delete_entries=True)
    return redirect('/poop/admin')


@app.route('/poop/admin/entry/add', methods=['POST'])
def poop_admin_entry_add_form():
    if not _poop_admin_authorized():
        return redirect('/poop/admin')
    client_id = str(request.form.get('client_id') or '').strip()
    if client_id:
        poop_fetcher.add_entry(client_id)
    return redirect('/poop/admin')


@app.route('/poop/admin/entry/delete', methods=['POST'])
def poop_admin_entry_delete_form():
    if not _poop_admin_authorized():
        return redirect('/poop/admin')
    entry_id = str(request.form.get('entry_id') or '').strip()
    if entry_id:
        poop_fetcher.delete_entry(entry_id)
    return redirect('/poop/admin')


@app.route('/api/poop/admin/logout', methods=['POST'])
def poop_admin_logout():
    session.pop('poop_admin_ok', None)
    response = make_response(jsonify({"success": True}))
    response.delete_cookie('poop_admin_basic')
    return response


@app.route('/api/poop/admin/state', methods=['GET'])
def poop_admin_state():
    auth_err = _poop_admin_guard()
    if auth_err:
        return auth_err
    try:
        state = poop_fetcher.get_state()
        return jsonify({
            "success": True,
            "users": state.get('users', []),
            "entries": state.get('entries', []),
        })
    except Exception as e:
        print(f"Poop admin state error: {e}")
        return jsonify({"success": False, "message": "Server error"}), 500


@app.route('/api/poop/admin/user', methods=['POST'])
def poop_admin_user_update():
    auth_err = _poop_admin_guard()
    if auth_err:
        return auth_err
    try:
        payload = request.json or {}
        client_id = str(payload.get('client_id') or '').strip()
        name = str(payload.get('name') or '').strip()
        if not client_id or not name:
            return jsonify({"success": False, "message": "Missing fields"}), 400

        ok = poop_fetcher.set_user_name(client_id, name)
        if not ok:
            return jsonify({"success": False, "message": "User not found"}), 404
        return jsonify({"success": True})
    except Exception as e:
        print(f"Poop admin user update error: {e}")
        return jsonify({"success": False, "message": "Server error"}), 500


@app.route('/api/poop/admin/user/count', methods=['POST'])
def poop_admin_user_count():
    auth_err = _poop_admin_guard()
    if auth_err:
        return auth_err
    try:
        payload = request.json or {}
        client_id = str(payload.get('client_id') or '').strip()
        count_value = payload.get('count')
        if not client_id or count_value is None:
            return jsonify({"success": False, "message": "Missing fields"}), 400

        ok, new_count = poop_fetcher.set_user_entry_count(client_id, int(count_value))
        if not ok:
            return jsonify({"success": False, "message": "User not found"}), 404
        return jsonify({"success": True, "count": new_count})
    except Exception as e:
        print(f"Poop admin user count error: {e}")
        return jsonify({"success": False, "message": "Server error"}), 500


@app.route('/api/poop/admin/user/delete', methods=['POST'])
def poop_admin_user_delete():
    auth_err = _poop_admin_guard()
    if auth_err:
        return auth_err
    try:
        payload = request.json or {}
        client_id = str(payload.get('client_id') or '').strip()
        if not client_id:
            return jsonify({"success": False, "message": "Missing client_id"}), 400
        ok = poop_fetcher.remove_client(client_id, delete_entries=True)
        if not ok:
            return jsonify({"success": False, "message": "User not found"}), 404
        return jsonify({"success": True})
    except Exception as e:
        print(f"Poop admin user delete error: {e}")
        return jsonify({"success": False, "message": "Server error"}), 500


@app.route('/api/poop/admin/entry/add', methods=['POST'])
def poop_admin_entry_add():
    auth_err = _poop_admin_guard()
    if auth_err:
        return auth_err
    try:
        payload = request.json or {}
        client_id = str(payload.get('client_id') or '').strip()
        if not client_id:
            return jsonify({"success": False, "message": "Missing client_id"}), 400

        entry = poop_fetcher.add_entry(client_id)
        return jsonify({"success": True, "entry": entry})
    except Exception as e:
        print(f"Poop admin add entry error: {e}")
        return jsonify({"success": False, "message": "Server error"}), 500


@app.route('/api/poop/admin/entry/delete', methods=['POST'])
def poop_admin_entry_delete():
    auth_err = _poop_admin_guard()
    if auth_err:
        return auth_err
    try:
        payload = request.json or {}
        entry_id = str(payload.get('entry_id') or '').strip()
        if not entry_id:
            return jsonify({"success": False, "message": "Missing entry_id"}), 400

        ok = poop_fetcher.delete_entry(entry_id)
        if not ok:
            return jsonify({"success": False, "message": "Entry not found"}), 404
        return jsonify({"success": True})
    except Exception as e:
        print(f"Poop admin delete entry error: {e}")
        return jsonify({"success": False, "message": "Server error"}), 500

@app.route('/api/config', methods=['POST'])
def api_config():
    try:
        new_data = request.json
        if not isinstance(new_data, dict): return jsonify({"error": "Invalid payload"}), 400

        # Migrate legacy modes to canonical mode names
        incoming_submode = new_data.get('flight_submode')

        # Pin normalization (ticker-scoped): always keep a single pinned game.
        normalized_pin = None
        normalized_pin_list = None
        if 'pinned_game' in new_data or 'pinned_games' in new_data:
            normalized_pin, normalized_pin_list = _normalize_single_pin(
                pinned_game=new_data.get('pinned_game'),
                pinned_games=new_data.get('pinned_games')
            )

        if 'mode' in new_data:
            new_data['mode'] = MODE_MIGRATIONS.get(new_data['mode'], new_data['mode'])
            # Submode compatibility: allow both directions
            if incoming_submode == 'track':
                new_data['mode'] = 'flight_tracker'
            elif incoming_submode == 'airport' and new_data['mode'] == 'flight_tracker':
                new_data['mode'] = 'flights'
            # Reject any mode that isn't valid; fall back to sports
            if new_data['mode'] not in VALID_MODES:
                new_data['mode'] = 'sports'
        elif incoming_submode in ('track', 'airport'):
            new_data['mode'] = 'flight_tracker' if incoming_submode == 'track' else 'flights'
        # Drop flight_submode — no longer a valid key
        new_data.pop('flight_submode', None)
        
        # 1. Determine which ticker is being targeted
        target_id = new_data.get('ticker_id') or request.args.get('id')
        
        cid = request.headers.get('X-Client-ID')
        
        # If we have a CID, try to find the associated ticker
        if not target_id and cid:
            for tid, t_data in tickers.items():
                if cid in t_data.get('clients', []):
                    target_id = tid
                    break
        
        # Fallback for single-ticker setups
        if not target_id and len(tickers) == 1: 
            target_id = list(tickers.keys())[0]

        if new_data.get('mode') == 'poop_fetcher' and not _is_poop_fetcher_mode_allowed(target_id):
            new_data['mode'] = 'sports'

        # If a specific ticker is targeted but doesn't exist yet, create it so
        # mode and other settings are applied locally instead of falling back to
        # global state.
        if target_id and target_id not in tickers:
            seed_client = cid or target_id
            tickers[target_id] = {
                "name": "Ticker",
                "settings": DEFAULT_TICKER_SETTINGS.copy(),
                "my_teams": None,
                "clients": [seed_client],
                "paired": True,
                "pairing_code": generate_pairing_code(),
                "last_seen": time.time()
            }
            tickers[target_id]['settings']['mode'] = state.get('mode', 'sports')
            save_specific_ticker(target_id)

        # ================= SECURITY CHECK START =================
        if target_id and target_id in tickers:
            rec = tickers[target_id]
            
            # If the client ID is not in the list, block them. 
            if cid not in rec.get('clients', []):
                print(f"⛔ Blocked unauthorized config change from {cid}")
                return jsonify({"error": "Unauthorized: Device not paired"}), 403
        # ================== SECURITY CHECK END ==================

        with data_lock:
            # Update Weather (Global)
            new_city = new_data.get('weather_city')
            if new_city: 
                fetcher.weather.update_config(city=new_city, lat=new_data.get('weather_lat'), lon=new_data.get('weather_lon'))

            # Update Flight Tracker (Global)
            if flight_tracker:
                flight_changed = False
                if 'track_flight_id' in new_data:
                    flight_tracker.track_flight_id = new_data.get('track_flight_id', '')
                    flight_changed = True
                if 'track_guest_name' in new_data:
                    flight_tracker.track_guest_name = new_data.get('track_guest_name', '')
                
                # Auto-fill airport information when any airport code is provided
                airport_code_input = None
                if 'airport_code_iata' in new_data:
                    airport_code_input = new_data.get('airport_code_iata', '').strip()
                elif 'airport_code_icao' in new_data:
                    airport_code_input = new_data.get('airport_code_icao', '').strip()
                
                if airport_code_input:
                    # Perform airport lookup
                    airport_info = lookup_and_auto_fill_airport(airport_code_input)
                    
                    if airport_info['iata']:  # Only update if airport was found
                        flight_tracker.airport_code_iata = airport_info['iata']
                        flight_tracker.airport_code_icao = airport_info['icao']
                        flight_tracker.airport_name = airport_info['name']
                        print(f"✅ Airport auto-fill: {airport_info['iata']} ({airport_info['icao']}) - {airport_info['name']}")
                        flight_changed = True
                    else:
                        print(f"⚠️ Airport code '{airport_code_input}' not found in database")
                        # Clear airport info if code is invalid
                        flight_tracker.airport_code_iata = ''
                        flight_tracker.airport_code_icao = ''
                        flight_tracker.airport_name = ''
                        flight_changed = True
                elif 'airport_code_icao' in new_data:
                    flight_tracker.airport_code_icao = new_data.get('airport_code_icao', '')
                    flight_changed = True
                if 'airport_name' in new_data and not airport_code_input:
                    flight_tracker.airport_name = new_data.get('airport_name', '')
                if flight_changed:
                    # Clear stale data immediately so old airport/flight info doesn't linger
                    with flight_tracker.lock:
                        flight_tracker.airport_arrivals = []
                        flight_tracker.airport_departures = []
                        flight_tracker.airport_weather = {"temp": "--", "cond": "LOADING"}
                        if not flight_tracker.track_flight_id:
                            flight_tracker.visitor_flight = None
                    # Signal the flights_worker to fetch immediately (no 30s wait)
                    flight_tracker.force_update()
            
            allowed_keys = {
                'active_sports', 'mode', 'layout_mode', 'my_teams', 'debug_mode', 'custom_date',
                'weather_city', 'weather_lat', 'weather_lon', 'utc_offset',
                'timezone_name',
                'track_flight_id', 'track_guest_name', 'airport_code_icao',
                'airport_code_iata', 'airport_name',
                'test_mode', 'test_spotify', 'test_stocks', 'test_sports_date', 'test_flights',
                'pinned_game', 'pinned_games'
            }
            
            for k, v in new_data.items():
                if k not in allowed_keys: continue
                
                # HANDLE TEAMS
                if k == 'my_teams':
                    if v is None or (isinstance(v, list) and not v):
                        # null or empty list = reset ticker to use global fallback (always [])
                        if target_id and target_id in tickers:
                            tickers[target_id]['my_teams'] = None
                            tickers[target_id].pop('my_teams_set', None)
                        continue
                    elif isinstance(v, list):
                        cleaned = []
                        seen = set()
                        for e in v:
                            if e:
                                entry = str(e).strip()
                                if ':' in entry:
                                    # Already prefixed: normalize to lowercase_league:UPPER_ABBR
                                    lg, ab = entry.split(':', 1)
                                    raw = f"{lg.lower()}:{ab.upper()}"
                                else:
                                    # Plain abbr: look up league and normalize
                                    ab = entry.upper()
                                    matches = [lg for lg, idx in fetcher._teams_abbr_index.items() if ab in idx]
                                    raw = f"{matches[0]}:{ab}" if len(matches) == 1 else ab
                                if raw not in seen:
                                    seen.add(raw)
                                    cleaned.append(raw)
                        if target_id and target_id in tickers:
                            tickers[target_id]['my_teams'] = cleaned if cleaned else None
                            tickers[target_id].pop('my_teams_set', None)
                        # else: global my_teams always stays [] — ignore untargeted team updates
                        continue

                # HANDLE ACTIVE SPORTS — only accept keys that exist in LEAGUE_OPTIONS
                if k == 'active_sports' and isinstance(v, dict):
                    for ak, av in v.items():
                        if ak in _VALID_LEAGUE_IDS:
                            state['active_sports'][ak] = av
                    continue
                
                # HANDLE MODE — per-ticker isolation
                if k == 'mode':
                    if target_id and target_id in tickers:
                        # Targeted request: only update this ticker's mode
                        tickers[target_id]['settings']['mode'] = v
                    else:
                        # No specific target: update the global default
                        state['mode'] = v
                    continue

                # HANDLE PINS — already normalized above; skip raw assignment
                if k in ('pinned_game', 'pinned_games'):
                    if target_id and target_id in tickers:
                        tickers[target_id]['settings']['pinned_game'] = normalized_pin or ''
                        tickers[target_id]['settings']['pinned_games'] = list(normalized_pin_list or [])
                    continue

                # HANDLE ALL OTHER SETTINGS
                if v is not None: state[k] = v

                # SYNC TO TICKER SETTINGS (non-mode keys only)
                if target_id and target_id in tickers:
                    if k in tickers[target_id]['settings']:
                        tickers[target_id]['settings'][k] = v
            
            # Sync auto-filled airport info back to state dictionary
            # (This ensures /api/state returns the validated airport data)
            if flight_tracker:
                state['airport_code_iata'] = flight_tracker.airport_code_iata
                state['airport_code_icao'] = flight_tracker.airport_code_icao
                state['airport_name'] = flight_tracker.airport_name
                state['track_flight_id'] = flight_tracker.track_flight_id
                state['track_guest_name'] = flight_tracker.track_guest_name

                # Also sync to ticker-specific settings if a ticker is targeted
                if target_id and target_id in tickers:
                    tickers[target_id]['settings']['airport_code_iata'] = flight_tracker.airport_code_iata
                    tickers[target_id]['settings']['airport_code_icao'] = flight_tracker.airport_code_icao
                    tickers[target_id]['settings']['airport_name'] = flight_tracker.airport_name
                    tickers[target_id]['settings']['track_flight_id'] = flight_tracker.track_flight_id
                    tickers[target_id]['settings']['track_guest_name'] = flight_tracker.track_guest_name

            # Force airline_filter to always be empty (support all airlines)
            state['airline_filter'] = ''

        # Sync console verbosity with debug_mode
        if tee_instance is not None:
            Tee.verbose_debug = state.get('debug_mode', False)

        # Sync TestMode whenever any test_* or debug key changes
        if any(k.startswith('test_') or k in ('debug_mode', 'custom_date') for k in new_data):
            TestMode.configure(
                enabled=state.get('test_mode', False),
                spotify=state.get('test_spotify', False),
                stocks=state.get('test_stocks', False),
                sports_date=state.get('test_sports_date', False),
                flights=state.get('test_flights', False),
                custom_date=state.get('custom_date'),
            )

        # For flights modes, wake the background worker immediately so data is
        # ready as soon as possible (otherwise it can take up to 30 s to fetch).
        # Check effective mode: use targeted ticker's mode if set, else global.
        new_mode = (tickers[target_id]['settings'].get('mode') if (target_id and target_id in tickers)
                    else None) or state.get('mode', '')
        if new_mode in ('flights', 'flight_tracker') and flight_tracker:
            flight_tracker.force_update()

        # Rebuild buffer in background — sports fetches can take 30 s+, don't block the response
        threading.Thread(target=fetcher.update_current_games, daemon=True).start()

        if target_id:
            save_specific_ticker(target_id)
            # Also persist global config for flight/weather settings that live globally
            save_global_config()
        else:
            save_global_config()
        
        current_teams = tickers[target_id].get('my_teams', []) if (target_id and target_id in tickers) else state['my_teams']
        
        resolved = {}
        if flight_tracker:
            resolved = {
                "airport_code_iata": flight_tracker.airport_code_iata,
                "airport_code_icao": flight_tracker.airport_code_icao,
                "airport_name":      flight_tracker.airport_name,
            }
        return jsonify({"status": "ok", "saved_teams": current_teams, "ticker_id": target_id, **resolved})
        
    except Exception as e:
        print(f"Config Error: {e}") 
        return jsonify({"error": "Failed"}), 500

@app.route('/leagues', methods=['GET'])
def get_league_options():
    ticker_id = request.args.get('id')
    if not ticker_id:
        cid = request.headers.get('X-Client-ID')
        if cid:
            for tid, t_data in tickers.items():
                if cid in t_data.get('clients', []):
                    ticker_id = tid
                    break
    if not ticker_id and len(tickers) == 1:
        ticker_id = list(tickers.keys())[0]

    poop_fetcher_allowed = _is_poop_fetcher_mode_allowed(ticker_id)

    league_meta = []
    for item in LEAGUE_OPTIONS:
        if item['id'] == 'poop_fetcher' and not poop_fetcher_allowed:
            continue
        league_meta.append({
            'id': item['id'],
            'label': item['label'],
            'type': item['type'],
            'enabled': state['active_sports'].get(item['id'], False)
        })
    # Add Music Option explicitly if not in list
    if not any(x['id'] == 'music' for x in league_meta):
        league_meta.append({'id': 'music', 'label': 'Music', 'type': 'util', 'enabled': state['active_sports'].get('music', False)})
        
    return jsonify(league_meta)

@app.route('/data', methods=['GET'])
def get_ticker_data():
    ticker_id = request.args.get('id')
    
    # 1. Resolve Ticker ID
    if not ticker_id and len(tickers) == 1: 
        ticker_id = list(tickers.keys())[0]
    
    if not ticker_id:
        return jsonify({"status": "ok", "content": {"sports": []}})

    # Auto-create ticker if ID is unknown
    if ticker_id not in tickers:
        tickers[ticker_id] = {
            "name": "Ticker",
            "settings": DEFAULT_TICKER_SETTINGS.copy(),
            "my_teams": None,
            # Hardware device self-authorizes: its device_id is both the ticker key
            # and its client identity, so add it to clients automatically.
            "clients": [ticker_id],
            "paired": True,
            "pairing_code": generate_pairing_code(),
            "last_seen": time.time()
        }
        # Sync new ticker to global state immediately
        tickers[ticker_id]['settings']['mode'] = state.get('mode', 'sports')
        save_specific_ticker(ticker_id)

    rec = tickers[ticker_id]
    rec['last_seen'] = time.time()

    # Auto-detect ticker timezone from its public IP (ip-api.com) and persist.
    _maybe_update_ticker_timezone_from_request(ticker_id, request)
    
    # 2. Pairing Check
    if not rec.get('clients') or not rec.get('paired'):
        if not rec.get('pairing_code'):
            rec['pairing_code'] = generate_pairing_code()
            save_specific_ticker(ticker_id)
        return jsonify({ "status": "pairing", "code": rec['pairing_code'], "ticker_id": ticker_id })

    t_settings = rec['settings']

    # Per-ticker mode: use the ticker's own mode setting, fall back to global
    current_mode = t_settings.get('mode') or state.get('mode', 'sports')
    current_mode = MODE_MIGRATIONS.get(current_mode, current_mode)
    sports_mode_family = ('sports', 'live', 'my_teams', 'sports_full')
    
    # --- FORCE SPORTS_FULL IF TICKER HAS A PIN ---
    t_pinned_game = str(rec.get('settings', {}).get('pinned_game', '')).strip()
    t_pins = rec.get('settings', {}).get('pinned_games', [])
    has_pinned_game = bool(t_pinned_game) or (isinstance(t_pins, list) and any(str(p).strip() for p in t_pins))
    effective_pin = t_pinned_game if t_pinned_game else ''
    if not effective_pin and isinstance(t_pins, list):
        non_empty = [str(p).strip() for p in t_pins if str(p).strip()]
        if non_empty:
            effective_pin = non_empty[0]

    if has_pinned_game and current_mode in sports_mode_family:
        current_mode = 'sports_full'
    elif current_mode not in VALID_MODES:
        current_mode = state.get('mode', 'sports')

    if current_mode == 'poop_fetcher' and not _is_poop_fetcher_mode_allowed(ticker_id):
        current_mode = 'sports'

    # Sleep Mode: dim the display but still fetch real game data so it's
    # immediately available when the ticker wakes up (no stale-data bug).
    is_sleep = t_settings.get('brightness', 100) <= 0

    # 4. Content Fetching
    # Live delay only applies to sports content (history buffer only exists for sports)
    is_sports_mode = current_mode in sports_mode_family
    delay_seconds = (t_settings.get('live_delay_seconds', 0)
                     if (is_sports_mode and t_settings.get('live_delay_mode'))
                     else 0)
    if effective_pin and current_mode == 'sports_full':
        raw_games = fetcher.get_mode_snapshot('sports_full', delay_seconds)
        pin_id = str(effective_pin).split(':', 1)[-1]
        raw_games = [g for g in raw_games if str(g.get('id', '')) == pin_id]
    else:
        raw_games = fetcher.get_mode_snapshot(current_mode, delay_seconds)
    active_sports = state.get('active_sports', {})
    visible_items = []

    def _sport_for_data_mode(sport_name: str) -> str:
        sport_norm = str(sport_name or '').lower()
        return 'mlb' if sport_norm == 'wbc' else sport_norm

    # 5. Filter Buffer based on current_mode
    if current_mode == 'music':
        for g in raw_games:
            if g.get('type') == 'music':
                g['is_shown'] = True
                visible_items.append(g)
        
        # Fallback: If buffer is empty, fetch immediately
        if not visible_items:
            music_obj = fetcher.get_music_object()
            if music_obj: visible_items.append(music_obj)

    elif current_mode == 'my_teams':
        _ticker_teams = rec.get('my_teams')
        saved_teams = set(state.get('my_teams', []) if _ticker_teams is None else _ticker_teams)
        COLLISION_ABBRS = {'LV'}
        for g in raw_games:
            sport = _sport_for_data_mode(g.get('sport', ''))
            if not active_sports.get(sport, True): continue
            h_ab, a_ab = str(g.get('home_abbr', '')).upper(), str(g.get('away_abbr', '')).upper()
            in_home = f"{sport}:{h_ab}" in saved_teams or (h_ab in saved_teams and h_ab not in COLLISION_ABBRS)
            in_away = f"{sport}:{a_ab}" in saved_teams or (a_ab in saved_teams and a_ab not in COLLISION_ABBRS)
            if in_home or in_away:
                g_copy = g.copy()
                g_copy['sport'] = sport
                g_copy['is_shown'] = True
                visible_items.append(g_copy)

    elif current_mode == 'live':
        for g in raw_games:
            sport = _sport_for_data_mode(g.get('sport', ''))
            if not active_sports.get(sport, True): continue
            if g.get('state') in _ACTIVE_STATES:
                g_copy = g.copy()
                g_copy['sport'] = sport
                g_copy['is_shown'] = True
                visible_items.append(g_copy)

    elif current_mode == 'sports_full':
        # Pinned game override — show everything without active_sports filtering
        for g in raw_games:
            sport = _sport_for_data_mode(g.get('sport', ''))
            g_copy = g.copy()
            g_copy['sport'] = sport
            g_copy['is_shown'] = True
            visible_items.append(g_copy)

    elif current_mode == 'sports':
        for g in raw_games:
            sport = _sport_for_data_mode(g.get('sport', ''))
            if not active_sports.get(sport, True): continue
            if g.get('type') in ['music', 'clock', 'weather', 'stock_ticker', 'flight_visitor']:
                continue
            status_lower = str(g.get('status', '')).lower()
            if any(k in status_lower for k in ("postponed", "suspended", "canceled", "ppd")):
                continue
            g_copy = g.copy()
            g_copy['sport'] = sport
            g_copy['is_shown'] = True
            visible_items.append(g_copy)

    else:
        # Stocks, Weather, Clock, Flights
        for g in raw_games:
            g_type, g_sport = g.get('type', ''), g.get('sport', '')
            match = False
            if current_mode == 'stocks' and g_type == 'stock_ticker': match = True
            elif current_mode == 'weather' and g_type == 'weather': match = True
            elif current_mode == 'clock' and g_type == 'clock': match = True
            elif current_mode == 'flights' and g_sport == 'flight': match = True
            elif current_mode == 'flight_tracker' and g_type == 'flight_visitor': match = True
            elif current_mode == 'poop_fetcher' and g_type == 'poop_fetcher': match = True

            if match:
                g['is_shown'] = True
                visible_items.append(g)

    tz_name, tz_offset = _get_ticker_timezone_context(rec)
    _apply_timezone_to_game_times(visible_items, tz_name=tz_name, utc_offset=tz_offset)

    # 6. Final Response
    # Display-only override: if normal sports mode has exactly one item,
    # render it as full-bleed without persisting ticker/global mode changes.
    response_local_config = dict(t_settings)
    response_local_config['timezone_name'] = tz_name
    response_local_config['utc_offset'] = tz_offset
    effective_mode_for_response = current_mode
    if current_mode == 'sports' and len(visible_items) == 1:
        effective_mode_for_response = 'sports_full'
    response_local_config['mode'] = effective_mode_for_response

    # Report global config from global state only. Do not reflect per-ticker
    # pin overrides here, otherwise global_config.mode appears to change.
    g_config = { "mode": state.get('mode', 'sports') }
    if rec.get('reboot_requested'): g_config['reboot'] = True
    if rec.get('update_requested'): g_config['update'] = True
        
    return jsonify({
        "status": "sleep" if is_sleep else "ok",
        "version": SERVER_VERSION,
        "ticker_id": ticker_id,
        "global_config": g_config,
        "local_config": response_local_config,
        "content": { "sports": visible_items }
    })

@app.route('/api/spotify/now', methods=['GET'])
def api_spotify():
    data = spotify_fetcher.get_cached_state()
    # If playing, calculate real-time progress based on elapsed time since last poll
    if data.get('is_playing') and data.get('last_fetch_ts'):
        elapsed = time.time() - data['last_fetch_ts']
        data['progress'] = min(data['progress'] + elapsed, data.get('duration', 0))
    return jsonify(data)

@app.route('/api/airport/lookup', methods=['GET'])
def api_airport_lookup():
    """
    Lookup airport information by IATA or ICAO code.
    Query params: code=ABE or code=KABE
    Returns: {iata, icao, name}
    """
    try:
        code = request.args.get('code', '').strip()
        if not code:
            return jsonify({"error": "Please provide an airport code"}), 400
        
        airport_info = lookup_and_auto_fill_airport(code)
        
        if airport_info['iata']:
            return jsonify({
                "status": "found",
                "iata": airport_info['iata'],
                "icao": airport_info['icao'],
                "name": airport_info['name']
            })
        else:
            return jsonify({
                "status": "not_found",
                "message": f"Airport code '{code}' not found"
            }), 404
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/pair', methods=['POST'])
def pair_ticker():
    try:
        cid = request.headers.get('X-Client-ID')
        json_body = request.json or {}
        code = json_body.get('code')
        friendly_name = json_body.get('name', 'My Ticker')
        
        print(f"🔗 Pairing Attempt from Client: {cid} | Code: {code}")

        if not cid or not code:
            print("❌ Missing CID or Code")
            return jsonify({"success": False, "message": "Missing Data"}), 400
        
        input_code = str(code).strip()

        for uid, rec in tickers.items():
            known_code = str(rec.get('pairing_code', '')).strip()
            
            if known_code == input_code:
                if cid not in rec.get('clients', []):
                    rec['clients'].append(cid)
                
                rec['paired'] = True
                rec['name'] = friendly_name
                save_specific_ticker(uid)
                
                print(f"✅ Paired Successfully to Ticker: {uid}")
                return jsonify({"success": True, "ticker_id": uid})
        
        print(f"❌ Invalid Code. Input: {input_code}")
        return jsonify({"success": False, "message": "Invalid Pairing Code"}), 200

    except Exception as e:
        print(f"🔥 Pairing Server Error: {e}")
        return jsonify({"success": False, "message": "Server Logic Error"}), 500

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
        save_specific_ticker(tid)
        return jsonify({"success": True, "ticker_id": tid})
        
    return jsonify({"success": False}), 404

@app.route('/api/flight/debug', methods=['GET'])
def debug_flight_tracking():
    """Diagnostic endpoint to see what's happening with flight tracking"""
    if not flight_tracker:
        return jsonify({'error': 'Flight tracking not available'})
    
    # Force an immediate fetch
    try:
        flight_tracker.fetch_visitor_tracking()
    except Exception as e:
        return jsonify({'error': f'Fetch failed: {str(e)}'})
    
    # Get the current state
    with flight_tracker.lock:
        visitor_data = flight_tracker.visitor_flight.copy() if flight_tracker.visitor_flight else None
    
    return jsonify({
        'config': {
            'track_flight_id': flight_tracker.track_flight_id,
            'track_guest_name': flight_tracker.track_guest_name,
            'fr_api_available': flight_tracker.fr_api is not None
        },
        'visitor_flight': visitor_data,
        'last_fetch': {
            'visitor': flight_tracker.last_visitor_fetch,
            'time_since': time.time() - flight_tracker.last_visitor_fetch
        }
    })

@app.route('/register', methods=['POST'])
def register_ticker():
    """Register a new ticker and auto-pair the requesting client."""
    try:
        cid = request.headers.get('X-Client-ID')
        json_body = request.json or {}
        friendly_name = json_body.get('name', 'My Ticker')

        if not cid:
            return jsonify({"success": False, "message": "Missing X-Client-ID header"}), 400

        # Check if this client already owns a ticker — return it instead of creating a duplicate
        for tid, rec in tickers.items():
            if cid in rec.get('clients', []):
                print(f"🔁 Client {cid} already owns ticker {tid}, returning existing")
                return jsonify({"success": True, "ticker_id": tid})

        # Generate a unique ticker ID
        new_tid = str(uuid.uuid4())

        # Create the ticker record
        new_ticker = {
            "name": friendly_name,
            "settings": DEFAULT_TICKER_SETTINGS.copy(),
            "my_teams": None,
            "clients": [cid],
            "paired": True,
            "pairing_code": generate_pairing_code(),
            "last_seen": time.time()
        }
        # Copy default mode into settings
        new_ticker['settings']['mode'] = state.get('mode', 'sports')

        tickers[new_tid] = new_ticker
        save_specific_ticker(new_tid)

        print(f"✅ Registered new ticker: {new_tid} (client: {cid})")
        return jsonify({"success": True, "ticker_id": new_tid})

    except Exception as e:
        print(f"🔥 Register Error: {e}")
        return jsonify({"success": False, "message": "Server error"}), 500

@app.route('/ticker/<tid>/unpair', methods=['POST'])
def unpair(tid):
    cid = request.headers.get('X-Client-ID')
    if tid in tickers and cid in tickers[tid]['clients']:
        tickers[tid]['clients'].remove(cid)
        if not tickers[tid]['clients']: tickers[tid]['paired'] = False; tickers[tid]['pairing_code'] = generate_pairing_code()
        save_specific_ticker(tid)
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

    cid = request.headers.get('X-Client-ID')
    rec = tickers[tid]
    
    if not cid or cid not in rec.get('clients', []):
        print(f"⛔ Blocked unauthorized settings change from {cid}")
        return jsonify({"error": "Unauthorized: Device not paired"}), 403

    data = request.json
    rec['settings'].update(data)
    
    # --- FIX: Sync Mode (per-ticker only — do NOT touch global state['mode']) ---
    if 'mode' in data:
        new_mode = data['mode']
        new_mode = MODE_MIGRATIONS.get(new_mode, new_mode)
        if new_mode not in VALID_MODES:
            new_mode = 'sports'
        if new_mode == 'poop_fetcher' and not _is_poop_fetcher_mode_allowed(tid):
            new_mode = 'sports'

        with data_lock:
            # Only update this ticker's mode setting; other tickers keep theirs
            rec['settings']['mode'] = new_mode

        # Trigger immediate buffer rebuild in the background so this request
        # returns quickly (sports refresh can take >5s).
        threading.Thread(target=fetcher.update_current_games, daemon=True).start()

    save_specific_ticker(tid)
    
    print(f"✅ Updated Settings for {tid}: {data}") 
    return jsonify({"success": True})

@app.route('/api/state', methods=['GET'])
def api_state():
    ticker_id = request.args.get('id')
    
    # 1. Resolve Ticker ID (Manual, Header, or Single-Ticker Fallback)
    if not ticker_id:
        cid = request.headers.get('X-Client-ID')
        if cid:
            for tid, t_data in tickers.items():
                if cid in t_data.get('clients', []):
                    ticker_id = tid
                    break
    
    if not ticker_id and len(tickers) == 1:
        ticker_id = list(tickers.keys())[0]

    # Initialize with global state, then override with ticker-specific settings if found
    with data_lock:
        response_settings = dict(state)
    if ticker_id and ticker_id in tickers:
        response_settings.update(tickers[ticker_id]['settings'])
        response_settings['active_sports'] = dict(state['active_sports'])  # global always wins
        _t_teams = tickers[ticker_id].get('my_teams')
        # None = use global fallback (always []); non-empty list = ticker's saved teams
        response_settings['my_teams'] = list(state.get('my_teams', [])) if _t_teams is None else _t_teams
        response_settings['ticker_id'] = ticker_id

        # Include stored timezone context (learned from /data ticker requests).
        _tz_name, _tz_offset = _get_ticker_timezone_context(tickers[ticker_id])
        response_settings['timezone_name'] = _tz_name
        response_settings['utc_offset'] = _tz_offset

    pinned_game = ''
    pinned_games = []
    if ticker_id and ticker_id in tickers:
        _settings = tickers[ticker_id].get('settings', {})
        pinned_game, pinned_games = _normalize_single_pin(
            pinned_game=_settings.get('pinned_game'),
            pinned_games=_settings.get('pinned_games', [])
        )
    response_settings['pinned_game'] = pinned_game
    response_settings['pinned_games'] = pinned_games
    response_settings['is_pinned'] = bool(pinned_game)

    current_mode = MODE_MIGRATIONS.get(response_settings.get('mode', 'sports'), response_settings.get('mode', 'sports'))
    sports_mode_family = ('sports', 'live', 'my_teams', 'sports_full')

    # Legacy app behavior: reflect pin by forcing sports_full mode in /api/state.
    # This keeps pinned detection compatible with clients that key off mode.
    if pinned_game and current_mode in sports_mode_family:
        current_mode = 'sports_full'
        response_settings['mode'] = current_mode
    
    if current_mode not in VALID_MODES:
        current_mode = 'sports'
    if current_mode == 'poop_fetcher' and not _is_poop_fetcher_mode_allowed(ticker_id):
        current_mode = 'sports'

    response_settings['mode'] = current_mode
    if not _is_poop_fetcher_mode_allowed(ticker_id):
        response_settings.get('active_sports', {}).pop('poop_fetcher', None)
        
    response_settings['flight_submode'] = 'track' if current_mode == 'flight_tracker' else 'airport'

    is_sports_mode = current_mode in sports_mode_family
    delay_seconds = (response_settings.get('live_delay_seconds', 0)
                     if (is_sports_mode and response_settings.get('live_delay_mode'))
                     else 0)
    raw_games = fetcher.get_mode_snapshot(current_mode, delay_seconds)
    processed_games = []
    saved_teams = set(response_settings.get('my_teams', []))
    COLLISION_ABBRS = {'LV'}
    _active_sports = state.get('active_sports', {})

    for g in raw_games:
        game_copy = g.copy()
        sport = game_copy.get('sport', '')
        g_type = game_copy.get('type', '')
        if current_mode in ('sports', 'live', 'my_teams'):
            should_show = _active_sports.get(sport, True)
        else:
            should_show = True

        if current_mode == 'my_teams':
            h_ab = str(game_copy.get('home_abbr', '')).upper()
            a_ab = str(game_copy.get('away_abbr', '')).upper()
            in_home = f"{sport}:{h_ab}" in saved_teams or (h_ab in saved_teams and h_ab not in COLLISION_ABBRS)
            in_away = f"{sport}:{a_ab}" in saved_teams or (a_ab in saved_teams and a_ab not in COLLISION_ABBRS)
            if not (in_home or in_away):
                should_show = False
        elif current_mode == 'live':
            if game_copy.get('state') not in ('in', 'half', 'crit'):
                should_show = False
        elif current_mode == 'sports':
            if g_type in ('music', 'clock', 'weather', 'stock_ticker', 'flight_visitor'):
                should_show = False
            else:
                status_lower = str(game_copy.get('status', '')).lower()
                if any(k in status_lower for k in ("postponed", "suspended", "canceled", "ppd")):
                    should_show = False
        elif current_mode == 'music':
            if g_type != 'music':
                should_show = False
        elif current_mode == 'stocks':
            if g_type != 'stock_ticker':
                should_show = False
        elif current_mode == 'weather':
            if g_type != 'weather':
                should_show = False
        elif current_mode == 'clock':
            if g_type != 'clock':
                should_show = False
        elif current_mode == 'flights':
            if sport != 'flight':
                should_show = False
        elif current_mode == 'flight_tracker':
            if g_type != 'flight_visitor':
                should_show = False
        elif current_mode == 'poop_fetcher':
            if g_type != 'poop_fetcher':
                should_show = False

        game_copy['is_shown'] = should_show
        processed_games.append(game_copy)

    tz_name = str(response_settings.get('timezone_name', '')).strip()
    tz_offset = response_settings.get('utc_offset', state.get('utc_offset', -5))
    _apply_timezone_to_game_times(processed_games, tz_name=tz_name, utc_offset=tz_offset)

    return jsonify({
        "status": "ok",
        "settings": response_settings,
        "games": processed_games,
        "is_pinned": bool(pinned_game),
        "pinned_game": pinned_game,
        "pinned_games": pinned_games
    })


@app.route('/api/timezone', methods=['GET'])
@app.route('/timezone', methods=['GET'])
def api_timezone_debug():
    """
    Debug endpoint for ticker timezone resolution.
    Query params:
      - id: ticker id (optional; inferred from X-Client-ID or single-ticker fallback)
      - refresh: 1/true to force running timezone update pipeline for this request
    """
    ticker_id = request.args.get('id')
    if not ticker_id:
        cid = request.headers.get('X-Client-ID')
        if cid:
            for tid, t_data in tickers.items():
                if cid in t_data.get('clients', []):
                    ticker_id = tid
                    break
    if not ticker_id and len(tickers) == 1:
        ticker_id = list(tickers.keys())[0]

    if not ticker_id or ticker_id not in tickers:
        return jsonify({
            "status": "error",
            "message": "Ticker not found. Provide ?id=<ticker_id>",
            "known_tickers": list(tickers.keys())[:20]
        }), 404

    refresh_raw = str(request.args.get('refresh', '')).strip().lower()
    do_refresh = refresh_raw in ('1', 'true', 'yes', 'y', 'on')

    if do_refresh:
        _maybe_update_ticker_timezone_from_request(ticker_id, request)

    rec = tickers[ticker_id]
    settings = rec.get('settings', {}) if isinstance(rec, dict) else {}

    hdr_tz, hdr_offset = _extract_timezone_from_request_headers(request)
    client_ip = _extract_client_ip(request)

    ip_lookup = None
    if client_ip:
        ip_tz, ip_off = _lookup_timezone_for_ip(client_ip)
        ip_lookup = {
            "ip": client_ip,
            "timezone": ip_tz,
            "utc_offset": ip_off,
        }

    self_tz, self_off, self_ip = _lookup_timezone_for_current_connection()

    lat = settings.get('weather_lat', state.get('weather_lat'))
    lon = settings.get('weather_lon', state.get('weather_lon'))
    ll_tz, ll_off = _lookup_timezone_for_latlon(lat, lon)

    effective_tz, effective_off = _get_ticker_timezone_context(rec)

    return jsonify({
        "status": "ok",
        "ticker_id": ticker_id,
        "refresh_applied": do_refresh,
        "request_inputs": {
            "query": {
                "timezone_name": request.args.get('timezone_name'),
                "utc_offset": request.args.get('utc_offset'),
                "tz": request.args.get('tz'),
                "offset": request.args.get('offset'),
            },
            "headers": {
                "X-Client-ID": request.headers.get('X-Client-ID'),
                "X-Ticker-Timezone": request.headers.get('X-Ticker-Timezone'),
                "X-Ticker-Utc-Offset": request.headers.get('X-Ticker-Utc-Offset'),
                "X-Timezone": request.headers.get('X-Timezone'),
                "X-UTC-Offset": request.headers.get('X-UTC-Offset'),
                "X-Forwarded-For": request.headers.get('X-Forwarded-For'),
                "X-Real-IP": request.headers.get('X-Real-IP'),
                "CF-Connecting-IP": request.headers.get('CF-Connecting-IP'),
            },
            "resolved_from_request": {
                "header_timezone": hdr_tz,
                "header_utc_offset": hdr_offset,
                "client_ip": client_ip,
                "remote_addr": request.remote_addr,
            }
        },
        "stored": {
            "settings.timezone_name": settings.get('timezone_name'),
            "settings.utc_offset": settings.get('utc_offset'),
            "rec.timezone_name": rec.get('timezone_name'),
            "rec.last_ip": rec.get('last_ip'),
            "weather_lat": lat,
            "weather_lon": lon,
        },
        "lookups": {
            "ip_lookup": ip_lookup,
            "current_connection_lookup": {
                "ip": self_ip,
                "timezone": self_tz,
                "utc_offset": self_off,
            },
            "latlon_lookup": {
                "timezone": ll_tz,
                "utc_offset": ll_off,
            }
        },
        "effective": {
            "timezone_name": effective_tz,
            "utc_offset": effective_off,
        }
    })

@app.route('/api/pin_games', methods=['POST'])
def api_pin_games():
    try:
        payload = request.json or {}
        ticker_id = payload.get('ticker_id') or request.args.get('id')
        cid = request.headers.get('X-Client-ID')

        if not ticker_id and cid:
            for tid, rec in tickers.items():
                if cid in rec.get('clients', []):
                    ticker_id = tid
                    break
        if not ticker_id and len(tickers) == 1:
            ticker_id = list(tickers.keys())[0]

        if ticker_id and ticker_id in tickers:
            rec = tickers[ticker_id]
            if cid and cid not in rec.get('clients', []):
                print(f"⛔ Blocked unauthorized pin change from {cid}")
                return jsonify({"error": "Unauthorized: Device not paired"}), 403

        single_pin, pin_list = _normalize_single_pin(pinned_games=payload.get('game_ids', []))

        with data_lock:
            if ticker_id and ticker_id in tickers:
                tickers[ticker_id]['settings']['pinned_game'] = single_pin
                tickers[ticker_id]['settings']['pinned_games'] = pin_list

        if ticker_id and ticker_id in tickers:
            save_specific_ticker(ticker_id)

        threading.Thread(target=fetcher.update_current_games, daemon=True).start()

        return jsonify({
            "status": "ok",
            "ticker_id": ticker_id,
            "pinned_game": single_pin,
            "pinned_games": pin_list
        })
    except Exception as e:
        print(f"Pin API Error: {e}")
        return jsonify({"error": "Failed to save pinned games"}), 500
    
@app.route('/api/teams')
def api_teams():
    with data_lock: return jsonify(state['all_teams_data'])

@app.route('/api/hardware', methods=['POST'])
def api_hardware():
    try:
        data = request.json or {}
        action = data.get('action')
        ticker_id = data.get('ticker_id')
        
        # NEW: Handle Update Action
        if action == 'update':
            with data_lock:
                for t in tickers.values(): t['update_requested'] = True
            threading.Timer(60, lambda: [t.update({'update_requested':False}) for t in tickers.values()]).start()
            return jsonify({"status": "ok", "message": "Updating Fleet"})

        if action == 'reboot':
            if ticker_id and ticker_id in tickers:
                with data_lock:
                    tickers[ticker_id]['reboot_requested'] = True
                def clear_flag(tid):
                    with data_lock:
                        if tid in tickers: tickers[tid]['reboot_requested'] = False
                threading.Timer(15, clear_flag, args=[ticker_id]).start()
                return jsonify({"status": "ok", "message": f"Rebooting {ticker_id}"})
            elif len(tickers) > 0:
                target = list(tickers.keys())[0]
                with data_lock:
                    tickers[target]['reboot_requested'] = True
                threading.Timer(15, lambda: tickers[target].update({'reboot_requested': False})).start()
                return jsonify({"status": "ok"})
                
        return jsonify({"status": "ignored"})
    except Exception as e:
        print(f"Hardware API Error: {e}")
        return jsonify({"status": "error"}), 500

@app.route('/api/debug', methods=['GET', 'POST'])
def api_debug():
    if request.method == 'POST':
        payload = request.json or {}
        with data_lock:
            state.update(payload)
        # Sync TestMode whenever any relevant key was sent
        if any(k.startswith('test_') or k in ('debug_mode', 'custom_date') for k in payload):
            TestMode.configure(
                enabled=state.get('test_mode', False),
                spotify=state.get('test_spotify', False),
                stocks=state.get('test_stocks', False),
                sports_date=state.get('test_sports_date', False),
                flights=state.get('test_flights', False),
                custom_date=state.get('custom_date'),
            )
        if tee_instance is not None:
            Tee.verbose_debug = state.get('debug_mode', False)
        return jsonify({"status": "ok"})
    else:
        # GET: return current debug / test mode snapshot
        with data_lock:
            debug_snap = {
                'debug_mode': state.get('debug_mode'),
                'custom_date': state.get('custom_date'),
                'show_debug_options': state.get('show_debug_options'),
            }
        return jsonify({
            "state_debug": debug_snap,
            "test_mode": TestMode.status(),
        })

@app.route('/errors', methods=['GET'])
def get_logs():
    log_file = "ticker.log"
    if not os.path.exists(log_file):
        return "Log file not found", 404
    try:
        file_size = os.path.getsize(log_file)
        read_size = min(file_size, 102400) 
        log_content = ""
        with open(log_file, 'rb') as f:
            if file_size > read_size:
                f.seek(file_size - read_size)
            data = f.read()
            log_content = data.decode('utf-8', errors='replace')

        html_response = f"""
        <!DOCTYPE html>
        <html>
        <head><title>Logs</title><meta http-equiv="refresh" content="10"></head>
        <body style="background:#111;color:#0f0;font-family:monospace;padding:20px;">
            <pre>{log_content}</pre>
            <script>window.scrollTo(0,document.body.scrollHeight);</script>
        </body></html>
        """
        return app.response_class(response=html_response, status=200, mimetype='text/html')
    except Exception as e:
        return f"Error: {str(e)}", 500

@app.route('/api/my_teams', methods=['GET'])
def check_my_teams():
    ticker_id = request.args.get('id')
    with data_lock:
        global_teams = state.get('my_teams', [])
        if not ticker_id:
            return jsonify({ "status": "ok", "scope": "Global", "teams": global_teams })

        if ticker_id in tickers:
            rec = tickers[ticker_id]
            specific_teams = rec.get('my_teams')
            using_fallback = specific_teams is None
            effective = global_teams if using_fallback else specific_teams
            return jsonify({ 
                "status": "ok", "scope": "Ticker Specific", 
                "using_global_fallback": using_fallback, 
                "teams": effective 
            })
        
        return jsonify({"error": "Ticker ID not found"}), 404

@app.route('/api/airports', methods=['GET'])
def get_airports():
    airports = [
        {'icao': 'KEWR', 'iata': 'EWR', 'name': 'Newark', 'city': 'New York'},
        {'icao': 'KJFK', 'iata': 'JFK', 'name': 'JFK', 'city': 'New York'},
        {'icao': 'KLGA', 'iata': 'LGA', 'name': 'LaGuardia', 'city': 'New York'},
        {'icao': 'KORD', 'iata': 'ORD', 'name': "O'Hare", 'city': 'Chicago'},
        {'icao': 'KLAX', 'iata': 'LAX', 'name': 'LAX', 'city': 'Los Angeles'},
        {'icao': 'KSFO', 'iata': 'SFO', 'name': 'San Francisco', 'city': 'San Francisco'},
        {'icao': 'KATL', 'iata': 'ATL', 'name': 'Hartsfield', 'city': 'Atlanta'},
        {'icao': 'KDEN', 'iata': 'DEN', 'name': 'Denver Intl', 'city': 'Denver'},
        {'icao': 'KDFW', 'iata': 'DFW', 'name': 'Dallas/Fort Worth', 'city': 'Dallas'},
        {'icao': 'KBOS', 'iata': 'BOS', 'name': 'Logan', 'city': 'Boston'},
        {'icao': 'KSEA', 'iata': 'SEA', 'name': 'SeaTac', 'city': 'Seattle'},
        {'icao': 'KMIA', 'iata': 'MIA', 'name': 'Miami Intl', 'city': 'Miami'},
    ]
    return jsonify(airports)

@app.route('/api/airlines', methods=['GET'])
def get_airlines():
    airlines = [
        {'code': '', 'name': 'All Airlines'},
        {'code': 'UA', 'name': 'United Airlines'},
        {'code': 'DL', 'name': 'Delta'},
        {'code': 'AA', 'name': 'American'},
        {'code': 'WN', 'name': 'Southwest'},
        {'code': 'B6', 'name': 'JetBlue'},
        {'code': 'AS', 'name': 'Alaska'},
    ]
    return jsonify(airlines)

@app.route('/api/flight/status', methods=['GET'])
def get_flight_status():
    if not flight_tracker:
        return jsonify({'available': False})
    # Optional: force a fresh fetch for debugging
    force = request.args.get('force') == '1'
    if force:
        try:
            flight_tracker.fetch_visitor_tracking()
        except Exception as e:
            print(f"[DEBUG] force fetch failed: {e}")
    with data_lock:
        return jsonify({
            'available': True,
            'visitor_enabled': state['active_sports'].get('flight_tracker', False),
            'airport_enabled': state['active_sports'].get('flight_airport', False),
            'tracking': {
                'flight_id': state.get('track_flight_id', ''),
                'guest_name': state.get('track_guest_name', ''),
                'airport': {
                    'icao': state.get('airport_code_icao', ''),
                    'iata': state.get('airport_code_iata', ''),
                    'name': state.get('airport_name', ''),
                    'airline': ''  # Always empty - support all airlines
                }
            },
            'visitor': flight_tracker.get_visitor_object() if force else None
        })

@app.route('/')
def root(): return "Ticker Server v9 Running"

if __name__ == "__main__":
    print("🚀 Starting Ticker Server...")
    threading.Thread(target=sports_worker, daemon=True).start()
    threading.Thread(target=stocks_worker, daemon=True).start()
    threading.Thread(target=music_worker, daemon=True).start()
    if flight_tracker:
        threading.Thread(target=flights_worker, daemon=True).start()
    print("✅ Worker threads started")
    print("🌐 Starting Flask on port 5000...")
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 5000)))
