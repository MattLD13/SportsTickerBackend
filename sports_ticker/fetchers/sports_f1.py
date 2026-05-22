"""Formula 1 fetcher using F1 Live Timing (livetiming.formula1.com) + Jolpica."""

from datetime import datetime, timezone, timedelta

from .. import core as _core
globals().update({k: v for k, v in vars(_core).items() if not k.startswith('__')})

from . import f1_signalr as _f1_signalr

_F1LT_BASE    = "https://livetiming.formula1.com/static"
_JOLPICA_BASE = "https://api.jolpi.ca/ergast/f1"

# F1 live timing CDN requires the BestHTTP UA used by their official apps.
_F1LT_HEADERS = {
    'User-Agent':      'BestHTTP',
    'Accept':          '*/*',
    'Accept-Encoding': 'gzip, identity',
    'Referer':         'https://www.formula1.com/',
    'Origin':          'https://www.formula1.com',
}

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

# TrackStatus.Status codes from the F1 live timing feed
_F1LT_TRACK_STATUS = {
    '1': 'GREEN',
    '2': 'YELLOW',
    '4': 'SAFETY CAR',
    '5': 'RED FLAG',
    '6': 'VSC',
    '7': 'VSC ENDING',
}


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
        r = self.session.get(url, headers=_F1LT_HEADERS, timeout=TIMEOUTS.get('default', 10))
        r.raise_for_status()
        return r.json()

    def _jolpica_get(self, path):
        """GET a JSON resource from the Jolpica/Ergast F1 API."""
        url = f"{_JOLPICA_BASE}/{path.lstrip('/')}"
        r = self.session.get(url, headers=HEADERS, timeout=TIMEOUTS.get('default', 10))
        r.raise_for_status()
        return r.json()

    def _fetch_f1(self, force=False):
        """Fetch the current F1 session using F1 Live Timing (SignalR) + Jolpica."""
        self.__init_f1_cache()
        now_ts = time.time()
        if not force and (now_ts - self._f1_cache.get('ts', 0.0)) < self._f1_ttl:
            return self._f1_cache.get('data')

        # ── 0. Ensure SignalR client is running ──────────────────────────────
        signalr_client = _f1_signalr.get_client()
        signalr_data   = signalr_client.get_live_data() if signalr_client else {}

        # ── 1. Session info: static CDN first, SignalR fallback ──────────────
        si = None
        try:
            si = self._f1lt_get('SessionInfo.json')
        except Exception as exc:
            print(f"[F1] SessionInfo CDN error ({exc}); using SignalR session info")
            # Build a synthetic si from SignalR SessionInfo topic data
            sr_si = signalr_data.get('session_info', {})
            if sr_si:
                si = sr_si

        if not si:
            return self._f1_cache.get('data')

        session_status = str(si.get('SessionStatus', '')).strip()
        session_name   = str(si.get('Name') or si.get('Type') or 'Session').strip()
        session_type   = str(si.get('Type') or session_name).strip()
        gmt_offset     = str(si.get('GmtOffset', '+00:00:00'))
        meeting        = si.get('Meeting', {}) if isinstance(si.get('Meeting'), dict) else {}
        circuit        = meeting.get('Circuit', {}) if isinstance(meeting.get('Circuit'), dict) else {}

        event = _f1_short_event(meeting.get('OfficialName') or meeting.get('Name') or circuit.get('ShortName'))
        track = str(circuit.get('ShortName') or meeting.get('Location') or '').strip()
        session_id = str(si.get('Key') or 'f1_latest')

        # ── 2. State detection ───────────────────────────────────────────────
        now_utc = datetime.now(timezone.utc)
        state = 'pre'

        # SignalR session_status is authoritative when connected
        sr_session_status = signalr_data.get('session_status', '')
        effective_status  = sr_session_status if sr_session_status else session_status

        if effective_status in _F1LT_LIVE_STATUSES:
            state = 'in'
        elif effective_status in ('Finalised', 'Finished'):
            state = 'post'
        else:
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
        live_signalr = signalr_data if (signalr_client and signalr_client.is_connected and state == 'in') else {}

        if live_signalr and live_signalr.get('driver_list'):
            drivers = _drivers_from_signalr(live_signalr)

        if not drivers:
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
                    code    = str(drv.get('code') or '').upper()[:3]
                    name    = f"{drv.get('givenName', '')} {drv.get('familyName', '')}".strip().title()
                    car     = str(drv.get('permanentNumber') or res.get('number') or '').strip()
                    gap_val = res.get('Time', {}).get('time') or res.get('status', '')
                    gap     = 'Leader' if pos == 1 else (f"+{gap_val}" if gap_val and gap_val not in ('Finished', 'Lapped') else '')
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

        # ── 4. Status display ────────────────────────────────────────────────
        session_lower = session_type.lower()
        is_practice   = any(x in session_lower for x in ('practice', 'warm up'))

        if state == 'post':
            status_display = 'FINAL'
        elif state == 'in':
            ts_code    = str(live_signalr.get('track_status', {}).get('Status', '1')).strip()
            lap_count  = live_signalr.get('lap_count', {})
            extrap     = live_signalr.get('extrapolated_clock', {})
            cur_lap    = lap_count.get('CurrentLap')
            tot_lap    = lap_count.get('TotalLaps')
            remaining  = str(extrap.get('Remaining') or '').split('.')[0]  # strip sub-seconds

            if is_practice:
                status_display = _F1LT_TRACK_STATUS.get(ts_code, 'GREEN')
            else:
                # Race / Qualifying: prefer laps, then time remaining, then flag
                if cur_lap and tot_lap:
                    status_display = f"Lap {cur_lap}/{tot_lap}"
                elif remaining and remaining not in ('', '0:00:00'):
                    status_display = remaining
                else:
                    status_display = _F1LT_TRACK_STATUS.get(ts_code, 'GREEN')
        else:
            # Pre: show scheduled start time
            if start_utc_str:
                try:
                    start_dt = parse_iso(start_utc_str)
                    if start_dt:
                        status_display = start_dt.strftime('%I:%M %p').lstrip('0')
                    else:
                        status_display = 'Starts Soon'
                except Exception:
                    status_display = 'Starts Soon'
            else:
                status_display = 'Starts Soon'

        flag = _F1LT_TRACK_STATUS.get(
            str(live_signalr.get('track_status', {}).get('Status', '1')).strip(),
            _f1_flag_for_state(state)
        )

        # Lap info for racing sessions
        lap_count_d = live_signalr.get('lap_count', {})
        cur_lap_val = int(lap_count_d.get('CurrentLap') or 0)
        tot_lap_val = int(lap_count_d.get('TotalLaps') or 0)

        # ── 5. Build game object ─────────────────────────────────────────────
        game = {
            'id':           session_id,
            'type':         'racing',
            'sport':        'f1',
            'state':        state,
            'status':       status_display,
            'is_shown':     True,
            'startTimeUTC': start_utc_str,
            'away_abbr':    event,
            'home_abbr':    session_name,
            'away_score':   '',
            'home_score':   '',
            'f1': {
                'event_name':     event,
                'short_name':     event,
                'track_name':     track,
                'session_type':   session_name,
                'session_name':   session_name,
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
