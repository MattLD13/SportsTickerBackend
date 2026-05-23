"""Airline/airport lookups backed by Wikidata SPARQL (free, no API key)."""

import csv
import io
import json
import os
import re
import threading
import time

import requests

# Imported from core — available by the time any route loads this module.
from .core import (
    AIRPORTS_DB, AIRPORT_CACHE_FILE, AIRLINE_CACHE_FILE,
    TIMEOUTS, save_json_atomically,
)

# ── Wikidata SPARQL setup (free, no API key, remote) ──
_WIKIDATA_SPARQL = 'https://query.wikidata.org/sparql'
_WIKIDATA_HEADERS = {'User-Agent': 'SportsTicker/1.0 (sports display ticker)'}

AI_CLIENT    = None   # set to 'wikidata' sentinel when reachable
AI_AVAILABLE = False


def _check_wikidata():
    global AI_CLIENT, AI_AVAILABLE
    try:
        # Ping with a trivial 1-result query
        r = requests.get(
            _WIKIDATA_SPARQL,
            params={'query': 'SELECT ?x WHERE { BIND(1 AS ?x) } LIMIT 1', 'format': 'json'},
            headers=_WIKIDATA_HEADERS,
            timeout=5,
        )
        if r.status_code == 200:
            AI_CLIENT    = 'wikidata'
            AI_AVAILABLE = True
            print('[WIKIDATA] Connected — airline/domain lookups enabled')
        else:
            print(f'[WIKIDATA] Responded with status {r.status_code} — lookups disabled')
    except Exception as e:
        print(f'[WIKIDATA] Not reachable ({e}) — lookups disabled')


_check_wikidata()


def _wikidata_query(sparql: str) -> list:
    """Run a SPARQL query against Wikidata. Returns list of binding dicts or []."""
    try:
        r = requests.get(
            _WIKIDATA_SPARQL,
            params={'query': sparql, 'format': 'json'},
            headers=_WIKIDATA_HEADERS,
            timeout=10,
        )
        if r.status_code == 200:
            return r.json().get('results', {}).get('bindings', [])
    except Exception:
        pass
    return []


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

# ── Persistent caches ──
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
_airline_cache_lock   = threading.RLock()
_airline_lookup_lock  = threading.Lock()
_AIRLINE_UNKNOWN_SENTINEL = "__UNKNOWN__"


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
    Resolve an unknown airline code (2-letter IATA or 3-letter ICAO) via Wikidata.
    Stores the result bidirectionally so Wikidata is only queried once per airline.
    Returns (icao_3, iata_2) or (None, None).
    """
    query_code = query_code.upper().strip()
    if len(query_code) not in (2, 3) or not query_code.isalnum():
        return None, None

    with _airline_cache_lock:
        cached = _ai_airline_cache.get(query_code)
        if isinstance(cached, str):
            if cached == _AIRLINE_UNKNOWN_SENTINEL:
                return None, None
            return (cached, query_code) if len(query_code) == 2 else (query_code, cached)

    if not AI_AVAILABLE:
        return None, None

    with _airline_lookup_lock:
        # Re-check cache after acquiring lock
        with _airline_cache_lock:
            cached = _ai_airline_cache.get(query_code)
            if isinstance(cached, str):
                if cached == _AIRLINE_UNKNOWN_SENTINEL:
                    return None, None
                return (cached, query_code) if len(query_code) == 2 else (query_code, cached)

        try:
            if len(query_code) == 2:
                # IATA → ICAO
                sparql = f"""
SELECT ?icao WHERE {{
  ?airline wdt:P229 "{query_code}" .
  ?airline wdt:P230 ?icao .
}}
LIMIT 1"""
                rows = _wikidata_query(sparql)
                if rows:
                    icao = rows[0].get('icao', {}).get('value', '').upper()
                    if len(icao) == 3:
                        with _airline_cache_lock:
                            _ai_airline_cache[query_code] = icao
                            _ai_airline_cache[icao] = query_code
                            save_json_atomically(AIRLINE_CACHE_FILE, _ai_airline_cache)
                        print(f"[WIKIDATA] {query_code} → ICAO={icao}")
                        return icao, query_code
            else:
                # ICAO → IATA
                sparql = f"""
