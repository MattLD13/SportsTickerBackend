"""Per-mode content buffer builders."""

import concurrent.futures
import time

from .. import core as _core
globals().update({k: v for k, v in vars(_core).items() if not k.startswith('__')})
from .sports_modes_common import (
    _racing_loading_game,
    flight_tracker,
    spotify_fetcher,
)


class SportsModesBuffersMixin:
    def get_music_object(self, require_enabled=True):
        if require_enabled and not state['active_sports'].get('music', False): return None

        custom = state.get('custom_music_track', {})
        if custom and custom.get('title'):
            duration_sec = custom.get('duration_ms', 0) / 1000.0 or 180.0
            elapsed = time.time() - custom.get('set_at', time.time())
            prog = elapsed % duration_sec if duration_sec else 0
            cur_m, cur_s = divmod(int(prog), 60)
            tot_m, tot_s = divmod(int(duration_sec), 60)
            return {
                'type': 'music',
                'sport': 'music',
                'id': 'custom_track',
                'status': f"{cur_m}:{cur_s:02d} / {tot_m}:{tot_s:02d}",
                'state': 'in',
                'is_shown': True,
                'home_abbr': custom.get('artist', ''),
                'away_abbr': custom.get('title', ''),
                'home_logo': custom.get('art_url', ''),
                'next_logos': [],
                'situation': {
                    'progress': prog,
                    'duration': duration_sec,
                    'is_playing': True,
                    'fetch_ts': time.time(),
                }
            }

        if not spotify_fetcher:
            return None
        s_data = spotify_fetcher.get_cached_state()
        
        # If no data or explicit "Waiting for Music" state, return placeholder
        if not s_data or s_data.get('name') == "Waiting for Music...":
            return None

        is_playing = s_data.get('is_playing', False)
        
        # INTERPOLATION: Only add elapsed time if Spotify says it is currently playing
        elapsed = 0
        if is_playing:
            elapsed = time.time() - s_data.get('last_fetch_ts', time.time())
        
        prog = min(s_data['progress'] + elapsed, s_data['duration'])
        
        cur_m, cur_s = divmod(int(prog), 60)
        tot_m, tot_s = divmod(int(s_data['duration']), 60)
        
        # Clearer status string for the ticker
        if is_playing:
            status_str = f"{cur_m}:{cur_s:02d} / {tot_m}:{tot_s:02d}"
        else:
            status_str = f"PAUSED {cur_m}:{cur_s:02d}"

        return {
            'type': 'music', 
            'sport': 'music', 
            'id': 'spotify_now',
            'status': status_str, 
            'state': 'in' if is_playing else 'paused',
            'is_shown': True, 
            'home_abbr': s_data.get('artist', 'Unknown'),
            'away_abbr': s_data.get('name', 'Unknown'),
            'home_logo': s_data.get('cover', ''),
            'situation': {
                'progress': prog,
                'duration': s_data['duration'],
                'is_playing': is_playing,
                'fetch_ts': time.time()
            }
        }

    def _music_placeholder_object(self):
        return {
            'type': 'music',
            'sport': 'music',
            'id': 'spotify_idle',
            'status': 'IDLE',
            'state': 'paused',
            'is_shown': True,
            'home_abbr': 'MUSIC',
            'away_abbr': 'NO SONG DATA',
            'home_logo': '',
            'next_logos': [],
            'situation': {
                'progress': 0,
                'duration': 1,
                'is_playing': False,
                'fetch_ts': time.time()
            }
        }

    def _flight_tracker_placeholder_object(self):
        return {
            'type': 'flight_visitor',
            'sport': 'flight',
            'id': 'flight_tracker_blank',
            'guest_name': 'NO FLIGHT SELECTED',
            'route': 'TRACKER > SETUP',
            'origin_city': 'TRACKER',
            'dest_city': 'SETUP',
            'alt': 0,
            'dist': 0,
            'eta_str': '--',
            'speed': 0,
            'progress': 0,
            'status': 'ADD FLIGHT',
            'delay_min': 0,
            'is_delayed': False,
            'is_live': False,
            'aircraft_type': '',
            'aircraft_code': '',
            'is_shown': True
        }

    def _filter_and_sort_games(self, all_games, visible_start_utc, visible_end_utc):
        """Apply 3AM cutoff window filter and sort by priority."""
        filtered = []
        for g in all_games:
            g_type = g.get('type', '')
            g_sport = g.get('sport', '')
            if g_type in ['clock', 'weather', 'music'] or g_sport in ['clock', 'weather', 'music', 'flight']:
                filtered.append(g)
                continue
            state_val = g.get('state', '')
            status_val = str(g.get('status', '')).upper()
            if state_val in ['in', 'half', 'crit']:
                filtered.append(g)
                continue
            if state_val == 'pre':
                # Racing sessions: only show on the day the session is scheduled
                if g_type == 'racing' and g.get('startTimeUTC'):
                    try:
                        game_dt = parse_iso(g.get('startTimeUTC'))
                        if not (visible_start_utc <= game_dt < visible_end_utc):
                            continue
                    except Exception:
                        pass
                filtered.append(g)
                continue
            if state_val == 'post' or 'FINAL' in status_val:
                try:
                    game_dt = parse_iso(g.get('startTimeUTC', ''))
                    if visible_start_utc <= game_dt < visible_end_utc:
                        filtered.append(g)
                except Exception:
                    filtered.append(g)
                continue
            filtered.append(g)
        filtered.sort(key=_game_sort_key)
        return filtered

    def _build_sports_buffer(self):
        """Fetch all active sports leagues and return sorted game list."""
        with data_lock:
            conf = {
                'active_sports': state.get('active_sports', {}),
                'active_modes': state.get('active_modes', {}),
                'mode': state.get('mode', 'sports'),
                'utc_offset': state.get('utc_offset', -5),
                'debug_mode': state.get('debug_mode', False),
                'custom_date': state.get('custom_date')}

            # Special pinned-game poller inputs: collect active pins
            # and merge fresh pinned objects into the normal sports snapshot.
            active_pins = []
            seen_pins = set()
            for _t in tickers.values():
                _s = _t.get('settings', {})
                single_pin, pin_list = _normalize_single_pin(
                    pinned_game=_s.get('pinned_game'),
                    pinned_games=_s.get('pinned_games', [])
                )
                for _p in pin_list:
                    _pn = str(_p).strip().lower()
                    if _pn and _pn not in seen_pins:
                        seen_pins.add(_pn)
                        active_pins.append(_p)
            golf_needed = bool(conf.get('active_sports', {}).get('golf', True))
            if not golf_needed:
                golf_needed = any(str(p).strip().lower().startswith(('golf:', 'masters:')) for p in active_pins)
            indycar_needed = bool(conf.get('active_sports', {}).get('indycar', True))
            f1_needed = bool(conf.get('active_sports', {}).get('f1', True))
            nascar_needed = bool(conf.get('active_sports', {}).get('nascar', False))
            
        all_games = []
        utc_offset = conf.get('utc_offset', -5)
        now_utc = dt.now(timezone.utc)
        now_local = now_utc.astimezone(timezone(timedelta(hours=utc_offset)))
        
        # Visibility Windows
        if now_local.hour < 3:
            visible_start_local = (now_local - timedelta(days=1)).replace(hour=10, minute=0, second=0, microsecond=0)
            visible_end_local = now_local.replace(hour=3, minute=0, second=0, microsecond=0)
        else:
            visible_start_local = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
            visible_end_local = (now_local + timedelta(days=1)).replace(hour=3, minute=0, second=0, microsecond=0)
        
        visible_start_utc = visible_start_local.astimezone(timezone.utc)
        visible_end_utc = visible_end_local.astimezone(timezone.utc)
        window_start_utc = (now_local - timedelta(hours=30)).astimezone(timezone.utc)
        window_end_utc = (now_local + timedelta(hours=48)).astimezone(timezone.utc)

        futures = {}
        for internal_id, fid in FOTMOB_LEAGUE_MAP.items():
            if not conf.get('active_sports', {}).get(internal_id, False):
                continue
            f = self.executor.submit(self._fetch_fotmob_league, fid, internal_id, conf, window_start_utc, window_end_utc, visible_start_utc, visible_end_utc)
            futures[f] = internal_id

        if not conf['debug_mode']:
            f = self.executor.submit(self._fetch_nhl_native, conf, window_start_utc, window_end_utc, visible_start_utc, visible_end_utc)
            futures[f] = 'nhl_native'

        for league_key, config in self.leagues.items():
            if league_key in ('nhl', 'golf', 'indycar', 'f1') or league_key.startswith('soccer_'): continue
            if not conf.get('active_sports', {}).get(league_key, False): continue
            f = self.executor.submit(self.fetch_single_league, league_key, config, conf, window_start_utc, window_end_utc, utc_offset, visible_start_utc, visible_end_utc)
            futures[f] = league_key
        
        partial = {lk: self.league_last_data.get(lk, []) for lk in futures.values()}
        deadline = time.time() + API_TIMEOUT

        for future in concurrent.futures.as_completed(list(futures.keys())):
            lk = futures[future]
            try:
                res = future.result(timeout=0)
                if res:
                    partial[lk] = res
                    self.league_last_data[lk] = res
            except Exception: pass
            interim_all = []
            for games in partial.values(): interim_all.extend(games)
            interim = self._filter_and_sort_games(interim_all, visible_start_utc, visible_end_utc)
            with data_lock:
                if interim or not state.get('current_games'): state['current_games'] = interim
            if time.time() >= deadline: break

        all_games = []
        for games in partial.values(): all_games.extend(games)

        if golf_needed:
            golf_game = self._fetch_golf_game()
            if golf_game:
                g_key = (str(golf_game.get('sport', '')), str(golf_game.get('id', '')))
                replaced = False
                for idx, existing in enumerate(all_games):
                    e_key = (str(existing.get('sport', '')), str(existing.get('id', '')))
                    if e_key == g_key:
                        all_games[idx] = golf_game
                        replaced = True
                        break
                if not replaced:
                    all_games.append(golf_game)

        if indycar_needed:
            indycar_game = self._fetch_indycar()
            if indycar_game:
                ic_key = (str(indycar_game.get('sport', '')), str(indycar_game.get('id', '')))
                replaced = False
                for idx, existing in enumerate(all_games):
                    if (str(existing.get('sport', '')), str(existing.get('id', ''))) == ic_key:
                        all_games[idx] = indycar_game
                        replaced = True
                        break
                if not replaced:
                    all_games.append(indycar_game)

        if f1_needed:
            f1_game = self._fetch_f1()
            if f1_game:
                f1_key = (str(f1_game.get('sport', '')), str(f1_game.get('id', '')))
                replaced = False
                for idx, existing in enumerate(all_games):
                    if (str(existing.get('sport', '')), str(existing.get('id', ''))) == f1_key:
                        all_games[idx] = f1_game
                        replaced = True
                        break
                if not replaced:
                    all_games.append(f1_game)

        if nascar_needed:
            nascar_game = self._fetch_nascar()
            if nascar_game:
                nc_key = (str(nascar_game.get('sport', '')), str(nascar_game.get('id', '')))
                replaced = False
                for idx, existing in enumerate(all_games):
                    if (str(existing.get('sport', '')), str(existing.get('id', ''))) == nc_key:
                        all_games[idx] = nascar_game
                        replaced = True
                        break
                if not replaced:
                    all_games.append(nascar_game)

        # Pinned refresh merge: poll only pinned games and merge them into the
        # normal sports feed so pinned full-screen display gets a fresh focused game while
        # retaining all other scores from the standard poller.
        if active_pins:
            pinned_futures = {
                self.executor.submit(self.fetch_pinned_game, p, conf, visible_start_utc, visible_end_utc): p
                for p in active_pins
            }
            merged_index = {(str(g.get('sport', '')), str(g.get('id', ''))): i for i, g in enumerate(all_games)}
            for pf in concurrent.futures.as_completed(list(pinned_futures.keys())):
                try:
                    pin_games = pf.result(timeout=0)
                except Exception:
                    pin_games = []
                for pg in pin_games or []:
                    key = (str(pg.get('sport', '')), str(pg.get('id', '')))
                    if key in merged_index:
                        all_games[merged_index[key]] = pg
                    else:
                        merged_index[key] = len(all_games)
                        all_games.append(pg)

        return self._filter_and_sort_games(all_games, visible_start_utc, visible_end_utc)

    def _build_stocks_buffer(self):
        with data_lock:
            active_sports = dict(state['active_sports'])
        games = []
        for item in LEAGUE_OPTIONS:
            if item['type'] == 'stock' and active_sports.get(item['id'], False):
                games.extend(self.stocks.get_list(item['id']))
        return games

    def _build_weather_buffer(self):
        with data_lock:
            city = state['weather_city']
            lat  = state['weather_lat']
            lon  = state['weather_lon']
        if lat != self.weather.lat or lon != self.weather.lon or city != self.weather.city_name:
            self.weather.update_config(city=city, lat=lat, lon=lon)
        w = self.weather.get_weather()
        if w:
            return [w]
        return [{
            'type': 'weather',
            'sport': 'weather',
            'id': 'weather_loading',
            'away_abbr': str(city or 'WEATHER').upper(),
            'home_abbr': '--',
            'situation': {
                'icon': 'cloud',
                'stats': {'aqi': '--', 'uv': '--'},
                'forecast': []
            },
            'home_score': '--',
            'away_score': '0',
            'status': 'LOADING',
            'is_shown': True
        }]

    def _build_music_buffer(self):
        obj = self.get_music_object(require_enabled=False)
        return [obj] if obj else [self._music_placeholder_object()]

    def _build_clock_buffer(self):
        return [{'type': 'clock', 'sport': 'clock', 'id': 'clk', 'is_shown': True}]

    def _build_golf_buffer(self):
        obj = self._fetch_golf_game(force=True)
        if obj:
            return [obj]
        return [self._golf_placeholder_game()]

    def _build_indycar_buffer(self):
        obj = self._fetch_indycar()
        if obj:
            return [obj]
        return [_racing_loading_game(
            'indycar', 'indycar', 'IndyCar', 'Race',
            {
                'event_name': 'IndyCar',
                'short_name': 'IndyCar',
                'session_type': 'Race',
                'lap': 0,
                'total_laps': 0,
                'laps_remaining': 0,
                'caution': False,
                'drivers': [],
            },
        )]

    def _build_f1_buffer(self):
        obj = self._fetch_f1()
        if obj:
            return [obj]
        return [_racing_loading_game(
            'f1', 'f1', 'Formula 1', 'Race',
            {
                'event_name': 'Formula 1',
                'short_name': 'Formula 1',
                'session_type': 'Race',
                'flag': 'GREEN',
                'drivers': [],
                'weather': {},
            },
        )]

    def _build_nascar_buffer(self):
        obj = self._fetch_nascar()
        if obj:
            return [obj]
        return [_racing_loading_game(
            'nascar', 'nascar', 'NASCAR', 'Cup Series',
            {
                'event_name': 'NASCAR',
                'short_name': 'NASCAR',
                'track_name': '',
                'session_type': 'Cup Series',
                'flag': 'GREEN',
                'lap': 0,
                'total_laps': 0,
                'laps_remaining': 0,
                'caution': False,
                'drivers': [],
                'weather': {},
            },
        )]

    def _build_flights_buffer(self):
        if not flight_tracker:
            return []
        return flight_tracker.get_airport_objects()

    def _build_flight_tracker_buffer(self):
        if not flight_tracker:
            return [self._flight_tracker_placeholder_object()]
        obj = flight_tracker.get_visitor_object()
        return [obj] if obj else [self._flight_tracker_placeholder_object()]
