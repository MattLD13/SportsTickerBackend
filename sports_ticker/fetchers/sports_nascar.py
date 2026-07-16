"""NASCAR live data fetcher using cf.nascar.com public feeds."""

import os
import re
from datetime import date, datetime as _dt_cls, timedelta, timezone as _tz

from .. import core as _core
globals().update({k: v for k, v in vars(_core).items() if not k.startswith('__')})

_NASCAR_LIVE_URL = "https://cf.nascar.com/cacher/live/live-feed.json"
_NASCAR_HEADERS  = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}

# If NASCAR_BADGE_HOST is set (e.g. "https://ticker.mattdicks.org/api/nascar/badge"),
# badge URLs in the game JSON point to the server proxy instead of cf.nascar.com.
# The server pre-resizes badges to 32×32 and caches them, saving the Pi the work.
# Leave unset to have the Pi fetch directly from cf.nascar.com (fine for carbadges).
_NASCAR_BADGE_HOST = os.environ.get(
    'NASCAR_BADGE_HOST',
    'https://cf.nascar.com/data/images/carbadges/1',
)

# Official season schedule (all series, with per-session start times) — same
# cf.nascar.com host as the live feed above.
_NASCAR_SCHEDULE_URL  = "https://cf.nascar.com/cacher/{year}/race_list_basic.json"
_NASCAR_SCHEDULE_TTL  = 3600.0

# run_type codes in the schedule feed's per-race "schedule" array
_RUN_TYPE_PRACTICE   = 1
_RUN_TYPE_QUALIFYING = 2
_RUN_TYPE_RACE       = 3
_NASCAR_SESSION_DURATION_MIN = {
    _RUN_TYPE_PRACTICE:   60,
    _RUN_TYPE_QUALIFYING: 60,
    _RUN_TYPE_RACE:       220,
}

# Track name → NASCAR.com media slug. Stable across years (a venue's slug
# only changes if NASCAR renames/replaces it), unlike the schedule itself —
# only needs an entry here for venues the generic stripping rule can't handle.
_NASCAR_TRACK_SLUG_OVERRIDES = {
    'circuit of the americas':  'Cota',
    'san diego street course':  'Sandiego',
}
_NASCAR_TRACK_SLUG_STRIP_WORDS = {
    'motor', 'speedway', 'raceway', 'international', 'superspeedway', 'stadium', 'fairgrounds',
}


def _nascar_track_slug(track_name):
    """Derive NASCAR.com's car-image slug from a track name, e.g.
    'Las Vegas Motor Speedway' -> 'Lasvegas', 'Bowman Gray Stadium' -> 'Bowmangray'.
    """
    key = str(track_name or '').strip().lower()
    if key in _NASCAR_TRACK_SLUG_OVERRIDES:
        return _NASCAR_TRACK_SLUG_OVERRIDES[key]
    words = re.findall(r"[A-Za-z']+", track_name or '')
    kept = [w for w in words if w.lower() not in _NASCAR_TRACK_SLUG_STRIP_WORDS]
    slug = ''.join(kept)
    return slug.capitalize() if slug else ''


def _nascar_build_image_lookup(payload):
    """Map race_id -> (race_num, track_slug, race_date_iso) for Cup Series
    races, derived entirely from the official schedule so this never needs a
    manual per-season update. race_num is the ordinal position of each race
    that has an actual Race session — qualifying-only races like the Daytona
    Duels aren't separately numbered, matching NASCAR.com's image naming.
    """
    races = []
    for race in (payload or {}).get(f'series_{_NASCAR_CUP_SERIES_ID}', []) or []:
        if not isinstance(race, dict):
            continue
        race_id    = int(race.get('race_id') or 0)
        track_name = str(race.get('track_name') or '').strip()
        race_date  = None
        for s in race.get('schedule', []) or []:
            if int(s.get('run_type') or 0) == _RUN_TYPE_RACE:
                raw = str(s.get('start_time_utc') or '').strip()
                if raw:
                    try:
                        race_date = _dt_cls.fromisoformat(raw).date()
                    except Exception:
                        pass
                break
        if race_id and race_date:
            races.append((race_id, track_name, race_date))
    races.sort(key=lambda x: x[2])
    return {
        race_id: (i + 1, _nascar_track_slug(track_name), race_date.isoformat())
        for i, (race_id, track_name, race_date) in enumerate(races)
    }


