"""Formula 1 fetcher using F1 Live Timing (livetiming.formula1.com) + Jolpica."""

from datetime import datetime, timezone, timedelta

from .. import core as _core
globals().update({k: v for k, v in vars(_core).items() if not k.startswith('__')})

from . import f1_signalr as _f1_signalr

_F1LT_BASE  = "https://livetiming.formula1.com/static"
_JOLPICA_BASE = "https://api.jolpi.ca/ergast/f1"

_F1_CAR_URL = (
    "https://media.formula1.com/image/upload/c_lfill,h_224/q_auto/"
    "d_common:f1:2026:fallback:car:2026fallbackcarright.webp/"
    "v1740000001/common/f1/2026/{slug}/2026{slug}carright.webp"
)

# Keyed by lowercase substring of constructor name/id
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

# SessionStatus values that indicate a live session
_F1LT_LIVE_STATUSES = frozenset({'Started', 'Aborted', 'Ends'})


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
        num = float(text)
        return f"+{num:.3f}"
    except Exception:
        return text[:10]


def _f1_team_match(team_name):
    """Return the first key in _F1_TEAM_SLUGS/COLORS that appears in team_name."""
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


def _f1lt_to_utc(date_str, gmt_offset_str):
    """Convert F1 live timing local datetime + GMT offset string to UTC datetime."""
    dt = datetime.fromisoformat(str(date_str))
    sign = -1 if str(gmt_offset_str).startswith('-') else 1
    parts = str(gmt_offset_str).lstrip('+-').split(':')
    offset = timedelta(hours=int(parts[0]), minutes=int(parts[1]) if len(parts) > 1 else 0)
    return dt.replace(tzinfo=timezone.utc) - (sign * offset)


def _drivers_from_signalr(live_data):
    """Build a sorted driver list from the SignalR timing snapshot."""
    driver_list  = live_data.get('driver_list', {})
    timing_lines = live_data.get('timing_lines', {})
    if not driver_list:
        return []

    drivers = []
    for num, dl_info in driver_list.items():
        if not isinstance(dl_info, dict):
            continue
        tl = timing_lines.get(str(num), {}) if isinstance(timing_lines.get(str(num)), dict) else {}

        try:
            pos = int(tl.get('Position') or 999)
        except Exception:
            pos = 999

        team = str(dl_info.get('TeamName') or '')
        tc   = str(dl_info.get('TeamColour') or '').strip().lstrip('#')
        livery = f"#{tc}" if tc else _f1_team_color(team)

        # GapToLeader may be a plain string or a dict with a 'Value' key
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
            self._f1_cache = {'ts': 0.0, 'data': None}
            self._f1_ttl = 30.0

    def _f1lt_get(self, path):
        """GET a JSON file from the F1 live timing static CDN."""
        url = f"{_F1LT_BASE}/{path.lstrip('/')}"
        r = self.session.get(url, headers=HEADERS, timeout=TIMEOUTS.get('default', 10))
        r.raise_for_status()
        return r.json()

    def _jolpica_get(self, path):
        """GET a JSON resource from the Jolpica/Ergast F1 API."""
        url = f"{_JOLPICA_BASE}/{path.lstrip('/')}"
        r = self.session.get(url, headers=HEADERS, timeout=TIMEOUTS.get('default', 10))
        r.raise_for_status()
        return r.json()

    def _fetch_f1(self, force=False):
        """Fetch the current F1 session using F1 Live Timing + Jolpica."""
        self.__init_f1_cache()
        now_ts = time.time()
        if not force and (now_ts - self._f1_cache.get('ts', 0.0)) < self._f1_ttl:
            return self._f1_cache.get('data')

        # ── 1. Session info from F1 live timing ──────────────────────────────
        try:
            si = self._f1lt_get('SessionInfo.json')
        except Exception as exc:
            print(f"[F1] SessionInfo fetch error: {exc}")
            return self._f1_cache.get('data')

        session_status = str(si.get('SessionStatus', '')).strip()
        session_type   = str(si.get('Type', '')).strip()
        session_name   = str(si.get('Name') or si.get('Type') or 'Session').strip()
        gmt_offset     = str(si.get('GmtOffset', '+00:00:00'))
        meeting        = si.get('Meeting', {})
        circuit        = meeting.get('Circuit', {})

        event = _f1_short_event(meeting.get('OfficialName') or meeting.get('Name') or circuit.get('ShortName'))
        track = str(circuit.get('ShortName') or meeting.get('Location') or '').strip()
        session_id = str(si.get('Key') or 'f1_latest')

        # ── 2. State detection ───────────────────────────────────────────────
        now_utc = datetime.now(timezone.utc)
        state = 'pre'

        if session_status in _F1LT_LIVE_STATUSES:
            state = 'in'
        elif session_status in ('Finalised', 'Finished'):
            state = 'post'
        else:
            # Fall back to time-window comparison
            try:
                start_utc = _f1lt_to_utc(si['StartDate'], gmt_offset)
                end_utc   = _f1lt_to_utc(si['EndDate'],   gmt_offset)
                if start_utc <= now_utc <= end_utc + timedelta(hours=2):
                    state = 'in'
                elif now_utc > end_utc + timedelta(hours=2):
                    state = 'post'
            except Exception:
                pass

        start_utc_str = ''
        try:
            start_utc_str = _f1lt_to_utc(si['StartDate'], gmt_offset).strftime('%Y-%m-%dT%H:%M:%SZ')
        except Exception:
            pass

        # ── 3. Driver list — SignalR (live) or Jolpica (fallback) ────────────
        drivers = []

        # Always ensure the SignalR client is running so it's ready when a
        # session goes live.
        signalr_client = _f1_signalr.get_client()

        signalr_live_data = None
        if signalr_client and signalr_client.is_connected and state == 'in':
            signalr_live_data = signalr_client.get_live_data()

        if signalr_live_data and signalr_live_data.get('driver_list'):
            drivers = _drivers_from_signalr(signalr_live_data)
            # Override session_status from SignalR if available
            sr_status = signalr_live_data.get('session_status', '')
            if sr_status in _F1LT_LIVE_STATUSES:
                state = 'in'

        if not drivers:
            # Fall back to Jolpica last-race results for driver roster
            try:
                data = self._jolpica_get('current/last/results.json')
                races = data.get('MRData', {}).get('RaceTable', {}).get('Races', [])
                results = races[0].get('Results', []) if races else []
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
                    gap_val = res.get('Time', {}).get('time') or res.get('status', '')
                    gap = 'Leader' if pos == 1 else (f"+{gap_val}" if gap_val and gap_val not in ('Finished', 'Lapped') else '')
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
            except Exception as exc:
                print(f"[F1] Jolpica results fetch error: {exc}")

        # ── 4. Build game object ─────────────────────────────────────────────
        game = {
            'id':           session_id,
            'type':         'racing',
            'sport':        'f1',
            'state':        state,
            'status':       'LIVE' if state == 'in' else ('FINAL' if state == 'post' else 'Starts Soon'),
            'is_shown':     True,
            'startTimeUTC': start_utc_str,
            'away_abbr':    event,
            'home_abbr':    session_name,
            'away_score':   '',
            'home_score':   '',
            'f1': {
                'event_name':    event,
                'short_name':    event,
                'track_name':    track,
                'session_type':  session_name,
                'session_name':  session_name,
                'lap':           0,
                'total_laps':    0,
                'laps_remaining': 0,
                'caution':       False,
                'flag':          _f1_flag_for_state(state),
                'drivers':       drivers,
                'weather':       {},
            },
        }
        self._f1_cache = {'ts': now_ts, 'data': game}
        return game
