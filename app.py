import sys
import time
import threading
import io
import json
import os
import datetime
from datetime import datetime as dt, timedelta
from flask import Flask, jsonify, request
import requests
from PIL import Image, ImageDraw, ImageFont

# ================= CONFIGURATION =================
PANEL_W = 64   
PANEL_H = 32   
TRANSITION_SPEED = 0.05
HOLD_TIME = 5.0
TIMEZONE_OFFSET = -5 # EST
CONFIG_FILE = "ticker_config.json"

# ================= STATE =================
default_state = {
    'active_sports': { 'nfl': True, 'ncf_fbs': True, 'ncf_fcs': True, 'mlb': True, 'nhl': True, 'nba': True },
    'mode': 'all', 'my_teams': [], 'current_games': [],
    'all_teams_data': {}, 'debug_mode': False, 'custom_date': None, 'debug_games': [],
    'resolution': {'w': 64, 'h': 32} 
}
state = default_state.copy()

# ================= GRAPHICS ENGINE (FOR WEB PREVIEW) =================
class VirtualMatrix:
    def __init__(self):
        self.lock = threading.Lock()
        self.width = PANEL_W
        self.height = PANEL_H
        self.current_image = Image.new("RGB", (self.width, self.height), (0, 0, 0))

    def update_display(self, new_image):
        with self.lock:
            self.current_image = new_image.copy()

    def get_pixel_data(self):
        with self.lock:
            pixels = list(self.current_image.getdata())
            return {
                'w': self.width, 'h': self.height, 
                'data': [f"#{r:02x}{g:02x}{b:02x}" for r, g, b in pixels]
            }

matrix = VirtualMatrix()

