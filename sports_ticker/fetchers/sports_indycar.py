"""IndyCar live data fetcher using IndyCar's official Azure Blob Storage API.

Endpoints discovered by reverse-engineering leaderboard.indycar.com:
  timingscoring-ris.json  — live timing/scoring for current session
  driversfeed.json        — static driver roster (headshots, livery images, car numbers)
  tsconfig.json           — session config flags
"""

import re
from datetime import datetime, timezone, timedelta

from .. import core as _core
globals().update({k: v for k, v in vars(_core).items() if not k.startswith('__')})
from .racing_flags import LIVE_FLAGS, CAUTION_FLAGS, normalize_flag

_BLOB_BASE            = "https://indycar.blob.core.windows.net/racecontrol"
_IC_POST_SINCE_FILE   = "indycar_post_since.json"
_IC_EXPIRED_IDS_FILE  = "indycar_expired_events.json"
_IC_LAST_FINAL_FILE   = "indycar_last_final.json"
_IC_POST_GRACE_SECS   = 12 * 3600   # show FINAL for 12 h after race ends, then hide
_IMS_LAT = 39.7950
_IMS_LON = -86.2340

# Race-day times for the whole season come from ESPN (same API the F1 fetcher
# uses, year resolved at request time). IndyCar publishes no API for
# Practice/Qualifying/Warmup times, so those are scraped from indycar.com's
# own schedule pages for the *current* race weekend only — that's the only
# weekend ever actually displayed, so the rest of the season stays race-day-only.
_IC_ESPN_SCOREBOARD     = "http://site.api.espn.com/apis/site/v2/sports/racing/irl/scoreboard"
_IC_SCHEDULE_INDEX_URL  = "https://www.indycar.com/Schedule"
_IC_SCHEDULE_TTL        = 3600.0
_IC_INDEX_TTL           = 6 * 3600.0
_IC_EVENT_DETAIL_TTL    = 1800.0

_IC_SESSION_DURATION_MIN = {
    'Practice 1': 90, 'Practice 2': 90, 'Practice 3': 90, 'Practice': 90,
    'Qualifying': 60, 'Fast 12': 30, 'Fast 6': 20, 'Fast 10': 30,
    'Warmup': 30, 'Race': 180,
}
_IC_DEFAULT_DURATION_MIN = 60

_IC_INDEX_HREF_RE = re.compile(r'href="/Schedule/(\d{4})/([^"]+)"')
_IC_DAY_HEADER_RE = re.compile(r'<h3>[A-Za-z]+, ([A-Za-z]+) (\d{1,2})</h3>')
_IC_ENTRY_RE = re.compile(
    r'<div class="schedule-entry">.*?<div class="schedule-time">([^<]+)</div>'
    r'.*?<div class="schedule-description">([^<]+)</div>',
    re.DOTALL,
)

_IC_RESULTS_BASE  = "https://www.indycar.com/results/ntt-indycar-series"
_IC_RESULTS_TTL   = 300.0   # re-fetch results page every 5 min max

# HTML table parsers for the server-rendered results page
_IC_TR_RE  = re.compile(r'<tr\b[^>]*>(.*?)</tr>', re.DOTALL | re.IGNORECASE)
_IC_TD_RE  = re.compile(r'<td\b[^>]*>(.*?)</td>', re.DOTALL | re.IGNORECASE)
_IC_TAG_RE = re.compile(r'<[^>]+>')


def _ic_strip_html(s):
    return _IC_TAG_RE.sub('', s).replace('&amp;', '&').replace('&#39;', "'").strip()


def _ic_session_to_results_slug(session_name):
    """Map a session name like 'Practice 1' to an indycar.com results URL slug."""
    name = str(session_name or '').lower().strip()
    m = re.search(r'(\d+)', name)
    n = m.group(1) if m else '1'
    if 'practice' in name:
        return f'practice-{n}'
    if 'qualifying' in name or 'qual' in name or 'fast' in name:
        return 'qualifying'
    if 'race' in name:
        return 'race'
    if 'warm' in name:
        return 'warmup'
    return None


def _ic_parse_results_table(html):
    """Parse the first data table from an indycar.com results page.
    Returns list of dicts: pos, car, driver, team, best_time, speed, gap, laps.
    Columns confirmed from live DOM inspection:
      0=Rank  1=Car#  2=Driver  3=Team  4=BestTime  5=Speed(mph)
      6=BestLap  7=GapToLeader  8=Interval  9=TotalLaps
    """
    drivers = []
    for tr_m in _IC_TR_RE.finditer(html):
        tds = [_ic_strip_html(td) for td in _IC_TD_RE.findall(tr_m.group(1))]
        if len(tds) < 8:
            continue
        try:
            pos = int(tds[0])
        except (ValueError, IndexError):
            continue
        gap = tds[7] if len(tds) > 7 else ''
        if gap.startswith('-') or gap == '':
            gap = 'Leader' if pos == 1 else ''
        drivers.append({
            'pos':       pos,
            'car':       tds[1],
            'driver':    tds[2],
            'team':      tds[3],
            'best_time': tds[4],
            'speed':     tds[5],
            'gap':       gap,
            'laps':      tds[9] if len(tds) > 9 else '',
        })
    return drivers


