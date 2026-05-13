from .. import core as _core
globals().update({k: v for k, v in vars(_core).items() if not k.startswith('__')})
from .test_mode import TestMode

class SportsNhlMixin:
    def _fetch_nhl_native(self, conf, window_start_utc, window_end_utc, visible_start_utc, visible_end_utc):
        games_found = []
        is_nhl = conf['active_sports'].get('nhl', False)
        if not is_nhl: return []
        
        processed_ids = set()
        try:
            r = self.session.get("https://api-web.nhle.com/v1/schedule/now", headers=HEADERS, timeout=TIMEOUTS['stock'])
            if r.status_code != 200: return []

            landing_futures = {}
            _local_tz = timezone(timedelta(hours=conf.get('utc_offset', -5)))

            for d in r.json().get('gameWeek', []):
                for g in d.get('games', []):
                    try:
                        # Filter out non-NHL events (e.g. 9 = Olympics, 6 = World Cup)
                        # Keep 1 (Preseason), 2 (Regular Season), 3 (Playoffs), 4 (All-Star)
                        if int(g.get('gameType', 2)) not in [1, 2, 3, 4]:
                            continue

                        g_utc = g.get('startTimeUTC')
                        if not g_utc: continue
                        g_dt = parse_iso(g_utc)
                        if not (window_start_utc <= g_dt <= window_end_utc): continue
                    except: continue

                    gid = g['id']
                    if gid in processed_ids: continue
                    processed_ids.add(gid)
                    
                    st = g.get('gameState', 'OFF')
                    if st in ['LIVE', 'CRIT', 'FINAL', 'OFF']:
                        landing_futures[gid] = self.executor.submit(self._fetch_nhl_landing, gid)
            
            processed_ids.clear() 
            for d in r.json().get('gameWeek', []):
                for g in d.get('games', []):
                    try:
                        # Filter out non-NHL events here as well
                        if int(g.get('gameType', 2)) not in [1, 2, 3, 4]:
                            continue

                        g_utc = g.get('startTimeUTC')
                        if not g_utc: continue
                        g_dt = parse_iso(g_utc)

                        if g_dt < visible_start_utc or g_dt >= visible_end_utc:
                            st = g.get('gameState', 'OFF')
                            if st not in ['LIVE', 'CRIT']:
                                continue
                    except: continue

                    gid = g['id']
                    if gid in processed_ids: continue
                    processed_ids.add(gid)

                    st = g.get('gameState', 'OFF')
                    map_st = 'in' if st in ['LIVE', 'CRIT'] else ('pre' if st in ['PRE', 'FUT'] else 'post')

                    # === FIX: NORMALIZE ABBREVIATIONS FOR MY TEAMS COMPATIBILITY ===
                    raw_h = g['homeTeam']['abbrev']; raw_a = g['awayTeam']['abbrev']
                    h_ab = ABBR_MAPPING.get(raw_h, raw_h) # Translates LAK -> LA
                    a_ab = ABBR_MAPPING.get(raw_a, raw_a) # Translates TBL -> TB
                    # === FIX END ===

                    h_sc = str(g['homeTeam'].get('score', 0)); a_sc = str(g['awayTeam'].get('score', 0))
                    
                    h_lg = self.get_corrected_logo('nhl', h_ab, f"https://a.espncdn.com/i/teamlogos/nhl/500/{h_ab.lower()}.png")
                    a_lg = self.get_corrected_logo('nhl', a_ab, f"https://a.espncdn.com/i/teamlogos/nhl/500/{a_ab.lower()}.png")
                    h_info = self.lookup_team_info_from_cache('nhl', h_ab, logo=h_lg)
                    a_info = self.lookup_team_info_from_cache('nhl', a_ab, logo=a_lg)
                    
                    if st in ['SUSP', 'SUSPENDED', 'PPD', 'POSTPONED']:
                        map_st = 'post'

                    disp = "Scheduled"; pp = False; poss = ""; en = False; shootout_data = None 
                    dur = self.calculate_game_timing('nhl', g_utc, 1, st)
                    
                    g_local = g_dt.astimezone(_local_tz)

                    if st in ['PRE', 'FUT']:
                           try: disp = g_local.strftime("%I:%M %p").lstrip('0')
                           except: pass
                    elif st in ['FINAL', 'OFF']:
                          disp = "FINAL"
                          pd = g.get('periodDescriptor', {})
                          if pd.get('periodType', '') == 'SHOOTOUT' or pd.get('number', 0) >= 5: disp = "FINAL S/O"
                          elif pd.get('periodType', '') == 'OT' or pd.get('number', 0) == 4: disp = "FINAL OT"

                    if gid in landing_futures:
                        try:
                            d2 = landing_futures[gid].result()
                            if d2:
                                h_sc = str(d2['homeTeam'].get('score', h_sc)); a_sc = str(d2['awayTeam'].get('score', a_sc))
                                pd = d2.get('periodDescriptor', {})
                                clk = d2.get('clock', {}); time_rem = clk.get('timeRemaining', '00:00')
                                p_type = pd.get('periodType', '')
                                
                                if st in ['FINAL', 'OFF']:
                                    p_num_final = pd.get('number', 3)
                                    if p_type == 'SHOOTOUT' or p_num_final >= 5: disp = "FINAL S/O"
                                    elif p_type == 'OT' or p_num_final == 4: disp = "FINAL OT"
                                
                                p_num = pd.get('number', 1)

                                if p_type == 'SHOOTOUT' or p_num >= 5:
                                    if map_st == 'in': disp = "S/O"
                                    shootout_data = self.fetch_shootout_details(gid, 0, 0)
                                else:
                                    if map_st == 'in':
                                        if clk.get('inIntermission', False) or time_rem == "00:00":
                                            if p_num == 1: disp = "End 1st"
                                            elif p_num == 2: disp = "End 2nd"
                                            elif p_num == 3: disp = "End 3rd"
                                            else: disp = "End OT"
                                        else:
                                            if p_num == 4:
                                                p_lbl = "OT"
                                            else:
                                                p_lbl = f"P{p_num}"
                                            
                                            disp = f"{p_lbl} {time_rem}"
                                    
                                sit_obj = d2.get('situation', {})
                                if sit_obj:
                                    sit = sit_obj.get('situationCode', '1551')
                                    ag = int(sit[0]); as_ = int(sit[1]); hs = int(sit[2]); hg = int(sit[3])
                                    if as_ > hs: pp=True; poss=a_ab
                                    elif hs > as_: pp=True; poss=h_ab
                                    en = (ag==0 or hg==0)
                        except: pass 

                    if "FINAL" in disp:
                        shootout_data = None

                    games_found.append({
                        'type': 'scoreboard',
                        'sport': 'nhl', 'id': str(gid), 'status': disp, 'state': map_st, 'is_shown': True,
                        'home_abbr': h_ab, 'home_score': h_sc, 'home_logo': h_lg, 'home_id': h_ab,
                        'away_abbr': a_ab, 'away_score': a_sc, 'away_logo': a_lg, 'away_id': a_ab,
                        'home_color': f"#{h_info['color']}", 'home_alt_color': f"#{h_info['alt_color']}",
                        'away_color': f"#{a_info['color']}", 'away_alt_color': f"#{a_info['alt_color']}",
                        'startTimeUTC': g_utc,
                        'estimated_duration': dur,
                        'situation': { 'powerPlay': pp, 'possession': poss, 'emptyNet': en, 'shootout': shootout_data }
                    })
            return games_found
        except: return []

    def parse_side_list(self, side_list):
        seq = []
        for attempt in side_list or []:
            if not isinstance(attempt, dict):
                seq.append("pending")
                continue
            result = (attempt.get("result") or attempt.get("outcome") or "").lower()
            if result in {"goal", "scored", "score", "converted"}:
                seq.append("goal")
                continue
            if result in {"miss", "missed", "failed", "saved", "fail"}:
                seq.append("miss")
                continue
            if attempt.get("scored") is True:
                seq.append("goal")
                continue
            if attempt.get("scored") is False:
                seq.append("miss")
                continue
            seq.append("pending")
        return seq

    def parse_shootout(self, raw, home_id=None, away_id=None, general_home=None, general_away=None):
        if not raw:
            return [], [], None, None

        pen_home_score = raw.get("homeScore") if isinstance(raw, dict) else None
        pen_away_score = raw.get("awayScore") if isinstance(raw, dict) else None

        for hk, ak in (("home", "away"), ("homeTeam", "awayTeam"), ("homePenalties", "awayPenalties")):
            if hk in raw or ak in raw:
                return (
                    self.parse_side_list(raw.get(hk) or []),
                    self.parse_side_list(raw.get(ak) or []),
                    pen_home_score,
                    pen_away_score,
                )

        seq = raw.get("sequence") if isinstance(raw, dict) else raw if isinstance(raw, list) else []
        home_seq, away_seq = [], []
        for attempt in seq or []:
            if not isinstance(attempt, dict):
                continue
            team_id = attempt.get("teamId") or attempt.get("team")
            side = attempt.get("side") or attempt.get("teamSide")
            is_home = False
            if team_id is not None:
                is_home = team_id in {home_id, general_home} if home_id or general_home else False
                if not is_home:
                    is_home = team_id not in {away_id, general_away} if (home_id or general_home) else False
            elif isinstance(side, str):
                is_home = side.lower() in {"home", "h"}

            parsed = self.parse_side_list([attempt])[0]
            (home_seq if is_home else away_seq).append(parsed)

        return home_seq, away_seq, pen_home_score, pen_away_score

    def parse_shootout_events(self, events_container, home_id=None, away_id=None, general_home=None, general_away=None):
        if not isinstance(events_container, dict):
            return [], [], None, None

        pen_events = events_container.get("penaltyShootoutEvents") or []
        home_seq, away_seq = [], []
        pen_home_score = pen_away_score = None

        def classify(event):
            text = (event.get("result") or event.get("outcome") or event.get("type") or "").lower()
            if "goal" in text: return "goal"
            if "miss" in text or "fail" in text or "save" in text: return "miss"
            if event.get("scored") is True: return "goal"
            if event.get("scored") is False: return "miss"
            return "pending"

        for ev in pen_events:
            if not isinstance(ev, dict): continue

            score = ev.get("penShootoutScore")
            if isinstance(score, (list, tuple)) and len(score) >= 2:
                pen_home_score, pen_away_score = score[0], score[1]

            is_home = None
            if ev.get("isHome") is not None:
                is_home = bool(ev.get("isHome"))
            if is_home is None:
                team_id = ev.get("teamId") or (ev.get("shotmapEvent") or {}).get("teamId")
                if team_id is not None:
                    if home_id or general_home:
                        is_home = team_id in {home_id, general_home}
                    elif away_id or general_away:
                        is_home = team_id not in {away_id, general_away}
            if is_home is None:
                side = ev.get("side")
                if isinstance(side, str):
                    is_home = side.lower().startswith("h")
            if is_home is None:
                is_home = True

            outcome = classify(ev)
            (home_seq if is_home else away_seq).append(outcome)

        return home_seq, away_seq, pen_home_score, pen_away_score