# ================= DATA FETCHING =================
class SportsFetcher:
    def __init__(self):
        self.base_url = 'http://site.api.espn.com/apis/site/v2/sports/'
        self.leagues = {
            'nfl': { 'path': 'football/nfl', 'scoreboard_params': {} },
            'ncf_fbs': { 'path': 'football/college-football', 'scoreboard_params': {'groups': '80', 'limit': 100} },
            'ncf_fcs': { 'path': 'football/college-football', 'scoreboard_params': {'groups': '81,22,20', 'limit': 300} },
            'mlb': { 'path': 'baseball/mlb', 'scoreboard_params': {} },
            'nhl': { 'path': 'hockey/nhl', 'scoreboard_params': {} },
            'nba': { 'path': 'basketball/nba', 'scoreboard_params': {} }
        }

    def fetch_all_teams(self):
        # Only fetch if empty to save bandwidth
        if state['all_teams_data']: return
        try:
            teams_catalog = {k: [] for k in self.leagues.keys()}
            for league_key, config in self.leagues.items():
                url = f"{self.base_url}{config['path']}/teams"
                try:
                    r = requests.get(url, params={'limit': 100}, timeout=5)
                    data = r.json()
                    for sport in data.get('sports', []):
                        for league in sport.get('leagues', []):
                            for item in league.get('teams', []):
                                team = item.get('team', {})
                                teams_catalog[league_key].append({
                                    'abbr': team.get('abbreviation', 'unk'), 
                                    'logo': team.get('logos', [{}])[0].get('href', '')
                                })
                except: continue
            state['all_teams_data'] = teams_catalog
        except: pass

    def analyze_nhl_power_play(self, game_id, current_period, current_clock_str, home_id, away_id, home_abbr, away_abbr):
        try:
            url = f"https://site.api.espn.com/apis/site/v2/sports/hockey/nhl/playbyplay?event={game_id}"
            r = requests.get(url, timeout=2)
            pbp = r.json()
            
            def get_seconds_elapsed(period, clock_str):
                parts = clock_str.split(':')
                return ((period - 1) * 1200) + (1200 - (int(parts[0]) * 60 + int(parts[1])))

            try: current_total = get_seconds_elapsed(current_period, current_clock_str)
            except: return {'powerPlay': False}

            active_penalties = {home_id: 0, away_id: 0}

            if 'plays' in pbp:
                for play in pbp['plays']:
                    text = play.get('text', '').lower()
                    if 'penalty' in text and 'shot' not in text:
                        if 'misconduct' in text and 'game' not in text: continue
                        duration = 120
                        if 'double minor' in text or '4 minutes' in text: duration = 240
                        elif 'major' in text or '5 minutes' in text: duration = 300
                        try:
                            start = get_seconds_elapsed(play['period']['number'], play['clock']['displayValue'])
                            if (start + duration) > current_total:
                                tid = play.get('team', {}).get('id')
                                if not tid:
                                    if home_abbr.lower() in text: tid = home_id
                                    elif away_abbr.lower() in text: tid = away_id
                                if tid in active_penalties: active_penalties[tid] += 1
                        except: continue

            if active_penalties.get(home_id, 0) > active_penalties.get(away_id, 0):
                return {'powerPlay': True, 'possession': away_id}
            elif active_penalties.get(away_id, 0) > active_penalties.get(home_id, 0):
                return {'powerPlay': True, 'possession': home_id}
            return {'powerPlay': False}
        except: return {'powerPlay': False}

    def get_real_games(self):
        if state['debug_mode']:
            if state['custom_date'] == 'TEST_PP':
                return [{ "sport": "nhl", "id": "test_pp", "status": "P2 14:20", "state": "in", "home_abbr": "NYR", "home_id": "h", "home_score": "3", "home_logo": "", "away_abbr": "BOS", "away_id": "a", "away_score": "2", "away_logo": "", "situation": {"powerPlay": True, "possession": "a"} }]
            if state['custom_date'] == 'TEST_RZ':
                return [{ "sport": "nfl", "id": "test_rz", "status": "3rd 4:20", "state": "in", "home_abbr": "KC", "home_id": "h", "home_score": "21", "home_logo": "", "away_abbr": "BUF", "away_id": "a", "away_score": "17", "away_logo": "", "situation": {"isRedZone": True, "downDist": "2nd & 5", "possession": "a"} }]

        games = []
        local_now = dt.utcnow() + timedelta(hours=TIMEZONE_OFFSET)
        today_str = local_now.strftime("%Y-%m-%d")
        target_date = state['custom_date'] if (state['debug_mode'] and state['custom_date']) else today_str
        is_history = (state['debug_mode'] and state['custom_date'])

        for league_key, config in self.leagues.items():
            if not state['active_sports'].get(league_key, False): continue 
            try:
                params = config['scoreboard_params'].copy()
                if is_history: params['dates'] = target_date.replace('-', '')
                
                r = requests.get(f"{self.base_url}{config['path']}/scoreboard", params=params, timeout=3)
                data = r.json()
                
                for event in data.get('events', []):
                    status = event['status']['type']['state']
                    utc_str = event['date'].replace('Z', '')
                    game_local_dt = dt.fromisoformat(utc_str) + timedelta(hours=TIMEZONE_OFFSET)
                    game_local_date = game_local_dt.strftime("%Y-%m-%d")

                    if is_history:
                        if game_local_date != target_date: continue
                    else:
                        # Logic: Show Live ('in'), Today's Pre-game ('pre'), or Recent Finals
                        is_today = (game_local_date == today_str)
                        if not is_today and status != 'in': continue

                    comp = event['competitions'][0]
                    home = comp['competitors'][0]
                    away = comp['competitors'][1]
                    sit = comp.get('situation', {})
                    h_id, a_id = home.get('id', '0'), away.get('id', '0')
                    h_abbr, a_abbr = home['team']['abbreviation'], away['team']['abbreviation']

                    game_obj = {
                        'sport': league_key, 'id': event['id'], 
                        'status': event['status']['type']['shortDetail'].replace(" EST","").replace(" EDT","").replace("Final","FINAL"), 
                        'state': status,
                        'home_abbr': h_abbr, 'home_id': h_id, 'home_score': home.get('score', '0'), 'home_logo': home['team'].get('logo', ''),
                        'away_abbr': a_abbr, 'away_id': a_id, 'away_score': away.get('score', '0'), 'away_logo': away['team'].get('logo', ''),
                        'situation': {}
                    }

                    if status == 'in':
                        if 'football' in config['path']:
                            game_obj['situation'] = {
                                'possession': sit.get('possession', ''), 'downDist': sit.get('downDistanceText', ''), 'isRedZone': sit.get('isRedZone', False)
                            }
                        elif league_key == 'nhl':
                            game_obj['situation'] = self.analyze_nhl_power_play(game_obj['id'], event['status']['period'], event['status']['displayClock'], h_id, a_id, h_abbr, a_abbr)
                        elif league_key == 'mlb':
                            game_obj['situation'] = { 'balls': sit.get('balls',0), 'strikes': sit.get('strikes',0), 'outs': sit.get('outs',0), 'onFirst': sit.get('onFirst',False), 'onSecond': sit.get('onSecond',False), 'onThird': sit.get('onThird',False) }
                    
                    games.append(game_obj)
            except: continue
        return games

