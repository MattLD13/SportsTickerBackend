import time
import threading
import json
import os
import re
from datetime import datetime as dt, timezone, timedelta
import requests
from flask import Flask, jsonify, request, redirect, url_for

# ================= CONFIGURATION =================
DEFAULT_OFFSET = -5 
CONFIG_FILE = "ticker_config.json"
UPDATE_INTERVAL = 5
data_lock = threading.Lock()

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
    "Cache-Control": "no-cache, no-store, must-revalidate",
    "Pragma": "no-cache",
    "Expires": "0"
}

# ================= DEFAULT STATE =================
default_state = {
    'active_sports': { 'nfl': True, 'ncf_fbs': True, 'ncf_fcs': True, 'mlb': True, 'nhl': True, 'nba': True, 'weather': False, 'clock': False },
    'mode': 'all', 
    'scroll_seamless': False,
    'my_teams': [], 
    'current_games': [],
    'all_teams_data': {}, 
    'debug_mode': False,
    'custom_date': None,
    'brightness': 0.5,
    'inverted': False,
    'panel_count': 2,
    'test_pattern': False,
    'reboot_requested': False,
    'weather_location': "New York",
    'manual_offset': None 
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
                'scroll_seamless': state['scroll_seamless'], 
                'my_teams': state['my_teams'],
                'brightness': state['brightness'],
                'inverted': state['inverted'],
                'panel_count': state['panel_count'],
                'weather_location': state['weather_location'],
                'manual_offset': state.get('manual_offset')
            }
        with open(CONFIG_FILE, 'w') as f:
            json.dump(export_data, f)
    except: pass

# ==========================================
# TIMEZONE MANAGER
# ==========================================
class TimezoneManager:
    def __init__(self):
        self.ip_cache = {} 
        self.cache_lock = threading.Lock()

    def get_offset_data(self, ip_address):
        # 1. Manual Override
        with data_lock:
            manual = state.get('manual_offset')
            if manual is not None and str(manual).strip() != "":
                try:
                    val = float(manual)
                    return val * 3600, f"Manual Override ({val})"
                except: pass

        # 2. Cache
        with self.cache_lock:
            if ip_address in self.ip_cache:
                return self.ip_cache[ip_address], "Auto-Detected (Cached)"

        clean_ip = ip_address.split(':')[0]
        
        # 3. TimeAPI
        try:
            r = requests.get(f"https://timeapi.io/api/TimeZone/ip?ipAddress={clean_ip}", timeout=3.0, headers=HEADERS)
            if r.status_code == 200:
                data = r.json()
                if 'currentUtcOffset' in data and 'seconds' in data['currentUtcOffset']:
                    offset = data['currentUtcOffset']['seconds']
                    with self.cache_lock: self.ip_cache[ip_address] = offset
                    return offset, "Auto-Detected (timeapi.io)"
        except: pass

        # 4. Fallback API
        try:
            r = requests.get(f"http://ip-api.com/json/{clean_ip}", timeout=3.0)
            data = r.json()
            if data['status'] == 'success':
                offset = data['offset']
                with self.cache_lock: self.ip_cache[ip_address] = offset
                return offset, "Auto-Detected (ip-api)"
        except: pass

        return DEFAULT_OFFSET * 3600, "Server Default (Fallback)"

tz_manager = TimezoneManager()

