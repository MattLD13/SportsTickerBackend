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

# IMPORT TEAMS
try:
    from valid_teams import FBS_TEAMS, FCS_TEAMS
except ImportError:
    print("Warning: valid_teams.py not found. College filtering will be disabled.")
    FBS_TEAMS = []
    FCS_TEAMS = []

# ================= CONFIGURATION =================
TIMEZONE_OFFSET = -5  
CONFIG_FILE = "ticker_config.json"
UPDATE_INTERVAL = 20 # Seconds

# --- NHL LOGO FIXES ---
NHL_LOGO_MAP = {
    "SJS": "sj",  "NJD": "nj",  "TBL": "tb", 
    "LAK": "la",  "VGK": "vgs", "VEG": "vgs"
}

# ================= IMAGE PROCESSING =================
logo_blob_cache = {} 
logo_url_map = {}

def process_logo_to_rgb565(url, size=(24, 24)):
    try:
        r = requests.get(url, timeout=2)
        if r.status_code != 200: return None
        img = Image.open(io.BytesIO(r.content)).convert("RGBA")
        img = img.resize(size, Image.Resampling.LANCZOS)
        bg = Image.new("RGBA", size, (0, 0, 0))
        img = Image.alpha_composite(bg, img).convert("RGB")
        output = io.BytesIO()
        for y in range(size[1]):
            for x in range(size[0]):
                r, g, b = img.getpixel((x, y))
                c = ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)
                output.write(struct.pack('<H', c))
        return output.getvalue()
    except: return None

# ================= STATE MANAGEMENT =================
class TickerState:
    def __init__(self):
        self.settings = self.load_config()
        self.game_data = []
        self.all_teams_data = {} 
        self.last_fetch_time = 0
        self.is_fetching = False

    def load_config(self):
        default = {
            "active_sports": {"nfl": True, "ncf_fbs": True, "ncf_fcs": True, "mlb": True, "nhl": True, "nba": True},
            "my_teams": [], "mode": "all", "scroll_seamless": False, "debug_mode": False, "custom_date": None
        }
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, 'r') as f:
                    default.update(json.load(f))
            except: pass
        return default

    def save_config(self, settings):
        self.settings = settings
        with open(CONFIG_FILE, 'w') as f: json.dump(self.settings, f, indent=4)

ticker_state = TickerState()

# ================= DATA FETCHING =================