# race_id -> (race_num, track_slug, race_date_iso); refreshed each time the
# season schedule is fetched, so it tracks the current year automatically.
_NASCAR_IMAGE_LOOKUP = {}

_NASCAR_IMG_BASE = "https://www.nascar.com/wp-content/uploads/sites/7"


def _nascar_car_image_url(race_id, car_number):
    entry = _NASCAR_IMAGE_LOOKUP.get(int(race_id or 0))
    if not entry:
        return ''
    race_num, track_slug, race_date_iso = entry
    try:
        race_day = date.fromisoformat(race_date_iso)
    except Exception:
        return ''
    # NASCAR uploads images 4-7 days before race day; use 5 as the default.
    # The downloader will try adjacent offsets if the primary URL 404s.
    upload_day = race_day - timedelta(days=5)
    yy  = str(race_day.year)[-2:]
    mon = f"{upload_day.month:02d}"
    day = f"{upload_day.day:02d}"
    car = str(car_number).strip()
    return (
        f"{_NASCAR_IMG_BASE}/{race_day.year}/{mon}/{day}/"
        f"{yy}_NCS_{race_num}{track_slug}_{car}-922x400.jpg"
    )


def _nascar_car_image_candidates(race_id, car_number):
    """Return candidate URLs trying upload offsets around the expected upload day."""
    entry = _NASCAR_IMAGE_LOOKUP.get(int(race_id or 0))
    if not entry:
        return []
    race_num, track_slug, race_date_iso = entry
    try:
        race_day = date.fromisoformat(race_date_iso)
    except Exception:
        return []
    yy  = str(race_day.year)[-2:]
    car = str(car_number).strip()
    urls = []
    for offset in (5, 4, 6, 3, 7, 2, 8, 1, 9, 0, 10):
        d = race_day - timedelta(days=offset)
        urls.append(
            f"{_NASCAR_IMG_BASE}/{race_day.year}/{d.month:02d}/{d.day:02d}/"
            f"{yy}_NCS_{race_num}{track_slug}_{car}-922x400.jpg"
        )
    return urls

# Flag state codes from NASCAR feed
_FLAG_MAP = {
    1: 'GREEN',
    2: 'YELLOW',   # caution
    3: 'RED',
    4: 'CHECKERED',
    8: 'GREEN',    # pace lap / pre-race
    9: 'CHECKERED',  # race complete
}

# Official manufacturer brand colors
_MAKE_COLOR = {
    'tyt': '#CC0000',   # Toyota red
    'chv': '#F5A623',   # Chevrolet gold
    'frd': '#003EAC',   # Ford blue
}

# Series id → label
_SERIES_LABEL = {
    1: 'Cup Series',
    2: 'Xfinity',
    3: 'Trucks',
}

# run_type → display session name (title's secondary line)
_RUN_TYPE_SESSION_NAME = {
    _RUN_TYPE_PRACTICE:   'Practice',
    _RUN_TYPE_QUALIFYING: 'Qualifying',
    _RUN_TYPE_RACE:       'Race',
}


def _nascar_short_race_name(race_name):
    """Strip secondary sponsor clauses from a NASCAR race name for display."""
    name = str(race_name or '').strip()
    name = re.split(r'\s+(?:presented by|powered by|sponsored by)\b', name, flags=re.IGNORECASE)[0]
    return name.strip()


def _nascar_compact_gap(delta, pos):
    if pos == 1:
        return 'Leader'
    try:
        s = float(delta)
        if s == 0:
            return ''
        if s < 0:
            # Negative delta = laps down (e.g. -1.0 → "-1L")
            laps = int(abs(s))
            return f"-{laps}L" if laps > 0 else ''
        return f"+{s:.3f}s"
    except Exception:
        return ''


def _nascar_flag(flag_state, laps_to_go):
    if laps_to_go == 0:
        return 'CHECKERED'
    return _FLAG_MAP.get(int(flag_state or 0), 'GREEN')


