import time
import threading
import json
import os
import datetime
from datetime import datetime as dt, timezone, timedelta
import requests
from flask import Flask, jsonify, request
import struct 
import io     
from PIL import Image 

# IMPORT TEAMS
try:
    from valid_teams import FBS_TEAMS, FCS_TEAMS
except ImportError:
    FBS_TEAMS = []
    FCS_TEAMS = []

# ================= CONFIGURATION =================
TIMEZONE_OFFSET = -5  # Set to -5 for EST/EDT
CONFIG_FILE = "ticker_config.json"
UPDATE_INTERVAL = 10 

# ================= LOGO OVERRIDES (Hardcoded) =================
# These URLs are used by the /api/logo endpoint to fix missing/bad logos
LOGO_OVERRIDES = {
    # NHL Fixes
    "NJD": "https://a.espncdn.com/i/teamlogos/nhl/500/nj.png",
    "LAK": "https://a.espncdn.com/i/teamlogos/nhl/500/lak.png",
    "LA":  "https://a.espncdn.com/i/teamlogos/nhl/500/lak.png",
    "UTA": "https://assets.nhle.com/logos/nhl/svg/UTA_light.svg",
    "UTAH": "https://assets.nhle.com/logos/nhl/svg/UTA_light.svg",
    "STL": "https://a.espncdn.com/i/teamlogos/nhl/500/stl.png",
    "WSH": "https://a.espncdn.com/guid/cbe677ee-361e-91b4-5cae-6c4c30044743/logos/secondary_logo_on_black_color.png",
    "WAS": "https://a.espncdn.com/guid/cbe677ee-361e-91b4-5cae-6c4c30044743/logos/secondary_logo_on_black_color.png",
    
    # College/FBS Fixes
    "UL":  "https://a.espncdn.com/i/teamlogos/ncaa/500/309.png", # Louisiana
    "ULL": "https://a.espncdn.com/i/teamlogos/ncaa/500/309.png",
    "LOU": "https://a.espncdn.com/i/teamlogos/ncaa/500/97.png",
}

