# ── Standard library ──
import csv
import concurrent.futures
import glob
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
from datetime import datetime as dt, timezone, timedelta

# ── Third-party ──
import requests
from requests.adapters import HTTPAdapter
from flask import Flask, jsonify, request
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

# Logo URL cache so validate_logo_url doesn't re-HEAD the same URL
_logo_url_cache: dict = {}

def validate_logo_url(base_id):
    if base_id in _logo_url_cache:
        return _logo_url_cache[base_id]
    urls_to_try = [
        f"https://assets.leaguestat.com/ahl/logos/50x50/{base_id}_90.png",
        f"https://assets.leaguestat.com/ahl/logos/{base_id}_91.png",
        f"https://assets.leaguestat.com/ahl/logos/50x50/{base_id}.png"
    ]
    for url in urls_to_try:
        try:
            r = requests.head(url, timeout=1)
            if r.status_code == 200:
                _logo_url_cache[base_id] = url
                return url
        except: pass
    fallback = f"https://assets.leaguestat.com/ahl/logos/{base_id}.png"
    _logo_url_cache[base_id] = fallback
    return fallback

# ================= SERVER VERSION TAG =================
SERVER_VERSION = "v0.8-AIFlights"

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

GLOBAL_CONFIG_FILE = "global_config.json"
STOCK_CACHE_FILE = "stock_cache.json"
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

AHL_API_KEYS = ["ccb91f29d6744675", "694cfeed58c932ee", "50c2cd9b5e18e390"]

TZ_OFFSETS = {
    "EST": -5, "EDT": -4, "CST": -6, "CDT": -5,
    "MST": -7, "MDT": -6, "PST": -8, "PDT": -7, "AST": -4, "ADT": -3
}

