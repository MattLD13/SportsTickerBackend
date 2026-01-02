import time
import threading
import json
import os
import re
import traceback
import random
from datetime import datetime as dt, timezone, timedelta
import requests
from flask import Flask, jsonify, request, render_template_string

# ================= CONFIGURATION =================
CONFIG_FILE = "ticker_config.json"
UPDATE_INTERVAL = 5
data_lock = threading.Lock()

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache"
}

# ================= DEFAULT STATE =================
default_state = {
    'active_sports': { 
        'nfl': True, 'ncf_fbs': True, 'ncf_fcs': True, 
        'mlb': True, 'nhl': True, 'nba': True, 
        'soccer_epl': True, 'soccer_mls': True, 
        'golf': True, 
        'racing_f1': True, 'racing_nascar': True, 'racing_indycar': True,
        'racing_wec': True, 'racing_imsa': True,
        'weather': False, 'clock': False 
    },
    'mode': 'all', 
    'layout_mode': 'schedule',
    'scroll_seamless': False,
    'my_teams': ["NYG", "NYY", "NJD", "NYK", "LAL", "BOS", "KC", "BUF", "LEH", "LIV", "MCI", "TOT", "ARS", "VER", "HAM", "NOR"], 
    'current_games': [],
    'all_teams_data': {}, 
    'debug_mode': False,
    'demo_mode': False,
    'custom_date': None,
    'brightness': 0.5,
    'scroll_speed': 5,
    'inverted': False,
    'panel_count': 2,
    'test_pattern': False,
    'reboot_requested': False,
    'weather_location': "New York",
    'utc_offset': -5 
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
                'utc_offset': state['utc_offset'],
                'demo_mode': state['demo_mode']
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
    'NY': 'NYK', 'NO': 'NOP', 'GS': 'GSW', 'SA': 'SAS',
    'TOT': 'TOT', 'ARS': 'ARS', 'LIV': 'LIV', 'MCI': 'MCI', 'MUN': 'MUN', 'CHE': 'CHE'
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
    "NCF_FBS:CAL": "https://a.espncdn.com/i/teamlogos/ncaa/500/25.png", "NCF_FBS:OSU": "https://a.espncdn.com/i/teamlogos/ncaa/500/194.png", "NCF_FBS:ORST": "https://a.espncdn.com/i/teamlogos/ncaa/500/204.png", "NCF_FCS:LIN": "https://a.espncdn.com/i/teamlogos/ncaa/500/2815.png", "NCF_FCS:LEH": "https://a.espncdn.com/i/teamlogos/ncaa/500/2329.png",
    "SOCCER_EPL:TOT": "https://a.espncdn.com/i/teamlogos/soccer/500/367.png",
    "SOCCER_EPL:ARS": "https://a.espncdn.com/i/teamlogos/soccer/500/359.png",
    "SOCCER_EPL:LIV": "https://a.espncdn.com/i/teamlogos/soccer/500/364.png"
}

