# ── Standard library ──
import glob
import json
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
from dotenv import load_dotenv

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

try:
    from FlightRadar24.api import FlightRadar24API
    FR24_SDK_AVAILABLE = True
except ImportError:
    FR24_SDK_AVAILABLE = False

load_dotenv()

# ================= SERVER VERSION =================
def _compute_version():
    import subprocess as _sp
    try:
        count = _sp.check_output(
            ["git", "rev-list", "--count", "HEAD"],
            cwd=os.path.dirname(os.path.dirname(__file__)),
            stderr=_sp.DEVNULL, text=True,
        ).strip()
        sha = _sp.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=os.path.dirname(os.path.dirname(__file__)),
            stderr=_sp.DEVNULL, text=True,
        ).strip()
        date = _sp.check_output(
            ["git", "log", "-1", "--format=%cd", "--date=format:%Y.%m.%d"],
            cwd=os.path.dirname(os.path.dirname(__file__)),
            stderr=_sp.DEVNULL, text=True,
        ).strip()
        return f"r{count}+{sha}", date, int(count), sha
    except Exception:
        return "r0+unknown", "unknown", 0, "unknown"

_VERSION_SHORT, _VERSION_DATE, _VERSION_BUILD, _VERSION_HASH = _compute_version()
SERVER_VERSION = f"{_VERSION_DATE} · build {_VERSION_SHORT}"

# ── Section A: Logging ──
class Tee(object):
    verbose_debug: bool = False

    def __init__(self, name, mode):
        self.file = open(name, mode, buffering=1, encoding='utf-8')
        self.original_stdout = sys.stdout
        self.original_stderr = sys.stderr
        self._lock = threading.Lock()
        self.stdout = self
        self.stderr = self

    def write(self, data):
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

# ── Section C: Constants ──
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

TIMEOUTS = {
    'default': 7,
    'quick':   3,
    'stock':   5,
    'slow':    10,
}

CACHE_TTL = {
    'weather': 900,
    'flight':  600,
    'stock':   30,
}

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

# Re-export static lookup tables so fetchers (using globals().update(vars(_core)))
# continue to find them without any changes to the fetcher files.
from .lookups import (
    HEADERS, FOTMOB_LEAGUE_MAP, TZ_OFFSETS, KNOTS_TO_MPH,
    _AIRCRAFT_TYPE_NAMES, normalize_aircraft_type,
    FBS_TEAMS, FCS_TEAMS, SOCCER_ABBR_OVERRIDES, LOGO_OVERRIDES,
    ABBR_MAPPING, SOCCER_COLOR_FALLBACK, SPORT_DURATIONS, WMO_DESCRIPTIONS,
)

# ── Section D: Category helpers ──
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
    'test_mode':        False,
    'test_spotify':     False,
    'test_stocks':      False,
    'test_sports_date': False,
    'test_flights':     False,
    'weather_city': "New York",
    'weather_lat': 40.7128,
    'weather_lon': -74.0060,
    'utc_offset': -5,
    'show_debug_options': False,
    'track_flight_id': '',
    'track_guest_name': '',
    'airport_code_icao': 'KEWR',
    'airport_code_iata': 'EWR',
    'airport_name': 'Newark Liberty International',
    'airline_filter': '',
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
    "timezone_name": "",
}

# ── Section F: Boot / Config Load ──
state = default_state.copy()
tickers = {}

# 1. Load Global Config
if os.path.exists(GLOBAL_CONFIG_FILE):
    try:
        with open(GLOBAL_CONFIG_FILE, 'r') as f:
            config_data = json.load(f)
        config_data['mode'] = MODE_MIGRATIONS.get(config_data.get('mode', 'sports'), config_data.get('mode', 'sports'))
        if config_data.get('flight_submode') == 'track':
            config_data['mode'] = 'flight_tracker'
        elif config_data.get('flight_submode') == 'airport' and config_data.get('mode') == 'flight_tracker':
            config_data['mode'] = 'flights'
        config_data.pop('flight_submode', None)
        config_data['airline_filter'] = ''
        for k, v in config_data.items():
            if k in state:
                if isinstance(state[k], dict) and isinstance(v, dict):
                    state[k].update(v)
                else:
                    state[k] = v
        if 'flight_submode' in config_data or config_data.get('airline_filter', '') != '':
            with open(GLOBAL_CONFIG_FILE, 'w') as _f:
                json.dump(config_data, _f, indent=4)
            print("🧹 Migrated legacy keys in global config")
    except Exception as e:
        print(f"⚠️ Error loading global config: {e}")

state['my_teams'] = []

# Reconcile active_sports against current LEAGUE_OPTIONS
_valid_league_ids = {item['id'] for item in LEAGUE_OPTIONS}
_deprecated_leagues = []
for _k in list(state['active_sports'].keys()):
    if _k not in _valid_league_ids:
        del state['active_sports'][_k]
        _deprecated_leagues.append(_k)
for _item in LEAGUE_OPTIONS:
    if _item['id'] not in state['active_sports']:
        state['active_sports'][_item['id']] = _item['default']

if _deprecated_leagues:
    print(f"🧹 Removed deprecated leagues: {', '.join(_deprecated_leagues)}")
_deprecated_leagues_pending_save = bool(_deprecated_leagues)

