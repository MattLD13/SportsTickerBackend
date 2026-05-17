"""Nürburgring 24h live timing fetcher (Race Result API)."""

import re
import time
import requests
from datetime import datetime

from ..lookups import (
    RACING_MANUFACTURER_COLORS as MANUFACTURER_COLORS,
    RACING_CLASS_COLORS         as CLASS_COLORS,
    _RACING_DEFAULT_MFR,
    _RACING_DEFAULT_CLASS,
)

_HEADERS = {
    'User-Agent': (
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
        'AppleWebKit/537.36 (KHTML, like Gecko) '
        'Chrome/124.0.0.0 Safari/537.36'
    ),
    'Accept': 'application/json, text/html, */*',
    'Accept-Language': 'en-US,en;q=0.9,de;q=0.8',
}


# ---------------------------------------------------------------------------
# Helper utilities
# ---------------------------------------------------------------------------

def _pick_current_driver(drivers: list, hint: str = '') -> str | None:
    """Return the name of the driver currently at the wheel.

    Race Result sometimes marks the active driver with an asterisk prefix or
    supplies an explicit field.  Fall back to the first driver listed.
    """
    if hint:
        clean = hint.lstrip('*').strip()
        if clean:
            return clean
    for d in drivers:
        if d.startswith('*'):
            return d.lstrip('*').strip()
    return drivers[0] if drivers else None


def make_driver_acronym(name: str) -> str:
    """Return the 3-letter racing acronym for a driver name.

    FIA/endurance convention: first letter of first name + first two letters
    of last name  (e.g. 'Dennis Olsen' → 'DOL').
    """
    name = name.strip()
    if not name:
        return '???'
    parts = name.split()
    if len(parts) >= 2:
        return (parts[0][0] + parts[-1][:2]).upper()
    return parts[0][:3].upper()


def extract_manufacturer(text: str) -> str | None:
    """Infer manufacturer key from car model / team name string."""
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


# ---------------------------------------------------------------------------
# Fetcher
# ---------------------------------------------------------------------------

