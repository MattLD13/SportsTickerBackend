"""IndyCar live timing fetcher — HTTP polling against IndyCar's scoring API.

Supports all IndyCar session types: Race, Practice, Qualifying.
Indy 500-specific: 200-lap race distance tracking, starting grid, bump day.

Endpoint URL can be overridden via the /api/indycar/event admin route.
"""

import json
import re
import threading
import time
import urllib.parse
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

# Default scoring endpoint — livetiming.net PKT feed
# The `ts` query parameter is refreshed automatically on every poll to bust the cache.
_DEFAULT_SCORING_URL = 'https://livetiming.net/indycar/LoadPKT.asp?filename=leader.PKT&Refresh=1000'

# ---------------------------------------------------------------------------
# PKT (pipe-delimited) format support  — LiveTiming.net
# ---------------------------------------------------------------------------
# Header line:  <!EventName|SessionCode|…|Flag|…|>|
#   field 0 = event name
#   field 1 = session code (QC=qualifying, RC=race, P=practice, …)
#   field 5 = flag state  (G=green, Y/C=yellow, R=red, W=white, F=checkered)
#   field 9 = total race laps
#
# Driver lines: pos|car#|name|laps|lastLap|lapsBack|FTime|diff|interval|…|status|lastSpeed|bestSpeed|…|D/H/F or D/C/F|…
#   field  0 = position (may have +/- suffix)
#   field  1 = car number
#   field  2 = driver full name
#   field  3 = laps completed
#   field  4 = last lap time
#   field  6 = fastest time (FTime)
#   field  7 = diff from leader (for leader row this is their FTime — detect by value > 10)
#   field 13 = status (e.g. "In Pit", "On Track")
#   field 14 = last lap speed
#   field 15 = best speed
#   field 31 = compound string "D/H/F" or "D/C/F" (chassis/engine/tire)

_PKT_FLAG = {
    'G': 'green',   'Y': 'yellow',  'C': 'yellow',
    'R': 'red',     'W': 'white',   'F': 'checkered',
    'CH': 'checkered',
}


def _pkt_session_type(code: str) -> str:
    c = str(code).strip().upper()
    if 'Q' in c:
        return 'qualifying2' if ('2' in c or 'BUMP' in c) else 'qualifying'
    if c.startswith(('P', 'W')) or 'PRAC' in c or 'WARM' in c:
        return 'practice'
    return 'race'


def _pkt_engine(compound: str) -> str:
    """'D/H/F' → 'honda',  'D/C/F' → 'chevrolet'."""
    parts = str(compound).strip().upper().split('/')
    if len(parts) >= 2:
        return 'honda' if parts[1] == 'H' else 'chevrolet' if parts[1] == 'C' else ''
    return ''


def _clean_timing(s: str) -> str:
    """Strip trailing direction indicators (/+) from timing values."""
    return re.sub(r'[/+\s]+$', '', str(s).strip())