class SportsFetcher:
    def __init__(self):
        self.base_url = 'http://site.api.espn.com/apis/site/v2/sports'
        self.leagues = {
            'nfl': {'path': 'football/nfl', 'team_params': {'limit': 100}},
            'ncf_fbs': {'path': 'football/college-football', 'team_params': {'limit': 1000}},
            'mlb': {'path': 'baseball/mlb', 'team_params': {'limit': 100}},
            'nhl': {'path': 'hockey/nhl', 'team_params': {'limit': 100}},
            'nba': {'path': 'basketball/nba', 'team_params': {'limit': 100}}
        }

    # --- 1. Populate Team List for "My Teams" UI ---
    def fetch_all_teams(self):
        print("Fetching full team list...")
        teams_catalog = {k: [] for k in ['nfl', 'ncf_fbs', 'ncf_fcs', 'mlb', 'nhl', 'nba']}
        
        def fetch_league_teams(league_key, path, params):
            try:
                r = requests.get(f"{self.base_url}/{path}/teams", params=params, timeout=10)
                data = r.json()
                for sport in data.get('sports', []):
                    for league in sport.get('leagues', []):
                        for item in league.get('teams', []):
                            t = item.get('team', {})
                            abbr = t.get('abbreviation')
                            logo = t.get('logos', [{}])[0].get('href', '')
                            if abbr:
                                entry = {'abbr': abbr, 'logo': logo}
                                # FIX: If validation lists are empty, default to FBS so they appear somewhere
                                if league_key == 'ncf_fbs':
                                    if FBS_TEAMS and abbr in FBS_TEAMS: 
                                        teams_catalog['ncf_fbs'].append(entry)
                                    elif FCS_TEAMS and abbr in FCS_TEAMS: 
                                        teams_catalog['ncf_fcs'].append(entry)
                                    else:
                                        # Fallback if lists missing or team new
                                        teams_catalog['ncf_fbs'].append(entry) 
                                else:
                                    teams_catalog[league_key].append(entry)
                                
                                if logo: logo_url_map[abbr] = logo
            except Exception as e: 
                print(f"Error fetching teams for {league_key}: {e}")

        for key in ['nfl', 'mlb', 'nhl', 'nba']:
            fetch_league_teams(key, self.leagues[key]['path'], self.leagues[key]['team_params'])
        
        # College fetch
        fetch_league_teams('ncf_fbs', 'football/college-football', {'limit': 1000})
        
        ticker_state.all_teams_data = teams_catalog
        print("Team list updated.")

    # --- 2. NATIVE NHL FETCHING (Official NHL API) ---
    def fetch_nhl_native(self, target_date_str):
        formatted_date = f"{target_date_str[:4]}-{target_date_str[4:6]}-{target_date_str[6:]}"
        games = []
        try:
            r = requests.get("https://api-web.nhle.com/v1/schedule/now", timeout=5)
            data = r.json()
            
            for day in data.get('gameWeek', []):
                if day['date'] != formatted_date: continue
                for game in day.get('games', []):
                    try:
                        g_r = requests.get(f"https://api-web.nhle.com/v1/gamecenter/{game['id']}/play-by-play", timeout=2)
                        if g_r.status_code != 200: continue
                        gd = g_r.json()

                        h_abbr = gd['homeTeam']['abbrev']
                        a_abbr = gd['awayTeam']['abbrev']
                        
                        h_code = NHL_LOGO_MAP.get(h_abbr, h_abbr.lower())
                        a_code = NHL_LOGO_MAP.get(a_abbr, a_abbr.lower())
                        h_logo = f"https://a.espncdn.com/i/teamlogos/nhl/500/{h_code}.png"
                        a_logo = f"https://a.espncdn.com/i/teamlogos/nhl/500/{a_code}.png"
                        
                        if h_abbr == 'WSH': h_logo = "https://a.espncdn.com/guid/cbe677ee-361e-91b4-5cae-6c4c30044743/logos/secondary_logo_on_black_color.png"
                        if a_abbr == 'WSH': a_logo = "https://a.espncdn.com/guid/cbe677ee-361e-91b4-5cae-6c4c30044743/logos/secondary_logo_on_black_color.png"
                        
                        logo_url_map[h_abbr] = h_logo
                        logo_url_map[a_abbr] = a_logo

                        state = gd.get('gameState', 'OFF')
                        mapped_state = 'in' if state in ['LIVE', 'CRIT'] else 'pre'
                        if state in ['FINAL', 'OFF']: mapped_state = 'post'
                        
                        status_disp = state
                        clock = gd.get('clock', {})
                        if state in ['PRE', 'FUT']:
                            utc_t = dt.strptime(gd['startTimeUTC'], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
                            status_disp = utc_t.astimezone(timezone(timedelta(hours=TIMEZONE_OFFSET))).strftime("%I:%M %p").lstrip('0')
                        elif state in ['LIVE', 'CRIT']:
                            per = gd.get('periodDescriptor', {}).get('number', 1)
                            rem = clock.get('timeRemaining', '00:00')
                            status_disp = f"P{per} - {rem}"
                            if clock.get('inIntermission'): status_disp = "INT"

                        sit = gd.get('situation', {})
                        sit_code = sit.get('situationCode', '1551')
                        pp = False; poss = ""
                        if len(sit_code) == 4:
                            if sit_code[1] > sit_code[2]: pp = True; poss = a_abbr
                            elif sit_code[2] > sit_code[1]: pp = True; poss = h_abbr

                        games.append({
                            'game_id': str(game['id']), 'sport': 'nhl',
                            'state': mapped_state, 'status': status_disp,
                            'away_abbr': a_abbr, 'away_score': gd['awayTeam'].get('score', 0), 'away_logo': a_logo,
                            'home_abbr': h_abbr, 'home_score': gd['homeTeam'].get('score', 0), 'home_logo': h_logo,
                            'situation': {'powerPlay': pp, 'possession': poss, 'isRedZone': False},
                            'is_shown': True
                        })
                    except: continue
        except Exception as e: print(f"NHL Fetch Error: {e}")
        return games

    # --- 3. GENERIC ESPN FETCHING ---
    def fetch_espn_generic(self, sport, date_str):
        base = f"{self.base_url}/{self.leagues[sport]['path']}/scoreboard"
        if sport == 'ncf_fbs': base += "?group=80"
        elif sport == 'ncf_fcs': base += "?group=81"
        else: base += "?"
        
        url = f"{base}&dates={date_str}"
        games = []
        
        try:
            r = requests.get(url, timeout=5)
            if r.status_code != 200: return []
            data = r.json()
            
            for event in data.get('events', []):
                status = event.get('status', {})
                state = status.get('type', {}).get('state', 'pre')
                
                comp = event['competitions'][0]
                home = next(c for c in comp['competitors'] if c['homeAway'] == 'home')
                away = next(c for c in comp['competitors'] if c['homeAway'] == 'away')
                
                h_url = home['team'].get('logo', '')
                a_url = away['team'].get('logo', '')
                h_abbr = home['team']['abbreviation']
                a_abbr = away['team']['abbreviation']
                if h_url: logo_url_map[h_abbr] = h_url
                if a_url: logo_url_map[a_abbr] = a_url
                
                # Status Text Logic
                raw_s = status.get('type', {}).get('shortDetail', 'Scheduled')
                if state == 'half': s_disp = "HALFTIME"
                elif state == 'in':
                    clock = status.get('displayClock', '')
                    per = status.get('period', 1)
                    if 'football' in sport: s_disp = f"Q{per} - {clock}" if clock else f"Q{per}"
                    else: s_disp = raw_s
                else: s_disp = raw_s.replace("Final", "FINAL").replace(" EST", "")
                
                sit = comp.get('situation', {})
                is_rz = sit.get('isRedZone', False) if state == 'in' else False
                
                games.append({
                    'game_id': event['id'], 'sport': sport,
                    'state': state, 'status': s_disp,
                    'away_abbr': a_abbr, 'away_score': int(away.get('score', 0)), 'away_logo': a_url,
                    'home_abbr': h_abbr, 'home_score': int(home.get('score', 0)), 'home_logo': h_url,
                    'situation': {
                        'possession': sit.get('possession'),
                        'downDist': sit.get('downDistanceText', ''),
                        'isRedZone': is_rz,
                        'powerPlay': sit.get('powerPlay', False),
                        'onFirst': sit.get('onFirst', False), 'onSecond': sit.get('onSecond', False), 'onThird': sit.get('onThird', False)
                    } if state == 'in' else {},
                    'is_shown': True
                })
        except Exception as e: print(f"ESPN Fetch Error {sport}: {e}")
        return games

fetcher = SportsFetcher()

def background_loop():
    # Initial Team Fetch
    fetcher.fetch_all_teams()
    
    while True:
        try:
            ticker_state.is_fetching = True
            
            # Date Calculation
            if ticker_state.settings.get('debug_mode') and ticker_state.settings.get('custom_date'):
                date_str = ticker_state.settings['custom_date'].replace('-', '')
            else:
                tz = timezone(timedelta(hours=TIMEZONE_OFFSET))
                now = dt.now(timezone.utc).astimezone(tz)
                # If it's 2 AM, show yesterday's late games. If it's 4 AM, show today's.
                if now.hour < 3: date_str = (now - timedelta(days=1)).strftime("%Y%m%d")
                else: date_str = now.strftime("%Y%m%d")

            all_games = []
            
            for sport, enabled in ticker_state.settings['active_sports'].items():
                if not enabled: continue
                
                fetched = []
                if sport == 'nhl':
                    fetched = fetcher.fetch_nhl_native(date_str)
                elif sport == 'ncf_fbs':
                    fetched = fetcher.fetch_espn_generic('ncf_fbs', date_str)
                elif sport == 'ncf_fcs':
                    fetched = fetcher.fetch_espn_generic('ncf_fcs', date_str)
                elif sport in ['nfl', 'mlb', 'nba']:
                    fetched = fetcher.fetch_espn_generic(sport, date_str)
                
                print(f"Fetched {len(fetched)} games for {sport}") # DEBUG
                all_games.extend(fetched)

            # Filtering
            mode = ticker_state.settings['mode']
            my_teams = ticker_state.settings['my_teams']
            
            for g in all_games:
                should_show = True
                if mode == 'live' and g['state'] not in ['in', 'half']: 
                    should_show = False
                elif mode == 'my_teams':
                    if not my_teams: should_show = True 
                    elif g['away_abbr'] not in my_teams and g['home_abbr'] not in my_teams:
                        should_show = False
                
                g['is_shown'] = should_show

            ticker_state.game_data = all_games
            ticker_state.last_fetch_time = time.time()
            
        except Exception as e:
            print(f"Loop Error: {e}")
        
        ticker_state.is_fetching = False
        time.sleep(UPDATE_INTERVAL)

threading.Thread(target=background_loop, daemon=True).start()

# ================= FLASK & UI =================
app = Flask(__name__)

@app.route('/')
def root(): return redirect('/control')

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
    <div class="panel" style="padding-top:5px;"> <div style="display:flex; justify-content:space-between; align-items:center; border-bottom:1px solid #333; padding-bottom:10px; margin-bottom:5px;"> <span class="section-title" style="margin:0;">Active Feed (<span id="game_count">0</span>)</span> <div style="font-size:0.7em; color:#666;">Updates every 20s</div> </div> <table class="game-table"> <thead> <tr> <th class="th-league">LGE</th> <th>Matchup</th> <th style="text-align:center;">Score</th> <th style="text-align:right;">Status</th> <th style="text-align:right;">Sit.</th> </tr> </thead> <tbody id="gameTableBody"></tbody> </table> </div>
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

@app.route('/control')
def dashboard(): return DASHBOARD_HTML

@app.route('/api/ticker')
def get_ticker():
    return jsonify({
        'games': [g for g in ticker_state.game_data if g['is_shown']],
        'meta': {'scroll_seamless': ticker_state.settings['scroll_seamless']}
    })

@app.route('/api/logo/<abbr>')
def serve_logo(abbr):
    url = logo_url_map.get(abbr)
    if not url: return Response(status=404)
    if abbr not in logo_blob_cache:
        blob = process_logo_to_rgb565(url)
        if blob: logo_blob_cache[abbr] = blob
        else: return Response(status=404)
    return send_file(io.BytesIO(logo_blob_cache[abbr]), mimetype='application/octet-stream')

@app.route('/api/all_games')
def get_all(): return jsonify({'games': ticker_state.game_data})

@app.route('/api/state')
def get_state(): return jsonify({'settings': ticker_state.settings, 'games': ticker_state.game_data})

@app.route('/api/config', methods=['POST'])
def update_config():
    ticker_state.save_config(request.json)
    threading.Thread(target=background_loop).start() # Force refresh
    return jsonify({"status": "success"})

@app.route('/api/teams')
def get_teams(): return jsonify(ticker_state.all_teams_data)

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
