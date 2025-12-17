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

# ================= VALID TEAMS CONFIGURATION (EMBEDDED) =================
# This ensures it works even if valid_teams.py is missing
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
UPDATE_INTERVAL = 30 

# --- NHL LOGO FIXES ---
NHL_LOGO_MAP = {
    "SJS": "sj", "NJD": "nj", "TBL": "tb", "LAK": "la", "VGK": "vgs", "VEG": "vgs", "UTA": "utah"
}

# ================= IMAGE PROCESSING ENGINE =================
logo_cache = {} 

def fetch_and_convert_logo(abbr, sport):
    if sport == 'nhl':
        code = NHL_LOGO_MAP.get(abbr, abbr.lower())
        url = f"https://a.espncdn.com/i/teamlogos/nhl/500/{code}.png"
        if abbr == 'WSH': url = "https://a.espncdn.com/guid/cbe677ee-361e-91b4-5cae-6c4c30044743/logos/secondary_logo_on_black_color.png"
    elif 'ncf' in sport:
        url = f"https://a.espncdn.com/i/teamlogos/ncaa/500/{abbr}.png"
    else:
        url = f"https://a.espncdn.com/i/teamlogos/{sport}/500/{abbr}.png"

    try:
        r = requests.get(url, timeout=2)
        if r.status_code != 200: return None
        
        img = Image.open(io.BytesIO(r.content)).convert("RGBA")
        img = img.resize((24, 24), Image.Resampling.LANCZOS)
        bg = Image.new("RGBA", (24, 24), (0, 0, 0))
        img = Image.alpha_composite(bg, img).convert("RGB")
        
        output = io.BytesIO()
        for y in range(24):
            for x in range(24):
                r, g, b = img.getpixel((x, y))
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
        self.all_teams_data = {} 

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
    """Main fetching loop."""
    while True:
        try:
            # 1. Determine Date
            if state.settings.get('debug_mode') and state.settings.get('custom_date'):
                date_str = state.settings['custom_date'].replace('-', '')
            else:
                now = dt.now(timezone(timedelta(hours=TIMEZONE_OFFSET)))
                if now.hour < 4: date_str = (now - timedelta(days=1)).strftime("%Y%m%d")
                else: date_str = now.strftime("%Y%m%d")

            # 2. Fetch Sports
            all_games = []
            sports_map = {
                'nfl': 'football/nfl',
                'ncf_fbs': 'football/college-football', 
                'ncf_fcs': 'football/college-football',
                'mlb': 'baseball/mlb',
                'nhl': 'hockey/nhl',
                'nba': 'basketball/nba'
            }

            for sport_key, path in sports_map.items():
                if not state.settings['active_sports'].get(sport_key, True): continue

                url = f"http://site.api.espn.com/apis/site/v2/sports/{path}/scoreboard?dates={date_str}"
                
                # IMPORTANT: Fetch ALL college games then filter, don't rely on ESPN groups alone
                if sport_key == 'ncf_fbs': url += "&limit=100&groups=80"
                elif sport_key == 'ncf_fcs': url += "&limit=100&groups=81"
                
                try:
                    r = requests.get(url, timeout=5)
                    data = r.json()
                    
                    for event in data.get('events', []):
                        status = event['status']['type']
                        state_raw = status['state'] # 'pre', 'in', 'post'
                        
                        comp = event['competitions'][0]
                        home = comp['competitors'][0]
                        away = comp['competitors'][1]
                        
                        h_abbr = home['team']['abbreviation']
                        a_abbr = away['team']['abbreviation']

                        # --- COLLEGE SPLIT FIX ---
                        # If fetching FBS, ensure team is actually FBS. 
                        if sport_key == 'ncf_fbs':
                            # If neither team is in our FBS list, skip it (unless list is empty)
                            if FBS_TEAMS and (h_abbr not in FBS_TEAMS and a_abbr not in FBS_TEAMS):
                                continue 
                        elif sport_key == 'ncf_fcs':
                            if FCS_TEAMS and (h_abbr not in FCS_TEAMS and a_abbr not in FCS_TEAMS):
                                continue

                        # --- FILTER LOGIC ---
                        should_show = True
                        
                        # Live Mode Filter
                        if state.settings['mode'] == 'live':
                            if state_raw not in ['in', 'half']: should_show = False
                        
                        # My Teams Filter
                        elif state.settings['mode'] == 'my_teams' and state.settings['my_teams']:
                            if h_abbr not in state.settings['my_teams'] and a_abbr not in state.settings['my_teams']:
                                should_show = False

                        # --- DISPLAY LOGIC ---
                        status_txt = status.get('shortDetail', '')
                        
                        # Halftime
                        if state_raw == 'half': 
                            status_txt = "HALFTIME"
                        
                        # Live Clock
                        elif state_raw == 'in':
                            clock = event['status'].get('displayClock', '')
                            period = event['status'].get('period', 1)
                            if clock: 
                                prefix = f"P{period}" if 'hockey' in path else f"Q{period}"
                                status_txt = f"{prefix} - {clock}"
                        
                        # Scheduled/Final cleanup
                        elif " - " in status_txt: 
                            status_txt = status_txt.split(" - ")[-1]

                        # Situation
                        sit = comp.get('situation', {})
                        sit_data = {}
                        if state_raw == 'in':
                            # RedZone logic: Auto-clears if API says false
                            is_rz = sit.get('isRedZone', False) if 'football' in path else False
                            
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
                            'situation': sit_data,
                            'is_shown': should_show
                        })

                except Exception as e:
                    print(f"Error fetching {sport_key}: {e}")

            state.game_data = all_games
            print(f"Cycle Complete. Found {len(all_games)} games.")
            
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
        'ncf_fbs': 'football/college-football' 
    }
    
    while True:
        temp_data = {}
        for k, path in cats.items():
            try:
                r = requests.get(f"http://site.api.espn.com/apis/site/v2/sports/{path}/teams?limit=1000")
                data = r.json()
                team_list = []
                
                # Safety check for missing keys
                if 'sports' in data and len(data['sports']) > 0:
                    leagues = data['sports'][0].get('leagues', [])
                    if leagues:
                        teams = leagues[0].get('teams', [])
                        for t in teams:
                            team = t.get('team', {})
                            if team:
                                logos = team.get('logos', [{}])
                                logo_url = logos[0].get('href', '') if logos else ''
                                team_list.append({'abbr': team.get('abbreviation', 'UNK'), 'logo': logo_url})
                
                if k == 'ncf_fbs':
                    # Split College into FBS/FCS using the embedded lists
                    temp_data['ncf_fbs'] = [t for t in team_list if t['abbr'] in FBS_TEAMS] if FBS_TEAMS else team_list
                    temp_data['ncf_fcs'] = [t for t in team_list if t['abbr'] in FCS_TEAMS] if FCS_TEAMS else []
                else:
                    temp_data[k] = team_list
            except Exception as e: 
                print(f"Team List Error {k}: {e}")
        
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
    # Basic HTML Dashboard
    return DASHBOARD_HTML

