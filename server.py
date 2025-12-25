import time
import threading
import json
import os
import subprocess
import requests
from datetime import datetime as dt, timedelta
from flask import Flask, jsonify, request

# ================= CONFIGURATION =================
DEFAULT_OFFSET = -4 
CONFIG_FILE = "ticker_config.json"
UPDATE_INTERVAL = 5
FANTASY_FILE = "fantasy_output.json"
DEBUG_FILE = "fantasy_debug.json"
data_lock = threading.Lock()

# INITIAL STATE
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
                except: pass
        
        with data_lock: state['current_games'] = games

fetcher = SportsFetcher()

def background_updater():
    # Attempt to kill old instances (Linux/Mac only)
    try: subprocess.run(["pkill", "-f", "fantasy_oddsmaker.py"], capture_output=True)
    except: pass

    print("🚀 Starting Fantasy Oddsmaker Background Process...")
    # Launch the oddsmaker. Ensure 'fantasy_oddsmaker.py' is in the same folder.
    subprocess.Popen(["python", "fantasy_oddsmaker.py"])
    
    while True:
        fetcher.get_real_games()
        time.sleep(UPDATE_INTERVAL)

app = Flask(__name__)

@app.route('/')
def root():
    return """
    <html><body style='background:#111;color:#eee;font-family:sans-serif;padding:2rem'>
    <h1>Ticker Online</h1>
    <p>The backend is running successfully.</p>
    <ul>
        <li><a style='color:#4dabf7' href='/fantasy'>Fantasy Dashboard (Analytics)</a></li>
        <li><a style='color:#4dabf7' href='/api/ticker'>JSON Output (For Matrix)</a></li>
    </ul>
    </body></html>
    """

@app.route('/fantasy')
def fantasy_dashboard():
    data = []
    
    # --- ROBUST FILE READING (Prevents 502) ---
    if os.path.exists(DEBUG_FILE):
        try:
            with open(DEBUG_FILE, 'r') as f:
                content = f.read().strip()
                if content:
                    data = json.loads(content)
        except Exception as e:
            # Return a valid HTML page even on error so the browser retries
            return f"""
            <html><head><meta http-equiv="refresh" content="5"></head>
            <body style='background:#121212;color:white;font-family:sans-serif;padding:20px'>
            <h3>Data Syncing...</h3>
            <p>The oddsmaker is writing to the database. Retrying in 5 seconds...</p>
            <p style='color:#555;font-size:12px'>Error details: {str(e)}</p>
            </body></html>
            """
    else:
        return """
        <html><head><meta http-equiv="refresh" content="5"></head>
        <body style='background:#121212;color:white;font-family:sans-serif;padding:20px'>
        <h3>Initializing...</h3>
        <p>Waiting for the Oddsmaker to generate the first batch of data.</p>
        </body></html>
        """
    
    if not data or not isinstance(data, list): 
        return """<html><head><meta http-equiv="refresh" content="5"></head>
        <body style='background:#121212;color:white;font-family:sans-serif;padding:20px'>
        <h3>Loading...</h3></body></html>"""

    # --- HTML RENDERING ---
    html = """<html><head><title>Fantasy Odds</title>
    <meta http-equiv="refresh" content="30">
    <style>
        body{font-family:sans-serif;background:#121212;color:#eee;padding:20px}
        .matchup{background:#1e1e1e;padding:20px;border-radius:10px;margin-bottom:20px; border:1px solid #333}
        h2{color:#4dabf7;border-bottom:1px solid #333;padding-bottom:10px; margin-top:0}
        h3{color:#bbb; margin-top:20px; border-bottom:1px solid #444; display:inline-block; font-size:1.1rem}
        table{width:100%;border-collapse:collapse;margin-top:5px; margin-bottom:15px; font-size:14px}
        th{text-align:left;color:#888;font-size:12px;padding:8px;background:#252525; text-transform:uppercase}
        td{padding:8px;border-bottom:1px solid #333}
        .pos{color:#666;font-size:11px; font-weight:bold}
        .source-vegas{color:#40c057;font-weight:bold; background:rgba(64, 192, 87, 0.1); padding:2px 6px; border-radius:4px}
        .source-fallback{color:#fab005;font-style:italic; font-size:12px}
        .total-row td{font-weight:bold; background:#2a2a2a; border-top:2px solid #555; color:#fff; font-size:15px}
        .my-proj-better{color:#40c057; font-weight:bold} 
        .my-proj-worse{color:#ff6b6b}
        .timestamp{color:#555; font-size:12px; margin-bottom:20px; text-align:right}
    </style></head><body>
    <div class="timestamp">Last Updated: """ + dt.now().strftime("%I:%M:%S %p") + """</div>"""
    
    for game in data:
        home_team = game.get('home_team', 'Home')
        away_team = game.get('away_team', 'Away')
        platform = game.get('platform', 'FANTASY')
        
        html += f"<div class='matchup'><h2>{platform}: {home_team} vs {away_team}</h2>"
        
        all_players = game.get('players', [])
        home_players = [p for p in all_players if p.get('team') == 'HOME']
        away_players = [p for p in all_players if p.get('team') == 'AWAY']
        
        def render_table(team_name, players):
            if not players: return f"<h3>{team_name}</h3><p>No roster data found.</p>"
            
            tbl = f"<h3>{team_name}</h3><table><thead><tr><th width='30%'>PLAYER</th><th width='10%'>POS</th><th width='20%'>LEAGUE</th><th width='20%'>MY PROJ</th><th width='20%'>SOURCE</th></tr></thead><tbody>"
            l_sum = 0; m_sum = 0
            
            for p in players:
                l_proj = p.get('league_proj', 0)
                m_proj = p.get('my_proj', 0)
                l_sum += l_proj; m_sum += m_proj
                
                src = p.get('source', 'Unknown')
                src_cls = "source-vegas" if "Vegas" in src else "source-fallback"
                val_cls = "my-proj-better" if m_proj > l_proj else "my-proj-worse"
                
                tbl += f"<tr><td>{p.get('name','Unknown')}</td><td class='pos'>{p.get('pos','')}</td><td>{l_proj:.2f}</td><td class='{val_cls}'>{m_proj:.2f}</td><td><span class='{src_cls}'>{src}</span></td></tr>"
            
            diff = m_sum - l_sum
            diff_color = "#40c057" if diff > 0 else "#ff6b6b"
            diff_str = f"(+{diff:.2f})" if diff > 0 else f"({diff:.2f})"
            
            tbl += f"<tr class='total-row'><td>TOTAL</td><td></td><td>{l_sum:.2f}</td><td style='color:{diff_color}'>{m_sum:.2f} <span style='font-size:11px;opacity:0.8'>{diff_str}</span></td><td></td></tr></tbody></table>"
            return tbl

        html += render_table(home_team, home_players)
        html += render_table(away_team, away_players)
        html += "</div>"
    
    return html + "</body></html>"

@app.route('/api/ticker')
def api_ticker():
    with data_lock: 
        return jsonify({'games': state['current_games']})

if __name__ == "__main__":
    threading.Thread(target=background_updater, daemon=True).start()
    app.run(host='0.0.0.0', port=5000, debug=False)