def _nascar_make_color(manufacturer):
    return _MAKE_COLOR.get(str(manufacturer or '').lower().strip(), '#888888')


_NASCAR_CUP_SERIES_ID = 1   # only Cup Series is shown on the ticker — no Xfinity/Trucks


def _nascar_flatten_schedule(payload):
    """Flatten the {'series_1': [...], 'series_2': [...], 'series_3': [...]} schedule
    payload into a chronological list of Cup Series session tuples:
    (race_id, series_id, race_name, track_name, run_type, event_name, start_utc).
    """
    sessions = []
    for key, races in (payload or {}).items():
        try:
            series_id = int(str(key).rsplit('_', 1)[-1])
        except Exception:
            continue
        if series_id != _NASCAR_CUP_SERIES_ID:
            continue
        for race in races or []:
            if not isinstance(race, dict):
                continue
            race_id    = int(race.get('race_id') or 0)
            race_name  = str(race.get('race_name') or '').strip()
            track_name = str(race.get('track_name') or '').strip()
            for s in race.get('schedule', []) or []:
                run_type = int(s.get('run_type') or 0)
                if run_type not in _NASCAR_SESSION_DURATION_MIN:
                    continue
                raw = str(s.get('start_time_utc') or '').strip()
                if not raw:
                    continue
                try:
                    start = _dt_cls.fromisoformat(raw).replace(tzinfo=_tz.utc)
                except Exception:
                    continue
                event_name = str(s.get('event_name') or '').strip()
                sessions.append((race_id, series_id, race_name, track_name, run_type, event_name, start))
    sessions.sort(key=lambda x: x[6])
    return sessions


def _nascar_find_schedule_session(sessions, now_utc):
    """Return the most relevant session — currently live, recently finished
    (within 12h), or else the next upcoming one — as (race_id, series_id,
    race_name, track_name, run_type, event_name, start_utc, end_utc, state).
    Like other sports on this ticker, the next scheduled session is always
    shown (with a real countdown) regardless of how far away it is.
    """
    best_post = None
    next_pre = None
    for race_id, series_id, race_name, track_name, run_type, event_name, start in sessions:
        end = start + timedelta(minutes=_NASCAR_SESSION_DURATION_MIN[run_type])
        if start <= now_utc <= end:
            return (race_id, series_id, race_name, track_name, run_type, event_name, start, end, 'in')
        if end < now_utc and (now_utc - end).total_seconds() < 12 * 3600:
            best_post = (race_id, series_id, race_name, track_name, run_type, event_name, start, end, 'post')
        elif start > now_utc and next_pre is None:
            next_pre = (race_id, series_id, race_name, track_name, run_type, event_name, start, end, 'pre')
    return best_post or next_pre


def _nascar_abbr(full_name):
    # Strip rookie "#" suffix and any non-alpha trailing tokens from the NASCAR feed
    name = re.sub(r'\s*#\w*\s*$', '', str(full_name or '').strip()).strip()
    parts = name.split()
    if len(parts) >= 2:
        return parts[-1][:3].upper()   # first 3 of last name: HAMlin, BRIscoe, etc.
    return name[:3].upper()