def _ic_parse_espn_schedule(events):
    """Parse the ESPN IndyCar scoreboard's events into
    [(race_name, session_name, start_utc), ...] — race-day times only."""
    sessions = []
    for e in events or []:
        if not isinstance(e, dict):
            continue
        name = str(e.get('shortName') or e.get('name') or '').strip()
        raw  = str(e.get('date') or '').strip()
        if not name or not raw:
            continue
        try:
            start = datetime.fromisoformat(raw.replace('Z', '+00:00'))
            if start.tzinfo is None:
                start = start.replace(tzinfo=timezone.utc)
        except Exception:
            continue
        sessions.append((name, 'Race', start))
    sessions.sort(key=lambda x: x[2])
    return sessions


def _ic_parse_schedule_index(html):
    """Return the season's [(year, slug), ...] in chronological order from
    indycar.com's /Schedule index page's "Full Schedule" section (the page
    repeats the same list a second time further down for mobile, so stop at
    the first repeated slug)."""
    marker = html.find('Full Schedule</h2>')
    if marker == -1:
        return []
    body = html[marker:]
    ordered = []
    seen_slugs = set()
    for year, slug in _IC_INDEX_HREF_RE.findall(body):
        if ordered and ordered[-1] == (year, slug):
            continue   # same event linked twice within its own card
        if slug in seen_slugs:
            break       # page repeats the whole list a second time
        seen_slugs.add(slug)
        ordered.append((year, slug))
    return ordered


def _ic_parse_event_sessions(html, year, race_name):
    """Parse Practice/Qualifying/Warmup/Race times off an indycar.com event
    page into [(race_name, session_name, start_utc), ...]. Times on these
    pages are always shown in US Eastern regardless of the track's actual
    timezone."""
    markers = []
    for m in _IC_DAY_HEADER_RE.finditer(html):
        markers.append((m.start(), 'day', (m.group(1), m.group(2))))
    for m in _IC_ENTRY_RE.finditer(html):
        markers.append((m.start(), 'entry', (m.group(1).strip(), m.group(2).strip())))
    markers.sort(key=lambda x: x[0])

    sessions = []
    cur_day = None
    tz = ZoneInfo('America/New_York')
    for _, kind, val in markers:
        if kind == 'day':
            cur_day = val
            continue
        if not cur_day:
            continue
        time_str, desc = val
        if not desc.startswith('NTT INDYCAR SERIES'):
            continue   # support-series or ancillary entry, not on-track IndyCar time
        session_name = desc.split(' - ', 1)[-1].strip()
        time_str = time_str.replace(' ET', '').strip()
        month_str, day_str = cur_day
        try:
            local_dt = datetime.strptime(f"{month_str} {day_str} {year} {time_str}", '%b %d %Y %I:%M%p')
            local_dt = local_dt.replace(tzinfo=tz)
        except Exception:
            continue
        sessions.append((race_name, session_name, local_dt.astimezone(timezone.utc)))
    return sessions


def _ic_find_schedule_session(sessions, now_utc):
    """Return the most relevant session — live, recently finished, or next up
    — as (race_name, session_name, start_utc, end_utc, state), like other
    sports on this ticker the next scheduled session is always shown
    regardless of how far off it is.
    """
    best_post = None
    next_pre = None
    for race_name, session_name, start in sessions:
        duration = _IC_SESSION_DURATION_MIN.get(session_name, _IC_DEFAULT_DURATION_MIN)
        end = start + timedelta(minutes=duration)
        if start <= now_utc <= end:
            return (race_name, session_name, start, end, 'in')
        if end < now_utc and (now_utc - end).total_seconds() < 12 * 3600:
            best_post = (race_name, session_name, start, end, 'post')
        elif start > now_utc and next_pre is None:
            next_pre = (race_name, session_name, start, end, 'pre')
    return best_post or next_pre

_SESSION_TYPE_MAP = {
    'Q': 'Qualifying',
    'P': 'Practice',
    'R': 'Race',
    'W': 'Warm Up',
    'F': 'Qualifying',   # Fast Friday / final qualifying runs
}

_LIVE_FLAGS = LIVE_FLAGS  # imported from racing_flags

# Team livery colors keyed by lowercased team name fragments
_INDYCAR_LIVERIES = {
    'chip ganassi':  ('#E31937', '#002D62'),
    'ganassi':       ('#E31937', '#002D62'),
    'andretti':      ('#112A5A', '#FFFFFF'),
    'penske':        ('#00327A', '#FFD700'),
    'arrow mclaren': ('#FF8000', '#000000'),
    'mclaren':       ('#FF8000', '#000000'),
    'rahal':         ('#7B0D1E', '#C5A028'),
    'coyne':         ('#0033A0', '#FFFFFF'),
    'dale coyne':    ('#0033A0', '#FFFFFF'),
    'juncos':        ('#141414', '#FF0000'),
    'meyer shank':   ('#1E3A5F', '#C5A028'),
    'shank':         ('#1E3A5F', '#C5A028'),
    'foyt':          ('#003087', '#FFD700'),
    'aj foyt':       ('#003087', '#FFD700'),
    'dreyer':        ('#E31837', '#FFFFFF'),
    'prema':         ('#E31837', '#FFFFFF'),
    'carpenter':     ('#012169', '#FFFFFF'),
    'ed carpenter':  ('#012169', '#FFFFFF'),
    'abel':          ('#CC0000', '#FFFFFF'),
    'cusick':        ('#006400', '#FFFFFF'),
    'msp':           ('#FF6600', '#FFFFFF'),
}

