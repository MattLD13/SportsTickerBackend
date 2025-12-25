import time
import threading
import json
import os
import re
import subprocess
import sys
import requests
from datetime import datetime as dt, timezone, timedelta
from flask import Flask, jsonify, request

PORT = int(os.environ.get("PORT", 5000))
DEFAULT_OFFSET = -4 
UPDATE_INTERVAL = 10
CONFIG_FILE = "ticker_config.json"
FANTASY_FILE = "fantasy_output.json"
DEBUG_FILE = "fantasy_debug.json"
data_lock = threading.Lock()

HEADERS = {"User-Agent": "Mozilla/5.0", "Cache-Control": "no-cache"}

state = {
    'active_sports': { 'nfl': True, 'ncf_fbs': True, 'ncf_fcs': True, 'mlb': True, 'nhl': True, 'nba': True, 'weather': False, 'clock': False, 'fantasy': True },
    'mode': 'all', 'scroll_seamless': False, 'my_teams': [], 'current_games': [],
    'all_teams_data': {}, 'debug_mode': False, 'custom_date': None,
    'brightness': 0.5, 'inverted': False, 'panel_count': 2,
    'test_pattern': False, 'reboot_requested': False, 'weather_location': "New York"
}

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
            with open(CONFIG_FILE, 'w') as f: json.dump(state, f)
    except: pass

FBS_TEAMS = ["AF", "AKR", "ALA", "APP", "ARIZ", "ASU", "ARK", "ARST", "ARMY", "AUB", "BALL", "BAY", "BOIS", "BC", "BGSU", "BUF", "BYU", "CAL", "CMU", "CLT", "CIN", "CLEM", "CCU", "COLO", "CSU", "CONN", "DEL", "DUKE", "ECU", "EMU", "FAU", "FIU", "FLA", "FSU", "FRES", "GASO", "GAST", "GT", "UGA", "HAW", "HOU", "ILL", "IND", "IOWA", "ISU", "JXST", "JMU", "KAN", "KSU", "KENN", "KENT", "UK", "LIB", "ULL", "LT", "LOU", "LSU", "MAR", "MD", "MASS", "MEM", "MIA", "M-OH", "MICH", "MSU", "MTSU", "MINN", "MSST", "MIZ", "MOST", "NAVY", "NCST", "NEB", "NEV", "UNM", "NMSU", "UNC", "UNT", "NIU", "NU", "ND", "OHIO", "OSU", "OU", "OKST", "ODU", "MISS", "ORE", "ORST", "PSU", "PITT", "PUR", "RICE", "RUTG", "SAM", "SDSU", "SJSU", "SMU", "USA", "SC", "USF", "USM", "STAN", "SYR", "TCU", "TEM", "TENN", "TEX", "TA&M", "TXST", "TTU", "TOL", "TROY", "TULN", "TLSA", "UAB", "UCF", "UCLA", "ULM", "UMASS", "UNLV", "USC", "UTAH", "USU", "UTEP", "UTSA", "VAN", "UVA", "VT", "WAKE", "WASH", "WSU", "WVU", "WKU", "WMU", "WIS", "WYO"]
FCS_TEAMS = ["ACU", "AAMU", "ALST", "UALB", "ALCN", "UAPB", "APSU", "BCU", "BRWN", "BRY", "BUCK", "BUT", "CP", "CAM", "CARK", "CCSU", "CHSO", "UTC", "CIT", "COLG", "COLU", "COR", "DART", "DAV", "DAY", "DSU", "DRKE", "DUQ", "EIU", "EKU", "ETAM", "EWU", "ETSU", "ELON", "FAMU", "FOR", "FUR", "GWEB", "GTWN", "GRAM", "HAMP", "HARV", "HC", "HCU", "HOW", "IDHO", "IDST", "ILST", "UIW", "INST", "JKST", "LAF", "LAM", "LEH", "LIN", "LIU", "ME", "MRST", "MCN", "MER", "MERC", "MRMK", "MVSU", "MONM", "MONT", "MTST", "MORE", "MORG", "MUR", "UNH", "NHVN", "NICH", "NORF", "UNA", "NCAT", "NCCU", "UND", "NDSU", "NAU", "UNCO", "UNI", "NWST", "PENN", "PRST", "PV", "PRES", "PRIN", "URI", "RICH", "RMU", "SAC", "SHU", "SFPA", "SAM", "USD", "SELA", "SEMO", "SDAK", "SDST", "SCST", "SOU", "SIU", "SUU", "STMN", "SFA", "STET", "STO", "STBK", "TAR", "TNST", "TNTC", "TXSO", "TOW", "UCD", "UTM", "UTU", "UTRGV", "VAL", "VILL", "VMI", "WAG", "WEB", "WGA", "WCU", "WIU", "W&M", "WOF", "YALE", "YSU"]
LOGO_OVERRIDES = {"NFL:HOU": "https://a.espncdn.com/i/teamlogos/nfl/500/hou.png", "NCF_FBS:CAL": "https://a.espncdn.com/i/teamlogos/ncaa/500/25.png"}

