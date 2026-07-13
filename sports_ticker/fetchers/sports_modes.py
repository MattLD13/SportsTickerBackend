import concurrent.futures

from .. import core as _core
globals().update({k: v for k, v in vars(_core).items() if not k.startswith('__')})
from .sports_modes_common import _sports_no_games_placeholder
from .test_mode import TestMode

spotify_fetcher = None
flight_tracker = None

class SportsModesMixin:
    def fetch_pinned_game(self, pinned_str, conf, visible_start_utc, visible_end_utc):
        """
        Fetches ONLY the pinned game, bypassing all other league fetches.
        pinned_str format: "league:game_id" (e.g., "nfl:401547378" or "soccer_epl:423141")
        """
        try:
            league_key, game_id = pinned_str.split(':', 1)
            league_key = league_key.lower()
        except ValueError:
            return []

        utc_offset = conf.get('utc_offset', -5)

        # Golf pin always resolves to current golf snapshot.
        if league_key in ('golf', 'masters'):
            golf_game = self._fetch_golf_game(force=True)
            return [golf_game] if golf_game else []

        if league_key == 'f1':
            return self._fetch_f1(force=True)

        # 0. NHL Native Pinned Game (handles NHL gamecenter IDs like 2025020978)
        if league_key == 'nhl':
            try:
                native = self._fetch_nhl_landing(game_id)
                if native:
                    st = str(native.get('gameState', 'OFF')).upper()
                    map_st = 'in' if st in ['LIVE', 'CRIT'] else ('pre' if st in ['PRE', 'FUT'] else 'post')

                    g_utc = native.get('startTimeUTC', '')
                    raw_h = native.get('homeTeam', {}).get('abbrev', 'UNK')
                    raw_a = native.get('awayTeam', {}).get('abbrev', 'UNK')
                    h_ab = ABBR_MAPPING.get(raw_h, raw_h)
                    a_ab = ABBR_MAPPING.get(raw_a, raw_a)

                    h_sc = str(native.get('homeTeam', {}).get('score', 0))
                    a_sc = str(native.get('awayTeam', {}).get('score', 0))

                    h_lg = self.get_corrected_logo('nhl', h_ab, f"https://a.espncdn.com/i/teamlogos/nhl/500/{h_ab.lower()}.png")
                    a_lg = self.get_corrected_logo('nhl', a_ab, f"https://a.espncdn.com/i/teamlogos/nhl/500/{a_ab.lower()}.png")
                    h_info = self.lookup_team_info_from_cache('nhl', h_ab, logo=h_lg)
                    a_info = self.lookup_team_info_from_cache('nhl', a_ab, logo=a_lg)

                    disp = "Scheduled"
                    pp = False
                    poss = ""
                    en = False
                    shootout_data = None

                    pd = native.get('periodDescriptor', {})
                    clk = native.get('clock', {})
                    p_num = int(pd.get('number', 1) or 1)
                    p_type = str(pd.get('periodType', '')).upper()
                    time_rem = clk.get('timeRemaining', '00:00')

                    if map_st == 'pre':
                        try:
                            g_dt = parse_iso(g_utc)
                            disp = g_dt.astimezone(timezone(timedelta(hours=utc_offset))).strftime("%I:%M %p").lstrip('0')
                        except:
                            pass
                    elif map_st == 'post':
                        disp = "FINAL"
                        if p_type == 'SHOOTOUT' or p_num >= 5:
                            disp = "FINAL S/O"
                        elif p_type == 'OT' or p_num == 4:
                            disp = "FINAL OT"
                    else:
                        if p_type == 'SHOOTOUT' or p_num >= 5:
                            disp = "S/O"
                            shootout_data = self.fetch_shootout_details(game_id, 0, 0)
                        elif clk.get('inIntermission', False) or time_rem == "00:00":
                            if p_num == 1:
                                disp = "End 1st"
                            elif p_num == 2:
                                disp = "End 2nd"
                            elif p_num == 3:
                                disp = "End 3rd"
                            else:
                                disp = "End OT"
                        else:
                            p_lbl = "OT" if p_num == 4 else f"P{p_num}"
                            disp = f"{p_lbl} {time_rem}"

                    sit_obj = native.get('situation', {})
                    if sit_obj:
                        sit = sit_obj.get('situationCode', '1551')
                        if len(sit) >= 4 and sit.isdigit():
                            ag = int(sit[0])
                            as_ = int(sit[1])
                            hs = int(sit[2])
                            hg = int(sit[3])
                            if as_ > hs:
                                pp = True
                                poss = a_ab
                            elif hs > as_:
                                pp = True
                                poss = h_ab
                            en = (ag == 0 or hg == 0)

                    if "FINAL" in disp:
                        shootout_data = None

                    return [{
                        'type': 'scoreboard',
                        'sport': 'nhl', 'id': str(game_id), 'status': disp, 'state': map_st, 'is_shown': True,
                        'home_abbr': h_ab, 'home_score': h_sc, 'home_logo': h_lg, 'home_id': h_ab,
                        'away_abbr': a_ab, 'away_score': a_sc, 'away_logo': a_lg, 'away_id': a_ab,
                        'home_color': f"#{h_info['color']}", 'home_alt_color': f"#{h_info['alt_color']}",
                        'away_color': f"#{a_info['color']}", 'away_alt_color': f"#{a_info['alt_color']}",
                        'startTimeUTC': g_utc,
                        'estimated_duration': self.calculate_game_timing('nhl', g_utc, p_num, disp),
                        'situation': {
                            'powerPlay': pp,
                            'possession': poss,
                            'emptyNet': en,
                            'shootout': shootout_data
                        }
                    }]
            except Exception as e:
                print(f"NHL Pinned Game Error: {e}")

        # 1. FotMob (Soccer) Pinned Game
        if league_key in FOTMOB_LEAGUE_MAP:
            try:
                url = f"https://www.fotmob.com/api/matchDetails?matchId={game_id}"
                resp = self.session.get(url, headers=HEADERS, timeout=TIMEOUTS['slow'])
                if resp.status_code == 200:
                    payload = resp.json()
                    general = payload.get("general", {})
                    header = payload.get("header", {})
                    status_obj = header.get("status", {})
                    
                    # Convert matchDetails into the standard FotMob 'matches' array format 
                    mock_match = {
                        "id": game_id,
                        "home": {"id": general.get("homeTeam", {}).get("id"), "name": general.get("homeTeam", {}).get("name")},
                        "away": {"id": general.get("awayTeam", {}).get("id"), "name": general.get("awayTeam", {}).get("name")},
                        "status": {
                            "utcTime": general.get("matchTimeUTC"),
                            "finished": status_obj.get("finished"),
                            "started": status_obj.get("started"),
                            "cancelled": status_obj.get("cancelled"),
                            "scoreStr": status_obj.get("scoreStr"),
                            "reason": status_obj.get("reason"),
                            "liveTime": status_obj.get("liveTime")
                        }
                    }
                    
                    # Pass a massive time window so it passes normal time filters
                    huge_start = dt(1970, 1, 1, tzinfo=timezone.utc)
                    huge_end = dt(2099, 1, 1, tzinfo=timezone.utc)
                    return self._extract_matches([mock_match], league_key, conf, huge_start, huge_end, huge_start, huge_end)
            except Exception as e:
                print(f"FotMob Pinned Game Error: {e}")
                return []

        # 2. ESPN Pinned Game (NFL, NBA, MLB, NHL, NCAA)
        config = self.leagues.get(league_key)
        path = config.get('path') if config else None
        if not path:
            paths = {
                'nfl': 'football/nfl', 'mlb': 'baseball/mlb', 'nhl': 'hockey/nhl', 'nba': 'basketball/nba',
                'ncf_fbs': 'football/college-football', 'ncf_fcs': 'football/college-football',
                'march_madness': 'basketball/mens-college-basketball'
            }
            path = paths.get(league_key)

        if not path:
            print(f"Unsupported pinned game league: {league_key}")
            return []

        try:
            url = f"{self.base_url}{path}/summary?event={game_id}"
            r = self.session.get(url, headers=HEADERS, timeout=TIMEOUTS['default'])
            if r.status_code != 200:
                return []
            
            data = r.json()
            header = data.get('header', {})
            comp = header.get('competitions', [{}])[0]
            
            e_date = comp.get('date', '')
            st = comp.get('status', {})
            tp = st.get('type', {})
            gst = tp.get('state', 'pre')

            # Extract competitors
            competitors = comp.get('competitors', [])
            h = next((c for c in competitors if c.get('homeAway') == 'home'), competitors[0] if competitors else {})
            a = next((c for c in competitors if c.get('homeAway') == 'away'), competitors[1] if len(competitors) > 1 else {})

            h_ab = h.get('team', {}).get('abbreviation', 'UNK')
            a_ab = a.get('team', {}).get('abbreviation', 'UNK')

            h_lg = self.get_corrected_logo(league_key, h_ab, h.get('team', {}).get('logos', [{}])[0].get('href', ''))
            a_lg = self.get_corrected_logo(league_key, a_ab, a.get('team', {}).get('logos', [{}])[0].get('href', ''))

            h_clr = h.get('team', {}).get('color', '000000')
            a_clr = a.get('team', {}).get('color', '000000')
            h_alt = h.get('team', {}).get('alternateColor', 'ffffff')
            a_alt = a.get('team', {}).get('alternateColor', 'ffffff')

            if not h_clr or h_clr == '000000' or not a_clr or a_clr == '000000':
                h_info = self.lookup_team_info_from_cache(league_key, h_ab, logo=h_lg)
                a_info = self.lookup_team_info_from_cache(league_key, a_ab, logo=a_lg)
                h_clr = h_clr if h_clr and h_clr != '000000' else h_info.get('color', '000000')
                a_clr = a_clr if a_clr and a_clr != '000000' else a_info.get('color', '000000')
                h_alt = h_alt if h_alt else h_info.get('alt_color', 'ffffff')
                a_alt = a_alt if a_alt else a_info.get('alt_color', 'ffffff')

            h_score = h.get('score', '0')
            a_score = a.get('score', '0')

            s_disp = tp.get('shortDetail', 'TBD')
            p = st.get('period', 1)

            # State Inference
            if gst == 'pre' and any(x in s_disp for x in ['1st', '2nd', '3rd', 'OT', 'Half', 'Qtr', 'Inning']):
                if "FINAL" not in s_disp.upper():
                    gst = 'in'

            is_suspended = any(kw in s_disp for kw in ["Suspended", "Postponed", "Canceled", "Delayed", "PPD"])

            if not is_suspended:
                if gst == 'pre':
                    try: 
                        game_dt = parse_iso(e_date)
                        s_disp = game_dt.astimezone(timezone(timedelta(hours=utc_offset))).strftime("%I:%M %p").lstrip('0')
                    except: pass
                elif gst in ['in', 'half']:
                    clk = st.get('displayClock', '0:00').replace("'", "")
                    if (not clk or clk == '0:00') and ':' in s_disp:
                        m = re.search(r'(\d{1,2}:\d{2})', s_disp)
                        if m: clk = m.group(1)

                    if gst == 'half' or (p == 2 and clk == '0:00' and 'football' in path): s_disp = "Halftime"
                    elif 'hockey' in path and clk == '0:00':
                        s_disp = "End 1st" if p == 1 else "End 2nd" if p == 2 else "End 3rd" if p == 3 else "Intermission"
                    else:
                        if 'basketball' in path:
                            if p > 4:
                                s_disp = f"OT{p-4 if p-4>1 else ''} {clk}"
                            elif league_key == 'march_madness' and p <= 2:
                                s_disp = f"H{p} {clk}"
                            else:
                                s_disp = f"Q{p} {clk}"
                        elif 'football' in path:
                            s_disp = f"OT{p-4 if p-4>1 else ''} {clk}" if p > 4 else f"Q{p} {clk}"
                        elif 'hockey' in path:
                            s_disp = f"OT{p-3 if p-3>1 else ''} {clk}" if p > 3 else f"P{p} {clk}"
                        elif 'baseball' in path:
                            s_disp = self._mlb_normalize_status_label(
                                tp.get('shortDetail', s_disp).replace(" - ", " ").replace("Inning", "In")
                            )
                        else: s_disp = f"P{p} {clk}"

            s_disp = s_disp.replace("Final", "FINAL").replace("/OT", " OT").replace("/SO", " S/O")
            s_disp = s_disp.replace("End of ", "End ").replace(" Quarter", "").replace(" Inning", "").replace(" Period", "")

            # Possessions & Situations
            sit_data = data.get('drives', {}).get('current', {}) if 'football' in path else {}
            # For football, also check the competition situation (has full downDistanceText with position)
            comp_sit = comp.get('situation', {}) if 'football' in path else {}
            poss_raw = comp_sit.get('possession') or (sit_data.get('team', {}).get('id') if sit_data else None)

            balls, strikes, outs, onFirst, onSecond, onThird = 0, 0, 0, False, False, False
            batter_name = pitcher_name = batter_avg = batter_h = batter_ab = ''
            last_pitch_type = last_pitch_type_abbr = last_pitch_type_full = ''
            pitcher_pitches = last_pitch_speed = 0
            if 'baseball' in path and data.get('situation'):
                bsit = data['situation']
                balls = bsit.get('balls', 0)
                strikes = bsit.get('strikes', 0)
                outs = bsit.get('outs', 0)
                onFirst = bool(bsit.get('onFirst', False))
                onSecond = bool(bsit.get('onSecond', False))
                onThird = bool(bsit.get('onThird', False))

                # ESPN summary gives bare {playerId: N} — look up names via athletes API
                _bat_obj = bsit.get('batter') or {}
                _pit_obj = bsit.get('pitcher') or {}
                _bat_pid = self._mlb_player_id_from_obj(_bat_obj)
                _pit_pid = self._mlb_player_id_from_obj(_pit_obj)
                poss_raw = None   # batter team unavailable in summary; determine from inning
                batter_name = self._mlb_resolve_person_name(
                    _bat_obj,
                    _bat_pid,
                    bsit.get('batterName') or bsit.get('batter_name') or ''
                )
                pitcher_name = self._mlb_resolve_person_name(
                    _pit_obj,
                    _pit_pid,
                    bsit.get('pitcherName') or bsit.get('pitcher_name') or ''
                )

                _mlb_stats = self._mlb_extract_situation_stats(bsit, _bat_obj, _pit_obj, data)
                batter_avg = _mlb_stats.get('batter_avg', '')
                batter_h = _mlb_stats.get('batter_h', '')
                batter_ab = _mlb_stats.get('batter_ab', '')
                pitcher_pitches = _mlb_stats.get('pitcher_pitches', 0)
                last_pitch_speed = _mlb_stats.get('last_pitch_speed', 0)
                last_pitch_type = _mlb_stats.get('last_pitch_type', '')
                last_pitch_type_abbr = _mlb_stats.get('last_pitch_type_abbr', last_pitch_type)
                last_pitch_type_full = _mlb_stats.get('last_pitch_type_full', '')

                _box_stats = self._mlb_extract_boxscore_stats(data, _bat_pid, _pit_pid)
                batter_avg = _box_stats.get('batter_avg') or batter_avg
                batter_h = _box_stats.get('batter_h') or batter_h
                batter_ab = _box_stats.get('batter_ab') or batter_ab
                pitcher_pitches = _box_stats.get('pitcher_pitches') or pitcher_pitches

            poss_abbr = ""
            if str(poss_raw) == str(h.get('team', {}).get('id')): poss_abbr = h_ab
            elif str(poss_raw) == str(a.get('team', {}).get('id')): poss_abbr = a_ab
            # comp_sit possession may already be an abbreviation
            if not poss_abbr and str(poss_raw).upper() == h_ab: poss_abbr = h_ab
            elif not poss_abbr and str(poss_raw).upper() == a_ab: poss_abbr = a_ab

            # Prefer competition situation downDistanceText (includes position "at TEAM YARD")
            down_text = (comp_sit.get('downDistanceText') or comp_sit.get('shortDownDistanceText')
                         or sit_data.get('shortDownDistanceText') or sit_data.get('description') or '')
            if s_disp == "Halftime": down_text = ''
            is_rz = comp_sit.get('isRedZone', False) or sit_data.get('isRedZone', False)

            game_obj = {
                'type': 'scoreboard', 'sport': league_key, 'id': game_id, 'status': s_disp, 'state': gst, 'is_shown': not is_suspended,
                'home_abbr': h_ab, 'home_score': h_score, 'home_logo': h_lg, 'home_id': h.get('team', {}).get('id'),
                'away_abbr': a_ab, 'away_score': a_score, 'away_logo': a_lg, 'away_id': a.get('team', {}).get('id'),
                'home_color': f"#{h_clr}", 'home_alt_color': f"#{h_alt}",
                'away_color': f"#{a_clr}", 'away_alt_color': f"#{a_alt}",
                'startTimeUTC': e_date,
                'estimated_duration': 180,
                'situation': {
                    'possession': poss_abbr,
                    'isRedZone': is_rz,
                    'downDist': down_text,
                    'yardLine': comp_sit.get('yardLine'),
                    'yardsToGo': comp_sit.get('distance'),
                    'possessionTeam': comp_sit.get('possessionText', ''),
                    'shootout': None,
                    'powerPlay': False,
                    'emptyNet': False,
                    'balls': balls, 'strikes': strikes, 'outs': outs,
                    'onFirst': onFirst, 'onSecond': onSecond, 'onThird': onThird,
                    'batter_name': batter_name, 'batter_avg': batter_avg,
                    'batter_h': batter_h, 'batter_ab': batter_ab,
                    'pitcher_name': pitcher_name, 'pitcher_pitches': pitcher_pitches,
                    'last_pitch_speed': last_pitch_speed,
                    'last_pitch_type': last_pitch_type,
                    'last_pitch_type_abbr': last_pitch_type_abbr,
                    'last_pitch_type_full': last_pitch_type_full}
            }

            if 'baseball' in (path or ''):
                self._mlb_apply_challenge_fields(
                    game_obj,
                    str(game_id),
                    h_ab,
                    a_ab,
                    e_date,
                    h.get('team', {}).get('id'),
                    a.get('team', {}).get('id'),
                )

            return [game_obj]

        except Exception as e:
            print(f"ESPN Pinned Game Error: {e}")
            return []

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
                start_utc_str = g.get('startTimeUTC', '')
                if not start_utc_str and g_type == 'racing':
                    # Racing games (NASCAR/IndyCar/F1) with no startTimeUTC rely on
                    # their own fetcher-level expiry — if they reached here without
                    # a start time they've already been deemed current; show them.
                    filtered.append(g)
                else:
                    try:
                        game_dt = parse_iso(start_utc_str)
                        if visible_start_utc <= game_dt < visible_end_utc:
                            filtered.append(g)
                    except Exception:
                        if g_type != 'racing':
                            filtered.append(g)
                        # racing with unparseable startTimeUTC: skip — expiry
                        # should have been handled at the fetcher level
                continue
            filtered.append(g)
        filtered.sort(key=_game_sort_key)
        return filtered

    def _build_sports_buffer(self):
        """Fetch all active sports leagues and return sorted game list."""
        with data_lock:
            conf = {
                'active_sports': state.get('active_sports', {}),
                'mode': state.get('mode', 'sports'),
                'utc_offset': state.get('utc_offset', -5),
                'debug_mode': state.get('debug_mode', False),
                'custom_date': state.get('custom_date')}

            # Special pinned-game poller inputs (sports_full): collect active pins
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
            for indycar_game in self._fetch_indycar():
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
            for f1_game in self._fetch_f1():
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
        # normal sports feed so sports_full gets a fresh focused game while
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

        if not all_games:
            clock_text = time.strftime('%I:%M %p').lstrip('0')
            return [_sports_no_games_placeholder(clock_text)]

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
        return self._fetch_indycar()

    def _build_f1_buffer(self):
        return self._fetch_f1()

    def _build_nascar_buffer(self):
        obj = self._fetch_nascar()
        if obj:
            return [obj]
        return [{
            'id': 'nascar_loading',
            'type': 'racing',
            'sport': 'nascar',
            'state': 'pre',
            'status': 'Loading',
            'is_shown': True,
            'startTimeUTC': '',
            'away_abbr': 'NASCAR',
            'home_abbr': 'Cup Series',
            'away_score': '',
            'home_score': '',
            'nascar': {
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
        }]

    def _build_flights_buffer(self):
        if not flight_tracker:
            return []
        return flight_tracker.get_airport_objects()

    def _build_flight_tracker_buffer(self):
        if not flight_tracker:
            return [self._flight_tracker_placeholder_object()]
        obj = flight_tracker.get_visitor_object()
        return [obj] if obj else [self._flight_tracker_placeholder_object()]

    def update_current_games(self):
        """Build and cache content buffers for every mode currently needed by any ticker."""
        if not self._update_lock.acquire(blocking=False):
            # A refresh is already running. Coalesce this request and run once more.
            self._update_pending.set()
            return

        try:
            while True:
                # Consume any prior coalesced request before this pass; new requests
                # that arrive during the pass will set the event again.
                self._update_pending.clear()

                with data_lock:
                    global_mode = state.get('mode', 'sports')
                    # Collect all modes currently in use across all tickers.
                    needed: set = {global_mode}
                    for t in tickers.values():
                        m = t.get('settings', {}).get('mode')
                        if m and m in VALID_MODES:
                            needed.add(m)

                        # If any ticker has a special racing/golf pin, ensure the
                        # dedicated buffer is built even when that ticker is in
                        # another mode (e.g. clock).
                        # even when that ticker is currently in another mode (e.g. clock).
                        t_settings = t.get('settings', {})
                        t_single_pin, t_pin_list = _normalize_single_pin(
                            pinned_game=t_settings.get('pinned_game'),
                            pinned_games=t_settings.get('pinned_games', []),
                        )
                        for _pin in t_pin_list:
                            pin_norm = str(_pin).strip().lower()
                            if not pin_norm:
                                continue
                            if ':' in pin_norm:
                                pin_league = pin_norm.split(':', 1)[0]
                            else:
                                pin_league = 'golf' if pin_norm.startswith(('golf', 'masters')) else ''
                            if pin_league in ('golf', 'masters'):
                                needed.add('golf')
                                break
                            if pin_league == 'f1':
                                needed.add('f1')
                                break

                _dispatch = {
                    'sports':         self._build_sports_buffer,
                    'live':           self._build_sports_buffer,
                    'my_teams':       self._build_sports_buffer,
                    'soccer_full':    self._build_sports_buffer,
                    'stocks':         self._build_stocks_buffer,
                    'weather':        self._build_weather_buffer,
                    'music':          self._build_music_buffer,
                    'clock':          self._build_clock_buffer,
                    'golf':           self._build_golf_buffer,
                    'masters':        self._build_golf_buffer,   # legacy alias
                    'flights':        self._build_flights_buffer,
                    'flight_tracker': self._build_flight_tracker_buffer,
                    'indycar':        self._build_indycar_buffer,
                    'indycar_full':   self._build_indycar_buffer,
                    'f1':             self._build_f1_buffer,
                    'f1_full':        self._build_f1_buffer,
                    'nascar':         self._build_nascar_buffer,
                    'nascar_full':    self._build_nascar_buffer,
                }

                sports_built = False
                for mode in needed:
                    is_sports = mode in ('sports', 'live', 'my_teams', 'sports_full', 'soccer_full')

                    if is_sports and sports_built:
                        # Sports-like modes share one raw buffer; filtering happens in /data.
                        continue

                    builder = _dispatch.get(mode, self._build_sports_buffer)
                    result = builder()

                    if is_sports:
                        sports_built = True
                        for sm in ('sports', 'live', 'my_teams', 'sports_full', 'soccer_full'):
                            self._set_mode_buffer(sm, result)

                        snap = (time.time(), result[:])
                        self.history_buffer.append(snap)
                        if len(self.history_buffer) > 120:
                            self.history_buffer = self.history_buffer[-120:]

                        if result:
                            try:
                                save_json_atomically(GAME_CACHE_FILE, result)
                            except Exception:
                                pass
                    else:
                        self._set_mode_buffer(mode, result)

                # Keep global state['current_games'] in sync with the global mode.
                with self._mode_buffer_lock:
                    global_result = self._mode_buffers.get(global_mode, [])
                is_global_sports = global_mode in ('sports', 'live', 'my_teams', 'sports_full', 'soccer_full')
                with data_lock:
                    if global_result or not is_global_sports or not state.get('current_games'):
                        state['current_games'] = global_result

                # Drain coalesced refreshes without recursive calls.
                if not self._update_pending.is_set():
                    break
        finally:
            self._update_lock.release()

    def get_snapshot_for_delay(self, delay_seconds):
        """Return current games, optionally from history buffer for live-delay."""
        with self._mode_buffer_lock:
            latest_sports = list(self._mode_buffers.get('sports', []))

        if delay_seconds <= 0:
            if latest_sports:
                return latest_sports
            return []

        if not self.history_buffer:
            if latest_sports:
                return latest_sports
            return []

        target_time = time.time() - delay_seconds
        chosen = None
        for ts, snapshot in reversed(self.history_buffer):
            if ts <= target_time:
                chosen = snapshot
                break

        if chosen is None and self.history_buffer:
            chosen = self.history_buffer[0][1]

        if chosen is None:
            return latest_sports

        return chosen

    def _set_mode_buffer(self, mode: str, result: list):
        """Store result in per-mode buffer. Also syncs global buffer when mode matches global."""
        with self._mode_buffer_lock:
            self._mode_buffers[mode] = result
        # Keep global state['current_games'] in sync for backward compat
        with data_lock:
            if state.get('mode') == mode:
                if result or not state.get('current_games'):
                    state['current_games'] = result

    def get_mode_snapshot(self, mode: str, delay_seconds: float = 0) -> list:
        """Return buffered content for the given mode.
        Sports modes with delay use the history buffer for live-delay support.
        All other modes always return current data (delay is ignored).
        """
        refresh_on_access = mode in ('indycar', 'indycar_full', 'f1', 'f1_full')
        if mode in ('sports', 'live', 'my_teams', 'sports_full', 'soccer_full'):
            return self.get_snapshot_for_delay(delay_seconds)
        with self._mode_buffer_lock:
            snapshot = list(self._mode_buffers.get(mode, []))

        if snapshot and not refresh_on_access:
            return snapshot

        # Web dashboard previews can ask for a mode that no paired ticker is
        # currently using. Build those lightweight buffers on demand so the
        # website behaves as an independent preview surface.
        _dispatch = {
            'stocks':         self._build_stocks_buffer,
            'weather':        self._build_weather_buffer,
            'music':          self._build_music_buffer,
            'clock':          self._build_clock_buffer,
            'golf':           self._build_golf_buffer,
            'masters':        self._build_golf_buffer,
            'flights':        self._build_flights_buffer,
            'flight_tracker': self._build_flight_tracker_buffer,
            'indycar':        self._build_indycar_buffer,
            'indycar_full':   self._build_indycar_buffer,
            'f1':             self._build_f1_buffer,
            'f1_full':        self._build_f1_buffer,
        }
        builder = _dispatch.get(mode)
        if not builder:
            return []

        try:
            result = builder()
            self._set_mode_buffer(mode, result)
            return list(result)
        except Exception as e:
            print(f"[preview] on-demand buffer build failed for {mode}: {e}")
            return []

