import time
import threading
import json
import os
import datetime
from datetime import datetime as dt, timezone, timedelta
import requests
from flask import Flask, jsonify, request
import struct # <--- ADDED
import io     # <--- ADDED
from PIL import Image # <--- ADDED

# IMPORT TEAMS
try:
    # Ensure you have a 'valid_teams.py' file if you use it for college team filtering
    from valid_teams import FBS_TEAMS, FCS_TEAMS
except ImportError:
    FBS_TEAMS = []
    FCS_TEAMS = []

# ================= CONFIGURATION =================
TIMEZONE_OFFSET = -5  # Set to -5 for EST/EDT
CONFIG_FILE = "ticker_config.json"
UPDATE_INTERVAL = 10 

# --- NHL LOGO FIXES ---
NHL_LOGO_MAP = {
    "SJS": "sj",  "NJD": "nj",  "TBL": "tb", 
    "LAK": "la",  "VGK": "vgs", "VEG": "vgs"
}

# --- LOGO OVERRIDES (For Image Generation) ---
LOGO_OVERRIDES = {
    "WSH": "https://a.espncdn.com/guid/cbe677ee-361e-91b4-5cae-6c4c30044743/logos/secondary_logo_on_black_color.png",
    "WAS": "https://a.espncdn.com/guid/cbe677ee-361e-91b4-5cae-6c4c30044743/logos/secondary_logo_on_black_color.png",
    "LEH": "https://a.espncdn.com/i/teamlogos/ncaa/500/2329.png"
}

