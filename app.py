import time
import threading
import json
import os
import re
from datetime import datetime as dt, timezone, timedelta
import requests
from flask import Flask, jsonify, request, render_template_string

# ================= CONFIGURATION =================
CONFIG_FILE = "ticker_config.json"
UPDATE_INTERVAL = 10 # Slightly increased to handle more API calls
data_lock = threading.Lock()

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
    "Cache-Control": "no-cache, no-store, must-revalidate",
    "Pragma": "no-cache",
    "Expires": "0"
}

# ================= DEFAULT STATE =================
default_state = {
    'active_sports': { 
        'nfl': True, 'ncf_fbs': True, 'ncf_fcs': True, 'mlb': True, 'nhl': True, 'nba': True, 
        'soccer': True, 'golf': True, 'f1': True, 'nascar': True, 'indycar': True, 'wec': False, 'imsa': False,
        'weather': False, 'clock': False 
    },
    'mode': 'all', 
    'layout_mode': 'schedule',
    'scroll_seamless': False,
    'my_teams': ["NYG", "NYY", "NJD", "NYK", "LAL", "BOS", "KC", "BUF", "LEH"], 
    'current_games': [],
    'all_teams_data': {}, 
    'debug_mode': False,
    'custom_date': None,
    'brightness': 0.5,
    'scroll_speed': 5, 
    'inverted': False,
    'panel_count': 2,
    'test_pattern': False,
    'reboot_requested': False,
    'weather_location': "New York",
    'utc_offset': -5  # Default to EST
}

state = default_state.copy()

if os.path.exists(CONFIG_FILE):
    try:
        with open(CONFIG_FILE, 'r') as f:
            loaded = json.load(f)
            for k, v in loaded.items():
                if k in state:
                    if isinstance(state[k], dict) and isinstance(v, dict): state[k].update(v)
                    else: state[k] = v
    except: pass

def save_config_file():
    try:
        with data_lock:
            export_data = {
                'active_sports': state['active_sports'], 
                'mode': state['mode'], 
                'layout_mode': state['layout_mode'],
                'scroll_seamless': state['scroll_seamless'], 
                'my_teams': state['my_teams'],
                'brightness': state['brightness'],
                'scroll_speed': state['scroll_speed'], 
                'inverted': state['inverted'],
                'panel_count': state['panel_count'],
                'weather_location': state['weather_location'],
                'utc_offset': state['utc_offset']
            }
        with open(CONFIG_FILE, 'w') as f:
            json.dump(export_data, f)
    except: pass

# ==========================================
# TEAMS LISTS & MAPPINGS
# ==========================================
FBS_TEAMS = ["AF", "AKR", "ALA", "APP", "ARIZ", "ASU", "ARK", "ARST", "ARMY", "AUB", "BALL", "BAY", "BOIS", "BC", "BGSU", "BUF", "BYU", "CAL", "CMU", "CLT", "CIN", "CLEM", "CCU", "COLO", "CSU", "CONN", "DEL", "DUKE", "ECU", "EMU", "FAU", "FIU", "FLA", "FSU", "FRES", "GASO", "GAST", "GT", "UGA", "HAW", "HOU", "ILL", "IND", "IOWA", "ISU", "JXST", "JMU", "KAN", "KSU", "KENN", "KENT", "UK", "LIB", "ULL", "LT", "LOU", "LSU", "MAR", "MD", "MASS", "MEM", "MIA", "M-OH", "MICH", "MSU", "MTSU", "MINN", "MSST", "MIZ", "MOST", "NAVY", "NCST", "NEB", "NEV", "UNM", "NMSU", "UNC", "UNT", "NIU", "NU", "ND", "OHIO", "OSU", "OU", "OKST", "ODU", "MISS", "ORE", "ORST", "PSU", "PITT", "PUR", "RICE", "RUTG", "SAM", "SDSU", "SJSU", "SMU", "USA", "SC", "USF", "USM", "STAN", "SYR", "TCU", "TEM", "TENN", "TEX", "TA&M", "TXST", "TTU", "TOL", "TROY", "TULN", "TLSA", "UAB", "UCF", "UCLA", "ULM", "UMASS", "UNLV", "USC", "UTAH", "USU", "UTEP", "UTSA", "VAN", "UVA", "VT", "WAKE", "WASH", "WSU", "WVU", "WKU", "WMU", "WIS", "WYO"]
FCS_TEAMS = ["ACU", "AAMU", "ALST", "UALB", "ALCN", "UAPB", "APSU", "BCU", "BRWN", "BRY", "BUCK", "BUT", "CP", "CAM", "CARK", "CCSU", "CHSO", "UTC", "CIT", "COLG", "COLU", "COR", "DART", "DAV", "DAY", "DSU", "DRKE", "DUQ", "EIU", "EKU", "ETAM", "EWU", "ETSU", "ELON", "FAMU", "FOR", "FUR", "GWEB", "GTWN", "GRAM", "HAMP", "HARV", "HC", "HCU", "HOW", "IDHO", "IDST", "ILST", "UIW", "INST", "JKST", "LAF", "LAM", "LEH", "LIN", "LIU", "ME", "MRST", "MCN", "MER", "MERC", "MRMK", "MVSU", "MONM", "MONT", "MTST", "MORE", "MORG", "MUR", "UNH", "NHVN", "NICH", "NORF", "UNA", "NCAT", "NCCU", "UND", "NDSU", "NAU", "UNCO", "UNI", "NWST", "PENN", "PRST", "PV", "PRES", "PRIN", "URI", "RICH", "RMU", "SAC", "SHU", "SFPA", "SAM", "USD", "SELA", "SEMO", "SDAK", "SDST", "SCST", "SOU", "SIU", "SUU", "STMN", "SFA", "STET", "STO", "STBK", "TAR", "TNST", "TNTC", "TXSO", "TOW", "UCD", "UTM", "UTU", "UTRGV", "VAL", "VILL", "VMI", "WAG", "WEB", "WGA", "WCU", "WIU", "W&M", "WOF", "YALE", "YSU"]

