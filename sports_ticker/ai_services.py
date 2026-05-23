"""AI-assisted lookups: airline codes, airport names, and airport data helpers."""

import csv
import io
import json
import os
import re
import threading
import time

import requests

try:
    from google import genai
    from google.genai import types as genai_types
except ImportError:
    genai = None
    genai_types = None

# Imported from core — available by the time any route loads this module.
from .core import (
    AIRPORTS_DB, AIRPORT_CACHE_FILE, AIRLINE_CACHE_FILE,
    TIMEOUTS, save_json_atomically,
)

# ── Gemini AI setup ──
GEMINI_KEY = os.getenv('GEMINI_API_KEY')
AI_CLIENT = None
AI_AVAILABLE = False

if GEMINI_KEY and genai is not None:
    try:
        AI_CLIENT = genai.Client(api_key=GEMINI_KEY)
        AI_AVAILABLE = True
    except Exception:
        AI_AVAILABLE = False

# ── Airline IATA ↔ ICAO mappings ──
_IATA_TO_ICAO_FALLBACK = {
    'DL': 'DAL', 'UA': 'UAL', 'AA': 'AAL', 'WN': 'SWA', 'B6': 'JBU',
    'AS': 'ASA', 'NK': 'NKS', 'F9': 'FFT', 'G4': 'AAY', 'SY': 'SCX',
    'HA': 'HAL', 'BA': 'BAW', 'LH': 'DLH', 'AF': 'AFR', 'KL': 'KLM',
    'EK': 'UAE', 'QR': 'QTR', 'VS': 'VIR', 'FR': 'RYR', 'U2': 'EZY',
    'AC': 'ACA', 'WS': 'WJA', 'EI': 'EIN', 'LY': 'ELY',
}


