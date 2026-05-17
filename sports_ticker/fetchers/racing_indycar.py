"""IndyCar live timing fetcher — HTTP polling against IndyCar's scoring API.

Supports all IndyCar session types: Race, Practice, Qualifying.
Indy 500-specific: 200-lap race distance tracking, starting grid, bump day.

Endpoint URL can be overridden via the /api/indycar/event admin route.
"""

import json
import threading
import time
import urllib.request

from ..lookups import (
    RACING_MANUFACTURER_COLORS as MANUFACTURER_COLORS,
    _RACING_DEFAULT_MFR,
    _RACING_DEFAULT_CLASS,
)

# ---------------------------------------------------------------------------
# Flag / track state mapping  (IndyCar-specific)
# ---------------------------------------------------------------------------

_FLAG_STATES = {
    '0':  ('green',      'GREEN',             '#00C040'),
    '1':  ('yellow',     'CAUTION',           '#FFD000'),
    '2':  ('red',        'RED FLAG',          '#FF2020'),
    '3':  ('checkered',  'CHECKERED FLAG',    '#CCCCCC'),
    '4':  ('white',      'WHITE FLAG',        '#FFFFFF'),
    '8':  ('yellow',     'CAUTION',           '#FFD000'),
    # Text-based keys returned by some feed versions
    'green':      ('green',      'GREEN',             '#00C040'),
    'yellow':     ('yellow',     'CAUTION',           '#FFD000'),
    'caution':    ('yellow',     'CAUTION',           '#FFD000'),
    'red':        ('red',        'RED FLAG',          '#FF2020'),
    'checkered':  ('checkered',  'CHECKERED FLAG',    '#CCCCCC'),
    'white':      ('white',      'WHITE FLAG',        '#FFFFFF'),
    'warmup':     ('green',      'WARMUP',            '#4488FF'),
    'cooldown':   ('yellow',     'COOLDOWN',          '#FFAA00'),
}

_SESSION_LABELS = {
    'race':         'RACE',
    'practice':     'PRACTICE',
    'qualifying':   'QUALIFYING',
    'qualifying1':  'QUALIFYING',
    'qualifying2':  'BUMP DAY',
    'warmup':       'WARMUP',
}

# Engine supplier colors (replaces car-class concept)
_ENGINE_COLORS = {
    'chevrolet': {
        'bg':    '#FFB81C',
        'text':  '#1A1A1A',
        'label': 'CHEVY',
        'primary':   '#FFB81C',
        'secondary': '#D49B00',
        'accent':    '#FFFFFF',
    },
    'honda': {
        'bg':    '#CC0000',
        'text':  '#FFFFFF',
        'label': 'HONDA',
        'primary':   '#CC0000',
        'secondary': '#990000',
        'accent':    '#FFFFFF',
    },
}
_ENGINE_DEFAULT = {
    'bg': '#2A3A4A', 'text': '#CCCCDD', 'label': '?',
    'primary': '#2A3A4A', 'secondary': '#4A6A8A', 'accent': '#AABBCC',
}

# Default scoring endpoint — updated each season as needed
_DEFAULT_SCORING_URL = 'https://racecontrol.indycar.com/scoring/live'


def flag_state_info(raw: str) -> dict:
    key = str(raw).strip().lower()
    entry = _FLAG_STATES.get(key) or _FLAG_STATES.get('0')
    k, name, color = entry
    return {'raw': raw, 'key': k, 'name': name, 'color': color}


def get_engine_colors(engine: str | None) -> dict:
    if not engine:
        return _ENGINE_DEFAULT
    return _ENGINE_COLORS.get(engine.strip().lower(), _ENGINE_DEFAULT)


def _parse_driver_name(raw: str) -> str:
    """Normalize 'Power, Will' → 'Will Power' or pass through."""
    if not raw:
        return ''
    raw = raw.strip()
    if ',' in raw:
        parts = [p.strip() for p in raw.split(',', 1)]
        return f'{parts[1]} {parts[0]}'
    return raw


def _driver_acronym(name: str) -> str:
    name = name.strip()
    if not name:
        return '???'
    parts = name.split()
    if len(parts) >= 2:
        return (parts[0][0] + parts[-1][:2]).upper()
    return parts[0][:3].upper()