class WeatherFetcher:
    def __init__(self, loc): self.loc=loc; self.lat=40.71; self.lon=-74.00; self.update_coords(loc)
    def update_coords(self, q):
        try:
            r=requests.get(f"https://geocoding-api.open-meteo.com/v1/search?name={q}&count=1&format=json", timeout=5).json()
            if 'results' in r: self.lat=r['results'][0]['latitude']; self.lon=r['results'][0]['longitude']; self.loc=r['results'][0]['name']
        except: pass
    def get_weather(self):
        try:
            r=requests.get(f"https://api.open-meteo.com/v1/forecast?latitude={self.lat}&longitude={self.lon}&current=temperature_2m,weather_code,is_day&daily=temperature_2m_max,temperature_2m_min&temperature_unit=fahrenheit", timeout=5).json()
            c=r['current']; d=r['daily']
            return {"sport":"weather","id":"w","home_abbr":f"{int(c['temperature_2m'])}°","away_abbr":self.loc,"situation":{"icon":"cloud","stats":{"high":int(d['temperature_2m_max'][0]),"low":int(d['temperature_2m_min'][0])}}}
        except: return None

class SportsFetcher:
    def __init__(self, loc):
        self.w=WeatherFetcher(loc); self.base="http://site.api.espn.com/apis/site/v2/sports/"
        self.leagues={'nfl':'football/nfl','nba':'basketball/nba','mlb':'baseball/mlb','nhl':'hockey/nhl','ncf_fbs':'football/college-football'}
    
    def fetch_all_teams(self): pass 

    def get_corrected_logo(self, l, a, d): return LOGO_OVERRIDES.get(f"{l.upper()}:{a}", d)

    def get_real_games(self):
        games=[]
        with data_lock: conf=state.copy()
        
        if conf['active_sports'].get('fantasy') and os.path.exists(FANTASY_FILE):
            try: 
                with open(FANTASY_FILE,'r') as f: 
                    d=json.load(f)
                    if isinstance(d,list): games.extend([x for x in d if x])
            except: pass
            
        if conf['active_sports'].get('weather'):
            if conf['weather_location']!=self.w.loc: self.w.update_coords(conf['weather_location'])
            w=self.w.get_weather(); 
            if w: games.append(w)

        dt_str = (dt.now(timezone(timedelta(hours=DEFAULT_OFFSET))) - timedelta(days=1 if dt.now().hour<4 else 0)).strftime("%Y%m%d")
        
        for l, p in self.leagues.items():
            if not conf['active_sports'].get(l): continue
            try:
                u=f"{self.base}{p}/scoreboard?dates={dt_str}&limit=100"
                if 'college' in l: u+="&groups=80"
                d=requests.get(u,timeout=4).json()
                for e in d['events']:
                    s=e['status']; t=s['type']
                    if t['state']=='pre' and 'TBD' in t['shortDetail']: continue
                    c=e['competitions'][0]; h=c['competitors'][0]; a=c['competitors'][1]
                    games.append({
                        "sport":l,"id":e['id'],"status":t['shortDetail'],
                        "home_abbr":h['team']['abbreviation'],"home_score":h.get('score','0'),
                        "home_logo":self.get_corrected_logo(l,h['team']['abbreviation'],h['team'].get('logo','')),
                        "away_abbr":a['team']['abbreviation'],"away_score":a.get('score','0'),
                        "away_logo":self.get_corrected_logo(l,a['team']['abbreviation'],a['team'].get('logo','')),
                        "is_shown":True
                    })
            except: pass
        with data_lock: state['current_games']=games