# ================= WEB UI =================
DASHBOARD_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <title>Ticker Controller</title>
    <style>
        :root { --bg: #0f111a; --card: #1c1f2e; --accent: #ff5722; --text: #e0e0e0; --success: #4caf50; --inactive: #f44336; --warn: #ffeb3b; }
        body { background: var(--bg); color: var(--text); font-family: 'Segoe UI', sans-serif; margin: 0; padding: 10px; padding-bottom: 40px; }
        
        .panel { background: var(--card); padding: 15px; border-radius: 12px; max-width: 800px; margin: 0 auto 15px auto; box-shadow: 0 4px 6px rgba(0,0,0,0.3); }
        
        /* HEADER & HAMBURGER */
        .header-row { display: flex; justify-content: space-between; align-items: center; margin-bottom: 15px; }
        .app-title { font-size: 1.2em; font-weight: bold; letter-spacing: 1px; color: white; margin: 0; }
        .hamburger-btn { background: none; border: none; color: #fff; font-size: 1.5em; cursor: pointer; padding: 0 5px; }
        
        /* SETTINGS CONTAINER (Collapsible) */
        #settingsArea { display: block; overflow: hidden; transition: max-height 0.3s ease-out; margin-top: 5px; padding-top: 15px; border-top: 1px solid #333; }
        .settings-hidden { display: none !important; }

        .section-title { color: #888; text-transform: uppercase; font-size: 0.75em; display: block; margin: 0 0 8px 0; font-weight: bold; letter-spacing: 1px; }
        
        /* VISIBLE CONTROLS (Filters/Scroll) */
        .control-row { margin-bottom: 15px; }
        
        /* SETTINGS CONTROLS (Sports/Teams) */
        .sports-grid { 
            display: grid; 
            grid-template-columns: repeat(3, 1fr); /* 3x2 Grid */
            gap: 8px; 
            margin-bottom: 15px; 
        }
        .sport-btn { padding: 10px; border-radius: 6px; background: #252836; color: #888; cursor: pointer; text-align: center; transition: 0.2s; font-weight: bold; font-size: 0.85em; }
        .sport-btn.active { background: var(--success); color: white; box-shadow: 0 0 8px rgba(76,175,80,0.3); }
        
        .mode-switch { display: flex; background: #252836; padding: 4px; border-radius: 8px; }
        .mode-opt { flex: 1; text-align: center; padding: 8px; cursor: pointer; border-radius: 6px; color: #888; font-size: 0.85em; }
        .mode-opt.active { background: #3d4150; color: white; font-weight: bold; }

        button.action-btn { padding: 12px; border-radius: 6px; border: none; font-weight: bold; cursor: pointer; width: 100%; margin-bottom: 10px; font-size: 0.9em; }
        .btn-teams { background: #3d4150; color: white; }
        
        /* SAVE BUTTON STYLING */
        .btn-save { 
            background: #3d4150; 
            color: #ccc; 
            font-size: 1em; 
            margin-bottom: 0; 
            transition: background 0.3s, color 0.3s;
        }
        .btn-save:hover { background: #4a4e60; color: white; }

        /* --- RESPONSIVE TABLE --- */
        table.game-table { width: 100%; border-collapse: separate; border-spacing: 0 6px; }
        th { 
            text-align: center; 
            color: #666; font-size: 0.7em; text-transform: uppercase; padding: 0 8px 4px 8px; font-weight: 600; 
        }
        th:first-child { text-align: left; } 
        
        tr.game-row td { background: #252836; padding: 10px 8px; border-top: 1px solid #333; border-bottom: 1px solid #333; font-size: 0.9em; vertical-align: middle; }
        
        /* BORDER RADIUS & INDICATORS (Desktop Default) */
        tr.game-row td:first-child { border-left: 4px solid var(--success); border-top-left-radius: 6px; border-bottom-left-radius: 6px; }
        tr.game-row td:last-child { border-top-right-radius: 6px; border-bottom-right-radius: 6px; border-right: 1px solid #333; }
        
        tr.game-row.filtered-out td:first-child { border-left-color: var(--inactive); }
        tr.game-row.filtered-out { opacity: 0.6; }

        /* COLUMN WIDTHS (Desktop Default) */
        .col-league { width: 50px; font-weight: bold; color: #aaa; font-size: 0.75em; text-align: center; }
        .col-matchup { color: white; font-weight: 500; display: flex; align-items: center; gap: 6px; white-space: nowrap; text-align: left; }
        .col-score { width: 60px; font-weight: bold; color: white; text-align: center; font-size: 1.1em; }
        .col-status { width: 90px; color: #888; font-size: 0.75em; text-align: right; line-height: 1.2; }
        .col-situation { width: 120px; text-align: right; font-weight: bold; font-size: 0.8em; }
        .league-label { display: block; } 

        .mini-logo { width: 24px; height: 24px; object-fit: contain; }
        .at-symbol { color: #555; font-size: 0.8em; margin: 0 2px; }

        .sit-football { color: var(--success); }
        .sit-hockey { color: var(--warn); }
        .sit-baseball { color: #aaa; }

        /* --- MOBILE TWEAKS (Fixes Indicator Gap) --- */
        @media (max-width: 600px) {
            body { padding: 5px; }
            .panel { padding: 12px; margin-bottom: 10px; }
            
            /* Hide League Column Header */
            th.th-league { display: none; }
            
            /* Hide League Column CONTENT and reset padding/width */
            td.col-league { display: none; }
            
            /* Apply the indicator border to the Matchup column (the new first visible column) */
            tr.game-row td:nth-child(2) { 
                border-left-width: 4px; 
                border-left-style: solid; 
                border-top-left-radius: 6px; 
                border-bottom-left-radius: 6px; 
                padding-left: 8px; /* Reset padding to keep match-up close to the line */
            }
            
            /* Ensure the indicator line color is correct on mobile */
            tr.game-row.filtered-out td:nth-child(2) { border-left-color: var(--inactive) !important; }
            tr.game-row:not(.filtered-out) td:nth-child(2) { border-left-color: var(--success); }
            
            /* Compact Columns */
            tr.game-row td { padding: 8px 5px; }
            .mini-logo { width: 20px; height: 20px; }
            .col-matchup { font-size: 0.9em; gap: 4px; }
            .col-score { width: 45px; font-size: 1em; }
            .col-status { width: 70px; font-size: 0.7em; }
            .col-situation { width: 80px; font-size: 0.7em; }
        }

        /* MODAL */
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
        <div class="header-row">
            <h1 class="app-title">Ticker Control</h1>
            <button class="hamburger-btn" onclick="toggleSettings()">☰</button>
        </div>

        <div class="control-row">
            <span class="section-title">Display Filter</span>
            <div class="mode-switch">
                <div id="mode_all" class="mode-opt" onclick="setMode('all')">Show All</div>
                <div id="mode_live" class="mode-opt" onclick="setMode('live')">Live Only</div>
                <div id="mode_my" class="mode-opt" onclick="setMode('my_teams')">My Teams</div>
            </div>
        </div>

        <div class="control-row">
            <span class="section-title">Scroll Style</span>
            <div class="mode-switch">
                <div id="scroll_paged" class="mode-opt" onclick="setScroll(false)">Paged (Slide)</div>
                <div id="scroll_seamless" class="mode-opt" onclick="setScroll(true)">Seamless (Marquee)</div>
            </div>
        </div>

        <button class="action-btn btn-save" onclick="saveConfig()">SAVE SETTINGS</button>

        <div id="settingsArea" class="settings-hidden">
            <span class="section-title">Enabled Sports</span>
            <div class="sports-grid">
                <div id="btn_nfl" class="sport-btn" onclick="toggleSport('nfl')">NFL</div>
                <div id="btn_ncf_fbs" class="sport-btn" onclick="toggleSport('ncf_fbs')">FBS</div>
                <div id="btn_ncf_fcs" class="sport-btn" onclick="toggleSport('ncf_fcs')">FCS</div>
                <div id="btn_mlb" class="sport-btn" onclick="toggleSport('mlb')">MLB</div>
                <div id="btn_nhl" class="sport-btn" onclick="toggleSport('nhl')">NHL</div>
                <div id="btn_nba" class="sport-btn" onclick="toggleSport('nba')">NBA</div>
            </div>

            <button class="action-btn btn-teams" onclick="openTeamModal()">Manage My Teams (<span id="team_count">0</span>)</button>
            
            <div style="text-align:center; margin-top:15px;">
                <a href="#" onclick="toggleDebug()" style="color:#555; font-size:0.75em; text-decoration:none;">Debug / Time Machine</a>
            </div>
            <div id="debugControls" style="display:none; margin-top:10px; padding-top:10px; border-top:1px solid #333;">
                <div style="display:flex; gap:10px;">
                    <input type="date" id="custom_date" style="padding:8px; flex:1; background:#111; color:#fff; border:1px solid #555; border-radius:4px;">
                    <button style="width:auto; background:#fff; color:#000; margin:0; padding:0 15px;" onclick="setDate()">Go</button>
                </div>
                <button style="background:#333; color:#aaa; margin-top:8px; width:100%; padding:8px; border:none; cursor:pointer;" onclick="resetDate()">Reset to Live</button>
            </div>
        </div>
    </div>

    <div class="panel" style="padding-top:5px;">
        <div style="display:flex; justify-content:space-between; align-items:center; border-bottom:1px solid #333; padding-bottom:10px; margin-bottom:5px;">
            <span class="section-title" style="margin:0;">Active Feed (<span id="game_count">0</span>)</span>
            <div style="font-size:0.7em; color:#666;">Updates every 5s</div>
        </div>
        
        <table class="game-table">
            <thead>
                <tr>
                    <th class="th-league">LGE</th>
                    <th>Matchup</th>
                    <th style="text-align:center;">Score</th>
                    <th style="text-align:right;">Status</th>
                    <th style="text-align:right;">Sit.</th>
                </tr>
            </thead>
            <tbody id="gameTableBody"></tbody>
        </table>
    </div>

    <div id="teamModal" class="modal">
        <div class="modal-content">
            <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:10px;">
                <h3 style="margin:0; color:white;">Select Teams</h3>
                <button onclick="closeTeamModal()" style="background:#444; color:white; border:none; padding:5px 15px; border-radius:4px; cursor:pointer;">Done</button>
            </div>
            <div class="tabs">
                <div id="tab_nfl" class="tab active" onclick="showTab('nfl')">NFL</div>
                <div id="tab_ncf_fbs" class="tab" onclick="showTab('ncf_fbs')">FBS</div>
                <div id="tab_ncf_fcs" class="tab" onclick="showTab('ncf_fcs')">FCS</div>
                <div id="tab_mlb" class="tab" onclick="showTab('mlb')">MLB</div>
                <div id="tab_nhl" class="tab" onclick="showTab('nhl')">NHL</div>
                <div id="tab_nba" class="tab" onclick="showTab('nba')">NBA</div>
            </div>
            <div id="teamGrid" class="team-grid"><div style="text-align:center; padding:20px; color:#666; grid-column: 1/-1;">Loading...</div></div>
        </div>
    </div>

    <script>
        let currentState = { active_sports: {}, mode: 'all', my_teams: [], scroll_seamless: false };
        let allTeams = {};
        let currentTabLeague = 'nfl';
        let settingsVisible = false;

        async function init() {
            let r = await fetch('/api/state');
            let data = await r.json();
            currentState = data.settings;
            fetch('/api/teams').then(r => r.json()).then(d => { allTeams = d; });
            renderUI();
            renderGames(data.games);
            setInterval(fetchLiveTicker, 5000);
            
            // Set initial visibility based on screen size (default hidden on small screens)
            if (window.innerWidth >= 600) { settingsVisible = true; document.getElementById('settingsArea').classList.remove('settings-hidden'); }
        }

        function toggleSettings() {
            const area = document.getElementById('settingsArea');
            if (settingsVisible) area.classList.add('settings-hidden');
            else area.classList.remove('settings-hidden');
            settingsVisible = !settingsVisible;
        }

        async function fetchLiveTicker() {
            try {
                let r = await fetch('/api/all_games');
                let data = await r.json();
                renderGames(data.games);
            } catch(e) {}
        }

        function renderUI() {
            ['nfl','ncf_fbs','ncf_fcs','mlb','nhl','nba'].forEach(sport => {
                let btn = document.getElementById('btn_' + sport);
                if(btn) btn.className = currentState.active_sports[sport] ? 'sport-btn active' : 'sport-btn';
            });
            document.querySelectorAll('.mode-opt').forEach(m => m.classList.remove('active'));
            if(currentState.mode === 'all') document.getElementById('mode_all').classList.add('active');
            else if(currentState.mode === 'live') document.getElementById('mode_live').classList.add('active');
            else if(currentState.mode === 'my_teams') document.getElementById('mode_my').classList.add('active');
            if(currentState.scroll_seamless) document.getElementById('scroll_seamless').classList.add('active');
            else document.getElementById('scroll_paged').classList.add('active');
            document.getElementById('team_count').innerText = currentState.my_teams.length;
            if(currentState.debug_mode) {
                document.getElementById('debugControls').style.display = 'block';
                if(currentState.custom_date) document.getElementById('custom_date').value = currentState.custom_date;
            } else { document.getElementById('debugControls').style.display = 'none'; }
        }

        function formatLeague(key) {
            if(key === 'ncf_fbs') return 'FBS';
            if(key === 'ncf_fcs') return 'FCS';
            return key.toUpperCase();
        }
        
        function renderGames(games) {
            const tbody = document.getElementById('gameTableBody');
            document.getElementById('game_count').innerText = games.length;
            tbody.innerHTML = '';
            
            if(games.length === 0) { 
                tbody.innerHTML = '<tr><td colspan="5" style="text-align:center; padding:20px; color:#555;">No active games found.</td></tr>'; 
                return; 
            }

            games.forEach(g => {
                let tr = document.createElement('tr');
                tr.className = g.is_shown ? 'game-row' : 'game-row filtered-out';
                
                let leagueLabel = formatLeague(g.sport);
                let awayLogo = g.away_logo ? `<img src="${g.away_logo}" class="mini-logo">` : '';
                let homeLogo = g.home_logo ? `<img src="${g.home_logo}" class="mini-logo">` : '';
                
                let sitHTML = '';
                if(g.state === 'in' || g.state === 'half') {
                    if(g.sport === 'nfl' || g.sport.includes('ncf')) {
                        if(g.status === 'HALFTIME') {
                            sitHTML = '';
                        } else if(g.situation.downDist) {
                            sitHTML = `<span class="sit-football">${g.situation.downDist}</span>`;
                        } else if(g.situation.isRedZone) {
                            sitHTML = `<span class="sit-football">RedZone</span>`;
                        }
                    } else if(g.sport === 'nhl' && g.situation.powerPlay) {
                        let poss = g.situation.possession ? ` (${g.situation.possession})` : '';
                        sitHTML = `<span class="sit-hockey">PP${poss}</span>`;
                    } else if(g.sport === 'mlb' && g.situation.outs !== undefined) {
                        sitHTML = `<span class="sit-baseball">${g.situation.balls}-${g.situation.strikes}, ${g.situation.outs} Out</span>`;
                    }
                }

                tr.innerHTML = `
                    <td class="col-league"><span class="league-label">${leagueLabel}</span></td>
                    <td><div class="col-matchup">
                        ${awayLogo} ${g.away_abbr} <span class="at-symbol">@</span> ${homeLogo} ${g.home_abbr}
                    </div></td>
                    <td class="col-score">${g.away_score}-${g.home_score}</td>
                    <td class="col-status">${g.status}</td>
                    <td class="col-situation">${sitHTML}</td>
                `;
                tbody.appendChild(tr);
            });
        }
        
        function toggleSport(s) { currentState.active_sports[s] = !currentState.active_sports[s]; renderUI(); }
        function setMode(m) { currentState.mode = m; renderUI(); }
        function setScroll(isSeamless) { currentState.scroll_seamless = isSeamless; renderUI(); }
        
        async function saveConfig() {
            await fetch('/api/config', { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(currentState)});
            let btn = document.querySelector('.btn-save');
            let oldText = btn.innerText;
            btn.innerText = "SAVED!";
            
            // CHANGED: Uses exact hex requested for active state
            btn.style.background = "#1c1f2e"; 
            btn.style.color = "white";
            
            setTimeout(() => { 
                btn.innerText = oldText; 
                btn.style.background = ""; // Revert to CSS default (Grey)
                btn.style.color = "";
            }, 1500);
        }

        function openTeamModal() { document.getElementById('teamModal').style.display = 'block'; showTab(currentTabLeague); }
        function closeTeamModal() { document.getElementById('teamModal').style.display = 'none'; renderUI(); }
        function showTab(league) {
            currentTabLeague = league;
            document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
            let activeTab = document.getElementById('tab_' + league);
            if(activeTab) activeTab.classList.add('active');
            const grid = document.getElementById('teamGrid');
            grid.innerHTML = '';
            if (!allTeams[league] || allTeams[league].length === 0) { grid.innerHTML = '<div style="grid-column:1/-1; text-align:center; padding:20px; color:#666;">No teams found.</div>'; return; }
            allTeams[league].forEach(team => {
                let isSelected = currentState.my_teams.includes(team.abbr);
                let card = document.createElement('div');
                card.className = `team-card ${isSelected ? 'selected' : ''}`;
                card.onclick = () => toggleTeamSelection(team.abbr, card);
                let logoImg = team.logo ? `<img src="${team.logo}">` : '<div style="width:35px;height:35px;"></div>';
                card.innerHTML = `${logoImg} <span>${team.abbr}</span>`;
                grid.appendChild(card);
            });
        }
        function toggleTeamSelection(abbr, cardElement) {
            if(currentState.my_teams.includes(abbr)) { currentState.my_teams = currentState.my_teams.filter(t => t !== abbr); cardElement.classList.remove('selected'); } 
            else { currentState.my_teams.push(abbr); cardElement.classList.add('selected'); }
            document.getElementById('team_count').innerText = currentState.my_teams.length;
        }
        async function toggleDebug() {
            currentState.debug_mode = !currentState.debug_mode;
            await fetch('/api/debug', { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({debug_mode: currentState.debug_mode})});
            init(); 
        }
        async function setDate() {
            let d = document.getElementById('custom_date').value;
            await fetch('/api/debug', { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({custom_date: d})});
            setTimeout(init, 500);
        }
        async function resetDate() {
            await fetch('/api/debug', { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({custom_date: null})});
            setTimeout(init, 500);
        }
        window.onload = init;
    </script>
</body>
</html>
"""

# ================= DEFAULT STATE =================
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
            if 'active_sports' in loaded: state['active_sports'] = loaded['active_sports']
            if 'mode' in loaded: state['mode'] = loaded['mode']
            if 'scroll_seamless' in loaded: state['scroll_seamless'] = loaded['scroll_seamless']
            if 'my_teams' in loaded: state['my_teams'] = loaded['my_teams']
    except: pass

class SportsFetcher:
    def __init__(self):
        self.base_url = 'http://site.api.espn.com/apis/site/v2/sports/'
        self.leagues = {
            'nfl': { 'path': 'football/nfl', 'scoreboard_params': {}, 'team_params': {'limit': 100} },
            'ncf_fbs': { 'path': 'football/college-football', 'scoreboard_params': {'groups': '80', 'limit': 100}, 'team_params': {'limit': 1000} },
            'ncf_fcs': { 'path': 'football/college-football', 'scoreboard_params': {'groups': '81', 'limit': 100}, 'team_params': {'limit': 1000} },
            'mlb': { 'path': 'baseball/mlb', 'scoreboard_params': {}, 'team_params': {'limit': 100} },
            'nhl': { 'path': 'hockey/nhl', 'scoreboard_params': {}, 'team_params': {'limit': 100} },
            'nba': { 'path': 'basketball/nba', 'scoreboard_params': {}, 'team_params': {'limit': 100} }
        }

    def fetch_all_teams(self):
        try:
            teams_catalog = {k: [] for k in self.leagues.keys()}
            for league_key in ['nfl', 'mlb', 'nhl', 'nba']:
                self._fetch_simple_league(league_key, teams_catalog)

            url = f"{self.base_url}football/college-football/teams"
            try:
                r = requests.get(url, params={'limit': 1000}, timeout=10)
                data = r.json()
                if 'sports' in data:
                    for sport in data['sports']:
                        for league in sport['leagues']:
                            for item in league.get('teams', []):
                                try:
                                    t_abbr = item['team'].get('abbreviation', 'unk')
                                    t_short = item['team'].get('shortDisplayName', '') 
                                    logos = item['team'].get('logos', [])
                                    t_logo = logos[0].get('href', '') if len(logos) > 0 else ''
                                    team_obj = {'abbr': t_abbr, 'logo': t_logo, 'name': t_short}
                                    if t_abbr in FBS_TEAMS: teams_catalog['ncf_fbs'].append(team_obj)
                                    elif t_abbr in FCS_TEAMS: teams_catalog['ncf_fcs'].append(team_obj)
                                except: continue
            except: pass
            state['all_teams_data'] = teams_catalog
        except Exception as e: print(e)

    def _fetch_simple_league(self, league_key, catalog):
        config = self.leagues[league_key]
        url = f"{self.base_url}{config['path']}/teams"
        try:
            r = requests.get(url, params=config['team_params'], timeout=10)
            data = r.json()
            if 'sports' in data:
                for sport in data['sports']:
                    for league in sport['leagues']:
                        for item in league.get('teams', []):
                            catalog[league_key].append({
                                'abbr': item['team'].get('abbreviation', 'unk'), 
                                'logo': item['team'].get('logos', [{}])[0].get('href', '')
                            })
        except: pass

    # ================= NHL NATIVE FETCHING =================
    def _fetch_nhl_native(self, games_list, target_date_str):
        schedule_url = "https://api-web.nhle.com/v1/schedule/now"
        try:
            response = requests.get(schedule_url, timeout=5)
            if response.status_code != 200: return
            schedule_data = response.json()
        except: return

        for date_entry in schedule_data.get('gameWeek', []):
            if date_entry.get('date') != target_date_str: continue 
            
            for game in date_entry.get('games', []):
                self._process_single_nhl_game(game['id'], games_list)

    def _process_single_nhl_game(self, game_id, games_list):
        pbp_url = f"https://api-web.nhle.com/v1/gamecenter/{game_id}/play-by-play"
        try:
            r = requests.get(pbp_url, timeout=3)
            if r.status_code != 200: return
            data = r.json()
        except: return

        away_abbr = data['awayTeam']['abbrev']
        home_abbr = data['homeTeam']['abbrev']
        away_score = str(data['awayTeam'].get('score', 0))
        home_score = str(data['homeTeam'].get('score', 0))
        
        # --- LOGO CORRECTION ---
        away_code = NHL_LOGO_MAP.get(away_abbr, away_abbr.lower())
        home_code = NHL_LOGO_MAP.get(home_abbr, home_abbr.lower())
        
        # Apply Capitals logo override for WSH
        if away_abbr.upper() == 'WSH':
            away_logo = "https://a.espncdn.com/guid/cbe677ee-361e-91b4-5cae-6c4c30044743/logos/secondary_logo_on_black_color.png"
        else:
            away_logo = f"https://a.espncdn.com/i/teamlogos/nhl/500/{away_code}.png"
            
        if home_abbr.upper() == 'WSH':
            home_logo = "https://a.espncdn.com/guid/cbe677ee-361e-91b4-5cae-6c4c30044743/logos/secondary_logo_on_black_color.png"
        else:
            home_logo = f"https://a.espncdn.com/i/teamlogos/nhl/500/{home_code}.png"

        game_state = data.get('gameState', 'OFF') 
        mapped_state = 'in' if game_state in ['LIVE', 'CRIT'] else 'post'
        if game_state in ['PRE', 'FUT']: mapped_state = 'pre'

        # FILTER LOGIC: Calculate 'is_shown'
        is_shown = True
        if state['mode'] == 'live' and mapped_state != 'in': is_shown = False
        if state['mode'] == 'my_teams':
            if (home_abbr not in state['my_teams']) and (away_abbr not in state['my_teams']): is_shown = False

        clock = data.get('clock', {})
        time_rem = clock.get('timeRemaining', '00:00')
        period = data.get('periodDescriptor', {}).get('number', 1)
        
        if game_state == 'FINAL' or game_state == 'OFF': status_disp = "FINAL"
        elif game_state in ['PRE', 'FUT']: 
            raw_time = data.get('startTimeUTC', '')
            if raw_time:
                try:
                    utc_dt = dt.strptime(raw_time, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
                    local_dt = utc_dt + timedelta(hours=TIMEZONE_OFFSET)
                    status_disp = local_dt.strftime("%I:%M %p").lstrip('0') 
                except: status_disp = "Scheduled"
            else: status_disp = "Scheduled"
        elif clock.get('inIntermission'): status_disp = f"P{period} INT"
        else: status_disp = f"P{period} {time_rem}"

        sit_code = data.get('situation', {}).get('situationCode', '1551')
        try:
            away_skaters = int(sit_code[1])
            home_skaters = int(sit_code[2])
        except:
            away_skaters = 5
            home_skaters = 5

        is_pp = False
        possession = ""
        if away_skaters > home_skaters:
            is_pp = True
            possession = away_abbr 
        elif home_skaters > away_skaters:
            is_pp = True
            possession = home_abbr

        game_obj = {
            'sport': 'nhl', 'id': str(game_id), 'status': status_disp, 'state': mapped_state,
            'is_shown': is_shown, 
            'home_abbr': home_abbr, 'home_score': home_score, 'home_logo': home_logo, 'home_id': home_abbr, 
            'away_abbr': away_abbr, 'away_score': away_score, 'away_logo': away_logo, 'away_id': away_abbr,
            'situation': { 'powerPlay': is_pp, 'possession': possession }
        }
        
        games_list.append(game_obj)
    # =======================================================

    def get_real_games(self):
        games = []
        
        if state['debug_mode'] and state['custom_date'] == 'TEST_PP':
             games.append({ "sport": "nhl", "id": "test_pp", "status": "P2 14:20", "state": "in", "is_shown": True, "home_abbr": "NYR", "home_id": "NYR", "home_score": "3", "home_logo": "https://a.espncdn.com/i/teamlogos/nhl/500/nyr.png", "away_abbr": "BOS", "away_id": "BOS", "away_score": "2", "away_logo": "https://a.espncdn.com/i/teamlogos/nhl/500/bos.png", "situation": {"powerPlay": True, "possession": "BOS"} })
             state['current_games'] = games
             return

        req_params = {}
        if state['debug_mode'] and state['custom_date']:
            target_date_str = state['custom_date']
            req_params['dates'] = target_date_str.replace('-', '')
            is_history = True
        else:
            local_now = dt.now(timezone.utc) + timedelta(hours=TIMEZONE_OFFSET)
            target_date_str = local_now.strftime("%Y-%m-%d")
            is_history = False
        
        for league_key, config in self.leagues.items():
            if not state['active_sports'].get(league_key, False): continue 

            if league_key == 'nhl':
                self._fetch_nhl_native(games, target_date_str)
                continue

            try:
                current_params = config['scoreboard_params'].copy()
                current_params.update(req_params)
                r = requests.get(f"{self.base_url}{config['path']}/scoreboard", params=current_params, timeout=3)
                data = r.json()
                
                for event in data.get('events', []):
                    if 'date' not in event: continue
                    utc_str = event['date'].replace('Z', '')
                    game_utc = dt.fromisoformat(utc_str).replace(tzinfo=timezone.utc)
                    local_game_time = game_utc + timedelta(hours=TIMEZONE_OFFSET)
                    game_date_str = local_game_time.strftime("%Y-%m-%d")
                    
                    status_obj = event.get('status', {})
                    status_type = status_obj.get('type', {})
                    status_state = status_type.get('state', 'pre')
                    
                    keep_date = (status_state == 'in') or (game_date_str == target_date_str)
                    if league_key == 'mlb' and not keep_date: continue

                    if keep_date:
                        comp = event['competitions'][0]
                        home = comp['competitors'][0]
                        away = comp['competitors'][1]
                        sit = comp.get('situation', {})
                        
                        raw_status = status_type.get('shortDetail', 'Scheduled')
                        
                        # --- HALFTIME & FOOTBALL CLOCK LOGIC ---
                        status_display = raw_status # Default
                        
                        period = status_obj.get('period', 1)
                        clock = status_obj.get('displayClock', '')

                        # 1. FORCE HALFTIME STATE if Q2 and clock is 0:00 or state is 'half'
                        is_halftime = (status_state == 'half') or (period == 2 and clock == '0:00')
                        
                        if is_halftime:
                            status_display = "HALFTIME"
                            status_state = 'half' # Ensure state matches logic
                        
                        elif status_state == 'in' and 'football' in config['path']:
                            # 2. FOOTBALL LIVE CLOCK: "Q# - 12:45"
                            if clock:
                                status_display = f"Q{period} - {clock}"
                            else:
                                status_display = f"Q{period}" # Fallback
                        
                        else:
                            # Standard cleanup for other sports/states
                            status_display = raw_status.replace("Final", "FINAL").replace(" EST", "").replace(" EDT", "").replace("/OT", "")
                            if " - " in status_display:
                                status_display = status_display.split(" - ")[-1]
                        
                        # --- FILTER LOGIC (Calculate is_shown) ---
                        is_shown = True
                        if state['mode'] == 'live':
                            if status_state not in ['in', 'half']: is_shown = False
                        elif state['mode'] == 'my_teams':
                            h_abbr = home['team']['abbreviation']
                            a_abbr = away['team']['abbreviation']
                            if (h_abbr not in state['my_teams']) and (a_abbr not in state['my_teams']):
                                is_shown = False
                        
                        # Apply Capitals logo override
                        home_logo_url = home['team'].get('logo', '')
                        away_logo_url = away['team'].get('logo', '')
                        if home['team']['abbreviation'].upper() == 'WSH':
                            home_logo_url = "https://a.espncdn.com/guid/cbe677ee-361e-91b4-5cae-6c4c30044743/logos/secondary_logo_on_black_color.png"
                        if away['team']['abbreviation'].upper() == 'WSH':
                            away_logo_url = "https://a.espncdn.com/guid/cbe677ee-361e-91b4-5cae-6c4c30044743/logos/secondary_logo_on_black_color.png"
                            
                        game_obj = {
                            'sport': league_key, 'id': event['id'], 'status': status_display, 'state': status_state,
                            'is_shown': is_shown, 
                            'home_abbr': home['team']['abbreviation'], 'home_score': home.get('score', '0'), 
                            'home_logo': home_logo_url, 'home_id': home.get('id'),
                            'away_abbr': away['team']['abbreviation'], 'away_score': away.get('score', '0'), 
                            'away_logo': away_logo_url, 'away_id': away.get('id'),
                            'situation': {}
                        }

                        # 3. SITUATION DATA: Only show if LIVE (not Halftime)
                        if status_state == 'in' and not is_halftime:
                            if 'football' in config['path']:
                                # RedZone Fix: Only show if API actively reports it (clears on score)
                                is_rz = sit.get('isRedZone', False)
                                game_obj['situation'] = { 'possession': sit.get('possession', ''), 'downDist': sit.get('downDistanceText', ''), 'isRedZone': is_rz }
                            elif league_key == 'mlb':
                                game_obj['situation'] = { 'balls': sit.get('balls', 0), 'strikes': sit.get('strikes', 0), 'outs': sit.get('outs', 0), 'onFirst': sit.get('onFirst', False), 'onSecond': sit.get('onSecond', False), 'onThird': sit.get('onThird', False) }
                        
                        games.append(game_obj)

            except Exception as e: print(f"Fetch Error {league_key}: {e}")
            
        state['current_games'] = games

fetcher = SportsFetcher()

def background_updater():
    fetcher.fetch_all_teams()
    while True:
        fetcher.get_real_games()
        time.sleep(UPDATE_INTERVAL)

app = Flask(__name__)

@app.route('/')
def dashboard(): return DASHBOARD_HTML

# --- TICKER API: ONLY RETURNS GREEN GAMES (for Simulator) ---
@app.route('/api/ticker')
def get_ticker_data():
    visible_games = [g for g in state['current_games'] if g.get('is_shown', True)]
    return jsonify({
        'meta': { 'time': dt.now(timezone.utc).strftime("%I:%M %p"), 'count': len(visible_games), 'speed': 0.02, 'scroll_seamless': state.get('scroll_seamless', False) },
        'games': visible_games
    })

# --- DASHBOARD API: RETURNS ALL GAMES (for Web UI) ---
@app.route('/api/all_games')
def get_all_games():
    return jsonify({ 'games': state['current_games'] })

@app.route('/api/state')
def get_full_state(): return jsonify({'settings': state, 'games': state['current_games']})

@app.route('/api/teams')
def get_teams(): return jsonify(state['all_teams_data'])

@app.route('/api/config', methods=['POST'])
def update_config():
    d = request.json
    if 'mode' in d: state['mode'] = d['mode']
    if 'active_sports' in d: state['active_sports'] = d['active_sports']
    if 'scroll_seamless' in d: state['scroll_seamless'] = d['scroll_seamless']
    if 'my_teams' in d: state['my_teams'] = d['my_teams']
    
    try:
        with open(CONFIG_FILE, 'w') as f:
            json.dump({
                'active_sports': state['active_sports'], 
                'mode': state['mode'], 
                'scroll_seamless': state['scroll_seamless'], 
                'my_teams': state['my_teams']
            }, f)
    except Exception as e:
        print(f"[WARNING] Could not save config file (File Locked). Settings active in memory only. Error: {e}")
    
    # INSTANT REFRESH
    threading.Thread(target=fetcher.get_real_games).start()
    return jsonify({"status": "ok"})

@app.route('/api/debug', methods=['POST'])
def set_debug():
    d = request.json
    if 'debug_mode' in d: state['debug_mode'] = d['debug_mode']
    if 'custom_date' in d: state['custom_date'] = d['custom_date']
    fetcher.get_real_games()
    return jsonify({"status": "ok"})

# ================= NEW: IMAGE PROCESSING ENDPOINT =================
@app.route('/api/logo/<abbr>')
def serve_logo(abbr):
    # 1. Look for URL in OVERRIDES, then in state['all_teams_data']
    url = None
    if abbr in LOGO_OVERRIDES: 
        url = LOGO_OVERRIDES[abbr]
    else:
        # Search efficiently through loaded teams
        found = False
        for league_data in state['all_teams_data'].values():
            for t in league_data:
                if t['abbr'] == abbr:
                    url = t['logo']
                    found = True
                    break
            if found: break
    
    if not url: return "Not found", 404

    try:
        # 2. Download and Resize
        r = requests.get(url, timeout=3)
        img = Image.open(io.BytesIO(r.content))
        img = img.resize((24, 24), Image.Resampling.LANCZOS).convert("RGBA")

        # 3. Handle Transparency (Composite over black)
        bg = Image.new("RGBA", img.size, (0, 0, 0, 255))
        combined = Image.alpha_composite(bg, img).convert("RGB")

        # 4. Convert to RGB565 (Little Endian for ESP32)
        pixels = list(combined.getdata())
        byte_arr = bytearray()
        for r, g, b in pixels:
            # RGB565: RRRRRGGG GGGBBBBB
            val = ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)
            # Pack as unsigned short (2 bytes), Little Endian
            byte_arr.extend(struct.pack('<H', val))

        return bytes(byte_arr), 200, {'Content-Type': 'application/octet-stream'}

    except Exception as e:
        print(f"Logo Processing Error: {e}")
        return "Error", 500

if __name__ == "__main__":
    t = threading.Thread(target=background_updater)
    t.daemon = True
    t.start()
    # Railway PORT logic included here:
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
