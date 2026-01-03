import time
import threading
import json
import os
import random
import string
import requests
from datetime import datetime as dt, timezone, timedelta
from flask import Flask, jsonify, request

# ================= CONFIGURATION =================
CONFIG_FILE = "devices.json"
UPDATE_INTERVAL = 10
data_lock = threading.Lock()

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
    "Cache-Control": "no-cache"
}

# ================= TEAMS & LOGOS (FULL LIST) =================
FBS_TEAMS = ["AF", "AKR", "ALA", "APP", "ARIZ", "ASU", "ARK", "ARST", "ARMY", "AUB", "BALL", "BAY", "BOIS", "BC", "BGSU", "BUF", "BYU", "CAL", "CMU", "CLT", "CIN", "CLEM", "CCU", "COLO", "CSU", "CONN", "DEL", "DUKE", "ECU", "EMU", "FAU", "FIU", "FLA", "FSU", "FRES", "GASO", "GAST", "GT", "UGA", "HAW", "HOU", "ILL", "IND", "IOWA", "ISU", "JXST", "JMU", "KAN", "KSU", "KENN", "KENT", "UK", "LIB", "ULL", "LT", "LOU", "LSU", "MAR", "MD", "MASS", "MEM", "MIA", "M-OH", "MICH", "MSU", "MTSU", "MINN", "MSST", "MIZ", "MOST", "NAVY", "NCST", "NEB", "NEV", "UNM", "NMSU", "UNC", "UNT", "NIU", "NU", "ND", "OHIO", "OSU", "OU", "OKST", "ODU", "MISS", "ORE", "ORST", "PSU", "PITT", "PUR", "RICE", "RUTG", "SAM", "SDSU", "SJSU", "SMU", "USA", "SC", "USF", "USM", "STAN", "SYR", "TCU", "TEM", "TENN", "TEX", "TA&M", "TXST", "TTU", "TOL", "TROY", "TULN", "TLSA", "UAB", "UCF", "UCLA", "ULM", "UMASS", "UNLV", "USC", "UTAH", "USU", "UTEP", "UTSA", "VAN", "UVA", "VT", "WAKE", "WASH", "WSU", "WVU", "WKU", "WMU", "WIS", "WYO"]
FCS_TEAMS = ["ACU", "AAMU", "ALST", "UALB", "ALCN", "UAPB", "APSU", "BCU", "BRWN", "BRY", "BUCK", "BUT", "CP", "CAM", "CARK", "CCSU", "CHSO", "UTC", "CIT", "COLG", "COLU", "COR", "DART", "DAV", "DAY", "DSU", "DRKE", "DUQ", "EIU", "EKU", "ETAM", "EWU", "ETSU", "ELON", "FAMU", "FOR", "FUR", "GWEB", "GTWN", "GRAM", "HAMP", "HARV", "HC", "HCU", "HOW", "IDHO", "IDST", "ILST", "UIW", "INST", "JKST", "LAF", "LAM", "LEH", "LIN", "LIU", "ME", "MRST", "MCN", "MER", "MERC", "MRMK", "MVSU", "MONM", "MONT", "MTST", "MORE", "MORG", "MUR", "UNH", "NHVN", "NICH", "NORF", "UNA", "NCAT", "NCCU", "UND", "NDSU", "NAU", "UNCO", "UNI", "NWST", "PENN", "PRST", "PV", "PRES", "PRIN", "URI", "RICH", "RMU", "SAC", "SHU", "SFPA", "SAM", "USD", "SELA", "SEMO", "SDAK", "SDST", "SCST", "SOU", "SIU", "SUU", "STMN", "SFA", "STET", "STO", "STBK", "TAR", "TNST", "TNTC", "TXSO", "TOW", "UCD", "UTM", "UTM", "UTRGV", "VAL", "VILL", "VMI", "WAG", "WEB", "WGA", "WCU", "WIU", "W&M", "WOF", "YALE", "YSU"]

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

SPORT_DURATIONS = { 'nfl': 195, 'ncf_fbs': 210, 'ncf_fcs': 195, 'nba': 150, 'nhl': 150, 'mlb': 180, 'weather': 60, 'soccer': 115 }