fetcher = SportsFetcher()

# ================= THREADS =================
def run_fetcher():
    fetcher.fetch_all_teams() # Fetch logos once on startup
    while True:
        try: state['current_games'] = fetcher.get_real_games()
        except: pass
        time.sleep(10)

def run_drawer():
    try: font = ImageFont.truetype("arialbd.ttf", 10)
    except: font = ImageFont.load_default()
    try: tiny = ImageFont.truetype("arial.ttf", 9)
    except: tiny = ImageFont.load_default()
    try: micro = ImageFont.truetype("arial.ttf", 8)
    except: micro = ImageFont.load_default()
    
    logo_cache = {}
    def get_logo(url):
        if not url: return None
        if url in logo_cache: return logo_cache[url]
        try:
            r = requests.get(url, timeout=1)
            img = Image.open(io.BytesIO(r.content)).convert("RGBA")
            bg = Image.new("RGBA", img.size, (0,0,0,255)); bg.alpha_composite(img)
            ret = bg.convert("RGB"); logo_cache[url] = ret; return ret
        except: return None

    while True:
        games = state['current_games']
        if not games:
            canvas = Image.new("RGB", (PANEL_W, PANEL_H), (0,0,0))
            d = ImageDraw.Draw(canvas)
            d.text((2, 10), "NO GAMES", fill=(80,80,80))
            matrix.update_display(canvas)
            time.sleep(2)
            continue

        for game in games:
            # Check Filter Mode
            if state['mode'] == 'live' and game['state'] != 'in': continue
            if state['mode'] == 'my_teams' and (game['home_abbr'] not in state['my_teams'] and game['away_abbr'] not in state['my_teams']): continue

            p = Image.new("RGB", (PANEL_W, PANEL_H), (0,0,0))
            d = ImageDraw.Draw(p)
            
            # Red Zone Border
            if ('football' in str(game['sport'])) and game['situation'].get('isRedZone'):
                d.rectangle((0, 0, 63, 31), outline=(139, 0, 0), width=2)

            l1 = get_logo(game['away_logo'])
            l2 = get_logo(game['home_logo'])
            
            is_wide = (game['state'] == 'in' and 'football' in str(game['sport'])) or len(str(game['away_score'])) > 1
            if is_wide:
                l_size = (16,16); ly = 5 if 'football' in str(game['sport']) else 2
                pos1 = (0, ly); pos2 = (48, ly); sy = 12
            else:
                l_size = (24,24); pos1 = (0,0); pos2 = (40,0); sy = 12

            if l1: p.paste(l1.resize(l_size), pos1)
            else: d.text(pos1, game['away_abbr'], font=micro, fill=(200,200,200))
            if l2: p.paste(l2.resize(l_size), pos2)
            else: d.text(pos2, game['home_abbr'], font=micro, fill=(200,200,200))

            sc = f"{game['away_score']}-{game['home_score']}"
            w = d.textlength(sc, font=font)
            d.text(((64-w)/2, sy), sc, font=font, fill=(255,255,255))

            w_st = d.textlength(game['status'], font=tiny)
            d.text(((64-w_st)/2, 22), game['status'], font=tiny, fill=(180,180,180))

            sit = game['situation']
            if game['state'] == 'in':
                if 'football' in str(game['sport']) and 'downDist' in sit:
                    dd = sit['downDist'].split(' at ')[0]
                    w_dd = d.textlength(dd, font=tiny)
                    d.text(((64-w_dd)/2, 0), dd, font=tiny, fill=(0,255,0))
                elif game['sport'] == 'nhl' and sit.get('powerPlay'):
                    w_pp = d.textlength("PP", font=tiny)
                    d.text(((64-w_pp)/2, 0), "PP", font=tiny, fill=(255,255,0))

            matrix.update_display(p)
            time.sleep(HOLD_TIME)

