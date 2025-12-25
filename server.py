import time
import threading
import json
import os
import subprocess
from datetime import datetime as dt
from flask import Flask, jsonify

# ================= CONFIGURATION =================
# DYNAMIC PORT ASSIGNMENT (Required for Railway)
PORT = int(os.environ.get("PORT", 5000))

UPDATE_INTERVAL = 5
FANTASY_FILE = "fantasy_output.json"
DEBUG_FILE = "fantasy_debug.json"
data_lock = threading.Lock()

state = { 'active_sports': { 'fantasy': True }, 'current_games': [] }

class SportsFetcher:
    def get_real_games(self):
        games = []
        if state['active_sports'].get('fantasy'):
            if os.path.exists(FANTASY_FILE):
                try: 
                    with open(FANTASY_FILE, 'r') as f: 
                        content = f.read().strip()
                        if content: games.extend(json.loads(content))
                except (json.JSONDecodeError, ValueError): pass
                except: pass
        with data_lock: state['current_games'] = games

fetcher = SportsFetcher()

def background_updater():
    # Kill old instances (Linux/Mac only)
    try: subprocess.run(["pkill", "-f", "fantasy_oddsmaker.py"], capture_output=True)
    except: pass
    
    # Launch Oddsmaker
    print("Launching Oddsmaker Engine...")
    subprocess.Popen(["python", "fantasy_oddsmaker.py"])
    
    while True:
        fetcher.get_real_games()
        time.sleep(UPDATE_INTERVAL)

app = Flask(__name__)

@app.route('/')
def root(): return "<a href='/fantasy'>Fantasy Dashboard</a> | <a href='/api/ticker'>JSON API</a>"

@app.route('/fantasy')
def fantasy_dashboard():
    data = []
    # Robust read to avoid crashes
    if os.path.exists(DEBUG_FILE):
        try:
            with open(DEBUG_FILE, 'r') as f:
                content = f.read().strip()
                if content: data = json.loads(content)
        except: return "<meta http-equiv='refresh' content='2'><h3>Syncing Data...</h3>"
    
    if not data: return "<meta http-equiv='refresh' content='5'><h3>Waiting for Data...</h3>"

    html = """<html><head><meta http-equiv="refresh" content="30"><style>
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
                l_sum += p['league_proj']; m_sum += p['my_proj']
                cls = "good" if p['my_proj'] > p['league_proj'] else "bad"
                src = "src-v" if "Vegas" in p['source'] else ""
                html += f"<tr><td>{p['name']}</td><td>{p['pos']}</td><td>{p['league_proj']:.2f}</td><td class='{cls}'>{p['my_proj']:.2f}</td><td><span class='{src}'>{p['source']}</span></td></tr>"
            d = m_sum - l_sum; dc = "#40c057" if d > 0 else "#ff6b6b"
            html += f"<tr class='total'><td>TOTAL</td><td></td><td>{l_sum:.2f}</td><td style='color:{dc}'>{m_sum:.2f} ({d:+.2f})</td><td></td></tr></tbody></table>"
        html += "</div>"
    return html + "</body></html>"

@app.route('/api/ticker')
def api_ticker():
    with data_lock: 
        # Return proper JSON structure for the app
        return jsonify({'games': state['current_games']})

if __name__ == "__main__":
    threading.Thread(target=background_updater, daemon=True).start()
    
    # CRITICAL: BIND TO 0.0.0.0 AND THE PORT RAILWAY GIVES
    print(f"Starting server on port {PORT}")
    app.run(host='0.0.0.0', port=PORT, debug=False)
