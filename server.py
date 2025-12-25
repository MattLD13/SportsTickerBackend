import time
import threading
import json
import os
import subprocess
import requests
from datetime import datetime as dt
from flask import Flask, jsonify, request

DEFAULT_OFFSET = -4 
CONFIG_FILE = "ticker_config.json"
UPDATE_INTERVAL = 5
FANTASY_FILE = "fantasy_output.json"
DEBUG_FILE = "fantasy_debug.json"
data_lock = threading.Lock()

state = {
    'active_sports': { 'nfl': True, 'ncf_fbs': True, 'ncf_fcs': True, 'mlb': True, 'nhl': True, 'nba': True, 'weather': False, 'clock': False, 'fantasy': True },
    'mode': 'all', 'scroll_seamless': False, 'my_teams': [], 'current_games': [], 
    'brightness': 0.5, 'inverted': False, 'panel_count': 2, 'weather_location': "New York"
}

class SportsFetcher:
    def get_real_games(self):
        games = []
        if state['active_sports'].get('fantasy'):
            if os.path.exists(FANTASY_FILE):
                try: 
                    with open(FANTASY_FILE, 'r') as f: 
                        content = f.read().strip()
                        if content: games.extend(json.loads(content))
                except json.JSONDecodeError: pass # Ignored corrupt reads
                except: pass
        with data_lock: state['current_games'] = games

fetcher = SportsFetcher()

def background_updater():
    try: subprocess.run(["pkill", "-f", "fantasy_oddsmaker.py"], capture_output=True)
    except: pass
    subprocess.Popen(["python", "fantasy_oddsmaker.py"])
    while True: fetcher.get_real_games(); time.sleep(UPDATE_INTERVAL)

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

    html = """<html><head><meta http-equiv="refresh" content="30"><style>
        body{font-family:sans-serif;background:#121212;color:#eee;padding:20px}
        .matchup{background:#1e1e1e;padding:20px;border-radius:10px;margin-bottom:20px}
        h2{color:#4dabf7;border-bottom:1px solid #333;padding-bottom:10px}
        table{width:100%;border-collapse:collapse;margin-top:10px}
        th{text-align:left;color:#888;font-size:12px;padding:8px;background:#252525}
        td{padding:8px;border-bottom:1px solid #333}
        .source-vegas{color:#40c057;font-weight:bold}
        .total-row td{font-weight:bold; background:#2a2a2a; border-top:2px solid #555}
        .better{color:#40c057} .worse{color:#ff6b6b}
    </style></head><body>"""
    
    for game in data:
        html += f"<div class='matchup'><h2>{game.get('platform','FANTASY')}</h2>"
        for team_type in ['HOME', 'AWAY']:
            players = [p for p in game['players'] if p['team'] == team_type]
            if not players: continue
            team_name = game.get('home_team' if team_type == 'HOME' else 'away_team', team_type)
            html += f"<h3>{team_name}</h3><table><thead><tr><th>PLAYER</th><th>POS</th><th>LEAGUE</th><th>MY PROJ</th><th>SOURCE</th></tr></thead><tbody>"
            l_sum = 0; m_sum = 0
            for p in players:
                l_sum += p['league_proj']; m_sum += p['my_proj']
                cls = "better" if p['my_proj'] > p['league_proj'] else "worse"
                src = "source-vegas" if "Vegas" in p['source'] else ""
                html += f"<tr><td>{p['name']}</td><td>{p['pos']}</td><td>{p['league_proj']}</td><td class='{cls}'>{p['my_proj']}</td><td class='{src}'>{p['source']}</td></tr>"
            html += f"<tr class='total-row'><td>TOTAL</td><td></td><td>{l_sum:.2f}</td><td>{m_sum:.2f}</td><td></td></tr></tbody></table>"
        html += "</div>"
    return html + "</body></html>"

@app.route('/api/ticker')
def api_ticker():
    with data_lock: return jsonify({'games': state['current_games']})

if __name__ == "__main__":
    threading.Thread(target=background_updater, daemon=True).start()
    app.run(host='0.0.0.0', port=5000)
