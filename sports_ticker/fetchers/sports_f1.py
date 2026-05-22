"""Formula 1 live/latest data fetcher using OpenF1."""

from datetime import datetime, timezone, timedelta

from .. import core as _core
globals().update({k: v for k, v in vars(_core).items() if not k.startswith('__')})

_OPENF1_BASE = "https://api.openf1.org/v1"
_F1_CAR_URL = (
    "https://media.formula1.com/image/upload/c_lfill,h_224/q_auto/"
    "d_common:f1:2026:fallback:car:2026fallbackcarright.webp/"
    "v1740000001/common/f1/2026/{slug}/2026{slug}carright.webp"
)
_F1_TEAM_SLUGS = {
    'mclaren': 'mclaren',
    'mercedes': 'mercedes',
    'ferrari': 'ferrari',
    'red bull': 'red-bull-racing',
    'racing bulls': 'racing-bulls',
    'rb': 'racing-bulls',
    'aston martin': 'aston-martin',
    'alpine': 'alpine',
    'williams': 'williams',
    'haas': 'haas',
    'sauber': 'kick-sauber',
    'kick sauber': 'kick-sauber',
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


def _f1_team_slug(team_name):
    lower = str(team_name or '').strip().lower()
    for key, slug in _F1_TEAM_SLUGS.items():
        if key in lower:
            return slug
    return ''


def _f1_car_url(team_name):
    slug = _f1_team_slug(team_name)
    return _F1_CAR_URL.format(slug=slug) if slug else ''


def _fahrenheit(value):
    try:
        return str(int(round(float(value) * 9 / 5 + 32)))
    except Exception:
        return ''


def _mph_from_ms(value):
    try:
        return str(int(round(float(value) * 2.236936)))
    except Exception:
        return ''


class SportsF1Mixin:
    def __init_f1_cache(self):
        if not hasattr(self, '_f1_cache'):
            self._f1_cache = {'ts': 0.0, 'data': None}
            self._f1_ttl = 30.0

    def _openf1_get(self, endpoint, **params):
        clean = {k: v for k, v in params.items() if v not in (None, '')}
        url = f"{_OPENF1_BASE}/{endpoint.lstrip('/')}"
        r = self.session.get(url, headers=HEADERS, params=clean, timeout=TIMEOUTS.get('default', 10))
        r.raise_for_status()
        data = r.json()
        return data if isinstance(data, list) else []

    def _fetch_f1(self, force=False):
        """Fetch the latest Formula 1 session and return a racing game object."""
        self.__init_f1_cache()
        now_ts = time.time()
        if not force and (now_ts - self._f1_cache.get('ts', 0.0)) < self._f1_ttl:
            return self._f1_cache.get('data')

        try:
            sessions = self._openf1_get('sessions', session_key='latest')
            if not sessions:
                return self._f1_cache.get('data')
            session = sessions[-1]
            session_key = session.get('session_key')
            meeting_key = session.get('meeting_key')
        except Exception as exc:
            log(f"[F1] session fetch error: {exc}")
            return self._f1_cache.get('data')

        try:
            meetings = self._openf1_get('meetings', meeting_key=meeting_key) if meeting_key else []
            meeting = meetings[-1] if meetings else {}
        except Exception:
            meeting = {}

        try:
            drivers_raw = self._openf1_get('drivers', session_key=session_key)
        except Exception:
            drivers_raw = []

        # For position and intervals, limit to the last 10 minutes to avoid
        # downloading the full session history during long live sessions.
        recent_cutoff = (datetime.now(timezone.utc) - timedelta(minutes=10)).strftime('%Y-%m-%dT%H:%M:%S')
        try:
            positions_raw = self._openf1_get('position', **{'session_key': session_key, 'date>': recent_cutoff})
            if not positions_raw:
                positions_raw = self._openf1_get('position', session_key=session_key)
        except Exception:
            positions_raw = []

        try:
            intervals_raw = self._openf1_get('intervals', **{'session_key': session_key, 'date>': recent_cutoff})
            if not intervals_raw:
                intervals_raw = self._openf1_get('intervals', session_key=session_key)
        except Exception:
            intervals_raw = []

        try:
            weather_raw = self._openf1_get('weather', session_key=session_key)
        except Exception:
            weather_raw = []

        try:
            latest_pos = {}
            for item in positions_raw:
                num = item.get('driver_number')
                if num is not None:
                    latest_pos[str(num)] = item

            latest_interval = {}
            for item in intervals_raw:
                num = item.get('driver_number')
                if num is not None:
                    latest_interval[str(num)] = item

            drivers = []
            for drv in drivers_raw:
                num = str(drv.get('driver_number') or '').strip()
                pos_item = latest_pos.get(num, {})
                try:
                    pos = int(pos_item.get('position') or 999)
                except Exception:
                    pos = 999
                int_item = latest_interval.get(num, {})
                team_hex = str(drv.get('team_colour') or '').strip().lstrip('#')
                drivers.append({
                    'pos': pos,
                    'name': str(drv.get('full_name') or drv.get('broadcast_name') or '').title().strip() or 'Driver',
                    'abbr': str(drv.get('name_acronym') or '')[:3].upper(),
                    'car': num,
                    'team': str(drv.get('team_name') or '').strip(),
                    'team_logo': '',
                    'car_illustration': _f1_car_url(drv.get('team_name')),
                    'livery_primary': f"#{team_hex}" if len(team_hex) == 6 else '#888888',
                    'livery_secondary': '#111111',
                    'gap': _f1_compact_gap(int_item.get('gap_to_leader'), pos),
                    'speed': '',
                    'status': 'Active',
                    'on_track': True,
                })

            drivers.sort(key=lambda d: d['pos'])

            now_utc = datetime.now(timezone.utc)
            state = 'pre'
            try:
                start = datetime.fromisoformat(str(session.get('date_start')).replace('Z', '+00:00'))
                date_end_raw = session.get('date_end')
                if date_end_raw:
                    end = datetime.fromisoformat(str(date_end_raw).replace('Z', '+00:00'))
                    # Add a 2-hour buffer so sessions running overtime still show as LIVE.
                    if start <= now_utc <= end + timedelta(hours=2):
                        state = 'in'
                    elif now_utc > end + timedelta(hours=2):
                        state = 'post'
                else:
                    # No scheduled end — treat as live for up to 5 hours after start.
                    if start <= now_utc <= start + timedelta(hours=5):
                        state = 'in'
                    elif now_utc > start + timedelta(hours=5):
                        state = 'post'
            except Exception:
                pass

            weather = {}
            if weather_raw:
                wx = weather_raw[-1]
                weather = {
                    'air_temp': _fahrenheit(wx.get('air_temperature')),
                    'track_temp': _fahrenheit(wx.get('track_temperature')),
                    'wind_mph': _mph_from_ms(wx.get('wind_speed')),
                    'wind_dir': str(int(round(float(wx.get('wind_direction'))))) if wx.get('wind_direction') is not None else '',
                }

            event = _f1_short_event(meeting.get('meeting_name') or session.get('circuit_short_name'))
            session_name = str(session.get('session_name') or session.get('session_type') or 'Session').strip()
            game = {
                'id': str(session_key or 'f1_latest'),
                'type': 'racing',
                'sport': 'f1',
                'state': state,
                'status': 'LIVE' if state == 'in' else ('FINAL' if state == 'post' else 'Starts Soon'),
                'is_shown': True,
                'startTimeUTC': str(session.get('date_start') or ''),
                'away_abbr': event,
                'home_abbr': session_name,
                'away_score': '',
                'home_score': '',
                'f1': {
                    'event_name': event,
                    'short_name': event,
                    'track_name': str(session.get('circuit_short_name') or ''),
                    'session_type': session_name,
                    'session_name': session_name,
                    'lap': 0,
                    'total_laps': 0,
                    'laps_remaining': 0,
                    'caution': False,
                    'flag': _f1_flag_for_state(state),
                    'drivers': drivers,
                    'weather': weather,
                },
            }
            self._f1_cache = {'ts': now_ts, 'data': game}
            return game
        except Exception as exc:
            log(f"[F1] build error: {exc}")
            return self._f1_cache.get('data')
