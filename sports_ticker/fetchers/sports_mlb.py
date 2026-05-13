from .. import core as _core
globals().update({k: v for k, v in vars(_core).items() if not k.startswith('__')})
from .test_mode import TestMode

class SportsMlbMixin:
    def _mlb_abbr_candidates(self, abbr):
        """Return MLB abbreviation aliases so ESPN and Stats API values can match."""
        val = str(abbr or '').strip().upper()
        if not val:
            return set()
        aliases = {
            'ARI': {'ARI', 'AZ'},
            'AZ': {'AZ', 'ARI'},
            'WSH': {'WSH', 'WAS'},
            'WAS': {'WAS', 'WSH'}}
        return aliases.get(val, {val})

    def _mlb_get_gamepk(self, espn_gid, home_abbr, away_abbr, date_utc_str, home_team_id=None, away_team_id=None):
        """Resolve MLB Stats API gamePk for an ESPN game, cached per espn_gid."""
        gid = str(espn_gid)
        if gid in self._mlb_gamepk_cache:
            return self._mlb_gamepk_cache[gid]

        home_abbr_set = self._mlb_abbr_candidates(home_abbr)
        away_abbr_set = self._mlb_abbr_candidates(away_abbr)
        home_id = str(home_team_id) if home_team_id is not None else ''
        away_id = str(away_team_id) if away_team_id is not None else ''
        target_dt = None
        try:
            target_dt = parse_iso(str(date_utc_str or ''))
        except Exception:
            target_dt = None

        # Build candidate dates: the UTC date and the day before (US evening games)
        dates_to_try = []
        try:
            date_part = str(date_utc_str or '')[:10]
            if date_part:
                from datetime import date as _date, timedelta as _td
                d = _date.fromisoformat(date_part)
                dates_to_try = [str(d), str(d - _td(days=1)), str(d + _td(days=1))]
        except Exception:
            pass

        candidates = []
        candidate_index = 0
        for date_str in dates_to_try:
            try:
                r = self.session.get(
                    'https://statsapi.mlb.com/api/v1/schedule',
                    params={'sportId': '1', 'date': date_str, 'hydrate': 'team'},
                    timeout=5,
                )
                if r.status_code != 200:
                    continue
                for date_obj in r.json().get('dates', []):
                    for game in date_obj.get('games', []):
                        pk = game.get('gamePk')
                        t = game.get('teams', {})
                        h_team = t.get('home', {}).get('team', {})
                        a_team = t.get('away', {}).get('team', {})

                        h = (h_team.get('abbreviation') or '').upper()
                        a = (a_team.get('abbreviation') or '').upper()
                        h_id = str(h_team.get('id') or '')
                        a_id = str(a_team.get('id') or '')

                        id_match = bool(home_id and away_id and h_id == home_id and a_id == away_id)
                        abbr_match = bool(h in home_abbr_set and a in away_abbr_set)

                        if id_match or abbr_match:
                            game_dt = None
                            try:
                                game_dt = parse_iso(str(game.get('gameDate') or ''))
                            except Exception:
                                game_dt = None
                            if target_dt and game_dt:
                                score = abs((game_dt - target_dt).total_seconds())
                            else:
                                score = float(candidate_index)
                            candidates.append((score, candidate_index, pk))
                            candidate_index += 1
            except Exception:
                pass

        if candidates:
            best_pk = sorted(candidates, key=lambda x: (x[0], x[1]))[0][2]
            self._mlb_gamepk_cache[gid] = best_pk
            return best_pk
        return None  # Don't cache None — retry on next poll until found

    def _mlb_get_challenges(self, gamepk, max_age=60):
        """Return (home_rem, home_used, away_rem, away_used) from MLB Stats API, cached 60s."""
        def _safe_int(v):
            try:
                return int(v)
            except (TypeError, ValueError):
                return None

        def _normalize_pair(rem_val, used_val, default_remaining=2):
            rem = _safe_int(rem_val)
            used = _safe_int(used_val)
            if rem is None and used is None:
                return default_remaining, 0
            if rem is None:
                rem = max(0, default_remaining - max(0, used or 0))
            if used is None:
                used = max(0, default_remaining - max(0, rem or 0))
            return max(0, rem), max(0, used)

        if not gamepk:
            return 2, 0, 2, 0
        pk_str = str(gamepk)
        now = time.time()
        cached = self._mlb_challenge_cache.get(pk_str)
        if cached and (now - cached.get('ts', 0) < max_age):
            h_rem, h_used = _normalize_pair(cached.get('home_rem'), cached.get('home_used'))
            a_rem, a_used = _normalize_pair(cached.get('away_rem'), cached.get('away_used'))
            return h_rem, h_used, a_rem, a_used
        try:
            r = self.session.get(
                f'https://statsapi.mlb.com/api/v1.1/game/{gamepk}/feed/live',
                timeout=5,
            )
            if r.status_code == 200:
                game_data = r.json().get('gameData', {})
                abs_ch = game_data.get('absChallenges', {})
                review = game_data.get('review', {})

                h_rem = h_used = a_rem = a_used = None

                # Prefer ABS challenge counts when present (teams start with 2).
                if isinstance(abs_ch, dict) and abs_ch.get('hasChallenges'):
                    h_abs = abs_ch.get('home', {})
                    a_abs = abs_ch.get('away', {})
                    h_rem, h_used = _normalize_pair(h_abs.get('remaining'), h_abs.get('usedFailed'))
                    a_rem, a_used = _normalize_pair(a_abs.get('remaining'), a_abs.get('usedFailed'))
                else:
                    h = review.get('home', {}) if isinstance(review, dict) else {}
                    a = review.get('away', {}) if isinstance(review, dict) else {}
                    h_rem, h_used = _normalize_pair(h.get('remaining'), h.get('used'))
                    a_rem, a_used = _normalize_pair(a.get('remaining'), a.get('used'))

                entry = {
                    'ts': now,
                    'home_rem': h_rem,
                    'home_used': h_used,
                    'away_rem': a_rem,
                    'away_used': a_used}
                self._mlb_challenge_cache[pk_str] = entry
                return entry['home_rem'], entry['home_used'], entry['away_rem'], entry['away_used']
        except Exception:
            pass

        # Fallback to stale cache entry when API call fails; otherwise 2 remaining, 0 used.
        if cached:
            h_rem, h_used = _normalize_pair(cached.get('home_rem'), cached.get('home_used'))
            a_rem, a_used = _normalize_pair(cached.get('away_rem'), cached.get('away_used'))
            return h_rem, h_used, a_rem, a_used
        return 2, 0, 2, 0

    def _mlb_apply_challenge_fields(self, game_obj, game_id, home_abbr, away_abbr, date_utc_str, home_team_id=None, away_team_id=None):
        """Attach MLB challenge fields to game object across all game states."""
        try:
            gamepk = self._mlb_get_gamepk(
                game_id,
                home_abbr,
                away_abbr,
                date_utc_str,
                home_team_id,
                away_team_id,
            )
            h_rem, h_used, a_rem, a_used = self._mlb_get_challenges(gamepk)
        except Exception:
            h_rem, h_used, a_rem, a_used = 2, 0, 2, 0

        game_obj['home_challenges'] = h_rem
        game_obj['home_challenges_used'] = h_used
        game_obj['away_challenges'] = a_rem
        game_obj['away_challenges_used'] = a_used

    def _mlb_player_last_name(self, player_id):
        """Return last name for an MLB player ID, using cache + ESPN athletes API."""
        if not player_id:
            return ''
        pid = str(player_id)
        if pid in self._mlb_player_cache:
            return self._mlb_player_cache[pid]
        # Try ESPN core API first, then site API fallback
        urls = [
            f"https://sports.core.api.espn.com/v2/sports/baseball/leagues/mlb/athletes/{pid}",
            f"{self.base_url}baseball/mlb/athletes/{pid}",
        ]
        for url in urls:
            try:
                r = self.session.get(url, headers=HEADERS, timeout=5)
                if r.status_code == 200:
                    ath = r.json()
                    full = (ath.get('shortName') or ath.get('displayName')
                            or ath.get('fullName') or ath.get('lastName', ''))
                    if '. ' in full:
                        full = full.split('. ', 1)[1]
                    name = full.upper()
                    self._mlb_player_cache[pid] = name
                    return name
            except Exception:
                pass
        self._mlb_player_cache[pid] = ''   # cache miss so we don't retry every tick
        return ''

    def _mlb_player_id_from_obj(self, person_obj):
        """Extract an MLB player ID from a batter/pitcher object, handling ESPN variants."""
        if not isinstance(person_obj, dict):
            return ''

        pid = person_obj.get('playerId') or person_obj.get('id')
        if pid:
            return str(pid)

        ath = person_obj.get('athlete')
        if isinstance(ath, dict):
            ath_id = ath.get('id') or ath.get('playerId')
            if ath_id:
                return str(ath_id)

        ref = person_obj.get('$ref')
        if isinstance(ref, str):
            m = re.search(r'/athletes/(\d+)', ref)
            if m:
                return m.group(1)

        return ''

    def _mlb_inline_name_from_obj(self, person_obj):
        """Read a usable display/last name directly from an ESPN person object."""
        if not isinstance(person_obj, dict):
            return ''

        for key in ('lastName', 'displayName', 'shortName', 'fullName', 'name'):
            val = person_obj.get(key)
            if val:
                name = str(val).strip()
                if '. ' in name:
                    name = name.split('. ', 1)[1]
                return name.upper()

        ath = person_obj.get('athlete')
        if isinstance(ath, dict):
            for key in ('lastName', 'displayName', 'shortName', 'fullName', 'name'):
                val = ath.get(key)
                if val:
                    name = str(val).strip()
                    if '. ' in name:
                        name = name.split('. ', 1)[1]
                    return name.upper()

        return ''

    def _mlb_resolve_person_name(self, person_obj, person_id=None, fallback_name=''):
        """Resolve batter/pitcher name from ID first, then fallback name/object text."""
        if person_id:
            by_id = self._mlb_player_last_name(person_id)
            if by_id:
                return by_id

        if fallback_name:
            return str(fallback_name).strip().upper()

        return self._mlb_inline_name_from_obj(person_obj)

    def _mlb_find_stat_value(self, data, wanted_keys):
        """Depth-first search for the first non-empty key in nested ESPN stat payloads."""
        if isinstance(data, dict):
            for k, v in data.items():
                if k in wanted_keys and v not in (None, ''):
                    return v
            for v in data.values():
                found = self._mlb_find_stat_value(v, wanted_keys)
                if found not in (None, ''):
                    return found
        elif isinstance(data, (list, tuple)):
            for item in data:
                found = self._mlb_find_stat_value(item, wanted_keys)
                if found not in (None, ''):
                    return found
        return None

    def _mlb_int(self, value, default=0):
        try:
            if value in (None, ''):
                return default
            return int(float(value))
        except Exception:
            return default

    def _mlb_normalize_pitch_type(self, pitch_type):
        """Return normalized (abbr, full_name) for MLB pitch types."""
        raw_abbr = ''
        raw_full = ''

        if isinstance(pitch_type, dict):
            raw_abbr = str(pitch_type.get('abbreviation') or '').strip().upper()
            raw_full = str(pitch_type.get('text') or pitch_type.get('displayValue') or '').strip()
        elif isinstance(pitch_type, str):
            p = pitch_type.strip()
            if p and len(p) <= 4 and ' ' not in p and '-' not in p:
                raw_abbr = p.upper()
            else:
                raw_full = p

        full_l = raw_full.lower()

        official_full = {
            'FF': 'Four-Seam Fastball',
            'FT': 'Two-Seam Fastball / Sinker',
            'FC': 'Cutter (Fastball-cutter)',
            'FA': 'Fastball (general)',
            'FS': 'Splitter / Split-fingered Fastball',
            'SF': 'Splitter / Split-fingered Fastball',
            'SI': 'Sinker',
            'SL': 'Slider',
            'CB': 'Curveball',
            'CU': 'Curveball',
            'KC': 'Knuckle Curve',
            'SC': 'Screwball',
            'ST': 'Sweeper',
            'CH': 'Changeup',
            'EP': 'Eephus',
            'FO': 'Forkball',
            'KN': 'Knuckleball',
            'UN': 'Unidentified / Unknown',
            'XX': 'Unidentified / Unknown',
            'PO': 'Pitchout',
            'GY': 'Gyroball',
            'NP': 'No Pitch'}

        # Pass through official abbreviations as-is.
        abbr = raw_abbr if raw_abbr in official_full else ''
        if not abbr:
            if 'four-seam' in full_l or '4-seam' in full_l:
                abbr = 'FF'
            elif 'two-seam' in full_l or '2-seam' in full_l:
                abbr = 'FT'
            elif 'sinker' in full_l:
                abbr = 'SI'
            elif 'cutter' in full_l:
                abbr = 'FC'
            elif 'slider' in full_l:
                abbr = 'SL'
            elif 'sweeper' in full_l:
                abbr = 'ST'
            elif 'knuckle curve' in full_l:
                abbr = 'KC'
            elif 'curve' in full_l:
                abbr = 'CB'
            elif 'screwball' in full_l:
                abbr = 'SC'
            elif 'change' in full_l:
                abbr = 'CH'
            elif 'eephus' in full_l:
                abbr = 'EP'
            elif 'forkball' in full_l:
                abbr = 'FO'
            elif 'split' in full_l:
                abbr = 'SF'
            elif 'knuckleball' in full_l:
                abbr = 'KN'
            elif 'pitchout' in full_l:
                abbr = 'PO'
            elif 'gyro' in full_l:
                abbr = 'GY'
            elif 'no pitch' in full_l:
                abbr = 'NP'
            elif 'unknown' in full_l or 'unidentified' in full_l:
                abbr = 'UN'
            elif 'fastball' in full_l:
                abbr = 'FA'

        full = official_full.get(abbr, '')
        if not full and raw_full:
            full = raw_full

        return abbr, full

    def _mlb_extract_situation_stats(self, sit, batter_obj=None, pitcher_obj=None, full_data=None):
        """Extract batter/pitcher live stats from diverse ESPN MLB situation payload shapes."""
        sit = sit or {}
        batter_obj = batter_obj or (sit.get('batter') or {})
        pitcher_obj = pitcher_obj or (sit.get('pitcher') or {})

        batter_avg = self._mlb_find_stat_value(
            [sit.get('batterStats'), sit, batter_obj],
            {'avg', 'average', 'battingAverage'}
        )
        batter_h = self._mlb_find_stat_value(
            [sit.get('batterStats'), sit, batter_obj],
            {'hits', 'h'}
        )
        batter_ab = self._mlb_find_stat_value(
            [sit.get('batterStats'), sit, batter_obj],
            {'atBats', 'ab'}
        )
        pitcher_pitches = self._mlb_find_stat_value(
            [sit.get('pitcherStats'), sit, pitcher_obj],
            {'pitchCount', 'numberOfPitches', 'pitches', 'totalPitches'}
        )

        lp = sit.get('lastPlay') or sit.get('lastPitch') or {}

        # ESPN often provides situation.lastPlay as only {'id': '...'} while
        # pitchVelocity/pitchType live in the matching object under data['plays'].
        if isinstance(lp, dict) and isinstance(full_data, dict):
            has_speed = self._mlb_find_stat_value(lp, {'pitchVelocity', 'velocity', 'speed'}) not in (None, '')
            pt_val = lp.get('pitchType')
            has_type = bool(pt_val)
            if not (has_speed and has_type):
                lp_id = str(lp.get('id') or '')
                plays = full_data.get('plays') if isinstance(full_data.get('plays'), list) else []
                if plays:
                    resolved = None
                    if lp_id:
                        for p in plays:
                            if str((p or {}).get('id', '')) == lp_id:
                                resolved = p
                                break
                    if resolved is None:
                        resolved = plays[-1]
                    if isinstance(resolved, dict):
                        lp = resolved

        last_pitch_speed = 0
        last_pitch_type_abbr = ''
        last_pitch_type_full = ''
        if isinstance(lp, dict):
            spd_val = (
                lp.get('pitchVelocity')
                or lp.get('velocity')
                or lp.get('speed')
                or self._mlb_find_stat_value(lp, {'pitchVelocity', 'velocity', 'speed'})
            )
            last_pitch_speed = self._mlb_int(spd_val, 0)
            pt = lp.get('pitchType')
            if not pt:
                pt = {
                    'abbreviation': lp.get('pitchTypeAbbreviation'),
                    'text': lp.get('pitchTypeText')
                }
            last_pitch_type_abbr, last_pitch_type_full = self._mlb_normalize_pitch_type(pt)

        return {
            'batter_avg': str(batter_avg).strip() if batter_avg not in (None, '') else '',
            'batter_h': str(batter_h).strip() if batter_h not in (None, '') else '',
            'batter_ab': str(batter_ab).strip() if batter_ab not in (None, '') else '',
            'pitcher_pitches': self._mlb_int(pitcher_pitches, 0),
            'last_pitch_speed': last_pitch_speed,
            # Keep legacy key for compatibility; value is normalized abbreviation.
            'last_pitch_type': last_pitch_type_abbr,
            'last_pitch_type_abbr': last_pitch_type_abbr,
            'last_pitch_type_full': last_pitch_type_full}

    def _mlb_extract_boxscore_stats(self, data, batter_id=None, pitcher_id=None):
        """Extract batter/pitcher line stats from ESPN MLB boxscore payload variants."""
        result = {
            'batter_avg': '',
            'batter_h': '',
            'batter_ab': '',
            'pitcher_pitches': 0}

        bid = str(batter_id or '')
        pid = str(pitcher_id or '')
        box = (data or {}).get('boxscore') or {}

        # Variant A: boxscore.players[*].statistics[*] with block.keys + athlete.stats[] values.
        for team in (box.get('players') or []):
            for block in (team.get('statistics') or []):
                keys = [str(k) for k in (block.get('keys') or [])]
                for ath in (block.get('athletes') or []):
                    aid = str((ath.get('athlete') or {}).get('id') or '')
                    vals = [str(v) if v is not None else '' for v in (ath.get('stats') or [])]
                    if not aid or not vals:
                        continue

                    by_key = {}
                    for i, k in enumerate(keys):
                        if i < len(vals):
                            by_key[k] = vals[i]

                    if aid == bid:
                        result['batter_avg'] = result['batter_avg'] or by_key.get('avg') or by_key.get('average') or by_key.get('battingAverage') or ''
                        result['batter_h'] = result['batter_h'] or by_key.get('hits') or ''
                        result['batter_ab'] = result['batter_ab'] or by_key.get('atBats') or ''

                        h_ab = by_key.get('hits-atBats') or by_key.get('h-ab') or ''
                        if h_ab and ('-' in h_ab or '/' in h_ab):
                            parts = re.split(r'[-/]', h_ab)
                            if len(parts) >= 2:
                                if not result['batter_h']:
                                    result['batter_h'] = str(parts[0]).strip()
                                if not result['batter_ab']:
                                    result['batter_ab'] = str(parts[1]).strip()

                    if aid == pid:
                        pc = by_key.get('pitches') or by_key.get('numberOfPitches') or by_key.get('pitchCount') or ''
                        if not pc:
                            pc_st = by_key.get('pitches-strikes') or by_key.get('pitchCount-strikes') or ''
                            if isinstance(pc_st, str) and '-' in pc_st:
                                pc = pc_st.split('-', 1)[0]
                        if pc not in (None, ''):
                            result['pitcher_pitches'] = self._mlb_int(pc, result['pitcher_pitches'])

        # Variant B: older boxscore.teams[*].statistics[*].athletes with named stat rows.
        for team_box in (box.get('teams') or []):
            for stat_block in (team_box.get('statistics') or []):
                for ath in (stat_block.get('athletes') or []):
                    aid = str((ath.get('athlete') or {}).get('id') or '')
                    if not aid:
                        continue
                    stat_map = {}
                    for s in (ath.get('stats') or []):
                        k = s.get('name')
                        if not k:
                            continue
                        stat_map[k] = s.get('displayValue') or s.get('value') or ''

                    if aid == pid:
                        pc = stat_map.get('pitchCount') or stat_map.get('numberOfPitches')
                        if pc not in (None, ''):
                            result['pitcher_pitches'] = self._mlb_int(pc, result['pitcher_pitches'])
                    if aid == bid:
                        result['batter_avg'] = stat_map.get('avg') or result['batter_avg']
                        result['batter_h'] = stat_map.get('hits') or result['batter_h']
                        result['batter_ab'] = stat_map.get('atBats') or result['batter_ab']

        return result

    def _mlb_get_summary(self, game_id, max_age=12):
        """Return cached MLB summary payload for a game, refreshing every max_age seconds."""
        gid = str(game_id)
        now = time.time()
        cached = self._mlb_summary_cache.get(gid)
        if cached and (now - cached.get('ts', 0) < max_age):
            return cached.get('data')

        try:
            url = f"{self.base_url}baseball/mlb/summary"
            r = self.session.get(url, params={'event': gid}, headers=HEADERS, timeout=TIMEOUTS['default'])
            if r.status_code == 200:
                data = r.json()
                self._mlb_summary_cache[gid] = {'ts': now, 'data': data}
                return data
        except Exception:
            pass
        return None

    def _mlb_enrich_live_from_summary(self, game_id, current_sit):
        """Fill missing live MLB fields from the per-game summary endpoint."""
        data = self._mlb_get_summary(game_id)
        if not data:
            return {}

        current_sit = current_sit or {}
        comp = (data.get('header', {}).get('competitions') or [{}])[0]
        bsit = data.get('situation') or comp.get('situation') or {}

        bat_obj = bsit.get('batter') or {}
        pit_obj = bsit.get('pitcher') or {}
        bat_pid = self._mlb_player_id_from_obj(bat_obj)
        pit_pid = self._mlb_player_id_from_obj(pit_obj)

        batter_name = self._mlb_resolve_person_name(
            bat_obj,
            bat_pid,
            bsit.get('batterName') or bsit.get('batter_name') or current_sit.get('batter_name', '')
        )
        pitcher_name = self._mlb_resolve_person_name(
            pit_obj,
            pit_pid,
            bsit.get('pitcherName') or bsit.get('pitcher_name') or current_sit.get('pitcher_name', '')
        )

        stats = self._mlb_extract_situation_stats(bsit, bat_obj, pit_obj, data)
        batter_avg = stats.get('batter_avg', '') or current_sit.get('batter_avg', '')
        batter_h = stats.get('batter_h', '') or current_sit.get('batter_h', '')
        batter_ab = stats.get('batter_ab', '') or current_sit.get('batter_ab', '')
        pitcher_pitches = stats.get('pitcher_pitches', 0) or current_sit.get('pitcher_pitches', 0)
        last_pitch_speed = stats.get('last_pitch_speed', 0) or current_sit.get('last_pitch_speed', 0)
        last_pitch_type_abbr = (
            stats.get('last_pitch_type_abbr', '')
            or stats.get('last_pitch_type', '')
            or current_sit.get('last_pitch_type_abbr', '')
            or current_sit.get('last_pitch_type', '')
        )
        last_pitch_type_full = stats.get('last_pitch_type_full', '') or current_sit.get('last_pitch_type_full', '')

        # Secondary stats source: boxscore athletes (supports ESPN players+keys/stats shape).
        box_stats = self._mlb_extract_boxscore_stats(data, bat_pid, pit_pid)
        batter_avg = box_stats.get('batter_avg') or batter_avg
        batter_h = box_stats.get('batter_h') or batter_h
        batter_ab = box_stats.get('batter_ab') or batter_ab
        pitcher_pitches = box_stats.get('pitcher_pitches') or pitcher_pitches

        return {
            'balls': bsit.get('balls', current_sit.get('balls', 0)),
            'strikes': bsit.get('strikes', current_sit.get('strikes', 0)),
            'outs': bsit.get('outs', current_sit.get('outs', 0)),
            'onFirst': bool(bsit.get('onFirst', current_sit.get('onFirst', False))),
            'onSecond': bool(bsit.get('onSecond', current_sit.get('onSecond', False))),
            'onThird': bool(bsit.get('onThird', current_sit.get('onThird', False))),
            'batter_name': batter_name or current_sit.get('batter_name', ''),
            'batter_avg': str(batter_avg).strip() if batter_avg not in (None, '') else '',
            'batter_h': str(batter_h).strip() if batter_h not in (None, '') else '',
            'batter_ab': str(batter_ab).strip() if batter_ab not in (None, '') else '',
            'pitcher_name': pitcher_name or current_sit.get('pitcher_name', ''),
            'pitcher_pitches': self._mlb_int(pitcher_pitches, 0),
            'last_pitch_speed': self._mlb_int(last_pitch_speed, 0),
            'last_pitch_type': str(last_pitch_type_abbr or '').strip(),
            'last_pitch_type_abbr': str(last_pitch_type_abbr or '').strip(),
            'last_pitch_type_full': str(last_pitch_type_full or '').strip()}

