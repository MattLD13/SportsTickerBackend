import time
import threading
import json
import os
import io
import struct
import datetime
from datetime import datetime as dt, timezone, timedelta
import requests
from flask import Flask, jsonify, request, send_file, Response, redirect
from PIL import Image

# ================= VALID TEAMS CONFIGURATION =================
# Integrated directly to prevent import errors
FBS_TEAMS = [
    "AF", "AKR", "ALA", "APP", "ARIZ", "ASU", "ARK", "ARST", "ARMY", "AUB", 
    "BALL", "BAY", "BOIS", "BC", "BGSU", "BUF", "BYU", "CAL", "CMU", "CLT", 
    "CIN", "CLEM", "CCU", "COLO", "CSU", "CONN", "DEL", "DUKE", "ECU", "EMU", 
    "FAU", "FIU", "FLA", "FSU", "FRES", "GASO", "GAST", "GT", "UGA", "HAW", 
    "HOU", "ILL", "IND", "IOWA", "ISU", "JMU", "JXST", "KAN", "KSU", "KENN", 
    "KENT", "UK", "LIB", "LOU", "LT", "LSU", "MAR", "MD", "MASS", "MEM", 
    "MIA", "M-OH", "MICH", "MSU", "MTSU", "MINN", "MSST", "MIZ", "MOST", 
    "NAVY", "NCST", "NEB", "NEV", "UNM", "NMSU", "UNC", "UNT", "NIU", "NU", 
    "ND", "OHIO", "OSU", "OU", "OKST", "ODU", "MISS", "ORE", "ORST", "PSU", 
    "PITT", "PUR", "RICE", "RUTG", "SAM", "SDSU", "SJSU", "SMU", "USA", "SC", 
    "USF", "USM", "STAN", "SYR", "TCU", "TEM", "TENN", "TEX", "TA&M", "TXST", 
    "TTU", "TOL", "TROY", "TULN", "TLSA", "UAB", "UCF", "UCLA", "ULM", "ULL", 
    "UNLV", "USC", "UTAH", "USU", "UTEP", "UTSA", "VAN", "UVA", "VT", "WAKE", 
    "WASH", "WSU", "WVU", "WKU", "WMU", "WIS", "WYO"
]

FCS_TEAMS = [
    "ACU", "AAMU", "ALST", "UALB", "ALCN", "UAPB", "APSU", "BCU", "BRWN", 
    "BRY", "BUCK", "BUT", "CP", "CAM", "CARK", "CCSU", "CHSO", "UTC", "CIT", 
    "COLG", "COLU", "COR", "DART", "DAV", "DAY", "DSU", "DRKE", "DUQ", "EIU", 
    "EKU", "ETAM", "EWU", "ETSU", "ELON", "FAMU", "FOR", "FUR", "GWEB", 
    "GTWN", "GRAM", "HAMP", "HARV", "HC", "HCU", "HOW", "IDHO", "IDST", 
    "ILST", "UIW", "INST", "JKST", "LAF", "LAM", "LEH", "LIN", "LIU", 
    "ME", "MRST", "MCN", "MER", "MERC", "MRMK", "MVSU", "MONM", "MONT", 
    "MTST", "MORE", "MORG", "MUR", "UNH", "NHVN", "NICH", "NORF", "UNA", 
    "NCAT", "NCCU", "UND", "NDSU", "NAU", "UNCO", "UNI", "NWST", "PENN", 
    "PRST", "PV", "PRES", "PRIN", "URI", "RICH", "RMU", "SAC", "SHU", 
    "SFPA", "SAM", "USD", "SELA", "SEMO", "SDAK", "SDST", "SCST", "SOU", 
    "SIU", "SUU", "STMN", "SFA", "STET", "STO", "STBK", "TAR", "TNST", 
    "TNTC", "TXSO", "TOW", "UCD", "UTM", "UTU", "VAL", "VILL", "VMI", "WAG", 
    "WEB", "WGA", "WCU", "WIU", "W&M", "WOF", "YALE", "YSU"
]