# ==========================================
# TEAMS LISTS (Shortened for brevity, full list implied)
# ==========================================
FBS_TEAMS = ["AF", "AKR", "ALA", "APP", "ARIZ", "ASU", "ARK", "ARST", "ARMY", "AUB", "BALL", "BAY", "BOIS", "BC", "BGSU", "BUF", "BYU", "CAL", "CMU", "CLT", "CIN", "CLEM", "CCU", "COLO", "CSU", "CONN", "DEL", "DUKE", "ECU", "EMU", "FAU", "FIU", "FLA", "FSU", "FRES", "GASO", "GAST", "GT", "UGA", "HAW", "HOU", "ILL", "IND", "IOWA", "ISU", "JXST", "JMU", "KAN", "KSU", "KENN", "KENT", "UK", "LIB", "ULL", "LT", "LOU", "LSU", "MAR", "MD", "MASS", "MEM", "MIA", "M-OH", "MICH", "MSU", "MTSU", "MINN", "MSST", "MIZ", "MOST", "NAVY", "NCST", "NEB", "NEV", "UNM", "NMSU", "UNC", "UNT", "NIU", "NU", "ND", "OHIO", "OSU", "OU", "OKST", "ODU", "MISS", "ORE", "ORST", "PSU", "PITT", "PUR", "RICE", "RUTG", "SAM", "SDSU", "SJSU", "SMU", "USA", "SC", "USF", "USM", "STAN", "SYR", "TCU", "TEM", "TENN", "TEX", "TA&M", "TXST", "TTU", "TOL", "TROY", "TULN", "TLSA", "UAB", "UCF", "UCLA", "ULM", "UMASS", "UNLV", "USC", "UTAH", "USU", "UTEP", "UTSA", "VAN", "UVA", "VT", "WAKE", "WASH", "WSU", "WVU", "WKU", "WMU", "WIS", "WYO"]
FCS_TEAMS = ["ACU", "AAMU", "ALST", "UALB", "ALCN", "UAPB", "APSU", "BCU", "BRWN", "BRY", "BUCK", "BUT", "CP", "CAM", "CARK", "CCSU", "CHSO", "UTC", "CIT", "COLG", "COLU", "COR", "DART", "DAV", "DAY", "DSU", "DRKE", "DUQ", "EIU", "EKU", "ETAM", "EWU", "ETSU", "ELON", "FAMU", "FOR", "FUR", "GWEB", "GTWN", "GRAM", "HAMP", "HARV", "HC", "HCU", "HOW", "IDHO", "IDST", "ILST", "UIW", "INST", "JKST", "LAF", "LAM", "LEH", "LIN", "LIU", "ME", "MRST", "MCN", "MER", "MERC", "MRMK", "MVSU", "MONM", "MONT", "MTST", "MORE", "MORG", "MUR", "UNH", "NHVN", "NICH", "NORF", "UNA", "NCAT", "NCCU", "UND", "NDSU", "NAU", "UNCO", "UNI", "NWST", "PENN", "PRST", "PV", "PRES", "PRIN", "URI", "RICH", "RMU", "SAC", "SHU", "SFPA", "SAM", "USD", "SELA", "SEMO", "SDAK", "SDST", "SCST", "SOU", "SIU", "SUU", "STMN", "SFA", "STET", "STO", "STBK", "TAR", "TNST", "TNTC", "TXSO", "TOW", "UCD", "UTM", "UTU", "UTRGV", "VAL", "VILL", "VMI", "WAG", "WEB", "WGA", "WCU", "WIU", "W&M", "WOF", "YALE", "YSU"]

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
            'nba': { 'path': 'basketball/nba', 'scoreboard_params': {}, 'team_params': {'limit': 100} }
        }

    def get_corrected_logo(self, league_key, abbr, default_logo):
        key = f"{league_key.upper()}:{abbr}"
        return LOGO_OVERRIDES.get(key, default_logo)

    def fetch_all_teams(self):
        try:
            teams_catalog = {k: [] for k in self.leagues.keys()}
            for league_key in ['nfl', 'mlb', 'nhl', 'nba']:
                self._fetch_simple_league(league_key, teams_catalog)

            url = f"{self.base_url}football/college-football/teams"
            r = requests.get(url, params={'limit': 1000, 'groups': '80,81'}, headers=HEADERS, timeout=10) 
            data = r.json()
            if 'sports' in data:
                for sport in data['sports']:
                    for league in sport['leagues']:
                        for item in league.get('teams', []):
                            t_abbr = item['team'].get('abbreviation', 'unk')
                            logos = item['team'].get('logos', [])
                            t_logo = logos[0].get('href', '') if len(logos) > 0 else ''
                            league_tag = 'ncf_fbs' if t_abbr in FBS_TEAMS else 'ncf_fcs'
                            t_logo = self.get_corrected_logo(league_tag, t_abbr, t_logo)
                            team_obj = {'abbr': t_abbr, 'logo': t_logo}
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
        try:
            r = requests.get(f"{self.base_url}{config['path']}/teams", params=config['team_params'], headers=HEADERS, timeout=10)
            data = r.json()
            if 'sports' in data:
                for sport in data['sports']:
                    for league in sport['leagues']:
                        for item in league.get('teams', []):
                            abbr = item['team'].get('abbreviation', 'unk')
                            logo = item['team'].get('logos', [{}])[0].get('href', '')
                            logo = self.get_corrected_logo(league_key, abbr, logo)
                            catalog[league_key].append({'abbr': abbr, 'logo': logo})
        except: pass

    def _fetch_nhl_native(self, games_list, target_date_str):
        with data_lock: is_nhl = state['active_sports'].get('nhl', False)
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
                        
                        if st in ['FINAL', 'OFF']:
                             disp = "FINAL"
                             if g.get('periodDescriptor', {}).get('periodType') == 'OT': disp = "FINAL OT"
                             if g.get('periodDescriptor', {}).get('periodType') == 'SHOOTOUT': disp = "FINAL S/O"

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
                                    
                                    if p_type == 'SHOOTOUT': disp = "S/O"
                                    elif is_intermission or time_rem == "00:00":
                                        if p_num == 1: disp = "End 1st"
                                        elif p_num == 2: disp = "End 2nd"
                                        elif p_num == 3: disp = "End 3rd"
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
                            'startTimeUTC': utc_start,
                            'situation': { 'powerPlay': pp, 'possession': poss, 'emptyNet': en }
                        })
        except: pass

    def get_real_games(self):
        games = []
        with data_lock: conf = state.copy()

        if conf['active_sports'].get('clock'):
            with data_lock: state['current_games'] = [{'sport':'clock','id':'clk','is_shown':True}]; return
        if conf['active_sports'].get('weather'):
            if conf['weather_location'] != self.weather.location_name: self.weather.update_coords(conf['weather_location'])
            w = self.weather.get_weather()
            if w: 
                with data_lock: state['current_games'] = [w]; return

        req_params = {}
        now_local = dt.now(timezone(timedelta(hours=DEFAULT_OFFSET)))
        if conf['debug_mode'] and conf['custom_date']:
            target_date_str = conf['custom_date']
        else:
            if now_local.hour < 4: query_date = now_local - timedelta(days=1)
            else: query_date = now_local
            target_date_str = query_date.strftime("%Y-%m-%d")

        req_params['dates'] = target_date_str.replace('-', '')

        for league_key, config in self.leagues.items():
            if not conf['active_sports'].get(league_key, False): continue
            
            # === HYBRID NHL LOGIC ===
            if league_key == 'nhl' and not conf['debug_mode']:
                prev_count = len(games)
                self._fetch_nhl_native(games, target_date_str)
                if len(games) > prev_count: continue 

            try:
                curr_p = config['scoreboard_params'].copy(); curr_p.update(req_params)
                r = requests.get(f"{self.base_url}{config['path']}/scoreboard", params=curr_p, headers=HEADERS, timeout=5)
                data = r.json()
                
                for e in data.get('events', []):
                    utc_str = e['date'].replace('Z', '') 
                    utc_start_iso = e['date']
                    
                    st = e.get('status', {}); tp = st.get('type', {}); gst = tp.get('state', 'pre')
                    
                    # Convert to Server Time just for filtering logic (date check)
                    try:
                        game_dt_utc = dt.fromisoformat(utc_str).replace(tzinfo=timezone.utc)
                        game_dt_server = game_dt_utc.astimezone(timezone(timedelta(hours=DEFAULT_OFFSET)))
                        game_date_str = game_dt_server.strftime("%Y-%m-%d")
                    except:
                        game_date_str = target_date_str
                    
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

                    s_disp = tp.get('shortDetail', 'TBD')
                    
                    if gst == 'pre':
                        s_disp = "Scheduled"
                    elif gst == 'in' or gst == 'half':
                        p = st.get('period', 1); clk = st.get('displayClock', '')
                        if gst == 'half' or (p == 2 and clk == '0:00' and 'football' in config['path']):
                            s_disp = "Halftime"
                            is_halftime = True
                        elif 'hockey' in config['path'] and clk == '0:00':
                             if p == 1: s_disp = "End 1st"
                             elif p == 2: s_disp = "End 2nd"
                             elif p == 3: s_disp = "End 3rd"
                             else: s_disp = "Intermission"
                        else:
                            s_disp = f"P{p} {clk}" if 'hockey' in config['path'] else f"Q{p} {clk}"
                    else:
                        s_disp = s_disp.replace("Final", "FINAL").replace("/OT", " OT")

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
                        'sport': league_key, 'id': e['id'], 'status': s_disp, 'state': gst, 'is_shown': is_shown,
                        'home_abbr': h_ab, 'home_score': h.get('score','0'), 'home_logo': h_lg,
                        'home_id': h.get('id'), 
                        'away_abbr': a_ab, 'away_score': a.get('score','0'), 'away_logo': a_lg,
                        'away_id': a.get('id'), 
                        'startTimeUTC': utc_start_iso, 
                        'period': st.get('period', 1),
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