state['mode'] = MODE_MIGRATIONS.get(state.get('mode', 'sports'), state.get('mode', 'sports'))
if state['mode'] not in VALID_MODES:
    state['mode'] = 'sports'
state['airline_filter'] = ''

# 2. Load Individual Ticker Files
ticker_files = glob.glob(os.path.join(TICKER_DATA_DIR, "*.json"))
print(f"📂 Found {len(ticker_files)} saved tickers in '{TICKER_DATA_DIR}'")

for t_file in ticker_files:
    try:
        with open(t_file, 'r') as f:
            t_data = json.load(f)
            tid = os.path.splitext(os.path.basename(t_file))[0]
            if 'settings' not in t_data: t_data['settings'] = DEFAULT_TICKER_SETTINGS.copy()
            for _sk, _sv in DEFAULT_TICKER_SETTINGS.items():
                t_data['settings'].setdefault(_sk, _sv)
            t_data['settings'].pop('active_sports', None)
            if 'my_teams' not in t_data: t_data['my_teams'] = None
            elif t_data.get('my_teams') == []: t_data['my_teams'] = None
            if 'clients' not in t_data: t_data['clients'] = []
            tickers[tid] = t_data
    except Exception as e:
        print(f"❌ Failed to load ticker file {t_file}: {e}")

# Pre-populate current_games from cache for immediate display on restart
if os.path.exists(GAME_CACHE_FILE):
    try:
        with open(GAME_CACHE_FILE, 'r') as _gcf:
            _cached = json.load(_gcf)
        if isinstance(_cached, list) and _cached:
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
    temp = f"{filepath}.tmp"
    try:
        with open(temp, 'w') as f:
            json.dump(data, f, indent=4)
        os.replace(temp, filepath)
    except Exception as e:
        print(f"Write error for {filepath}: {e}")


def save_global_config():
    try:
        with data_lock:
            export_data = {
                'active_sports': state['active_sports'],
                'mode': state['mode'],
                'weather_city': state['weather_city'],
                'weather_lat': state['weather_lat'],
                'weather_lon': state['weather_lon'],
                'utc_offset': state['utc_offset'],
                'track_flight_id': state.get('track_flight_id', ''),
                'track_guest_name': state.get('track_guest_name', ''),
                'airport_code_icao': state.get('airport_code_icao', 'KEWR'),
                'airport_code_iata': state.get('airport_code_iata', 'EWR'),
                'airport_name': state.get('airport_name', 'Newark Liberty International'),
                'airline_filter': '',
            }
        save_json_atomically(GLOBAL_CONFIG_FILE, export_data)
    except Exception as e:
        print(f"Error saving global config: {e}")


if _deprecated_leagues_pending_save:
    save_global_config()


def save_specific_ticker(tid):
    if tid not in tickers: return
    try:
        filepath = os.path.join(TICKER_DATA_DIR, f"{tid}.json")
        save_json_atomically(filepath, tickers[tid])
        print(f"💾 Saved Ticker: {tid}")
    except Exception as e:
        print(f"Error saving ticker {tid}: {e}")


def save_config_file():
    save_global_config()


# ── Section H: Pairing / Ticker Helpers ──
def generate_pairing_code():
    while True:
        code = ''.join(random.choices(string.digits, k=6))
        active_codes = {t.get('pairing_code') for t in tickers.values() if not t.get('paired')}
        if code not in active_codes: return code


def create_ticker_record(name="Ticker", client_id=None, paired=True):
    rec = {
        "name": name,
        "settings": DEFAULT_TICKER_SETTINGS.copy(),
        "my_teams": None,
        "clients": [client_id] if client_id else [],
        "paired": paired,
        "pairing_code": generate_pairing_code(),
        "last_seen": time.time(),
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

# ── Section I: Utilities ──
def safe_get(obj, *keys, default=None):
    cur = obj
    for key in keys:
        if not isinstance(cur, dict):
            return default
        cur = cur.get(key)
        if cur is None:
            return default
    return cur if cur is not None else default


def parse_iso(s: str) -> dt:
    if not s:
        raise ValueError("Empty datetime string")
    return dt.fromisoformat(s.replace('Z', '+00:00'))


def _blank_logo_url_for_request(req) -> str:
    return BLANK_LOGO_URL


def _materialize_blank_logo_urls(games: list, req) -> None:
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
    r = session.get(
        url,
        params=params or {},
        headers=headers or {},
        timeout=timeout or TIMEOUTS['default'],
    )
    r.raise_for_status()
    return r.json()

# ── Re-exports from split modules ──
# These deferred imports run after all core names are defined, so the one-way
# dependency (ai_services/timezone → core) does not create a real circle.
from .ai_services import (                                      # noqa: E402
    _IATA_TO_ICAO, _ICAO_TO_IATA, _ICAO_TO_IATA_INDEX,
    ai_lookup_airline_codes, get_airport_display_name, get_city_name,
    lookup_and_auto_fill_airport, haversine,
    AI_CLIENT, AI_AVAILABLE,
)
from .timezone import (                                         # noqa: E402
    _get_ticker_timezone_context, _apply_ticker_timezone,
    _maybe_update_ticker_timezone_from_request, _apply_timezone_to_game_times,
    _extract_client_ip, _extract_timezone_from_request_headers,
    _lookup_timezone_for_ip, _lookup_timezone_for_current_connection,
    _lookup_timezone_for_latlon,
)