ABBR_MAPPING = {
    'SJS': 'SJ', 'TBL': 'TB', 'LAK': 'LA', 'NJD': 'NJ', 'VGK': 'VEG', 'UTA': 'UTAH', 'WSH': 'WSH', 'MTL': 'MTL', 'CHI': 'CHI',
    'NY': 'NYK', 'NO': 'NOP', 'GS': 'GSW', 'SA': 'SAS'
}

LOGO_OVERRIDES = {
    "NFL:HOU": "https://a.espncdn.com/i/teamlogos/nfl/500/hou.png", "NBA:HOU": "https://a.espncdn.com/i/teamlogos/nba/500/hou.png", "MLB:HOU": "https://a.espncdn.com/i/teamlogos/mlb/500/hou.png", "NCF_FBS:HOU": "https://a.espncdn.com/i/teamlogos/ncaa/500/248.png",
    "NFL:MIA": "https://a.espncdn.com/i/teamlogos/nfl/500/mia.png", "NBA:MIA": "https://a.espncdn.com/i/teamlogos/nba/500/mia.png", "MLB:MIA": "https://a.espncdn.com/i/teamlogos/mlb/500/mia.png", "NCF_FBS:MIA": "https://a.espncdn.com/i/teamlogos/ncaa/500/2390.png", "NCF_FBS:MIAMI": "https://a.espncdn.com/i/teamlogos/ncaa/500/2390.png",
    "NFL:IND": "https://a.espncdn.com/i/teamlogos/nfl/500/ind.png", "NBA:IND": "https://a.espncdn.com/i/teamlogos/nba/500/ind.png", "NCF_FBS:IND": "https://a.espncdn.com/i/teamlogos/ncaa/500/84.png",
    "NHL:WSH": "https://a.espncdn.com/guid/cbe677ee-361e-91b4-5cae-6c4c30044743/logos/secondary_logo_on_black_color.png", "NHL:WAS": "https://a.espncdn.com/guid/cbe677ee-361e-91b4-5cae-6c4c30044743/logos/secondary_logo_on_black_color.png",
    "NFL:WSH": "https://a.espncdn.com/i/teamlogos/nfl/500/wsh.png", "NFL:WAS": "https://a.espncdn.com/i/teamlogos/nfl/500/wsh.png", "NBA:WSH": "https://a.espncdn.com/i/teamlogos/nba/500/was.png", "NBA:WAS": "https://a.espncdn.com/i/teamlogos/nba/500/was.png",
    "MLB:WSH": "https://a.espncdn.com/i/teamlogos/mlb/500/wsh.png", "MLB:WAS": "https://a.espncdn.com/i/teamlogos/mlb/500/wsh.png", "NCF_FBS:WASH": "https://a.espncdn.com/i/teamlogos/ncaa/500/264.png",
    "NHL:SJS": "https://a.espncdn.com/i/teamlogos/nhl/500/sj.png", "NHL:NJD": "https://a.espncdn.com/i/teamlogos/nhl/500/nj.png", "NHL:TBL": "https://a.espncdn.com/i/teamlogos/nhl/500/tb.png", "NHL:LAK": "https://a.espncdn.com/i/teamlogos/nhl/500/la.png",
    "NHL:VGK": "https://a.espncdn.com/i/teamlogos/nhl/500/vgs.png", "NHL:VEG": "https://a.espncdn.com/i/teamlogos/nhl/500/vgs.png", "NHL:UTA": "https://a.espncdn.com/i/teamlogos/nhl/500/utah.png",
    "NCF_FBS:CAL": "https://a.espncdn.com/i/teamlogos/ncaa/500/25.png", "NCF_FBS:OSU": "https://a.espncdn.com/i/teamlogos/ncaa/500/194.png", "NCF_FBS:ORST": "https://a.espncdn.com/i/teamlogos/ncaa/500/204.png", "NCF_FCS:LIN": "https://a.espncdn.com/i/teamlogos/ncaa/500/2815.png", "NCF_FCS:LEH": "https://a.espncdn.com/i/teamlogos/ncaa/500/2329.png"
}

# Standard Game Lengths (minutes)
SPORT_DURATIONS = {
    'nfl': 195, 'ncf_fbs': 210, 'ncf_fcs': 195,
    'nba': 150, 'nhl': 150, 'mlb': 180, 'weather': 60, 'soccer': 115
}