def _parse_pkt(text: str) -> tuple:
    """Parse LiveTiming.net pipe-delimited PKT text.

    Returns (entries, flag_info, session_type, event_name).
    """
    entries = []
    event_name  = 'IndyCar'
    session_type = 'race'
    flag_info   = flag_state_info('0')
    total_laps  = 200

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        if line.startswith('<!'):
            # Session header
            content = line[2:].rstrip('|').rstrip('>')
            parts = [p.strip() for p in content.split('|')]
            if parts:
                event_name = parts[0] or 'IndyCar'
            if len(parts) > 1:
                session_type = _pkt_session_type(parts[1])
            if len(parts) > 5:
                flag_key = _PKT_FLAG.get(parts[5].upper(), 'green')
                flag_info = flag_state_info(flag_key)
            if len(parts) > 9:
                try:
                    total_laps = int(re.sub(r'[^0-9]', '', parts[9]) or '200')
                except ValueError:
                    pass
            continue

        if '|' not in line:
            continue

        parts = [p.strip() for p in line.split('|')]
        if len(parts) < 8:
            continue

        pos_raw = re.sub(r'[^0-9]', '', parts[0])
        if not pos_raw:
            continue

        car_num = parts[1]
        driver  = parts[2]
        if not car_num:
            continue

        try:
            laps = int(re.sub(r'[^0-9]', '', parts[3]) or '0')
        except ValueError:
            laps = 0

        last_lap  = _clean_timing(parts[4]) if len(parts) > 4 else ''
        best_lap  = _clean_timing(parts[6]) if len(parts) > 6 else ''

        # field 7: cumulative gap from leader — but the leader's row stores their
        # best time here instead of 0.000.  Values > 10 s are lap times, not gaps.
        raw_gap = _clean_timing(parts[7]) if len(parts) > 7 else ''
        try:
            gap = raw_gap if raw_gap and 0.0001 <= float(raw_gap) <= 10.0 else ''
        except ValueError:
            gap = ''

        status     = parts[13] if len(parts) > 13 else ''
        last_speed = _clean_timing(parts[14]) if len(parts) > 14 else ''
        best_speed = _clean_timing(parts[15]) if len(parts) > 15 else ''
        engine     = _pkt_engine(parts[31]) if len(parts) > 31 else ''

        # Skip cars that haven't turned a lap and have no useful data
        if not best_lap or best_lap.lower() in ('no time', '--', '---', ''):
            if not driver:
                continue
            best_lap = ''

        engine_colors = get_engine_colors(engine)
        entries.append({
            'pos':                    pos_raw,
            'car_num':                car_num,
            'driver':                 driver,
            'current_driver':         driver,
            'current_driver_acronym': _driver_acronym(driver),
            'driver_acronyms':        [_driver_acronym(driver)],
            'drivers':                [driver] if driver else [],
            'team':                   '',
            'car':                    '',
            'engine':                 engine,
            'class_name':             engine.upper() if engine else '',
            'laps':                   laps,
            'gap':                    gap,
            'last_lap':               last_lap,
            'best_lap':               best_lap,
            'best_speed':             best_speed,
            'last_speed':             last_speed,
            'pit_stops':              0,
            'status':                 status,
            'manufacturer':           engine.lower() if engine else None,
            'manufacturer_colors':    engine_colors,
            'class_colors': {
                'bg':    engine_colors['bg'],
                'text':  engine_colors['text'],
                'label': engine_colors['label'],
            },
            'current_lap': 0,
            'total_laps':  total_laps,
        })

    return entries, flag_info, session_type, event_name


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

    @staticmethod
    def _is_pkt_url(url: str) -> bool:
        return 'LoadPKT' in url or '.PKT' in url.upper()

    @staticmethod
    def _add_ts(url: str) -> str:
        """Inject/refresh the cache-busting ts= parameter."""
        base = re.sub(r'[&?]ts=[^&]*', '', url)
        sep  = '&' if '?' in base else '?'
        return f'{base}{sep}ts={int(time.time())}'

    def _poll_loop(self):
        while True:
            try:
                url    = self._scoring_url
                is_pkt = self._is_pkt_url(url)
                if is_pkt:
                    url = self._add_ts(url)

                req = urllib.request.Request(
                    url,
                    headers={
                        'Accept':     '*/*',
                        'User-Agent': 'SportsTickerBot/1.0',
                        'Referer':    'https://livetiming.net/',
                    }
                )
                with urllib.request.urlopen(req, timeout=8) as r:
                    raw = r.read()

                if is_pkt:
                    text = raw.decode('utf-8', errors='replace')
                    if not text.strip().startswith('<!') or '|' not in text[:100]:
                        # HTML error page or no active session
                        self._connected = False
                        time.sleep(self._IDLE_INTERVAL)
                        continue
                    entries, flag_info, session_type, event_name = _parse_pkt(text)
                    self._ingest_pkt(entries, flag_info, session_type, event_name)
                else:
                    stripped = raw.strip()
                    if not stripped or stripped[:1] in (b'<',):
                        self._connected = False
                        time.sleep(self._IDLE_INTERVAL)
                        continue
                    data = json.loads(raw)
                    self._ingest(data)

                self._connected = True
                interval = self._POLL_INTERVAL

            except urllib.error.HTTPError as e:
                if e.code not in (404, 503):
                    print(f'[IndyCar] HTTP {e.code}: {e.url}')
                self._connected = False
                interval = self._IDLE_INTERVAL
            except (json.JSONDecodeError, ValueError):
                self._connected = False
                interval = self._IDLE_INTERVAL
            except Exception as exc:
                print(f'[IndyCar] poll error: {exc}')
                self._connected = False
                interval = self._IDLE_INTERVAL
            time.sleep(interval)

    def _ingest_pkt(self, entries: list, flag_info: dict,
                    session_type: str, event_name: str):
        try:
            if not entries:
                return
            leader_laps = entries[0].get('laps', 0)
            with self._lock:
                self._entries     = entries
                self._flag_state  = flag_info
                self._session_type = session_type
                if event_name:
                    self._event_name = event_name
                self._cache = self._build_cache(leader_laps)
        except Exception as exc:
            print(f'[IndyCar] PKT ingest error: {exc}')

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
