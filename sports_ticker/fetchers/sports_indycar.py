"""IndyCar live data fetcher using IndyCar's official Azure Blob Storage API.

Endpoints discovered by reverse-engineering leaderboard.indycar.com:
  timingscoring-ris.json  — live timing/scoring for current session
  driversfeed.json        — static driver roster (headshots, livery images, car numbers)
  tsconfig.json           — session config flags
"""

from datetime import datetime, timezone, timedelta

from .. import core as _core
globals().update({k: v for k, v in vars(_core).items() if not k.startswith('__')})

_BLOB_BASE     = "https://indycar.blob.core.windows.net/racecontrol"
_ESPN_IRL_BASE = "http://site.api.espn.com/apis/site/v2/sports/racing/irl/scoreboard"
_IMS_LAT = 39.7950
_IMS_LON = -86.2340

_SESSION_TYPE_MAP = {
    'Q': 'Qualifying',
    'P': 'Practice',
    'R': 'Race',
    'W': 'Warm Up',
    'F': 'Qualifying',   # Fast Friday / final qualifying runs
}

_LIVE_FLAGS = {'GREEN', 'YELLOW', 'RED', 'CHECKERED', 'WHITE'}

# 2026 IndyCar roster: lowercase full name → (car_number, team_name)
# Used by the ESPN fallback to resolve car numbers before looking up driversfeed.
_INDYCAR_2026_ROSTER = {
    'álex palou':          ('10', 'Chip Ganassi Racing'),
    'alex palou':          ('10', 'Chip Ganassi Racing'),
    'pato o\'ward':        ('5',  'Arrow McLaren'),
    'patricio o\'ward':    ('5',  'Arrow McLaren'),
    'scott dixon':         ('9',  'Chip Ganassi Racing'),
    'josef newgarden':     ('2',  'Team Penske'),
    'will power':          ('26', 'Andretti Global'),
    'scott mclaughlin':    ('3',  'Team Penske'),
    'kyle kirkwood':       ('27', 'Andretti Global'),
    'nolan siegel':        ('6',  'Arrow McLaren'),
    'christian lundgaard': ('7',  'Arrow McLaren'),
    'kyffin simpson':      ('8',  'Chip Ganassi Racing'),
    'marcus armstrong':    ('66', 'Meyer Shank Racing'),
    'marcus ericsson':     ('28', 'Andretti Global'),
    'romain grosjean':     ('18', 'Dale Coyne Racing'),
    'alexander rossi':     ('20', 'Ed Carpenter Racing'),
    'christian rasmussen': ('21', 'Ed Carpenter Racing'),
    'david malukas':       ('12', 'Team Penske'),
    'felix rosenqvist':    ('60', 'Meyer Shank Racing'),
    'helio castroneves':   ('06', 'Meyer Shank Racing'),
    'takuma sato':         ('75', 'Rahal Letterman Lanigan Racing'),
    'rinus veekay':        ('76', 'Juncos Hollinger Racing'),
    'conor daly':          ('23', 'Dreyer & Reinbold Racing'),
    'jack harvey':         ('24', 'Dreyer & Reinbold Racing'),
    'louis foster':        ('45', 'Rahal Letterman Lanigan Racing'),
    'ryan hunter-reay':    ('31', 'Arrow McLaren'),
    'katherine legge':     ('11', 'HMD Motorsports w/ AJ Foyt Racing'),
    'mick schumacher':     ('47', 'Rahal Letterman Lanigan Racing'),
    'graham rahal':        ('15', 'Rahal Letterman Lanigan Racing'),
    'dennis hauger':       ('19', 'Dale Coyne Racing'),
    'jacob abel':          ('51', 'Abel Motorsports'),
    'sting ray robb':      ('77', 'Juncos Hollinger Racing'),
    'caio collet':         ('4',  'A.J. Foyt Enterprises'),
    'santino ferrucci':    ('14', 'A.J. Foyt Enterprises'),
    'ed carpenter':        ('33', 'Ed Carpenter Racing'),
}

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
    replacements = [
        ('110th Running of the ', ''),
        ('Running of the ', ''),
        ('Indianapolis 500', 'Indy 500'),
        ('Grand Prix', 'GP'),
        ('Championship', 'Champ'),
        ('Presented by', ''),
    ]
    for old, new in replacements:
        value = value.replace(old, new)
    value = ' '.join(value.split())
    if 'indy 500' in lowered or 'indianapolis 500' in lowered:
        return 'Indy 500'
    if 'fast 12' in lowered:
        return 'Fast 12'
    if 'fast 6' in lowered:
        return 'Fast 6'
    if 'fast 10' in lowered:
        return 'Fast 10'
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
            self._ic_timing_cache = {'ts': 0.0, 'data': None}
            self._ic_drivers_cache = {'ts': 0.0, 'data': {}}   # car_number → driver dict
            self._ic_weather_cache = {'ts': 0.0, 'data': {}}
            self._ic_timing_ttl   = 8.0     # seconds — poll live data frequently
            self._ic_drivers_ttl  = 300.0   # seconds — driver roster changes rarely
            self._ic_weather_ttl  = 300.0   # seconds — conditions are slower-moving

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

    def _fetch_indycar_espn_game(self):
        """Return a minimal IndyCar game object from ESPN IRL when the blob has no data."""
        try:
            r = self.session.get(_ESPN_IRL_BASE, headers=HEADERS,
                                 params={'_': int(time.time() * 1000)},
                                 timeout=TIMEOUTS.get('default', 10))
            r.raise_for_status()
            events = r.json().get('events', [])
        except Exception as exc:
            print(f"[IndyCar] ESPN fallback fetch error: {exc}")
            return None

        now_utc = datetime.now(timezone.utc)
        # Fetch driversfeed once up front — keyed by car number
        drivers_index = self._fetch_indycar_drivers()

        for event in events:
            competitions = event.get('competitions', [])
            if not competitions:
                continue
            comp      = competitions[0]
            start_str = comp.get('startDate') or comp.get('date') or event.get('date', '')
            status    = (comp.get('status') or {}).get('type', {})
            state     = status.get('state', 'pre')

            # Skip post-race events that ended more than 12 hours ago
            if state == 'post' and start_str:
                try:
                    start_dt = parse_iso(start_str)
                    if start_dt and (now_utc - start_dt).total_seconds() > 12 * 3600:
                        continue
                except Exception:
                    pass

            event_name = event.get('name', 'IndyCar')
            short_name = _simplify_indycar_event_name(event_name, '')

            if state == 'post':
                status_display = 'FINAL'
            elif state == 'in':
                status_display = 'LIVE'
            else:
                if start_str:
                    try:
                        start_dt = parse_iso(start_str)
                        utc_off  = _core.state.get('utc_offset', -5)
                        local_dt = start_dt.astimezone(timezone(timedelta(hours=utc_off)))
                        status_display = f"Starts {local_dt.strftime('%I:%M %p').lstrip('0')}"
                    except Exception:
                        status_display = 'Starts Soon'
                else:
                    status_display = 'Starts Soon'

            drivers = []
            for c in comp.get('competitors', []):
                athlete   = c.get('athlete', {})
                full_name = athlete.get('fullName', '')
                parts     = full_name.rsplit(' ', 1)
                first, last = (parts[0], parts[1]) if len(parts) == 2 else ('', full_name)
                pos = c.get('order', 0)

                # Resolve car number + team from hardcoded 2026 roster
                car_num, team_name = _INDYCAR_2026_ROSTER.get(
                    full_name.strip().lower(), (str(pos), ''))

                # Use car number to look up driversfeed for illustrations/endplate
                drv_feed  = drivers_index.get(car_num, {})
                car_illus = str(drv_feed.get('carillustration') or '').strip()
                endplate  = str(drv_feed.get('endplatesmall') or drv_feed.get('endplatelarge') or '').strip()
                headshot  = str(drv_feed.get('headshot') or '').strip()
                logo_url  = endplate or headshot
                pri_hex, sec_hex = _team_livery(team_name)

                drivers.append({
                    'pos':              pos,
                    'name':             full_name,
                    'abbr':             _build_abbr(first, last),
                    'car':              car_num,
                    'team':             team_name,
                    'team_logo':        logo_url,
                    'car_illustration': car_illus,
                    'livery_primary':   pri_hex,
                    'livery_secondary': sec_hex,
                    'gap':              '',
                    'laps':             '',
                    'speed':            '',
                    'best_time':        '',
                    'status':           'Active',
                    'on_track':         state == 'in',
                })

            return {
                'id':           str(event.get('id', 'indycar_espn')),
                'type':         'racing',
                'sport':        'indycar',
                'state':        state,
                'status':       status_display,
                'is_shown':     True,
                'startTimeUTC': start_str,
                'away_abbr':    short_name,
                'home_abbr':    'Race',
                'away_score':   '',
                'home_score':   '',
                'indycar': {
                    'event_name':     short_name,
                    'short_name':     short_name,
                    'track_name':     '',
                    'session_type':   'Race',
                    'session_name':   'Race',
                    'lap':            0,
                    'total_laps':     0,
                    'laps_remaining': 0,
                    'time_to_go':     '',
                    'caution':        False,
                    'flag':           '',
                    'drivers':        drivers,
                    'weather':        {},
                },
            }
        return None

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
            espn = self._fetch_indycar_espn_game()
            return [espn] if espn else []

        drivers_index = self._fetch_indycar_drivers()
        game = self._build_indycar_game(timing, drivers_index)
        if game:
            game.setdefault('indycar', {})['weather'] = self._fetch_indycar_weather()
        else:
            espn = self._fetch_indycar_espn_game()
            if espn:
                self._ic_timing_cache = {'ts': now, 'data': None}
                return [espn]

        self._ic_timing_cache = {'ts': now, 'data': game}
        return [game] if game else []

    def _build_indycar_game(self, timing, drivers_index):
        hb = timing.get('heartbeat', {}) or {}

        event_name   = str(hb.get('eventName') or 'IndyCar').strip()
        track_name   = str(hb.get('trackName') or '').strip()
        session_raw  = str(hb.get('SessionType') or 'R').strip().upper()
        session_name = str(hb.get('SessionName') or hb.get('EventSessionLabel') or '').strip()
        session_label = _SESSION_TYPE_MAP.get(session_raw, session_raw)
        short_event_name = _simplify_indycar_event_name(event_name, track_name)
        short_session_name = _simplify_indycar_session(session_label, session_name)
        start_time_utc = _extract_indycar_start_time(hb)

        # Determine state first so we can skip staleness checks for live sessions.
        flag_status    = str(hb.get('currentFlag') or hb.get('SessionStatus') or '').strip().upper()
        session_status = str(hb.get('SessionStatus') or '').strip().upper()

        _POST_STATUSES = {'FINAL', 'ENDED', 'UNOFFICIAL', 'OFFICIAL', 'CHKD', 'COLD'}
        if session_status in _POST_STATUSES or flag_status in _POST_STATUSES:
            state = 'post'
        elif flag_status in _LIVE_FLAGS or session_status in _LIVE_FLAGS:
            state = 'in'
        else:
            state = 'pre'

        # For live or recently-finished sessions the blob is authoritative —
        # never hide them due to a missing or stale start time.
        # Only filter 'pre' sessions where the start time is missing or stale.
        if state == 'pre':
            if not start_time_utc:
                return None
            try:
                start_dt = parse_iso(start_time_utc)
                if start_dt and abs((datetime.now(timezone.utc) - start_dt).total_seconds()) > 30 * 3600:
                    return None
            except Exception:
                return None

        caution = flag_status in ('YELLOW', 'RED')

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