def _build_airline_mappings():
    """Fetch comprehensive airline IATA↔ICAO from OpenFlights. Falls back to hardcoded table."""
    try:
        resp = requests.get(
            "https://raw.githubusercontent.com/jpatokal/openflights/master/data/airlines.dat",
            timeout=10,
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
            print(f"[AIRLINE-DB] Loaded {len(merged)} airline IATA↔ICAO mappings from OpenFlights")
            return merged
    except Exception as e:
        print(f"[AIRLINE-DB] Could not fetch airline data ({e}), using {len(_IATA_TO_ICAO_FALLBACK)} hardcoded entries")
    return dict(_IATA_TO_ICAO_FALLBACK)


_IATA_TO_ICAO: dict = _build_airline_mappings()
_ICAO_TO_IATA: dict = {v: k for k, v in _IATA_TO_ICAO.items()}

# Reverse ICAO → IATA index built once from airportsdata (O(1) lookup).
_ICAO_TO_IATA_INDEX: dict = {
    data.get('icao', '').upper(): iata
    for iata, data in AIRPORTS_DB.items()
    if data.get('icao')
}

# ── Persistent AI caches ──
def _load_json_cache(filepath: str, label: str) -> dict:
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
_airline_cache_lock = threading.RLock()
_airline_ai_request_lock = threading.Lock()
_AIRLINE_UNKNOWN_SENTINEL = "__UNKNOWN__"
_AIRLINE_QUOTA_RETRY_SECONDS = 3600
_airline_ai_cooldown_until = 0.0


def _migrate_airport_cache():
    """One-time migration: convert old 'CODE_Full Name' cache keys to plain 'CODE'."""
    additions = {}
    for key, name in _ai_airport_cache.items():
        m = re.match(r'^([A-Z]{2,4})_(.+)$', key)
        if m:
            code = m.group(1)
            if code not in _ai_airport_cache:
                additions[code] = name
    if additions:
        _ai_airport_cache.update(additions)
        save_json_atomically(AIRPORT_CACHE_FILE, _ai_airport_cache)
        print(f"[AIRPORT-CACHE] Migrated {len(additions)} legacy keys to plain-code format.")


_migrate_airport_cache()


def ai_lookup_airline_codes(query_code: str):
    """
    Resolve an unknown airline code (2-letter IATA or 3-letter ICAO) via Gemini AI.
    Stores the result bidirectionally so AI is only called once per airline.
    Returns (icao_3, iata_2) or (None, None).
    """
    global _ai_airline_cache, _airline_ai_cooldown_until
    query_code = query_code.upper().strip()

    if len(query_code) not in (2, 3) or not query_code.isalnum():
        return None, None

    now = time.time()
    with _airline_cache_lock:
        cached = _ai_airline_cache.get(query_code)
        if isinstance(cached, str):
            if cached == _AIRLINE_UNKNOWN_SENTINEL:
                return None, None
            return (cached, query_code) if len(query_code) == 2 else (query_code, cached)
        if isinstance(cached, dict):
            retry_after = float(cached.get('retry_after') or 0)
            if retry_after > now:
                return None, None
            _ai_airline_cache.pop(query_code, None)

        if _airline_ai_cooldown_until > now:
            return None, None

    if not AI_AVAILABLE or not AI_CLIENT:
        return None, None

    with _airline_ai_request_lock:
        now = time.time()
        with _airline_cache_lock:
            cached = _ai_airline_cache.get(query_code)
            if isinstance(cached, str):
                if cached == _AIRLINE_UNKNOWN_SENTINEL:
                    return None, None
                return (cached, query_code) if len(query_code) == 2 else (query_code, cached)
            if isinstance(cached, dict):
                retry_after = float(cached.get('retry_after') or 0)
                if retry_after > now:
                    return None, None
                _ai_airline_cache.pop(query_code, None)

            if _airline_ai_cooldown_until > now:
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
                config=genai_types.GenerateContentConfig(
                    candidate_count=1, max_output_tokens=10, temperature=0.0
                ),
            )
            text = (response.text or '').strip().upper()
            if text == 'UNKNOWN' or not text:
                with _airline_cache_lock:
                    _ai_airline_cache[query_code] = _AIRLINE_UNKNOWN_SENTINEL
                    save_json_atomically(AIRLINE_CACHE_FILE, _ai_airline_cache)
                return None, None
            parts = text.split()
            if len(parts) == 2 and len(parts[0]) == 2 and len(parts[1]) == 3:
                iata, icao = parts[0], parts[1]
                with _airline_cache_lock:
                    _ai_airline_cache[iata] = icao
                    _ai_airline_cache[icao] = iata
                    save_json_atomically(AIRLINE_CACHE_FILE, _ai_airline_cache)
                print(f"[AIRLINE-AI] Resolved '{query_code}' → IATA={iata}, ICAO={icao}")
                return icao, iata
        except Exception as e:
            message = str(e)
            if "429" in message or "RESOURCE_EXHAUSTED" in message:
                retry_after = time.time() + _AIRLINE_QUOTA_RETRY_SECONDS
                with _airline_cache_lock:
                    _airline_ai_cooldown_until = retry_after
                    _ai_airline_cache[query_code] = {
                        "error": "quota",
                        "retry_after": retry_after,
                    }
                    save_json_atomically(AIRLINE_CACHE_FILE, _ai_airline_cache)
                print(f"[AIRLINE-AI] Quota hit for '{query_code}', suppressing AI airline lookups for {_AIRLINE_QUOTA_RETRY_SECONDS}s")
            else:
                print(f"[AIRLINE-AI] Lookup failed for '{query_code}': {e}")
    return None, None