@app.route('/', methods=['GET', 'POST'])
def root():
    user_ip = request.headers.get('X-Real-IP') or \
              request.headers.get('CF-Connecting-IP') or \
              request.headers.get('X-Forwarded-For') or \
              request.remote_addr
    if user_ip and ',' in user_ip: user_ip = user_ip.split(',')[0].strip()
    
    if request.method == 'POST':
        manual_offset = request.form.get('offset')
        with data_lock:
            state['manual_offset'] = manual_offset
            save_config_file()
        return redirect(url_for('root'))
    
    offset_sec, source_type = tz_manager.get_offset_data(user_ip)
    server_time = dt.now()
    local_time = dt.now(timezone(timedelta(seconds=offset_sec)))
    
    current_offset_val = state.get('manual_offset', '')
    if current_offset_val is None: current_offset_val = ""
    # Ensure it's a string for HTML selection logic
    current_offset_val = str(current_offset_val)

    html = f"""
    <html><head><title>Ticker Status</title>
    <style>body{{font-family:sans-serif;padding:2rem;background:#1a1a1a;color:white}}
    .box{{background:#333;padding:1rem;border-radius:8px;margin-bottom:1rem}}
    select,button{{padding:0.5rem;border-radius:4px;border:none}}
    button{{background:#007bff;color:white;cursor:pointer}}
    </style>
    </head>
    <body>
        <h1>Ticker Backend Online</h1>
        
        <div class="box">
            <h3>Timezone Debug</h3>
            <p><strong>Your IP:</strong> {user_ip}</p>
            <p><strong>Detected Offset:</strong> {offset_sec / 3600} Hours</p>
            <p><strong>Source:</strong> {source_type}</p>
            <p><strong>Server Time (UTC):</strong> {dt.now(timezone.utc).strftime('%I:%M %p')}</p>
            <p><strong>Your Local Time:</strong> {local_time.strftime('%I:%M %p')}</p>
        </div>

        <div class="box">
            <h3>Manual Override</h3>
            <form method="POST">
                <label>Select Timezone Offset:</label><br><br>
                <select name="offset">
                    <option value="" {'selected' if current_offset_val == "" else ''}>Auto-Detect (Default)</option>
                    <option value="-4" {'selected' if current_offset_val == "-4" else ''}>AST / EDT (Aruba/NY Summer) [-4]</option>
                    <option value="-5" {'selected' if current_offset_val == "-5" else ''}>EST / CDT (NY Winter/Chicago Summer) [-5]</option>
                    <option value="-6" {'selected' if current_offset_val == "-6" else ''}>CST / MDT (Chicago Winter/Denver Summer) [-6]</option>
                    <option value="-7" {'selected' if current_offset_val == "-7" else ''}>MST / PDT (Denver Winter/LA Summer) [-7]</option>
                    <option value="-8" {'selected' if current_offset_val == "-8" else ''}>PST (LA Winter) [-8]</option>
                    <option value="0" {'selected' if current_offset_val == "0" else ''}>UTC [0]</option>
                    <option value="1" {'selected' if current_offset_val == "1" else ''}>CET [+1]</option>
                </select>
                <button type="submit">Save</button>
            </form>
        </div>

        <br><a href="/api/ticker" style="color:#007bff">View Raw JSON</a>
    </body></html>
    """
    return html

