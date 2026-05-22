"""Formula 1 fetcher using Jolpica (ergast) for the session schedule.

livetiming.formula1.com blocks server IPs; all session metadata now comes from
Jolpica which carries the full calendar including per-session start times.
SignalR is kept as an optional live-timing overlay — if it ever becomes
accessible it will upgrade the card with real positions and lap counts.
"""

from datetime import datetime, timezone, timedelta

from .. import core as _core
globals().update({k: v for k, v in vars(_core).items() if not k.startswith('__')})

from . import f1_signalr as _f1_signalr

_JOLPICA_BASE = "https://api.jolpi.ca/ergast/f1"

_F1_CAR_URL = (
    "https://media.formula1.com/image/upload/c_lfill,h_224/q_auto/"
    "d_common:f1:2026:fallback:car:2026fallbackcarright.webp/"
    "v1740000001/common/f1/2026/{slug}/2026{slug}carright.webp"
)

_F1_TEAM_SLUGS = {
    'mclaren':      'mclaren',
    'mercedes':     'mercedes',
    'ferrari':      'ferrari',
    'red bull':     'red-bull-racing',
    'racing bulls': 'racing-bulls',
    'rb':           'racing-bulls',
    'aston martin': 'aston-martin',
    'alpine':       'alpine',
    'williams':     'williams',
    'haas':         'haas',
    'sauber':       'kick-sauber',
    'kick sauber':  'kick-sauber',
}

_F1_TEAM_COLORS = {
    'mclaren':      '#FF8000',
    'mercedes':     '#27F4D2',
    'ferrari':      '#E8002D',
    'red bull':     '#3671C6',
    'racing bulls': '#6692FF',
    'rb':           '#6692FF',
    'aston martin': '#229971',
    'alpine':       '#FF87BC',
    'williams':     '#64C4FF',
    'haas':         '#B6BABD',
    'sauber':       '#52E252',
    'kick sauber':  '#52E252',
}

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


def _f1_short_event(name):
    text = str(name or 'Formula 1').strip()
    text = text.replace('FORMULA 1', '').replace('GRAND PRIX', 'GP')
    text = ' '.join(text.split())
    return text.title() or 'Formula 1'


def _f1_flag_for_state(state):
    return {'pre': 'WHITE', 'post': 'CHECKERED'}.get(str(state or '').lower(), 'GREEN')


def _f1_compact_gap(value, position):
    if position == 1:
        return 'Leader'
    if value in (None, ''):
        return ''
    text = str(value).strip()
    try:
        return f"+{float(text):.3f}"
    except Exception:
        return text[:10]


def _f1_team_match(team_name):
    lower = str(team_name or '').strip().lower()
    for key in _F1_TEAM_SLUGS:
        if key in lower:
            return key
    return ''


def _f1_car_url(team_name):
    key = _f1_team_match(team_name)
    slug = _F1_TEAM_SLUGS.get(key, '')
    return _F1_CAR_URL.format(slug=slug) if slug else ''


def _f1_team_color(team_name):
    key = _f1_team_match(team_name)
    return _F1_TEAM_COLORS.get(key, '#888888')


def _f1_parse_session_utc(sess_dict):
    """Parse a Jolpica session dict {'date': 'YYYY-MM-DD', 'time': 'HH:MM:SSZ'} → UTC datetime."""
    try:
        d = str(sess_dict.get('date', ''))
        t = str(sess_dict.get('time', '00:00:00Z')).rstrip('Z')
        return datetime.fromisoformat(f"{d}T{t}").replace(tzinfo=timezone.utc)
    except Exception:
        return None


def _find_f1_session(races, now_utc):
    """Scan the season calendar and return the active/next/post session for today.

    Returns (race_dict, sess_key, sess_name, is_practice, start_utc, end_utc, state)
    or None if no session is scheduled today or currently live.
    """
    today = now_utc.date()

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

        # Is today within this race weekend?
        weekend_start = min(s[3] for s in sessions)
        weekend_end   = max(s[4] for s in sessions)
        if not (weekend_start.date() <= today <= weekend_end.date()):
            continue

        # 1. Currently live?
        for key, name, ip, start, end in sessions:
            if start <= now_utc <= end:
                return race, key, name, ip, start, end, 'in'

        # 2. Most recently completed session today?
        past = [(k, n, ip, s, e) for k, n, ip, s, e in sessions
                if s.date() == today and e < now_utc]
        if past:
            k, n, ip, s, e = past[-1]
            return race, k, n, ip, s, e, 'post'

        # 3. Next upcoming session today?
        future = sorted(
            [(k, n, ip, s, e) for k, n, ip, s, e in sessions
             if s.date() == today and s > now_utc],
            key=lambda x: x[3]
        )
        if future:
            k, n, ip, s, e = future[0]
            return race, k, n, ip, s, e, 'pre'

        # Race weekend day with no sessions scheduled (e.g. Thursday media day)
        return None

    return None


def _drivers_from_signalr(live_data):
    """Build a sorted driver list from a SignalR live snapshot."""
    driver_list  = live_data.get('driver_list', {})
    timing_lines = live_data.get('timing_lines', {})
    if not driver_list:
        return []

    drivers = []
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

        gap_raw = tl.get('GapToLeader', '')
        if isinstance(gap_raw, dict):
            gap_raw = gap_raw.get('Value', '')
        gap = _f1_compact_gap(gap_raw, pos)

        full_name = str(dl_info.get('FullName') or dl_info.get('BroadcastName') or f"#{num}").strip()
        tla       = str(dl_info.get('Tla') or num)[:3].upper()

        drivers.append({
            'pos':              pos,
            'name':             full_name.title(),
            'abbr':             tla,
            'car':              str(num),
            'team':             team,
            'team_logo':        '',
            'car_illustration': _f1_car_url(team),
            'livery_primary':   livery,
            'livery_secondary': '#111111',
            'gap':              gap,
            'speed':            '',
            'status':           'Active',
            'on_track':         True,
        })

    drivers.sort(key=lambda d: d['pos'])
    return drivers


