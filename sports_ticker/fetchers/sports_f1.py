"""Formula 1 fetcher using ESPN for the session schedule.

livetiming.formula1.com blocks server IPs; all session metadata now comes from
the ESPN F1 scoreboard which carries the full calendar including per-session
start times for the current race weekend.
SignalR is kept as an optional live-timing overlay — if it ever becomes
accessible it will upgrade the card with real positions and lap counts.
"""

from datetime import datetime, timezone, timedelta
import re

from .. import core as _core
globals().update({k: v for k, v in vars(_core).items() if not k.startswith('__')})

from . import f1_signalr as _f1_signalr

_JOLPICA_BASE = "https://api.jolpi.ca/ergast/f1"
_ESPN_F1_SCOREBOARD = "http://site.api.espn.com/apis/site/v2/sports/racing/f1/scoreboard"

# ESPN competition type abbreviation → Jolpica session key
_ESPN_F1_ABBR_TO_JOLPICA = {
    'FP1':  'FirstPractice',
    'FP2':  'SecondPractice',
    'FP3':  'ThirdPractice',
    'SS':   'SprintQualifying',
    'SR':   'Sprint',
    'Qual': 'Qualifying',
    'Race': 'Race',
}

_F1_CAR_URL = (
    "https://media.formula1.com/image/upload/c_lfill,h_224/q_auto/"
    "v1740000001/common/f1/2026/{slug}/2026{slug}carright.webp"
)

_F1_TEAM_SLUGS = {
    'mclaren':      'mclaren',
    'mercedes':     'mercedes',
    'ferrari':      'ferrari',
    'red bull':     'redbullracing',
    'racing bulls': 'racingbulls',
    'rb':           'racingbulls',
    'aston martin': 'astonmartin',
    'alpine':       'alpine',
    'williams':     'williams',
    'haas':         'haasf1team',
    'audi':         'audi',
    'sauber':       'audi',       # Sauber became Audi in 2026
    'kick sauber':  'audi',
    'cadillac':     'cadillac',
    'andretti':     'cadillac',   
}

_F1_TEAM_COLORS = {
    'mclaren':      '#FF8000',
    'mercedes':     '#27F4D2',
    'ferrari':      '#E8002D',
    'red bull':     '#3671C6',
    'red bull racing': '#3671C6',
    'oracle red bull racing': '#3671C6',
    'racing bulls': '#6692FF',
    'visa cash app rb': '#6692FF',
    'visa cash app rb f1 team': '#6692FF',
    'vcarb':        '#6692FF',
    'rb':           '#6692FF',
    'aston martin': '#229971',
    'aston martin aramco': '#229971',
    'aston martin aramco mercedes': '#229971',
    'alpine':       '#FF87BC',
    'williams':     '#64C4FF',
    'haas':         '#B6BABD',
    'sauber':       '#BB0000',
    'kick sauber':  '#BB0000',
    'audi':         '#BB0000',
    'cadillac':     '#9CA3AF',
}

# Cache resolved working slugs to avoid repeated HEAD requests
_F1_RESOLVED_SLUGS = {}

# TrackStatus codes from the F1 SignalR feed (used if SignalR ever connects)
_F1LT_TRACK_STATUS = {
    '1': 'GREEN',
    '2': 'YELLOW',
    '4': 'SAFETY CAR',
    '5': 'RED FLAG',
    '6': 'VSC',
    '7': 'VSC ENDING',
}

# Jolpica session keys in race-weekend order.
# (jolpica_key, display_name, is_practice, duration_minutes)
_F1_SESSION_ORDER = [
    ('FirstPractice',    'Practice 1',        True,   90),
    ('SecondPractice',   'Practice 2',        True,   90),
    ('ThirdPractice',    'Practice 3',        True,   60),
    ('SprintQualifying', 'Sprint Qualifying', False,  60),
    ('Sprint',           'Sprint',            False,  60),
    ('Qualifying',       'Qualifying',        False,  70),
    ('Race',             'Race',              False, 130),
]

