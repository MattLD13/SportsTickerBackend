"""Nürburgring 24h live timing fetcher — Azure WebSocket timing system."""

import json
import re
import threading
import time

try:
    import websocket as _websocket_lib
    _WS_AVAILABLE = True
except ImportError:
    _WS_AVAILABLE = False
    print('[N24] websocket-client not installed; run: pip install websocket-client')

from ..lookups import (
    RACING_MANUFACTURER_COLORS as MANUFACTURER_COLORS,
    RACING_CLASS_COLORS         as CLASS_COLORS,
    _RACING_DEFAULT_MFR,
    _RACING_DEFAULT_CLASS,
)

# ---------------------------------------------------------------------------
# Track state mapping  (N24 / Nürburgring-specific codes included)
# ---------------------------------------------------------------------------

_TRACK_STATES = {
    # Standard codes
    '0':  ('green',       'GREEN FLAG',         '#00C040'),
    '1':  ('yellow',      'YELLOW FLAG',        '#FFD000'),
    '2':  ('safety_car',  'SAFETY CAR',         '#2060FF'),
    '3':  ('red',         'RED FLAG',           '#FF2020'),
    '4':  ('vsc',         'VIRTUAL SAFETY CAR', '#8888FF'),
    '5':  ('fcy',         'FULL COURSE YELLOW', '#FFB000'),
    '6':  ('chequered',   'CHEQUERED FLAG',     '#CCCCCC'),
    # Nürburgring-specific
    '60': ('code60',      'CODE 60',            '#00BBFF'),  # slow-zone 60 km/h
    '7':  ('code60',      'CODE 60',            '#00BBFF'),  # alt numeric code
    '8':  ('noz',         'NO OVERTAKING',      '#FF8C00'),  # no-overtaking zone
    '9':  ('caution',     'CAUTION',            '#FFCC00'),
    '10': ('pit_closed',  'PIT LANE CLOSED',    '#FF6600'),
    '11': ('medical_car', 'MEDICAL CAR',        '#FF4488'),
}

def track_state_info(code: str) -> dict:
    key, name, color = _TRACK_STATES.get(str(code), ('unknown', f'STATE {code}', '#666666'))
    return {'code': code, 'key': key, 'name': name, 'color': color}


# Sector-level flag parsing from RC message text
_SECTOR_PATTERNS = [
    # "CODE 60 ZONE SECTOR 3-5" / "CODE 60 S4" / "SC60 SECTORS 2,3"
    (r'(?:code\s*60|sc\s*60)\s+(?:zone\s+)?(?:sector[s]?\s*)?([0-9][0-9\-,\s]*)',
     'code60', '#00BBFF'),
    # "DOUBLE WAVED YELLOW S4-S5" / "YELLOW FLAG SECTOR 3"
    (r'(?:double\s+waved\s+yellow|yellow\s+flag)\s+(?:sector[s]?\s*)?([0-9][0-9\-,\s]*)',
     'yellow', '#FFD000'),
    # "SECTOR 6 CLEAR" / "CODE 60 CANCELLED SECTOR 3"
    (r'(?:code\s*60\s+cancel|sector\s+clear)\s+(?:sector[s]?\s*)?([0-9][0-9\-,\s]*)',
     'green', '#00C040'),
]

def parse_sector_flags(messages: list) -> dict:
    """Return a dict mapping sector numbers 1-9 to flag info dicts.

    Processes RC messages newest-first to build current sector state.
    """
    import re
    sector_state = {}   # sector_num → flag_info_dict

    for msg_obj in messages:
        text = str(msg_obj.get('MESSAGE', '') or '').lower()
        for pattern, flag_key, color in _SECTOR_PATTERNS:
            m = re.search(pattern, text, re.IGNORECASE)
            if m:
                # Extract sector numbers from the match group
                raw = m.group(1)
                nums = re.findall(r'\d+', raw)
                if len(nums) == 2 and int(nums[0]) <= 9 and int(nums[1]) <= 9:
                    sectors = list(range(int(nums[0]), int(nums[1]) + 1))
                elif len(nums) == 1:
                    sectors = [int(nums[0])]
                else:
                    sectors = [int(n) for n in nums if 1 <= int(n) <= 9]
                for s in sectors:
                    if s not in sector_state:   # newest message wins
                        sector_state[s] = {'key': flag_key, 'color': color}
                break

    return sector_state


