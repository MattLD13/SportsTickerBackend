"""NASCAR live data fetcher using cf.nascar.com public feeds."""

import re
from datetime import date, timedelta

from .. import core as _core
globals().update({k: v for k, v in vars(_core).items() if not k.startswith('__')})

_NASCAR_LIVE_URL = "https://cf.nascar.com/cacher/live/live-feed.json"
_NASCAR_HEADERS  = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}

# 2026 NCS schedule: race_id → (race_num, track_slug, race_date_iso)
# race_num excludes Duels (5594, 5595); upload date = race_date - 5 days (Tuesday of race week)
# Track slug: strip Motor/Speedway/Raceway/International/Superspeedway/Stadium; join remaining words
_NCS_2026 = {
    5593: (1,  'Bowmangray',            '2026-02-04'),
    5596: (2,  'Daytona',               '2026-02-15'),
    5597: (3,  'Atlanta',               '2026-02-22'),
    5598: (4,  'Cota',                  '2026-03-01'),
    5599: (5,  'Phoenix',               '2026-03-08'),
    5600: (6,  'Lasvegas',              '2026-03-15'),
    5603: (7,  'Darlington',            '2026-03-22'),
    5602: (8,  'Martinsville',          '2026-03-29'),
    5604: (9,  'Bristol',               '2026-04-12'),
    5607: (10, 'Kansas',                '2026-04-19'),
    5605: (11, 'Talladega',             '2026-04-26'),
    5606: (12, 'Texas',                 '2026-05-03'),
    5621: (13, 'Watkinsglen',           '2026-05-10'),
    5609: (14, 'Dover',                 '2026-05-17'),
    5610: (15, 'Charlotte',             '2026-05-24'),
    5611: (16, 'Nashville',             '2026-05-31'),
    5612: (17, 'Michigan',              '2026-06-07'),
    5614: (18, 'Pocono',                '2026-06-14'),
    5613: (19, 'Sandiego',              '2026-06-21'),
    5617: (20, 'Sonoma',                '2026-06-28'),
    5616: (21, 'Chicagoland',           '2026-07-05'),
    5615: (22, 'Atlanta',               '2026-07-12'),
    5618: (23, 'Northwilkesboro',       '2026-07-19'),
    5619: (24, 'Indianapolis',          '2026-07-26'),
    5620: (25, 'Iowa',                  '2026-08-09'),
    5622: (26, 'Richmond',              '2026-08-15'),
    5627: (27, 'Newhampshire',          '2026-08-23'),
    5623: (28, 'Daytona',               '2026-08-29'),
    5624: (29, 'Darlington',            '2026-09-06'),
    5625: (30, 'Worldwidetechnology',   '2026-09-13'),
    5626: (31, 'Bristol',               '2026-09-19'),
    5628: (32, 'Kansas',                '2026-09-27'),
    5630: (33, 'Lasvegas',              '2026-10-04'),
    5629: (34, 'Charlotte',             '2026-10-11'),
    5633: (35, 'Phoenix',               '2026-10-18'),
    5631: (36, 'Talladega',             '2026-10-25'),
    5632: (37, 'Martinsville',          '2026-11-01'),
    5601: (38, 'Homesteadmiami',        '2026-11-08'),
}

_NASCAR_IMG_BASE = "https://www.nascar.com/wp-content/uploads/sites/7"


def _nascar_car_image_url(race_id, car_number, year=2026):
    entry = _NCS_2026.get(int(race_id or 0))
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
    yy  = str(year)[-2:]
    mon = f"{upload_day.month:02d}"
    day = f"{upload_day.day:02d}"
    car = str(car_number).strip()
    return (
        f"{_NASCAR_IMG_BASE}/{year}/{mon}/{day}/"
        f"{yy}_NCS_{race_num}{track_slug}_{car}-922x400.jpg"
    )