class WeatherFetcher:
    def __init__(self, initial_loc):
        self.lat = 40.7128; self.lon = -74.0060; self.location_name = "New York"
        self.last_fetch = 0; self.cache = None
        if initial_loc: self.update_coords(initial_loc)

    def update_coords(self, location_query):
        clean_query = str(location_query).strip()
        if not clean_query: return
        if re.fullmatch(r'\d{5}', clean_query):
            try:
                r = requests.get(f"https://api.zippopotam.us/us/{clean_query}", timeout=5)
                if r.status_code == 200:
                    d = r.json(); p = d['places'][0]
                    self.lat = float(p['latitude']); self.lon = float(p['longitude'])
                    self.location_name = p['place name']; self.last_fetch = 0
                    return
            except: pass
        try:
            r = requests.get(f"https://geocoding-api.open-meteo.com/v1/search?name={clean_query}&count=1&language=en&format=json", timeout=5)
            d = r.json()
            if 'results' in d and len(d['results']) > 0:
                res = d['results'][0]
                self.lat = res['latitude']; self.lon = res['longitude']
                self.location_name = res['name']; self.last_fetch = 0 
        except: pass

    def get_icon(self, code, is_day=1):
        if code in [0, 1]: return "sun" if is_day else "moon"
        elif code in [2]: return "partly_cloudy"
        elif code in [3]: return "cloud"
        elif code in [45, 48]: return "fog"
        elif code in [51, 53, 55, 61, 63, 65, 80, 81, 82]: return "rain"
        elif code in [71, 73, 75, 77, 85, 86]: return "snow"
        elif code in [95, 96, 99]: return "storm"
        return "cloud"

    def get_weather(self):
        if time.time() - self.last_fetch < 900 and self.cache: return self.cache
        try:
            r = requests.get(f"https://api.open-meteo.com/v1/forecast?latitude={self.lat}&longitude={self.lon}&current=temperature_2m,weather_code,is_day&daily=temperature_2m_max,temperature_2m_min,uv_index_max&temperature_unit=fahrenheit&timezone=auto", timeout=5)
            d = r.json()
            c = d.get('current', {}); dl = d.get('daily', {})
            
            icon = self.get_icon(c.get('weather_code', 0), c.get('is_day', 1))
            high = int(dl['temperature_2m_max'][0]); low = int(dl['temperature_2m_min'][0]); uv = float(dl['uv_index_max'][0])
            
            w_obj = {
                "sport": "weather", "id": "weather_widget", "status": "Live",
                "home_abbr": f"{int(c.get('temperature_2m', 0))}°", "away_abbr": self.location_name,
                "home_score": "", "away_score": "", "is_shown": True, "home_logo": "", "away_logo": "",
                "home_color": "#000000", "away_color": "#000000",
                "situation": { "icon": icon, "stats": { "high": high, "low": low, "uv": uv } }
            }
            self.cache = w_obj; self.last_fetch = time.time(); return w_obj
        except: return None

