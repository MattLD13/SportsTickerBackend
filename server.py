import time
import threading
import json
import os
import subprocess
from datetime import datetime as dt, timedelta
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

def background_updater():
    # Only start if not already running to avoid duplicates
    subprocess.Popen(["python", "fantasy_oddsmaker.py"])
    while True: 
        # Simple Loop to reload fantasy data into state
        games = []
        if state['active_sports'].get('fantasy'):
            if os.path.exists(FANTASY_FILE):
                try:
                    with open(FANTASY_FILE, 'r') as f: games = json.load(f)
                except: pass
        with data_lock: state['current_games'] = games
        time.sleep(UPDATE_INTERVAL)

app = Flask(__name__)

@app.route('/')
def root():
    return '<a href="/fantasy">Fantasy Dashboard</a> | <a href="/api/ticker">JSON API</a>'

@app.route('/fantasy')
def fantasy_dashboard():
    # Robust File Reading
    data = []
    if os.path.exists(DEBUG_FILE):
        try:
            with open(DEBUG_FILE, 'r') as f: data = json.load(f)
        except: return "<h3>Loading Data... (Try refreshing in 10s)</h3>"
    
    if not data: return "<h3>Waiting for Odds Data...</h3>"

    html = """<html><head><title>Fantasy Odds</title>
    <style>
        body{font-family:sans-serif;background:#121212;color:#eee;padding:20px}
        .matchup{background:#1e1e1e;padding:20px;border-radius:10px;margin-bottom:20px}
        h2{color:#4dabf7;border-bottom:1px solid #333;padding-bottom:10px}
        h3{color:#bbb; margin-top:20px; border-bottom:1px solid #444; display:inline-block}
        table{width:100%;border-collapse:collapse;margin-top:5px; margin-bottom:15px}
        th{text-align:left;color:#888;font-size:12px;padding:8px;background:#252525}
        td{padding:8px;border-bottom:1px solid #333}
        .pos{color:#666;font-size:12px}
        .source-vegas{color:#40c057;font-weight:bold}
        .source-fallback{color:#fab005;font-style:italic}
        .total-row td{font-weight:bold; background:#2a2a2a; border-top:2px solid #555; color:#fff}
        .my-proj-better{color:#40c057} .my-proj-worse{color:#ff6b6b}
    </style></head><body>"""
    
    for game in data:
        html += f"<div class='matchup'><h2>{game.get('platform','FANTASY')}: {game.get('home_team','Home')} vs {game.get('away_team','Away')}</h2>"
        
        home_players = [p for p in game['players'] if p['team'] == 'HOME']
        away_players = [p for p in game['players'] if p['team'] == 'AWAY']
        
        def render_table(team, players):
            tbl = f"<h3>{team}</h3><table><thead><tr><th>PLAYER</th><th>POS</th><th>LEAGUE</th><th>MY PROJ</th><th>SOURCE</th></tr></thead><tbody>"
            l_sum = 0; m_sum = 0
            for p in players:
                l_sum += p['league_proj']; m_sum += p['my_proj']
                src_cls = "source-vegas" if p['source'] == "Vegas" else "source-fallback"
                val_cls = "my-proj-better" if p['my_proj'] > p['league_proj'] else "my-proj-worse"
                tbl += f"<tr><td>{p['name']}</td><td class='pos'>{p['pos']}</td><td>{p['league_proj']}</td><td class='{val_cls}'>{p['my_proj']}</td><td class='{src_cls}'>{p['source']}</td></tr>"
            tbl += f"<tr class='total-row'><td>TOTAL</td><td></td><td>{l_sum:.2f}</td><td>{m_sum:.2f}</td><td></td></tr></tbody></table>"
            return tbl

        html += render_table("Home", home_players)
        html += render_table("Away", away_players)
        html += "</div>"
    
    return html + "</body></html>"

@app.route('/api/ticker')
def api_ticker():
    with data_lock: 
        games = state['current_games']
        return jsonify({'games': games})

if __name__ == "__main__":
    threading.Thread(target=background_updater, daemon=True).start()
    app.run(host='0.0.0.0', port=5000)