SELECT ?iata WHERE {{
  ?airline wdt:P230 "{query_code}" .
  ?airline wdt:P229 ?iata .
}}
LIMIT 1"""
                rows = _wikidata_query(sparql)
                if rows:
                    iata = rows[0].get('iata', {}).get('value', '').upper()
                    if len(iata) == 2:
                        with _airline_cache_lock:
                            _ai_airline_cache[query_code] = iata
                            _ai_airline_cache[iata] = query_code
                            save_json_atomically(AIRLINE_CACHE_FILE, _ai_airline_cache)
                        print(f"[WIKIDATA] {query_code} → IATA={iata}")
                        return query_code, iata

            with _airline_cache_lock:
                _ai_airline_cache[query_code] = _AIRLINE_UNKNOWN_SENTINEL
                save_json_atomically(AIRLINE_CACHE_FILE, _ai_airline_cache)
        except Exception as e:
            print(f"[WIKIDATA] Airline code lookup failed for '{query_code}': {e}")

    return None, None


def ai_lookup_airline_domain(airline_code: str) -> str:
    """
    Return the official website domain for an airline IATA or ICAO code via Wikidata.
    Results are cached persistently so Wikidata is only queried once per airline.
    Returns a bare domain string like 'united.com', or '' if unknown.
    """
    code = airline_code.upper().strip()
    if not code or not code.isalnum() or len(code) not in (2, 3):
        return ''

    cache_key = f"{code}_domain"
    with _airline_cache_lock:
        cached = _ai_airline_cache.get(cache_key)
        if isinstance(cached, str):
            return '' if cached == _AIRLINE_UNKNOWN_SENTINEL else cached

    if not AI_AVAILABLE:
        return ''

    with _airline_lookup_lock:
        with _airline_cache_lock:
            cached = _ai_airline_cache.get(cache_key)
            if isinstance(cached, str):
                return '' if cached == _AIRLINE_UNKNOWN_SENTINEL else cached

        try:
            prop = 'P229' if len(code) == 2 else 'P230'
            sparql = f"""
SELECT ?website WHERE {{
  ?airline wdt:{prop} "{code}" .
  ?airline wdt:P856 ?website .
}}
LIMIT 1"""
            rows = _wikidata_query(sparql)
            if rows:
                url = rows[0].get('website', {}).get('value', '')
                url = re.sub(r'^https?://', '', url)
                url = re.sub(r'^www\.', '', url)
                domain = url.split('/')[0].strip().lower()
                if domain and '.' in domain:
                    with _airline_cache_lock:
                        _ai_airline_cache[cache_key] = domain
                        save_json_atomically(AIRLINE_CACHE_FILE, _ai_airline_cache)
                    print(f"[WIKIDATA] Domain for '{code}' → '{domain}'")
                    return domain

            with _airline_cache_lock:
                _ai_airline_cache[cache_key] = _AIRLINE_UNKNOWN_SENTINEL
                save_json_atomically(AIRLINE_CACHE_FILE, _ai_airline_cache)
        except Exception as e:
            print(f"[WIKIDATA] Domain lookup failed for '{code}': {e}")

    return ''


def get_airport_display_name(iata_code: str) -> str:
    """
    Return a short display name for an airport IATA code.
    Checks persistent cache first, then applies algorithmic suffix stripping.
    """
    if not iata_code:
        return 'UNKNOWN'
    code = iata_code.strip().upper()

    if code in _ai_airport_cache:
        return _ai_airport_cache[code]

    data = (AIRPORTS_DB or {}).get(code, {})
    raw_name = data.get('name', code)

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