@app.route('/api/ticker')
def api_ticker():
    user_ip = request.headers.get('X-Real-IP') or \
              request.headers.get('CF-Connecting-IP') or \
              request.headers.get('X-Forwarded-For') or \
              request.remote_addr
    if user_ip and ',' in user_ip: user_ip = user_ip.split(',')[0].strip()
    
    offset_sec, _ = tz_manager.get_offset_data(user_ip)
    
    with data_lock: d = state.copy()
    raw_games = d['current_games']
    processed_games = []
    
    for g in raw_games:
        if not g.get('is_shown', True): continue
        game_copy = g.copy()
        
        # === FORCE TIME OVERWRITE FOR PRE-GAME AND FUTURE ===
        utc_str = game_copy.get('startTimeUTC')
        # We apply this if status is "Scheduled" OR if state is pre/fut.
        # This handles both ESPN and Native NHL games properly.
        if utc_str and game_copy.get('state') in ['pre', 'fut']:
            try:
                if utc_str.endswith('Z'): utc_str = utc_str.replace('Z', '+00:00')
                dt_utc = dt.fromisoformat(utc_str)
                dt_local = dt_utc.astimezone(timezone(timedelta(seconds=offset_sec)))
                game_copy['status'] = dt_local.strftime("%I:%M %p").lstrip('0')
            except: pass
        
        processed_games.append(game_copy)

    return jsonify({
        'meta': {
            'time': dt.now(timezone(timedelta(seconds=offset_sec))).strftime("%I:%M %p"), 
            'count': len(processed_games), 
            'scroll_seamless': d['scroll_seamless'], 
            'brightness': d['brightness'], 
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
