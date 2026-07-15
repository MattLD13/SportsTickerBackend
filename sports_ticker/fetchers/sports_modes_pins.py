"""Pinned-game fetch handlers."""

import re

from .. import core as _core
globals().update({k: v for k, v in vars(_core).items() if not k.startswith('__')})


class SportsModesPinsMixin:
    def _pin_nhl_native_game(self, game_id, utc_offset):
        """Build a pinned NHL scoreboard object from the native gamecenter API."""
        try:
            native = self._fetch_nhl_landing(game_id)
            if not native:
                return []
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
                except Exception:
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
                    'shootout': shootout_data,
                },
            }]
        except Exception as e:
            print(f"NHL Pinned Game Error: {e}")
            return []

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
            f1_game = self._fetch_f1(force=True)
            return [f1_game] if f1_game else []

        if league_key == 'nhl':
            pinned = self._pin_nhl_native_game(game_id, utc_offset)
            return pinned if pinned else []

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
                    games = self._extract_matches([mock_match], league_key, conf, huge_start, huge_end, huge_start, huge_end)
                    # _extract_matches fetches details (and injects events) for live games.
                    # For finished pinned games we still want to show the full scoreline events.
                    if games and games[0].get('state') == 'post':
                        goal_events, red_cards = self.parse_fotmob_goal_and_card_events(payload)
                        if goal_events or red_cards:
                            games[0]['situation']['goal_events'] = goal_events
                            games[0]['situation']['red_cards'] = red_cards
                    return games
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

                # ESPN summary gives bare {playerId: N} â€” look up names via athletes API
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