# ================= FLASK SERVER =================
app = Flask(__name__)

t1 = threading.Thread(target=run_fetcher); t1.daemon = True; t1.start()
t2 = threading.Thread(target=run_drawer); t2.daemon = True; t2.start()

@app.route('/')
def index():
    return """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Sports Ticker Dashboard</title>
        <style>
            :root { --bg: #0f111a; --card: #1c1f2e; --accent: #ff5722; --text: #e0e0e0; --success: #4caf50; --danger: #f44336; }
            body { background: var(--bg); color: var(--text); font-family: 'Segoe UI', sans-serif; margin: 0; padding: 20px; }
            .matrix-wrapper { text-align: center; margin-bottom: 20px; overflow-x: auto; display: flex; justify-content: center; }
            .matrix { display: inline-grid; grid-template-columns: repeat(64, 1fr); gap: 2px; background: #000; padding: 4px; border: 8px solid #222; border-radius: 4px; width: fit-content; box-sizing: content-box; box-shadow: 0 0 30px rgba(0,0,0,0.9); }
            .led { width: 10px; height: 10px; background: #151515; border-radius: 50%; transition: background-color 0.05s; }
            .panel { background: var(--card); padding: 20px; border-radius: 12px; margin-bottom: 20px; max-width: 800px; margin: 0 auto 20px auto; }
            .section-title { color: #888; text-transform: uppercase; font-size: 0.85em; margin-bottom: 10px; display: block; }
            .sports-grid { display: flex; gap: 10px; margin-bottom: 20px; flex-wrap: wrap; }
            .sport-btn { flex: 1; min-width: 80px; padding: 15px; border-radius: 8px; border: 1px solid #333; background: #252836; color: #888; font-weight: bold; cursor: pointer; text-align: center; transition: all 0.2s; }
            .sport-btn.active { background: var(--success); color: white; border-color: var(--success); box-shadow: 0 0 10px rgba(76, 175, 80, 0.4); }
            button { padding: 12px 20px; border-radius: 6px; border: none; font-weight: bold; cursor: pointer; font-size: 14px; }
            .btn-teams { background: #3d4150; color: white; width: 100%; margin-bottom: 15px; }
            .btn-save { background: var(--accent); color: white; width: 100%; font-size: 1.1em; }
            .btn-debug { background: #444; color: #aaa; font-size: 0.8em; margin-top: 10px; transition: all 0.3s; }
            .btn-debug.active { background: var(--accent); color: white; box-shadow: 0 0 8px var(--accent); }
            .mode-switch { display: flex; background: #252836; padding: 4px; border-radius: 8px; margin-bottom: 20px; }
            .mode-opt { flex: 1; text-align: center; padding: 10px; cursor: pointer; border-radius: 6px; color: #888; }
            .mode-opt.active { background: #3d4150; color: white; font-weight: bold; }
            table { width: 100%; border-collapse: separate; border-spacing: 0 5px; }
            td, th { padding: 12px; text-align: left; background: #252836; }
            th { background: transparent; color: #888; font-size: 0.8em; }
            tr td:first-child { border-top-left-radius: 6px; border-bottom-left-radius: 6px; border-left: 4px solid transparent; }
            tr td:last-child { border-top-right-radius: 6px; border-bottom-right-radius: 6px; }
            tr.status-active td:first-child { border-left-color: var(--success); }
            tr.status-inactive td { opacity: 0.5; }
            tr.status-inactive td:first-child { border-left-color: var(--danger); }
            .logo-mini { height: 24px; width: auto; vertical-align: middle; margin-right: 8px; object-fit: contain; }
            .modal { display: none; position: fixed; top: 0; left: 0; width: 100%; height: 100%; background: rgba(0,0,0,0.9); z-index: 999; }
            .modal-content { background: var(--card); margin: 5% auto; padding: 20px; width: 90%; max-width: 800px; height: 80vh; border-radius: 12px; display: flex; flex-direction: column; }
            .team-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(100px, 1fr)); gap: 10px; overflow-y: auto; flex-grow: 1; margin-top: 15px; }
            .team-card { background: #0f111a; padding: 10px; border-radius: 8px; display: flex; flex-direction: column; align-items: center; gap: 5px; cursor: pointer; border: 2px solid transparent; }
            .team-card.selected { border-color: var(--accent); background: #25100a; }
            .team-card img { width: 40px; height: 40px; object-fit: contain; }
            .tabs { display: flex; gap: 10px; overflow-x: auto; padding-bottom: 5px; }
            .tab { padding: 10px 20px; background: #2a2d3d; cursor: pointer; border-radius: 6px; white-space: nowrap; }
            .tab.active { background: var(--accent); }
            input[type="date"] { padding: 10px; background: #111; border: 1px solid #444; color: white; border-radius: 4px; }
        </style>
    </head>
    <body>
        <div class="matrix-wrapper"><div id="display" class="matrix"></div></div>
        <div class="panel">
            <span class="section-title">Enabled Sports</span>
            <div class="sports-grid">
                <div id="btn_nfl" class="sport-btn" onclick="toggleSport('nfl')">NFL</div>
                <div id="btn_ncf_fbs" class="sport-btn" onclick="toggleSport('ncf_fbs')">FBS</div>
                <div id="btn_ncf_fcs" class="sport-btn" onclick="toggleSport('ncf_fcs')">FCS</div>
                <div id="btn_mlb" class="sport-btn" onclick="toggleSport('mlb')">MLB</div>
                <div id="btn_nhl" class="sport-btn" onclick="toggleSport('nhl')">NHL</div>
                <div id="btn_nba" class="sport-btn" onclick="toggleSport('nba')">NBA</div>
            </div>
            <span class="section-title">Display Mode</span>
            <div class="mode-switch">
                <div id="mode_all" class="mode-opt" onclick="setMode('all')">Show All</div>
                <div id="mode_live" class="mode-opt" onclick="setMode('live')">Happening Now</div>
                <div id="mode_my" class="mode-opt" onclick="setMode('my_teams')">My Teams</div>
            </div>
            <button class="btn-teams" onclick="openTeamSelector()">Manage My Teams (<span id="team_count">0</span> Selected)</button>
            <button class="btn-save" onclick="saveConfig()">SAVE SETTINGS</button>
            <div id="saveMsg" style="text-align:center; color:#4caf50; height:20px; margin-top:5px;"></div>
            <button id="btnDebug" class="btn-debug" onclick="toggleDebug()">Time Machine Mode</button>
        </div>
        <div class="panel"><span class="section-title">Game Feed Status</span><table id="gameTable"><thead><tr><th>League</th><th>Matchup</th><th>Score</th><th>Status</th><th>Situation</th></tr></thead><tbody></tbody></table></div>
        <div id="teamModal" class="modal"><div class="modal-content"><div style="display:flex; justify-content:space-between;"><h2>Select Teams</h2><button onclick="closeModal()" style="background:#444;">Done</button></div><div class="tabs"><div class="tab active" onclick="showTab('nfl')">NFL</div><div class="tab" onclick="showTab('ncf_fbs')">FBS</div><div class="tab" onclick="showTab('ncf_fcs')">FCS</div><div class="tab" onclick="showTab('mlb')">MLB</div><div class="tab" onclick="showTab('nhl')">NHL</div><div class="tab" onclick="showTab('nba')">NBA</div></div><div id="teamGrid" class="team-grid"></div></div></div>
        <div id="debugControls" class="panel" style="display:none; border: 1px solid #ff5722;">
            <h3 style="margin-top:0;">Time Machine & Testing</h3>
            <p style="color:#aaa; font-size:0.9em; margin-bottom:15px;">Pick a date OR test a specific game state.</p>
            <div style="display:flex; gap:10px; align-items:center; flex-wrap:wrap;">
                <input type="date" id="custom_date">
                <button onclick="setDate()" style="background:var(--accent); color:white;">Go Date</button>
                <button onclick="testPP()" style="background:#ffc107; color:black;">Test Hockey PP</button>
                <button onclick="testRZ()" style="background:#d32f2f; color:white;">Test Red Zone</button>
                <button onclick="resetDate()" style="background:#444;">Reset to Live</button>
            </div>
            <div id="dateStatus" style="margin-top:10px; color:#4caf50; font-weight:bold;"></div>
        </div>
        <script>
            let currentState = { active_sports: {}, mode: 'all', my_teams: [] };
            let allTeams = {};
            let isModalOpen = false; 
            async function init() {
                const display = document.getElementById('display');
                for(let i=0; i<2048; i++) { let d = document.createElement('div'); d.className = 'led'; d.id = 'L'+i; display.appendChild(d); }
                let r = await fetch('/get_state'); let s = await r.json(); applyState(s.settings);
                setTimeout(updateLoop, 100); setInterval(refreshTable, 2000);
                try { r = await fetch('/get_teams'); allTeams = await r.json(); } catch(e) {}
            }
            function applyState(s) {
                if (isModalOpen) return;
                currentState = s;
                ['nfl','ncf_fbs','ncf_fcs','mlb','nhl','nba'].forEach(sport => { document.getElementById('btn_'+sport).className = s.active_sports[sport] ? 'sport-btn active' : 'sport-btn'; });
                document.querySelectorAll('.mode-opt').forEach(m => m.classList.remove('active'));
                if(s.mode === 'all') document.getElementById('mode_all').classList.add('active');
                else if(s.mode === 'live') document.getElementById('mode_live').classList.add('active');
                else if(s.mode === 'my_teams') document.getElementById('mode_my').classList.add('active');
                document.getElementById('team_count').innerText = s.my_teams.length;
                const btnDebug = document.getElementById('btnDebug');
                if(s.debug_mode) { btnDebug.classList.add('active'); btnDebug.innerText = "Time Machine: ON"; document.getElementById('debugControls').style.display = 'block'; } 
                else { btnDebug.classList.remove('active'); btnDebug.innerText = "Time Machine Mode"; document.getElementById('debugControls').style.display = 'none'; }
                if(s.custom_date) { 
                    if(s.custom_date.startsWith('TEST')) document.getElementById('dateStatus').innerText = "MODE: " + s.custom_date;
                    else { document.getElementById('custom_date').value = s.custom_date; document.getElementById('dateStatus').innerText = "Viewing: " + s.custom_date; }
                }
            }
            async function updateLoop() {
                try { let r = await fetch('/data'); let pixels = await r.json(); pixels.data.forEach((color, i) => { let el = document.getElementById('L'+i); if(el.dataset.c !== color) { el.style.backgroundColor = color; el.style.boxShadow = color !== '#000000' ? `0 0 4px ${color}` : 'none'; el.dataset.c = color; } }); } catch(e) {}
                setTimeout(updateLoop, 100);
            }
            async function refreshTable() {
                try {
                    let r = await fetch('/get_state'); let data = await r.json();
                    const tbody = document.querySelector('#gameTable tbody'); tbody.innerHTML = '';
                    if (data.games.length === 0) tbody.innerHTML = '<tr><td colspan="5" style="text-align:center; padding:20px; color:#666;">No active games found for current filter.</td></tr>';
                    data.games.forEach(g => {
                        let isActive = true;
                        if (currentState.debug_mode && currentState.custom_date) isActive = true;
                        else {
                            if (!currentState.active_sports[g.sport]) isActive = false;
                            else if (currentState.mode === 'my_teams') { if (!currentState.my_teams.includes(g.home_abbr) && !currentState.my_teams.includes(g.away_abbr)) isActive = false; } 
                            else if (currentState.mode === 'live') { if (g.state !== 'in') isActive = false; }
                        }
                        
                        let sitStr = '';
                        if(g.sport.includes('nfl') || g.sport.includes('ncf')) sitStr = g.situation.downDist || '';
                        else if(g.sport === 'nhl' && g.situation.powerPlay) sitStr = '<span style="color:#ffeb3b; font-weight:bold;">POWER PLAY</span>';
                        
                        let sportLabel = g.sport.toUpperCase().replace('NCF_', 'CFB-');
                        let rowClass = isActive ? 'status-active' : 'status-inactive';
                        tbody.innerHTML += `<tr class="${rowClass}"><td>${sportLabel}</td><td><img src="${g.away_logo}" class="logo-mini"> ${g.away_abbr} @ <img src="${g.home_logo}" class="logo-mini"> ${g.home_abbr}</td><td>${g.away_score} - ${g.home_score}</td><td>${g.status}</td><td>${sitStr}</td></tr>`;
                    });
                } catch(e) {}
            }
            function toggleSport(sport) { currentState.active_sports[sport] = !currentState.active_sports[sport]; applyState(currentState); }
            function setMode(mode) { currentState.mode = mode; applyState(currentState); }
            function saveConfig() { fetch('/set_config', { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(currentState) }).then(() => { document.getElementById('saveMsg').innerText = "Saved!"; setTimeout(() => document.getElementById('saveMsg').innerText = "", 2000); }); }
            function toggleDebug() { fetch('/toggle_debug').then(r => r.json()).then(res => { currentState.debug_mode = res.status; applyState(currentState); }); }
            function setDate() { const d = document.getElementById('custom_date').value; if(!d) return alert("Please pick a date"); currentState.custom_date = d; fetch('/set_custom_date', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({date: d}) }).then(() => applyState(currentState)); }
            
            function testPP() {
                currentState.custom_date = 'TEST_PP';
                if(!currentState.debug_mode) toggleDebug();
                fetch('/set_custom_date', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({date: 'TEST_PP'}) }).then(() => applyState(currentState));
            }
            function testRZ() {
                currentState.custom_date = 'TEST_RZ';
                if(!currentState.debug_mode) toggleDebug();
                fetch('/set_custom_date', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({date: 'TEST_RZ'}) }).then(() => applyState(currentState));
            }

            function resetDate() { currentState.custom_date = null; fetch('/set_custom_date', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({date: null}) }).then(() => applyState(currentState)); }
            function openTeamSelector() { isModalOpen = true; document.getElementById('teamModal').style.display = 'block'; showTab('nfl'); }
            function closeModal() { isModalOpen = false; document.getElementById('teamModal').style.display = 'none'; applyState(currentState); }
            function showTab(league) {
                document.querySelectorAll('.tab').forEach(t => t.classList.remove('active')); event.target.classList.add('active');
                const grid = document.getElementById('teamGrid'); grid.innerHTML = '';
                if(allTeams[league]) allTeams[league].forEach(team => {
                    let isSelected = currentState.my_teams.includes(team.abbr);
                    let card = document.createElement('div'); card.className = `team-card ${isSelected ? 'selected' : ''}`;
                    card.onclick = () => {
                        if(currentState.my_teams.includes(team.abbr)) { currentState.my_teams = currentState.my_teams.filter(t => t !== team.abbr); card.classList.remove('selected'); }
                        else { currentState.my_teams.push(team.abbr); card.classList.add('selected'); }
                        document.getElementById('team_count').innerText = currentState.my_teams.length;
                    };
                    card.innerHTML = `<img src="${team.logo}"> <span>${team.abbr}</span>`;
                    grid.appendChild(card);
                });
            }
            window.onload = init;
        </script>
    </body>
    </html>
    """

@app.route('/data')
def get_pixels(): return jsonify(matrix.get_pixel_data())

@app.route('/get_state')
def get_state(): return jsonify({ 'games': state['current_games'], 'settings': state })

@app.route('/client_data')
def get_client_data(): return jsonify({ 'games': state['current_games'], 'settings': state })

@app.route('/get_teams')
def get_teams(): return jsonify(state['all_teams_data'])

@app.route('/esp32')
def get_esp32(): return jsonify({ 'games': state['current_games'] })

@app.route('/set_config', methods=['POST'])
def set_config():
    d = request.json
    state['mode'] = d['mode']
    state['active_sports'] = d['active_sports']
    state['my_teams'] = d['my_teams']
    state['current_games'] = fetcher.get_real_games() # Force Update
    return "OK"

@app.route('/toggle_debug')
def toggle_debug():
    state['debug_mode'] = not state['debug_mode']
    state['current_games'] = fetcher.get_real_games() # Force Update
    return jsonify({'status': state['debug_mode']})

@app.route('/set_custom_date', methods=['POST'])
def set_custom_date():
    state['custom_date'] = request.json.get('date')
    state['current_games'] = fetcher.get_real_games() # Force Update
    return "OK"

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 5000)))