class SportsFetcher:
    def __init__(self, initial_loc):
        self.weather = WeatherFetcher(initial_loc)
        self.base_url = 'http://site.api.espn.com/apis/site/v2/sports/'
        self.possession_cache = {}  
        self.leagues = {
            'nfl': { 'path': 'football/nfl', 'scoreboard_params': {}, 'team_params': {'limit': 100} },
            'ncf_fbs': { 'path': 'football/college-football', 'scoreboard_params': {'groups': '80', 'limit': 100}, 'team_params': {'groups': '80', 'limit': 1000} },
            'ncf_fcs': { 'path': 'football/college-football', 'scoreboard_params': {'groups': '81', 'limit': 100}, 'team_params': {'groups': '81', 'limit': 1000} },
            'mlb': { 'path': 'baseball/mlb', 'scoreboard_params': {}, 'team_params': {'limit': 100} },
            'nhl': { 'path': 'hockey/nhl', 'scoreboard_params': {}, 'team_params': {'limit': 100} },
            'nba': { 'path': 'basketball/nba', 'scoreboard_params': {}, 'team_params': {'limit': 100} },
            # --- NEW SPORTS ---
            'soccer_epl': { 'path': 'soccer/eng.1', 'scoreboard_params': {}, 'team_params': {}, 'group': 'soccer' },
            'soccer_mls': { 'path': 'soccer/usa.1', 'scoreboard_params': {}, 'team_params': {}, 'group': 'soccer' },
            'soccer_ucl': { 'path': 'soccer/uefa.champions', 'scoreboard_params': {}, 'team_params': {}, 'group': 'soccer' },
            'soccer_esp': { 'path': 'soccer/esp.1', 'scoreboard_params': {}, 'team_params': {}, 'group': 'soccer' },
            'soccer_ger': { 'path': 'soccer/ger.1', 'scoreboard_params': {}, 'team_params': {}, 'group': 'soccer' },
            # Leaderboard Sports
            'golf': { 'path': 'golf/pga', 'type': 'leaderboard' },
            'f1': { 'path': 'racing/f1', 'type': 'leaderboard' },
            'nascar': { 'path': 'racing/nascar', 'type': 'leaderboard' },
            'indycar': { 'path': 'racing/indycar', 'type': 'leaderboard' },
            'wec': { 'path': 'racing/wec', 'type': 'leaderboard' },
            'imsa': { 'path': 'racing/imsa', 'type': 'leaderboard' }
        }

    def get_corrected_logo(self, league_key, abbr, default_logo):
        key = f"{league_key.upper()}:{abbr}"
        return LOGO_OVERRIDES.get(key, default_logo)

    def lookup_team_info_from_cache(self, league, abbr):
        search_abbr = ABBR_MAPPING.get(abbr, abbr)
        try:
            with data_lock:
                teams = state['all_teams_data'].get(league, [])
                for t in teams:
                    if t['abbr'] == search_abbr:
                        return {'color': t.get('color', '000000'), 'alt_color': t.get('alt_color', '444444')}
        except: pass
        return {'color': '000000', 'alt_color': '444444'}

    def calculate_game_timing(self, sport, start_utc, period, status_detail):
        duration = SPORT_DURATIONS.get(sport, 180) 
        ot_padding = 0
        
        # Heuristic OT Detection
        if 'OT' in str(status_detail) or 'S/O' in str(status_detail):
            if sport in ['nba', 'nfl', 'ncf_fbs', 'ncf_fcs']:
                ot_count = 1
                if '2OT' in status_detail: ot_count = 2
                elif '3OT' in status_detail: ot_count = 3
                ot_padding = ot_count * 20
            elif sport == 'nhl':
                ot_padding = 20 # Standard 20m for OT/SO
            elif sport == 'mlb' and period > 9:
                ot_padding = (period - 9) * 20
        
        return duration + ot_padding

    def fetch_all_teams(self):
        try:
            teams_catalog = {k: [] for k in self.leagues.keys()}
            # Fetch simple leagues
            for league_key in ['nfl', 'mlb', 'nhl', 'nba']:
                self._fetch_simple_league(league_key, teams_catalog)

            # Fetch College
            url = f"{self.base_url}football/college-football/teams"
            r = requests.get(url, params={'limit': 1000, 'groups': '80,81'}, headers=HEADERS, timeout=10) 
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
                            league_tag = 'ncf_fbs' if t_abbr in FBS_TEAMS else 'ncf_fcs'
                            t_logo = self.get_corrected_logo(league_tag, t_abbr, t_logo)
                            team_obj = {'abbr': t_abbr, 'logo': t_logo, 'color': t_clr, 'alt_color': t_alt}
                            if t_abbr in FBS_TEAMS:
                                if not any(x['abbr'] == t_abbr for x in teams_catalog['ncf_fbs']):
                                    teams_catalog['ncf_fbs'].append(team_obj)
                            elif t_abbr in FCS_TEAMS:
                                if not any(x['abbr'] == t_abbr for x in teams_catalog['ncf_fcs']):
                                    teams_catalog['ncf_fcs'].append(team_obj)
            with data_lock:
                state['all_teams_data'] = teams_catalog
        except: pass

    def _fetch_simple_league(self, league_key, catalog):
        config = self.leagues[league_key]
        if 'team_params' not in config: return
        try:
            r = requests.get(f"{self.base_url}{config['path']}/teams", params=config['team_params'], headers=HEADERS, timeout=10)
            data = r.json()
            if 'sports' in data:
                for sport in data['sports']:
                    for league in sport['leagues']:
                        for item in league.get('teams', []):
                            abbr = item['team'].get('abbreviation', 'unk')
                            clr = item['team'].get('color', '000000')
                            alt = item['team'].get('alternateColor', '444444')
                            logo = item['team'].get('logos', [{}])[0].get('href', '')
                            logo = self.get_corrected_logo(league_key, abbr, logo)
                            catalog[league_key].append({'abbr': abbr, 'logo': logo, 'color': clr, 'alt_color': alt})
        except: pass

    # === NEW: LEADERBOARD FETCHER ===
    def fetch_leaderboard_event(self, league_key, config, games_list, conf):
        try:
            url = f"{self.base_url}{config['path']}/scoreboard"
            r = requests.get(url, headers=HEADERS, timeout=5)
            data = r.json()
            
            for e in data.get('events', []):
                name = e.get('name', e.get('shortName', 'Tournament'))
                status_obj = e.get('status', {})
                state = status_obj.get('type', {}).get('state', 'pre')
                
                # Check date for caching/display logic
                utc_str = e['date'].replace('Z', '')
                try:
                    game_dt_utc = dt.fromisoformat(utc_str).replace(tzinfo=timezone.utc)
                    local_now = dt.now(timezone.utc)
                    diff_hours = (game_dt_utc - local_now).total_seconds() / 3600
                except: diff_hours = 0

                # Only show active or recently finished/upcoming events (Last 24h, Next 48h)
                if state == 'pre' and diff_hours > 48: continue
                if state == 'post' and diff_hours < -24: continue

                comps = e.get('competitions', [])
                if not comps: continue
                comp = comps[0]
                
                leaders = []
                raw_competitors = comp.get('competitors', [])
                
                # Try sorting by 'curatedRank' or 'order'
                try:
                    sorted_comps = sorted(raw_competitors, key=lambda x: int(x.get('curatedRank', x.get('order', 999))))
                except: sorted_comps = raw_competitors

                for c in sorted_comps[:5]: # Top 5 only
                    athlete = c.get('athlete', {})
                    disp_name = athlete.get('displayName', c.get('team',{}).get('displayName','Unk'))
                    if ' ' in disp_name: disp_name = disp_name.split(' ')[-1] # Shorten Name
                    
                    rank = c.get('curatedRank', c.get('order', '-'))
                    score = c.get('score', '')
                    
                    # For racing, get gap/points if available
                    if 'racing' in config['path']:
                        lines = c.get('linescores', [])
                        if lines: score = lines[-1].get('value', score)
                    
                    leaders.append({'rank': str(rank), 'name': disp_name, 'score': str(score)})

                game_obj = {
                    'sport': league_key, 'id': e['id'],
                    'status': status_obj.get('type', {}).get('shortDetail', 'Live'),
                    'state': state, 'tourney_name': name,
                    'leaders': leaders, 'is_shown': True,
                    'startTimeUTC': e['date']
                }
                games_list.append(game_obj)
        except: pass

    def _fetch_nhl_native(self, games_list, target_date_str):
        with data_lock: 
            is_nhl = state['active_sports'].get('nhl', False)
            utc_offset = state.get('utc_offset', -4)
        
        if not is_nhl: return
        processed_ids = set()
        
        try:
            r = requests.get("https://api-web.nhle.com/v1/schedule/now", headers=HEADERS, timeout=5)
            if r.status_code != 200: return
            
            for d in r.json().get('gameWeek', []):
                day_games = d.get('games', [])
                is_target_date = (d.get('date') == target_date_str)
                has_active_games = any(g.get('gameState') in ['LIVE', 'CRIT'] for g in day_games)
                
                if is_target_date or has_active_games:
                    for g in day_games:
                        gid = g['id']
                        if gid in processed_ids: continue
                        processed_ids.add(gid)

                        h_ab = g['homeTeam']['abbrev']; a_ab = g['awayTeam']['abbrev']
                        h_sc = str(g['homeTeam'].get('score', 0)); a_sc = str(g['awayTeam'].get('score', 0))
                        st = g.get('gameState', 'OFF')
                        
                        h_lg = self.get_corrected_logo('nhl', h_ab, f"https://a.espncdn.com/i/teamlogos/nhl/500/{h_ab.lower()}.png")
                        a_lg = self.get_corrected_logo('nhl', a_ab, f"https://a.espncdn.com/i/teamlogos/nhl/500/{a_ab.lower()}.png")
                        
                        h_info = self.lookup_team_info_from_cache('nhl', h_ab)
                        a_info = self.lookup_team_info_from_cache('nhl', a_ab)

                        map_st = 'in' if st in ['LIVE', 'CRIT'] else ('pre' if st in ['PRE', 'FUT'] else 'post')
                        
                        with data_lock:
                            mode = state['mode']; my_teams = state['my_teams']
                        
                        is_shown = True
                        if mode == 'live' and map_st != 'in': is_shown = False
                        if mode == 'my_teams':
                            h_k = f"nhl:{h_ab}"; a_k = f"nhl:{a_ab}"
                            if (h_k not in my_teams and h_ab not in my_teams) and (a_k not in my_teams and a_ab not in my_teams): is_shown = False

                        disp = "Scheduled"; pp = False; poss = ""; en = False
                        utc_start = g.get('startTimeUTC', '') 
                        
                        dur = self.calculate_game_timing('nhl', utc_start, 1, st)
                        
                        if st in ['PRE', 'FUT'] and utc_start:
                             try:
                                 dt_obj = dt.fromisoformat(utc_start.replace('Z', '+00:00'))
                                 local = dt_obj.astimezone(timezone(timedelta(hours=utc_offset)))
                                 disp = local.strftime("%I:%M %p").lstrip('0')
                             except: pass
                        elif st in ['FINAL', 'OFF']:
                             disp = "FINAL"
                             pd = g.get('periodDescriptor', {})
                             pt = pd.get('periodType', '')
                             if pt == 'OT': disp = "FINAL OT"
                             elif pt == 'SHOOTOUT': disp = "FINAL S/O"

                        if map_st == 'in':
                            try:
                                r2 = requests.get(f"https://api-web.nhle.com/v1/gamecenter/{gid}/landing", headers=HEADERS, timeout=2)
                                if r2.status_code == 200:
                                    d2 = r2.json()
                                    h_sc = str(d2['homeTeam'].get('score', h_sc))
                                    a_sc = str(d2['awayTeam'].get('score', a_sc))
                                    
                                    pd = d2.get('periodDescriptor', {})
                                    clk = d2.get('clock', {})
                                    time_rem = clk.get('timeRemaining', '00:00')
                                    is_intermission = clk.get('inIntermission', False)
                                    p_type = pd.get('periodType', '')
                                    p_num = pd.get('number', 1)
                                    
                                    dur = self.calculate_game_timing('nhl', utc_start, p_num, p_type)

                                    if p_type == 'SHOOTOUT': disp = "S/O"
                                    elif is_intermission or time_rem == "00:00":
                                        if p_num == 1: disp = "End 1st"
                                        elif p_num == 2: disp = "End 2nd"
                                        elif p_num == 3: disp = "End 3rd"
                                        elif p_num >= 4: disp = "S/O" 
                                        else: disp = "Intermission"
                                    else:
                                        p_lbl = "OT" if p_num > 3 else f"P{p_num}"
                                        disp = f"{p_lbl} {time_rem}"

                                    sit_obj = d2.get('situation', {})
                                    if sit_obj:
                                        sit = sit_obj.get('situationCode', '1551')
                                        ag = int(sit[0]); as_ = int(sit[1]); hs = int(sit[2]); hg = int(sit[3])
                                        if as_ > hs: pp=True; poss=a_ab
                                        elif hs > as_: pp=True; poss=h_ab
                                        en = (ag==0 or hg==0)
                            except: disp = "Live" 

                        games_list.append({
                            'sport': 'nhl', 'id': str(gid), 'status': disp, 'state': map_st, 'is_shown': is_shown,
                            'home_abbr': h_ab, 'home_score': h_sc, 'home_logo': h_lg, 'home_id': h_ab,
                            'away_abbr': a_ab, 'away_score': a_sc, 'away_logo': a_lg, 'away_id': a_ab,
                            'home_color': f"#{h_info['color']}", 'home_alt_color': f"#{h_info['alt_color']}",
                            'away_color': f"#{a_info['color']}", 'away_alt_color': f"#{a_info['alt_color']}",
                            'startTimeUTC': utc_start,
                            'estimated_duration': dur,
                            'situation': { 'powerPlay': pp, 'possession': poss, 'emptyNet': en }
                        })
        except: pass

    def get_real_games(self):
        games = []
        with data_lock: conf = state.copy()
        
        utc_offset = conf.get('utc_offset', -4)

        if conf['active_sports'].get('clock'):
            with data_lock: state['current_games'] = [{'sport':'clock','id':'clk','is_shown':True}]; return
        if conf['active_sports'].get('weather'):
            if conf['weather_location'] != self.weather.location_name: self.weather.update_coords(conf['weather_location'])
            w = self.weather.get_weather()
            if w: 
                with data_lock: state['current_games'] = [w]; return

        req_params = {}
        now_local = dt.now(timezone(timedelta(hours=utc_offset)))
        if conf['debug_mode'] and conf['custom_date']:
            target_date_str = conf['custom_date']
        else:
            if now_local.hour < 4: query_date = now_local - timedelta(days=1)
            else: query_date = now_local
            target_date_str = query_date.strftime("%Y-%m-%d")

        req_params['dates'] = target_date_str.replace('-', '')

        for league_key, config in self.leagues.items():
            # Handle Grouping (e.g. all soccer leagues checked by 'soccer' toggle)
            check_key = config.get('group', league_key)
            if not conf['active_sports'].get(check_key, False): continue
            
            # --- LEADERBOARD LOGIC (New Sports) ---
            if config.get('type') == 'leaderboard':
                self.fetch_leaderboard_event(league_key, config, games, conf)
                continue
            
            # === HYBRID NHL LOGIC ===
            if league_key == 'nhl' and not conf['debug_mode']:
                prev_count = len(games)
                self._fetch_nhl_native(games, target_date_str)
                if len(games) > prev_count: continue 

            try:
                curr_p = config.get('scoreboard_params', {}).copy(); curr_p.update(req_params)
                r = requests.get(f"{self.base_url}{config['path']}/scoreboard", params=curr_p, headers=HEADERS, timeout=5)
                data = r.json()
                
                for e in data.get('events', []):
                    utc_str = e['date'].replace('Z', '') 
                    utc_start_iso = e['date']
                    
                    game_dt_utc = dt.fromisoformat(utc_str).replace(tzinfo=timezone.utc)
                    game_dt_server = game_dt_utc.astimezone(timezone(timedelta(hours=utc_offset)))
                    game_date_str = game_dt_server.strftime("%Y-%m-%d")
                    
                    st = e.get('status', {}); tp = st.get('type', {}); gst = tp.get('state', 'pre')
                    
                    keep_date = (gst == 'in') or (game_date_str == target_date_str)
                    if league_key == 'mlb' and not keep_date: continue
                    if not keep_date: continue

                    comp = e['competitions'][0]; h = comp['competitors'][0]; a = comp['competitors'][1]
                    h_ab = h['team']['abbreviation']; a_ab = a['team']['abbreviation']
                    
                    if league_key == 'ncf_fbs':
                        if h_ab not in FBS_TEAMS and a_ab not in FBS_TEAMS: continue
                    elif league_key == 'ncf_fcs':
                        if h_ab not in FCS_TEAMS and a_ab not in FCS_TEAMS: continue

                    is_shown = True
                    if conf['mode'] == 'live' and gst not in ['in', 'half']: is_shown = False
                    elif conf['mode'] == 'my_teams':
                        hk = f"{league_key}:{h_ab}"; ak = f"{league_key}:{a_ab}"
                        if (hk not in conf['my_teams'] and h_ab not in conf['my_teams']) and \
                           (ak not in conf['my_teams'] and a_ab not in conf['my_teams']): is_shown = False

                    h_lg = self.get_corrected_logo(league_key, h_ab, h['team'].get('logo',''))
                    a_lg = self.get_corrected_logo(league_key, a_ab, a['team'].get('logo',''))

                    h_clr = h['team'].get('color', '000000')
                    h_alt = h['team'].get('alternateColor', 'ffffff')
                    a_clr = a['team'].get('color', '000000')
                    a_alt = a['team'].get('alternateColor', 'ffffff')

                    s_disp = tp.get('shortDetail', 'TBD')
                    
                    p = st.get('period', 1)
                    
                    # --- Time Calculation ---
                    dur = self.calculate_game_timing(league_key, utc_start_iso, p, s_disp)

                    if gst == 'pre':
                        try:
                            s_disp = game_dt_server.strftime("%I:%M %p").lstrip('0')
                        except: s_disp = "Scheduled"
                    elif gst == 'in' or gst == 'half':
                        clk = st.get('displayClock', '')
                        if gst == 'half' or (p == 2 and clk == '0:00' and 'football' in config['path']):
                            s_disp = "Halftime"
                            is_halftime = True
                        elif 'hockey' in config['path'] and clk == '0:00':
                             if p == 1: s_disp = "End 1st"
                             elif p == 2: s_disp = "End 2nd"
                             elif p == 3: s_disp = "End 3rd"
                             elif p >= 4: s_disp = "S/O" 
                             else: s_disp = "Intermission"
                        else:
                            s_disp = f"P{p} {clk}" if 'hockey' in config['path'] else f"Q{p} {clk}"
                            if 'soccer' in config['path']: s_disp = f"{clk}'"
                    else:
                        s_disp = s_disp.replace("Final", "FINAL").replace("/OT", " OT").replace("/SO", " S/O")
                        # Fallback for "FINAL" string but high period count
                        if s_disp == "FINAL" and league_key == 'nhl':
                            if p == 4: s_disp = "FINAL OT"
                            elif p > 4: s_disp = "FINAL S/O"

                    sit = comp.get('situation', {})
                    is_halftime = (s_disp == "Halftime")

                    curr_poss = sit.get('possession')
                    if curr_poss: self.possession_cache[e['id']] = curr_poss
                    
                    if gst == 'pre': curr_poss = '' 
                    elif is_halftime or gst in ['post', 'final']:
                         curr_poss = '' 
                         self.possession_cache[e['id']] = '' 
                    else:
                         if not curr_poss: curr_poss = self.possession_cache.get(e['id'], '')
                    
                    down_text = sit.get('downDistanceText', '')
                    if is_halftime: down_text = ''

                    game_obj = {
                        'sport': check_key, 'id': e['id'], 'status': s_disp, 'state': gst, 'is_shown': is_shown,
                        'home_abbr': h_ab, 'home_score': h.get('score','0'), 'home_logo': h_lg,
                        'home_id': h.get('id'), 
                        'away_abbr': a_ab, 'away_score': a.get('score','0'), 'away_logo': a_lg,
                        'away_id': a.get('id'), 
                        'home_color': f"#{h_clr}", 'home_alt_color': f"#{h_alt}",
                        'away_color': f"#{a_clr}", 'away_alt_color': f"#{a_alt}",
                        'startTimeUTC': utc_start_iso, 
                        'estimated_duration': dur,
                        'period': p,
                        'situation': { 
                            'possession': curr_poss, 
                            'isRedZone': sit.get('isRedZone', False), 
                            'downDist': down_text 
                        }
                    }
                    if league_key == 'mlb':
                        game_obj['situation'] = { 'balls': sit.get('balls', 0), 'strikes': sit.get('strikes', 0), 'outs': sit.get('outs', 0), 'onFirst': sit.get('onFirst', False), 'onSecond': sit.get('onSecond', False), 'onThird': sit.get('onThird', False) }
                    
                    games.append(game_obj)
            except: pass
        
        with data_lock: state['current_games'] = games

