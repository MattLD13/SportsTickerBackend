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
        # DEBUG OVERRIDES
        if state['debug_mode']:
            if state['custom_date'] == 'TEST_PP':
                return [{ "sport": "nhl", "id": "test_pp", "status": "P2 14:20", "state": "in", "home_abbr": "NYR", "home_id": "h", "home_score": "3", "home_logo": "", "away_abbr": "BOS", "away_id": "a", "away_score": "2", "away_logo": "", "situation": {"powerPlay": True, "possession": "a"} }]
            if state['custom_date'] == 'TEST_RZ':
                return [{ "sport": "nfl", "id": "test_rz", "status": "3rd 4:20", "state": "in", "home_abbr": "KC", "home_id": "h", "home_score": "21", "home_logo": "", "away_abbr": "BUF", "away_id": "a", "away_score": "17", "away_logo": "", "situation": {"isRedZone": True, "downDist": "2nd & 5", "possession": "a"} }]

        games = []
        
        # Calculate "Today" in Local Time (EST)
        local_now = dt.utcnow() + timedelta(hours=TIMEZONE_OFFSET)
        today_str = local_now.strftime("%Y-%m-%d")
        
        # Determine Target Date (Debug Mode or Today)
        target_date = state['custom_date'] if (state['debug_mode'] and state['custom_date']) else today_str
        is_history = (state['debug_mode'] and state['custom_date'])

        for league_key, config in self.leagues.items():
            if not state['active_sports'].get(league_key, False): continue 
            try:
                params = config['scoreboard_params'].copy()
                if is_history: params['dates'] = target_date.replace('-', '')
                
                # Fetch Scoreboard
                r = requests.get(f"{self.base_url}{config['path']}/scoreboard", params=params, timeout=3)
                data = r.json()
                
                for event in data.get('events', []):
                    status = event['status']['type']['state']
                    
                    # --- TIMEZONE FIX ---
                    # Convert ESPN UTC string (2023-10-27T23:00Z) to Local Datetime object
                    utc_str = event['date'].replace('Z', '')
                    game_local_dt = dt.fromisoformat(utc_str) + timedelta(hours=TIMEZONE_OFFSET)
                    game_local_date = game_local_dt.strftime("%Y-%m-%d")

                    # Filter Logic:
                    # 1. If History Mode: Date must match target.
                    # 2. If Live Mode: Include if game is LIVE ('in') OR if game is TODAY (in local time).
                    if is_history:
                        if game_local_date != target_date: continue
                    else:
                        is_today = (game_local_date == today_str)
                        is_live = (status == 'in')
                        if not (is_today or is_live): continue

                    # Process Game Data
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

# ================= FLASK SERVER =================
app = Flask(__name__)

def run_fetcher():
    while True:
        try: state['current_games'] = fetcher.get_real_games()
        except: pass
        time.sleep(10)

t = threading.Thread(target=run_fetcher)
t.daemon = True
t.start()

@app.route('/')
def index(): return "Sports Ticker Data Server (Timezone Fixed)"

@app.route('/client_data')
def get_client_data():
    return jsonify({ 'games': state['current_games'], 'settings': state })

@app.route('/set_config', methods=['POST'])
def set_config():
    d = request.json
    if 'mode' in d: state['mode'] = d['mode']
    if 'active_sports' in d: state['active_sports'] = d['active_sports']
    if 'my_teams' in d: state['my_teams'] = d['my_teams']
    return "OK"

@app.route('/toggle_debug')
def toggle_debug():
    state['debug_mode'] = not state['debug_mode']
    return jsonify({'status': state['debug_mode']})

@app.route('/set_custom_date', methods=['POST'])
def set_custom_date():
    state['custom_date'] = request.json.get('date')
    return "OK"

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 5000)))
