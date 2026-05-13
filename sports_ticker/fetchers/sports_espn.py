from .. import core as _core
globals().update({k: v for k, v in vars(_core).items() if not k.startswith('__')})
from .test_mode import TestMode

class SportsEspnMixin:
    def fetch_single_league(self, league_key, config, conf, window_start_utc, window_end_utc, utc_offset, visible_start_utc, visible_end_utc):
        local_games = []

        if config.get('type') == 'leaderboard':
            return local_games

        try:
            curr_p = config.get('scoreboard_params', {}).copy()
            
            # CHANGE B: DATE OPTIMIZATION
            now_local = dt.now(timezone.utc).astimezone(timezone(timedelta(hours=utc_offset)))
            
            custom = TestMode.get_custom_date()
            if custom:
                curr_p['dates'] = custom
            else:
                # If before 3AM, fetch yesterday's games so finals persist
                if now_local.hour < 3:
                    fetch_date = now_local - timedelta(days=1)
                else:
                    fetch_date = now_local
                curr_p['dates'] = fetch_date.strftime("%Y%m%d")
            
            # --- FIX: CACHE BUSTER ---
            # Forces ESPN's CDN to return live data instead of a stale cached file
            curr_p['_'] = int(time.time() * 1000)
            
            r = self.session.get(f"{self.base_url}{config['path']}/scoreboard", params=curr_p, headers=HEADERS, timeout=TIMEOUTS['default'])
            data = r.json()
            
            events = data.get('events', [])
            if not events:
                leagues = data.get('leagues', [])
                if leagues and len(leagues) > 0:
                    events = leagues[0].get('events', [])
            
            for e in events:
                gid = str(e['id'])

                # CHANGE A: CACHE CHECK (with date guard)
                if gid in self.final_game_cache:
                    cached = self.final_game_cache[gid]
                    try:
                        cached_dt = parse_iso(cached.get('startTimeUTC', ''))
                        if visible_start_utc <= cached_dt <= visible_end_utc:
                            needs_update = False
                            if league_key == 'mlb' and (
                                cached.get('home_challenges') is None
                                or cached.get('away_challenges') is None
                                or cached.get('home_challenges_used') is None
                                or cached.get('away_challenges_used') is None
                            ):
                                needs_update = True
                            # Re-apply logo overrides so changes to LOGO_OVERRIDES take
                            # effect immediately without needing to evict the cache entry.
                            h_ab = cached.get('home_abbr', '')
                            a_ab = cached.get('away_abbr', '')
                            new_h_lg = self.get_corrected_logo(league_key, h_ab, cached.get('home_logo', ''))
                            new_a_lg = self.get_corrected_logo(league_key, a_ab, cached.get('away_logo', ''))
                            if new_h_lg != cached.get('home_logo') or new_a_lg != cached.get('away_logo'):
                                needs_update = True
                            if needs_update:
                                cached = dict(cached)
                                cached['home_logo'] = new_h_lg
                                cached['away_logo'] = new_a_lg
                                if league_key == 'mlb' and (
                                    cached.get('home_challenges') is None
                                    or cached.get('away_challenges') is None
                                    or cached.get('home_challenges_used') is None
                                    or cached.get('away_challenges_used') is None
                                ):
                                    self._mlb_apply_challenge_fields(
                                        cached,
                                        gid,
                                        h_ab,
                                        a_ab,
                                        cached.get('startTimeUTC') or e.get('date') or '',
                                    )
                                self.final_game_cache[gid] = cached
                            local_games.append(cached)
                            continue
                        else:
                            del self.final_game_cache[gid]
                    except:
                        del self.final_game_cache[gid]
                
                utc_str = e['date'].replace('Z', '')
                st = e.get('status', {})
                tp = st.get('type', {})
                gst = tp.get('state', 'pre')
                
                try:
                    game_dt = dt.fromisoformat(utc_str).replace(tzinfo=timezone.utc)
                    if gst != 'in' and gst != 'half':
                        if not (window_start_utc <= game_dt <= window_end_utc): continue
                    
                    if game_dt < visible_start_utc or game_dt >= visible_end_utc:
                          if gst not in ['in', 'half']:
                              continue
                except: continue

                comp = e['competitions'][0]
                h = comp['competitors'][0]
                a = comp['competitors'][1]
                h_ab = h['team'].get('abbreviation', 'UNK')
                a_ab = a['team'].get('abbreviation', 'UNK')
                
                if league_key == 'ncf_fbs' and h_ab not in FBS_TEAMS and a_ab not in FBS_TEAMS: continue
                if league_key == 'ncf_fcs' and h_ab not in FCS_TEAMS and a_ab not in FCS_TEAMS: continue

                # Seed Extraction Logic for March Madness
                h_seed = h.get('curatedRank', {}).get('current', '')
                a_seed = a.get('curatedRank', {}).get('current', '')
                if h_seed == 99: h_seed = ""
                if a_seed == 99: a_seed = ""

                h_lg = self.get_corrected_logo(league_key, h_ab, h['team'].get('logo',''))
                a_lg = self.get_corrected_logo(league_key, a_ab, a['team'].get('logo',''))
                
                h_clr = h['team'].get('color')
                a_clr = a['team'].get('color')
                h_alt = h['team'].get('alternateColor')
                a_alt = a['team'].get('alternateColor')

                # Force fallback to our hardcoded colors for missing ESPN data
                if not h_clr or h_clr == '000000' or not a_clr or a_clr == '000000':
                    h_info = self.lookup_team_info_from_cache(league_key, h_ab, logo=h_lg)
                    a_info = self.lookup_team_info_from_cache(league_key, a_ab, logo=a_lg)
                    h_clr = h_clr if h_clr and h_clr != '000000' else h_info.get('color', '000000')
                    a_clr = a_clr if a_clr and a_clr != '000000' else a_info.get('color', '000000')
                    h_alt = h_alt if h_alt else h_info.get('alt_color', 'ffffff')
                    a_alt = a_alt if a_alt else a_info.get('alt_color', 'ffffff')
                else:
                    h_clr = h_clr or '000000'
                    a_clr = a_clr or '000000'
                    h_alt = h_alt or 'ffffff'
                    a_alt = a_alt or 'ffffff'

                h_score = h.get('score','0')
                a_score = a.get('score','0')
                if 'soccer' in league_key: 
                    h_score = re.sub(r'\s*\(.*?\)', '', str(h_score))
                    a_score = re.sub(r'\s*\(.*?\)', '', str(a_score))

                s_disp = tp.get('shortDetail', 'TBD')
                p = st.get('period', 1)
                duration_est = self.calculate_game_timing(league_key, e['date'], p, s_disp)

                # --- FIX: ROBUST STATE INFERENCE ---
                # ESPN sometimes fails to switch 'state' to 'in', leaving it stuck as 'pre'.
                if gst == 'pre' and any(x in s_disp for x in ['1st', '2nd', '3rd', 'OT', 'Half', 'Qtr', 'Inning']):
                    if "FINAL" not in s_disp.upper():
                        gst = 'in'

                is_suspended = False
                susp_keywords = ["Suspended", "Postponed", "Canceled", "Delayed", "PPD"]
                for kw in susp_keywords:
                    if kw in s_disp:
                        is_suspended = True
                        break
                
                if not is_suspended:
                    if gst == 'pre':
                        try: s_disp = game_dt.astimezone(timezone(timedelta(hours=utc_offset))).strftime("%I:%M %p").lstrip('0')
                        except: pass
                    elif gst == 'in' or gst == 'half':
                        clk = st.get('displayClock', '0:00').replace("'", "")
                        
                        # --- FIX: EXTRACT CLOCK FROM DETAIL IF ESPN LEAVES IT BLANK ---
                        if (not clk or clk == '0:00') and ':' in s_disp:
                            m = re.search(r'(\d{1,2}:\d{2})', s_disp)
                            if m: clk = m.group(1)

                        if gst == 'half' or (p == 2 and clk == '0:00' and 'football' in config['path']): s_disp = "Halftime"
                        elif 'hockey' in config['path'] and clk == '0:00':
                                if p == 1: s_disp = "End 1st"
                                elif p == 2: s_disp = "End 2nd"
                                elif p == 3: s_disp = "End 3rd"
                                else: s_disp = "Intermission"
                        else:
                            if 'soccer' in config['path']:
                                in_extra = p >= 3 or 'ET' in tp.get('shortDetail', '')
                                if in_extra:
                                    if gst == 'half' or tp.get('shortDetail') in ['Halftime', 'HT', 'ET HT']: s_disp = "ET HT"
                                    else: s_disp = f"ET {clk}'"
                                else:
                                    s_disp = f"{clk}'"
                                    if gst == 'half' or tp.get('shortDetail') in ['Halftime', 'HT']: s_disp = "Half"
                            elif 'basketball' in config['path']:
                                if p > 4:
                                    s_disp = f"OT{p-4 if p-4>1 else ''} {clk}"
                                elif league_key == 'march_madness' and p <= 2:
                                    s_disp = f"H{p} {clk}"
                                else:
                                    s_disp = f"Q{p} {clk}"
                            elif 'football' in config['path']:
                                if p > 4: s_disp = f"OT{p-4 if p-4>1 else ''} {clk}"
                                else: s_disp = f"Q{p} {clk}"
                            elif 'hockey' in config['path']:
                                if p > 3: s_disp = f"OT{p-3 if p-3>1 else ''} {clk}"
                                else: s_disp = f"P{p} {clk}"
                            elif 'baseball' in config['path']:
                                short_detail = tp.get('shortDetail', s_disp)
                                s_disp = self._mlb_normalize_status_label(
                                    short_detail.replace(" - ", " ").replace("Inning", "In")
                                )
                            else: s_disp = f"P{p} {clk}"

                if is_suspended:
                    s_disp = s_disp.title()
                s_disp = s_disp.replace("Final", "FINAL").replace("/OT", " OT").replace("/SO", " S/O")
                s_disp = s_disp.replace("End of ", "End ").replace(" Quarter", "").replace(" Inning", "").replace(" Period", "")

                if "FINAL" in s_disp:
                    if league_key == 'nhl':
                        if "SO" in s_disp or "Shootout" in s_disp or p >= 5: s_disp = "FINAL S/O"
                        elif p >= 4 and "OT" not in s_disp: s_disp = f"FINAL OT{p-3 if p-3>1 else ''}"
                    elif league_key in ['nba', 'nfl', 'ncf_fbs', 'ncf_fcs'] and p > 4 and "OT" not in s_disp:
                         s_disp = f"FINAL OT{p-4 if p-4>1 else ''}"

                sit = comp.get('situation', {})
                shootout_data = None
                
                poss_raw = sit.get('possession')
                if poss_raw: self.possession_cache[e['id']] = poss_raw
                elif gst in ('in', 'half'):
                    _cached_poss = self.possession_cache.get(e['id'])
                    if _cached_poss is not None: poss_raw = _cached_poss
                
                if gst == 'pre' or gst == 'post' or gst == 'final' or s_disp == 'Halftime' or is_suspended:
                    poss_raw = None
                    self.possession_cache.pop(e['id'], None)

                poss_abbr = ""
                if str(poss_raw) == str(h['team'].get('id')): poss_abbr = h_ab
                elif str(poss_raw) == str(a['team'].get('id')): poss_abbr = a_ab
                
                down_text = sit.get('downDistanceText') or sit.get('shortDownDistanceText') or ''
                if s_disp == "Halftime": down_text = ''

                game_obj = {
                    'type': 'scoreboard', 'sport': league_key, 'id': gid, 'status': s_disp, 'state': gst, 'is_shown': True,
                    'home_abbr': h_ab, 'home_score': h_score, 'home_logo': h_lg,
                    'away_abbr': a_ab, 'away_score': a_score, 'away_logo': a_lg,
                    'home_color': f"#{h_clr}", 'home_alt_color': f"#{h_alt}",
                    'away_color': f"#{a_clr}", 'away_alt_color': f"#{a_alt}",
                    'startTimeUTC': e['date'],
                    'estimated_duration': duration_est,
                    
                    # MARCH MADNESS SPECIFIC FIELDS
                    'home_seed': str(h_seed),
                    'away_seed': str(a_seed),
                    
                    'situation': {
                        'possession': poss_abbr,
                        'isRedZone': sit.get('isRedZone', False),
                        'downDist': down_text,
                        'yardLine': sit.get('yardLine'),
                        'yardsToGo': sit.get('distance'),
                        'possessionTeam': sit.get('possessionText', ''),
                        'shootout': shootout_data,
                        'powerPlay': False,
                        'emptyNet': False
                    }
                }
                if league_key == 'mlb':
                    _bat_obj = sit.get('batter') or {}
                    _pit_obj = sit.get('pitcher') or {}
                    _bat_pid = self._mlb_player_id_from_obj(_bat_obj)
                    _pit_pid = self._mlb_player_id_from_obj(_pit_obj)
                    _batter_name = self._mlb_resolve_person_name(
                        _bat_obj,
                        _bat_pid,
                        sit.get('batterName') or sit.get('batter_name') or ''
                    )
                    _pitcher_name = self._mlb_resolve_person_name(
                        _pit_obj,
                        _pit_pid,
                        sit.get('pitcherName') or sit.get('pitcher_name') or ''
                    )
                    _mlb_stats = self._mlb_extract_situation_stats(sit, _bat_obj, _pit_obj)
                    _batter_avg = _mlb_stats.get('batter_avg', '')
                    _batter_h = _mlb_stats.get('batter_h', '')
                    _batter_ab = _mlb_stats.get('batter_ab', '')
                    _pitcher_pitches = _mlb_stats.get('pitcher_pitches', 0)
                    _last_pitch_speed = _mlb_stats.get('last_pitch_speed', 0)
                    _last_pitch_type = _mlb_stats.get('last_pitch_type', '')
                    _last_pitch_type_abbr = _mlb_stats.get('last_pitch_type_abbr', _last_pitch_type)
                    _last_pitch_type_full = _mlb_stats.get('last_pitch_type_full', '')
                    game_obj['situation'].update({
                        'balls': sit.get('balls', 0), 'strikes': sit.get('strikes', 0), 'outs': sit.get('outs', 0),
                        'onFirst': bool(sit.get('onFirst', False)), 'onSecond': bool(sit.get('onSecond', False)), 'onThird': bool(sit.get('onThird', False)),
                        'batter_name': _batter_name, 'batter_avg': _batter_avg,
                        'batter_h': _batter_h, 'batter_ab': _batter_ab,
                        'pitcher_name': _pitcher_name, 'pitcher_pitches': _pitcher_pitches,
                        'last_pitch_speed': _last_pitch_speed,
                        'last_pitch_type': _last_pitch_type,
                        'last_pitch_type_abbr': _last_pitch_type_abbr,
                        'last_pitch_type_full': _last_pitch_type_full,
                    })

                    # ESPN scoreboard often omits MLB batter/pitcher stat fields.
                    # Enrich from per-game summary for live/half games when these are blank.
                    if gst in ('in', 'half'):
                        need_enrich = (
                            not game_obj['situation'].get('batter_avg')
                            or not game_obj['situation'].get('batter_h')
                            or not game_obj['situation'].get('batter_ab')
                            or int(game_obj['situation'].get('pitcher_pitches', 0) or 0) == 0
                            or int(game_obj['situation'].get('last_pitch_speed', 0) or 0) == 0
                            or not game_obj['situation'].get('last_pitch_type')
                        )
                        if need_enrich:
                            _enriched = self._mlb_enrich_live_from_summary(gid, game_obj['situation'])
                            if _enriched:
                                game_obj['situation'].update(_enriched)

                    # Always include challenge fields for MLB (live/final/pinned UI consistency).
                    self._mlb_apply_challenge_fields(
                        game_obj,
                        gid,
                        h_ab,
                        a_ab,
                        e['date'],
                        h['team'].get('id'),
                        a['team'].get('id'),
                    )
                
                if is_suspended: game_obj['is_shown'] = False
                
                local_games.append(game_obj)
                
                # CHANGE C: SAVE FINAL GAMES TO CACHE
                if gst == 'post' and "FINAL" in s_disp:
                    self.final_game_cache[gid] = game_obj

        except Exception as e: print(f"Error fetching {league_key}: {e}")
        return local_games