fetcher = SportsFetcher(state['weather_location'])

def background_updater():
    fetcher.fetch_all_teams()
    while True: fetcher.get_real_games(); time.sleep(UPDATE_INTERVAL)

# ================= FLASK API =================
app = Flask(__name__)

@app.route('/')
def root():
    html = """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
        <title>Game Schedule</title>
        <style>
            body { font-family: 'Segoe UI', system-ui, sans-serif; background: #121212; color: #e0e0e0; margin: 0; padding: 20px; }
            h2 { border-bottom: 1px solid #333; padding-bottom: 10px; }
            .control-group { margin-bottom: 20px; background: #1e1e1e; padding: 15px; border-radius: 8px; }
            .toggle-row { display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; font-size: 1rem; }
            .switch { position: relative; display: inline-block; width: 40px; height: 24px; }
            .switch input { opacity: 0; width: 0; height: 0; }
            .slider { position: absolute; cursor: pointer; top: 0; left: 0; right: 0; bottom: 0; background-color: #444; transition: .4s; border-radius: 34px; }
            .slider:before { position: absolute; content: ""; height: 18px; width: 18px; left: 3px; bottom: 3px; background-color: white; transition: .4s; border-radius: 50%; }
            input:checked + .slider { background-color: #007bff; }
            input:checked + .slider:before { transform: translateX(16px); }
            input[type="text"], input[type="range"] { width: 100%; padding: 8px; border-radius: 4px; border: 1px solid #333; background: #222; color: white; margin-top:5px;}
            button { width: 100%; padding: 12px; background: #007bff; border: none; color: white; border-radius: 6px; font-size: 1.1rem; cursor: pointer; margin-top: 20px; }
        </style>
    </head>
    <body>
        <h2>Ticker Settings</h2>
        
        <div class="control-group">
            <div style="font-weight:bold; margin-bottom:10px; color:#aaa;">ACTIVE SPORTS</div>
            <div class="toggle-row"><span>NFL</span><label class="switch"><input type="checkbox" id="chk_nfl"><span class="slider"></span></label></div>
            <div class="toggle-row"><span>NBA</span><label class="switch"><input type="checkbox" id="chk_nba"><span class="slider"></span></label></div>
            <div class="toggle-row"><span>NHL</span><label class="switch"><input type="checkbox" id="chk_nhl"><span class="slider"></span></label></div>
            <div class="toggle-row"><span>MLB</span><label class="switch"><input type="checkbox" id="chk_mlb"><span class="slider"></span></label></div>
            <div class="toggle-row"><span>NCAA FBS</span><label class="switch"><input type="checkbox" id="chk_ncf_fbs"><span class="slider"></span></label></div>
            <div class="toggle-row"><span>Soccer</span><label class="switch"><input type="checkbox" id="chk_soccer"><span class="slider"></span></label></div>
            <div class="toggle-row"><span>Golf (PGA)</span><label class="switch"><input type="checkbox" id="chk_golf"><span class="slider"></span></label></div>
            <hr style="border-color:#333">
            <div class="toggle-row"><span>Formula 1</span><label class="switch"><input type="checkbox" id="chk_f1"><span class="slider"></span></label></div>
            <div class="toggle-row"><span>NASCAR</span><label class="switch"><input type="checkbox" id="chk_nascar"><span class="slider"></span></label></div>
            <div class="toggle-row"><span>IndyCar</span><label class="switch"><input type="checkbox" id="chk_indycar"><span class="slider"></span></label></div>
            <div class="toggle-row"><span>IMSA</span><label class="switch"><input type="checkbox" id="chk_imsa"><span class="slider"></span></label></div>
            <div class="toggle-row"><span>WEC</span><label class="switch"><input type="checkbox" id="chk_wec"><span class="slider"></span></label></div>
            <hr style="border-color:#333">
            <div class="toggle-row"><span>Weather</span><label class="switch"><input type="checkbox" id="chk_weather"><span class="slider"></span></label></div>
            <div class="toggle-row"><span>Clock</span><label class="switch"><input type="checkbox" id="chk_clock"><span class="slider"></span></label></div>
        </div>

        <div class="control-group">
            <div style="font-weight:bold; margin-bottom:10px; color:#aaa;">CONFIGURATION</div>
            <div style="margin-bottom:10px;">
                <label>My Teams (Comma Separated)</label>
                <input type="text" id="inp_teams" placeholder="NYG, NYY, NJD...">
            </div>
            <div style="margin-bottom:10px;">
                <label>Weather Location (Zip or City)</label>
                <input type="text" id="inp_loc">
            </div>
            <div class="toggle-row"><span>Seamless Scroll</span><label class="switch"><input type="checkbox" id="chk_scroll"><span class="slider"></span></label></div>
            <div style="margin-top:10px;">
                <label>Brightness</label>
                <input type="range" id="rng_bright" min="0.1" max="1.0" step="0.1">
            </div>
        </div>

        <button onclick="saveSettings()">Save Changes</button>

        <script>
            async function load() {
                try {
                    const res = await fetch('/api/state');
                    const d = await res.json();
                    const s = d.settings;
                    
                    const keys = ['nfl','nba','nhl','mlb','ncf_fbs','soccer','golf','f1','nascar','indycar','imsa','wec','weather','clock'];
                    keys.forEach(k => {
                        if(document.getElementById('chk_'+k)) document.getElementById('chk_'+k).checked = s.active_sports[k];
                    });
                    
                    document.getElementById('inp_teams').value = (s.my_teams || []).join(', ');
                    document.getElementById('inp_loc').value = s.weather_location;
                    document.getElementById('chk_scroll').checked = s.scroll_seamless;
                    document.getElementById('rng_bright').value = s.brightness;
                } catch(e) { console.log(e); }
            }

            async function saveSettings() {
                const active = {};
                ['nfl','nba','nhl','mlb','ncf_fbs','soccer','golf','f1','nascar','indycar','imsa','wec','weather','clock'].forEach(k => {
                    active[k] = document.getElementById('chk_'+k).checked;
                });
                
                const payload = {
                    active_sports: active,
                    my_teams: document.getElementById('inp_teams').value.split(',').map(s=>s.trim()).filter(s=>s),
                    weather_location: document.getElementById('inp_loc').value,
                    scroll_seamless: document.getElementById('chk_scroll').checked,
                    brightness: parseFloat(document.getElementById('rng_bright').value)
                };
                
                await fetch('/api/config', { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(payload) });
                alert("Settings Saved!");
            }
            load();
        </script>
    </body>
    </html>
    """
    return render_template_string(html)