# ── Timeout constants (seconds) ──
TIMEOUTS = {
    'default': 7,   # general API calls (API_TIMEOUT)
    'quick':   3,   # AHL scoring / NHL landing
    'ahl':     4,   # AHL box score
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

LEAGUE_OPTIONS = [
    {'id': 'nfl', 'label': 'NFL', 'type': 'sport', 'default': True, 'fetch': {'path': 'football/nfl', 'team_params': {'limit': 100}, 'type': 'scoreboard'}},
    {'id': 'mlb', 'label': 'MLB', 'type': 'sport', 'default': True, 'fetch': {'path': 'baseball/mlb', 'team_params': {'limit': 100}, 'type': 'scoreboard'}},
    {'id': 'nhl', 'label': 'NHL', 'type': 'sport', 'default': True, 'fetch': {'path': 'hockey/nhl', 'team_params': {'limit': 100}, 'type': 'scoreboard'}},
    {'id': 'ahl', 'label': 'AHL', 'type': 'sport', 'default': True, 'fetch': {'type': 'ahl_native'}}, 
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
    {'id': 'hockey_olympics', 'label': 'Olympic Hockey', 'type': 'sport', 'default': True, 'fetch': {'path': 'hockey/olympics-mens-ice-hockey', 'type': 'scoreboard'}},
    {'id': 'f1', 'label': 'Formula 1', 'type': 'sport', 'default': True, 'fetch': {'path': 'racing/f1', 'type': 'leaderboard'}},
    {'id': 'nascar', 'label': 'NASCAR', 'type': 'sport', 'default': True, 'fetch': {'path': 'racing/nascar', 'type': 'leaderboard'}},
    {'id': 'weather', 'label': 'Weather', 'type': 'util', 'default': True},
    {'id': 'clock', 'label': 'Clock', 'type': 'util', 'default': True},
    {'id': 'music', 'label': 'Music', 'type': 'util', 'default': True},
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
    return (prio, x.get('startTimeUTC', '9999'), x.get('sport', ''), x.get('home_abbr', ''), str(x.get('id', '0')))


# Valid mode set — no 'all', no 'flight2', no 'flight_submode'
VALID_MODES = {'sports', 'live', 'my_teams', 'stocks', 'weather', 'music', 'clock', 'flights', 'flight_tracker'}

# Legacy mode migration map applied at load time and on /api/config writes
MODE_MIGRATIONS = {'all': 'sports', 'flight2': 'flight_tracker'}

FBS_TEAMS = {"AF", "AKR", "ALA", "APP", "ARIZ", "ASU", "ARK", "ARST", "ARMY", "AUB", "BALL", "BAY", "BOIS", "BC", "BGSU", "BUF", "BYU", "CAL", "CMU", "CLT", "CIN", "CLEM", "CCU", "COLO", "CSU", "CONN", "DEL", "DUKE", "ECU", "EMU", "FAU", "FIU", "FLA", "FSU", "FRES", "GASO", "GAST", "GT", "UGA", "HAW", "HOU", "ILL", "IND", "IOWA", "ISU", "JXST", "JMU", "KAN", "KSU", "KENN", "KENT", "UK", "LIB", "ULL", "LT", "LOU", "LSU", "MAR", "MD", "MASS", "MEM", "MIA", "M-OH", "MICH", "MSU", "MTSU", "MINN", "MSST", "MIZ", "MOST", "NAVY", "NCST", "NEB", "NEV", "UNM", "NMSU", "UNC", "UNT", "NIU", "NU", "ND", "OHIO", "OSU", "OU", "OKST", "ODU", "MISS", "ORE", "ORST", "PSU", "PITT", "PUR", "RICE", "RUTG", "SAM", "SDSU", "SJSU", "SMU", "USA", "SC", "USF", "USM", "STAN", "SYR", "TCU", "TEM", "TENN", "TEX", "TA&M", "TXST", "TTU", "TOL", "TROY", "TULN", "TLSA", "UAB", "UCF", "UCLA", "ULM", "UMASS", "UNLV", "USC", "UTAH", "USU", "UTEP", "UTSA", "VAN", "UVA", "VT", "WAKE", "WASH", "WSU", "WVU", "WKU", "WMU", "WIS", "WYO"}
FCS_TEAMS = {"ACU", "AAMU", "ALST", "UALB", "ALCN", "UAPB", "APSU", "BCU", "BRWN", "BRY", "BUCK", "BUT", "CP", "CAM", "CARK", "CCSU", "CHSO", "UTC", "CIT", "COLG", "COLU", "COR", "DART", "DAV", "DAY", "DSU", "DRKE", "DUQ", "EIU", "EKU", "ETAM", "EWU", "ETSU", "ELON", "FAMU", "FOR", "FUR", "GWEB", "GTWN", "GRAM", "HAMP", "HARV", "HC", "HCU", "HOW", "IDHO", "IDST", "ILST", "UIW", "INST", "JKST", "LAF", "LAM", "LEH", "LIN", "LIU", "ME", "MRST", "MCN", "MER", "MERC", "MRMK", "MVSU", "MONM", "MONT", "MTST", "MORE", "MORG", "MUR", "UNH", "NHVN", "NICH", "NORF", "UNA", "NCAT", "NCCU", "UND", "NDSU", "NAU", "UNCO", "UNI", "NWST", "PENN", "PRST", "PV", "PRES", "PRIN", "URI", "RICH", "RMU", "SAC", "SHU", "SFPA", "SAM", "USD", "SELA", "SEMO", "SDAK", "SDST", "SCST", "SOU", "SIU", "SUU", "STMN", "SFA", "STET", "STO", "STBK", "TAR", "TNST", "TNTC", "TXSO", "TOW", "UCD", "UTM", "UTM", "UTRGV", "VAL", "VILL", "VMI", "WAG", "WEB", "WGA", "WCU", "WIU", "W&M", "WOF", "YALE", "YSU"}
OLYMPIC_HOCKEY_TEAMS = [
    {"abbr": "CAN", "logo": "https://a.espncdn.com/i/teamlogos/countries/500/can.png", "color": "D52B1E", "alt_color": "FFFFFF"},
    {"abbr": "USA", "logo": "https://a.espncdn.com/i/teamlogos/countries/500/usa.png", "color": "0A3161", "alt_color": "B31942"},
    {"abbr": "SWE", "logo": "https://a.espncdn.com/i/teamlogos/countries/500/swe.png", "color": "FECC02", "alt_color": "004B87"},
    {"abbr": "FIN", "logo": "https://a.espncdn.com/i/teamlogos/countries/500/fin.png", "color": "002F6C", "alt_color": "FFFFFF"},
    {"abbr": "RUS", "logo": "https://a.espncdn.com/i/teamlogos/countries/500/rus.png", "color": "D52B1E", "alt_color": "0039A6"},
    {"abbr": "CZE", "logo": "https://a.espncdn.com/i/teamlogos/countries/500/cze.png", "color": "D7141A", "alt_color": "11457E"},
    {"abbr": "GER", "logo": "https://a.espncdn.com/i/teamlogos/countries/500/ger.png", "color": "000000", "alt_color": "FFCE00"},
    {"abbr": "SUI", "logo": "https://a.espncdn.com/i/teamlogos/countries/500/sui.png", "color": "FF0000", "alt_color": "FFFFFF"},
    {"abbr": "SVK", "logo": "https://a.espncdn.com/i/teamlogos/countries/500/svk.png", "color": "0B4EA2", "alt_color": "EE1C25"},
    {"abbr": "LAT", "logo": "https://a.espncdn.com/i/teamlogos/countries/500/lat.png", "color": "9E3039", "alt_color": "FFFFFF"},
    {"abbr": "DEN", "logo": "https://a.espncdn.com/i/teamlogos/countries/500/den.png", "color": "C60C30", "alt_color": "FFFFFF"},
    {"abbr": "ITA", "logo": "https://a.espncdn.com/i/teamlogos/countries/500/ita.png", "color": "0064A8", "alt_color": "FFFFFF"}
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
    "live_delay_seconds": 45
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
        # Handle old flights+track_submode combo
        if config_data.get('mode') == 'flights' and config_data.get('flight_submode') == 'track':
            config_data['mode'] = 'flight_tracker'
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
            if 'my_teams' not in t_data: t_data['my_teams'] = []
            if 'clients' not in t_data: t_data['clients'] = []
            
            tickers[tid] = t_data
    except Exception as e:
        print(f"❌ Failed to load ticker file {t_file}: {e}")


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
                'my_teams': state['my_teams'],
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
                'airline_filter': ''  # Always empty - support all airlines
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
        
        # Tracking variables for stalled progress detection
        last_progress_ms = -1
        last_check_time = 0
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
                        api_is_playing = current.get('is_playing', False)
                        progress_ms = current.get('progress_ms', 0)
                        
                        # --- FIX: DETECT STALLED PROGRESS ---
                        # Sometimes Spotify API says is_playing=True but progress doesn't move.
                        # We force pause if progress hasn't changed in >2 seconds.
                        actual_is_playing = api_is_playing
                        now = time.time()
                        
                        if api_is_playing:
                            if progress_ms == last_progress_ms:
                                # If progress is exactly the same as last fetch for >2 seconds, force pause
                                if (now - last_check_time) > 2.0: 
                                    actual_is_playing = False
                            else:
                                # Progress moved, update tracker
                                last_progress_ms = progress_ms
                                last_check_time = now
                        else:
                            # Naturally paused, reset tracker
                            last_progress_ms = -1
                        # ------------------------------------

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
                                "is_playing": actual_is_playing,
                                "name": item.get('name', 'Unknown'),
                                "artist": ", ".join(a['name'] for a in item.get('artists', [])),
                                "cover": current_cover,
                                "next_covers": self.cached_queue_covers,
                                "duration": item.get('duration_ms', 0) / 1000.0,
                                "progress": progress_ms / 1000.0,
                                "last_fetch_ts": time.time()
                            })

                        # STAGE 1 vs STAGE 2
                        # Quick Polling (0.8s) if playing, Medium (2.0s) if paused
                        current_delay = 0.8 if actual_is_playing else 2.0

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
        self.ahl_cached_key = None
        self.ahl_key_expiry = 0
        # abbr-keyed index rebuilt in fetch_all_teams — O(1) team lookups
        self._teams_abbr_index: dict = {}  # league -> {abbr -> team_entry}
        
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

            self._fetch_ahl_teams_reference(teams_catalog)

            for t in OLYMPIC_HOCKEY_TEAMS:
                scoped_id = f"hockey_olympics:{t['abbr']}"
                if scoped_id not in seen_ids.get('hockey_olympics', set()):
                    seen_ids.setdefault('hockey_olympics', set()).add(scoped_id)
                    teams_catalog['hockey_olympics'].append({
                        'abbr': t['abbr'],
                        'id': scoped_id,
                        'logo': t['logo'],
                        'color': t.get('color', '000000'),
                        'alt_color': t.get('alt_color', '444444')
                    })

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
            
    def _get_ahl_key(self):
        if self.ahl_cached_key and time.time() < self.ahl_key_expiry:
            return self.ahl_cached_key

        for key in AHL_API_KEYS:
            try:
                params = {"feed": "modulekit", "view": "seasons", "key": key, "client_code": "ahl", "lang": "en", "fmt": "json", "league_id": 4}
                r = self.session.get("https://lscluster.hockeytech.com/feed/index.php", params=params, timeout=TIMEOUTS['quick'])
                if r.status_code == 200:
                    data = r.json()
                    if "SiteKit" in data or "Seasons" in data:
                        self.ahl_cached_key = key
                        self.ahl_key_expiry = time.time() + 7200 
                        return key
            except: continue
        return AHL_API_KEYS[0]

    def _fetch_ahl_teams_reference(self, catalog):
        if 'ahl' not in self.leagues: return

        catalog['ahl'] = []
        seen_ids: set = set()

        # Collect unique team IDs first, then validate logos in parallel
        unique_teams = []
        for code, meta in AHL_TEAMS.items():
            t_id = meta.get('id')
            if t_id and t_id in seen_ids: continue
            if t_id: seen_ids.add(t_id)
            unique_teams.append((code, meta, t_id))

        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as ex:
            logo_futures = {t_id: ex.submit(validate_logo_url, t_id) for _, _, t_id in unique_teams if t_id}
        logo_results = {t_id: fut.result() for t_id, fut in logo_futures.items()}

        for code, meta, t_id in unique_teams:
            logo_url = logo_results.get(t_id, "") if t_id else ""
            catalog['ahl'].append({
                'abbr': code,
                'id': f"ahl:{code}",
                'real_id': t_id,
                'logo': logo_url,
                'color': meta.get('color', '000000'),
                'alt_color': '444444',
                'name': meta.get('name', code),
                'shortName': meta.get('name', code).split(" ")[-1]
            })

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

    def _fetch_ahl(self, conf, visible_start_utc, visible_end_utc):
        games_found = []
        if not conf['active_sports'].get('ahl', False): return []

        try:
            key = self._get_ahl_key()
            _local_tz = timezone(timedelta(hours=conf.get('utc_offset', -5)))
            req_date = visible_start_utc.astimezone(_local_tz).strftime("%Y-%m-%d")

            params = {
                "feed": "modulekit", "view": "scorebar", "key": key,
                "client_code": "ahl", "lang": "en", "fmt": "json", 
                "league_id": 4, "site_id": 0
            }
            
            r = self.session.get("https://lscluster.hockeytech.com/feed/index.php", params=params, timeout=TIMEOUTS['stock'])
            if r.status_code != 200: return []
            
            data = r.json()
            scorebar = data.get("SiteKit", {}).get("Scorebar", [])
            ahl_refs = state['all_teams_data'].get('ahl', [])
            _ahl_by_abbr = {t['abbr']: t for t in ahl_refs}

            for g in scorebar:
                if g.get("Date") != req_date: continue
                
                h_code, a_code = g.get("HomeCode", "").upper(), g.get("VisitorCode", "").upper()
                if not h_code or h_code == "TBD": continue

                h_sc, a_sc = int(g.get("HomeGoals", 0)), int(g.get("VisitorGoals", 0))
                raw_status = g.get("GameStatusString", "")
                status_lower = raw_status.lower()
                period_str = str(g.get("Period", "0"))
                
                # REPAIR LOGIC: If goals > 0 or period > 0, the game is active regardless of status string
                is_active = (h_sc > 0 or a_sc > 0 or (period_str != "0" and period_str != ""))
                
                if "final" in status_lower:
                    gst = "post"
                    disp = "FINAL"
                    if period_str == "4": disp = "FINAL OT"
                    if period_str == "5": disp = "FINAL S/O"
                elif is_active:
                    gst = "in"
                    # Look for clock in the string (e.g., "15:20 2nd")
                    m = re.search(r'(\d+:\d+)', raw_status)
                    if m:
                        clk = m.group(1)
                        prd = "OT" if "ot" in status_lower else f"P{period_str}"
                        disp = f"{prd} {clk}"
                    elif "intermission" in status_lower:
                        disp = f"End {period_str}"
                    else:
                        disp = f"P{period_str} LIVE"
                else:
                    gst = "pre"
                    # Format start time from ScheduledTime
                    try:
                        sched = g.get("ScheduledTime", "")
                        hh, mm = map(int, sched.split(":"))
                        dt_obj = dt.strptime(f"{req_date} {hh}:{mm}", "%Y-%m-%d %H:%M").replace(tzinfo=_local_tz)
                        disp = dt_obj.strftime("%I:%M %p").lstrip('0')
                    except: disp = raw_status

                h_obj, a_obj = _ahl_by_abbr.get(h_code), _ahl_by_abbr.get(a_code)
                h_logo = h_obj['logo'] if h_obj else validate_logo_url(g.get("HomeID"))
                a_logo = a_obj['logo'] if a_obj else validate_logo_url(g.get("VisitorID"))

                games_found.append({
                    'type': 'scoreboard', 'sport': 'ahl', 'id': f"ahl_{g.get('ID')}",
                    'status': disp, 'state': gst, 'is_shown': True,
                    'home_abbr': h_code, 'home_score': str(h_sc), 'home_logo': h_logo,
                    'away_abbr': a_code, 'away_score': str(a_sc), 'away_logo': a_logo,
                    'home_color': f"#{AHL_TEAMS.get(h_code, {}).get('color','000000')}",
                    'away_color': f"#{AHL_TEAMS.get(a_code, {}).get('color','000000')}",
                    'startTimeUTC': g.get("GameDateISO8601", "")
                })
        except Exception as e: print(f"AHL Fix Error: {e}")
        return games_found

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
        if not conf['active_sports'].get(league_key, False): return []

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

                # Force fallback to our hardcoded colors for international teams or missing ESPN data
                if league_key == 'hockey_olympics' or not h_clr or h_clr == '000000' or not a_clr or a_clr == '000000':
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
                        'shootout': shootout_data,
                        'powerPlay': False, 
                        'emptyNet': False
                    }
                }
                if league_key == 'mlb':
                    game_obj['situation'].update({'balls': sit.get('balls', 0), 'strikes': sit.get('strikes', 0), 'outs': sit.get('outs', 0), 
                        'onFirst': sit.get('onFirst', False), 'onSecond': sit.get('onSecond', False), 'onThird': sit.get('onThird', False)})
                
                if is_suspended: game_obj['is_shown'] = False
                
                local_games.append(game_obj)
                
                # CHANGE C: SAVE FINAL GAMES TO CACHE
                if gst == 'post' and "FINAL" in s_disp:
                    self.final_game_cache[gid] = game_obj

        except Exception as e: print(f"Error fetching {league_key}: {e}")
        return local_games

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
                'is_playing': is_playing
            }
        }

    # ── Per-mode buffer builders ────────────────────────────────────────────

    def _build_sports_buffer(self):
        """Fetch all active sports leagues and return sorted game list."""
        with data_lock:
            conf = {k: state[k] for k in (
                'active_sports', 'mode', 'utc_offset', 'debug_mode', 'custom_date',
            )}
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

        # --- RESTORED: EFL & SOCCER FETCHING ---
        for internal_id, fid in FOTMOB_LEAGUE_MAP.items():
            if conf['active_sports'].get(internal_id, False):
                f = self.executor.submit(
                    self._fetch_fotmob_league, 
                    fid, internal_id, conf, 
                    window_start_utc, window_end_utc, 
                    visible_start_utc, visible_end_utc
                )
                futures[f] = internal_id

        # NHL Native (Optimized)
        if conf['active_sports'].get('nhl', False) and not conf['debug_mode']:
            f = self.executor.submit(self._fetch_nhl_native, conf, window_start_utc, window_end_utc, visible_start_utc, visible_end_utc)
            futures[f] = 'nhl_native'

        # AHL
        if conf['active_sports'].get('ahl', False):
            f = self.executor.submit(self._fetch_ahl, conf, visible_start_utc, visible_end_utc)
            futures[f] = 'ahl'

        # Standard ESPN Leagues (NFL, NBA, MLB, NCAA)
        for league_key, config in self.leagues.items():
            if league_key in ['nhl', 'ahl'] or league_key.startswith('soccer_'):
                continue # Already handled by specialized fetchers above
            
            f = self.executor.submit(
                self.fetch_single_league, 
                league_key, config, conf, window_start_utc, window_end_utc, 
                utc_offset, visible_start_utc, visible_end_utc
            )
            futures[f] = league_key
        
        # Wait for all threads
        done, _ = concurrent.futures.wait(futures.keys(), timeout=API_TIMEOUT)
        
        for f in done:
            lk = futures[f]
            try: 
                res = f.result()
                if res: 
                    all_games.extend(res)
                    self.league_last_data[lk] = res 
                elif lk in self.league_last_data:
                    all_games.extend(self.league_last_data[lk])
            except Exception as e: 
                if lk in self.league_last_data:
                    all_games.extend(self.league_last_data[lk])

        # === FILTER OUT OLD GAMES (3AM CUTOFF) ===
        # Remove completed games that started before the visibility window
        filtered_games = []
        for g in all_games:
            # Always keep utilities (clock, weather, music, flights)
            g_type = g.get('type', '')
            g_sport = g.get('sport', '')
            if g_type in ['clock', 'weather', 'music'] or g_sport in ['clock', 'weather', 'music', 'flight']:
                filtered_games.append(g)
                continue
            
            # For sports games, check if they're old finals
            state_val = g.get('state', '')
            status_val = str(g.get('status', '')).upper()
            
            # Keep in-progress games
            if state_val in ['in', 'half', 'crit']:
                filtered_games.append(g)
                continue
            
            # Keep scheduled games
            if state_val == 'pre':
                filtered_games.append(g)
                continue
            
            # For completed games, check if they're within the visibility window
            if state_val == 'post' or 'FINAL' in status_val:
                try:
                    game_start_str = g.get('startTimeUTC', '')
                    if game_start_str:
                        game_dt = parse_iso(game_start_str)
                        # Only keep if the game started within the visibility window
                        if visible_start_utc <= game_dt < visible_end_utc:
                            filtered_games.append(g)
                        # else: game is too old, don't include it
                    else:
                        # No timestamp, keep it to be safe
                        filtered_games.append(g)
                except:
                    # Parse error, keep it to be safe
                    filtered_games.append(g)
                continue
            
            # Default: keep the game
            filtered_games.append(g)
        
        all_games = filtered_games
        # === END FILTER ===
        # Sorting & Buffering
        all_games.sort(key=_game_sort_key)

        return all_games

    def _build_stocks_buffer(self):
        with data_lock:
            active_sports = dict(state['active_sports'])
        games = []
        for item in LEAGUE_OPTIONS:
            if item['type'] == 'stock' and active_sports.get(item['id']):
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
        # No weather data yet — show the clock while the fetcher loads, so the
        # hardware doesn't fall through to its own raw clock fallback.
        return [{'type': 'clock', 'sport': 'clock', 'id': 'weather_loading', 'is_shown': True}]

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

    # ── Central update dispatcher ──────────────────────────────────────────

    def update_current_games(self):
        with data_lock:
            mode = state['mode']
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
        }
        builder = _dispatch.get(mode, self._build_sports_buffer)
        result = builder()

        # Maintain history buffer for live-delay only in sports modes
        if mode in ('sports', 'live', 'my_teams'):
            snap = (time.time(), result[:])
            self.history_buffer.append(snap)
            if len(self.history_buffer) > 120:
                self.history_buffer = self.history_buffer[-60:]

        with data_lock:
            # For sports modes, keep the previous buffer if the new result is empty
            # (avoids a brief clock fallback when the sports data refresh cycle
            # temporarily produces no results). For all other modes (flights, weather,
            # clock, etc.) always replace, so stale sports data never leaks into the
            # flights/weather filter and permanently blocks content from showing.
            is_sports_mode = mode in ('sports', 'live', 'my_teams')
            if result or not is_sports_mode or not state.get('current_games'):
                state['current_games'] = result

    def get_snapshot_for_delay(self, delay_seconds):
        """Return current games, optionally from history buffer for live-delay."""
        if delay_seconds <= 0 or not self.history_buffer:
            with data_lock:
                return list(state.get('current_games', []))
        target_time = time.time() - delay_seconds
        closest = min(self.history_buffer, key=lambda x: abs(x[0] - target_time))
        return closest[1]

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
def sports_worker():
    try: fetcher.fetch_all_teams()
    except Exception as e: print(f"Team fetch error: {e}")

    while True:
        start_time = time.time()
        with data_lock:
            mode = state['mode']
        if mode in ('sports', 'live', 'my_teams'):
            try:
                fetcher.update_current_games()
            except Exception as e:
                print(f"Sports Worker Error: {e}")
        execution_time = time.time() - start_time
        time.sleep(max(0, SPORTS_UPDATE_INTERVAL - execution_time))