@app.route('/api/ticker')
def api_ticker():
    # Only return games marked is_shown=True
    visible = [g for g in state.game_data if g.get('is_shown', True)]
    return jsonify({'games': visible, 'meta': {'scroll_seamless': state.settings['scroll_seamless']}})

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

DASHBOARD_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <title>Ticker Control</title>
    <style>
        :root { --bg: #0f111a; --card: #1c1f2e; --accent: #ff5722; --text: #e0e0e0; --blue: #0D47A1; }
        body { background: var(--bg); color: var(--text); font-family: sans-serif; padding: 10px; }
        .panel { background: var(--card); padding: 15px; border-radius: 12px; max-width: 800px; margin: 0 auto 15px; }
        .btn { width: 100%; padding: 12px; border: none; border-radius: 6px; font-weight: bold; cursor: pointer; margin-bottom: 10px; background: #333; color: white; }
        .btn.active { background: var(--accent); }
        .btn-save { background: var(--blue); }
        .row { display: flex; gap: 5px; margin-bottom: 10px; }
        .row .btn { margin: 0; }
        .game-row { border-bottom: 1px solid #333; padding: 8px 0; display: flex; justify-content: space-between; }
        .hidden { opacity: 0.4; }
    </style>
</head>
<body>
    <div class="panel">
        <h2>Ticker Control</h2>
        
        <h3>Mode</h3>
        <div class="row">
            <button id="mode_all" class="btn" onclick="setMode('all')">All</button>
            <button id="mode_live" class="btn" onclick="setMode('live')">Live</button>
            <button id="mode_my" class="btn" onclick="setMode('my_teams')">My Teams</button>
        </div>

        <h3>Scroll</h3>
        <div class="row">
            <button id="scroll_paged" class="btn" onclick="setScroll(false)">Paged</button>
            <button id="scroll_seamless" class="btn" onclick="setScroll(true)">Seamless</button>
        </div>

        <button class="btn btn-save" onclick="save()">SAVE SETTINGS</button>
        
        <h3>Active Games (<span id="count">0</span>)</h3>
        <div id="games" style="font-size: 0.9em;">Loading...</div>
    </div>

    <script>
        let state = {};
        async function init() {
            try {
                let r = await fetch('/api/state');
                let d = await r.json();
                state = d.settings;
                render();
                
                let visible = d.games.filter(g => g.is_shown);
                document.getElementById('count').innerText = visible.length;
                
                document.getElementById('games').innerHTML = d.games.map(g => {
                    let cls = g.is_shown ? 'game-row' : 'game-row hidden';
                    return `<div class="${cls}">
                        <span>${g.away_abbr} vs ${g.home_abbr}</span>
                        <span>${g.status}</span>
                    </div>`;
                }).join('');
            } catch(e) {}
        }
        function render() {
            ['all','live','my_teams'].forEach(m => document.getElementById('mode_'+m).className = state.mode==m ? 'btn active' : 'btn');
            document.getElementById('scroll_seamless').className = state.scroll_seamless ? 'btn active' : 'btn';
            document.getElementById('scroll_paged').className = !state.scroll_seamless ? 'btn active' : 'btn';
        }
        function setMode(m) { state.mode = m; render(); }
        function setScroll(s) { state.scroll_seamless = s; render(); }
        async function save() {
            await fetch('/api/config', { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(state)});
            alert('Saved');
        }
        init();
        setInterval(init, 5000);
    </script>
</body>
</html>
"""

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
