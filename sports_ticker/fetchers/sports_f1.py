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
_OPENF1_BASE  = "https://api.openf1.org/v1"

_OPENF1_LIVE_TTL = 15.0   # refresh live positions every 15 s during a session
_OPENF1_SK_TTL   = 300.0  # cache the session_key lookup for 5 min

_F1_CAR_URL = (
    "https://media.formula1.com/image/upload/c_lfill,h_224/q_auto/"
    "d_common:f1:2026:fallback:car:2026fallbackcarright.webp/"
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
    'andretti':     'cadillac',   # Cadillac/Andretti
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
    'audi':         '#C0C0C0',
    'sauber':       '#C0C0C0',
    'kick sauber':  '#C0C0C0',
    'cadillac':     '#CC0000',
    'andretti':     '#CC0000',
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


def _f1_driver_record(
    pos,
    name,
    abbr,
    car,
    team,
    gap,
    speed='',
    status='Active',
    on_track=True,
):
    """Canonical racing driver dict for F1 fetch + display paths."""
    team = str(team or '')
    tc = ''
    livery = _f1_team_color(team)
    return {
        'pos': int(pos) if pos is not None else 999,
        'name': str(name or 'Driver').strip(),
        'abbr': str(abbr or car or '')[:3].upper(),
        'car': str(car or ''),
        'team': team,
        'team_logo': '',
        'car_illustration': _f1_car_url(team),
        'livery_primary': livery,
        'livery_secondary': '#111111',
        'gap': str(gap or ''),
        'speed': str(speed or ''),
        'status': status,
        'on_track': on_track,
    }


def _f1_parse_laptime_s(t):
    """'1:28.653' or '28.653' → seconds as float."""
    parts = str(t or '').strip().split(':')
    if len(parts) == 2:
        return int(parts[0]) * 60 + float(parts[1])
    return float(parts[0])


def _f1_fmt_laptime(seconds):
    """88.965 → '1:28.965'"""
    m = int(seconds) // 60
    s = seconds - m * 60
    return f"{m}:{s:06.3f}"


def _f1_race_gap(pos, time_val, status):
    """Format gap for a race/sprint result entry."""
    if pos == 1:
        return 'Leader'
    if time_val:
        # Jolpica already includes the leading '+' (e.g. '+3.264')
        return time_val if time_val.startswith('+') else f"+{time_val}"
    if not status or status == 'Finished':
        return ''
    # Lapped cars: '+1 Lap', '+2 Laps', or 'Lapped'
    sl = status.lower()
    if sl == 'lapped':
        return '+1 Lap'
    if 'lap' in sl:
        return status   # already formatted e.g. '+2 Laps'
    return ''


def _f1_qual_gap(all_results, pos, best_time):
    """Format gap for a qualifying result entry relative to P1."""
    if not best_time:
        return ''
    if pos == 1:
        try:
            return _f1_fmt_laptime(_f1_parse_laptime_s(best_time))
        except Exception:
            return best_time
    leader_time = ''
    for r in all_results:
        try:
            if int(r.get('position', 999)) == 1:
                leader_time = r.get('Q3') or r.get('Q2') or r.get('Q1') or ''
                break
        except Exception:
            pass
    if leader_time and best_time:
        try:
            gap_s = _f1_parse_laptime_s(best_time) - _f1_parse_laptime_s(leader_time)
            return f"+{gap_s:.3f}"
        except Exception:
            pass
    return best_time


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

        team = str(dl_info.get('TeamName') or '')

        gap_raw = tl.get('GapToLeader', '')
        if isinstance(gap_raw, dict):
            gap_raw = gap_raw.get('Value', '')
        gap = _f1_race_gap(pos, str(gap_raw).strip(), '')

        full_name = str(dl_info.get('FullName') or dl_info.get('BroadcastName') or f"#{num}").strip()
        tla       = str(dl_info.get('Tla') or num)[:3].upper()

        drivers.append(_f1_driver_record(
            pos, full_name.title(), tla, str(num), team, gap,
        ))

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

    def _fetch_f1_results(self, force=False, round_num=None, sess_key='Race'):
        """Fetch driver results from Jolpica, choosing the best endpoint for the session.

        Returns (results_list, result_type) where result_type is 'race', 'sprint',
        or 'qualifying' — callers use this to format gaps appropriately.
        """
        self.__init_f1_cache()
        now = time.time()

        cache_key = f"{round_num}_{sess_key}"
        cached_map = self._f1_results_cache.get('data') or {}
        if not force and (now - self._f1_results_cache.get('ts', 0)) < _F1_RESULTS_TTL:
            if cache_key in cached_map:
                return cached_map[cache_key]

        is_qual   = sess_key in ('Qualifying', 'SprintQualifying')
        is_sprint = sess_key == 'Sprint'

        # Endpoints to try in priority order: round-specific first, then fallback to last
        if is_qual:
            endpoints = [
                (f'current/{round_num}/qualifying.json', 'QualifyingResults', 'qualifying'),
                ('current/last/qualifying.json',         'QualifyingResults', 'qualifying'),
                ('current/last/results.json',            'Results',           'race'),
            ]
        elif is_sprint:
            endpoints = [
                (f'current/{round_num}/sprint.json', 'SprintResults', 'sprint'),
                ('current/last/sprint.json',         'SprintResults', 'sprint'),
                ('current/last/results.json',        'Results',       'race'),
            ]
        else:
            endpoints = [
                (f'current/{round_num}/results.json', 'Results', 'race'),
                ('current/last/results.json',         'Results', 'race'),
            ]

        for path, rkey, rtype in endpoints:
            try:
                data    = self._jolpica_get(path)
                races   = data.get('MRData', {}).get('RaceTable', {}).get('Races', [])
                results = races[0].get(rkey, []) if races else []
                if results:
                    entry = (results, rtype)
                    cached_map[cache_key] = entry
                    self._f1_results_cache = {'ts': now, 'data': cached_map}
                    return entry
            except Exception as exc:
                print(f"[F1] {path} fetch error: {exc}")

        return ([], 'race')

    def _openf1_get(self, path):
        url = f"{_OPENF1_BASE}/{path.lstrip('/')}"
        r = self.session.get(url, headers=HEADERS, timeout=TIMEOUTS.get('default', 10))
        r.raise_for_status()
        return r.json()

    def _get_openf1_session_key(self, start_utc, end_utc, force=False):
        """Return the OpenF1 session_key whose start time is within 3 h of start_utc."""
        self.__init_f1_cache()
        now = time.time()
        sk_cache = getattr(self, '_openf1_sk_cache', {'ts': 0, 'key': None})
        if not force and (now - sk_cache['ts']) < _OPENF1_SK_TTL and sk_cache['key']:
            return sk_cache['key']
        try:
            sessions = self._openf1_get('sessions?session_key=latest')
            if not sessions:
                return None
            s = sessions[0] if isinstance(sessions, list) else sessions
            raw = str(s.get('date_start') or '').replace('Z', '+00:00')
            s_start = datetime.fromisoformat(raw)
            if s_start.tzinfo is None:
                s_start = s_start.replace(tzinfo=timezone.utc)
            diff = abs((s_start - start_utc).total_seconds())
            key = s['session_key'] if diff < 10800 else None
            self._openf1_sk_cache = {'ts': now, 'key': key}
            return key
        except Exception as exc:
            print(f"[F1] OpenF1 session lookup error: {exc}")
            return None

    def _fetch_openf1_drivers(self, session_key, is_qual, force=False):
        """Fetch live positions + best laps / intervals from OpenF1."""
        self.__init_f1_cache()
        now = time.time()
        of1_cache = getattr(self, '_openf1_drv_cache', {'ts': 0, 'sk': None, 'data': []})
        if (not force and of1_cache.get('sk') == session_key
                and (now - of1_cache['ts']) < _OPENF1_LIVE_TTL
                and of1_cache.get('data')):
            return of1_cache['data']
        try:
            drv_list = {
                d['driver_number']: d
                for d in self._openf1_get(f"drivers?session_key={session_key}")
            }
            positions_raw = self._openf1_get(f"position?session_key={session_key}")
            latest_pos = {}
            for p in positions_raw:
                dn = p['driver_number']
                if dn not in latest_pos or p['date'] > latest_pos[dn]['date']:
                    latest_pos[dn] = p

            best_lap: dict[int, float] = {}
            gap_map:  dict[int, dict]  = {}
            if is_qual:
                for lap in self._openf1_get(f"laps?session_key={session_key}"):
                    dn  = lap['driver_number']
                    dur = lap.get('lap_duration')
                    if dur and (dn not in best_lap or dur < best_lap[dn]):
                        best_lap[dn] = dur
            else:
                for iv in self._openf1_get(f"intervals?session_key={session_key}"):
                    dn = iv['driver_number']
                    if dn not in gap_map or iv['date'] > gap_map[dn]['date']:
                        gap_map[dn] = iv

            ranked = sorted(latest_pos.values(), key=lambda x: x['position'])
            leader_dn   = ranked[0]['driver_number'] if ranked else None
            leader_best = best_lap.get(leader_dn) if leader_dn else None

            drivers = []
            for p in ranked:
                dn   = p['driver_number']
                drv  = drv_list.get(dn, {})
                pos  = p['position']
                team = str(drv.get('team_name') or '')
                tc   = str(drv.get('team_colour') or '').strip().lstrip('#')
                livery = f"#{tc}" if tc else _f1_team_color(team)

                if pos == 1:
                    gap = _f1_fmt_laptime(leader_best) if (is_qual and leader_best) else 'Leader'
                elif is_qual:
                    bt  = best_lap.get(dn)
                    gap = f"+{bt - leader_best:.3f}" if (bt and leader_best) else ''
                else:
                    iv  = gap_map.get(dn, {})
                    gtl = iv.get('gap_to_leader')
                    gap = _f1_race_gap(pos, str(gtl) if gtl is not None else '', '')

                name = f"{drv.get('first_name','')  } {drv.get('last_name','')  }".strip().title()
                code = str(drv.get('name_acronym') or dn)[:3].upper()

                drivers.append(_f1_driver_record(
                    pos, name or 'Driver', code, str(dn), team, gap,
                ))

            self._openf1_drv_cache = {'ts': now, 'sk': session_key, 'data': drivers}
            return drivers
        except Exception as exc:
            print(f"[F1] OpenF1 drivers error: {exc}")
            return []

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

        # ── 2. Optional SignalR overlay (set F1_SIGNALR=1 to enable; blocked on most servers) ──
        signalr_client = _f1_signalr.get_client()
        signalr_data = signalr_client.get_live_data() if signalr_client else {}
        live_signalr = (
            signalr_data
            if signalr_client and signalr_client.is_connected and state == 'in'
            else {}
        )

        is_qual_sess = sess_key in ('Qualifying', 'SprintQualifying')

        # ── 3. Driver list (priority: SignalR → OpenF1 → Jolpica) ────────────
        drivers = []
        if live_signalr and live_signalr.get('driver_list'):
            drivers = _drivers_from_signalr(live_signalr)

        # OpenF1: free live-timing API with real positions and best laps
        if not drivers:
            of1_sk = self._get_openf1_session_key(start_utc, end_utc, force=force)
            if of1_sk:
                drivers = self._fetch_openf1_drivers(of1_sk, is_qual_sess, force=force)

        if not drivers:
            round_num = str(race.get('round') or '')
            results, result_type = self._fetch_f1_results(
                round_num=round_num, sess_key=sess_key
            )
            for res in results:
                drv  = res.get('Driver', {})
                ctor = res.get('Constructor', {})
                team = ctor.get('name', '')
                try:
                    pos = int(res.get('position', 999))
                except Exception:
                    pos = 999
                code = str(drv.get('code') or '').upper()[:3]
                name = f"{drv.get('givenName', '')} {drv.get('familyName', '')}".strip().title()
                car  = str(drv.get('permanentNumber') or res.get('number') or '').strip()

                if result_type == 'qualifying':
                    best_time = res.get('Q3') or res.get('Q2') or res.get('Q1') or ''
                    gap = _f1_qual_gap(results, pos, best_time)
                else:
                    gap = _f1_race_gap(
                        pos,
                        res.get('Time', {}).get('time') or '',
                        res.get('status', ''),
                    )

                drivers.append(_f1_driver_record(
                    pos, name or 'Driver', code, car, team, gap,
                ))
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