# ================= DEFAULT DEVICE STATE =================
DEFAULT_DEVICE = {
    'name': 'New Ticker',
    'setup_mode': True,
    'pairing_code': None,
    'active_sports': { 'nfl': True, 'ncf_fbs': True, 'ncf_fcs': True, 'mlb': True, 'nhl': True, 'nba': True, 'soccer': True, 'f1': True, 'nascar': True, 'indycar': True, 'wec': False, 'imsa': False, 'weather': False, 'clock': False },
    'mode': 'all', 'layout_mode': 'schedule', 'scroll_seamless': False,
    'my_teams': ["NYG", "NYY", "NJD", "NYK", "LAL", "BOS", "KC", "BUF", "LEH"],
    'brightness': 0.5, 'scroll_speed': 5, 'inverted': False, 'panel_count': 2, 'weather_location': "New York", 'utc_offset': -5,
    'debug_mode': False, 'demo_mode': False, 'custom_date': None
}

# ================= DEVICE MANAGER =================
class DeviceManager:
    def __init__(self):
        self.devices = {}
        self.code_map = {}
        self.all_teams_data = {}
        self.load()

    def load(self):
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, 'r') as f:
                    data = json.load(f)
                    self.devices = data.get('devices', {})
                    self.all_teams_data = data.get('teams', {})
                    for mac, d in self.devices.items():
                        if d.get('pairing_code'): self.code_map[d['pairing_code']] = mac
            except: self.devices = {}
        
        # Ensure default exists for legacy/global view
        if 'default' not in self.devices:
            self.devices['default'] = DEFAULT_DEVICE.copy()
            self.devices['default']['setup_mode'] = False

    def save(self):
        try:
            with open(CONFIG_FILE, 'w') as f:
                json.dump({'devices': self.devices, 'teams': self.all_teams_data}, f, indent=2)
        except: pass

    def generate_code(self):
        chars = string.ascii_uppercase + string.digits
        while True:
            code = ''.join(random.choices(chars, k=4))
            if code not in self.code_map: return code

    def get_device(self, device_id):
        if device_id not in self.devices:
            print(f"New Device Discovered: {device_id}")
            new_dev = DEFAULT_DEVICE.copy()
            new_code = self.generate_code()
            new_dev['pairing_code'] = new_code
            self.devices[device_id] = new_dev
            self.code_map[new_code] = device_id
            self.save()
        return self.devices[device_id]

    def update_device(self, device_id, updates):
        if device_id not in self.devices: return
        if 'active_sports' in updates and 'active_sports' in self.devices[device_id]:
            self.devices[device_id]['active_sports'].update(updates['active_sports'])
            del updates['active_sports']
        self.devices[device_id].update(updates)
        self.save()

    def claim_device(self, code):
        code = code.upper().strip()
        if code in self.code_map:
            mac = self.code_map[code]
            self.devices[mac]['setup_mode'] = False
            self.save()
            return mac, self.devices[mac]
        return None, None

manager = DeviceManager()

