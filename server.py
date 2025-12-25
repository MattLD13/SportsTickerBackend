import time
import threading
import json
import os
import subprocess
import requests
import re
from datetime import datetime as dt, timezone, timedelta
from flask import Flask, jsonify

# ================= CONFIGURATION =================
# DYNAMIC PORT ASSIGNMENT (Required for Railway)
PORT = int(os.environ.get("PORT", 5000))
DEFAULT_OFFSET = -4 

UPDATE_INTERVAL = 5
FANTASY_FILE = "fantasy_output.json"
DEBUG_FILE = "fantasy_debug.json"
data_lock = threading.Lock()

# STATE
state = {
    'active_sports': { 'nfl': True, 'ncf_fbs': True, 'ncf_fcs': True, 'mlb': True, 'nhl': True, 'nba': True, 'weather': False, 'clock': False, 'fantasy': True },
    'mode': 'all', 'scroll_seamless': False, 'my_teams': [], 'current_games': [], 
    'brightness': 0.5, 'inverted': False, 'panel_count': 2, 'weather_location': "New York"
}

# ================= FETCHING LOGIC =================
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
    "Cache-Control": "no-cache"
}

class SportsFetcher:
    def __init__(self):
        self.base_url = 'http://site.api.espn.com/apis/site/v2/sports/'
        self.leagues = {
            'nfl': 'football/nfl',
            'ncf_fbs': 'football/college-football',
            'nba': 'basketball/nba',
            'mlb': 'baseball/mlb',
            'nhl': 'hockey/nhl'
        }

    def get_real_games(self):
        games = []
        
        # 1. LOAD FANTASY DATA
        if state['active_sports'].get('fantasy'):
            if os.path.exists(FANTASY_FILE):
                try: 
                    with open(FANTASY_FILE, 'r') as f: 
                        content = f.read().strip()
                        if content: games.extend(json.loads(content))
                except (json.JSONDecodeError, ValueError): pass
                except: pass

        # 2. FETCH REAL SPORTS
        # We fetch today's games based on server time
        now = dt.now(timezone(timedelta(hours=DEFAULT_OFFSET)))
        # If it's early morning (before 4AM), look at "yesterday" for late games
        if now.hour < 4: query_date = now - timedelta(days=1)
        else: query_date = now
        date_str = query_date.strftime("%Y%m%d")
        
        for league, path in self.leagues.items():
            if not state['active_sports'].get(league, False): continue
            
            try:
                url = f"{self.base_url}{path}/scoreboard?dates={date_str}&limit=100"
                if 'college' in path: url += "&groups=80" # Top 25/FBS only
                
                r = requests.get(url, headers=HEADERS, timeout=4)
                if r.status_code == 200:
                    data = r.json()
                    for e in data.get('events', []):
                        st = e.get('status', {})
                        state_str = st.get('type', {}).get('state', 'pre')
                        
                        # Filter: Show Live, Completed (Today), or Pre (Today)
                        if state_str == 'pre' and 'TBD' in st.get('type', {}).get('shortDetail', ''): continue

                        # Parse Score
                        comp = e['competitions'][0]
                        h = comp['competitors'][0]
                        a = comp['competitors'][1]
                        
                        game_obj = {
                            "sport": league,
                            "id": e['id'],
                            "status": st.get('type', {}).get('shortDetail', ''),
                            "home_abbr": h['team']['abbreviation'],
                            "home_score": h.get('score', '0'),
                            "home_logo": h['team'].get('logo', ''),
                            "away_abbr": a['team']['abbreviation'],
                            "away_score": a.get('score', '0'),
                            "away_logo": a['team'].get('logo', ''),
                            "is_shown": True
                        }
                        games.append(game_obj)
            except: pass

        with data_lock: state['current_games'] = games

fetcher = SportsFetcher()

def background_updater():
    # Kill old instances
    try: subprocess.run(["pkill", "-f", "fantasy_oddsmaker.py"], capture_output=True)
    except: pass
    
    # Launch Oddsmaker
    print("Launching Oddsmaker Engine...")
    subprocess.Popen(["python", "fantasy_oddsmaker.py"])
    
    while True:
        fetcher.get_real_games()
        time.sleep(UPDATE_INTERVAL)

# ================= FLASK SERVER =================
app = Flask(__name__)

@app.route('/')
def root(): return "<a href='/fantasy'>Fantasy Dashboard</a> | <a href='/api/ticker'>JSON API</a>"

@app.route('/fantasy')
def fantasy_dashboard():
    data = []
    if os.path.exists(DEBUG_FILE):
        try:
            with open(DEBUG_FILE, 'r') as f:
                content = f.read().strip()
                if content: data = json.loads(content)
        except: return "<meta http-equiv='refresh' content='2'><h3>Syncing Data...</h3>"
    
    if not data: return "<meta http-equiv='refresh' content='5'><h3>Waiting for Data...</h3>"

    html = """<html><head><title>Fantasy Odds</title>
    <meta http-equiv="refresh" content="30">
    <style>
        body{font-family:sans-serif;background:#121212;color:#eee;padding:20px}
        .matchup{background:#1e1e1e;padding:20px;border-radius:10px;margin-bottom:20px}
        h2{color:#4dabf7;border-bottom:1px solid #333;padding-bottom:10px}
        table{width:100%;border-collapse:collapse;margin-top:10px}
        th{text-align:left;color:#888;font-size:12px;padding:8px;background:#252525}
        td{padding:8px;border-bottom:1px solid #333}
        .src-v{color:#40c057;font-weight:bold; background:rgba(64,192,87,0.1); padding:2px 6px; border-radius:4px}
        .total{font-weight:bold; background:#2a2a2a; border-top:2px solid #555}
        .good{color:#40c057; font-weight:bold} .bad{color:#ff6b6b}
    </style></head><body>"""
    
    for g in data:
        html += f"<div class='matchup'><h2>{g.get('platform','FANTASY')}</h2>"
        for team_type in ['HOME', 'AWAY']:
            players = [p for p in g['players'] if p['team'] == team_type]
            tm = g.get('home_team' if team_type=='HOME' else 'away_team', team_type)
            
            html += f"<h3>{tm}</h3><table><thead><tr><th>PLAYER</th><th>POS</th><th>LEAGUE</th><th>MY PROJ</th><th>SOURCE</th></tr></thead><tbody>"
            l_sum = 0; m_sum = 0
            for p in players:
                l_proj = p.get('league_proj', 0)
                m_proj = p.get('my_proj', 0)
                l_sum += l_proj; m_sum += m_proj
                
                cls = "good" if m_proj > l_proj else "bad"
                src = "src-v" if "Vegas" in p['source'] else ""
                html += f"<tr><td>{p['name']}</td><td>{p['pos']}</td><td>{l_proj:.2f}</td><td class='{cls}'>{m_proj:.2f}</td><td><span class='{src}'>{p['source']}</span></td></tr>"
            
            d = m_sum - l_sum; dc = "#40c057" if d > 0 else "#ff6b6b"
            html += f"<tr class='total'><td>TOTAL</td><td></td><td>{l_sum:.2f}</td><td style='color:{dc}'>{m_sum:.2f} ({d:+.2f})</td><td></td></tr></tbody></table>"
        html += "</div>"
    return html + "</body></html>"

@app.route('/api/ticker')
def api_ticker():
    with data_lock: 
        # Return object wrapper 'games'
        return jsonify({'games': state['current_games']})

if __name__ == "__main__":
    threading.Thread(target=background_updater, daemon=True).start()
    
    print(f"Server starting on port {PORT}")
    app.run(host='0.0.0.0', port=PORT, debug=False)