# ================= CONFIGURATION =================
TIMEZONE_OFFSET = -5  
CONFIG_FILE = "ticker_config.json"
UPDATE_INTERVAL = 30 # Slower update to prevent ESPN rate limiting

# --- NHL LOGO FIXES ---
NHL_LOGO_MAP = {
    "SJS": "sj", "NJD": "nj", "TBL": "tb", "LAK": "la", "VGK": "vgs", "VEG": "vgs", "UTA": "utah"
}

# ================= IMAGE PROCESSING ENGINE =================
logo_cache = {} 

def fetch_and_convert_logo(abbr, sport):
    """
    1. Finds the logo URL for the team (using ESPN's predictable URL structure).
    2. Downloads and resizes to 24x24.
    3. Converts to Raw RGB565 bytes for ESP32.
    """
    # 1. Construct URL based on sport/abbr
    if sport == 'nhl':
        code = NHL_LOGO_MAP.get(abbr, abbr.lower())
        url = f"https://a.espncdn.com/i/teamlogos/nhl/500/{code}.png"
        if abbr == 'WSH': url = "https://a.espncdn.com/guid/cbe677ee-361e-91b4-5cae-6c4c30044743/logos/secondary_logo_on_black_color.png"
    elif sport == 'ncf_fbs' or sport == 'ncf_fcs':
        url = f"https://a.espncdn.com/i/teamlogos/ncaa/500/{abbr}.png"
    else:
        url = f"https://a.espncdn.com/i/teamlogos/{sport}/500/{abbr}.png"

    # 2. Download & Process
    try:
        r = requests.get(url, timeout=2)
        if r.status_code != 200: return None
        
        img = Image.open(io.BytesIO(r.content)).convert("RGBA")
        img = img.resize((24, 24), Image.Resampling.LANCZOS)
        
        # Handle Transparency (Paste onto black background)
        bg = Image.new("RGBA", (24, 24), (0, 0, 0))
        img = Image.alpha_composite(bg, img).convert("RGB")
        
        # 3. Convert to RGB565 (Little Endian)
        output = io.BytesIO()
        for y in range(24):
            for x in range(24):
                r, g, b = img.getpixel((x, y))
                # RGB565: R5, G6, B5
                c = ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)
                output.write(struct.pack('<H', c))
        return output.getvalue()
    except Exception as e:
        print(f"Logo Error {abbr}: {e}")
        return None

# ================= STATE & FETCHING =================
class TickerState:
    def __init__(self):
        self.settings = self.load_config()
        self.game_data = []
        self.all_teams_data = {} # For the Web UI dropdowns

    def load_config(self):
        default = {
            "active_sports": {"nfl": True, "ncf_fbs": True, "ncf_fcs": True, "mlb": True, "nhl": True, "nba": True},
            "my_teams": [], "mode": "all", "scroll_seamless": False, "debug_mode": False, "custom_date": None
        }
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, 'r') as f: default.update(json.load(f))
            except: pass
        return default

    def save_config(self, settings):
        self.settings = settings
        with open(CONFIG_FILE, 'w') as f: json.dump(self.settings, f, indent=4)

state = TickerState()