def stocks_worker():
    _cached_active_key = None
    while True:
        try:
            with data_lock:
                mode = state['mode']
                active_sports = state['active_sports']
            if mode == 'stocks':
                active_key = frozenset(k for k, v in active_sports.items() if k.startswith('stock_') and v)
                if active_key != _cached_active_key:
                    _cached_active_key = active_key
                fetcher.stocks.update_market_data(list(_cached_active_key))
                fetcher.update_current_games()
        except Exception as e:
            print(f"Stock worker error: {e}")
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

# ── Section L: Flask Routes ──
app = Flask(__name__)
CORS(app) 

@app.route('/api/config', methods=['POST'])
def api_config():
    try:
        new_data = request.json
        if not isinstance(new_data, dict): return jsonify({"error": "Invalid payload"}), 400

        # Migrate legacy modes to new clean mode names
        if 'mode' in new_data:
            new_data['mode'] = MODE_MIGRATIONS.get(new_data['mode'], new_data['mode'])
            # Old flights+track_submode combo → flight_tracker
            if new_data['mode'] == 'flights' and new_data.get('flight_submode') == 'track':
                new_data['mode'] = 'flight_tracker'
            # Reject any mode that isn't valid; fall back to sports
            if new_data['mode'] not in VALID_MODES:
                new_data['mode'] = 'sports'
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
                'track_flight_id', 'track_guest_name', 'airport_code_icao',
                'airport_code_iata', 'airport_name',
                'test_mode', 'test_spotify', 'test_stocks', 'test_sports_date', 'test_flights',
            }
            
            for k, v in new_data.items():
                if k not in allowed_keys: continue
                
                # HANDLE TEAMS
                if k == 'my_teams' and isinstance(v, list):
                    cleaned = []
                    seen = set()
                    for e in v:
                        if e:
                            k_str = str(e).strip()
                            if k_str == "LV": k_str = "ahl:LV"
                            if k_str not in seen:
                                seen.add(k_str)
                                cleaned.append(k_str)
                    
                    if target_id and target_id in tickers:
                        tickers[target_id]['my_teams'] = cleaned
                        tickers[target_id].pop('my_teams_set', None)
                    else:
                        state['my_teams'] = cleaned
                        state.pop('my_teams_set', None)
                    continue

                # HANDLE ACTIVE SPORTS
                if k == 'active_sports' and isinstance(v, dict): 
                    state['active_sports'].update(v)
                    continue
                
                # HANDLE MODES & SETTINGS
                if v is not None: state[k] = v
                
                # SYNC TO TICKER SETTINGS
                if target_id and target_id in tickers:
                    if k in tickers[target_id]['settings'] or k == 'mode':
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
        new_mode = state.get('mode', '')
        if new_mode in ('flights', 'flight_tracker') and flight_tracker:
            flight_tracker.force_update()

        # Immediately rebuild the buffer for the new mode (fast for non-sports modes)
        try: fetcher.update_current_games()
        except: pass

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
    league_meta = []
    for item in LEAGUE_OPTIONS:
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
            "my_teams": [],
            "clients": [],
            "paired": False,
            "pairing_code": generate_pairing_code(),
            "last_seen": time.time()
        }
        # Sync new ticker to global state immediately
        tickers[ticker_id]['settings']['mode'] = state.get('mode', 'sports')
        save_specific_ticker(ticker_id)

    rec = tickers[ticker_id]
    rec['last_seen'] = time.time()
    
    # 2. Pairing Check
    if not rec.get('clients') or not rec.get('paired'):
        if not rec.get('pairing_code'):
            rec['pairing_code'] = generate_pairing_code()
            save_specific_ticker(ticker_id)
        return jsonify({ "status": "pairing", "code": rec['pairing_code'], "ticker_id": ticker_id })

    t_settings = rec['settings']

    # ==============================================================================
    # CRITICAL FIX: FORCE SYNC WITH GLOBAL STATE
    # This ignores the ticker's local 'mode' setting and uses the server's global mode.
    # This ensures that when you change the mode in the dashboard, the ticker updates.
    # ==============================================================================
    current_mode = state.get('mode', 'sports')
    
    # Update local config to match global so the file stays mostly in sync
    if t_settings.get('mode') != current_mode:
        t_settings['mode'] = current_mode
        # Optional: Save here if you want persistence, but might be too much disk I/O
        # save_specific_ticker(ticker_id) 

    # Sleep Mode Check
    if t_settings.get('brightness', 100) <= 0:
        return jsonify({ "status": "sleep", "content": { "sports": [] } })

    # 4. Content Fetching
    delay_seconds = t_settings.get('live_delay_seconds', 0) if t_settings.get('live_delay_mode') else 0
    raw_games = fetcher.get_snapshot_for_delay(delay_seconds)
    visible_items = []

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
        saved_teams = set(rec.get('my_teams') or state.get('my_teams', []))
        COLLISION_ABBRS = {'LV'}
        for g in raw_games:
            sport = g.get('sport', '')
            h_ab, a_ab = str(g.get('home_abbr', '')).upper(), str(g.get('away_abbr', '')).upper()
            in_home = f"{sport}:{h_ab}" in saved_teams or (h_ab in saved_teams and h_ab not in COLLISION_ABBRS)
            in_away = f"{sport}:{a_ab}" in saved_teams or (a_ab in saved_teams and a_ab not in COLLISION_ABBRS)
            if in_home or in_away:
                g['is_shown'] = True
                visible_items.append(g)

    elif current_mode == 'live':
        for g in raw_games:
            if g.get('state') in _ACTIVE_STATES:
                g['is_shown'] = True
                visible_items.append(g)

    elif current_mode == 'sports':
        for g in raw_games:
            if g.get('type') in ['music', 'clock', 'weather', 'stock_ticker', 'flight_visitor']:
                continue
            status_lower = str(g.get('status', '')).lower()
            if any(k in status_lower for k in ("postponed", "suspended", "canceled", "ppd")):
                continue
            g['is_shown'] = True
            visible_items.append(g)
            
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
            
            if match:
                g['is_shown'] = True
                visible_items.append(g)

    # 6. Final Response
    g_config = { "mode": current_mode }
    if rec.get('reboot_requested'): g_config['reboot'] = True
    if rec.get('update_requested'): g_config['update'] = True
        
    return jsonify({ 
        "status": "ok", 
        "version": SERVER_VERSION,
        "ticker_id": ticker_id,
        "global_config": g_config, 
        "local_config": t_settings, 
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
            "my_teams": [],
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
    
    # --- FIX: Sync Mode ---
    if 'mode' in data:
        new_mode = data['mode']
        new_mode = MODE_MIGRATIONS.get(new_mode, new_mode)
        
        with data_lock:
            state['mode'] = new_mode
            rec['settings']['mode'] = new_mode
            
            # NOTE: Removed the logic that cleared flight_id and flags here.
            # This ensures that flight tracking continues in the background 
            # if a flight ID was previously set.

        # Trigger immediate refresh
        try:
            fetcher.update_current_games()
        except Exception as e:
            print(f"Error triggering update: {e}")

    save_specific_ticker(tid)
    save_global_config()
    
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
        response_settings['my_teams'] = tickers[ticker_id].get('my_teams', [])
        response_settings['ticker_id'] = ticker_id
    response_settings.pop('flight_submode', None)

    current_mode = MODE_MIGRATIONS.get(response_settings.get('mode', 'sports'), response_settings.get('mode', 'sports'))
    if current_mode not in VALID_MODES:
        current_mode = 'sports'

    raw_games = fetcher.get_snapshot_for_delay(0)
    processed_games = []
    saved_teams = set(response_settings.get('my_teams', []))
    COLLISION_ABBRS = {'LV'}

    for g in raw_games:
        game_copy = g.copy()
        sport = game_copy.get('sport', '')
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
            status_lower = str(game_copy.get('status', '')).lower()
            if any(k in status_lower for k in ("postponed", "suspended", "canceled", "ppd")):
                should_show = False

        game_copy['is_shown'] = should_show
        processed_games.append(game_copy)

    return jsonify({
        "status": "ok",
        "settings": response_settings,
        "games": processed_games 
    })
    
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
            specific_teams = rec.get('my_teams', [])
            using_fallback = len(specific_teams) == 0
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
def root(): return "Ticker Server v7 Running"

if __name__ == "__main__":
    print("🚀 Starting Ticker Server...")
    threading.Thread(target=sports_worker, daemon=True).start()
    threading.Thread(target=stocks_worker, daemon=True).start()
    if flight_tracker:
        threading.Thread(target=flights_worker, daemon=True).start()
    print("✅ Worker threads started")
    print("🌐 Starting Flask on port 5000...")
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 5000)))
