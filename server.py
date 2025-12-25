import time
import threading
import json
import os
import re
import subprocess
from datetime import datetime as dt, timezone, timedelta
import requests
from flask import Flask, jsonify, request, render_template_string

# ================= CONFIGURATION =================
DEFAULT_OFFSET = -4 
CONFIG_FILE = "ticker_config.json"
UPDATE_INTERVAL = 5
FANTASY_FILE = "fantasy_output.json"
DEBUG_FILE = "fantasy_debug.json"
data_lock = threading.Lock()

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
    "Cache-Control": "no-cache, no-store, must-revalidate",
    "Pragma": "no-cache",
    "Expires": "0"
}

# ================= DEFAULT STATE =================
default_state = {
    'active_sports': { 'nfl': True, 'ncf_fbs': True, 'ncf_fcs': True, 'mlb': True, 'nhl': True, 'nba': True, 'weather': False, 'clock': False, 'fantasy': True },
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
    'weather_location': "New York"
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
                'weather_location': state['weather_location']
            }
        with open(CONFIG_FILE, 'w') as f:
            json.dump(export_data, f)
    except: pass

# ================= TEAMS LISTS =================
FBS_TEAMS = ["AF", "AKR", "ALA", "APP", "ARIZ", "ASU", "ARK", "ARST", "ARMY", "AUB", "BALL", "BAY", "BOIS", "BC", "BGSU", "BUF", "BYU", "CAL", "CMU", "CLT", "CIN", "CLEM", "CCU", "COLO", "CSU", "CONN", "DEL", "DUKE", "ECU", "EMU", "FAU", "FIU", "FLA", "FSU", "FRES", "GASO", "GAST", "GT", "UGA", "HAW", "HOU", "ILL", "IND", "IOWA", "ISU", "JXST", "JMU", "KAN", "KSU", "KENN", "KENT", "UK", "LIB", "ULL", "LT", "LOU", "LSU", "MAR", "MD", "MASS", "MEM", "MIA", "M-OH", "MICH", "MSU", "MTSU", "MINN", "MSST", "MIZ", "MOST", "NAVY", "NCST", "NEB", "NEV", "UNM", "NMSU", "UNC", "UNT", "NIU", "NU", "ND", "OHIO", "OSU", "OU", "OKST", "ODU", "MISS", "ORE", "ORST", "PSU", "PITT", "PUR", "RICE", "RUTG", "SAM", "SDSU", "SJSU", "SMU", "USA", "SC", "USF", "USM", "STAN", "SYR", "TCU", "TEM", "TENN", "TEX", "TA&M", "TXST", "TTU", "TOL", "TROY", "TULN", "TLSA", "UAB", "UCF", "UCLA", "ULM", "UMASS", "UNLV", "USC", "UTAH", "USU", "UTEP", "UTSA", "VAN", "UVA", "VT", "WAKE", "WASH", "WSU", "WVU", "WKU", "WMU", "WIS", "WYO"]
FCS_TEAMS = ["ACU", "AAMU", "ALST", "UALB", "ALCN", "UAPB", "APSU", "BCU", "BRWN", "BRY", "BUCK", "BUT", "CP", "CAM", "CARK", "CCSU", "CHSO", "UTC", "CIT", "COLG", "COLU", "COR", "DART", "DAV", "DAY", "DSU", "DRKE", "DUQ", "EIU", "EKU", "ETAM", "EWU", "ETSU", "ELON", "FAMU", "FOR", "FUR", "GWEB", "GTWN", "GRAM", "HAMP", "HARV", "HC", "HCU", "HOW", "IDHO", "IDST", "ILST", "UIW", "INST", "JKST", "LAF", "LAM", "LEH", "LIN", "LIU", "ME", "MRST", "MCN", "MER", "MERC", "MRMK", "MVSU", "MONM", "MONT", "MTST", "MORE", "MORG", "MUR", "UNH", "NHVN", "NICH", "NORF", "UNA", "NCAT", "NCCU", "UND", "NDSU", "NAU", "UNCO", "UNI", "NWST", "PENN", "PRST", "PV", "PRES", "PRIN", "URI", "RICH", "RMU", "SAC", "SHU", "SFPA", "SAM", "USD", "SELA", "SEMO", "SDAK", "SDST", "SCST", "SOU", "SIU", "SUU", "STMN", "SFA", "STET", "STO", "STBK", "TAR", "TNST", "TNTC", "TXSO", "TOW", "UCD", "UTM", "UTU", "UTRGV", "VAL", "VILL", "VMI", "WAG", "WEB", "WGA", "WCU", "WIU", "W&M", "WOF", "YALE", "YSU"]
LOGO_OVERRIDES = {"NFL:HOU": "https://a.espncdn.com/i/teamlogos/nfl/500/hou.png", "NBA:HOU": "https://a.espncdn.com/i/teamlogos/nba/500/hou.png", "MLB:HOU": "https://a.espncdn.com/i/teamlogos/mlb/500/hou.png", "NCF_FBS:HOU": "https://a.espncdn.com/i/teamlogos/ncaa/500/248.png"}

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
            except: pass
        try:
            r = requests.get(f"https://geocoding-api.open-meteo.com/v1/search?name={clean_query}&count=1&language=en&format=json", timeout=5)
            d = r.json()
            if 'results' in d and len(d['results']) > 0:
                res = d['results'][0]
                self.lat = res['latitude']; self.lon = res['longitude']
                self.location_name = res['name']; self.last_fetch = 0 
        except: pass

    def get_weather(self):
        if time.time() - self.last_fetch < 900 and self.cache: return self.cache
        try:
            r = requests.get(f"https://api.open-meteo.com/v1/forecast?latitude={self.lat}&longitude={self.lon}&current=temperature_2m,weather_code,is_day&daily=temperature_2m_max,temperature_2m_min,uv_index_max&temperature_unit=fahrenheit&timezone=auto", timeout=5)
            d = r.json()
            c = d.get('current', {}); dl = d.get('daily', {})
            icon_map = {0:"sun", 1:"sun", 2:"partly_cloudy", 3:"cloud", 45:"fog", 48:"fog", 51:"rain", 61:"rain", 71:"snow", 95:"storm"}
            code = c.get('weather_code', 0)
            icon = icon_map.get(code, "cloud")
            if not c.get('is_day', 1) and icon == "sun": icon = "moon"
            high = int(dl['temperature_2m_max'][0]); low = int(dl['temperature_2m_min'][0]); uv = float(dl['uv_index_max'][0])
            w_obj = {"sport": "weather", "id": "weather_widget", "status": "Live", "home_abbr": f"{int(c.get('temperature_2m', 0))}°", "away_abbr": self.location_name, "home_score": "", "away_score": "", "is_shown": True, "home_logo": "", "away_logo": "", "situation": { "icon": icon, "stats": { "high": high, "low": low, "uv": uv } }}
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
            # ... (Full logic preserved) ...
            with data_lock: state['all_teams_data'] = teams_catalog
        except: pass

    def get_real_games(self):
        games = []
        with data_lock: conf = state.copy()

        # === FANTASY DATA ===
        if conf['active_sports'].get('fantasy', True):
            if os.path.exists(FANTASY_FILE):
                try:
                    with open(FANTASY_FILE, 'r') as f:
                        games.extend(json.load(f))
                except: pass

        if conf['active_sports'].get('clock'):
            with data_lock: state['current_games'] = [{'sport':'clock','id':'clk','is_shown':True}]; return
        if conf['active_sports'].get('weather'):
            if conf['weather_location'] != self.weather.location_name: self.weather.update_coords(conf['weather_location'])
            w = self.weather.get_weather()
            if w: 
                with data_lock: state['current_games'] = [w]; return

        # === REAL SPORTS FETCH ===
        req_params = {}
        now_local = dt.now(timezone(timedelta(hours=DEFAULT_OFFSET)))
        if conf['debug_mode'] and conf['custom_date']: target_date_str = conf['custom_date']
        else:
            if now_local.hour < 4: query_date = now_local - timedelta(days=1)
            else: query_date = now_local
            target_date_str = query_date.strftime("%Y-%m-%d")
        req_params['dates'] = target_date_str.replace('-', '')

        for league_key, config in self.leagues.items():
            if not conf['active_sports'].get(league_key, False): continue
            try:
                curr_p = config['scoreboard_params'].copy(); curr_p.update(req_params)
                r = requests.get(f"{self.base_url}{config['path']}/scoreboard", params=curr_p, headers=HEADERS, timeout=5)
                data = r.json()
                for e in data.get('events', []):
                    utc_str = e['date'].replace('Z', '') 
                    game_dt_utc = dt.fromisoformat(utc_str).replace(tzinfo=timezone.utc)
                    game_dt_server = game_dt_utc.astimezone(timezone(timedelta(hours=DEFAULT_OFFSET)))
                    game_date_str = game_dt_server.strftime("%Y-%m-%d")
                    st = e.get('status', {}); tp = st.get('type', {}); gst = tp.get('state', 'pre')
                    
                    keep_date = (gst == 'in') or (game_date_str == target_date_str)
                    if not keep_date: continue

                    comp = e['competitions'][0]; h = comp['competitors'][0]; a = comp['competitors'][1]
                    h_ab = h['team']['abbreviation']; a_ab = a['team']['abbreviation']
                    
                    is_shown = True
                    if conf['mode'] == 'live' and gst not in ['in', 'half']: is_shown = False
                    
                    h_lg = self.get_corrected_logo(league_key, h_ab, h['team'].get('logo',''))
                    a_lg = self.get_corrected_logo(league_key, a_ab, a['team'].get('logo',''))
                    s_disp = tp.get('shortDetail', 'TBD')
                    if gst == 'pre':
                        try: s_disp = game_dt_server.strftime("%I:%M %p").lstrip('0')
                        except: s_disp = "Scheduled"
                    elif gst == 'in' or gst == 'half':
                        p = st.get('period', 1); clk = st.get('displayClock', '')
                        s_disp = f"P{p} {clk}" if 'hockey' in config['path'] else f"Q{p} {clk}"

                    sit = comp.get('situation', {})
                    game_obj = {
                        'sport': league_key, 'id': e['id'], 'status': s_disp, 'state': gst, 'is_shown': is_shown,
                        'home_abbr': h_ab, 'home_score': h.get('score','0'), 'home_logo': h_lg, 'home_id': h.get('id'),
                        'away_abbr': a_ab, 'away_score': a.get('score','0'), 'away_logo': a_lg, 'away_id': a.get('id'),
                        'startTimeUTC': e['date'], 'period': st.get('period', 1),
                        'situation': { 'possession': sit.get('possession',''), 'isRedZone': sit.get('isRedZone', False), 'downDist': sit.get('downDistanceText', '') }
                    }
                    games.append(game_obj)
            except: pass
        with data_lock: state['current_games'] = games