# ================= FETCHERS =================
class WeatherFetcher:
    def __init__(self): self.cache = {}
    def get_icon(self, code, is_day=1):
        if code in [0, 1]: return "sun" if is_day else "moon"
        elif code in [2]: return "partly_cloudy"
        elif code in [3]: return "cloud"
        elif code in [45, 48]: return "fog"
        elif code in [51, 53, 55, 61, 63, 65, 80, 81, 82]: return "rain"
        elif code in [71, 73, 75, 77, 85, 86]: return "snow"
        elif code in [95, 96, 99]: return "storm"
        return "cloud"

    def get_weather(self, location):
        if not location: location = "New York"
        now = time.time()
        if location in self.cache:
            ts, data = self.cache[location]
            if now - ts < 900: return data
        try:
            r = requests.get(f"https://geocoding-api.open-meteo.com/v1/search?name={location}&count=1&language=en&format=json", timeout=3)
            gd = r.json()
            if 'results' not in gd: return None
            lat = gd['results'][0]['latitude']; lon = gd['results'][0]['longitude']; name = gd['results'][0]['name']
            r = requests.get(f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&current=temperature_2m,weather_code,is_day&daily=temperature_2m_max,temperature_2m_min,uv_index_max&temperature_unit=fahrenheit&timezone=auto", timeout=5)
            wd = r.json()
            c = wd.get('current', {}); dl = wd.get('daily', {})
            icon = self.get_icon(c.get('weather_code', 0), c.get('is_day', 1))
            high = int(dl['temperature_2m_max'][0]); low = int(dl['temperature_2m_min'][0]); uv = float(dl['uv_index_max'][0])
            w = {"type":"weather", "sport":"weather", "id":"weather", "status":"Live", "home_abbr": f"{int(c.get('temperature_2m', 0))}°", "away_abbr": name, "home_score":"", "away_score":"", "is_shown":True, "home_logo":"", "away_logo":"", "home_color":"#000000", "away_color":"#000000", "situation": {"icon": icon, "stats": {"high": int(dl['temperature_2m_max'][0]), "low": int(dl['temperature_2m_min'][0]), "uv": float(dl['uv_index_max'][0])}}}
            self.cache[location] = (now, w)
            return w
        except: return None

class SportsFetcher:
    def __init__(self):
        self.weather = WeatherFetcher()
        self.base_url = 'http://site.api.espn.com/apis/site/v2/sports/'
        self.possession_cache = {}
        self.leagues = {
            'nfl': { 'path': 'football/nfl', 'params': {'limit': 100}, 'type': 'scoreboard' },
            'ncf_fbs': { 'path': 'football/college-football', 'params': {'groups': '80', 'limit': 100}, 'type': 'scoreboard' },
            'ncf_fcs': { 'path': 'football/college-football', 'params': {'groups': '81', 'limit': 100}, 'type': 'scoreboard' },
            'mlb': { 'path': 'baseball/mlb', 'params': {'limit': 100}, 'type': 'scoreboard' },
            'nhl': { 'path': 'hockey/nhl', 'params': {'limit': 100}, 'type': 'scoreboard' },
            'nba': { 'path': 'basketball/nba', 'params': {'limit': 100}, 'type': 'scoreboard' },
            'soccer': { 'path': 'soccer/eng.1', 'params': {}, 'group': 'soccer', 'type': 'scoreboard' },
            'f1': { 'path': 'racing/f1', 'type': 'leaderboard' },
            'nascar': { 'path': 'racing/nascar', 'type': 'leaderboard' },
            'indycar': { 'path': 'racing/indycar', 'type': 'leaderboard' },
            'wec': { 'path': 'racing/wec', 'type': 'leaderboard' },
            'imsa': { 'path': 'racing/imsa', 'type': 'leaderboard' }
        }

    def get_corrected_logo(self, league_key, abbr, default_logo):
        key = f"{league_key.upper()}:{abbr}"
        return LOGO_OVERRIDES.get(key, default_logo)

    def calculate_game_timing(self, sport, start_utc, period, status_detail):
        duration = SPORT_DURATIONS.get(sport, 180); ot_padding = 0
        if 'OT' in str(status_detail) or 'S/O' in str(status_detail):
            if sport in ['nba', 'nfl', 'ncf_fbs', 'ncf_fcs']:
                ot_count = 1
                if '2OT' in status_detail: ot_count = 2
                elif '3OT' in status_detail: ot_count = 3
                ot_padding = ot_count * 20
            elif sport == 'nhl': ot_padding = 20
            elif sport == 'mlb' and period > 9: ot_padding = (period - 9) * 20
        return duration + ot_padding

    def fetch_leaderboard(self, key, cfg, games, conf):
        try:
            r = requests.get(f"{self.base_url}{cfg['path']}/scoreboard", timeout=5)
            data = r.json()
            for e in data.get('events', []):
                utc_str = e['date'].replace('Z', '')
                try:
                    game_dt_utc = dt.fromisoformat(utc_str).replace(tzinfo=timezone.utc)
                    local_now = dt.now(timezone.utc)
                    diff_hours = (game_dt_utc - local_now).total_seconds() / 3600
                except: diff_hours = 0
                state = e.get('status',{}).get('type',{}).get('state','pre')
                if state == 'pre' and diff_hours > 48: continue
                if state == 'post' and diff_hours < -24: continue
                leaders = []
                try:
                    comps = e.get('competitions', [])[0].get('competitors', [])
                    sorted_comps = sorted(comps, key=lambda x: int(x.get('curatedRank', x.get('order', 999))))
                    for c in sorted_comps[:5]:
                        disp_name = c.get('athlete', {}).get('displayName', c.get('team',{}).get('displayName','Unk'))
                        if ' ' in disp_name: disp_name = disp_name.split(' ')[-1]
                        score = c.get('score', c.get('linescores', [{}])[-1].get('value', ''))
                        leaders.append({'rank': str(c.get('curatedRank', '-')), 'name': disp_name, 'score': str(score)})
                except: pass
                games.append({'type': 'leaderboard', 'sport': key, 'id': e['id'], 'status': e.get('status',{}).get('type',{}).get('shortDetail','Live'), 'state': state, 'tourney_name': e.get('name','Event'), 'leaders': leaders, 'is_shown': True, 'startTimeUTC': e['date']})
        except: pass

    def _fetch_nhl_native(self, games_list, target_date_str, conf):
        if not conf['active_sports'].get('nhl', False): return
        utc_offset = conf.get('utc_offset', -5)
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
                        st = g.get('gameState', 'OFF')
                        map_st = 'in' if st in ['LIVE', 'CRIT'] else ('pre' if st in ['PRE', 'FUT'] else 'post')
                        is_shown = True
                        if conf['mode'] == 'live' and map_st != 'in': is_shown = False
                        if conf['mode'] == 'my_teams':
                            my = conf.get('my_teams', [])
                            if h_ab not in my and a_ab not in my: is_shown = False
                        disp = "Scheduled"; utc_start = g.get('startTimeUTC', '')
                        dur = self.calculate_game_timing('nhl', utc_start, 1, st)
                        if st in ['PRE', 'FUT'] and utc_start:
                             try:
                                 dt_obj = dt.fromisoformat(utc_start.replace('Z', '+00:00'))
                                 local = dt_obj.astimezone(timezone(timedelta(hours=utc_offset)))
                                 disp = local.strftime("%I:%M %p").lstrip('0')
                             except: pass
                        elif st in ['FINAL', 'OFF']: disp = "FINAL"
                        pp = False; poss = ""; en = False; h_sc = "0"; a_sc = "0"
                        if map_st == 'in':
                            try:
                                r2 = requests.get(f"https://api-web.nhle.com/v1/gamecenter/{gid}/landing", headers=HEADERS, timeout=2)
                                if r2.status_code == 200:
                                    d2 = r2.json()
                                    h_sc = str(d2['homeTeam'].get('score', 0))
                                    a_sc = str(d2['awayTeam'].get('score', 0))
                                    clk = d2.get('clock', {})
                                    time_rem = clk.get('timeRemaining', '00:00')
                                    pd = d2.get('periodDescriptor', {})
                                    p_num = pd.get('number', 1)
                                    disp = f"P{p_num} {time_rem}"
                                    sit_obj = d2.get('situation', {})
                                    if sit_obj:
                                        sit = sit_obj.get('situationCode', '1551')
                                        ag = int(sit[0]); as_ = int(sit[1]); hs = int(sit[2]); hg = int(sit[3])
                                        if as_ > hs: pp=True; poss=a_ab
                                        elif hs > as_: pp=True; poss=h_ab
                                        en = (ag==0 or hg==0)
                            except: disp = "Live"
                        games_list.append({'type': 'scoreboard', 'sport': 'nhl', 'id': str(gid), 'status': disp, 'state': map_st, 'is_shown': is_shown, 'home_abbr': h_ab, 'home_score': h_sc, 'home_logo': self.get_corrected_logo('nhl', h_ab, f"https://a.espncdn.com/i/teamlogos/nhl/500/{h_ab.lower()}.png"), 'home_id': h_ab, 'away_abbr': a_ab, 'away_score': a_sc, 'away_logo': self.get_corrected_logo('nhl', a_ab, f"https://a.espncdn.com/i/teamlogos/nhl/500/{a_ab.lower()}.png"), 'away_id': a_ab, 'home_color': '#000000', 'home_alt_color': '#ffffff', 'away_color': '#000000', 'away_alt_color': '#ffffff', 'startTimeUTC': utc_start, 'estimated_duration': dur, 'situation': { 'powerPlay': pp, 'possession': poss, 'emptyNet': en }})
        except: pass

    def get_games(self, conf):
        if conf.get('demo_mode'): return self.generate_demo_data()
        games = []
        if conf['active_sports'].get('clock'): games.append({'type':'clock','sport':'clock','id':'clk','is_shown':True})
        if conf['active_sports'].get('weather'):
            w = self.weather.get_weather(conf.get('weather_location'))
            if w: games.append(w)
        utc_offset = conf.get('utc_offset', -5)
        now_local = dt.now(timezone(timedelta(hours=utc_offset)))
        target_date_str = conf['custom_date'] if (conf['debug_mode'] and conf['custom_date']) else (now_local - timedelta(days=1) if now_local.hour < 4 else now_local).strftime("%Y%m%d")
        
        for league_key, config in self.leagues.items():
            check_key = config.get('group', league_key)
            if not conf['active_sports'].get(check_key, False): continue
            if config.get('type') == 'leaderboard': self.fetch_leaderboard(league_key, config, games, conf); continue
            if league_key == 'nhl' and not conf['debug_mode']:
                prev_cnt = len(games); self._fetch_nhl_native(games, target_date_str, conf)
                if len(games) > prev_cnt: continue
            try:
                curr_p = config.get('scoreboard_params', {}).copy(); curr_p['dates'] = target_date_str
                r = requests.get(f"{self.base_url}{config['path']}/scoreboard", params=curr_p, headers=HEADERS, timeout=5)
                data = r.json()
                for e in data.get('events', []):
                    utc_start = e['date']; st = e.get('status', {}); tp = st.get('type', {}); gst = tp.get('state', 'pre')
                    comp = e['competitions'][0]; h = comp['competitors'][0]; a = comp['competitors'][1]
                    h_ab = h['team']['abbreviation']; a_ab = a['team']['abbreviation']
                    if league_key == 'ncf_fbs' and (h_ab not in FBS_TEAMS and a_ab not in FBS_TEAMS): continue
                    if league_key == 'ncf_fcs' and (h_ab not in FCS_TEAMS and a_ab not in FCS_TEAMS): continue
                    
                    is_shown = True
                    if conf['mode'] == 'live' and gst not in ['in', 'half']: is_shown = False
                    elif conf['mode'] == 'my_teams':
                        my = conf.get('my_teams', [])
                        hk = f"{league_key}:{h_ab}"; ak = f"{league_key}:{a_ab}"
                        if (hk not in my and h_ab not in my) and (ak not in my and a_ab not in my): is_shown = False
                    
                    h_clr = h['team'].get('color', '000000'); h_alt = h['team'].get('alternateColor', 'ffffff')
                    a_clr = a['team'].get('color', '000000'); a_alt = a['team'].get('alternateColor', 'ffffff')
                    s_disp = tp.get('shortDetail', 'TBD')
                    if gst == 'pre':
                        try:
                            g_dt = dt.fromisoformat(utc_start.replace('Z','+00:00'))
                            local = g_dt.astimezone(timezone(timedelta(hours=utc_offset)))
                            s_disp = local.strftime("%I:%M %p").lstrip('0')
                        except: pass
                    
                    sit = comp.get('situation', {}); poss = sit.get('possession'); 
                    if poss: self.possession_cache[e['id']] = poss
                    elif gst == 'in': poss = self.possession_cache.get(e['id'])
                    
                    game_obj = {
                        'type': 'scoreboard', 'sport': check_key, 'id': e['id'], 'status': s_disp, 'state': gst, 'is_shown': is_shown,
                        'home_abbr': h_ab, 'home_score': h.get('score','0'), 'home_logo': self.get_corrected_logo(league_key, h_ab, h['team'].get('logo','')), 'home_id': h.get('id'),
                        'away_abbr': a_ab, 'away_score': a.get('score','0'), 'away_logo': self.get_corrected_logo(league_key, a_ab, a['team'].get('logo','')), 'away_id': a.get('id'),
                        'home_color': f"#{h_clr}", 'home_alt_color': f"#{h_alt}", 'away_color': f"#{a_clr}", 'away_alt_color': f"#{a_alt}",
                        'startTimeUTC': utc_start, 'situation': { 'possession': poss, 'isRedZone': sit.get('isRedZone', False), 'downDist': sit.get('downDistanceText', '') }
                    }
                    if league_key == 'mlb': game_obj['situation'].update({'balls': sit.get('balls', 0), 'strikes': sit.get('strikes', 0), 'outs': sit.get('outs', 0), 'onFirst': sit.get('onFirst', False), 'onSecond': sit.get('onSecond', False), 'onThird': sit.get('onThird', False)})
                    games.append(game_obj)
            except: pass
        return games

    def generate_demo_data(self):
        return [{'type': 'leaderboard', 'sport': 'f1', 'id': 'demo_f1', 'status': 'Lap 45/78', 'state': 'in', 'tourney_name': 'Monaco GP', 'is_shown': True, 'leaders': [{'rank': '1', 'name': 'Verstappen', 'score': 'LDR'}, {'rank': '2', 'name': 'Norris', 'score': '+2.4s'}]}, {'type': 'scoreboard', 'sport': 'nfl', 'id': 'demo_nfl', 'status': '4th 2:00', 'state': 'in', 'is_shown': True, 'home_abbr': 'KC', 'home_score': '24', 'home_logo': 'https://a.espncdn.com/i/teamlogos/nfl/500/kc.png', 'home_color': '#e31837', 'home_alt_color': '#ffb81c', 'away_abbr': 'BUF', 'away_score': '20', 'away_logo': 'https://a.espncdn.com/i/teamlogos/nfl/500/buf.png', 'away_color': '#00338d', 'away_alt_color': '#c60c30', 'situation': {'possession': 'KC', 'isRedZone': True, 'downDist': '1st & Goal'}}]

    def fetch_all_teams(self):
        teams_catalog = {k: [] for k in self.leagues.keys()}
        for league_key, config in self.leagues.items():
            if config.get('type') != 'scoreboard': continue
            try:
                url = f"{self.base_url}{config['path']}/teams"
                r = requests.get(url, params={'limit': 1000}, headers=HEADERS, timeout=10)
                data = r.json()
                if 'sports' in data:
                    for sport in data['sports']:
                        for league in sport['leagues']:
                            for item in league.get('teams', []):
                                t = item['team']
                                abbr = t.get('abbreviation','UNK'); logo = t.get('logos',[{}])[0].get('href','')
                                logo = self.get_corrected_logo(league_key, abbr, logo)
                                teams_catalog[league_key].append({'abbr': abbr, 'logo': logo})
            except: pass
        with data_lock:
            manager.all_teams_data = teams_catalog
            manager.save()

fetcher = SportsFetcher()

# ================= FLASK API =================
app = Flask(__name__)

@app.route('/data')
def route_data_global():
    with data_lock: conf = manager.get_device('default')
    games = fetcher.get_games(conf)
    return jsonify({'meta': {'is_setup': False}, 'games': games})

@app.route('/data/<device_id>')
def route_data_device(device_id):
    with data_lock: conf = manager.get_device(device_id)
    if conf.get('setup_mode'): return jsonify({'meta': {'is_setup': True, 'pairing_code': conf['pairing_code']}, 'games': []})
    games = fetcher.get_games(conf)
    return jsonify({'meta': {'is_setup': False, 'brightness': conf['brightness'], 'scroll_speed': conf['scroll_speed'], 'inverted': conf['inverted'], 'scroll_seamless': conf['scroll_seamless']}, 'games': games})

@app.route('/setup', methods=['GET', 'POST'])
def route_setup():
    if request.method == 'GET': return "<h1>Sports Ticker API</h1><p>Use the iOS App to Pair.</p>"
    code = request.json.get('code', '')
    mac, data = manager.claim_device(code)
    if mac: return jsonify({"status": "ok", "device_id": mac, "name": data['name']})
    return jsonify({"status": "error", "message": "Invalid Code"}), 404

@app.route('/config/<device_id>', methods=['POST'])
def route_config(device_id):
    with data_lock: manager.update_device(device_id, request.json)
    return jsonify({"status": "ok"})

@app.route('/state/<device_id>')
def route_state(device_id):
    with data_lock: conf = manager.get_device(device_id)
    games = fetcher.get_games(conf)
    return jsonify({'settings': conf, 'games': games})

@app.route('/teams')
def route_teams():
    return jsonify(manager.all_teams_data)

if __name__ == "__main__":
    threading.Thread(target=fetcher.fetch_all_teams, daemon=True).start()
    app.run(host='0.0.0.0', port=5000)