def _detect_session_type(raw: str | None) -> str:
    if not raw:
        return 'race'
    low = raw.strip().lower()
    if 'qual' in low:
        if 'bump' in low or '2' in low:
            return 'qualifying2'
        return 'qualifying'
    if 'practice' in low or 'warmup' in low or 'warm' in low or 'carb' in low:
        return 'practice'
    return 'race'


# ---------------------------------------------------------------------------
# Response parsers — handle multiple known IndyCar feed formats
# ---------------------------------------------------------------------------

def _parse_v1(data: dict) -> tuple[list, dict, str, str]:
    """Parse IndyCar's primary scoring JSON format.

    Returns (entries, flag_info, session_type, event_name).
    """
    # Top-level keys vary: "Race"/"Session"/"race" etc.
    race_info = (data.get('Race') or data.get('Session') or
                 data.get('race') or data.get('session') or {})

    raw_flag = (race_info.get('FlagState') or race_info.get('flagState') or
                race_info.get('flag_state') or '0')
    session_raw = (race_info.get('SessionType') or race_info.get('sessionType') or
                   race_info.get('session_type') or race_info.get('Session') or '')
    event_name = (race_info.get('RaceName') or race_info.get('raceName') or
                  race_info.get('event_name') or race_info.get('EventName') or 'IndyCar')
    current_lap = int(race_info.get('CurrentLap') or race_info.get('currentLap') or 0)
    total_laps  = int(race_info.get('TotalLaps') or race_info.get('totalLaps') or 200)

    competitors_raw = (data.get('Competitors') or data.get('competitors') or
                       data.get('results') or data.get('Entries') or data.get('entries') or [])

    entries = []
    for c in competitors_raw:
        if not c:
            continue

        driver_raw = (c.get('Driver') or c.get('driver') or c.get('DriverName') or
                      c.get('driverName') or c.get('Name') or c.get('name') or '')
        driver = _parse_driver_name(driver_raw)
        engine = (c.get('Engine') or c.get('engine') or c.get('Manufacturer') or
                  c.get('manufacturer') or c.get('EngineSupplier') or '').strip()
        team   = (c.get('TeamName') or c.get('teamName') or c.get('Team') or
                  c.get('team') or '').strip()
        pos    = str(c.get('Rank') or c.get('rank') or c.get('Position') or
                     c.get('position') or '?')
        car_num = str(c.get('CarNumber') or c.get('carNumber') or c.get('Car') or
                      c.get('car') or c.get('Number') or '?')
        laps   = int(c.get('Laps') or c.get('laps') or c.get('LapsCompleted') or 0)
        gap    = str(c.get('Gap') or c.get('gap') or c.get('Delta') or '').strip()
        interval = str(c.get('Interval') or c.get('interval') or '').strip()
        last_lap = str(c.get('LastLap') or c.get('lastLap') or c.get('LastLapTime') or '').strip()
        best_lap = str(c.get('BestLap') or c.get('bestLap') or c.get('BestLapTime') or '').strip()
        best_speed = str(c.get('BestSpeed') or c.get('bestSpeed') or c.get('Speed') or '').strip()
        pit_stops = int(c.get('PitStops') or c.get('pitStops') or 0)
        status = str(c.get('Status') or c.get('status') or 'Running').strip()

        # Display gap: for leader show blank; prefer Delta/Interval when Gap is empty
        display_gap = gap or interval

        engine_colors = get_engine_colors(engine)
        entries.append({
            'pos':                    pos,
            'car_num':                car_num,
            'driver':                 driver,
            'current_driver':         driver,
            'current_driver_acronym': _driver_acronym(driver),
            'driver_acronyms':        [_driver_acronym(driver)],
            'drivers':                [driver] if driver else [],
            'team':                   team,
            'car':                    team,   # IndyCar has no separate car model
            'engine':                 engine,
            'class_name':             engine.upper() if engine else '',
            'laps':                   laps,
            'gap':                    display_gap,
            'last_lap':               last_lap,
            'best_lap':               best_lap,
            'best_speed':             best_speed,
            'pit_stops':              pit_stops,
            'status':                 status,
            'manufacturer':           engine.lower() if engine else None,
            'manufacturer_colors':    engine_colors,
            'class_colors':           {
                'bg':    engine_colors['bg'],
                'text':  engine_colors['text'],
                'label': engine_colors['label'],
            },
            # Extra Indy-specific
            'current_lap':  current_lap,
            'total_laps':   total_laps,
        })

    flag_info = flag_state_info(raw_flag)
    session_type = _detect_session_type(session_raw)
    return entries, flag_info, session_type, event_name