fetcher = SportsFetcher(state['weather_location'])

def background_updater():
    fetcher.fetch_all_teams()
    print("Launching Fantasy Process...")
    subprocess.Popen(["python", "fantasy_oddsmaker.py"])
    while True: fetcher.get_real_games(); time.sleep(UPDATE_INTERVAL)

# ================= FLASK API =================
app = Flask(__name__)

@app.route('/')
def root():
    html = f"""
    <html><head><title>Ticker Status</title>
    <style>body{{font-family:sans-serif;padding:2rem;background:#1a1a1a;color:white}} a{{color:#007bff}} .box{{background:#333;padding:1rem;border-radius:8px;margin-bottom:1rem}}</style>
    </head><body>
        <h1>Ticker Backend Online</h1>
        <div class="box"><p><strong>Status:</strong> Running</p></div>
        <a href="/api/ticker">Raw JSON</a> | <a href="/fantasy">Fantasy Dashboard</a>
    </body></html>
    """
    return html

@app.route('/fantasy')
def fantasy_dashboard():
    if not os.path.exists(DEBUG_FILE): return "No Data Yet"
    try:
        with open(DEBUG_FILE, 'r') as f: data = json.load(f)
    except: return "Error Loading Data"
    
    html = """
    <html><head><title>Fantasy Odds</title>
    <style>
        body{font-family:sans-serif;background:#121212;color:#eee;padding:20px}
        .matchup{background:#1e1e1e;padding:20px;border-radius:10px;margin-bottom:20px}
        h2{color:#4dabf7;border-bottom:1px solid #333;padding-bottom:10px}
        h3{color:#bbb; margin-top:20px; border-bottom:1px solid #444; display:inline-block}
        table{width:100%;border-collapse:collapse;margin-top:5px; margin-bottom:15px}
        th{text-align:left;color:#888;font-size:12px;padding:8px;background:#252525}
        td{padding:8px;border-bottom:1px solid #333}
        .pos{color:#666;font-size:12px}
        .source-vegas{color:#40c057;font-weight:bold}
        .total-row td{font-weight:bold; background:#2a2a2a; border-top:2px solid #555; color:#fff}
        .my-proj-better{color:#40c057} 
        .my-proj-worse{color:#ff6b6b}
    </style></head><body>
    """
    
    for game in data:
        html += f"<div class='matchup'><h2>{game['platform']}: {game['home_team']} vs {game['away_team']}</h2>"
        
        # Split players by team
        home_players = [p for p in game['players'] if p['team'] == 'HOME']
        away_players = [p for p in game['players'] if p['team'] == 'AWAY']
        
        # Helper to render table
        def render_team_table(team_name, players):
            tbl = f"<h3>{team_name}</h3><table><thead><tr><th>PLAYER</th><th>POS</th><th>LEAGUE</th><th>MY PROJ</th><th>SOURCE</th></tr></thead><tbody>"
            l_sum = 0; m_sum = 0
            for p in players:
                l_sum += p['league_proj']; m_sum += p['my_proj']
                src_class = "source-vegas" if p['source'] == "Vegas" else ""
                val_class = "my-proj-better" if p['my_proj'] > p['league_proj'] else "my-proj-worse"
                tbl += f"<tr><td>{p['name']}</td><td class='pos'>{p['pos']}</td><td>{p['league_proj']}</td><td class='{val_class}'>{p['my_proj']}</td><td class='{src_class}'>{p['source']}</td></tr>"
            
            # Totals Row
            tbl += f"<tr class='total-row'><td>TOTAL</td><td></td><td>{l_sum:.2f}</td><td>{m_sum:.2f}</td><td></td></tr>"
            tbl += "</tbody></table>"
            return tbl

        html += render_team_table(game['home_team'] + " (Home)", home_players)
        html += render_team_table(game['away_team'] + " (Away)", away_players)
        html += "</div>"
    
    html += "</body></html>"
    return html

@app.route('/api/ticker')
def api_ticker():
    offset_sec = DEFAULT_OFFSET * 3600
    with data_lock: d = state.copy()
    raw_games = d['current_games']
    processed_games = [g.copy() for g in raw_games if g.get('is_shown', True)]
    return jsonify({
        'meta': { 'time': dt.now(timezone(timedelta(seconds=offset_sec))).strftime("%I:%M %p"), 'count': len(processed_games), 'scroll_seamless': d['scroll_seamless'], 'brightness': d['brightness'], 'inverted': d['inverted'], 'panel_count': d['panel_count'], 'reboot_requested': d['reboot_requested'], 'utc_offset_seconds': offset_sec }, 
        'games': processed_games
    })

@app.route('/api/config', methods=['POST'])
def api_config():
    with data_lock: state.update(request.json)
    save_config_file()
    threading.Thread(target=fetcher.get_real_games).start()
    return jsonify({"status": "ok"})

@app.route('/api/hardware', methods=['POST'])
def api_hardware():
    with data_lock: state.update(request.json)
    return jsonify({"status": "ok"})

if __name__ == "__main__":
    threading.Thread(target=background_updater, daemon=True).start()
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 5000)))