def _team_livery(team_name):
    lower = str(team_name or '').lower()
    for key, colors in _INDYCAR_LIVERIES.items():
        if key in lower:
            return colors
    return ('#888888', '#333333')

def _build_abbr(first, last):
    """Build a 3-letter driver abbreviation from first/last name."""
    last = str(last or '').strip()
    first = str(first or '').strip()
    clean_last = ''.join(ch for ch in last if ch.isalnum())
    clean_first = ''.join(ch for ch in first if ch.isalnum())
    if len(clean_last) >= 3:
        return clean_last[:3].upper()
    if clean_last and clean_first:
        return (clean_last + clean_first)[:3].upper()
    if last:
        return last[:3].upper()
    if first:
        return clean_first[:3].upper() if clean_first else first[:3].upper()
    return '???'


def _simplify_indycar_event_name(event_name, track_name):
    value = str(event_name or track_name or 'IndyCar').strip()
    lowered = value.lower()
    if 'indy 500' in lowered or 'indianapolis 500' in lowered:
        return 'Indy 500'
    if 'fast 12' in lowered:
        return 'Fast 12'
    if 'fast 6' in lowered:
        return 'Fast 6'
    if 'fast 10' in lowered:
        return 'Fast 10'

    # IndyCar race names are almost always "<title sponsor> Grand Prix of/at
    # <location>[ presented by <sponsor>]" — drop the sponsor on both sides
    # and keep just the location, regardless of which sponsor is attached
    # this year (e.g. "XPEL Grand Prix at Road America" -> "Road America").
    m = re.search(r'grand\s+prix\s+(?:of|at)\s+(.+)', value, re.IGNORECASE)
    if m:
        location = re.split(r'\s+presented\s+by\b', m.group(1), flags=re.IGNORECASE)[0]
        location = location.strip().rstrip('.,')
        if location:
            return location

    value = value.replace('110th Running of the ', '').replace('Running of the ', '')
    value = re.sub(r'\bGrand Prix\b', 'GP', value, flags=re.IGNORECASE)
    value = re.sub(r'\bChampionship\b', 'Champ', value, flags=re.IGNORECASE)
    value = re.sub(r'\bpresented by\b.*$', '', value, flags=re.IGNORECASE).strip()
    value = ' '.join(value.split())
    return value or 'IndyCar'


def _simplify_indycar_session(session_label, session_name):
    value = str(session_name or session_label or 'Race').strip()
    lowered = value.lower()
    if 'fast 12' in lowered:
        return 'Fast 12'
    if 'fast 6' in lowered:
        return 'Fast 6'
    if 'fast 10' in lowered:
        return 'Fast 10'
    if 'qual' in lowered:
        return 'Qualifying'
    if 'practice' in lowered or lowered == 'p':
        return 'Practice'
    if 'race' in lowered or lowered == 'r':
        return 'Race'
    if 'warm' in lowered:
        return 'Warm Up'
    return value


def _extract_indycar_start_time(hb):
    for key in (
        'startTimeUTC',
        'StartTimeUTC',
        'SessionStartUTC',
        'SessionStartTimeUTC',
        'SessionStartTime',
        'EventStartTimeUTC',
        'EventStartTime',
        'sessionStartUTC',
        'sessionStartTimeUTC',
    ):
        value = str(hb.get(key) or '').strip()
        if value:
            return value
    return ''