SPORT_DURATIONS = {
    'nfl': 195, 'ncf_fbs': 210, 'ncf_fcs': 195,
    'nba': 150, 'nhl': 150, 'mlb': 180, 'weather': 60,
    'soccer_epl': 110, 'soccer_mls': 110, 
    'golf': 720, 'racing_f1': 120, 'racing_nascar': 240, 'racing_indycar': 180,
    'racing_wec': 360, 'racing_imsa': 360
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
            'soccer_epl': { 'path': 'soccer/eng.1', 'scoreboard_params': {}, 'team_params': {} },
            'soccer_mls': { 'path': 'soccer/usa.1', 'scoreboard_params': {}, 'team_params': {} },
            
            # ESPN FALLBACKS (Golf, Indy, WEC, IMSA)
            'golf': { 'path': 'golf/pga', 'scoreboard_params': {}, 'team_params': {} },
            'racing_indycar': { 'path': 'racing/indycar', 'scoreboard_params': {}, 'team_params': {} },
            'racing_wec': { 'path': 'racing/racing', 'scoreboard_params': {}, 'team_params': {} },
            'racing_imsa': { 'path': 'racing/racing', 'scoreboard_params': {}, 'team_params': {} }
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

    def fetch_all_teams(self):
        try:
            teams_catalog = {k: [] for k in self.leagues.keys()}
            for league_key in ['nfl', 'mlb', 'nhl', 'nba']:
                self._fetch_simple_league(league_key, teams_catalog)
            
            url = f"{self.base_url}football/college-football/teams"
            r = requests.get(url, params={'limit': 1000, 'groups': '80,81'}, headers=HEADERS, timeout=10) 
            if r.status_code == 200:
                data = r.json()
                if 'sports' in data:
                    for sport in data['sports']:
                        for league in sport['leagues']:
                            for item in league.get('teams', []):
                                t_abbr = item['team'].get('abbreviation', 'unk'); t_clr = item['team'].get('color', '000000')
                                t_alt = item['team'].get('alternateColor', '444444'); t_logo = item['team'].get('logos', [{}])[0].get('href', '')
                                league_tag = 'ncf_fbs' if t_abbr in FBS_TEAMS else 'ncf_fcs'
                                t_logo = self.get_corrected_logo(league_tag, t_abbr, t_logo)
                                team_obj = {'abbr': t_abbr, 'logo': t_logo, 'color': t_clr, 'alt_color': t_alt}
                                if t_abbr in FBS_TEAMS and not any(x['abbr'] == t_abbr for x in teams_catalog['ncf_fbs']): teams_catalog['ncf_fbs'].append(team_obj)
                                elif t_abbr in FCS_TEAMS and not any(x['abbr'] == t_abbr for x in teams_catalog['ncf_fcs']): teams_catalog['ncf_fcs'].append(team_obj)
            with data_lock: state['all_teams_data'] = teams_catalog
        except: pass

    def _fetch_simple_league(self, league_key, catalog):
        config = self.leagues[league_key]
        try:
            r = requests.get(f"{self.base_url}{config['path']}/teams", params=config['team_params'], headers=HEADERS, timeout=10)
            if r.status_code == 200:
                data = r.json()
                if 'sports' in data:
                    for sport in data['sports']:
                        for league in sport['leagues']:
                            for item in league.get('teams', []):
                                abbr = item['team'].get('abbreviation', 'unk'); clr = item['team'].get('color', '000000')
                                alt = item['team'].get('alternateColor', '444444'); logo = item['team'].get('logos', [{}])[0].get('href', '')
                                catalog[league_key].append({'abbr': abbr, 'logo': logo, 'color': clr, 'alt_color': alt})
        except: pass

    def _fetch_nhl_native(self, games_list, target_date_str):
        with data_lock: is_nhl = state['active_sports'].get('nhl', False); utc_offset = state.get('utc_offset', -4)
        if not is_nhl: return
        processed_ids = set()
        try:
            r = requests.get("https://api-web.nhle.com/v1/schedule/now", headers=HEADERS, timeout=5)
            if r.status_code != 200: return
            for d in r.json().get('gameWeek', []):
                day_games = d.get('games', [])
                if (d.get('date') == target_date_str) or any(g.get('gameState') in ['LIVE', 'CRIT'] for g in day_games):
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
                        
                        with data_lock: mode = state['mode']; my_teams = state['my_teams']
                        is_shown = True
                        if mode == 'live' and map_st != 'in': is_shown = False
                        if mode == 'my_teams':
                            if (f"nhl:{h_ab}" not in my_teams and h_ab not in my_teams) and (f"nhl:{a_ab}" not in my_teams and a_ab not in my_teams): is_shown = False

                        disp = "Scheduled"; pp = False; poss = ""; en = False; utc_start = g.get('startTimeUTC', '') 
                        dur = self.calculate_game_timing('nhl', utc_start, 1, st)
                        
                        if st in ['PRE', 'FUT'] and utc_start:
                             try:
                                 dt_obj = dt.fromisoformat(utc_start.replace('Z', '+00:00'))
                                 local = dt_obj.astimezone(timezone(timedelta(hours=utc_offset)))
                                 disp = local.strftime("%I:%M %p").lstrip('0')
                             except: pass
                        elif st in ['FINAL', 'OFF']:
                             disp = "FINAL"
                             if g.get('periodDescriptor', {}).get('periodType') == 'OT': disp = "FINAL OT"
                             elif g.get('periodDescriptor', {}).get('periodType') == 'SHOOTOUT': disp = "FINAL S/O"

                        if map_st == 'in':
                            try:
                                r2 = requests.get(f"https://api-web.nhle.com/v1/gamecenter/{gid}/landing", headers=HEADERS, timeout=2)
                                if r2.status_code == 200:
                                    d2 = r2.json()
                                    h_sc = str(d2['homeTeam'].get('score', h_sc)); a_sc = str(d2['awayTeam'].get('score', a_sc))
                                    pd = d2.get('periodDescriptor', {}); clk = d2.get('clock', {})
                                    time_rem = clk.get('timeRemaining', '00:00'); is_intermission = clk.get('inIntermission', False)
                                    p_type = pd.get('periodType', ''); p_num = pd.get('number', 1)
                                    dur = self.calculate_game_timing('nhl', utc_start, p_num, p_type)
                                    if p_type == 'SHOOTOUT': disp = "S/O"
                                    elif is_intermission or time_rem == "00:00":
                                        if p_num <= 3: disp = f"End {p_num}{'st' if p_num==1 else 'nd' if p_num==2 else 'rd'}"
                                        else: disp = "Intermission"
                                    else: disp = f"{'OT' if p_num > 3 else 'P'+str(p_num)} {time_rem}"
                                    
                                    sit_obj = d2.get('situation', {})
                                    if sit_obj:
                                        sit = sit_obj.get('situationCode', '1551')
                                        if int(sit[1]) > int(sit[2]): pp=True; poss=a_ab
                                        elif int(sit[2]) > int(sit[1]): pp=True; poss=h_ab
                                        en = (int(sit[0])==0 or int(sit[3])==0)
                            except: disp = "Live" 

                        games_list.append({
                            'sport': 'nhl', 'id': str(gid), 'status': disp, 'state': map_st, 'is_shown': is_shown,
                            'home_abbr': h_ab, 'home_score': h_sc, 'home_logo': h_lg, 'home_id': h_ab,
                            'away_abbr': a_ab, 'away_score': a_sc, 'away_logo': a_lg, 'away_id': a_ab,
                            'home_color': f"#{h_info['color']}", 'home_alt_color': f"#{h_info['alt_color']}",
                            'away_color': f"#{a_info['color']}", 'away_alt_color': f"#{a_info['alt_color']}",
                            'startTimeUTC': utc_start, 'estimated_duration': dur,
                            'situation': { 'powerPlay': pp, 'possession': poss, 'emptyNet': en }
                        })
        except: pass

    # === F1 SPECIFIC FETCHER (OpenF1) ===
    def _fetch_f1_openf1(self, games_list):
        if not state['active_sports'].get('racing_f1', False): return
        try:
            year = dt.now().year
            r = requests.get(f"https://api.openf1.org/v1/sessions?year={year}", timeout=5)
            if r.status_code != 200: return
            sessions = r.json()
            if not sessions: return
            
            sorted_sess = sorted(sessions, key=lambda x: x['date_start'], reverse=True)
            sess = sorted_sess[0]
            sess_key = sess['session_key']
            t_name = f"{sess['location']} - {sess['session_name']}"
            
            r2 = requests.get(f"https://api.openf1.org/v1/position?session_key={sess_key}", timeout=5)
            if r2.status_code != 200: return
            positions = r2.json()
            
            driver_map = {}
            for p in positions:
                driver_map[p['driver_number']] = p
            
            r3 = requests.get(f"https://api.openf1.org/v1/drivers?session_key={sess_key}", timeout=5)
            if r3.status_code != 200: return
            drivers = {d['driver_number']: d['last_name'] for d in r3.json()}
            
            leaders = []
            sorted_drivers = sorted(driver_map.values(), key=lambda x: x['position'])
            
            for d in sorted_drivers[:4]:
                num = d['driver_number']
                name = drivers.get(num, str(num))
                leaders.append({'rank': d['position'], 'name': name[:3].upper(), 'score': ''})
                
            games_list.append({
                'sport': 'racing_f1', 'id': f"f1_{sess_key}", 'status': 'Live' if sess['date_end'] > dt.utcnow().isoformat() else 'Final',
                'state': 'in', 'is_shown': True, 'tourney_name': t_name, 'leaders': leaders,
                'home_abbr': 'F1', 'away_abbr': 'F1', 'home_color': '#FF0000', 'away_color': '#FFFFFF'
            })
        except Exception as e: print(f"OpenF1 Error: {e}")

    # === NASCAR NATIVE FETCHER ===
    def _fetch_nascar_native(self, games_list):
        if not state['active_sports'].get('racing_nascar', False): return
        try:
            r = requests.get("https://cf.nascar.com/live/feeds/live-feed.json", timeout=5)
            if r.status_code != 200: return
            data = r.json()
            
            run_name = data.get('run_name', 'NASCAR')
            vehicles = data.get('vehicles', [])
            leaders = []
            sorted_v = sorted(vehicles, key=lambda x: x.get('running_position', 999))
            
            for v in sorted_v[:4]:
                name = v.get('driver_name', 'Unknown')
                if ' ' in name: name = name.split(' ')[-1]
                delta = v.get('delta', '')
                if delta and float(delta) < 0: delta = "LEAD"
                elif delta: delta = f"+{delta}"
                leaders.append({'rank': v.get('running_position'), 'name': name, 'score': delta})
            
            if leaders:
                games_list.append({
                    'sport': 'racing_nascar', 'id': 'nascar_live', 'status': f"Lap {data.get('lap_number')}",
                    'state': 'in', 'is_shown': True, 'tourney_name': run_name, 'leaders': leaders,
                    'home_abbr': 'NASCAR', 'away_abbr': 'NASCAR', 'home_color': '#0000FF', 'away_color': '#FFFFFF'
                })
        except: pass

    # === GENERIC ESPN LEADERBOARD FETCHER ===
    def _fetch_leaderboard_sport(self, sport_key, games_list):
        if not state['active_sports'].get(sport_key, False): return
        config = self.leagues.get(sport_key)
        if not config: return

        try:
            r = requests.get(f"{self.base_url}{config['path']}/scoreboard", headers=HEADERS, timeout=5)
            if r.status_code != 200: return
            data = r.json()
            for event in data.get('events', []):
                status = event.get('status', {}).get('type', {}).get('shortDetail', 'TBD')
                state_code = event.get('status', {}).get('type', {}).get('state', '')
                if state_code not in ['in', 'post']: continue

                tourney_name = event.get('shortName', 'Event')
                leaders = []
                comps_list = event.get('competitions', [])
                if not comps_list: continue
                comps = comps_list[0].get('competitors', [])
                if not comps: continue
                
                def get_rank(c):
                    try: return int(c.get('curPosition', 999))
                    except: return 999
                
                sorted_comps = sorted(comps, key=get_rank)
                
                for c in sorted_comps[:4]: 
                    athlete = c.get('athlete', {})
                    score = c.get('score', {}).get('displayValue', '')
                    if not score and 'statistics' in c:
                        for s in c['statistics']:
                            if s.get('name') in ['time', 'points', 'leaderBehind']:
                                score = s.get('displayValue', ''); break
                    
                    rank = c.get('curPosition', c.get('order', '-'))
                    name = athlete.get('displayName', 'Unknown')
                    last_name = athlete.get('lastName', name)
                    leaders.append({'rank': rank, 'name': last_name, 'score': score})

                if leaders:
                    games_list.append({
                        'sport': sport_key, 'id': event['id'], 'status': status, 'state': state_code, 'is_shown': True,
                        'tourney_name': tourney_name, 'leaders': leaders,
                        'home_abbr': 'RACE', 'away_abbr': 'RACE', 'home_score': '', 'away_score': '',
                        'home_logo': '', 'away_logo': '', 'home_color': '#000000', 'away_color': '#FFFFFF'
                    })
        except Exception: pass

    # === DEMO DATA GENERATOR ===
    def generate_demo_data(self):
        t_str = dt.now().strftime('%H:%M:%S')
        return [
            {
                'sport': 'nfl', 'id': 'd1', 'status': f'DEMO {t_str}', 'state': 'in', 'is_shown': True,
                'home_abbr': 'KC', 'home_score': '24', 'home_logo': 'https://a.espncdn.com/i/teamlogos/nfl/500/kc.png',
                'away_abbr': 'BUF', 'away_score': '21', 'away_logo': 'https://a.espncdn.com/i/teamlogos/nfl/500/buf.png',
                'home_color': '#e31837', 'away_color': '#00338d', 'home_alt_color': '#ffb81c', 'away_alt_color': '#c60c30',
                'situation': {'possession': 'KC', 'isRedZone': True, 'downDist': '2nd & Goal'},
                'startTimeUTC': dt.utcnow().isoformat()
            },
            {
                'sport': 'racing_f1', 'id': 'd2', 'status': f'Lap 45/52', 'state': 'in', 'is_shown': True,
                'tourney_name': f'British GP {t_str}',
                'leaders': [
                    {'rank': '1', 'name': 'Norris', 'score': 'LEAD'},
                    {'rank': '2', 'name': 'Verstappen', 'score': '+1.2s'},
                    {'rank': '3', 'name': 'Hamilton', 'score': '+4.5s'},
                    {'rank': '4', 'name': 'Piastri', 'score': '+12.1s'}
                ],
                'home_abbr': 'F1', 'away_abbr': 'F1', 'home_color': '#FF0000', 'away_color': '#FFFFFF'
            },
            {
                'sport': 'racing_wec', 'id': 'd3', 'status': '12:00 Remaining', 'state': 'in', 'is_shown': True,
                'tourney_name': '24h Le Mans',
                'leaders': [
                    {'rank': '1', 'name': 'Ferrari #50', 'score': 'LEAD'},
                    {'rank': '2', 'name': 'Toyota #7', 'score': '+12s'},
                    {'rank': '3', 'name': 'Porsche #6', 'score': '+1m'},
                    {'rank': '4', 'name': 'Cadillac #2', 'score': '+1L'}
                ],
                'home_abbr': 'WEC', 'away_abbr': 'WEC', 'home_color': '#0000FF', 'away_color': '#FFFFFF'
            }
        ]

    def get_real_games(self):
        games = []
        with data_lock: conf = state.copy()
        
        # === CHECK DEMO MODE ===
        if conf.get('demo_mode', False):
            with data_lock: state['current_games'] = self.generate_demo_data()
            return

        utc_offset = conf.get('utc_offset', -4)

        if conf['active_sports'].get('clock'):
            with data_lock: state['current_games'] = [{'sport':'clock','id':'clk','is_shown':True}]; return
        if conf['active_sports'].get('weather'):
            if conf['weather_location'] != self.weather.location_name: self.weather.update_coords(conf['weather_location'])
            w = self.weather.get_weather()
            if w: 
                with data_lock: state['current_games'] = [w]; return

        # 1. Fetch Specific Racing APIs
        self._fetch_f1_openf1(games)
        self._fetch_nascar_native(games)
        
        # 2. Fetch ESPN Fallbacks (Golf, Indy, WEC, IMSA)
        for s in ['golf', 'racing_indycar', 'racing_wec', 'racing_imsa']:
            self._fetch_leaderboard_sport(s, games)

        # 3. Fetch Team Sports
        req_params = {}
        now_local = dt.now(timezone(timedelta(hours=utc_offset)))
        if conf['debug_mode'] and conf['custom_date']: target_date_str = conf['custom_date']
        else:
            if now_local.hour < 4: query_date = now_local - timedelta(days=1)
            else: query_date = now_local
            target_date_str = query_date.strftime("%Y-%m-%d")
        req_params['dates'] = target_date_str.replace('-', '')

        for league_key, config in self.leagues.items():
            if 'racing' in league_key or 'golf' in league_key: continue
            if not conf['active_sports'].get(league_key, False): continue
            
            # Hybrid NHL
            if league_key == 'nhl' and not conf['debug_mode']:
                prev_count = len(games); self._fetch_nhl_native(games, target_date_str)
                if len(games) > prev_count: continue 

            try:
                curr_p = config['scoreboard_params'].copy(); curr_p.update(req_params)
                r = requests.get(f"{self.base_url}{config['path']}/scoreboard", params=curr_p, headers=HEADERS, timeout=5)
                if r.status_code != 200: continue
                data = r.json()
                
                for e in data.get('events', []):
                    utc_str = e['date'].replace('Z', '') 
                    utc_start_iso = e['date']
                    st = e.get('status', {}); tp = st.get('type', {}); gst = tp.get('state', 'pre')
                    
                    game_dt_utc = dt.fromisoformat(utc_str).replace(tzinfo=timezone.utc)
                    game_dt_server = game_dt_utc.astimezone(timezone(timedelta(hours=utc_offset)))
                    game_date_str = game_dt_server.strftime("%Y-%m-%d")
                    keep_date = (gst == 'in') or (game_date_str == target_date_str)
                    if league_key == 'mlb' and not keep_date: continue
                    if not keep_date: continue

                    if not e.get('competitions'): continue
                    comp = e['competitions'][0]
                    if len(comp.get('competitors', [])) < 2: continue

                    h = comp['competitors'][0]; a = comp['competitors'][1]
                    h_ab = h['team']['abbreviation']; a_ab = a['team']['abbreviation']
                    
                    if league_key == 'ncf_fbs' and (h_ab not in FBS_TEAMS and a_ab not in FBS_TEAMS): continue
                    if league_key == 'ncf_fcs' and (h_ab not in FCS_TEAMS and a_ab not in FCS_TEAMS): continue

                    is_shown = True
                    if conf['mode'] == 'live' and gst not in ['in', 'half']: is_shown = False
                    elif conf['mode'] == 'my_teams':
                        hk = f"{league_key}:{h_ab}"; ak = f"{league_key}:{a_ab}"
                        if (hk not in conf['my_teams'] and h_ab not in conf['my_teams']) and \
                           (ak not in conf['my_teams'] and a_ab not in conf['my_teams']): is_shown = False

                    h_lg = self.get_corrected_logo(league_key, h_ab, h['team'].get('logo',''))
                    a_lg = self.get_corrected_logo(league_key, a_ab, a['team'].get('logo',''))
                    h_clr = h['team'].get('color', '000000'); h_alt = h['team'].get('alternateColor', 'ffffff')
                    a_clr = a['team'].get('color', '000000'); a_alt = a['team'].get('alternateColor', 'ffffff')

                    s_disp = tp.get('shortDetail', 'TBD'); p = st.get('period', 1)
                    dur = self.calculate_game_timing(league_key, utc_start_iso, p, s_disp)

                    if gst == 'pre': s_disp = game_dt_server.strftime("%I:%M %p").lstrip('0')
                    elif gst == 'in' or gst == 'half':
                        clk = st.get('displayClock', '')
                        if gst == 'half': s_disp = "Halftime"
                        elif 'soccer' in league_key: s_disp = f"{clk}'"
                        else: s_disp = f"P{p} {clk}" if 'hockey' in config['path'] else f"Q{p} {clk}"
                    else: s_disp = s_disp.replace("Final", "FINAL").replace("Full Time", "FT")

                    sit = comp.get('situation', {}); curr_poss = sit.get('possession')
                    if curr_poss: self.possession_cache[e['id']] = curr_poss
                    elif gst in ['in'] and not curr_poss: curr_poss = self.possession_cache.get(e['id'], '')

                    game_obj = {
                        'sport': league_key, 'id': e['id'], 'status': s_disp, 'state': gst, 'is_shown': is_shown,
                        'home_abbr': h_ab, 'home_score': h.get('score','0'), 'home_logo': h_lg, 'home_id': h.get('id'),
                        'away_abbr': a_ab, 'away_score': a.get('score','0'), 'away_logo': a_lg, 'away_id': a.get('id'),
                        'home_color': f"#{h_clr}", 'home_alt_color': f"#{h_alt}", 'away_color': f"#{a_clr}", 'away_alt_color': f"#{a_alt}",
                        'startTimeUTC': utc_start_iso, 'estimated_duration': dur, 'period': p,
                        'situation': { 'possession': curr_poss, 'isRedZone': sit.get('isRedZone', False), 'downDist': sit.get('downDistanceText', '') }
                    }
                    if league_key == 'mlb':
                        game_obj['situation'] = { 'balls': sit.get('balls', 0), 'strikes': sit.get('strikes', 0), 'outs': sit.get('outs', 0), 'onFirst': sit.get('onFirst', False), 'onSecond': sit.get('onSecond', False), 'onThird': sit.get('onThird', False) }
                    
                    games.append(game_obj)
            except Exception as e:
                print(f"Error fetching {league_key}: {e}")
        
        with data_lock: state['current_games'] = games

fetcher = SportsFetcher(state['weather_location'])

def background_updater():
    # Robust Loop: If it crashes, it waits and restarts.
    while True:
        try:
            fetcher.fetch_all_teams()
            break
        except Exception as e:
            print(f"Startup Error: {e}")
            time.sleep(10)

    while True:
        try:
            fetcher.get_real_games()
        except Exception as e:
            print("CRITICAL FETCH ERROR:")
            traceback.print_exc()
        time.sleep(UPDATE_INTERVAL)

# ================= FLASK API =================
app = Flask(__name__)

# PREVENT FLASK CACHING
@app.after_request
def add_header(response):
    response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response

@app.route('/')
def root():
    html = """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
        <title>Sports Ticker</title>
        <style>
            body { font-family: 'Segoe UI', system-ui; background: #121212; color: #e0e0e0; margin: 0; padding: 20px; }
            h2 { border-bottom: 1px solid #333; padding-bottom: 10px; }
            .control-group { background: #1e1e1e; padding: 15px; margin-bottom: 15px; border-radius: 8px; }
            .toggle-row { display: flex; justify-content: space-between; margin-bottom: 8px; align-items: center; }
            input[type="text"], input[type="number"], select { width: 100%; padding: 8px; background: #2a2a2a; border: 1px solid #444; color: white; border-radius: 4px; margin-bottom: 10px; }
            button { width: 100%; padding: 12px; background: #007bff; border: none; color: white; border-radius: 6px; font-weight: bold; cursor: pointer; }
            button.demo { background: #d32f2f; margin-bottom: 15px; }
        </style>
    </head>
    <body>
        <h2>Config</h2>
        
        <button class="demo" id="btn_demo" onclick="toggleDemo()">Loading...</button>

        <div class="control-group">
            <label>My Teams (Comma Separated)</label>
            <input type="text" id="inp_teams">
        </div>

        <div class="control-group">
            <div class="toggle-row"><span>NFL</span><input type="checkbox" id="chk_nfl"></div>
            <div class="toggle-row"><span>NBA</span><input type="checkbox" id="chk_nba"></div>
            <div class="toggle-row"><span>NHL</span><input type="checkbox" id="chk_nhl"></div>
            <div class="toggle-row"><span>MLB</span><input type="checkbox" id="chk_mlb"></div>
            <div class="toggle-row"><span>EPL</span><input type="checkbox" id="chk_soccer_epl"></div>
            <div class="toggle-row"><span>MLS</span><input type="checkbox" id="chk_soccer_mls"></div>
            <div class="toggle-row"><span>Golf (PGA)</span><input type="checkbox" id="chk_golf"></div>
            <div class="toggle-row"><span>F1 (OpenF1)</span><input type="checkbox" id="chk_racing_f1"></div>
            <div class="toggle-row"><span>NASCAR (Live Feed)</span><input type="checkbox" id="chk_racing_nascar"></div>
            <div class="toggle-row"><span>IndyCar</span><input type="checkbox" id="chk_racing_indycar"></div>
            <div class="toggle-row"><span>WEC</span><input type="checkbox" id="chk_racing_wec"></div>
            <div class="toggle-row"><span>IMSA</span><input type="checkbox" id="chk_racing_imsa"></div>
            <div class="toggle-row"><span>Weather</span><input type="checkbox" id="chk_weather"></div>
            <div class="toggle-row"><span>Clock</span><input type="checkbox" id="chk_clock"></div>
        </div>

        <div class="control-group">
            <label>Scroll Speed (1-10)</label>
            <input type="number" id="inp_speed" min="1" max="10">
            <label>Brightness (0.1-1.0)</label>
            <input type="number" id="inp_bright" step="0.1" min="0.1" max="1.0">
        </div>

        <button onclick="saveSettings()">Save Configuration</button>

        <script>
            let currentDemoState = false;

            async function loadState() {
                const res = await fetch('/api/state');
                const data = await res.json();
                const s = data.settings;
                currentDemoState = s.demo_mode;
                document.getElementById('btn_demo').innerText = currentDemoState ? "DISABLE DEMO MODE" : "ENABLE DEMO MODE";
                document.getElementById('btn_demo').style.background = currentDemoState ? "#4CAF50" : "#d32f2f";

                document.getElementById('inp_teams').value = (s.my_teams || []).join(', ');
                document.getElementById('chk_nfl').checked = s.active_sports.nfl;
                document.getElementById('chk_nba').checked = s.active_sports.nba;
                document.getElementById('chk_nhl').checked = s.active_sports.nhl;
                document.getElementById('chk_mlb').checked = s.active_sports.mlb;
                document.getElementById('chk_soccer_epl').checked = s.active_sports.soccer_epl;
                document.getElementById('chk_soccer_mls').checked = s.active_sports.soccer_mls;
                document.getElementById('chk_golf').checked = s.active_sports.golf;
                document.getElementById('chk_racing_f1').checked = s.active_sports.racing_f1;
                document.getElementById('chk_racing_nascar').checked = s.active_sports.racing_nascar;
                document.getElementById('chk_racing_indycar').checked = s.active_sports.racing_indycar;
                document.getElementById('chk_racing_wec').checked = s.active_sports.racing_wec;
                document.getElementById('chk_racing_imsa').checked = s.active_sports.racing_imsa;
                document.getElementById('chk_weather').checked = s.active_sports.weather;
                document.getElementById('chk_clock').checked = s.active_sports.clock;
                document.getElementById('inp_speed').value = s.scroll_speed || 5;
                document.getElementById('inp_bright').value = s.brightness || 0.5;
            }

            async function toggleDemo() {
                const payload = { demo_mode: !currentDemoState };
                await fetch('/api/config', { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(payload) });
                loadState();
            }

            async function saveSettings() {
                const payload = {
                    active_sports: {
                        nfl: document.getElementById('chk_nfl').checked,
                        nba: document.getElementById('chk_nba').checked,
                        nhl: document.getElementById('chk_nhl').checked,
                        mlb: document.getElementById('chk_mlb').checked,
                        soccer_epl: document.getElementById('chk_soccer_epl').checked,
                        soccer_mls: document.getElementById('chk_soccer_mls').checked,
                        golf: document.getElementById('chk_golf').checked,
                        racing_f1: document.getElementById('chk_racing_f1').checked,
                        racing_nascar: document.getElementById('chk_racing_nascar').checked,
                        racing_indycar: document.getElementById('chk_racing_indycar').checked,
                        racing_wec: document.getElementById('chk_racing_wec').checked,
                        racing_imsa: document.getElementById('chk_racing_imsa').checked,
                        weather: document.getElementById('chk_weather').checked,
                        clock: document.getElementById('chk_clock').checked
                    },
                    my_teams: document.getElementById('inp_teams').value.split(',').map(s=>s.trim()).filter(s=>s),
                    scroll_speed: parseInt(document.getElementById('inp_speed').value),
                    brightness: parseFloat(document.getElementById('inp_bright').value)
                };
                await fetch('/api/config', { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(payload) });
                alert("Saved!");
            }
            loadState();
        </script>
    </body>
    </html>
    """
    return render_template_string(html)

@app.route('/api/ticker')
def api_ticker():
    with data_lock: d = state.copy()
    offset_sec = d.get('utc_offset', -4) * 3600
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
            'reboot_requested': d['reboot_requested'],
            'utc_offset_seconds': offset_sec 
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
    # Force immediate refresh
    threading.Thread(target=fetcher.get_real_games).start()
    return jsonify({"status": "ok"})

@app.route('/api/hardware', methods=['POST'])
def api_hardware():
    d = request.json
    if d.get('action') == 'reboot':
        with data_lock: state['reboot_requested'] = True
        threading.Timer(10, lambda: state.update({'reboot_requested': False})).start()
    elif d.get('action') == 'test_pattern':
        with data_lock: state['test_pattern'] = not state['test_pattern']
    else:
        with data_lock: state.update(d)
        save_config_file()
    return jsonify({"status": "ok", "settings": state})

if __name__ == "__main__":
    threading.Thread(target=background_updater, daemon=True).start()
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 5000)))
