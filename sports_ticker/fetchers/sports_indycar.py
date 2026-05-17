"""IndyCar live data fetcher using IndyCar's official Azure Blob Storage API.

Endpoints discovered by reverse-engineering leaderboard.indycar.com:
  timingscoring-ris.json  — live timing/scoring for current session
  driversfeed.json        — static driver roster (headshots, livery images, car numbers)
  tsconfig.json           — session config flags
"""

from .. import core as _core
globals().update({k: v for k, v in vars(_core).items() if not k.startswith('__')})

_BLOB_BASE = "https://indycar.blob.core.windows.net/racecontrol"

_SESSION_TYPE_MAP = {
    'Q': 'Qualifying',
    'P': 'Practice',
    'R': 'Race',
    'W': 'Warm Up',
    'F': 'Qualifying',   # Fast Friday / final qualifying runs
}

_LIVE_FLAGS = {'GREEN', 'YELLOW', 'RED', 'CHECKERED', 'WHITE'}

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
    if last:
        return last[:3].upper()
    if first:
        return first[:3].upper()
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


class SportsIndycarMixin:

    def __init_indycar_cache(self):
        if not hasattr(self, '_ic_timing_cache'):
            self._ic_timing_cache = {'ts': 0.0, 'data': None}
            self._ic_drivers_cache = {'ts': 0.0, 'data': {}}   # car_number → driver dict
            self._ic_timing_ttl   = 8.0     # seconds — poll live data frequently
            self._ic_drivers_ttl  = 300.0   # seconds — driver roster changes rarely

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
            log(f"[IndyCar] driversfeed fetch error: {exc}")
            return self._ic_drivers_cache.get('data', {})

    def _fetch_indycar(self, force=False):
        """Fetch live IndyCar session and return a game object, or None."""
        self.__init_indycar_cache()
        now = time.time()
        if not force and (now - self._ic_timing_cache['ts']) < self._ic_timing_ttl:
            cached = self._ic_timing_cache.get('data')
            if cached is not None:
                return cached

        try:
            url = f"{_BLOB_BASE}/timingscoring-ris.json"
            r = self.session.get(url, headers=HEADERS,
                                 params={'_': int(now * 1000)},
                                 timeout=TIMEOUTS.get('default', 10))
            r.raise_for_status()
            payload = r.json()
        except Exception as exc:
            log(f"[IndyCar] timingscoring fetch error: {exc}")
            # Return stale cache if we have it
            return self._ic_timing_cache.get('data')

        timing = payload.get('timing_results', {})
        if not timing:
            return None

        drivers_index = self._fetch_indycar_drivers()
        game = self._build_indycar_game(timing, drivers_index)

        self._ic_timing_cache = {'ts': now, 'data': game}
        return game

    def _build_indycar_game(self, timing, drivers_index):
        hb = timing.get('heartbeat', {}) or {}

        event_name   = str(hb.get('eventName') or 'IndyCar').strip()
        track_name   = str(hb.get('trackName') or '').strip()
        session_raw  = str(hb.get('SessionType') or 'R').strip().upper()
        session_name = str(hb.get('SessionName') or hb.get('EventSessionLabel') or '').strip()
        session_label = _SESSION_TYPE_MAP.get(session_raw, session_raw)
        short_event_name = _simplify_indycar_event_name(event_name, track_name)
        short_session_name = _simplify_indycar_session(session_label, session_name)

        # State from flag / session status
        flag_status    = str(hb.get('currentFlag') or hb.get('SessionStatus') or '').strip().upper()
        session_status = str(hb.get('SessionStatus') or '').strip().upper()

        if session_status in ('FINAL', 'ENDED', 'UNOFFICIAL', 'OFFICIAL', 'CHKD'):
            state = 'post'
        elif flag_status in _LIVE_FLAGS or session_status in _LIVE_FLAGS:
            state = 'in'
        else:
            state = 'pre'

        caution = flag_status in ('YELLOW', 'RED')

        # Status display string
        if state == 'post':
            status_display = 'FINAL'
        elif state == 'in':
            if flag_status == 'YELLOW':
                status_display = 'YELLOW'
            elif flag_status == 'RED':
                status_display = 'RED FLAG'
            elif flag_status == 'CHECKERED':
                status_display = 'CHECKERED'
            else:
                status_display = 'LIVE'
        else:
            status_display = 'Scheduled'

        # Lap info (race sessions)
        current_lap = 0
        total_laps  = 0
        laps_rem    = 0
        items = timing.get('Item', [])
        if isinstance(items, list) and items:
            try:
                current_lap = max(int(d.get('laps') or 0) for d in items if isinstance(d, dict))
            except Exception:
                pass

        # Time to go (timed/qualifying sessions)
        time_to_go = str(hb.get('overallTimeToGo') or '').strip()

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

            # Gap / diff
            raw_gap = str(item.get('diff') or item.get('gap') or '').strip()
            if not raw_gap or raw_gap in ('0', '0.0000', '0.000', '--'):
                gap = 'Leader' if position == 1 else ''
            else:
                gap = raw_gap

            laps_completed = str(item.get('laps') or '').strip()
            driver_status  = str(item.get('status') or 'Active').strip()
            on_track       = str(item.get('onTrack') or '').strip().lower() == 'true'

            # Speed — qualSpeed for Q sessions, LastSpeed for race
            if session_raw == 'Q':
                speed = str(item.get('qualSpeed') or item.get('BestSpeed') or '').strip()
                best_time = str(item.get('bestLapTime') or '').strip()
                # For qualifying, gap is usually shown as time diff
            else:
                speed     = str(item.get('LastSpeed') or item.get('BestSpeed') or '').strip()
                best_time = str(item.get('bestLapTime') or '').strip()

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
            'startTimeUTC': '',
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