def get_airport_display_name(iata_code: str) -> str:
    """
    Return a short display name for an airport IATA code.
    Checks the persistent cache first; calls Gemini AI for anything not cached.
    Falls back to algorithmic suffix stripping.
    """
    if not iata_code:
        return 'UNKNOWN'
    code = iata_code.strip().upper()

    if code in _ai_airport_cache:
        return _ai_airport_cache[code]

    data = (AIRPORTS_DB or {}).get(code, {})
    raw_name = data.get('name', code)
    city = data.get('city', '')

    if AI_AVAILABLE and AI_CLIENT:
        try:
            prompt = (
                f"Shorten the airport name '{raw_name}' (City: {city}) for a compact display ticker.\n"
                "Rules:\n"
                "1. KEEP 'International' if it is part of the airport's distinct identity.\n"
                "2. REMOVE only trailing standalone 'Airport' and generic suffixes like "
                "'Intercontinental', 'Municipal', 'Regional', 'Field'.\n"
                "3. REMOVE the city name only when it adds no info.\n"
                "4. PERSON NAMES: Always use Full Name (First + Last). Never shorten to surname only.\n"
                "5. COLLOQUIAL: Use a famous acronym or nickname when universally known "
                "(e.g. 'JFK', 'Heathrow').\n"
                f"Input to process: {raw_name}"
            )
            response = AI_CLIENT.models.generate_content(
                model='gemini-2.0-flash',
                contents=prompt,
                config=genai_types.GenerateContentConfig(
                    candidate_count=1, max_output_tokens=15, temperature=0.1
                ),
            )
            if response.text:
                short_name = response.text.strip()
                if len(short_name) < len(raw_name) + 5:
                    _ai_airport_cache[code] = short_name
                    save_json_atomically(AIRPORT_CACHE_FILE, _ai_airport_cache)
                    return short_name
        except Exception as e:
            if "429" in str(e):
                print(f"[AI] Quota hit (429) for {code}, using algorithmic fallback.")
            else:
                print(f"[AI] Failed to shorten {code}: {e}")

    # Algorithmic fallback
    replacements = [
        " Intercontinental Airport", " Regional Airport", " Municipal Airport",
        " Intercontinental", " Municipal", " Regional",
        " Airport", " Intl", " Apt", " Field", " Air Force Base", " AFB",
    ]
    clean_name = raw_name
    for phrase in replacements:
        clean_name = re.compile(re.escape(phrase) + r'\s*$', re.IGNORECASE).sub("", clean_name)
    clean_name = clean_name.strip()

    _ai_airport_cache[code] = clean_name
    save_json_atomically(AIRPORT_CACHE_FILE, _ai_airport_cache)
    return clean_name


def get_city_name(iata_code: str) -> str:
    if not iata_code:
        return 'UNKNOWN'
    code = iata_code.strip().upper()
    if not AIRPORTS_DB:
        return code
    if code in AIRPORTS_DB:
        return AIRPORTS_DB[code].get('city', code)
    return code


def lookup_and_auto_fill_airport(airport_code_input: str) -> dict:
    """
    Accept either an IATA (3-char) or ICAO (4-char) code and return complete airport info.
    Returns: {'iata': 'ABE', 'icao': 'KABE', 'name': 'Lehigh Valley International Airport'}
    """
    if not airport_code_input or not AIRPORTS_DB:
        return {'iata': '', 'icao': '', 'name': ''}

    code = airport_code_input.strip().upper()

    if code in AIRPORTS_DB:
        airport_data = AIRPORTS_DB[code]
        iata = code
        icao = airport_data.get('icao', f'K{code}' if len(code) == 3 else '')
        name = airport_data.get('name', airport_data.get('city', code))
        return {'iata': iata, 'icao': icao, 'name': name}

    if len(code) == 4:
        iata_code = _ICAO_TO_IATA_INDEX.get(code)
        if iata_code and iata_code in AIRPORTS_DB:
            airport_data = AIRPORTS_DB[iata_code]
            name = airport_data.get('name', airport_data.get('city', iata_code))
            return {'iata': iata_code, 'icao': code, 'name': name}

    return {'iata': '', 'icao': '', 'name': ''}


def haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Return great-circle distance in nautical miles."""
    import math
    R = 3440.065
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2
         + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2)
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