class NurburgringFetcher:
    """Fetches live standings from the Nürburgring 24h via Race Result."""

    _SEARCH_URL = 'https://www.raceresult.com/en/results.php'
    _LIVE_BASE  = 'https://livetiming.raceresult.com'
    _EVENT_TTL  = 1800   # re-discover event ID every 30 min
    _DATA_TTL   = 30     # refresh timing data every 30 s

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update(_HEADERS)
        self._event_id: str | None = None
        self._event_id_ts: float   = 0.0
        self._cache: dict | None   = None
        self._cache_ts: float      = 0.0

    # ------------------------------------------------------------------
    # Event discovery
    # ------------------------------------------------------------------

    def _discover_event_id(self) -> str | None:
        now = time.time()
        if self._event_id and (now - self._event_id_ts) < self._EVENT_TTL:
            return self._event_id

        year = datetime.now().year
        for query in [
            f'Nürburgring 24 {year}',
            f'Nuerburgring 24 {year}',
            '24h Nürburgring',
        ]:
            try:
                resp = self.session.get(
                    self._SEARCH_URL, params={'search': query}, timeout=10,
                )
                if not resp.ok:
                    continue
                ids = re.findall(r'/en/results/(\d{5,6})', resp.text)
                if not ids:
                    ids = re.findall(r'livetiming\.raceresult\.com/(\d{5,6})', resp.text)
                if ids:
                    eid = max(ids, key=lambda x: int(x))
                    self._event_id    = eid
                    self._event_id_ts = now
                    return eid
            except Exception as exc:
                print(f'[N24] discover failed ({query}): {exc}')

        return self._event_id

    # ------------------------------------------------------------------
    # Timing data fetch
    # ------------------------------------------------------------------

    def _fetch_timing(self, event_id: str) -> object:
        endpoints = [
            (f'{self._LIVE_BASE}/{event_id}/RRHMI/data',
             {'l': 0, 'p': 1, 't': 0, 's': '', 'f': 'L', 'r': 0, 'm': ''}),
            (f'{self._LIVE_BASE}/{event_id}/data',
             {'type': 'leaderboard', 'format': 'json'}),
            (f'{self._LIVE_BASE}/{event_id}/results.json', {}),
        ]
        for url, params in endpoints:
            try:
                resp = self.session.get(url, params=params, timeout=10)
                if resp.ok and resp.content:
                    try:
                        return resp.json()
                    except Exception:
                        pass
            except Exception:
                pass
        return None

    # ------------------------------------------------------------------
    # Parsing
    # ------------------------------------------------------------------

    def _parse(self, raw: object, event_id: str) -> dict | None:
        rows = self._extract_rows(raw)
        if not rows:
            return None
        entries = [e for e in (self._parse_row(r) for r in rows) if e]
        if not entries:
            return None
        leader_laps = entries[0].get('laps', 0)
        return {
            'source':      'race_result',
            'event_id':    event_id,
            'event_name':  'ADAC TOTAL 24h-Rennen Nürburgring',
            'status':      'live',
            'leader_laps': leader_laps,
            'entries':     entries,
            'fetched_at':  time.time(),
        }

    @staticmethod
    def _extract_rows(raw: object) -> list:
        if isinstance(raw, list):
            return raw
        if isinstance(raw, dict):
            for key in ('data', 'entries', 'results', 'rows', 'timing'):
                val = raw.get(key)
                if isinstance(val, list) and val:
                    return val
            if all(str(k).isdigit() for k in raw):
                return list(raw.values())
        return []

    def _parse_row(self, raw) -> dict | None:
        if isinstance(raw, list):
            return self._parse_row_list(raw)
        if isinstance(raw, dict):
            return self._parse_row_dict(raw)
        return None

    @staticmethod
    def _parse_row_list(r: list) -> dict | None:
        if len(r) < 3:
            return None
        def _s(i): return str(r[i]).strip() if i < len(r) else ''
        def _i(i):
            try: return int(r[i])
            except Exception: return 0
        car_text = _s(4) or _s(3)
        drivers  = [d for d in [_s(8)] if d]
        current  = _pick_current_driver(drivers, _s(9))
        return {
            'pos':                    _s(0) or '?',
            'car_num':                _s(1) or '?',
            'class_name':             _s(2),
            'team':                   _s(3),
            'car':                    _s(4),
            'drivers':                drivers,
            'driver_acronyms':        [make_driver_acronym(d) for d in drivers],
            'current_driver':         current,
            'current_driver_acronym': make_driver_acronym(current) if current else '???',
            'laps':                   _i(5),
            'gap':                    _s(6),
            'last_lap':               _s(7),
            'best_lap':               '',
            'manufacturer':           extract_manufacturer(car_text),
        }

    @staticmethod
    def _parse_row_dict(r: dict) -> dict | None:
        def _g(*keys):
            for k in keys:
                v = r.get(k)
                if v is not None: return str(v).strip()
            return ''
        def _gi(*keys):
            for k in keys:
                v = r.get(k)
                try: return int(v)
                except Exception: pass
            return 0

        car_text  = _g('Car', 'car', 'vehicle', 'Vehicle')
        team_text = _g('Name', 'name', 'Team', 'team')
        drivers   = []
        for i in range(1, 5):
            d = _g(f'Driver{i}', f'driver{i}', f'Driver_{i}')
            if d: drivers.append(d)
        if not drivers:
            combined = _g('Drivers', 'drivers', 'driver_names')
            if combined:
                drivers = [d.strip() for d in re.split(r'[/,;]', combined) if d.strip()]

        current_raw = _g('CurrentDriver', 'current_driver', 'Driving', 'driving', 'ActiveDriver')
        current     = _pick_current_driver(drivers, current_raw)
        car_num     = _g('BIB', 'Bib', 'bib', 'Num', 'num', 'No', 'no', 'car_num', 'number')
        return {
            'pos':                    _g('Pos', 'pos', 'Position', 'position') or '?',
            'car_num':                car_num or '?',
            'class_name':             _g('Class', 'class', 'class_name', 'Category'),
            'team':                   team_text,
            'car':                    car_text,
            'drivers':                drivers,
            'driver_acronyms':        [make_driver_acronym(d) for d in drivers],
            'current_driver':         current,
            'current_driver_acronym': make_driver_acronym(current) if current else '???',
            'laps':                   _gi('Laps', 'laps', 'LapCount', 'lap_count', 'Lap'),
            'gap':                    _g('Gap', 'gap', 'Diff', 'diff'),
            'last_lap':               _g('LastLap', 'last_lap', 'LastLapTime', 'last_lap_time'),
            'best_lap':               _g('BestLap', 'best_lap', 'BestLapTime'),
            'manufacturer':           extract_manufacturer(car_text or team_text),
        }

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def fetch(self) -> dict | None:
        now = time.time()
        if self._cache and (now - self._cache_ts) < self._DATA_TTL:
            return self._cache

        event_id = self._discover_event_id()
        if not event_id:
            return self._cache

        raw = self._fetch_timing(event_id)
        if raw is None:
            return self._cache

        parsed = self._parse(raw, event_id)
        if parsed:
            self._cache    = parsed
            self._cache_ts = now

        return self._cache

    def enrich(self, data: dict) -> dict:
        """Add colour + logo data to every entry in-place."""
        for entry in data.get('entries', []):
            mfr = entry.get('manufacturer')
            entry['manufacturer_colors'] = get_manufacturer_colors(mfr)
            entry['class_colors']        = get_class_colors(entry.get('class_name', ''))
        return data

    def format_for_ticker(self, data: dict | None) -> list[dict]:
        """Convert fetched N24 data into a list of controller-ready game objects."""
        if not data or not data.get('entries'):
            return []
        enriched = self.enrich(data)
        games = []
        for entry in enriched.get('entries', []):
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
                'current_driver':         entry.get('current_driver'),
                'current_driver_acronym': entry.get('current_driver_acronym', '???'),
                'laps':                   entry.get('laps', 0),
                'gap':                    entry.get('gap', ''),
                'last_lap':               entry.get('last_lap', ''),
                'best_lap':               entry.get('best_lap', ''),
                'manufacturer':           entry.get('manufacturer'),
                'manufacturer_colors':    entry.get('manufacturer_colors', _RACING_DEFAULT_MFR),
                'class_colors':           entry.get('class_colors', _RACING_DEFAULT_CLASS),
                # Compatibility fields used by the generic strip builder
                'home_abbr':  entry.get('team', '')[:8],
                'away_abbr':  entry.get('car_num', '?'),
                'home_score': str(entry.get('laps', 0)),
                'away_score': entry.get('gap', ''),
                'status':     entry.get('class_name', ''),
            })
        return games


# Module-level singleton — imported by routes and workers
n24_fetcher = NurburgringFetcher()
