import time
import json
import re
import concurrent.futures
from datetime import datetime as dt, timezone, timedelta
import requests

from modules.config import (
    LEAGUE_OPTIONS, WORKER_THREAD_COUNT, API_TIMEOUT, HEADERS, FOTMOB_LEAGUE_MAP,
    AHL_API_KEYS, TZ_OFFSETS, AHL_TEAMS, FBS_TEAMS, FCS_TEAMS, OLYMPIC_HOCKEY_TEAMS,
    SOCCER_ABBR_OVERRIDES, LOGO_OVERRIDES, ABBR_MAPPING, SOCCER_COLOR_FALLBACK, SPORT_DURATIONS
)
from modules.state import state, data_lock
from modules.utils import build_pooled_session
from modules.fetchers.weather import WeatherFetcher
from modules.fetchers.stocks import StockFetcher

def validate_logo_url(base_id):
    url_90 = f"https://assets.leaguestat.com/ahl/logos/50x50/{base_id}_90.png"
    try:
        r = requests.head(url_90, timeout=1)
        if r.status_code == 200:
            return url_90
    except: pass
    return f"https://assets.leaguestat.com/ahl/logos/50x50/{base_id}.png"

class SportsFetcher:
    def __init__(self, initial_city, initial_lat, initial_lon):
        self.weather = WeatherFetcher(initial_lat=initial_lat, initial_lon=initial_lon, city=initial_city)
        self.stocks = StockFetcher()
        self.possession_cache = {}
        self.base_url = 'http://site.api.espn.com/apis/site/v2/sports/'

        # CHANGE 1: Reduce Pool Size to 15 (Save RAM)
        self.session = build_pooled_session(pool_size=15)

        # CHANGE 2: Use Configured Thread Count (10)
        self.executor = concurrent.futures.ThreadPoolExecutor(max_workers=WORKER_THREAD_COUNT)

        # CHANGE 3: Add New Caches for Smart Sleep
        self.history_buffer = []
        self.final_game_cache = {}      # Stores finished games so we don't re-fetch
        self.league_next_update = {}    # Stores "Wake Up" time for sleeping leagues
        self.league_last_data = {}      # Stores last data for sleeping leagues

        self.consecutive_empty_fetches = 0
        self.ahl_cached_key = None
        self.ahl_key_expiry = 0

        self.leagues = {
            item['id']: item['fetch']
            for item in LEAGUE_OPTIONS
            if item['type'] == 'sport' and 'fetch' in item
        }

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
                    ts = dt.fromisoformat(g['startTimeUTC'].replace('Z', '+00:00')).timestamp()
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

    def lookup_team_info_from_cache(self, league, abbr, name=None):
        search_abbr = ABBR_MAPPING.get(abbr, abbr)

        if 'soccer' in league:
            name_check = name.lower() if name else ""
            abbr_check = search_abbr.lower()
            for k, v in SOCCER_COLOR_FALLBACK.items():
                if k in name_check or k == abbr_check:
                        return {'color': v, 'alt_color': '444444'}

        try:
            with data_lock:
                teams = state['all_teams_data'].get(league, [])

                for t in teams:
                    if t['abbr'] == search_abbr:
                        return {'color': t.get('color', '000000'), 'alt_color': t.get('alt_color', '444444')}

                if name:
                    name_lower = name.lower()
                    for t in teams:
                        t_name = t.get('name', '').lower()
                        t_short = t.get('shortName', '').lower()

                        if (name_lower in t_name) or (t_name in name_lower) or \
                           (name_lower in t_short) or (t_short in name_lower):
                             return {'color': t.get('color', '000000'), 'alt_color': t.get('alt_color', '444444')}

        except: pass
        return {'color': '000000', 'alt_color': '444444'}

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

    def _fetch_simple_league(self, league_key, catalog):
        config = self.leagues[league_key]
        if 'team_params' not in config: return
        try:
            r = self.session.get(f"{self.base_url}{config['path']}/teams", params=config['team_params'], headers=HEADERS, timeout=10)
            data = r.json()
            if 'sports' in data:
                for sport in data['sports']:
                    for league in sport['leagues']:
                        for item in league.get('teams', []):
                            abbr = item['team'].get('abbreviation', 'unk')
                            scoped_id = f"{league_key}:{abbr}"

                            clr = item['team'].get('color', '000000')
                            alt = item['team'].get('alternateColor', '444444')
                            logo = item['team'].get('logos', [{}])[0].get('href', '')
                            logo = self.get_corrected_logo(league_key, abbr, logo)

                            name = item['team'].get('displayName', '')
                            short_name = item['team'].get('shortDisplayName', '')

                            if not any(x.get('id') == scoped_id for x in catalog[league_key]):
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

            self._fetch_ahl_teams_reference(teams_catalog)

            for t in OLYMPIC_HOCKEY_TEAMS:
                teams_catalog['hockey_olympics'].append({
                    'abbr': t['abbr'],
                    'id': f"hockey_olympics:{t['abbr']}",
                    'logo': t['logo'],
                    'color': '000000',
                    'alt_color': '444444'
                })

            url = f"{self.base_url}football/college-football/teams"
            r = self.session.get(url, params={'limit': 1000, 'groups': '80,81'}, headers=HEADERS, timeout=10)
            data = r.json()
            if 'sports' in data:
                for sport in data['sports']:
                    for league in sport['leagues']:
                        for item in league.get('teams', []):
                            t_abbr = item['team'].get('abbreviation', 'unk')
                            t_clr = item['team'].get('color', '000000')
                            t_alt = item['team'].get('alternateColor', '444444')
                            logos = item['team'].get('logos', [])
                            t_logo = logos[0].get('href', '') if len(logos) > 0 else ''

                            if t_abbr in FBS_TEAMS:
                                t_logo = self.get_corrected_logo('ncf_fbs', t_abbr, t_logo)
                                scoped_id = f"ncf_fbs:{t_abbr}"
                                if not any(x['id'] == scoped_id for x in teams_catalog['ncf_fbs']):
                                    teams_catalog['ncf_fbs'].append({'abbr': t_abbr, 'id': scoped_id, 'logo': t_logo, 'color': t_clr, 'alt_color': t_alt})

                            elif t_abbr in FCS_TEAMS:
                                t_logo = self.get_corrected_logo('ncf_fcs', t_abbr, t_logo)
                                scoped_id = f"ncf_fcs:{t_abbr}"
                                if not any(x['id'] == scoped_id for x in teams_catalog['ncf_fcs']):
                                    teams_catalog['ncf_fcs'].append({'abbr': t_abbr, 'id': scoped_id, 'logo': t_logo, 'color': t_clr, 'alt_color': t_alt})

            futures = []
            leagues_to_fetch = [
                'nfl', 'mlb', 'nhl', 'nba', 'march_madness',
                'soccer_epl', 'soccer_fa_cup', 'soccer_champ', 'soccer_l1', 'soccer_l2', 'soccer_wc', 'soccer_champions_league', 'soccer_europa_league','soccer_mls'
            ]
            for lk in leagues_to_fetch:
                if lk in self.leagues:
                    futures.append(self.executor.submit(self._fetch_simple_league, lk, teams_catalog))
            concurrent.futures.wait(futures)

            with data_lock: state['all_teams_data'] = teams_catalog
        except Exception as e: print(f"Global Team Fetch Error: {e}")

    def _get_ahl_key(self):
        if self.ahl_cached_key and time.time() < self.ahl_key_expiry:
            return self.ahl_cached_key

        for key in AHL_API_KEYS:
            try:
                params = {"feed": "modulekit", "view": "seasons", "key": key, "client_code": "ahl", "lang": "en", "fmt": "json", "league_id": 4}
                r = self.session.get("https://lscluster.hockeytech.com/feed/index.php", params=params, timeout=3)
                if r.status_code == 200:
                    data = r.json()
                    if "SiteKit" in data or "Seasons" in data:
                        self.ahl_cached_key = key
                        self.ahl_key_expiry = time.time() + 7200
                        return key
            except: continue
        return AHL_API_KEYS[0]

    def _fetch_ahl_teams_reference(self, catalog):
        if 'ahl' not in self.leagues: return

        catalog['ahl'] = []
        seen_ids = set()

        for code, meta in AHL_TEAMS.items():
            t_id = meta.get('id')
            if t_id and t_id in seen_ids: continue
            if t_id: seen_ids.add(t_id)

            logo_url = validate_logo_url(t_id) if t_id else ""
            scoped_id = f"ahl:{code}"

            catalog['ahl'].append({
                'abbr': code,
                'id': scoped_id,
                'real_id': t_id,
                'logo': logo_url,
                'color': meta.get('color', '000000'),
                'alt_color': '444444',
                'name': meta.get('name', code),
                'shortName': meta.get('name', code).split(" ")[-1]
            })

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

    def _fetch_ahl(self, conf, visible_start_utc, visible_end_utc):
        games_found = []
        if not conf['active_sports'].get('ahl', False): return []

        try:
            key = self._get_ahl_key()
            req_date = visible_start_utc.astimezone(timezone(timedelta(hours=conf.get('utc_offset', -5)))).strftime("%Y-%m-%d")

            params = {
                "feed": "modulekit", "view": "scorebar", "key": key,
                "client_code": "ahl", "lang": "en", "fmt": "json",
                "league_id": 4, "site_id": 0
            }

            r = self.session.get("https://lscluster.hockeytech.com/feed/index.php", params=params, timeout=5)
            if r.status_code != 200: return []

            data = r.json()
            scorebar = data.get("SiteKit", {}).get("Scorebar", [])
            ahl_refs = state['all_teams_data'].get('ahl', [])

            for g in scorebar:
                g_date_str = g.get("Date", "")
                gid = g.get("ID")
                h_code = g.get("HomeCode", "").upper()
                a_code = g.get("VisitorCode", "").upper()
                h_sc = str(g.get("HomeGoals", "0"))
                a_sc = str(g.get("VisitorGoals", "0"))

                parsed_utc = ""
                iso_date = g.get("GameDateISO8601", "")
                if iso_date:
                    try:
                        dt_obj = dt.fromisoformat(iso_date)
                        parsed_utc = dt_obj.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                    except: pass

                if not parsed_utc:
                    raw_time = (g.get("GameTime") or g.get("Time") or "").strip()
                    parsed_utc = f"{g_date_str}T00:00:00Z" # Fallback
                    try:
                        tm_match = re.search(r"(\d+:\d+)\s*(am|pm)(?:\s*([A-Z]+))?", raw_time, re.IGNORECASE)
                        if tm_match:
                            time_str, meridiem, tz_str = tm_match.groups()
                            offset = -5
                            if tz_str: offset = TZ_OFFSETS.get(tz_str.upper(), -5)
                            dt_obj = dt.strptime(f"{g_date_str} {time_str} {meridiem}", "%Y-%m-%d %I:%M %p")
                            dt_obj = dt_obj.replace(tzinfo=timezone(timedelta(hours=offset)))
                            parsed_utc = dt_obj.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                    except: pass

                if g_date_str != req_date: continue

                raw_status = g.get("GameStatusString", "")
                status_lower = raw_status.lower()
                period_str = str(g.get("Period", ""))

                disp = "Scheduled"; gst = "pre"

                if "final" in status_lower:
                    gst = "post"
                    summary_data = None
                    try:
                        sum_params = {
                            "feed": "statviewfeed", "view": "gameSummary", "key": key,
                            "client_code": "ahl", "lang": "en", "fmt": "json", "game_id": gid
                        }
                        r_sum = self.session.get("https://lscluster.hockeytech.com/feed/index.php", params=sum_params, timeout=4)
                        if r_sum.status_code == 200:
                            text = r_sum.text.strip()
                            if text.startswith("(") and text.endswith(")"):
                                text = text[1:-1]
                            summary_data = json.loads(text)
                    except: pass

                    is_shootout = self.check_shootout(g, summary_data)

                    if is_shootout: disp = "FINAL S/O"
                    elif period_str == "4" or "ot" in status_lower or "overtime" in status_lower: disp = "FINAL OT"
                    else:
                        if summary_data and (summary_data.get("hasOvertime") or "OT" in str(summary_data.get("periodNameShort", "")).upper()):
                             disp = "FINAL OT"
                        else:
                             disp = "FINAL"

                elif "scheduled" in status_lower or "pre" in status_lower or (re.search(r'\d+:\d+', status_lower) and "1st" not in status_lower and "2nd" not in status_lower and "3rd" not in status_lower and "ot" not in status_lower):
                    gst = "pre"
                    try:
                         if iso_date:
                           local_dt = dt.fromisoformat(iso_date).astimezone(timezone(timedelta(hours=conf.get('utc_offset', -5))))
                           disp = local_dt.strftime("%I:%M %p").lstrip('0')
                         else:
                             raw_time_clean = (g.get("GameTime") or "").strip()
                             disp = raw_time_clean.split(" ")[0] + " " + raw_time_clean.split(" ")[1]
                    except: disp = "Scheduled"
                else:
                    gst = "in"
                    if "intermission" in status_lower:
                        # Check text first, then fallback to the period number
                        if "1st" in status_lower or period_str == "1": disp = "End 1st"
                        elif "2nd" in status_lower or period_str == "2": disp = "End 2nd"
                        elif "3rd" in status_lower or period_str == "3": disp = "End 3rd"
                        else: disp = "INT"
                    else:
                        m = re.search(r'(\d+:\d+)\s*(1st|2nd|3rd|ot|overtime)', raw_status, re.IGNORECASE)
                        if m:
                            clk = m.group(1); prd = m.group(2).lower()
                            p_lbl = "OT" if "ot" in prd else f"P{prd[0]}"
                            disp = f"{p_lbl} {clk}"
                        else: disp = raw_status

                is_shown = True
                # NO LOCAL FILTERING HERE - LET /DATA DO IT

                h_obj = next((t for t in ahl_refs if t['abbr'] == h_code), None)
                a_obj = next((t for t in ahl_refs if t['abbr'] == a_code), None)

                if not h_obj:
                    h_meta_raw = AHL_TEAMS.get(h_code)
                    if h_meta_raw: h_obj = next((t for t in ahl_refs if t.get('real_id') == h_meta_raw.get('id')), None)
                if not a_obj:
                    a_meta_raw = AHL_TEAMS.get(a_code)
                    if a_meta_raw: a_obj = next((t for t in ahl_refs if t.get('real_id') == a_meta_raw.get('id')), None)

                h_logo = h_obj['logo'] if h_obj else ""
                a_logo = a_obj['logo'] if a_obj else ""

                h_meta = AHL_TEAMS.get(h_code, {"color": "000000"})
                a_meta = AHL_TEAMS.get(a_code, {"color": "000000"})

                games_found.append({
                    'type': 'scoreboard', 'sport': 'ahl', 'id': f"ahl_{gid}",
                    'status': disp, 'state': gst, 'is_shown': is_shown,
                    'home_abbr': h_code, 'home_score': h_sc, 'home_logo': h_logo,
                    'away_abbr': a_code, 'away_score': a_sc, 'away_logo': a_logo,
                    'home_color': f"#{h_meta.get('color','000000')}", 'away_color': f"#{a_meta.get('color','000000')}",
                    'home_alt_color': '#444444', 'away_alt_color': '#444444',
                    'startTimeUTC': parsed_utc, 'situation': {}
                })
        except Exception as e:
            print(f"AHL Fetch Error: {e}")

        return games_found

    def fetch_shootout_details(self, game_id, away_id, home_id):
        try:
            url = f"https://api-web.nhle.com/v1/gamecenter/{game_id}/play-by-play"
            r = self.session.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=3)
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
            r = self.session.get(f"https://api-web.nhle.com/v1/gamecenter/{gid}/landing", headers=HEADERS, timeout=2)
            if r.status_code == 200: return r.json()
        except: pass
        return None

    def _fetch_nhl_native(self, conf, window_start_utc, window_end_utc, visible_start_utc, visible_end_utc):
        games_found = []
        is_nhl = conf['active_sports'].get('nhl', False)
        if not is_nhl: return []

        processed_ids = set()
        try:
            r = self.session.get("https://api-web.nhle.com/v1/schedule/now", headers=HEADERS, timeout=5)
            if r.status_code != 200: return []

            landing_futures = {}

            for d in r.json().get('gameWeek', []):
                for g in d.get('games', []):
                    try:
                        g_utc = g.get('startTimeUTC')
                        if not g_utc: continue
                        g_dt = dt.fromisoformat(g_utc.replace('Z', '+00:00'))
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
                        g_utc = g.get('startTimeUTC')
                        if not g_utc: continue
                        g_dt = dt.fromisoformat(g_utc.replace('Z', '+00:00'))

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

                    h_ab = g['homeTeam']['abbrev']; a_ab = g['awayTeam']['abbrev']
                    h_sc = str(g['homeTeam'].get('score', 0)); a_sc = str(g['awayTeam'].get('score', 0))

                    h_lg = self.get_corrected_logo('nhl', h_ab, f"https://a.espncdn.com/i/teamlogos/nhl/500/{h_ab.lower()}.png")
                    a_lg = self.get_corrected_logo('nhl', a_ab, f"https://a.espncdn.com/i/teamlogos/nhl/500/{a_ab.lower()}.png")
                    h_info = self.lookup_team_info_from_cache('nhl', h_ab)
                    a_info = self.lookup_team_info_from_cache('nhl', a_ab)

                    if st in ['SUSP', 'SUSPENDED', 'PPD', 'POSTPONED']:
                        map_st = 'post'

                    disp = "Scheduled"; pp = False; poss = ""; en = False; shootout_data = None
                    dur = self.calculate_game_timing('nhl', g_utc, 1, st)

                    g_local = g_dt.astimezone(timezone(timedelta(hours=conf.get('utc_offset', -5))))

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

    def _fetch_fotmob_details(self, match_id, home_id=None, away_id=None):
        try:
            url = f"https://www.fotmob.com/api/matchDetails?matchId={match_id}"
            resp = self.session.get(url, headers=HEADERS, timeout=10)
            resp.raise_for_status()
            payload = resp.json()

            info = payload.get("general", {})
            general_home = (info.get("homeTeam") or {}).get("id")
            general_away = (info.get("awayTeam") or {}).get("id")

            containers = [
                payload.get("shootout"),
                payload.get("content", {}).get("shootout"),
                payload.get("content", {}).get("penaltyShootout"),
            ]

            home_shootout, away_shootout = [], []
            for raw in containers:
                h, a, _, _ = self.parse_shootout(raw, home_id, away_id, general_home, general_away)
                if h or a:
                    home_shootout, away_shootout = h, a
                    break

            if not home_shootout and not away_shootout and payload.get("content", {}).get("matchFacts"):
                events_container = payload["content"].get("matchFacts", {}).get("events")
                h, a, _, _ = self.parse_shootout_events(events_container, home_id, away_id, general_home, general_away)
                if h or a:
                    home_shootout, away_shootout = h, a

            if home_shootout or away_shootout:
                return {'home': home_shootout, 'away': away_shootout}
            return None
        except: return None

    def _parse_score_str(self, score_str):
        if not score_str or "-" not in str(score_str):
            return None, None
        try:
            home_raw, away_raw = [part.strip() for part in str(score_str).split("-", 1)]
            home_val = int(home_raw) if home_raw.isdigit() else None
            away_val = int(away_raw) if away_raw.isdigit() else None
            return home_val, away_val
        except Exception:
            return None, None

    def _format_live_clock(self, status: dict, fallback_text: str = "") -> str | None:
        def _render_clock(minutes: int, seconds: int, max_time: int | None) -> str:
            if max_time is not None and minutes > max_time:
                extra_total = minutes * 60 + seconds - max_time * 60
                extra_min, extra_sec = divmod(extra_total, 60)
                return f"{max_time}+{extra_min:02d}:{extra_sec:02d}'"
            return f"{minutes:02d}:{seconds:02d}'"

        if not isinstance(status, dict):
            return None

        live_time = status.get("liveTime") or status.get("live_time") or {}
        max_time = None
        if isinstance(live_time, dict):
            max_time_raw = live_time.get("maxTime") or live_time.get("max_time")
            if isinstance(max_time_raw, (int, float)) or (isinstance(max_time_raw, str) and max_time_raw.isdigit()):
                max_time = int(float(max_time_raw))

            long_val = live_time.get("long") or live_time.get("clock") or live_time.get("elapsed")
            if long_val:
                text = str(long_val)
                plus_match = re.match(r"\s*(\d+)\+(\d+)(?::(\d{1,2}))?", text)
                if plus_match:
                    base = int(plus_match.group(1))
                    extra_min = int(plus_match.group(2))
                    extra_sec = int(plus_match.group(3) or 0)
                    return f"{base}+{extra_min:02d}:{extra_sec:02d}'"

                clock_match = re.match(r"\s*(\d+):(\d{1,2})", text)
                if clock_match:
                    minutes = int(clock_match.group(1))
                    seconds = int(clock_match.group(2))
                    return _render_clock(minutes, seconds, max_time)

            minute_val = live_time.get("minute")
            second_val = live_time.get("second")
            if minute_val is not None and second_val is not None:
                try:
                    minutes = int(minute_val)
                    seconds = int(second_val)
                    return _render_clock(minutes, seconds, max_time)
                except Exception:
                    pass

            short_val = live_time.get("short")
            if short_val:
                short_match = re.match(r"\s*(\d+)(?:\+(\d+))?'", str(short_val))
                if short_match:
                    base = int(short_match.group(1))
                    extra = int(short_match.group(2) or 0)
                    if extra:
                        return f"{base}+{extra:02d}:00'"
                    return f"{base:02d}:00'"

        if fallback_text:
            text = str(fallback_text)
            text_match = re.search(r"(\d+)(?:\+(\d+))?'", text)
            if text_match:
                base = int(text_match.group(1))
                extra = int(text_match.group(2) or 0)
                if extra:
                    return f"{base}+{extra:02d}:00'"
                return f"{base:02d}:00'"

        return None

    def _extract_matches(self, sections, internal_id, conf, start_window, end_window, visible_start_utc, visible_end_utc):
        matches = []
        for section in sections:
            candidate_matches = section.get("matches") if isinstance(section, dict) else None
            if candidate_matches is None: candidate_matches = [section]

            for match in candidate_matches:
                if not isinstance(match, dict): continue

                status = match.get("status") or {}
                kickoff = status.get("utcTime") or match.get("time")
                if not kickoff: continue

                try:
                    match_dt = dt.fromisoformat(kickoff.replace('Z', '+00:00'))
                    if not (start_window <= match_dt <= end_window): continue
                except: continue

                mid = match.get("id")
                h_name = match.get("home", {}).get("name") or "Home"
                a_name = match.get("away", {}).get("name") or "Away"

                h_ab = SOCCER_ABBR_OVERRIDES.get(h_name, h_name[:3].upper())
                a_ab = SOCCER_ABBR_OVERRIDES.get(a_name, a_name[:3].upper())

                finished = bool(status.get("finished"))
                started = bool(status.get("started"))
                reason = (status.get("reason") or {}).get("short") or ""

                home_score = (match.get("home") or {}).get("score")
                away_score = (match.get("away") or {}).get("score")

                status_score = status.get("score") or status.get("current") or {}
                if isinstance(status_score, dict):
                    if home_score is None: home_score = status_score.get("home")
                    if away_score is None: away_score = status_score.get("away")

                    for key in ("ft", "fulltime"):
                        ft_score = status_score.get(key)
                        if isinstance(ft_score, (list, tuple)) and len(ft_score) >= 2:
                            if home_score is None: home_score = ft_score[0]
                            if away_score is None: away_score = ft_score[1]
                elif isinstance(status_score, (list, tuple)) and len(status_score) >= 2:
                    if home_score is None: home_score = status_score[0]
                    if away_score is None: away_score = status_score[1]

                score_str_sources = [
                    status.get("scoreStr"),
                    (match.get("home") or {}).get("scoreStr"),
                    (match.get("away") or {}).get("scoreStr"),
                    status.get("statusText") if "-" in str(status.get("statusText", "")) else None
                ]

                for s_str in score_str_sources:
                    if home_score is not None and away_score is not None: break
                    h_val, a_val = self._parse_score_str(s_str)
                    if home_score is None: home_score = h_val
                    if away_score is None: away_score = a_val

                final_home_score = str(home_score) if home_score is not None else "0"
                final_away_score = str(away_score) if away_score is not None else "0"

                gst = 'pre'

                try:
                    k_dt = dt.fromisoformat(kickoff.replace('Z', '+00:00'))
                    local_k = k_dt.astimezone(timezone(timedelta(hours=conf.get('utc_offset', -5))))
                    disp = local_k.strftime("%I:%M %p").lstrip('0')
                except:
                    disp = kickoff.split("T")[1][:5]

                if started and not finished:
                    gst = 'in'
                    clock_str = self._format_live_clock(status, match.get("status_text"))
                    if clock_str:
                        disp = clock_str
                    else:
                        disp = "In Progress"

                    current_minute = 0
                    try:
                        current_minute = int((status.get("liveTime") or {}).get("minute", 0))
                    except: pass

                    raw_status_text = str(status.get("statusText", ""))
                    is_ht = (
                        reason == "HT"
                        or raw_status_text == "HT"
                        or "Halftime" in raw_status_text
                        or status.get("liveTime", {}).get("short") == "HT"
                        or reason == "PET"
                    )

                    if is_ht:
                        if current_minute >= 105:
                            disp = "HT ET"
                        else:
                            disp = "HALF"

                elif finished:
                    gst = 'post'
                    disp = "Final"
                    if "AET" in reason: disp = "Final AET"
                    if "Pen" in reason or (status.get("reason") and "Pen" in str(status.get("reason"))):
                        disp = "FIN"

                elif status.get("cancelled"):
                    gst = 'post'
                    disp = "Postponed"

                if "Postponed" in reason or "PPD" in reason:
                    gst = 'post'
                    disp = "Postponed"

                if match_dt < visible_start_utc or match_dt >= visible_end_utc:
                      if gst != 'in': continue

                is_shootout = False
                if "Pen" in reason or (gst == 'in' and "Pen" in str(status)) or disp == "FIN":
                    is_shootout = True
                    if gst == 'in': disp = "Pens"

                shootout_data = None
                if is_shootout:
                    shootout_data = self._fetch_fotmob_details(mid, match.get("home", {}).get("id"), match.get("away", {}).get("id"))

                is_shown = True
                if "Postponed" in disp or "PPD" in reason or status.get("cancelled"):
                    is_shown = False

                h_id = match.get("home", {}).get("id")
                a_id = match.get("away", {}).get("id")

                h_info = self.lookup_team_info_from_cache(internal_id, h_ab, h_name)
                a_info = self.lookup_team_info_from_cache(internal_id, a_ab, a_name)

                matches.append({
                    'type': 'scoreboard',
                    'sport': internal_id,
                    'id': str(mid),
                    'status': disp,
                    'state': gst,
                    'is_shown': is_shown,
                    'home_abbr': h_ab, 'home_score': final_home_score,
                    'home_logo': f"https://images.fotmob.com/image_resources/logo/teamlogo/{h_id}.png",
                    'away_abbr': a_ab, 'away_score': final_away_score,
                    'away_logo': f"https://images.fotmob.com/image_resources/logo/teamlogo/{a_id}.png",
                    'home_color': f"#{h_info['color']}", 'home_alt_color': f"#{h_info['alt_color']}",
                    'away_color': f"#{a_info['color']}", 'away_alt_color': f"#{a_info['alt_color']}",
                    'startTimeUTC': kickoff,
                    'estimated_duration': 115,
                    'situation': { 'possession': '', 'shootout': shootout_data }
                })
        return matches

    def _fetch_fotmob_league(self, league_id, internal_id, conf, start_window, end_window, visible_start_utc, visible_end_utc):
        try:
            url = "https://www.fotmob.com/api/leagues"
            last_sections = []

            for l_type in ("cup", "league", None):
                params = {"id": league_id, "tab": "matches", "timeZone": "UTC", "type": l_type, "_": int(time.time())}

                try:
                    resp = self.session.get(url, params=params, headers=HEADERS, timeout=10)
                    resp.raise_for_status()
                    payload = resp.json()

                    sections = payload.get("matches", {}).get("allMatches", [])
                    if not sections:
                        sections = payload.get("fixtures", {}).get("allMatches", [])

                    last_sections = sections
                    matches = self._extract_matches(sections, internal_id, conf, start_window, end_window, visible_start_utc, visible_end_utc)
                    if matches: return matches
                except: continue

            if last_sections:
                 return self._extract_matches(last_sections, internal_id, conf, start_window, end_window, visible_start_utc, visible_end_utc)
            return []
        except Exception as e:
            print(f"FotMob League {league_id} error: {e}")
            return []

    def fetch_single_league(self, league_key, config, conf, window_start_utc, window_end_utc, utc_offset, visible_start_utc, visible_end_utc):
        local_games = []
        if not conf['active_sports'].get(league_key, False): return []

        if config.get('type') == 'leaderboard':
            return local_games

        try:
            curr_p = config.get('scoreboard_params', {}).copy()

            # CHANGE B: DATE OPTIMIZATION (Only fetch TODAY)
            now_local = dt.now(timezone.utc).astimezone(timezone(timedelta(hours=utc_offset)))

            if conf['debug_mode'] and conf['custom_date']:
                curr_p['dates'] = conf['custom_date'].replace('-', '')
            else:
                curr_p['dates'] = now_local.strftime("%Y%m%d") # Only fetch today

            # CHANGE: Use API_TIMEOUT
            r = self.session.get(f"{self.base_url}{config['path']}/scoreboard", params=curr_p, headers=HEADERS, timeout=API_TIMEOUT)
            data = r.json()

            events = data.get('events', [])
            if not events:
                leagues = data.get('leagues', [])
                if leagues and len(leagues) > 0:
                    events = leagues[0].get('events', [])

            for e in events:
                gid = str(e['id'])

                # CHANGE A: CACHE CHECK
                if gid in self.final_game_cache:
                    local_games.append(self.final_game_cache[gid])
                    continue # Skip processing

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
                h_score = h.get('score','0')
                a_score = a.get('score','0')
                if 'soccer' in league_key:
                    h_score = re.sub(r'\s*\(.*?\)', '', str(h_score))
                    a_score = re.sub(r'\s*\(.*?\)', '', str(a_score))

                s_disp = tp.get('shortDetail', 'TBD')
                p = st.get('period', 1)
                duration_est = self.calculate_game_timing(league_key, e['date'], p, s_disp)

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
                                if p > 4: s_disp = f"OT{p-4 if p-4>1 else ''} {clk}"
                                else: s_disp = f"Q{p} {clk}"
                            elif 'football' in config['path']:
                                if p > 4: s_disp = f"OT{p-4 if p-4>1 else ''} {clk}"
                                else: s_disp = f"Q{p} {clk}"
                            elif 'hockey' in config['path']:
                                if p > 3: s_disp = f"OT{p-3 if p-3>1 else ''} {clk}"
                                else: s_disp = f"P{p} {clk}"
                            elif 'baseball' in config['path']:
                                short_detail = tp.get('shortDetail', s_disp)
                                s_disp = short_detail.replace(" - ", " ").replace("Inning", "In")
                            else: s_disp = f"P{p} {clk}"

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
                elif gst in ['in', 'half'] and e['id'] in self.possession_cache: poss_raw = self.possession_cache[e['id']]

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
                    'away_abbr': a_ab, 'away_score': a_sc, 'away_logo': a_lg,
                    'home_color': f"#{h['team'].get('color','000000')}", 'home_alt_color': f"#{h['team'].get('alternateColor','ffffff')}",
                    'away_color': f"#{a['team'].get('color','000000')}", 'away_alt_color': f"#{a['team'].get('alternateColor','ffffff')}",
                    'startTimeUTC': e['date'],
                    'estimated_duration': duration_est,

                    # MARCH MADNESS SPECIFIC FIELDS
                    'home_seed': str(h_seed),
                    'away_seed': str(a_seed),

                    'situation': {
                        'possession': poss_abbr,
                        'isRedZone': sit.get('isRedZone', False),
                        'downDist': down_text,
                        'shootout': shootout_data,
                        'powerPlay': False,
                        'emptyNet': False
                    }
                }
                if league_key == 'mlb':
                    game_obj['situation'].update({'balls': sit.get('balls', 0), 'strikes': sit.get('strikes', 0), 'outs': sit.get('outs', 0),
                        'onFirst': sit.get('onFirst', False), 'onSecond': sit.get('onSecond', False), 'onThird': sit.get('onThird', False)})

                if is_suspended: game_obj['is_shown'] = False

                local_games.append(game_obj)

                # CHANGE C: SAVE FINAL GAMES TO CACHE
                if gst == 'post' and "FINAL" in s_disp:
                    self.final_game_cache[gid] = game_obj

        except Exception as e: print(f"Error fetching {league_key}: {e}")
        return local_games

    def update_buffer_sports(self):
        all_games = []
        with data_lock:
            conf = state.copy()

        # 1. WEATHER & CLOCK (Simple, fast)
        if conf['active_sports'].get('weather'):
            if (conf['weather_lat'] != self.weather.lat or
                conf['weather_lon'] != self.weather.lon or
                conf['weather_city'] != self.weather.city_name):
                self.weather.update_config(city=conf['weather_city'], lat=conf['weather_lat'], lon=conf['weather_lon'])
            w = self.weather.get_weather()
            if w: all_games.append(w)

        if conf['active_sports'].get('clock'):
            all_games.append({'type':'clock','sport':'clock','id':'clk','is_shown':True})

        # 2. SPORTS (Parallelized & Smart)
        if conf['mode'] in ['sports', 'live', 'my_teams', 'all']:
            utc_offset = conf.get('utc_offset', -5)
            now_utc = dt.now(timezone.utc)
            now_local = now_utc.astimezone(timezone(timedelta(hours=utc_offset)))

            if now_local.hour < 3:
                visible_start_local = (now_local - timedelta(days=1)).replace(hour=10, minute=0, second=0, microsecond=0)
                visible_end_local = now_local.replace(hour=3, minute=0, second=0, microsecond=0)
            else:
                visible_start_local = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
                visible_end_local = (now_local + timedelta(days=1)).replace(hour=3, minute=0, second=0, microsecond=0)

            visible_start_utc = visible_start_local.astimezone(timezone.utc)
            visible_end_utc = visible_end_local.astimezone(timezone.utc)

            window_start_local = now_local - timedelta(hours=30)
            window_end_local = now_local + timedelta(hours=48)

            window_start_utc = window_start_local.astimezone(timezone.utc)
            window_end_utc = window_end_local.astimezone(timezone.utc)

            futures = {}

            # --- SMART LOOP IMPLEMENTATION ---

            # Special fetchers (Always submit for now, but with timeout)
            if conf['active_sports'].get('ahl', False):
                f = self.executor.submit(self._fetch_ahl, conf, visible_start_utc, visible_end_utc)
                futures[f] = 'ahl'

            if conf['active_sports'].get('nhl', False) and not conf['debug_mode']:
                f = self.executor.submit(self._fetch_nhl_native, conf, window_start_utc, window_end_utc, visible_start_utc, visible_end_utc)
                futures[f] = 'nhl_native'

            for internal_id, fid in FOTMOB_LEAGUE_MAP.items():
                if conf['active_sports'].get(internal_id, False):
                    f = self.executor.submit(self._fetch_fotmob_league, fid, internal_id, conf, window_start_utc, window_end_utc, visible_start_utc, visible_end_utc)
                    futures[f] = internal_id

            # Standard ESPN fetchers (Apply Smart Sleep)
            for league_key, config in self.leagues.items():
                if league_key == 'nhl' and not conf['debug_mode']: continue
                if league_key.startswith('soccer_'): continue
                if league_key == 'ahl': continue

                # Check Sleep Status
                if time.time() < self.league_next_update.get(league_key, 0):
                    # SLEEPING: Use cached data (Instant)
                    if league_key in self.league_last_data:
                        all_games.extend(self.league_last_data[league_key])
                    continue

                # AWAKE: Submit task
                f = self.executor.submit(
                    self.fetch_single_league,
                    league_key, config, conf, window_start_utc, window_end_utc, utc_offset, visible_start_utc, visible_end_utc
                )
                futures[f] = league_key

            # HARD TIMEOUT: Wait max 3.0s for threads
            done, _ = concurrent.futures.wait(futures.keys(), timeout=API_TIMEOUT)

            for f in done:
                lk = futures[f]
                try:
                    res = f.result()
                    if res:
                        all_games.extend(res)
                        # Save data for next sleep cycle
                        if lk not in ['ahl', 'nhl_native'] and not lk.startswith('soccer_'):
                            self.league_last_data[lk] = res
                            self.league_next_update[lk] = self._calculate_next_update(res)
                except Exception as e:
                    print(f"Fetch error {lk}: {e}")

        sports_count = len([g for g in all_games if g.get('type') == 'scoreboard'])

        with data_lock:
            prev_buffer = state.get('buffer_sports', [])
            prev_sports_count = len([g for g in prev_buffer if g.get('type') == 'scoreboard'])

        if sports_count == 0 and prev_sports_count > 0:
            self.consecutive_empty_fetches += 1
            if self.consecutive_empty_fetches < 3:
                prev_pure_sports = [g for g in prev_buffer if g.get('type') == 'scoreboard']
                utils = [g for g in all_games if g.get('type') != 'scoreboard']
                all_games = prev_pure_sports + utils
            else:
                self.consecutive_empty_fetches = 0
        else:
            self.consecutive_empty_fetches = 0

        for g in all_games:
            ts = g.get('startTimeUTC')
            if ts and isinstance(ts, str):
                try:
                    d = dt.fromisoformat(ts.replace('Z', '+00:00'))
                    g['startTimeUTC'] = d.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                except: pass

        all_games.sort(key=lambda x: (
            0 if x.get('type') == 'clock' else
            1 if x.get('type') == 'weather' else
            4 if any(k in str(x.get('status', '')).lower() for k in ["postponed", "cancelled", "canceled", "suspended", "ppd"]) else
            3 if "FINAL" in str(x.get('status', '')).upper() or "FIN" == str(x.get('status', '')) else
            2, # Active
            x.get('startTimeUTC', '9999'),
            x.get('sport', ''),
            x.get('id', '0')
        ))

        now_ts = time.time()
        self.history_buffer.append((now_ts, all_games))
        cutoff_time = now_ts - 120
        self.history_buffer = [x for x in self.history_buffer if x[0] > cutoff_time]

        with data_lock:
            state['buffer_sports'] = all_games
            self.merge_buffers()

    def get_snapshot_for_delay(self, delay_seconds):
        if delay_seconds <= 0 or not self.history_buffer:
            with data_lock:
                return state.get('current_games', [])

        target_time = time.time() - delay_seconds
        closest = min(self.history_buffer, key=lambda x: abs(x[0] - target_time))
        sports_snap = closest[1]

        with data_lock:
            stocks_snap = state.get('buffer_stocks', [])
            mode = state['mode']

        utils = [g for g in sports_snap if g.get('type') == 'weather' or g.get('sport') == 'clock']
        pure_sports = [g for g in sports_snap if g not in utils]

        if mode == 'stocks': return stocks_snap
        elif mode == 'weather': return [g for g in utils if g.get('type') == 'weather']
        elif mode == 'clock': return [g for g in utils if g.get('sport') == 'clock']
        elif mode in ['sports', 'live', 'my_teams']: return pure_sports
        else: return pure_sports

    def update_buffer_stocks(self):
        games = []
        with data_lock: conf = state.copy()

        if conf['mode'] in ['stocks', 'all']:
            cats = [item['id'] for item in LEAGUE_OPTIONS if item['type'] == 'stock']

            for cat in cats:
                if conf['active_sports'].get(cat): games.extend(self.stocks.get_list(cat))

        with data_lock:
            state['buffer_stocks'] = games
            self.merge_buffers()

    def merge_buffers(self):
        mode = state['mode']
        final_list = []

        sports_buffer = state.get('buffer_sports', [])
        stocks_buffer = state.get('buffer_stocks', [])

        utils = [g for g in sports_buffer if g.get('type') == 'weather' or g.get('sport') == 'clock']
        pure_sports = [g for g in sports_buffer if g not in utils]

        if mode == 'stocks': final_list = stocks_buffer
        elif mode == 'weather': final_list = [g for g in utils if g.get('type') == 'weather']
        elif mode == 'clock': final_list = [g for g in utils if g.get('sport') == 'clock']
        elif mode in ['sports', 'live', 'my_teams']: final_list = pure_sports
        else: final_list = pure_sports

        state['current_games'] = final_list