def get_games():
    """Main fetching loop. Fault tolerant."""
    while True:
        try:
            # 1. Determine Date
            if state.settings.get('debug_mode') and state.settings.get('custom_date'):
                date_str = state.settings['custom_date'].replace('-', '')
            else:
                now = dt.now(timezone(timedelta(hours=TIMEZONE_OFFSET)))
                # If before 4AM, check yesterday (for late west coast games)
                if now.hour < 4: date_str = (now - timedelta(days=1)).strftime("%Y%m%d")
                else: date_str = now.strftime("%Y%m%d")

            # 2. Fetch Sports
            all_games = []
            sports_map = {
                'nfl': 'football/nfl',
                'ncf_fbs': 'football/college-football', # Group 80 handled in logic
                'ncf_fcs': 'football/college-football', # Group 81 handled in logic
                'mlb': 'baseball/mlb',
                'nhl': 'hockey/nhl',
                'nba': 'basketball/nba'
            }

            for sport_key, path in sports_map.items():
                if not state.settings['active_sports'].get(sport_key, True): continue

                url = f"http://site.api.espn.com/apis/site/v2/sports/{path}/scoreboard?dates={date_str}"
                if sport_key == 'ncf_fbs': url += "&groups=80"
                elif sport_key == 'ncf_fcs': url += "&groups=81"
                
                try:
                    r = requests.get(url, timeout=5)
                    data = r.json()
                    
                    for event in data.get('events', []):
                        status = event['status']['type']
                        state_raw = status['state'] # 'pre', 'in', 'post'
                        
                        # --- FILTER LOGIC ---
                        # If Mode is Live, skip non-live games
                        if state.settings['mode'] == 'live' and state_raw not in ['in']: continue
                        
                        comp = event['competitions'][0]
                        home = comp['competitors'][0]
                        away = comp['competitors'][1]
                        
                        h_abbr = home['team']['abbreviation']
                        a_abbr = away['team']['abbreviation']

                        # If Mode is My Teams, skip if neither team is in list
                        if state.settings['mode'] == 'my_teams' and state.settings['my_teams']:
                            if h_abbr not in state.settings['my_teams'] and a_abbr not in state.settings['my_teams']:
                                continue

                        # --- DISPLAY LOGIC ---
                        # Status Text
                        status_txt = status.get('shortDetail', '')
                        
                        # 1. HALFTIME FIX
                        if state_raw == 'half':
                            status_txt = "HALFTIME"
                        elif state_raw == 'in':
                            # 2. FOOTBALL CLOCK FIX
                            clock = event['status'].get('displayClock', '')
                            period = event['status'].get('period', 1)
                            if 'football' in path: # Applies to NFL/FBS/FCS
                                prefix = f"Q{period}" 
                                if clock: status_txt = f"{prefix} - {clock}"
                                else: status_txt = prefix
                            elif 'hockey' in path:
                                prefix = f"P{period}" 
                                if clock: status_txt = f"{prefix} - {clock}"
                                else: status_txt = prefix
                        elif " - " in status_txt: 
                            status_txt = status_txt.split(" - ")[-1] # Remove date from "12/17 - 7:00 PM"

                        # Situation Data (RedZone, etc)
                        sit = comp.get('situation', {})
                        sit_data = {}
                        
                        # 3. REDZONE & SITUATION FIX
                        if state_raw == 'in':
                            is_rz = False
                            if 'football' in path:
                                is_rz = sit.get('isRedZone', False) # Clears automatically if API updates
                            
                            sit_data = {
                                'possession': sit.get('possession'),
                                'isRedZone': is_rz,
                                'downDist': sit.get('downDistanceText', ''),
                                'powerPlay': sit.get('powerPlay', False),
                                'onFirst': sit.get('onFirst', False),
                                'onSecond': sit.get('onSecond', False),
                                'onThird': sit.get('onThird', False)
                            }

                        all_games.append({
                            'game_id': event['id'],
                            'sport': sport_key,
                            'status': status_txt,
                            'away_abbr': a_abbr, 'away_score': int(away.get('score', 0)),
                            'home_abbr': h_abbr, 'home_score': int(home.get('score', 0)),
                            'is_active': (state_raw == 'in'),
                            'situation': sit_data
                        })

                except Exception as e:
                    print(f"Error fetching {sport_key}: {e}")

            state.game_data = all_games
            
        except Exception as e:
            print(f"Critical Loop Error: {e}")
        
        time.sleep(UPDATE_INTERVAL)

# Start Fetch Thread
threading.Thread(target=get_games, daemon=True).start()