_F1_SCHEDULE_TTL = 3600.0   # cache the season calendar for 1 hour
_F1_RESULTS_TTL  = 1800.0   # cache driver results for 30 min


_F1_MULTI_WORD_LOCATIONS = {
    'las vegas', 'abu dhabi', 'sao paulo', 'são paulo',
    'emilia romagna', 'saudi arabian', 'great britain',
}

def _strip_f1_sponsor(name):
    """Strip title-sponsor prefix from ESPN race names.

    'Lenovo Canadian Grand Prix'       → 'Canadian Grand Prix'
    'Qatar Airways Australian Grand Prix' → 'Australian Grand Prix'
    'Pirelli Abu Dhabi Grand Prix'     → 'Abu Dhabi Grand Prix'
    """
    m = re.search(r'(.+?)\s+grand\s+prix', name, re.IGNORECASE)
    if not m:
        return name
    words = m.group(1).strip().split()
    two   = ' '.join(words[-2:]).lower() if len(words) >= 2 else ''
    location = ' '.join(words[-2:]) if two in _F1_MULTI_WORD_LOCATIONS else words[-1]
    return f"{location} Grand Prix"


def _f1_short_event(name):
    text = _strip_f1_sponsor(str(name or 'Formula 1').strip())
    text = text.replace('FORMULA 1', '').replace('GRAND PRIX', 'GP')
    text = ' '.join(text.split())
    return text.title() or 'Formula 1'


def _f1_flag_for_state(state):
    return {'pre': 'WHITE', 'post': 'CHECKERED'}.get(str(state or '').lower(), 'GREEN')


def _f1_format_lapped_gap(text):
    raw = str(text or '').strip().lower()
    if not raw:
        return ''
    match = re.search(r'([+-]?\d+)\s*(?:lap|laps|\bl\b)', raw)
    if not match:
        return ''
    laps = abs(int(match.group(1)))
    if laps <= 0:
        return ''
    return f"+{laps} lap" if laps == 1 else f"+{laps} laps"


def _f1_seconds_from_time_text(text):
    raw = str(text or '').strip()
    if ':' not in raw:
        return None
    try:
        parts = [float(part) for part in raw.split(':')]
    except Exception:
        return None
    if len(parts) == 2:
        return parts[0] * 60 + parts[1]
    if len(parts) == 3:
        return parts[0] * 3600 + parts[1] * 60 + parts[2]
    return None


def _f1_compact_gap(value, position):
    if position == 1:
        return 'Leader'
    if value in (None, ''):
        return ''
    text = str(value).strip()

    lapped = _f1_format_lapped_gap(text)
    if lapped:
        return lapped

    # Collapse stray plus signs like '++3.264' to a single normalized plus.
    text = re.sub(r'^\++', '', text).strip()
    if not text:
        return ''

    seconds = _f1_seconds_from_time_text(text)
    if seconds is not None:
        return f"+{seconds:.1f}s" if seconds < 60 else f"+{seconds:.0f}s"

    try:
        gap = abs(float(text))
        if gap < 1:
            return f"+{int(round(gap * 1000))}ms"
        if gap < 60:
            return f"+{gap:.1f}s"
        return f"+{gap:.0f}s"
    except Exception:
        # Status text such as "Retired" should not pick up a synthetic plus.
        return text[:10]


