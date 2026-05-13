from .. import core as _core
globals().update({k: v for k, v in vars(_core).items() if not k.startswith('__')})
from .test_mode import TestMode

class SportsGeneralMixin:
    def _mlb_normalize_status_label(self, status_text):
        text = str(status_text or '').strip()
        lower = text.lower()
        if not text:
            return text
        if any(word in lower for word in ('postponed', 'canceled', 'cancelled', 'suspended', 'ppd')):
            return text
        if 'delay' in lower or 'rain' in lower or 'weather' in lower:
            return 'rain delay'
        return text

    def _calculate_next_update(self, games):
        """Returns TIMESTAMP when we should next fetch this league"""
        if not games: return 0 
        now = time.time()
        earliest_start = None
        
        for g in games:
            # If ACTIVE (In/Half/Crit) -> Fetch Immediately (0)
            if g['state'] in ['in', 'half', 'crit']: return 0
            
            # If SCHEDULED -> Track earliest start time
            if g['state'] == 'pre':
                try:
                    ts = parse_iso(g['startTimeUTC']).timestamp()
                    if earliest_start is None or ts < earliest_start: earliest_start = ts
                except: pass
        
        # If games are in future, sleep until 60s before start
        if earliest_start:
            wake_time = earliest_start - 60 
            if wake_time > now: return wake_time
            return 0
            
        # If all FINAL -> Sleep 60s
        return now + 60

    def get_corrected_logo(self, league_key, abbr, default_logo):
        return LOGO_OVERRIDES.get(f"{league_key.upper()}:{abbr}", default_logo)

    def _extract_color_from_logo(self, logo_url):
        """Download the team logo and return the dominant non-white, non-transparent color as a hex string, or None on failure."""
        if not logo_url or not PIL_AVAILABLE:
            return None
        try:
            r = self.session.get(logo_url, timeout=5)
            r.raise_for_status()
            img = _PIL_Image.open(io.BytesIO(r.content)).convert('RGBA')
            img = img.resize((64, 64))
            freq = {}
            for px in img.getdata():
                r_val, g_val, b_val, a_val = px
                if a_val < 128:
                    continue
                brightness = (r_val + g_val + b_val) / 3
                if brightness > 240:
                    continue
                # Quantize to reduce noise
                key = (r_val // 32 * 32, g_val // 32 * 32, b_val // 32 * 32)
                freq[key] = freq.get(key, 0) + 1
            if not freq:
                return None
            best = max(freq, key=freq.get)
            return '{:02X}{:02X}{:02X}'.format(*best)
        except Exception:
            return None

    def lookup_team_info_from_cache(self, league, abbr, name=None, logo=None):
        search_abbr = ABBR_MAPPING.get(abbr, abbr)

        if 'soccer' in league:
            name_check = name.lower() if name else ""
            abbr_check = search_abbr.lower()
            for k, v in SOCCER_COLOR_FALLBACK.items():
                if k in name_check or k == abbr_check:
                    return {'color': v, 'alt_color': '444444'}

        try:
            # O(1) abbr lookup via pre-built index
            league_idx = self._teams_abbr_index.get(league, {})
            t = league_idx.get(search_abbr)
            if t:
                return {'color': t.get('color', '000000'), 'alt_color': t.get('alt_color', '444444')}

            # Fallback: name-based scan (rare — only for teams without standard abbr)
            if name:
                name_lower = name.lower()
                with data_lock:
                    teams = state['all_teams_data'].get(league, [])
                for t in teams:
                    t_name = t.get('name', '').lower()
                    t_short = t.get('shortName', '').lower()
                    if (name_lower in t_name) or (t_name in name_lower) or \
                       (name_lower in t_short) or (t_short in name_lower):
                        return {'color': t.get('color', '000000'), 'alt_color': t.get('alt_color', '444444')}
        except: pass
        logo_color = self._extract_color_from_logo(logo)
        return {'color': logo_color or '000000', 'alt_color': '444444'}

    def calculate_game_timing(self, sport, start_utc, period, status_detail):
        duration = SPORT_DURATIONS.get(sport, 180) 
        ot_padding = 0
        if 'OT' in str(status_detail) or 'S/O' in str(status_detail):
            if sport in ['nba', 'nfl', 'ncf_fbs', 'ncf_fcs']:
                ot_count = 1
                if '2OT' in status_detail: ot_count = 2
                elif '3OT' in status_detail: ot_count = 3
                ot_padding = ot_count * 20
            elif sport == 'nhl':
                ot_padding = 20
            elif sport == 'mlb' and period > 9:
                ot_padding = (period - 9) * 20
        return duration + ot_padding

    def _fetch_simple_league(self, league_key, catalog, seen_ids):
        config = self.leagues[league_key]
        if 'team_params' not in config: return
        try:
            r = self.session.get(f"{self.base_url}{config['path']}/teams", params=config['team_params'], headers=HEADERS, timeout=TIMEOUTS['slow'])
            data = r.json()
            if 'sports' in data:
                for sport in data['sports']:
                    for league in sport['leagues']:
                        for item in league.get('teams', []):
                            abbr = item['team'].get('abbreviation', 'unk')
                            scoped_id = f"{league_key}:{abbr}"
                            if scoped_id in seen_ids[league_key]:
                                continue
                            seen_ids[league_key].add(scoped_id)

                            clr = item['team'].get('color', '000000')
                            alt = item['team'].get('alternateColor', '444444')
                            logo = item['team'].get('logos', [{}])[0].get('href', '')
                            logo = self.get_corrected_logo(league_key, abbr, logo)
                            name = item['team'].get('displayName', '')
                            short_name = item['team'].get('shortDisplayName', '')

                            catalog[league_key].append({
                                'abbr': abbr,
                                'id': scoped_id,
                                'logo': logo,
                                'color': clr,
                                'alt_color': alt,
                                'name': name,
                                'shortName': short_name
                            })
        except Exception as e: print(f"Error fetching teams for {league_key}: {e}")

    def fetch_all_teams(self):
        try:
            teams_catalog = {k: [] for k in self.leagues.keys()}
            # Per-league seen-ID sets for O(1) deduplication (replaces any() linear scan)
            seen_ids: dict = {k: set() for k in self.leagues.keys()}

            # NCAA college teams — O(1) dedup via seen_ids sets
            ncf_seen = {'ncf_fbs': set(), 'ncf_fcs': set()}
            url = f"{self.base_url}football/college-football/teams"
            r = self.session.get(url, params={'limit': 1000, 'groups': '80,81'}, headers=HEADERS, timeout=TIMEOUTS['slow'])
            data = r.json()
            if 'sports' in data:
                for sport in data['sports']:
                    for league in sport['leagues']:
                        for item in league.get('teams', []):
                            t_abbr = item['team'].get('abbreviation', 'unk')
                            t_clr = item['team'].get('color', '000000')
                            t_alt = item['team'].get('alternateColor', '444444')
                            logos = item['team'].get('logos', [])
                            t_logo = logos[0].get('href', '') if logos else ''

                            if t_abbr in FBS_TEAMS:
                                scoped_id = f"ncf_fbs:{t_abbr}"
                                if scoped_id not in ncf_seen['ncf_fbs']:
                                    ncf_seen['ncf_fbs'].add(scoped_id)
                                    t_logo = self.get_corrected_logo('ncf_fbs', t_abbr, t_logo)
                                    teams_catalog['ncf_fbs'].append({'abbr': t_abbr, 'id': scoped_id, 'logo': t_logo, 'color': t_clr, 'alt_color': t_alt})
                            elif t_abbr in FCS_TEAMS:
                                scoped_id = f"ncf_fcs:{t_abbr}"
                                if scoped_id not in ncf_seen['ncf_fcs']:
                                    ncf_seen['ncf_fcs'].add(scoped_id)
                                    t_logo = self.get_corrected_logo('ncf_fcs', t_abbr, t_logo)
                                    teams_catalog['ncf_fcs'].append({'abbr': t_abbr, 'id': scoped_id, 'logo': t_logo, 'color': t_clr, 'alt_color': t_alt})

            # Fetch teams for all leagues except the NCAA ones handled above.
            # _fetch_simple_league silently skips entries without 'team_params' (e.g. golf).
            _ncaa_handled = {'ncf_fbs', 'ncf_fcs'}
            futures = [
                self.executor.submit(self._fetch_simple_league, lk, teams_catalog, seen_ids)
                for lk in self.leagues
                if lk not in _ncaa_handled
            ]
            concurrent.futures.wait(futures)

            # Build abbr-keyed index for O(1) lookup in lookup_team_info_from_cache
            new_index = {
                league: {entry['abbr']: entry for entry in entries}
                for league, entries in teams_catalog.items()
            }

            with data_lock:
                state['all_teams_data'] = teams_catalog
            self._teams_abbr_index = new_index
        except Exception as e: print(f"Global Team Fetch Error: {e}")

    def check_shootout(self, game, summary=None):
        if summary:
            if summary.get("hasShootout"): return True
            if summary.get("shootoutDetails"): return True
            
            so_section = (
                summary.get("shootout") or summary.get("Shootout") or 
                summary.get("shootOut") or summary.get("SO")
            )
            if so_section: return True
            
            summary_status = str(
                summary.get("gameStatusString") or summary.get("gameStatus") or 
                summary.get("status") or ""
            ).lower()
            if "so" in summary_status or "shootout" in summary_status or "s/o" in summary_status:
                return True
        
        period = str(game.get("Period", "") or game.get("period", ""))
        period_name = str(game.get("PeriodNameShort", "") or game.get("periodNameShort", "")).upper()
        
        if period == "5": return True
        if period_name == "SO" or "SHOOTOUT" in period_name: return True
        
        status = str(
            game.get("GameStatusString") or game.get("game_status") or 
            game.get("GameStatusStringLong") or ""
        ).lower()
        
        if "so" in status or "shootout" in status or "s/o" in status:
            return True
            
        return False

    def fetch_shootout_details(self, game_id, away_id, home_id):
        try:
            url = f"https://api-web.nhle.com/v1/gamecenter/{game_id}/play-by-play"
            r = self.session.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=TIMEOUTS['quick'])
            if r.status_code != 200: return None
            data = r.json(); plays = data.get("plays", [])
            native_away = data.get("awayTeam", {}).get("id")
            native_home = data.get("homeTeam", {}).get("id")
            results = {'away': [], 'home': []}
            for play in plays:
                if play.get("periodDescriptor", {}).get("periodType") != "SO": continue
                type_key = play.get("typeDescKey")
                if type_key not in {"goal", "shot-on-goal", "missed-shot"}: continue
                details = play.get("details", {})
                team_id = details.get("eventOwnerTeamId")
                res_code = "goal" if type_key == "goal" else "miss"
                if team_id == native_away: results['away'].append(res_code)
                elif team_id == native_home: results['home'].append(res_code)
            return results
        except: return None

    def _fetch_nhl_landing(self, gid):
        try:
            r = self.session.get(f"https://api-web.nhle.com/v1/gamecenter/{gid}/landing", headers=HEADERS, timeout=TIMEOUTS['quick'])
            if r.status_code == 200: return r.json()
        except: pass
        return None