# ================= TEAMS LIST FETCHING (Background) =================
def fetch_teams_list():
    """Fetches list of all teams once for the Web UI dropdown"""
    cats = {
        'nfl': 'football/nfl', 'mlb': 'baseball/mlb', 'nhl': 'hockey/nhl', 'nba': 'basketball/nba',
        'ncf_fbs': 'football/college-football' # We will split this manually using the imported lists
    }
    
    while True:
        temp_data = {}
        for k, path in cats.items():
            try:
                r = requests.get(f"http://site.api.espn.com/apis/site/v2/sports/{path}/teams?limit=1000")
                data = r.json()
                team_list = []
                for t in data['sports'][0]['leagues'][0]['teams']:
                    team = t['team']
                    team_list.append({'abbr': team['abbreviation'], 'logo': team.get('logos', [{}])[0].get('href')})
                
                if k == 'ncf_fbs':
                    # Split College into FBS/FCS using the integrated lists
                    temp_data['ncf_fbs'] = [t for t in team_list if t['abbr'] in FBS_TEAMS] if FBS_TEAMS else team_list
                    temp_data['ncf_fcs'] = [t for t in team_list if t['abbr'] in FCS_TEAMS] if FCS_TEAMS else []
                else:
                    temp_data[k] = team_list
            except: pass
        
        state.all_teams_data = temp_data
        time.sleep(3600) # Update once an hour

threading.Thread(target=fetch_teams_list, daemon=True).start()

# ================= FLASK APP =================
app = Flask(__name__)

# --- ROUTES ---
@app.route('/')
def root(): return redirect('/control')

@app.route('/control')
def dashboard():
    return DASHBOARD_HTML

@app.route('/api/ticker')
def api_ticker():
    return jsonify({'games': state.game_data, 'meta': {'scroll_seamless': state.settings['scroll_seamless']}})

@app.route('/api/all_games')
def api_all(): return jsonify({'games': state.game_data})

@app.route('/api/teams')
def api_teams(): return jsonify(state.all_teams_data)

@app.route('/api/state')
def api_state(): return jsonify({'settings': state.settings, 'games': state.game_data})

@app.route('/api/config', methods=['POST'])
def api_config():
    state.save_config(request.json)
    return jsonify({"status": "ok"})

# --- LOGO PROXY ROUTE ---
@app.route('/api/logo/<sport>/<abbr>')
def api_logo(sport, abbr):
    key = f"{sport}_{abbr}"
    
    # Check Cache
    if key in logo_cache:
        return send_file(io.BytesIO(logo_cache[key]), mimetype='application/octet-stream')
    
    # Process New
    blob = fetch_and_convert_logo(abbr, sport)
    if blob:
        logo_cache[key] = blob
        return send_file(io.BytesIO(blob), mimetype='application/octet-stream')
    else:
        return Response(status=404)