class SportsNascarMixin:
    def __init_nascar_cache(self):
        if not hasattr(self, '_nascar_cache'):
            self._nascar_cache = {'ts': 0.0, 'data': None}
            self._nascar_ttl = 30.0
            self._nascar_schedule_cache = {'ts': 0.0, 'data': []}

    def _fetch_nascar_schedule(self, force=False):
        """Fetch the official season schedule (all series, with per-session start
        times) from cf.nascar.com, flattened and cached for an hour."""
        self.__init_nascar_cache()
        now = time.time()
        cache = self._nascar_schedule_cache
        if not force and (now - cache['ts']) < _NASCAR_SCHEDULE_TTL and cache['data']:
            return cache['data']
        try:
            year = _dt_cls.now(_tz.utc).year
            r = self.session.get(
                _NASCAR_SCHEDULE_URL.format(year=year),
                headers=_NASCAR_HEADERS,
                timeout=10,
            )
            r.raise_for_status()
            payload = r.json()
            sessions = _nascar_flatten_schedule(payload)
            _NASCAR_IMAGE_LOOKUP.update(_nascar_build_image_lookup(payload))
            self._nascar_schedule_cache = {'ts': now, 'data': sessions}
            return sessions
        except Exception as exc:
            print(f"[NASCAR] schedule fetch error: {exc}")
            return cache.get('data', [])

    def _fetch_nascar(self, force=False):
        """Fetch the live NASCAR feed and return a racing game object.

        The official schedule decides *which* session is current (live, just
        finished, or next up); the live feed supplies rich telemetry when it's
        actually reporting on that same session. This keeps a real, accurate
        card showing throughout race week instead of only once the live feed
        catches up.
        """
        self.__init_nascar_cache()
        now_ts = time.time()
        if not force and (now_ts - self._nascar_cache.get('ts', 0.0)) < self._nascar_ttl:
            return self._nascar_cache.get('data')

        sched_sessions = self._fetch_nascar_schedule()
        sched_match = _nascar_find_schedule_session(sched_sessions, _dt_cls.now(_tz.utc)) if sched_sessions else None

        try:
            r = self.session.get(_NASCAR_LIVE_URL, headers=_NASCAR_HEADERS, timeout=10)
            r.raise_for_status()
            feed = r.json()
        except Exception as exc:
            print(f"[NASCAR] fetch error: {exc}")
            feed = {}

        try:
            lap          = int(feed.get('lap_number') or 0)
            total_laps   = int(feed.get('laps_in_race') or 0)
            laps_to_go   = int(feed.get('laps_to_go') or 0)
            flag_state   = int(feed.get('flag_state') or 0)
            track_name   = str(feed.get('track_name') or 'NASCAR').strip()
            run_name     = str(feed.get('run_name') or 'NASCAR Race').strip()
            series_id    = int(feed.get('series_id') or 1)
            race_id      = int(feed.get('race_id') or 0)
            cautions     = int(feed.get('number_of_caution_laps') or 0)

            feed_state = None
            if feed:
                if laps_to_go == 0 and total_laps > 0:
                    feed_state = 'post'
                elif lap > 0:
                    feed_state = 'in'
                else:
                    feed_state = 'pre'

            start_time_utc_str = ''
            race_name = ''
            session_name = ''
            feed_matches_schedule = bool(sched_match) and sched_match[0] == race_id

            if sched_match and feed_matches_schedule and feed_state == sched_match[8]:
                # Live feed is reporting on the same session the schedule says is
                # current — trust its telemetry as-is.
                state = feed_state
                _, _, race_name, _, s_run_type, _, s_start, _, _ = sched_match
                start_time_utc_str = s_start.strftime('%Y-%m-%dT%H:%M:%SZ')
                session_name = _RUN_TYPE_SESSION_NAME.get(s_run_type, '')
            elif sched_match:
                # Schedule decides which session is current; only keep the feed's
                # telemetry when it's actually tracking that same session.
                s_race_id, s_series_id, s_race_name, s_track_name, s_run_type, _s_event_name, s_start, _s_end, s_state = sched_match
                state = s_state
                race_name = s_race_name
                session_name = _RUN_TYPE_SESSION_NAME.get(s_run_type, '')
                start_time_utc_str = s_start.strftime('%Y-%m-%dT%H:%M:%SZ')
                if not feed_matches_schedule:
                    race_id    = s_race_id
                    series_id  = s_series_id
                    track_name = s_track_name or track_name
                    lap = total_laps = laps_to_go = 0
                    flag_state = 0
                    cautions   = 0
                    feed = {}   # telemetry belongs to a different session
            elif feed_state:
                state = feed_state
            else:
                # No schedule and no usable live feed — nothing to show.
                self._nascar_cache = {'ts': now_ts, 'data': None}
                return None

            series_label = _SERIES_LABEL.get(series_id, 'NASCAR')
            if feed:
                flag    = _nascar_flag(flag_state, laps_to_go)
                caution = flag_state == 2
            else:
                # Schedule-only card (no matching telemetry) — flag reflects state alone.
                flag    = 'CHECKERED' if state == 'post' else ('GREEN' if state == 'in' else 'WHITE')
                caution = False

            vehicles = sorted(
                [v for v in feed.get('vehicles', []) if isinstance(v, dict)],
                key=lambda v: int(v.get('running_position') or 999),
            )

            drivers = []
            for v in vehicles:
                pos      = int(v.get('running_position') or 999)
                car_num  = str(v.get('vehicle_number') or '').strip()
                make     = str(v.get('vehicle_manufacturer') or '').strip()
                drv_info = v.get('driver') or {}
                full_name = re.sub(r'\s*#\w*\s*$', '', str(drv_info.get('full_name') or '').strip()).strip()
                delta    = v.get('delta', 0.0)
                on_track = bool(v.get('is_on_track', True))
                sponsor  = str(v.get('sponsor_name') or '').strip()

                drivers.append({
                    'pos': pos,
                    'name': full_name or f"#{car_num}",
                    'abbr': _nascar_abbr(full_name),
                    'car': car_num,
                    'team': sponsor,
                    'team_logo': f"{_NASCAR_BADGE_HOST}/{car_num}.png" if car_num else '',
                    'car_illustration': _nascar_car_image_url(race_id, car_num),
                    'livery_primary': _nascar_make_color(make),
                    'livery_secondary': '#111111',
                    'gap': _nascar_compact_gap(delta, pos),
                    'speed': '',
                    'status': 'Active' if on_track else 'Out',
                    'on_track': on_track,
                    'make': make,
                })

            if race_name:
                # Race name from the official schedule — the card's title.
                short_name = _nascar_short_race_name(race_name)
            else:
                # No schedule match (e.g. schedule fetch failed) — fall back to
                # deriving a display name from the live feed's run_name.
                short_name = run_name
                for drop in ('NASCAR CUP SERIES ', 'NASCAR XFINITY SERIES ', 'NASCAR CRAFTSMAN TRUCK SERIES '):
                    short_name = short_name.replace(drop, '').replace(drop.title(), '')
                for suffix in (' - Final Segment', ' - FINAL SEGMENT', ' - Final', ' - FINAL'):
                    if short_name.endswith(suffix):
                        short_name = short_name[:-len(suffix)].strip()
                        break
                short_name = short_name.strip()

            # session_label e.g. "Practice", "Qualifying", "Race" — the card's subtitle.
            session_label_short = session_name or {1: 'Race', 2: 'Xfinity', 3: 'Trucks'}.get(series_id, series_label)

            if state == 'in':
                status_display = 'LIVE'
            elif state == 'post':
                status_display = 'FINAL'
            elif start_time_utc_str:
                try:
                    utc_off = _core.state.get('utc_offset', -5)
                    local_tz = _tz(timedelta(hours=utc_off))
                    start_dt = _dt_cls.fromisoformat(start_time_utc_str.rstrip('Z')).replace(tzinfo=_tz.utc)
                    status_display = 'Starts ' + start_dt.astimezone(local_tz).strftime('%I:%M %p').lstrip('0')
                except Exception:
                    status_display = 'Starts Soon'
            else:
                status_display = 'Starts Soon'

            game = {
                'id': f"nascar_{race_id or 'live'}",
                'type': 'racing',
                'sport': 'nascar',
                'state': state,
                'status': status_display,
                'is_shown': True,
                'startTimeUTC': start_time_utc_str,
                'away_abbr': short_name,
                'home_abbr': session_label_short,
                'away_score': '',
                'home_score': '',
                'nascar': {
                    'race_id': race_id,
                    'event_name': short_name,
                    'short_name': short_name,
                    'track_name': track_name,
                    'session_type': session_label_short,
                    'session_name': session_label_short,
                    'lap': lap,
                    'total_laps': total_laps,
                    'laps_remaining': laps_to_go,
                    'caution': caution,
                    'caution_laps': cautions,
                    'flag': flag,
                    'drivers': drivers,
                    'weather': {},
                },
            }
            self._nascar_cache = {'ts': now_ts, 'data': game}
            return game

        except Exception as exc:
            print(f"[NASCAR] fetch error: {exc}")
            return self._nascar_cache.get('data')