# ================= WEB UI =================
DASHBOARD_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Ticker Controller</title>
    <style>
        :root { --bg: #0f111a; --card: #1c1f2e; --accent: #ff5722; --text: #e0e0e0; --success: #4caf50; }
        body { background: var(--bg); color: var(--text); font-family: sans-serif; margin: 0; padding: 10px; }
        .panel { background: var(--card); padding: 15px; border-radius: 12px; max-width: 800px; margin: 0 auto 15px auto; }
        .btn-save { background: #3d4150; color: #ccc; width: 100%; padding: 12px; border: none; border-radius: 6px; font-weight: bold; cursor: pointer; }
        table { width: 100%; border-collapse: separate; border-spacing: 0 6px; }
        td { background: #252836; padding: 10px; }
        td:first-child { border-left: 4px solid var(--success); border-radius: 6px 0 0 6px; }
        td:last-child { border-radius: 0 6px 6px 0; }
        .mode-switch { display: flex; gap: 5px; margin-bottom: 15px; }
        .mode-opt { flex: 1; padding: 10px; background: #252836; text-align: center; border-radius: 6px; cursor: pointer; }
        .mode-opt.active { background: var(--accent); color: white; }
    </style>
</head>
<body>
    <div class="panel">
        <h2>Ticker Control</h2>
        <div class="mode-switch">
            <div id="mode_all" class="mode-opt" onclick="setMode('all')">All Games</div>
            <div id="mode_live" class="mode-opt" onclick="setMode('live')">Live Only</div>
        </div>
        <div class="mode-switch">
             <div id="scroll_paged" class="mode-opt" onclick="setScroll(false)">Paged (Sweep)</div>
             <div id="scroll_seamless" class="mode-opt" onclick="setScroll(true)">Seamless (Scroll)</div>
        </div>
        <button class="btn-save" onclick="saveConfig()">SAVE SETTINGS</button>
    </div>
    <div class="panel">
        <h3>Active Games (<span id="count">0</span>)</h3>
        <table id="gameTable"></table>
    </div>
    <script>
        let state = {};
        async function init() {
            let r = await fetch('/api/state');
            let data = await r.json();
            state = data.settings;
            render();
            setInterval(async () => {
                let r2 = await fetch('/api/all_games');
                let d2 = await r2.json();
                renderGames(d2.games);
            }, 5000);
        }
        function render() {
            document.querySelectorAll('.mode-opt').forEach(e => e.classList.remove('active'));
            if(state.mode === 'all') document.getElementById('mode_all').classList.add('active');
            else document.getElementById('mode_live').classList.add('active');
            if(state.scroll_seamless) document.getElementById('scroll_seamless').classList.add('active');
            else document.getElementById('scroll_paged').classList.add('active');
            renderGames(state.current_games || []);
        }
        function renderGames(games) {
            document.getElementById('count').innerText = games.length;
            let h = '';
            games.forEach(g => {
                h += `<tr>
                    <td><b>${g.sport.toUpperCase()}</b></td>
                    <td>${g.away_abbr} @ ${g.home_abbr}</td>
                    <td>${g.away_score}-${g.home_score}</td>
                    <td>${g.status}</td>
                </tr>`;
            });
            document.getElementById('gameTable').innerHTML = h;
        }
        function setMode(m) { state.mode = m; render(); }
        function setScroll(s) { state.scroll_seamless = s; render(); }
        async function saveConfig() {
            await fetch('/api/config', { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(state)});
            alert('Saved');
        }
        window.onload = init;
    </script>
</body>
</html>
"""

# ================= STATE =================
default_state = {
    'active_sports': { 'nfl': True, 'ncf_fbs': True, 'ncf_fcs': True, 'mlb': True, 'nhl': True, 'nba': True },
    'mode': 'all', 
    'scroll_seamless': False,
    'my_teams': [], 
    'current_games': [],
    'all_teams_data': {}, 
    'debug_mode': False,
    'custom_date': None
}
state = default_state.copy()

if os.path.exists(CONFIG_FILE):
    try:
        with open(CONFIG_FILE, 'r') as f:
            loaded = json.load(f)
            state.update(loaded)
    except: pass

class SportsFetcher:
    def __init__(self):
        self.base_url = 'http://site.api.espn.com/apis/site/v2/sports/'
        # Original simple config that worked reliably
        self.leagues = {
            'nfl': { 'path': 'football/nfl', 'params': {} },
            'ncf_fbs': { 'path': 'football/college-football', 'params': {'groups': '80', 'limit': 100} },
            'nhl': { 'path': 'hockey/nhl', 'params': {} },
            'mlb': { 'path': 'baseball/mlb', 'params': {} },
            'nba': { 'path': 'basketball/nba', 'params': {} }
        }

    def fetch_teams(self):
        try:
            teams_catalog = {k: [] for k in self.leagues.keys()}
            # Simple fetch for college teams only as they are static
            url = f"{self.base_url}football/college-football/teams"
            r = requests.get(url, params={'limit': 1000}, timeout=10)
            data = r.json()
            if 'sports' in data:
                for sport in data['sports']:
                    for league in sport['leagues']:
                        for item in league.get('teams', []):
                            try:
                                t_abbr = item['team'].get('abbreviation', 'unk')
                                t_logo = item['team'].get('logos', [{}])[0].get('href', '')
                                team_obj = {'abbr': t_abbr, 'logo': t_logo}
                                if t_abbr in FBS_TEAMS: teams_catalog['ncf_fbs'].append(team_obj)
                            except: continue
            state['all_teams_data'] = teams_catalog
        except: pass

    def get_games(self):
        games = []
        
        # Calculate Date for Filtering
        local_now = dt.now(timezone.utc) + timedelta(hours=TIMEZONE_OFFSET)
        target_date_str = local_now.strftime("%Y-%m-%d")
        
        # DEBUG OVERRIDE
        if state['debug_mode'] and state['custom_date']:
            target_date_str = state['custom_date']

        for league, cfg in self.leagues.items():
            if not state['active_sports'].get(league, True): continue
            
            try:
                # Add date param if debugging history
                params = cfg['params'].copy()
                if state['debug_mode']: params['dates'] = target_date_str.replace('-','')

                url = f"{self.base_url}{cfg['path']}/scoreboard"
                r = requests.get(url, params=params, timeout=3)
                data = r.json()
                
                for event in data.get('events', []):
                    # DATE FILTERING LOGIC
                    # Parse UTC date from event
                    if 'date' not in event: continue
                    utc_str = event['date'].replace('Z', '')
                    game_utc = dt.fromisoformat(utc_str).replace(tzinfo=timezone.utc)
                    local_game_time = game_utc + timedelta(hours=TIMEZONE_OFFSET)
                    game_date_str = local_game_time.strftime("%Y-%m-%d")

                    status = event.get('status', {})
                    state_code = status.get('type', {}).get('state', 'pre')

                    # Keep if: Active OR Matches Today's Date
                    if state_code != 'in' and game_date_str != target_date_str: continue

                    # Filter: If Mode=Live, skip non-live
                    is_shown = True
                    if state['mode'] == 'live' and state_code != 'in': is_shown = False
                    
                    comp = event['competitions'][0]
                    home = comp['competitors'][0]
                    away = comp['competitors'][1]
                    
                    # Fix Abbrs
                    h_abbr = home['team']['abbreviation'].upper()
                    a_abbr = away['team']['abbreviation'].upper()
                    
                    sit = comp.get('situation', {})
                    
                    # Construct Game Object
                    g = {
                        'sport': league,
                        'id': event['id'],
                        'status': status.get('type', {}).get('shortDetail', ''),
                        'state': state_code,
                        'is_shown': is_shown,
                        'home_abbr': h_abbr,
                        'home_score': home.get('score', '0'),
                        'home_logo': home['team'].get('logo', ''),
                        'home_id': home['team'].get('id', ''),
                        'away_abbr': a_abbr,
                        'away_score': away.get('score', '0'),
                        'away_logo': away['team'].get('logo', ''),
                        'away_id': away['team'].get('id', ''),
                        'situation': {}
                    }
                    
                    # Situation Data
                    if state_code == 'in':
                        if league == 'nfl' or 'football' in cfg['path']:
                            g['situation'] = {
                                'possession': sit.get('possession', ''),
                                'downDist': sit.get('downDistanceText', ''),
                                'isRedZone': sit.get('isRedZone', False)
                            }
                        elif league == 'nhl':
                            # Basic Power Play logic
                             # (Use try/catch as API formats vary)
                             try:
                                 # 1551 code logic
                                 # This is a simplification; for full PP data we need the other endpoint
                                 # But for "getting games back", we stick to basic scoreboard data
                                 pass 
                             except: pass

                        elif league == 'mlb':
                             g['situation'] = {
                                 'balls': sit.get('balls', 0),
                                 'strikes': sit.get('strikes', 0),
                                 'outs': sit.get('outs', 0),
                                 'onFirst': sit.get('onFirst', False),
                                 'onSecond': sit.get('onSecond', False),
                                 'onThird': sit.get('onThird', False)
                             }
                    
                    games.append(g)
            except Exception as e: 
                print(f"Error fetching {league}: {e}")
            
        state['current_games'] = games

fetcher = SportsFetcher()

def bg_loop():
    fetcher.fetch_teams()
    while True:
        fetcher.get_games()
        time.sleep(UPDATE_INTERVAL)

app = Flask(__name__)

@app.route('/')
def index(): return DASHBOARD_HTML

@app.route('/api/ticker')
def ticker():
    visible = [g for g in state['current_games'] if g.get('is_shown', True)]
    return jsonify({
        'meta': {'scroll_seamless': state.get('scroll_seamless', False)},
        'games': visible
    })

@app.route('/api/all_games')
def all_games(): return jsonify({'games': state['current_games']})

@app.route('/api/state')
def get_state(): return jsonify({'settings': state})

@app.route('/api/config', methods=['POST'])
def config():
    state.update(request.json)
    with open(CONFIG_FILE, 'w') as f: json.dump(state, f)
    return jsonify('ok')

@app.route('/api/debug', methods=['POST'])
def debug():
    state.update(request.json)
    fetcher.get_games()
    return jsonify('ok')

# === IMAGE PROCESSING (With Padding & Override Fixes) ===
@app.route('/api/logo/<league>/<abbr>')
def logo(league, abbr):
    abbr = abbr.upper()
    url = None
    
    # 1. Check Hardcoded Overrides First
    if abbr in LOGO_OVERRIDES: 
        url = LOGO_OVERRIDES[abbr]
    
    # 2. If not overridden, find in current games list
    if not url:
        for g in state['current_games']:
            if g['home_abbr'] == abbr: url = g['home_logo']
            if g['away_abbr'] == abbr: url = g['away_logo']
            if url: break

    # 3. Fallback to loaded teams data
    if not url:
        # Check standard lists
        target_leagues = []
        if 'ncf' in league: target_leagues = ['ncf_fbs']
        elif league in state['all_teams_data']: target_leagues = [league]
        
        for l_key in target_leagues:
            if l_key in state['all_teams_data']:
                for t in state['all_teams_data'][l_key]:
                    if t['abbr'] == abbr:
                        url = t['logo']
                        break
    
    if not url: return "Not Found", 404

    try:
        r = requests.get(url, timeout=2)
        img = Image.open(io.BytesIO(r.content)).convert("RGBA")
        
        # 1. Auto-Crop
        bbox = img.getbbox()
        if bbox: img = img.crop(bbox)
        
        # 2. Resize with PADDING (Max 20x20 inside 24x24)
        img.thumbnail((20, 20), Image.Resampling.LANCZOS)
        
        # 3. Center
        bg = Image.new("RGBA", (24, 24), (0,0,0,255))
        off_x = (24 - img.width) // 2
        off_y = (24 - img.height) // 2
        bg.paste(img, (off_x, off_y), img)
        
        # 4. RGB565
        final = bg.convert("RGB")
        out = bytearray()
        for r,g,b in final.getdata():
            v = ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)
            out.extend(struct.pack('<H', v))
            
        return bytes(out), 200, {'Content-Type': 'application/octet-stream'}
        
    except Exception as e:
        print(e)
        return "Error", 500

if __name__ == '__main__':
    t = threading.Thread(target=bg_loop)
    t.daemon = True
    t.start()
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 5000)))