# Re-insert the Dashboard HTML string here (same as before)
DASHBOARD_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <title>Ticker Controller</title>
    <style>
        :root { --bg: #0f111a; --card: #1c1f2e; --accent: #ff5722; --text: #e0e0e0; --success: #4caf50; --inactive: #f44336; --warn: #ffeb3b; --blue: #0D47A1; }
        body { background: var(--bg); color: var(--text); font-family: 'Segoe UI', sans-serif; margin: 0; padding: 10px; padding-bottom: 40px; }
        .panel { background: var(--card); padding: 15px; border-radius: 12px; max-width: 800px; margin: 0 auto 15px auto; box-shadow: 0 4px 6px rgba(0,0,0,0.3); }
        .header-row { display: flex; justify-content: space-between; align-items: center; margin-bottom: 15px; }
        .app-title { font-size: 1.2em; font-weight: bold; letter-spacing: 1px; color: white; margin: 0; }
        .hamburger-btn { background: none; border: none; color: #fff; font-size: 1.5em; cursor: pointer; padding: 0 5px; }
        #settingsArea { display: block; overflow: hidden; transition: max-height 0.3s ease-out; margin-top: 5px; padding-top: 15px; border-top: 1px solid #333; }
        .settings-hidden { display: none !important; }
        .section-title { color: #888; text-transform: uppercase; font-size: 0.75em; display: block; margin: 0 0 8px 0; font-weight: bold; letter-spacing: 1px; }
        .control-row { margin-bottom: 15px; }
        .sports-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px; margin-bottom: 15px; }
        .sport-btn { padding: 10px; border-radius: 6px; background: #252836; color: #888; cursor: pointer; text-align: center; transition: 0.2s; font-weight: bold; font-size: 0.85em; }
        .sport-btn.active { background: var(--success); color: white; box-shadow: 0 0 8px rgba(76,175,80,0.3); }
        .mode-switch { display: flex; background: #252836; padding: 4px; border-radius: 8px; }
        .mode-opt { flex: 1; text-align: center; padding: 8px; cursor: pointer; border-radius: 6px; color: #888; font-size: 0.85em; }
        .mode-opt.active { background: #3d4150; color: white; font-weight: bold; }
        button.action-btn { padding: 12px; border-radius: 6px; border: none; font-weight: bold; cursor: pointer; width: 100%; margin-bottom: 10px; font-size: 0.9em; }
        .btn-teams { background: #3d4150; color: white; }
        .btn-save { background: #3d4150; color: #ccc; font-size: 1em; margin-bottom: 0; transition: background 0.3s, color 0.3s; }
        .btn-save:hover { background: #4a4e60; color: white; }
        table.game-table { width: 100%; border-collapse: separate; border-spacing: 0 6px; }
        th { text-align: center; color: #666; font-size: 0.7em; text-transform: uppercase; padding: 0 8px 4px 8px; font-weight: 600; }
        th:first-child { text-align: left; } 
        tr.game-row td { background: #252836; padding: 10px 8px; border-top: 1px solid #333; border-bottom: 1px solid #333; font-size: 0.9em; vertical-align: middle; }
        tr.game-row td:first-child { border-left: 4px solid var(--success); border-top-left-radius: 6px; border-bottom-left-radius: 6px; }
        tr.game-row td:last-child { border-top-right-radius: 6px; border-bottom-right-radius: 6px; border-right: 1px solid #333; }
        tr.game-row.filtered-out td:first-child { border-left-color: var(--inactive); }
        tr.game-row.filtered-out { opacity: 0.6; }
        .col-league { width: 50px; font-weight: bold; color: #aaa; font-size: 0.75em; text-align: center; }
        .col-matchup { color: white; font-weight: 500; display: flex; align-items: center; gap: 6px; white-space: nowrap; text-align: left; }
        .col-score { width: 60px; font-weight: bold; color: white; text-align: center; font-size: 1.1em; }
        .col-status { width: 90px; color: #888; font-size: 0.75em; text-align: right; line-height: 1.2; }
        .col-situation { width: 120px; text-align: right; font-weight: bold; font-size: 0.8em; }
        .league-label { display: block; } 
        .mini-logo { width: 24px; height: 24px; object-fit: contain; vertical-align: middle; }
        .at-symbol { color: #555; font-size: 0.8em; margin: 0 2px; }
        .sit-football { color: var(--success); }
        .sit-hockey { color: var(--warn); }
        .sit-baseball { color: #aaa; }
        @media (max-width: 600px) {
            body { padding: 5px; } .panel { padding: 12px; margin-bottom: 10px; }
            th.th-league { display: none; } td.col-league { display: none; }
            tr.game-row td:nth-child(2) { border-left-width: 4px; border-left-style: solid; border-top-left-radius: 6px; border-bottom-left-radius: 6px; padding-left: 8px; }
            tr.game-row.filtered-out td:nth-child(2) { border-left-color: var(--inactive) !important; }
            tr.game-row:not(.filtered-out) td:nth-child(2) { border-left-color: var(--success); }
            tr.game-row td { padding: 8px 5px; } 
            .col-matchup { font-size: 0.9em; gap: 4px; } .col-score { width: 45px; font-size: 1em; }
            .col-status { width: 70px; font-size: 0.7em; } .col-situation { width: 80px; font-size: 0.7em; }
        }
        .modal { display: none; position: fixed; top: 0; left: 0; width: 100%; height: 100%; background: rgba(0,0,0,0.85); z-index: 999; backdrop-filter: blur(3px); }
        .modal-content { background: var(--card); margin: 2% auto; padding: 20px; width: 95%; max-width: 800px; height: 90vh; border-radius: 12px; display: flex; flex-direction: column; }
        .tabs { display: flex; gap: 8px; overflow-x: auto; padding-bottom: 10px; border-bottom: 1px solid #333; margin-bottom: 15px; -webkit-overflow-scrolling: touch; }
        .tab { padding: 8px 14px; background: #2a2d3d; cursor: pointer; border-radius: 6px; white-space: nowrap; color: #aaa; font-size: 0.9em; }
        .tab.active { background: var(--accent); color: white; }
        .team-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(80px, 1fr)); gap: 8px; overflow-y: auto; flex-grow: 1; }
        .team-card { background: #151720; padding: 8px; border-radius: 8px; display: flex; flex-direction: column; align-items: center; gap: 5px; cursor: pointer; border: 2px solid transparent; }
        .team-card.selected { border-color: var(--accent); background: #2d1b15; }
        .team-card img { width: 35px; height: 35px; object-fit: contain; }
    </style>
</head>
<body>
    <div class="panel">
        <div class="header-row"> <h1 class="app-title">Ticker Control</h1> <button class="hamburger-btn" onclick="toggleSettings()">☰</button> </div>
        <div class="control-row"> <span class="section-title">Display Filter</span> <div class="mode-switch"> <div id="mode_all" class="mode-opt" onclick="setMode('all')">Show All</div> <div id="mode_live" class="mode-opt" onclick="setMode('live')">Live Only</div> <div id="mode_my" class="mode-opt" onclick="setMode('my_teams')">My Teams</div> </div> </div>
        <div class="control-row"> <span class="section-title">Scroll Style</span> <div class="mode-switch"> <div id="scroll_paged" class="mode-opt" onclick="setScroll(false)">Paged (Slide)</div> <div id="scroll_seamless" class="mode-opt" onclick="setScroll(true)">Seamless (Marquee)</div> </div> </div>
        <button class="action-btn btn-save" onclick="saveConfig()">SAVE SETTINGS</button>
        <div id="settingsArea" class="settings-hidden"> <span class="section-title">Enabled Sports</span> <div class="sports-grid"> <div id="btn_nfl" class="sport-btn" onclick="toggleSport('nfl')">NFL</div> <div id="btn_ncf_fbs" class="sport-btn" onclick="toggleSport('ncf_fbs')">FBS</div> <div id="btn_ncf_fcs" class="sport-btn" onclick="toggleSport('ncf_fcs')">FCS</div> <div id="btn_mlb" class="sport-btn" onclick="toggleSport('mlb')">MLB</div> <div id="btn_nhl" class="sport-btn" onclick="toggleSport('nhl')">NHL</div> <div id="btn_nba" class="sport-btn" onclick="toggleSport('nba')">NBA</div> </div> <button class="action-btn btn-teams" onclick="openTeamModal()">Manage My Teams (<span id="team_count">0</span>)</button> <div style="text-align:center; margin-top:15px;"> <a href="#" onclick="toggleDebug()" style="color:#555; font-size:0.75em; text-decoration:none;">Debug / Time Machine</a> </div> <div id="debugControls" style="display:none; margin-top:10px; padding-top:10px; border-top:1px solid #333;"> <div style="display:flex; gap:10px;"> <input type="date" id="custom_date" style="padding:8px; flex:1; background:#111; color:#fff; border:1px solid #555; border-radius:4px;"> <button style="width:auto; background:#fff; color:#000; margin:0; padding:0 15px;" onclick="setDate()">Go</button> </div> <button style="background:#333; color:#aaa; margin-top:8px; width:100%; padding:8px; border:none; cursor:pointer;" onclick="resetDate()">Reset to Live</button> </div> </div>
    </div>
    <div class="panel" style="padding-top:5px;"> <div style="display:flex; justify-content:space-between; align-items:center; border-bottom:1px solid #333; padding-bottom:10px; margin-bottom:5px;"> <span class="section-title" style="margin:0;">Active Feed (<span id="game_count">0</span>)</span> <div style="font-size:0.7em; color:#666;">Updates every 15s</div> </div> <table class="game-table"> <thead> <tr> <th class="th-league">LGE</th> <th>Matchup</th> <th style="text-align:center;">Score</th> <th style="text-align:right;">Status</th> <th style="text-align:right;">Sit.</th> </tr> </thead> <tbody id="gameTableBody"></tbody> </table> </div>
    <div id="teamModal" class="modal"> <div class="modal-content"> <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:10px;"> <h3 style="margin:0; color:white;">Select Teams</h3> <button onclick="closeTeamModal()" style="background:#444; color:white; border:none; padding:5px 15px; border-radius:4px; cursor:pointer;">Done</button> </div> <div class="tabs"> <div id="tab_nfl" class="tab active" onclick="showTab('nfl')">NFL</div> <div id="tab_ncf_fbs" class="tab" onclick="showTab('ncf_fbs')">FBS</div> <div id="tab_ncf_fcs" class="tab" onclick="showTab('ncf_fcs')">FCS</div> <div id="tab_mlb" class="tab" onclick="showTab('mlb')">MLB</div> <div id="tab_nhl" class="tab" onclick="showTab('nhl')">NHL</div> <div id="tab_nba" class="tab" onclick="showTab('nba')">NBA</div> </div> <div id="teamGrid" class="team-grid"><div style="text-align:center; padding:20px; color:#666; grid-column: 1/-1;">Loading...</div></div> </div> </div>
    <script>
        let currentState = { active_sports: {}, mode: 'all', my_teams: [], scroll_seamless: false }; let allTeams = {}; let currentTabLeague = 'nfl'; let settingsVisible = false;
        async function init() { let r = await fetch('/api/state'); let data = await r.json(); currentState = data.settings; fetch('/api/teams').then(r => r.json()).then(d => { allTeams = d; }); renderUI(); renderGames(data.games); setInterval(fetchLiveTicker, 5000); if (window.innerWidth >= 600) { settingsVisible = true; document.getElementById('settingsArea').classList.remove('settings-hidden'); } }
        function toggleSettings() { const area = document.getElementById('settingsArea'); if (settingsVisible) area.classList.add('settings-hidden'); else area.classList.remove('settings-hidden'); settingsVisible = !settingsVisible; }
        async function fetchLiveTicker() { try { let r = await fetch('/api/all_games'); let data = await r.json(); renderGames(data.games); } catch(e) {} }
        function renderUI() { ['nfl','ncf_fbs','ncf_fcs','mlb','nhl','nba'].forEach(sport => { let btn = document.getElementById('btn_' + sport); if(btn) btn.className = currentState.active_sports[sport] ? 'sport-btn active' : 'sport-btn'; }); document.querySelectorAll('.mode-opt').forEach(m => m.classList.remove('active')); if(currentState.mode === 'all') document.getElementById('mode_all').classList.add('active'); else if(currentState.mode === 'live') document.getElementById('mode_live').classList.add('active'); else if(currentState.mode === 'my_teams') document.getElementById('mode_my').classList.add('active'); if(currentState.scroll_seamless) document.getElementById('scroll_seamless').classList.add('active'); else document.getElementById('scroll_paged').classList.add('active'); document.getElementById('team_count').innerText = currentState.my_teams.length; if(currentState.debug_mode) { document.getElementById('debugControls').style.display = 'block'; if(currentState.custom_date) document.getElementById('custom_date').value = currentState.custom_date; } else { document.getElementById('debugControls').style.display = 'none'; } }
        function formatLeague(key) { if(key === 'ncf_fbs') return 'FBS'; if(key === 'ncf_fcs') return 'FCS'; return key.toUpperCase(); }
        function renderGames(games) { const tbody = document.getElementById('gameTableBody'); document.getElementById('game_count').innerText = games.length; tbody.innerHTML = ''; if(games.length === 0) { tbody.innerHTML = '<tr><td colspan="5" style="text-align:center; padding:20px; color:#555;">No active games found.</td></tr>'; return; }
            games.forEach(g => { let tr = document.createElement('tr'); tr.className = g.is_shown ? 'game-row' : 'game-row filtered-out'; let leagueLabel = formatLeague(g.sport); 
                let awayLogo = g.away_logo ? `<img src="${g.away_logo}" class="mini-logo">` : ''; 
                let homeLogo = g.home_logo ? `<img src="${g.home_logo}" class="mini-logo">` : ''; 
                let sitHTML = '';
                if(g.state === 'in' || g.state === 'half') { if(g.sport === 'nfl' || g.sport.includes('ncf')) { if(g.status === 'HALFTIME') { sitHTML = ''; } else if(g.situation.downDist) { sitHTML = `<span class="sit-football">${g.situation.downDist}</span>`; } else if(g.situation.isRedZone) { sitHTML = `<span class="sit-football">RedZone</span>`; } } else if(g.sport === 'nhl' && g.situation.powerPlay) { let poss = g.situation.possession ? ` (${g.situation.possession})` : ''; sitHTML = `<span class="sit-hockey">PP${poss}</span>`; } else if(g.sport === 'mlb' && g.situation.outs !== undefined) { sitHTML = `<span class="sit-baseball">${g.situation.balls}-${g.situation.strikes}, ${g.situation.outs} Out</span>`; } }
                tr.innerHTML = `<td class="col-league"><span class="league-label">${leagueLabel}</span></td> <td><div class="col-matchup"> ${awayLogo} ${g.away_abbr} <span class="at-symbol">@</span> ${homeLogo} ${g.home_abbr} </div></td> <td class="col-score">${g.away_score}-${g.home_score}</td> <td class="col-status">${g.status}</td> <td class="col-situation">${sitHTML}</td>`; tbody.appendChild(tr); }); }
        function toggleSport(s) { currentState.active_sports[s] = !currentState.active_sports[s]; renderUI(); } function setMode(m) { currentState.mode = m; renderUI(); } function setScroll(isSeamless) { currentState.scroll_seamless = isSeamless; renderUI(); }
        async function saveConfig() { await fetch('/api/config', { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(currentState)}); let btn = document.querySelector('.btn-save'); let oldText = btn.innerText; btn.innerText = "SAVED!"; btn.style.background = "#1c1f2e"; btn.style.color = "white"; setTimeout(() => { btn.innerText = oldText; btn.style.background = ""; btn.style.color = ""; }, 1500); }
        function openTeamModal() { document.getElementById('teamModal').style.display = 'block'; showTab(currentTabLeague); } function closeTeamModal() { document.getElementById('teamModal').style.display = 'none'; renderUI(); }
        function showTab(league) { currentTabLeague = league; document.querySelectorAll('.tab').forEach(t => t.classList.remove('active')); let activeTab = document.getElementById('tab_' + league); if(activeTab) activeTab.classList.add('active'); const grid = document.getElementById('teamGrid'); grid.innerHTML = ''; if (!allTeams[league] || allTeams[league].length === 0) { grid.innerHTML = '<div style="grid-column:1/-1; text-align:center; padding:20px; color:#666;">No teams found.</div>'; return; } allTeams[league].forEach(team => { let isSelected = currentState.my_teams.includes(team.abbr); let card = document.createElement('div'); card.className = `team-card ${isSelected ? 'selected' : ''}`; card.onclick = () => toggleTeamSelection(team.abbr, card); let logoImg = team.logo ? `<img src="${team.logo}">` : '<div style="width:35px;height:35px;"></div>'; card.innerHTML = `${logoImg} <span>${team.abbr}</span>`; grid.appendChild(card); }); }
        function toggleTeamSelection(abbr, cardElement) { if(currentState.my_teams.includes(abbr)) { currentState.my_teams = currentState.my_teams.filter(t => t !== abbr); cardElement.classList.remove('selected'); } else { currentState.my_teams.push(abbr); cardElement.classList.add('selected'); } document.getElementById('team_count').innerText = currentState.my_teams.length; }
        async function toggleDebug() { currentState.debug_mode = !currentState.debug_mode; await fetch('/api/debug', { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({debug_mode: currentState.debug_mode})}); init(); }
        async function setDate() { let d = document.getElementById('custom_date').value; await fetch('/api/debug', { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({custom_date: d})}); setTimeout(init, 500); }
        async function resetDate() { await fetch('/api/debug', { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({custom_date: null})}); setTimeout(init, 500); }
        window.onload = init;
    </script>
</body>
</html>
"""

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