@app.route('/api/ticker')
def api_ticker():
    with data_lock: d = state.copy()
    offset_sec = d.get('utc_offset', -5) * 3600
    
    raw_games = d['current_games']
    processed_games = []
    
    for g in raw_games:
        if not g.get('is_shown', True): continue
        processed_games.append(g.copy())

    return jsonify({
        'meta': {
            'time': dt.now(timezone(timedelta(seconds=offset_sec))).strftime("%I:%M %p"), 
            'count': len(processed_games), 
            'scroll_seamless': d['scroll_seamless'], 
            'brightness': d['brightness'], 
            'scroll_speed': d.get('scroll_speed', 5),
            'inverted': d['inverted'], 
            'panel_count': d['panel_count'], 
            'test_pattern': d['test_pattern'], 
            'reboot_requested': d['reboot_requested']
        }, 
        'games': processed_games
    })

@app.route('/api/state')
def api_state():
    with data_lock: return jsonify({'settings': state, 'games': state['current_games']})

@app.route('/api/teams')
def api_teams():
    with data_lock: return jsonify(state['all_teams_data'])

@app.route('/api/config', methods=['POST'])
def api_config():
    with data_lock: state.update(request.json)
    save_config_file()
    threading.Thread(target=fetcher.get_real_games).start()
    return jsonify({"status": "ok"})

@app.route('/api/debug', methods=['POST'])
def api_debug():
    with data_lock: state.update(request.json)
    fetcher.get_real_games()
    return jsonify({"status": "ok"})

@app.route('/api/hardware', methods=['POST'])
def api_hardware():
    d = request.json
    if d.get('action') == 'reboot':
        with data_lock: state['reboot_requested'] = True
        threading.Timer(10, lambda: state.update({'reboot_requested': False})).start()
    elif d.get('action') == 'test_pattern':
        with data_lock: 
            state['test_pattern'] = not state['test_pattern']
            state['test_pattern_ts'] = time.time()
    else:
        with data_lock: state.update(d)
        save_config_file()
    return jsonify({"status": "ok", "settings": state})

if __name__ == "__main__":
    threading.Thread(target=background_updater, daemon=True).start()
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 5000)))