fetcher=SportsFetcher(state['weather_location'])

def background_updater():
    try: subprocess.Popen([sys.executable, "fantasy_oddsmaker.py"])
    except: pass
    while True: fetcher.get_real_games(); time.sleep(UPDATE_INTERVAL)

app = Flask(__name__)

@app.route('/')
def root(): with data_lock: return jsonify({'games':state['current_games']})

@app.route('/fantasy')
def fantasy_dashboard():
    try:
        if os.path.exists(DEBUG_FILE):
            with open(DEBUG_FILE,'r') as f: d=json.load(f)
            
            h = """<html><head><meta http-equiv='refresh' content='30'>
            <style>
                body{background:#111;color:#eee;font-family:sans-serif;padding:20px}
                .m{background:#222;padding:15px;margin:10px;border-radius:8px}
                .g{color:#4f4} .b{color:#f44} .n{color:#aaa}
                table{width:100%;border-collapse:collapse} 
                th{text-align:left;color:#888;font-size:12px;border-bottom:1px solid #444;padding:5px}
                td{padding:6px;border-bottom:1px solid #333}
                .total{font-weight:bold;border-top:2px solid #555;background:#2a2a2a}
            </style></head><body>"""
            
            for g in d:
                if not g: continue
                h += f"<div class='m'><h2>{g.get('platform')}</h2>"
                
                for side in ['HOME','AWAY']:
                    tm_name = g.get('home_team' if side=='HOME' else 'away_team')
                    h += f"<h3>{tm_name}</h3><table><thead><tr><th>PLAYER</th><th>POS</th><th>LIVE</th><th>COMBO</th><th>VEGAS</th><th>LEAGUE</th></tr></thead><tbody>"
                    
                    players = [x for x in g.get('players',[]) if x.get('team')==side]
                    v_sum = 0; c_sum = 0; l_sum = 0; live_sum = 0
                    
                    for p in players:
                        live = p.get('live_score', 0.0)
                        vegas = p['my_proj']
                        league = p['league_proj']
                        
                        # Combo = Average of the Two Final Projections
                        combo = (vegas + league) / 2.0
                        
                        v_sum += vegas; l_sum += league; c_sum += combo; live_sum += live
                        
                        # Compare Combo to League
                        color = "g" if combo > league else "b"
                        
                        h += f"<tr><td>{p['name']}</td><td>{p.get('pos')}</td><td class='n'>{live:.1f}</td><td class='{color}'>{combo:.2f}</td><td>{vegas:.2f}</td><td>{league:.2f}</td></tr>"
                    
                    diff = c_sum - l_sum
                    color_diff = "#4f4" if diff > 0 else "#f44"
                    h += f"<tr class='total'><td>TOTAL</td><td></td><td>{live_sum:.1f}</td><td style='color:{color_diff}'>{c_sum:.2f} ({diff:+.2f})</td><td>{v_sum:.2f}</td><td>{l_sum:.2f}</td></tr>"
                    h += "</tbody></table>"
                h += "</div>"
            return h + "</body></html>"
    except Exception as e:
        return f"<h3>Loading Data... ({str(e)})</h3>"
    return "<h3>Waiting for data...</h3>"

@app.route('/api/ticker')
def api_ticker(): with data_lock: return jsonify({'games':state['current_games']})

@app.route('/api/config', methods=['POST'])
def api_config(): 
    with data_lock: state.update(request.json); save_config_file()
    return jsonify({"status":"ok"})

if __name__=="__main__":
    threading.Thread(target=background_updater, daemon=True).start()
    app.run(host='0.0.0.0', port=PORT)