# ---------------------------------------------------------------------------
# Helper utilities
# ---------------------------------------------------------------------------

def make_driver_acronym(name: str) -> str:
    """Return a 3-letter racing acronym for a driver name.

    Single surname (as in the timing feed): first 3 letters.
    Full name 'First Last': first letter of first + first two of last.
    """
    name = name.strip()
    if not name:
        return '???'
    parts = name.split()
    if len(parts) >= 2:
        return (parts[0][0] + parts[-1][:2]).upper()
    return parts[0][:3].upper()


def extract_manufacturer(text: str) -> str | None:
    if not text:
        return None
    low = text.lower()
    for name in sorted(MANUFACTURER_COLORS, key=len, reverse=True):
        if name in low:
            return name
    return None


def get_manufacturer_colors(manufacturer: str | None) -> dict:
    if not manufacturer:
        return _RACING_DEFAULT_MFR
    return MANUFACTURER_COLORS.get(manufacturer.strip().lower(), _RACING_DEFAULT_MFR)


def get_class_colors(class_name: str | None) -> dict:
    if not class_name:
        return _RACING_DEFAULT_CLASS
    upper = class_name.strip().upper()
    if upper in CLASS_COLORS:
        return CLASS_COLORS[upper]
    for k in CLASS_COLORS:
        if upper.startswith(k) or k.startswith(upper):
            return CLASS_COLORS[k]
    return _RACING_DEFAULT_CLASS


def _parse_rc_flag(message: str) -> str:
    """Infer a flag key from a race control message string."""
    low = message.lower()
    if 'code 60' in low or 'sc60' in low or 'code60' in low:
        return 'code60'
    if 'virtual safety car' in low or ' vsc ' in low:
        return 'vsc'
    if 'safety car' in low or 'sc deployed' in low:
        return 'safety_car'
    if 'red flag' in low or 'race stopped' in low:
        return 'red'
    if 'full course yellow' in low or ' fcy' in low:
        return 'fcy'
    if 'pit lane closed' in low or 'pit closed' in low:
        return 'pit_closed'
    if 'no overtaking' in low or 'noz' in low:
        return 'noz'
    if 'medical car' in low:
        return 'medical_car'
    if 'double waved yellow' in low or 'double yellow' in low:
        return 'yellow'
    if 'yellow flag' in low:
        return 'yellow'
    if 'green flag' in low or 'track clear' in low or 'safety car in this lap' in low:
        return 'green'
    return ''


# ---------------------------------------------------------------------------
# Fetcher
# ---------------------------------------------------------------------------