# ---------------------------------------------------------------------------
# Fetcher
# ---------------------------------------------------------------------------

class IndyCarFetcher:
    """Live timing via IndyCar's scoring API (HTTP polling).

    The scoring URL can be overridden via the /api/indycar/event admin route
    or by setting manual_scoring_url directly. This is necessary as IndyCar
    can change their endpoint each season.
    """

    _DEFAULT_EVENT_NAME = 'INDIANAPOLIS 500'
    _POLL_INTERVAL = 10  # seconds between polls when session is active
    _IDLE_INTERVAL = 30  # seconds between polls when no session data

    def __init__(self):
        self._lock         = threading.Lock()
        self._cache: dict | None = None
        self._flag_state   = flag_state_info('0')
        self._entries: list = []
        self._session_type = 'race'
        self._event_name   = self._DEFAULT_EVENT_NAME
        self._connected    = False
        self.manual_scoring_url: str | None = None  # override via admin API
        self._poll_thread: threading.Thread | None = None
        self._start_poll()

    @property
    def _scoring_url(self) -> str:
        return self.manual_scoring_url or _DEFAULT_SCORING_URL

    def _start_poll(self):
        if self._poll_thread and self._poll_thread.is_alive():
            return
        self._poll_thread = threading.Thread(
            target=self._poll_loop, daemon=True, name='indycar_poll')
        self._poll_thread.start()

    def _poll_loop(self):
        while True:
            try:
                req = urllib.request.Request(
                    self._scoring_url,
                    headers={
                        'Accept':     'application/json',
                        'User-Agent': 'SportsTickerBot/1.0',
                    }
                )
                with urllib.request.urlopen(req, timeout=8) as r:
                    raw = r.read()
                data = json.loads(raw)
                self._ingest(data)
                self._connected = True
                interval = self._POLL_INTERVAL
            except urllib.error.HTTPError as e:
                if e.code == 404:
                    pass  # No active session
                else:
                    print(f'[IndyCar] HTTP {e.code}: {e.url}')
                self._connected = False
                interval = self._IDLE_INTERVAL
            except Exception as exc:
                print(f'[IndyCar] poll error: {exc}')
                self._connected = False
                interval = self._IDLE_INTERVAL
            time.sleep(interval)

    def _ingest(self, data: dict):
        try:
            entries, flag_info, session_type, event_name = _parse_v1(data)
            if not entries:
                return

            leader_laps = entries[0].get('laps', 0) if entries else 0

            with self._lock:
                self._entries    = entries
                self._flag_state = flag_info
                self._session_type = session_type
                if event_name:
                    self._event_name = event_name
                self._cache = self._build_cache(leader_laps)
        except Exception as exc:
            print(f'[IndyCar] ingest error: {exc}')

    def _build_cache(self, leader_laps: int) -> dict:
        return {
            'source':             'indycar_scoring',
            'event_name':         self._event_name,
            'session_type':       self._session_type,
            'session_label':      _SESSION_LABELS.get(self._session_type, self._session_type.upper()),
            'status':             'live',
            'leader_laps':        leader_laps,
            'entries':            list(self._entries),
            'race_control':       [],
            'track_state':        self._flag_state.get('raw', '0'),
            'track_state_key':    self._flag_state.get('key', 'green'),
            'track_state_name':   self._flag_state.get('name', 'GREEN'),
            'track_state_color':  self._flag_state.get('color', '#00C040'),
            'sector_flags':       {},
            'fetched_at':         time.time(),
        }

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def fetch(self) -> dict | None:
        self._start_poll()  # no-op if already running
        with self._lock:
            return self._cache

    def enrich(self, data: dict) -> dict:
        for entry in data.get('entries', []):
            if 'manufacturer_colors' not in entry:
                entry['manufacturer_colors'] = get_engine_colors(entry.get('engine'))
            if 'class_colors' not in entry:
                eng = entry.get('engine', '')
                ec = get_engine_colors(eng)
                entry['class_colors'] = {'bg': ec['bg'], 'text': ec['text'], 'label': ec['label']}
        return data

    def format_for_ticker(self, data: dict | None) -> list[dict]:
        """Return controller-ready game objects from fetched data.

        Prepends one 'indycar_dashboard' fullscreen card (384 px, carries the
        complete entries list for draw_indycar_fullscreen) plus individual
        compact/full car cards for use in sports/live feed modes.
        """
        if not data:
            return []

        games = []
        entries = data.get('entries', [])
        ts_key   = data.get('track_state_key',   'green')
        ts_name  = data.get('track_state_name',  'GREEN')
        ts_color = data.get('track_state_color', '#00C040')
        session_label = data.get('session_label', 'RACE')

        # ── Fullscreen dashboard card (used in indycar mode) ──────────────
        games.append({
            'id':                'indycar_dashboard',
            'type':              'indycar_dashboard',
            'sport':             'indycar',
            'event_name':        data.get('event_name', 'IndyCar'),
            'session_type':      data.get('session_type', 'race'),
            'session_label':     session_label,
            'track_state':       data.get('track_state', '0'),
            'track_state_key':   ts_key,
            'track_state_name':  ts_name,
            'track_state_color': ts_color,
            'leader_laps':       data.get('leader_laps', 0),
            'entries':           entries,  # full list for cycling through
            # Compatibility fields
            'home_abbr': 'IMS', 'away_abbr': '', 'home_score': '', 'away_score': '',
            'status': ts_name,
            'is_shown': True,
        })

        # ── RC summary card (192 px, used in sports feed) ─────────────────
        session_label = data.get('session_label', 'RACE')
        games.append({
            'id':                'indycar_rc',
            'type':              'indycar_rc',
            'sport':             'indycar',
            'event_name':        data.get('event_name', 'IndyCar'),
            'session_type':      data.get('session_type', 'race'),
            'session_label':     session_label,
            'track_state':       data.get('track_state', '0'),
            'track_state_name':  ts_name,
            'track_state_color': ts_color,
            'track_state_key':   ts_key,
            'latest_message':    f'{session_label} · {ts_name}',
            'messages':          [],
            'leader_laps':       data.get('leader_laps', 0),
            'home_abbr': 'IMS', 'away_abbr': 'RC',
            'home_score': ts_key.upper()[:4], 'away_score': '',
            'status': ts_name,
        })

        for entry in data.get('entries', []):
            ec = entry.get('manufacturer_colors') or get_engine_colors(entry.get('engine'))
            games.append({
                'id':                     f"indycar_{entry.get('car_num', '?')}",
                'type':                   'indycar_car',
                'sport':                  'indycar',
                'event_name':             data.get('event_name', 'IndyCar'),
                'session_type':           data.get('session_type', 'race'),
                'pos':                    entry.get('pos', '?'),
                'car_num':                entry.get('car_num', '?'),
                'class_name':             entry.get('class_name', ''),
                'team':                   entry.get('team', ''),
                'car':                    entry.get('car', ''),
                'driver':                 entry.get('driver', ''),
                'drivers':                entry.get('drivers', []),
                'driver_acronyms':        entry.get('driver_acronyms', []),
                'current_driver':         entry.get('current_driver', ''),
                'current_driver_acronym': entry.get('current_driver_acronym', '???'),
                'engine':                 entry.get('engine', ''),
                'laps':                   entry.get('laps', 0),
                'gap':                    entry.get('gap', ''),
                'last_lap':               entry.get('last_lap', ''),
                'best_lap':               entry.get('best_lap', ''),
                'best_speed':             entry.get('best_speed', ''),
                'pit_stops':              entry.get('pit_stops', 0),
                'manufacturer':           entry.get('manufacturer'),
                'manufacturer_colors':    ec,
                'class_colors':           entry.get('class_colors', _ENGINE_DEFAULT),
                # Compatibility
                'home_abbr':  entry.get('team', '')[:8],
                'away_abbr':  entry.get('car_num', '?'),
                'home_score': str(entry.get('laps', 0)),
                'away_score': entry.get('gap', ''),
                'status':     entry.get('class_name', ''),
            })

        return games


# Module-level singleton
indycar_fetcher = IndyCarFetcher()
