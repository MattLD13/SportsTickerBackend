from .. import core as _core
globals().update({k: v for k, v in vars(_core).items() if not k.startswith('__')})
from .test_mode import TestMode

class SportsGolfMixin:
    def _golf_parse_relative_score(self, raw):
        txt = str(raw or '').strip().upper()
        if not txt:
            return None
        if txt in ('E', 'EVEN'):
            return 0
        try:
            return int(float(txt))
        except Exception:
            return None

    def _golf_format_relative_score(self, value):
        if value is None:
            return '--'
        if value == 0:
            return 'E'
        return f"+{value}" if value > 0 else str(value)

    def _golf_position_sort_key(self, raw_position):
        txt = str(raw_position or '').strip().upper()
        if not txt:
            return (9999, txt)
        if txt in ('CUT', 'WD', 'DQ'):
            return (10000, txt)
        cleaned = txt.replace('T', '')
        m = re.search(r'\d+', cleaned)
        if m:
            try:
                return (int(m.group(0)), txt)
            except Exception:
                return (9999, txt)
        return (9999, txt)

    def _golf_extract_holes(self, competitor):
        holes = [None] * 18
        rounds = competitor.get('linescores', []) if isinstance(competitor, dict) else []
        if not isinstance(rounds, list):
            rounds = []

        active_round = None
        for rd in reversed(rounds):
            if isinstance(rd, dict) and isinstance(rd.get('linescores'), list):
                active_round = rd
                break

        if not active_round:
            return holes

        seq_idx = 0
        for hole in active_round.get('linescores', []):
            if not isinstance(hole, dict):
                continue

            h_idx = None
            h_num = hole.get('period')
            try:
                h_num_int = int(h_num)
                if 1 <= h_num_int <= 18:
                    h_idx = h_num_int - 1
            except Exception:
                h_idx = None

            if h_idx is None:
                if seq_idx >= 18:
                    continue
                h_idx = seq_idx
                seq_idx += 1

            stroke = None
            for key in ('value', 'displayValue'):
                raw_val = hole.get(key)
                try:
                    if raw_val is not None and str(raw_val).strip() != '':
                        stroke = int(float(raw_val))
                        break
                except Exception:
                    continue

            if stroke is not None:
                holes[h_idx] = stroke
                if h_idx >= seq_idx:
                    seq_idx = h_idx + 1

        return holes

    def _golf_round_label(self, comp):
        round_num = None
        try:
            round_num = int(safe_get(comp, 'status', 'period', default=0) or 0)
        except Exception:
            round_num = None

        detail = str(safe_get(comp, 'status', 'type', 'shortDetail', default='') or '')
        if not round_num:
            m = re.search(r'round\s*(\d+)', detail, flags=re.IGNORECASE)
            if m:
                try:
                    round_num = int(m.group(1))
                except Exception:
                    round_num = None

        if round_num and round_num > 0:
            return f"ROUND {round_num}"
        return 'ROUND'

    def _fetch_golf_game(self, force=False):
        now_ts = time.time()
        cached = self._golf_cache.get('game')
        cached_ts = float(self._golf_cache.get('ts', 0.0) or 0.0)
        if not force and cached and (now_ts - cached_ts) < self._golf_cache_ttl:
            return cached

        try:
            url = "https://site.api.espn.com/apis/site/v2/sports/golf/pga/scoreboard"
            resp = self.session.get(
                url,
                headers=HEADERS,
                params={'_': int(now_ts * 1000)},
                timeout=TIMEOUTS['slow']
            )
            resp.raise_for_status()
            payload = resp.json() if resp.content else {}
            events = payload.get('events', []) if isinstance(payload, dict) else []
            if not isinstance(events, list) or not events:
                self._golf_cache = {'ts': now_ts, 'game': None}
                return None

            # Pick the first in-progress event, or else the most recent by date.
            active_event = None
            for event in events:
                comp0 = (event.get('competitions') or [{}])[0] or {}
                state = str(safe_get(comp0, 'status', 'type', 'state', default='pre') or 'pre').lower()
                if state in ('in', 'half', 'crit'):
                    active_event = event
                    break

            if not active_event:
                # Most recent event (first in list is typically most current from ESPN)
                active_event = events[0]

            event_name = str(active_event.get('name') or active_event.get('shortName') or 'PGA TOUR').strip()
            tour_colors = _golf_tournament_colors(event_name)

            comp = (active_event.get('competitions') or [{}])[0] or {}
            comps = comp.get('competitors', []) if isinstance(comp, dict) else []
            if not isinstance(comps, list):
                comps = []

            players = []
            for c in comps:
                if not isinstance(c, dict):
                    continue

                status_obj = c.get('status', {}) if isinstance(c.get('status'), dict) else {}
                pos = safe_get(status_obj, 'position', 'displayName', default='-')
                athlete = c.get('athlete', {}) if isinstance(c.get('athlete'), dict) else {}
                short_name = str(athlete.get('shortName') or athlete.get('displayName') or 'UNKNOWN').strip()
                if short_name:
                    short_name = short_name.split()[-1].upper()
                short_name = short_name[:14]

                total_val = self._golf_parse_relative_score(c.get('score'))
                if total_val is None:
                    total_val = self._golf_parse_relative_score(c.get('displayValue'))

                today_val = None
                stats = c.get('statistics', []) if isinstance(c.get('statistics'), list) else []
                for stat in stats:
                    if str(stat.get('name', '')).lower() == 'today':
                        today_val = self._golf_parse_relative_score(stat.get('displayValue'))
                        break

                holes = self._golf_extract_holes(c)
                players.append({
                    'pos': str(pos or '-'),
                    'name': short_name or 'UNKNOWN',
                    'total': total_val,
                    'today': today_val,
                    'thru': status_obj.get('thru', 0),
                    'holes': holes,
                })

            if not players:
                self._golf_cache = {'ts': now_ts, 'game': None}
                return None

            players.sort(
                key=lambda p: (
                    self._golf_position_sort_key(p.get('pos')),
                    p.get('total') if p.get('total') is not None else 9999,
                    p.get('name', 'ZZZ')
                )
            )
            leader = players[0]

            event_date = str(active_event.get('date') or comp.get('date') or '')
            year = str(dt.now().year)
            if len(event_date) >= 4 and event_date[:4].isdigit():
                year = event_date[:4]

            round_label = self._golf_round_label(comp)
            state_val = str(safe_get(comp, 'status', 'type', 'state', default='pre') or 'pre').lower()
            if state_val not in ('pre', 'in', 'half', 'post', 'final', 'crit'):
                state_val = 'pre'

            course = comp.get('course', [])
            if isinstance(course, list):
                course = course[0] if course else {}
            if not isinstance(course, dict):
                course = {}
            holes = course.get('holes', []) if isinstance(course.get('holes'), list) else []
            pars = []
            for h in holes[:18]:
                try:
                    pars.append(int(h.get('par')))
                except Exception:
                    pars.append(None)
            if len(pars) < 18:
                pars = [4, 5, 4, 3, 4, 3, 4, 5, 4, 4, 3, 4, 5, 4, 5, 3, 4, 4]

            leader_score = self._golf_format_relative_score(leader.get('total'))
            tourney_display = event_name.upper()

            game_obj = {
                'type': 'golf',
                'sport': 'golf',
                'id': str(active_event.get('id') or 'golf_current'),
                'status': round_label,
                'state': state_val,
                'is_shown': False,
                'away_abbr': tourney_display[:16],
                'away_score': str(year),
                'away_logo': tour_colors['logo'],
                'home_abbr': str(leader.get('name') or 'LEADER'),
                'home_score': leader_score,
                'home_logo': BLANK_LOGO_SENTINEL,
                'home_color': tour_colors['alt'],
                'home_alt_color': '#FFFFFF',
                'away_color': tour_colors['primary'],
                'away_alt_color': tour_colors['alt'],
                'tourney_name': tourney_display,
                'startTimeUTC': event_date,
                'estimated_duration': 60,
                'situation': {
                    'round': round_label,
                    'leader': str(leader.get('name') or 'LEADER'),
                    'leader_score': leader_score,
                },
                'golf': {
                    'event_name': tourney_display,
                    'year': str(year),
                    'round': round_label,
                    'brand': tour_colors['brand'],
                    'players': players,
                    'pars': pars,
                }
            }

            self._golf_cache = {'ts': now_ts, 'game': game_obj}
            return game_obj
        except Exception as e:
            print(f"Golf fetch error: {e}")
            return self._golf_cache.get('game')

    def _golf_placeholder_game(self):
        """Fallback so golf mode never degrades to clock when pinned off-season."""
        year = str(dt.now().year)
        tc = PGA_TOUR_COLORS
        return {
            'type': 'golf',
            'sport': 'golf',
            'id': 'golf_placeholder',
            'status': 'ROUND',
            'state': 'pre',
            'is_shown': False,
            'away_abbr': 'PGA TOUR',
            'away_score': year,
            'away_logo': tc['logo'],
            'home_abbr': 'LEADER',
            'home_score': '--',
            'home_logo': BLANK_LOGO_SENTINEL,
            'home_color': tc['alt'],
            'home_alt_color': '#FFFFFF',
            'away_color': tc['primary'],
            'away_alt_color': tc['alt'],
            'tourney_name': 'PGA TOUR',
            'startTimeUTC': '',
            'estimated_duration': 60,
            'situation': {
                'round': 'ROUND',
                'leader': 'LEADER',
                'leader_score': '--',
            },
            'golf': {
                'event_name': 'PGA TOUR',
                'year': year,
                'round': 'ROUND',
                'brand': tc['brand'],
                'players': [],
                'pars': [4, 5, 4, 3, 4, 3, 4, 5, 4, 4, 3, 4, 5, 4, 5, 3, 4, 4],
            }
        }