def _nascar_car_image_candidates(race_id, car_number, year=2026):
    """Return candidate URLs trying upload offsets 4-7 days before race."""
    entry = _NCS_2026.get(int(race_id or 0))
    if not entry:
        return []
    race_num, track_slug, race_date_iso = entry
    try:
        race_day = date.fromisoformat(race_date_iso)
    except Exception:
        return []
    yy  = str(year)[-2:]
    car = str(car_number).strip()
    urls = []
    for offset in (5, 6, 4, 7):
        d = race_day - timedelta(days=offset)
        urls.append(
            f"{_NASCAR_IMG_BASE}/{year}/{d.month:02d}/{d.day:02d}/"
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

    def _fetch_nascar(self, force=False):
        """Fetch the live NASCAR feed and return a racing game object."""
        self.__init_nascar_cache()
        now_ts = time.time()
        if not force and (now_ts - self._nascar_cache.get('ts', 0.0)) < self._nascar_ttl:
            return self._nascar_cache.get('data')

        try:
            r = self.session.get(
                _NASCAR_LIVE_URL,
                headers=_NASCAR_HEADERS,
                timeout=10,
            )
            r.raise_for_status()
            feed = r.json()

            lap          = int(feed.get('lap_number') or 0)
            total_laps   = int(feed.get('laps_in_race') or 0)
            laps_to_go   = int(feed.get('laps_to_go') or 0)
            flag_state   = int(feed.get('flag_state') or 0)
            track_name   = str(feed.get('track_name') or 'NASCAR').strip()
            run_name     = str(feed.get('run_name') or 'NASCAR Race').strip()
            series_id    = int(feed.get('series_id') or 1)
            race_id      = int(feed.get('race_id') or 0)
            cautions     = int(feed.get('number_of_caution_laps') or 0)

            series_label = _SERIES_LABEL.get(series_id, 'NASCAR')
            flag         = _nascar_flag(flag_state, laps_to_go)
            caution      = flag_state == 2

            if laps_to_go == 0 and total_laps > 0:
                state = 'post'
            elif lap > 0:
                state = 'in'
            else:
                state = 'pre'

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
                    'team_logo': f"https://cf.nascar.com/data/images/carbadges/1/{car_num}.png" if car_num else '',
                    'car_illustration': _nascar_car_image_url(race_id, car_num),
                    'livery_primary': _nascar_make_color(make),
                    'livery_secondary': '#111111',
                    'gap': _nascar_compact_gap(delta, pos),
                    'speed': '',
                    'status': 'Active' if on_track else 'Out',
                    'on_track': on_track,
                    'make': make,
                })

            # Shorten run_name so it fits display (~22 chars)
            short_name = run_name
            for drop in ('NASCAR CUP SERIES ', 'NASCAR XFINITY SERIES ', 'NASCAR CRAFTSMAN TRUCK SERIES '):
                short_name = short_name.replace(drop, '').replace(drop.title(), '')
            # Also strip " - Final Segment" / " - Final" suffixes for the display name
            for suffix in (' - Final Segment', ' - FINAL SEGMENT', ' - Final', ' - FINAL'):
                if short_name.endswith(suffix):
                    short_name = short_name[:-len(suffix)].strip()
                    break
            short_name = short_name.strip()

            # session_label e.g. "Race", "Qualifying" — used as home_abbr for iOS app display
            session_label_short = {1: 'Race', 2: 'Xfinity', 3: 'Trucks'}.get(series_id, series_label)

            game = {
                'id': f"nascar_{feed.get('race_id', 'live')}",
                'type': 'racing',
                'sport': 'nascar',
                'state': state,
                'status': 'LIVE' if state == 'in' else ('FINAL' if state == 'post' else 'Starts Soon'),
                'is_shown': True,
                'startTimeUTC': '',
                'away_abbr': short_name,
                'home_abbr': session_label_short,
                'away_score': '',
                'home_score': '',
                'nascar': {
                    'race_id': race_id,
                    'event_name': run_name,
                    'short_name': short_name,
                    'track_name': track_name,
                    'session_type': series_label,
                    'session_name': series_label,
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
            log(f"[NASCAR] fetch error: {exc}")
            return self._nascar_cache.get('data')