class NurburgringFetcher:
    """Live timing via the Azure WebSocket push system at livetiming.azurewebsites.net."""

    _WS_URL   = 'wss://livetiming.azurewebsites.net'
    _EVENT_ID = '50'   # 2026 54. ADAC RAVENOL 24h Nürburgring
    _PIDS     = [0, 3, 4]  # standings, race control messages, track state

    def __init__(self):
        self._lock      = threading.Lock()
        self._cache: dict | None = None
        self._entries: list = []
        self._rc_messages: list = []
        self._track_state_code: str = '0'
        self._event_name: str = '54. ADAC RAVENOL 24h Nürburgring'
        self._connected: bool = False
        self._ws_thread: threading.Thread | None = None
        # External override for event ID (set by /api/n24/event endpoint)
        self.manual_event_id: str | None = None
        if _WS_AVAILABLE:
            self._start_ws()

    # ------------------------------------------------------------------
    # WebSocket connection management
    # ------------------------------------------------------------------

    @property
    def _active_event_id(self) -> str:
        return self.manual_event_id or self._EVENT_ID

    def _start_ws(self):
        if self._ws_thread and self._ws_thread.is_alive():
            return
        self._ws_thread = threading.Thread(
            target=self._ws_loop, daemon=True, name='n24_ws')
        self._ws_thread.start()

    def _ws_loop(self):
        while True:
            try:
                ws = _websocket_lib.WebSocketApp(
                    self._WS_URL,
                    on_open=self._on_open,
                    on_message=self._on_message,
                    on_error=self._on_error,
                    on_close=self._on_close,
                )
                ws.run_forever(ping_interval=30, ping_timeout=10)
            except Exception as exc:
                print(f'[N24] WS loop error: {exc}')
            self._connected = False
            time.sleep(5)

    def _on_open(self, ws):
        self._connected = True
        print(f'[N24] WebSocket connected (event {self._active_event_id})')
        ws.send(json.dumps({
            'eventId':        self._active_event_id,
            'eventPid':       self._PIDS,
            'clientLocalTime': int(time.time() * 1000),
        }))

    def _on_message(self, ws, message):
        try:
            data = json.loads(message)
            pid  = str(data.get('PID', ''))
            if pid == 'LTS_TIMESYNC':
                pass
            elif pid == 'LTS_NOT_FOUND':
                print(f'[N24] event {self._active_event_id} not found on server')
            elif pid == '0':
                self._ingest_standings(data)
            elif pid == '3':
                self._ingest_racecontrol(data)
            elif pid == '4':
                self._ingest_trackstate(data)
        except Exception as exc:
            print(f'[N24] message error: {exc}')

    def _on_error(self, ws, error):
        print(f'[N24] WS error: {error}')

    def _on_close(self, ws, code, msg):
        self._connected = False
        print(f'[N24] WS closed (code={code})')

    # ------------------------------------------------------------------
    # PID processors
    # ------------------------------------------------------------------

    def _ingest_standings(self, data: dict):
        raw_entries = data.get('RESULT', [])
        if not raw_entries:
            return

        parsed = [self._parse_entry(e) for e in raw_entries]
        parsed = [e for e in parsed if e]

        # Enrich with colour data
        for entry in parsed:
            mfr = entry.get('manufacturer')
            entry['manufacturer_colors'] = get_manufacturer_colors(mfr)
            entry['class_colors']        = get_class_colors(entry.get('class_name', ''))

        leader_laps = parsed[0].get('laps', 0) if parsed else 0
        event_name  = data.get('CUP') or self._event_name
        if event_name:
            self._event_name = event_name

        with self._lock:
            self._entries = parsed
            self._cache = self._build_cache(leader_laps)

    def _ingest_racecontrol(self, data: dict):
        messages = data.get('MESSAGES', [])
        if not isinstance(messages, list):
            return
        with self._lock:
            self._rc_messages = messages  # server sends full history
            if self._cache is not None:
                self._cache['race_control'] = self._recent_rc()

    def _ingest_trackstate(self, data: dict):
        with self._lock:
            self._track_state_code = str(data.get('TRACKSTATE', '0'))
            if self._cache is not None:
                ts = track_state_info(self._track_state_code)
                self._cache['track_state']      = self._track_state_code
                self._cache['track_state_name'] = ts['name']
                self._cache['track_state_color'] = ts['color']

    # ------------------------------------------------------------------
    # Entry parser
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_entry(e: dict) -> dict | None:
        if not e:
            return None
        car     = str(e.get('CAR', '') or '')
        surname = str(e.get('NAME', '') or '').strip()
        return {
            'pos':                    str(e.get('POSITION', '?') or '?'),
            'car_num':                str(e.get('STNR',     '?') or '?'),
            'class_name':             str(e.get('CLASSNAME','') or ''),
            'team':                   str(e.get('TEAM',     '') or ''),
            'car':                    car,
            'drivers':                [surname] if surname else [],
            'driver_acronyms':        [make_driver_acronym(surname)] if surname else ['???'],
            'current_driver':         surname,
            'current_driver_acronym': make_driver_acronym(surname),
            'laps':                   int(e.get('LAPS', 0)         or 0),
            'gap':                    str(e.get('GAP',  '')        or ''),
            'last_lap':               str(e.get('LASTLAPTIME', '') or ''),
            'best_lap':               str(e.get('FASTESTLAP',  '') or ''),
            'manufacturer':           extract_manufacturer(car),
            'pit_stops':              int(e.get('PITSTOPCOUNT', 0) or 0),
            'pro_am':                 str(e.get('PRO', '')         or ''),
        }

    # ------------------------------------------------------------------
    # Cache builder
    # ------------------------------------------------------------------

    def _recent_rc(self) -> list:
        """Return the 50 most recent RC messages, newest first."""
        msgs = self._rc_messages
        try:
            msgs = sorted(msgs, key=lambda m: int(m.get('ID', 0)), reverse=True)
        except Exception:
            msgs = list(reversed(msgs))
        return msgs[:50]

    def _build_cache(self, leader_laps: int) -> dict:
        ts      = track_state_info(self._track_state_code)
        rc      = self._recent_rc()
        sec_map = parse_sector_flags(rc)
        return {
            'source':            'n24_livetiming_ws',
            'event_id':          self._active_event_id,
            'event_name':        self._event_name,
            'status':            'live',
            'leader_laps':       leader_laps,
            'entries':           self._entries,
            'race_control':      rc,
            'track_state':       self._track_state_code,
            'track_state_name':  ts['name'],
            'track_state_color': ts['color'],
            'track_state_key':   ts['key'],
            'sector_flags':      sec_map,  # {1: {key, color}, ...}
            'fetched_at':        time.time(),
        }

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def fetch(self) -> dict | None:
        if _WS_AVAILABLE:
            self._start_ws()  # no-op if thread already alive
        with self._lock:
            return self._cache

    def enrich(self, data: dict) -> dict:
        """Add colour data to entries in-place (already done by _ingest_standings)."""
        for entry in data.get('entries', []):
            if 'manufacturer_colors' not in entry:
                entry['manufacturer_colors'] = get_manufacturer_colors(entry.get('manufacturer'))
            if 'class_colors' not in entry:
                entry['class_colors'] = get_class_colors(entry.get('class_name', ''))
        return data

    def format_for_ticker(self, data: dict | None) -> list[dict]:
        """Return controller-ready game objects from fetched data.

        Prepends a single 'n24_rc' track-state card so the LED feed always
        shows the current flag status before the car standings.
        """
        if not data:
            return []

        games = []

        # ── Track-state / race-control card ─────────────────────────────
        rc_msgs   = data.get('race_control', [])
        latest_rc = rc_msgs[0].get('MESSAGE', '') if rc_msgs else ''
        ts_name   = data.get('track_state_name', 'GREEN FLAG')
        ts_color  = data.get('track_state_color', '#00C040')
        ts_key    = data.get('track_state_key', 'green')
        games.append({
            'id':               'n24_rc',
            'type':             'n24_rc',
            'sport':            'n24',
            'event_name':       data.get('event_name', 'N24'),
            'track_state':      data.get('track_state', '0'),
            'track_state_name': ts_name,
            'track_state_color': ts_color,
            'track_state_key':  ts_key,
            'latest_message':   latest_rc,
            'messages':         [m.get('MESSAGE', '') for m in rc_msgs[:5]],
            'leader_laps':      data.get('leader_laps', 0),
            # Compatibility
            'home_abbr': 'N24', 'away_abbr': 'RC',
            'home_score': ts_key.upper()[:4], 'away_score': '',
            'status': ts_name,
        })

        # ── Car entries ──────────────────────────────────────────────────
        for entry in data.get('entries', []):
            games.append({
                'id':                     f"n24_{entry.get('car_num', '?')}",
                'type':                   'n24_car',
                'sport':                  'n24',
                'event_name':             data.get('event_name', 'N24'),
                'pos':                    entry.get('pos', '?'),
                'car_num':                entry.get('car_num', '?'),
                'class_name':             entry.get('class_name', ''),
                'team':                   entry.get('team', ''),
                'car':                    entry.get('car', ''),
                'drivers':                entry.get('drivers', []),
                'driver_acronyms':        entry.get('driver_acronyms', []),
                'current_driver':         entry.get('current_driver', ''),
                'current_driver_acronym': entry.get('current_driver_acronym', '???'),
                'laps':                   entry.get('laps', 0),
                'gap':                    entry.get('gap', ''),
                'last_lap':               entry.get('last_lap', ''),
                'best_lap':               entry.get('best_lap', ''),
                'manufacturer':           entry.get('manufacturer'),
                'manufacturer_colors':    entry.get('manufacturer_colors', _RACING_DEFAULT_MFR),
                'class_colors':           entry.get('class_colors', _RACING_DEFAULT_CLASS),
                'pit_stops':              entry.get('pit_stops', 0),
                'pro_am':                 entry.get('pro_am', ''),
                # Compatibility
                'home_abbr':  entry.get('team', '')[:8],
                'away_abbr':  entry.get('car_num', '?'),
                'home_score': str(entry.get('laps', 0)),
                'away_score': entry.get('gap', ''),
                'status':     entry.get('class_name', ''),
            })
        return games


# Module-level singleton — imported by routes and workers
n24_fetcher = NurburgringFetcher()