class SportsF1Mixin:
    def __init_f1_cache(self):
        if not hasattr(self, '_f1_cache'):
            self._f1_cache          = {'ts': 0.0, 'data': None}
            self._f1_schedule_cache = {'ts': 0.0, 'data': []}
            self._f1_results_cache  = {'ts': 0.0, 'data': []}
            self._f1_ttl            = 30.0

    def _jolpica_get(self, path):
        url = f"{_JOLPICA_BASE}/{path.lstrip('/')}"
        r = self.session.get(url, headers=HEADERS, timeout=TIMEOUTS.get('default', 10))
        r.raise_for_status()
        return r.json()

    def _fetch_f1_schedule(self, force=False):
        """Fetch the full season race calendar from Jolpica (cached 1 h)."""
        self.__init_f1_cache()
        now = time.time()
        cache = self._f1_schedule_cache
        if not force and (now - cache['ts']) < _F1_SCHEDULE_TTL and cache['data']:
            return cache['data']
        try:
            data  = self._jolpica_get('current.json')
            races = data.get('MRData', {}).get('RaceTable', {}).get('Races', [])
            self._f1_schedule_cache = {'ts': now, 'data': races}
            return races
        except Exception as exc:
            print(f"[F1] Schedule fetch error: {exc}")
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

    def _fetch_f1(self, force=False):
        """Return an F1 game object for today's session, or None if no session today."""
        self.__init_f1_cache()
        now_ts = time.time()
        if not force and (now_ts - self._f1_cache.get('ts', 0.0)) < self._f1_ttl:
            return self._f1_cache.get('data')

        now_utc = datetime.now(timezone.utc)

        # ── 1. Find today's session from the Jolpica calendar ─────────────────
        races = self._fetch_f1_schedule()
        if not races:
            return self._f1_cache.get('data')

        result = _find_f1_session(races, now_utc)
        if result is None:
            # No session today — hide the card
            self._f1_cache = {'ts': now_ts, 'data': None}
            return None

        race, sess_key, sess_name, is_practice, start_utc, end_utc, state = result

        # Circuit / event metadata
        circuit    = race.get('Circuit', {})
        race_name  = str(race.get('raceName', 'Formula 1')).strip()
        locality   = circuit.get('Location', {}).get('locality', '')
        circ_name  = str(circuit.get('circuitName') or locality or race_name).strip()
        event      = _f1_short_event(race_name)
        track      = circ_name
        session_id = f"f1_{race.get('round', 'r')}_{sess_key.lower()}"
        start_utc_str = start_utc.strftime('%Y-%m-%dT%H:%M:%SZ')

        # ── 2. Optional SignalR overlay (real positions/laps when connected) ───
        signalr_client = _f1_signalr.get_client()
        signalr_data   = signalr_client.get_live_data() if signalr_client else {}
        live_signalr   = (signalr_data
                          if signalr_client and signalr_client.is_connected and state == 'in'
                          else {})

        # ── 3. Driver list ────────────────────────────────────────────────────
        drivers = []
        if live_signalr and live_signalr.get('driver_list'):
            drivers = _drivers_from_signalr(live_signalr)

        if not drivers:
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
                gap     = ('Leader' if pos == 1
                           else (f"+{gap_val}" if gap_val and gap_val not in ('Finished', 'Lapped') else ''))
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

        # ── 4. Status display ─────────────────────────────────────────────────
        ts_code   = str(live_signalr.get('track_status', {}).get('Status', '1')).strip()
        lap_count = live_signalr.get('lap_count', {})
        extrap    = live_signalr.get('extrapolated_clock', {})
        cur_lap   = lap_count.get('CurrentLap')
        tot_lap   = lap_count.get('TotalLaps')
        remaining = str(extrap.get('Remaining') or '').split('.')[0]

        if state == 'post':
            status_display = 'FINAL'
        elif state == 'in':
            if is_practice:
                status_display = _F1LT_TRACK_STATUS.get(ts_code, 'GREEN')
            else:
                if cur_lap and tot_lap:
                    status_display = f"Lap {cur_lap}/{tot_lap}"
                elif remaining and remaining not in ('', '0:00:00'):
                    status_display = remaining
                else:
                    status_display = _F1LT_TRACK_STATUS.get(ts_code, 'GREEN')
        else:
            try:
                status_display = start_utc.strftime('%I:%M %p').lstrip('0')
            except Exception:
                status_display = 'Starts Soon'

        flag        = _F1LT_TRACK_STATUS.get(ts_code, _f1_flag_for_state(state))
        cur_lap_val = int(cur_lap or 0)
        tot_lap_val = int(tot_lap or 0)

        # ── 5. Build game object ──────────────────────────────────────────────
        game = {
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
                'caution':        flag in ('YELLOW', 'SAFETY CAR', 'VSC', 'RED FLAG'),
                'flag':           flag,
                'drivers':        drivers,
                'weather':        {},
            },
        }
        self._f1_cache = {'ts': now_ts, 'data': game}
        return game