class SportsIndycarMixin:

    def __init_indycar_cache(self):
        if not hasattr(self, '_ic_timing_cache'):
            post_since = None
            try:
                with open(_IC_POST_SINCE_FILE) as _f:
                    _v = json.load(_f).get('post_since')
                    if _v:
                        post_since = float(_v)
            except Exception:
                pass

            expired_ids: set = set()
            try:
                with open(_IC_EXPIRED_IDS_FILE) as _f:
                    expired_ids = set(json.load(_f).get('ids', []))
            except Exception:
                pass

            last_final = None
            try:
                with open(_IC_LAST_FINAL_FILE) as _f:
                    last_final = json.load(_f).get('game') or None
            except Exception:
                pass

            self._ic_timing_cache        = {'ts': 0.0, 'data': last_final, 'post_since': post_since}
            self._ic_expired_ids         = expired_ids
            self._ic_drivers_cache       = {'ts': 0.0, 'data': {}}
            self._ic_weather_cache       = {'ts': 0.0, 'data': {}}
            self._ic_schedule_cache      = {'ts': 0.0, 'data': []}
            self._ic_index_cache         = {'ts': 0.0, 'data': []}
            self._ic_event_cache         = {}    # "{year}/{slug}" -> {'ts': ..., 'data': [...]}
            self._ic_results_cache       = {}    # "{year}/{slug}/{session}" -> {'ts': ..., 'data': [...]}
            self._ic_current_event_slug  = ('', '')  # (slug_year, event_slug) for current weekend
            self._ic_timing_ttl          = 8.0
            self._ic_drivers_ttl         = 300.0
            self._ic_weather_ttl         = 300.0

    def _fetch_indycar_schedule(self, force=False):
        """Fetch and cache the season's schedule: race-day times for every
        weekend from ESPN, with full Practice/Qualifying/Warmup/Race times
        for the current weekend scraped from indycar.com layered on top
        (IndyCar publishes no API for session-level times)."""
        self.__init_indycar_cache()
        now = time.time()
        cache = self._ic_schedule_cache
        if not force and (now - cache['ts']) < _IC_SCHEDULE_TTL and cache['data']:
            return cache['data']
        try:
            year = datetime.now(timezone.utc).year
            r = self.session.get(_IC_ESPN_SCOREBOARD, headers=HEADERS,
                                 params={'dates': year},
                                 timeout=TIMEOUTS.get('default', 10))
            r.raise_for_status()
            espn_sessions = _ic_parse_espn_schedule(r.json().get('events', []))
        except Exception as exc:
            print(f"[IndyCar] schedule fetch error: {exc}")
            return cache.get('data', [])

        sessions = list(espn_sessions)
        try:
            weekend = self._ic_fetch_current_weekend_sessions(espn_sessions, now)
            if weekend:
                race_name, weekend_sessions = weekend
                sessions = [s for s in sessions if s[0] != race_name] + weekend_sessions
        except Exception as exc:
            print(f"[IndyCar] weekend session scrape error: {exc}")

        sessions.sort(key=lambda x: x[2])
        self._ic_schedule_cache = {'ts': now, 'data': sessions}
        return sessions

    def _ic_fetch_current_weekend_sessions(self, espn_sessions, now):
        """Scrape indycar.com for the current weekend's per-session times.
        Returns (race_name, [(race_name, session_name, start_utc), ...]) or
        None if there's no relevant weekend or the scrape didn't pan out.
        """
        match = _ic_find_schedule_session(espn_sessions, datetime.now(timezone.utc)) if espn_sessions else None
        if not match:
            return None
        race_name = match[0]
        try:
            idx = next(i for i, (n, _, _) in enumerate(espn_sessions) if n == race_name)
        except StopIteration:
            return None

        idx_cache = self._ic_index_cache
        if (now - idx_cache['ts']) >= _IC_INDEX_TTL or not idx_cache['data']:
            r = self.session.get(_IC_SCHEDULE_INDEX_URL, headers=HEADERS,
                                 timeout=TIMEOUTS.get('default', 10))
            r.raise_for_status()
            idx_cache['data'] = _ic_parse_schedule_index(r.text)
            idx_cache['ts'] = now
        slugs = idx_cache['data']
        if idx >= len(slugs):
            return None
        slug_year, slug = slugs[idx]
        self._ic_current_event_slug = (slug_year, slug)

        cache_key = f"{slug_year}/{slug}"
        entry = self._ic_event_cache.get(cache_key)
        if not entry or (now - entry['ts']) >= _IC_EVENT_DETAIL_TTL:
            r = self.session.get(f"{_IC_SCHEDULE_INDEX_URL}/{slug_year}/{slug}", headers=HEADERS,
                                 timeout=TIMEOUTS.get('default', 10))
            r.raise_for_status()
            weekend_sessions = _ic_parse_event_sessions(r.text, int(slug_year), race_name)
            entry = {'ts': now, 'data': weekend_sessions}
            self._ic_event_cache[cache_key] = entry
        weekend_sessions = entry['data']
        if not weekend_sessions:
            return None
        return race_name, weekend_sessions

    def _build_indycar_schedule_game(self, now_utc):
        """Build a lightweight game object from the season schedule alone —
        used when IndyCar's live timing blob has nothing to report yet."""
        sessions = self._fetch_indycar_schedule()
        match = _ic_find_schedule_session(sessions, now_utc) if sessions else None
        if not match:
            return None
        race_name, session_name, start_utc, _end_utc, state = match

        short_event_name = _simplify_indycar_event_name(race_name, race_name)
        short_session_name = _simplify_indycar_session(session_name, session_name)
        start_time_utc = start_utc.strftime('%Y-%m-%dT%H:%M:%SZ')

        if state == 'in':
            status_display = 'LIVE'
        elif state == 'post':
            status_display = 'FINAL'
        else:
            try:
                utc_off = _core.state.get('utc_offset', -5)
                local_tz = timezone(timedelta(hours=utc_off))
                status_display = 'Starts ' + start_utc.astimezone(local_tz).strftime('%I:%M %p').lstrip('0')
            except Exception:
                status_display = 'Starts Soon'

        # For finished sessions, try to scrape the results from indycar.com
        drivers = []
        if state == 'post':
            slug_year, event_slug = self._ic_current_event_slug
            if slug_year and event_slug:
                session_slug = _ic_session_to_results_slug(session_name)
                if session_slug:
                    try:
                        raw = self._fetch_indycar_results(slug_year, event_slug, session_slug)
                        if raw:
                            drivers = self._build_drivers_from_results(raw)
                    except Exception as exc:
                        print(f"[IndyCar] results enrichment error: {exc}")

        return {
            'id':           f"indycar_sched_{start_utc.strftime('%Y%m%dT%H%M')}",
            'type':         'racing',
            'sport':        'indycar',
            'state':        state,
            'status':       status_display,
            'is_shown':     True,
            'startTimeUTC': start_time_utc,
            'away_abbr':    short_event_name,
            'home_abbr':    short_session_name,
            'away_score':   '',
            'home_score':   '',
            'indycar': {
                'event_name':   short_event_name,
                'short_name':   short_event_name,
                'track_name':   '',
                'session_type': short_session_name,
                'session_name': short_session_name,
                'lap':          0,
                'total_laps':   0,
                'laps_remaining': 0,
                'time_to_go':   '',
                'caution':      False,
                'flag':         'GREEN',
                'drivers':      drivers,
            },
        }

    def _ic_save_post_since(self, value):
        try:
            save_json_atomically(_IC_POST_SINCE_FILE, {'post_since': value} if value else {})
        except Exception as exc:
            print(f"[IndyCar] Could not save post_since: {exc}")

    def _ic_save_last_final(self, game):
        try:
            save_json_atomically(_IC_LAST_FINAL_FILE, {'game': game} if game else {})
        except Exception as exc:
            print(f"[IndyCar] Could not save last_final: {exc}")

    def _ic_expire_event(self, event_id: str):
        """Mark event_id as permanently expired and clear the post_since timer."""
        if event_id and event_id != 'indycar_live':
            self._ic_expired_ids.add(event_id)
            try:
                save_json_atomically(_IC_EXPIRED_IDS_FILE, {'ids': list(self._ic_expired_ids)[-100:]})
            except Exception as exc:
                print(f"[IndyCar] Could not save expired IDs: {exc}")
        self._ic_timing_cache['post_since'] = None
        self._ic_save_post_since(None)
        self._ic_save_last_final(None)

    def _fetch_indycar_results(self, slug_year, event_slug, session_slug, force=False):
        """Fetch post-session standings from the indycar.com server-rendered results page."""
        self.__init_indycar_cache()
        cache_key = f"{slug_year}/{event_slug}/{session_slug}"
        entry = self._ic_results_cache.get(cache_key)
        now = time.time()
        if not force and entry and (now - entry['ts']) < _IC_RESULTS_TTL:
            return entry['data']
        try:
            url = f"{_IC_RESULTS_BASE}/{slug_year}/{event_slug}/{session_slug}"
            r = self.session.get(url, headers=HEADERS, timeout=TIMEOUTS.get('default', 10))
            r.raise_for_status()
            drivers = _ic_parse_results_table(r.text)
            if drivers:
                self._ic_results_cache[cache_key] = {'ts': now, 'data': drivers}
                return drivers
        except Exception as exc:
            print(f"[IndyCar] results page fetch error ({session_slug}): {exc}")
        return entry['data'] if entry else []

    def _build_drivers_from_results(self, raw_drivers):
        """Convert scraped results-page rows into the standard driver dict format."""
        drivers_index = self._fetch_indycar_drivers()
        drivers = []
        for d in raw_drivers:
            car_num   = str(d.get('car') or '').strip()
            full_name = str(d.get('driver') or '').strip()
            team_name = str(d.get('team') or '').strip()
            parts     = full_name.rsplit(' ', 1)
            first = parts[0] if len(parts) == 2 else ''
            last  = parts[-1]
            abbr  = _build_abbr(first, last)

            drv_feed  = drivers_index.get(car_num, {})
            headshot  = str(drv_feed.get('headshot') or '').strip()
            car_illus = str(drv_feed.get('carillustration') or '').strip()
            endplate  = str(drv_feed.get('endplatesmall') or drv_feed.get('endplatelarge') or '').strip()
            logo_url  = endplate or headshot or ''

            pri_hex, sec_hex = _team_livery(team_name)
            drivers.append({
                'pos':              d['pos'],
                'name':             full_name or 'Unknown',
                'abbr':             abbr,
                'car':              car_num,
                'team':             team_name,
                'team_logo':        logo_url,
                'car_illustration': car_illus,
                'livery_primary':   pri_hex,
                'livery_secondary': sec_hex,
                'gap':              d.get('gap', ''),
                'laps':             d.get('laps', ''),
                'speed':            d.get('speed', ''),
                'best_time':        d.get('best_time', ''),
                'status':           'Active',
                'on_track':         False,
            })
        return drivers

    def _fetch_indycar_drivers(self, force=False):
        """Fetch and cache driversfeed.json indexed by car number."""
        self.__init_indycar_cache()
        now = time.time()
        if not force and (now - self._ic_drivers_cache['ts']) < self._ic_drivers_ttl:
            return self._ic_drivers_cache['data']
        try:
            url = f"{_BLOB_BASE}/driversfeed.json"
            r = self.session.get(url, headers=HEADERS,
                                 params={'_': int(now * 1000)},
                                 timeout=TIMEOUTS.get('default', 10))
            r.raise_for_status()
            payload = r.json()
            raw = payload.get('drivers', {}).get('driver', [])
            if not isinstance(raw, list):
                raw = []
            index = {}
            for d in raw:
                num = str(d.get('number') or '').strip()
                if num:
                    index[num] = d
            self._ic_drivers_cache = {'ts': now, 'data': index}
            return index
        except Exception as exc:
            print(f"[IndyCar] driversfeed fetch error: {exc}")
            return self._ic_drivers_cache.get('data', {})

    def _fetch_indycar_weather(self):
        """Fetch basic IMS conditions for the static IndyCar panel."""
        self.__init_indycar_cache()
        now = time.time()
        if (now - self._ic_weather_cache.get('ts', 0.0)) < self._ic_weather_ttl:
            return self._ic_weather_cache.get('data') or {}
        try:
            url = (
                "https://api.open-meteo.com/v1/forecast"
                f"?latitude={_IMS_LAT}&longitude={_IMS_LON}"
                "&current=temperature_2m,wind_speed_10m,wind_direction_10m"
                "&temperature_unit=fahrenheit&wind_speed_unit=mph&timezone=auto"
            )
            r = self.session.get(url, headers=HEADERS, timeout=TIMEOUTS.get('default', 10))
            r.raise_for_status()
            current = (r.json().get('current') or {})

            def _rounded(value):
                try:
                    return str(int(round(float(value))))
                except Exception:
                    return ''

            weather = {
                'air_temp': _rounded(current.get('temperature_2m')),
                'wind_mph': _rounded(current.get('wind_speed_10m')),
                'wind_dir': _rounded(current.get('wind_direction_10m')),
            }
            self._ic_weather_cache = {'ts': now, 'data': weather}
            return weather
        except Exception as exc:
            print(f"[IndyCar] weather fetch error: {exc}")
            return self._ic_weather_cache.get('data') or {}

    def _fetch_indycar(self, force=False):
        """Fetch live IndyCar session and return a list of game objects (0 or 1)."""
        self.__init_indycar_cache()
        now = time.time()
        if not force and (now - self._ic_timing_cache['ts']) < self._ic_timing_ttl:
            cached = self._ic_timing_cache.get('data')
            if cached is not None:
                return [cached]

        try:
            url = f"{_BLOB_BASE}/timingscoring-ris.json"
            r = self.session.get(url, headers=HEADERS,
                                 params={'_': int(now * 1000)},
                                 timeout=TIMEOUTS.get('default', 10))
            r.raise_for_status()
            payload = r.json()
        except Exception as exc:
            print(f"[IndyCar] timingscoring fetch error: {exc}")
            stale = self._ic_timing_cache.get('data')
            return [stale] if stale else []

        timing = payload.get('timing_results', {})
        if not timing:
            # Blob returned empty — session may have just ended. If we have a
            # FINAL result cached, keep showing it for the grace period before
            # switching to the schedule countdown.
            cached_game = self._ic_timing_cache.get('data')
            _is_live_timing_post = (
                cached_game and isinstance(cached_game, dict)
                and cached_game.get('state') == 'post'
                and not str(cached_game.get('id', '')).startswith('indycar_sched_')
            )
            if _is_live_timing_post:
                if not self._ic_timing_cache.get('post_since'):
                    self._ic_timing_cache['post_since'] = now
                    self._ic_save_post_since(now)
                if (now - self._ic_timing_cache['post_since']) <= _IC_POST_GRACE_SECS:
                    self._ic_timing_cache['ts'] = now
                    return [cached_game]
                # Grace period expired — fall through to schedule
                self._ic_timing_cache['post_since'] = None
                self._ic_save_post_since(None)
            elif self._ic_timing_cache.get('post_since'):
                self._ic_timing_cache['post_since'] = None
                self._ic_save_post_since(None)
            game = self._build_indycar_schedule_game(datetime.now(timezone.utc))
            self._ic_timing_cache['ts'] = now
            self._ic_timing_cache['data'] = game
            return [game] if game else []

        drivers_index = self._fetch_indycar_drivers()
        game = self._build_indycar_game(timing, drivers_index)

        if game:
            game.setdefault('indycar', {})['weather'] = self._fetch_indycar_weather()
            event_id = game.get('id', '')

            if game.get('state') == 'post':
                # Layer 1: permanently expired event IDs (auto-learned, survives restarts).
                if event_id in self._ic_expired_ids:
                    game = None

                # Layer 2: start_time present → expire 24 h after race start.
                if game:
                    start_utc = game.get('startTimeUTC', '')
                    if start_utc:
                        try:
                            start_dt = parse_iso(start_utc)
                            if start_dt and (datetime.now(timezone.utc) - start_dt).total_seconds() > 24 * 3600:
                                self._ic_expire_event(event_id)
                                game = None
                        except Exception:
                            pass

                # Layer 3: no start_time → use post_since timer (12 h grace window).
                # post_since is persisted to disk so restarts don't reset it.
                if game and not game.get('startTimeUTC'):
                    if not self._ic_timing_cache.get('post_since'):
                        self._ic_timing_cache['post_since'] = now
                        self._ic_save_post_since(now)
                    if (now - self._ic_timing_cache['post_since']) > _IC_POST_GRACE_SECS:
                        self._ic_expire_event(event_id)
                        game = None

            else:
                # Live or pre — clear post_since if it lingered.
                if self._ic_timing_cache.get('post_since'):
                    self._ic_timing_cache['post_since'] = None
                    self._ic_save_post_since(None)

            # Persist any real live-timing game (post or live) so a restart
            # doesn't lose the last known session results.
            if game and not str(game.get('id', '')).startswith('indycar_sched_'):
                self._ic_save_last_final(game)

        if not game:
            # Nothing from the blob — not for NTT INDYCAR SERIES (e.g. Indy NXT),
            # or a stale/expired post-race session just got cleared above. Either
            # way, fall back to the season schedule for the next race.
            game = self._build_indycar_schedule_game(datetime.now(timezone.utc))

        self._ic_timing_cache['ts'] = now
        self._ic_timing_cache['data'] = game
        return [game] if game else []

    def _build_indycar_game(self, timing, drivers_index):
        hb = timing.get('heartbeat', {}) or {}

        # The racecontrol blob also carries Indy NXT sessions (Series != 'I').
        # Only show NTT INDYCAR SERIES on the ticker.
        series_field = str(hb.get('Series') or '').strip().upper()
        if series_field and series_field != 'I':
            return None
        if 'NXT' in str(hb.get('eventName') or '').upper():
            return None

        event_name   = str(hb.get('eventName') or 'IndyCar').strip()
        track_name   = str(hb.get('trackName') or '').strip()
        session_raw  = str(hb.get('SessionType') or 'R').strip().upper()
        session_name = str(hb.get('SessionName') or hb.get('EventSessionLabel') or '').strip()
        session_label = _SESSION_TYPE_MAP.get(session_raw, session_raw)
        short_event_name = _simplify_indycar_event_name(event_name, track_name)
        short_session_name = _simplify_indycar_session(session_label, session_name)
        start_time_utc = _extract_indycar_start_time(hb)

        # Determine state first so we can skip staleness checks for live sessions.
        flag_status    = normalize_flag(hb.get('currentFlag') or hb.get('SessionStatus') or '')
        session_status = str(hb.get('SessionStatus') or '').strip().upper()

        _POST_STATUSES = {'FINAL', 'ENDED', 'UNOFFICIAL', 'OFFICIAL', 'CHKD', 'COLD'}
        if session_status in _POST_STATUSES or flag_status in _POST_STATUSES:
            state = 'post'
        elif flag_status in _LIVE_FLAGS or session_status in _LIVE_FLAGS:
            state = 'in'
        else:
            state = 'pre'

        # For live or recently-finished sessions the blob is authoritative —
        # never hide them due to a missing start time. For 'pre' sessions
        # without one (the blob often doesn't announce a start time until
        # close to the session), fall back to the season's race-day schedule
        # so a real countdown still shows, like other sports on this ticker.
        if state == 'pre' and not start_time_utc:
            sched = self._fetch_indycar_schedule()
            match = _ic_find_schedule_session(sched, datetime.now(timezone.utc)) if sched else None
            if match:
                start_time_utc = match[2].strftime('%Y-%m-%dT%H:%M:%SZ')
            else:
                return None

        caution = flag_status in CAUTION_FLAGS

        # Lap info (race sessions)
        current_lap = 0
        total_laps  = int(hb.get('totalLaps') or hb.get('TotalLaps') or hb.get('lapsInEvent') or 0)
        laps_rem    = int(hb.get('lapsToGo') or hb.get('LapsToGo') or 0)
        items = timing.get('Item', [])
        if isinstance(items, list) and items:
            try:
                current_lap = max(int(d.get('laps') or 0) for d in items if isinstance(d, dict))
            except Exception:
                pass

        # Time to go (timed/qualifying sessions)
        time_to_go = str(hb.get('overallTimeToGo') or '').strip()

        # Status display string
        if state == 'post':
            status_display = 'FINAL'
        elif state == 'in':
            is_practice = session_raw in ('P', 'W')
            is_race     = session_raw == 'R'
            is_quali    = session_raw in ('Q', 'F')

            if is_practice:
                # Practice: show the current flag colour
                if flag_status in ('YELLOW',):
                    status_display = 'YELLOW'
                elif flag_status == 'RED':
                    status_display = 'RED FLAG'
                elif flag_status == 'CHECKERED':
                    status_display = 'CHECKERED'
                else:
                    status_display = 'GREEN'

            elif is_race:
                # Race: show lap count, falling back to flag
                if total_laps > 0:
                    status_display = f"Lap {current_lap}/{total_laps}"
                elif laps_rem > 0:
                    status_display = f"{laps_rem} to go"
                elif flag_status == 'YELLOW':
                    status_display = 'YELLOW'
                elif flag_status == 'RED':
                    status_display = 'RED FLAG'
                elif flag_status == 'CHECKERED':
                    status_display = 'CHECKERED'
                else:
                    status_display = 'GREEN'

            elif is_quali:
                # Qualifying: show time remaining
                if time_to_go:
                    status_display = time_to_go
                elif flag_status == 'YELLOW':
                    status_display = 'YELLOW'
                elif flag_status == 'RED':
                    status_display = 'RED FLAG'
                elif flag_status == 'CHECKERED':
                    status_display = 'CHECKERED'
                else:
                    status_display = 'GREEN'

            else:
                status_display = 'LIVE'

        else:
            if start_time_utc:
                start_display = start_time_utc
                try:
                    start_dt = parse_iso(start_time_utc)
                    if start_dt:
                        utc_off = _core.state.get('utc_offset', -5)
                        start_display = start_dt.astimezone(timezone(timedelta(hours=utc_off))).strftime('%I:%M %p').lstrip('0')
                except Exception:
                    pass
                status_display = f"Starts {start_display}"
            else:
                status_display = 'Starts Soon'

        # Build driver list
        if not isinstance(items, list):
            items = []

        drivers = []
        for item in items:
            if not isinstance(item, dict):
                continue

            car_num   = str(item.get('no') or '').strip()
            first     = str(item.get('firstName') or '').strip()
            last      = str(item.get('lastName') or '').strip()
            team_name = str(item.get('team') or '').strip()
            try:
                position = int(item.get('rank') or item.get('overallRank') or 0)
            except Exception:
                position = 0

            abbr = _build_abbr(first, last)

            laps_completed = str(item.get('laps') or '').strip()
            driver_status  = str(item.get('status') or 'Active').strip()
            on_track       = str(item.get('onTrack') or '').strip().lower() == 'true'

            # Speed and gap — qualifying shows MPH, race shows time gap
            if session_raw == 'Q':
                speed     = str(item.get('qualSpeed') or item.get('BestSpeed') or '').strip()
                best_time = str(item.get('bestLapTime') or '').strip()
                # For qualifying all positions show their speed in mph
                if speed:
                    try:
                        gap = f"{float(speed):.3f}"
                    except Exception:
                        gap = speed
                else:
                    gap = ''
            else:
                speed     = str(item.get('LastSpeed') or item.get('BestSpeed') or '').strip()
                best_time = str(item.get('bestLapTime') or '').strip()
                raw_gap = str(item.get('diff') or item.get('gap') or '').strip()
                if not raw_gap or raw_gap in ('0', '0.0000', '0.000', '--'):
                    gap = 'Leader' if position == 1 else ''
                else:
                    gap = raw_gap

            # Cross-reference driver feed for enriched data
            drv_feed = drivers_index.get(car_num, {})
            headshot   = str(drv_feed.get('headshot') or '').strip()
            car_illus  = str(drv_feed.get('carillustration') or '').strip()
            endplate   = str(drv_feed.get('endplatesmall') or drv_feed.get('endplatelarge') or '').strip()

            # Use endplate as the "logo" — it shows the car number and primary color
            # Fall back to headshot if no endplate
            logo_url = endplate or headshot or ''

            # Livery colors from hardcoded table (endplate color extraction would be too slow inline)
            pri_hex, sec_hex = _team_livery(team_name)

            drivers.append({
                'pos':              position,
                'name':             f"{first} {last}".strip() or 'Unknown',
                'abbr':             abbr,
                'car':              car_num,
                'team':             team_name,
                'team_logo':        logo_url,
                'car_illustration': car_illus,
                'livery_primary':   pri_hex,
                'livery_secondary': sec_hex,
                'gap':              gap,
                'laps':             laps_completed,
                'speed':            speed,
                'best_time':        best_time,
                'status':           driver_status,
                'on_track':         on_track,
            })

        drivers.sort(key=lambda d: d['pos'] if d['pos'] > 0 else 999)

        event_id = str(hb.get('EventID') or hb.get('EventSessionID') or 'indycar_live')
        away_abbr = short_event_name
        home_abbr = short_session_name

        return {
            'id':           event_id,
            'type':         'racing',
            'sport':        'indycar',
            'state':        state,
            'status':       status_display,
            'is_shown':     True,
            'startTimeUTC': start_time_utc,
            'away_abbr':    away_abbr,
            'home_abbr':    home_abbr,
            'away_score':   '',
            'home_score':   '',
            'indycar': {
                'event_name':   short_event_name,
                'short_name':   short_event_name,
                'track_name':   track_name,
                'session_type': short_session_name,
                'session_name': short_session_name,
                'lap':          current_lap,
                'total_laps':   total_laps,
                'laps_remaining': laps_rem,
                'time_to_go':   time_to_go,
                'caution':      caution,
                'flag':         flag_status,
                'drivers':      drivers,
            },
        }