def _f1_duration_text(seconds):
    try:
        total_seconds = max(0, int(seconds))
    except Exception:
        return ''
    if total_seconds <= 0:
        return ''
    minutes, secs = divmod(total_seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def _f1_sanitize_time_text(text):
    raw = str(text or '').strip()
    if not raw:
        return ''
    raw = raw.replace('++', '').replace('+', '').strip()
    return raw


def _f1_format_qual_time(seconds):
    try:
        val = float(seconds)
        if val <= 0: return ""
        minutes = int(val // 60)
        secs = val % 60
        return f"{minutes}:{secs:06.3f}" if minutes > 0 else f"{secs:.3f}"
    except Exception:
        return str(seconds)



def _f1_team_match(team_name):
    lower = str(team_name or '').strip().lower()
    for key in sorted(_F1_TEAM_SLUGS, key=len, reverse=True):
        if key and key in lower:
            return key
    return ''


def _f1_car_url(team_name):
    key = _f1_team_match(team_name)
    slug = _F1_TEAM_SLUGS.get(key, '')
    if not slug:
        return ''

    # If we've already resolved a working slug, use it.
    if slug in _F1_RESOLVED_SLUGS:
        return _F1_CAR_URL.format(slug=_F1_RESOLVED_SLUGS[slug])

    # Try variants: original, without hyphens, and a few common alternates.
    candidates = [slug, slug.replace('-', ''), slug.replace('-', '_')]
    # also try removing numeric/dashed suffixes
    if '-' in slug:
        parts = slug.split('-')
        candidates += [''.join(parts), ''.join(parts[:2])]

    # Try each candidate with a HEAD request to find a working URL.
    try:
        import requests
        for cand in candidates:
            url = _F1_CAR_URL.format(slug=cand)
            try:
                r = requests.head(url, timeout=5)
                if r.status_code == 200:
                    _F1_RESOLVED_SLUGS[slug] = cand
                    return _F1_CAR_URL.format(slug=cand)
            except Exception:
                continue
    except Exception:
        # network not available or requests missing; fall back to original slug
        pass

    # No working variant found; record empty to avoid retrying.
    _F1_RESOLVED_SLUGS[slug] = slug
    return _F1_CAR_URL.format(slug=slug)


def _f1_team_color(team_name):
    key = _f1_team_match(team_name)
    return _F1_TEAM_COLORS.get(key, '#888888')


def _espn_f1_event_to_jolpica(event):
    """Convert an ESPN F1 scoreboard event to the Jolpica race dict format."""
    circuit = event.get('circuit', {})
    address = circuit.get('address', {})
    race = {
        'round':    str(event.get('id', '')),
        'raceName': event.get('name', 'Formula 1'),
        'Circuit': {
            'circuitName': circuit.get('fullName', ''),
            'Location': {
                'locality': address.get('city', ''),
                'country':  address.get('country', ''),
            },
        },
    }
    for comp in event.get('competitions', []):
        abbr  = (comp.get('type') or {}).get('abbreviation', '')
        jkey  = _ESPN_F1_ABBR_TO_JOLPICA.get(abbr)
        if not jkey:
            continue
        start = comp.get('startDate') or comp.get('date') or ''
        if not start:
            continue
        try:
            s = start.rstrip('Z')
            d, t = s.split('T', 1) if 'T' in s else (s, '00:00:00')
            if len(t.split(':')) == 2:
                t += ':00'
            race[jkey] = {'date': d, 'time': t + 'Z'}
        except Exception:
            pass
    return race


def _f1_parse_session_utc(sess_dict):
    """Parse a Jolpica session dict {'date': 'YYYY-MM-DD', 'time': 'HH:MM:SSZ'} → UTC datetime."""
    try:
        d = str(sess_dict.get('date', ''))
        t = str(sess_dict.get('time', '00:00:00Z')).rstrip('Z')
        return datetime.fromisoformat(f"{d}T{t}").replace(tzinfo=timezone.utc)
    except Exception:
        return None


def _f1_schedule_year(races):
    years = []
    for race in races or []:
        if not isinstance(race, dict):
            continue
        for key, _, _, _ in _F1_SESSION_ORDER:
            sess = race.get(key)
            if not isinstance(sess, dict):
                continue
            start = _f1_parse_session_utc(sess)
            if start:
                years.append(start.year)
    return max(years) if years else None


def _find_f1_sessions(races, now_utc):
    """Return all sessions for the nearest race weekend that warrant a ticker card.

    A session is included when it is:
      - currently live              → state 'in'
      - ended within the last 12 h  → state 'post'
      - starts within the next 24 h → state 'pre'

    Returns a list of (race, key, name, is_practice, start_utc, end_utc, state)
    sorted by start time, or [] if no relevant weekend is found.
    """
    for race in races:
        sessions = []
        for key, name, is_practice, dur_min in _F1_SESSION_ORDER:
            sess = race.get(key)
            if not isinstance(sess, dict):
                continue
            start = _f1_parse_session_utc(sess)
            if not start:
                continue
            end = start + timedelta(minutes=dur_min)
            sessions.append((key, name, is_practice, start, end))

        if not sessions:
            continue

        weekend_start = min(s[3] for s in sessions)
        weekend_end   = max(s[4] for s in sessions)

        if not (weekend_start - timedelta(days=1) <= now_utc <= weekend_end + timedelta(days=1)):
            continue

        relevant = []
        for key, name, ip, start, end in sessions:
            if start <= now_utc <= end:
                relevant.append((race, key, name, ip, start, end, 'in'))
            elif end < now_utc and (now_utc - end).total_seconds() < 12 * 3600:
                relevant.append((race, key, name, ip, start, end, 'post'))
            elif start > now_utc and (start - now_utc).total_seconds() < 48 * 3600:
                relevant.append((race, key, name, ip, start, end, 'pre'))

        if relevant:
            relevant.sort(key=lambda x: x[4])  # chronological order
            return relevant

    return []


def _gtl_to_float(raw):
    """Parse a GapToLeader string to float seconds, or None if non-numeric (e.g. lapped)."""
    s = str(raw or '').strip().lstrip('+')
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _drivers_from_signalr(live_data):
    """Build a sorted driver list from a SignalR live snapshot."""
    driver_list  = live_data.get('driver_list', {})
    timing_lines = live_data.get('timing_lines', {})
    if not driver_list:
        return []

    entries = []
    for num, dl_info in driver_list.items():
        if not isinstance(dl_info, dict):
            continue
        tl = timing_lines.get(str(num), {})
        if not isinstance(tl, dict):
            tl = {}

        try:
            pos = int(tl.get('Position') or 999)
        except Exception:
            pos = 999

        team   = str(dl_info.get('TeamName') or '')
        tc     = str(dl_info.get('TeamColour') or '').strip().lstrip('#')
        livery = f"#{tc}" if tc else _f1_team_color(team)

        gtl_raw = tl.get('GapToLeader', '')
        if isinstance(gtl_raw, dict):
            gtl_raw = gtl_raw.get('Value', '')

        full_name = str(dl_info.get('FullName') or dl_info.get('BroadcastName') or f"#{num}").strip()
        tla       = str(dl_info.get('Tla') or num)[:3].upper()

        entries.append({
            'pos':              pos,
            '_gtl':             str(gtl_raw or '').strip(),
            'name':             full_name.title(),
            'abbr':             tla,
            'car':              str(num),
            'team':             team,
            'team_logo':        '',
            'car_illustration': '',
            'livery_primary':   livery,
            'livery_secondary': '#111111',
            'gap':              '',
            'speed':            '',
            'status':           'Active',
            'on_track':         True,
        })

    entries.sort(key=lambda d: d['pos'])

    # Compute interval to car ahead from consecutive gap-to-leader values.
    prev_gtl = 0.0
    drivers = []
    for drv in entries:
        gtl_str = drv.pop('_gtl', '')
        pos     = drv['pos']
        if pos == 1:
            drv['gap'] = 'Leader'
            prev_gtl = 0.0
        else:
            gtl_f = _gtl_to_float(gtl_str)
            if gtl_f is not None:
                interval = gtl_f - prev_gtl
                prev_gtl = gtl_f
                drv['gap'] = _f1_compact_gap(f"+{interval:.3f}", pos)
            else:
                # Lapped or non-numeric gap — show as-is
                drv['gap'] = _f1_compact_gap(gtl_str, pos)
        drivers.append(drv)

    return drivers


class SportsF1Mixin:
    def __init_f1_cache(self):
        if not hasattr(self, '_f1_session_caches'):
            self._f1_session_caches   = {}           # {session_id: {'ts', 'data'}}
            self._f1_signalr_snapshots = {}          # {session_id: [drivers]} — last live standings
            self._f1_schedule_cache   = {'ts': 0.0, 'data': []}
            self._f1_results_cache    = {'ts': 0.0, 'data': []}
            self._f1_ttl              = 30.0

    def _jolpica_get(self, path):
        url = f"{_JOLPICA_BASE}/{path.lstrip('/')}"
        r = self.session.get(url, headers=HEADERS, timeout=TIMEOUTS.get('default', 10))
        r.raise_for_status()
        return r.json()

    def _fetch_f1_schedule(self, force=False):
        """Fetch the current race weekend schedule from ESPN F1 scoreboard (cached 1 h)."""
        self.__init_f1_cache()
        now = time.time()
        cache = self._f1_schedule_cache
        if not force and (now - cache['ts']) < _F1_SCHEDULE_TTL and cache['data']:
            return cache['data']
        try:
            r = self.session.get(_ESPN_F1_SCOREBOARD, headers=HEADERS,
                                 timeout=TIMEOUTS.get('default', 10))
            r.raise_for_status()
            events = r.json().get('events', [])
            races  = [_espn_f1_event_to_jolpica(e) for e in events]
            self._f1_schedule_cache = {'ts': now, 'data': races}
            return races
        except Exception as exc:
            print(f"[F1] ESPN schedule fetch error: {exc}")
            return cache.get('data', [])

    def _fetch_f1_results(self, force=False):
        """Fetch last-race driver results from Jolpica (cached 30 min)."""
        self.__init_f1_cache()
        now = time.time()
        cache = self._f1_results_cache
        if not force and (now - cache['ts']) < _F1_RESULTS_TTL and cache['data']:
            return cache['data']
        try:
            data    = self._jolpica_get('current/last/results.json')
            races   = data.get('MRData', {}).get('RaceTable', {}).get('Races', [])
            results = races[0].get('Results', []) if races else []
            self._f1_results_cache = {'ts': now, 'data': results}
            return results
        except Exception as exc:
            print(f"[F1] Results fetch error: {exc}")
            return cache.get('data', [])

    def _fetch_openf1_live(self, start_utc, session_key=None):
        """Fetch real-time position/driver data from OpenF1.

        session_key — if 'latest', skip the date-range search and query the
        live session directly (faster and more reliable during active sessions).
        If None, falls back to the ±90-min date-range lookup by start_utc.
        """
        try:
            base = "https://api.openf1.org/v1"

            if session_key:
                # Direct lookup — no date-range search needed
                sr = self.session.get(f"{base}/sessions?session_key={session_key}", timeout=10)
                if not sr.ok:
                    print(f"[F1] OpenF1 sessions HTTP {sr.status_code} (key={session_key})")
                    return None
                sess_list = sr.json()
                if isinstance(sess_list, dict):
                    print(f"[F1] OpenF1 sessions error: {str(sess_list)[:80]}")
                    return None
                if not sess_list or not isinstance(sess_list, list):
                    return None
                s  = sess_list[0]
                sk = s.get('session_key')
                if not sk:
                    return None
            else:
                # Search for the session by date range (±90 min of start_utc) so we get
                # the correct session even when a later session has become "latest".
                window_start = (start_utc - timedelta(minutes=90)).strftime('%Y-%m-%dT%H:%M:%SZ')
                window_end   = (start_utc + timedelta(minutes=90)).strftime('%Y-%m-%dT%H:%M:%SZ')
                url = (f"{base}/sessions"
                       f"?date_start>={window_start}&date_start<={window_end}")
                r = self.session.get(url, timeout=10)
                if not r.ok: return None
                results = r.json()
                if isinstance(results, dict):
                    print(f"[F1] OpenF1 sessions error: {str(results)[:80]}")
                    return None
                if not results or not isinstance(results, list):
                    return None
                # Pick the session whose date_start is closest to our start_utc
                def _dist(sess):
                    try:
                        sd = datetime.fromisoformat(str(sess.get('date_start', '')).replace('Z', '+00:00'))
                        if sd.tzinfo is None:
                            sd = sd.replace(tzinfo=timezone.utc)
                        return abs((sd - start_utc).total_seconds())
                    except Exception:
                        return float('inf')
                s  = min(results, key=_dist)
                sk = s.get('session_key')
                if not sk:
                    return None

            # Drivers
            drivers_r = self.session.get(f"{base}/drivers?session_key={sk}", timeout=10)
            if not drivers_r.ok: return None
            driver_info = {d['driver_number']: d for d in drivers_r.json()}

            # Positions
            pos_r = self.session.get(f"{base}/position?session_key={sk}", timeout=10)
            if not pos_r.ok: return None
            positions = pos_r.json()
            latest_pos = {}
            for p in positions:
                dn = p['driver_number']
                if dn not in latest_pos or p['date'] > latest_pos[dn]['date']:
                    latest_pos[dn] = p

            # Intervals / Laps (for gap)
            is_qual = 'qual' in s.get('session_name', '').lower()
            best_lap = {}
            intervals = {}
            if is_qual:
                laps_r = self.session.get(f"{base}/laps?session_key={sk}", timeout=10)
                if laps_r.ok:
                    for lap in laps_r.json():
                        dn = lap['driver_number']
                        dur = lap.get('lap_duration')
                        if dur and (dn not in best_lap or dur < best_lap[dn]):
                            best_lap[dn] = dur
            else:
                int_r = self.session.get(f"{base}/intervals?session_key={sk}", timeout=10)
                if int_r.ok:
                    for iv in int_r.json():
                        dn = iv['driver_number']
                        if dn not in intervals or iv['date'] > intervals[dn]['date']:
                            intervals[dn] = iv

            ranked = sorted(latest_pos.values(), key=lambda x: x['position'])
            leader_time = best_lap.get(ranked[0]['driver_number']) if ranked and is_qual else None

            # Pre-compute intervals from gap_to_leader for race sessions where
            # interval_to_position_ahead may be absent.
            computed_interval = {}
            if not is_qual:
                prev_gtl = 0.0
                for p in ranked:
                    dn = p['driver_number']
                    iv = intervals.get(dn, {})
                    raw_gtl = iv.get('gap_to_leader')
                    try:
                        gtl_f = float(raw_gtl)
                        computed_interval[dn] = gtl_f - prev_gtl
                        prev_gtl = gtl_f
                    except (TypeError, ValueError):
                        pass

            drivers = []
            for p in ranked:
                dn = p['driver_number']
                pos = p['position']
                drv = driver_info.get(dn, {})
                team = drv.get('team_name', '')
                code = drv.get('name_acronym', str(dn))
                name = drv.get('full_name', f"Driver {dn}")

                gap = ""
                if is_qual:
                    bt = best_lap.get(dn)
                    if bt:
                        if pos == 1:
                            gap = _f1_format_qual_time(bt)
                        elif leader_time:
                            gap = f"+{bt - leader_time:.3f}"
                else:
                    iv = intervals.get(dn, {})
                    if pos == 1:
                        gap = "Leader"
                    else:
                        # Prefer native interval; fall back to computed from gap_to_leader
                        itpa = iv.get('interval_to_position_ahead')
                        if itpa is not None:
                            try:
                                gap = _f1_compact_gap(f"+{float(itpa):.3f}", pos)
                            except Exception:
                                gap = _f1_compact_gap(str(itpa), pos)
                        elif dn in computed_interval:
                            gap = _f1_compact_gap(f"+{computed_interval[dn]:.3f}", pos)

                drivers.append({
                    'pos': pos,
                    'name': name.title(),
                    'abbr': code,
                    'car': str(dn),
                    'team': team,
                    'team_logo': '',
                    'car_illustration': _f1_car_url(team),
                    'livery_primary': _f1_team_color(team),
                    'livery_secondary': '#111111',
                    'gap': gap,
                    'speed': '',
                    'status': 'Active',
                    'on_track': True,
                })
            return drivers
        except Exception as e:
            print(f"[F1] OpenF1 fetch error: {e}")
            return None

    def _fetch_f1(self, force=False):
        """Return a list of F1 game objects — one per relevant session today."""
        self.__init_f1_cache()
        now_ts  = time.time()
        now_utc = datetime.now(timezone.utc)

        races = self._fetch_f1_schedule()
        if not races:
            return [c['data'] for c in self._f1_session_caches.values() if c.get('data')]

        session_list = _find_f1_sessions(races, now_utc)
        if not session_list:
            self._f1_session_caches.clear()
            return []

        # Fetch SignalR data once — it covers whichever session is currently live.
        has_live     = any(state == 'in' for *_, state in session_list)
        sig_client   = _f1_signalr.get_client() if has_live else None
        sig_data     = sig_client.get_live_data() if sig_client else {}
        live_signalr = sig_data if (sig_client and sig_client.is_connected and has_live) else {}

        games       = []
        current_ids = set()
        for race, sess_key, sess_name, is_practice, start_utc, end_utc, state in session_list:
            session_id = f"f1_{race.get('round', 'r')}_{sess_key.lower()}"
            current_ids.add(session_id)

            cache = self._f1_session_caches.get(session_id, {'ts': 0.0, 'data': None})
            if not force and (now_ts - cache['ts']) < self._f1_ttl and cache['data']:
                games.append(cache['data'])
                continue

            game = self._build_f1_game(
                race, sess_key, sess_name, is_practice,
                start_utc, end_utc, state, now_utc, live_signalr,
            )
            if game:
                self._f1_session_caches[session_id] = {'ts': now_ts, 'data': game}
                games.append(game)

        # Evict cache entries for sessions that are no longer relevant.
        for sid in list(self._f1_session_caches.keys()):
            if sid not in current_ids:
                del self._f1_session_caches[sid]

        return games

    def _build_f1_game(self, race, sess_key, sess_name, is_practice,
                       start_utc, end_utc, state, now_utc, live_signalr):
        """Build a single F1 game object for one session."""
        circuit   = race.get('Circuit', {})
        race_name = str(race.get('raceName', 'Formula 1')).strip()
        locality  = circuit.get('Location', {}).get('locality', '')
        circ_name = str(circuit.get('circuitName') or locality or race_name).strip()
        event     = _f1_short_event(race_name)
        track     = circ_name
        session_id    = f"f1_{race.get('round', 'r')}_{sess_key.lower()}"
        start_utc_str = start_utc.strftime('%Y-%m-%dT%H:%M:%SZ')

        # ── Driver list ───────────────────────────────────────────────────────
        drivers = []
        if live_signalr and state == 'in' and live_signalr.get('driver_list'):
            drivers = _drivers_from_signalr(live_signalr)
            if drivers:
                self._f1_signalr_snapshots[session_id] = list(drivers)

        if not drivers and state in ('in', 'post'):
            # Pass 'latest' for live sessions — skips the date-range search and
            # hits the current session directly, which is faster and more reliable.
            sk_hint = 'latest' if state == 'in' else None
            drivers = self._fetch_openf1_live(start_utc, session_key=sk_hint) or []

        if not drivers and state == 'post':
            drivers = list(self._f1_signalr_snapshots.get(session_id, []))

        if not drivers and state == 'post' and sess_key == 'Race':
            for res in self._fetch_f1_results():
                drv  = res.get('Driver', {})
                ctor = res.get('Constructor', {})
                team = ctor.get('name', '')
                try:
                    pos = int(res.get('position', 999))
                except Exception:
                    pos = 999
                code    = str(drv.get('code') or '').upper()[:3]
                name    = f"{drv.get('givenName', '')} {drv.get('familyName', '')}".strip().title()
                car     = str(drv.get('permanentNumber') or res.get('number') or '').strip()
                gap_val = res.get('Time', {}).get('time') or res.get('status', '')
                if pos == 1 and 'qual' in sess_name.lower() and gap_val and ':' not in gap_val and gap_val.replace('.', '', 1).isdigit():
                    gap = _f1_format_qual_time(gap_val)
                else:
                    gap = _f1_compact_gap(gap_val, pos)
                drivers.append({
                    'pos':              pos,
                    'name':             name or 'Driver',
                    'abbr':             code,
                    'car':              car,
                    'team':             team,
                    'team_logo':        '',
                    'car_illustration': _f1_car_url(team),
                    'livery_primary':   _f1_team_color(team),
                    'livery_secondary': '#111111',
                    'gap':              gap,
                    'speed':            '',
                    'status':           'Active',
                    'on_track':         True,
                })
            drivers.sort(key=lambda d: d['pos'])

        # ── Status display ────────────────────────────────────────────────────
        ts_code   = str(live_signalr.get('track_status', {}).get('Status', '1')).strip() if state == 'in' else '1'
        lap_count = live_signalr.get('lap_count', {}) if state == 'in' else {}
        extrap    = live_signalr.get('extrapolated_clock', {}) if state == 'in' else {}
        cur_lap   = lap_count.get('CurrentLap')
        tot_lap   = lap_count.get('TotalLaps')
        remaining = _f1_sanitize_time_text(str(extrap.get('Remaining') or '').split('.')[0])

        if state == 'post':
            status_display = 'FINAL'
        elif state == 'in':
            if is_practice:
                status_display = _F1LT_TRACK_STATUS.get(ts_code, 'GREEN')
            else:
                if cur_lap and tot_lap:
                    status_display = f"Lap {cur_lap}/{tot_lap}"
                elif remaining and remaining not in ('', '0:00:00', '0:00'):
                    status_display = remaining
                else:
                    status_display = _F1LT_TRACK_STATUS.get(ts_code, 'GREEN')
        else:
            try:
                utc_off = _core.state.get('utc_offset', -5)
                local_tz = timezone(timedelta(hours=utc_off))
                status_display = start_utc.astimezone(local_tz).strftime('%I:%M %p').lstrip('0')
            except Exception:
                status_display = 'Starts Soon'

        if state == 'in':
            flag = _F1LT_TRACK_STATUS.get(ts_code, 'GREEN')
        else:
            flag = _f1_flag_for_state(state)  # WHITE for pre, CHECKERED for post
        cur_lap_val = int(cur_lap or 0)
        tot_lap_val = int(tot_lap or 0)

        return {
            'id':           session_id,
            'type':         'racing',
            'sport':        'f1',
            'state':        state,
            'status':       status_display,
            'is_shown':     True,
            'startTimeUTC': start_utc_str,
            'away_abbr':    event,
            'home_abbr':    sess_name,
            'away_score':   '',
            'home_score':   '',
            'f1': {
                'event_name':     event,
                'short_name':     event,
                'track_name':     track,
                'session_type':   sess_name,
                'session_name':   sess_name,
                'lap':            cur_lap_val,
                'total_laps':     tot_lap_val,
                'laps_remaining': max(0, tot_lap_val - cur_lap_val),
                'time_to_go':     _f1_sanitize_time_text(
                    _f1_duration_text((start_utc - now_utc).total_seconds()) if state == 'pre'
                    else _f1_duration_text((end_utc - now_utc).total_seconds()) if state == 'in' and is_practice
                    else ''
                ),
                'caution':        flag in ('YELLOW', 'SAFETY CAR', 'VSC', 'RED FLAG'),
                'flag':           flag,
                'drivers':        drivers,
                'weather':        {},
            },
        }
