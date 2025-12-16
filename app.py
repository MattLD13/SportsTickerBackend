import threading
import time
import requests
import json
from datetime import datetime as dt, timedelta
from flask import Flask, jsonify

# ================= CONFIGURATION =================
TIMEZONE_OFFSET = -5 # EST

# ================= GLOBAL STATE =================
state = {
    'current_games': [],
    'active_sports': {
        'nfl': True, 'ncf_fbs': True, 'ncf_fcs': True,
        'mlb': True, 'nhl': True, 'nba': True
    },
    'debug_mode': False,
    'custom_date': None
}

# ================= DATA FETCHER LOGIC =================
class SportsFetcher:
    def __init__(self):
        self.base_url = 'http://site.api.espn.com/apis/site/v2/sports/'
        self.leagues = {
            'nfl': 'football/nfl',
            'ncf_fbs': 'football/college-football', # Special logic needed for groups in real app, simplified here
            'mlb': 'baseball/mlb',
            'nhl': 'hockey/nhl',
            'nba': 'basketball/nba'
        }

    def analyze_nhl_power_play(self, game_id, current_period, current_clock_str, home_id, away_id, home_abbr, away_abbr):
        """ Scans play-by-play data to find active penalties """
        try:
            url = f"https://site.api.espn.com/apis/site/v2/sports/hockey/nhl/playbyplay?event={game_id}"
            r = requests.get(url, timeout=2)
            pbp = r.json()
            
            def get_seconds_elapsed(period, clock_str):
                parts = clock_str.split(':')
                remaining_seconds = int(parts[0]) * 60 + int(parts[1])
                period_length = 300 if period > 3 else 1200
                elapsed_in_period = period_length - remaining_seconds
                return ((period - 1) * 1200) + elapsed_in_period

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
                            p_per = play['period']['number']
                            p_clk = play['clock']['displayValue']
                            start_time = get_seconds_elapsed(p_per, p_clk)
                            if (start_time + duration) > current_total:
                                team = play.get('team', {})
                                tid = team.get('id')
                                if not tid:
                                    if home_abbr.lower() in text: tid = home_id
                                    elif away_abbr.lower() in text: tid = away_id
                                if tid and tid in active_penalties:
                                    active_penalties[tid] += 1
                        except: continue

            if active_penalties.get(home_id, 0) > active_penalties.get(away_id, 0):
                return {'powerPlay': True, 'possession': away_id}
            elif active_penalties.get(away_id, 0) > active_penalties.get(home_id, 0):
                return {'powerPlay': True, 'possession': home_id}
            
            return {'powerPlay': False}
        except: return {'powerPlay': False}

    def get_games(self):
        games_list = []
        # Simplified date logic for server environment
        target_date = (dt.utcnow() + timedelta(hours=TIMEZONE_OFFSET)).strftime("%Y-%m-%d")
        
        for league_key, path in self.leagues.items():
            try:
                # Basic Scoreboard Fetch
                url = f"{self.base_url}{path}/scoreboard"
                params = {'limit': 100}
                if league_key == 'ncf_fbs': params['groups'] = '80'
                
                r = requests.get(url, params=params, timeout=3)
                data = r.json()
                
                for event in data.get('events', []):
                    status_state = event['status']['type']['state']
                    # Filter: Only Live games OR games today
                    game_date = event['date'][:10]
                    if status_state != 'in' and game_date != target_date: continue

                    comp = event['competitions'][0]
                    home = comp['competitors'][0]
                    away = comp['competitors'][1]
                    
                    game_obj = {
                        'sport': league_key,
                        'id': event['id'],
                        'status': event['status']['type']['shortDetail'].replace(" EST","").replace(" EDT","").replace("Final","FINAL"),
                        'state': status_state,
                        'h_abbr': home['team']['abbreviation'],
                        'h_score': home.get('score', '0'),
                        'a_abbr': away['team']['abbreviation'],
                        'a_score': away.get('score', '0'),
                        'sit': "",
                        'sit_color': "#FFFFFF", # Default White
                        'poss': ""
                    }

                    # --- SITUATION LOGIC ---
                    if status_state == 'in':
                        sit = comp.get('situation', {})
                        
                        # Football Logic
                        if 'football' in path:
                            game_obj['sit'] = sit.get('downDistanceText', '')
                            game_obj['sit_color'] = "#00FF00" # Bright Green for Downs
                            if sit.get('isRedZone'):
                                game_obj['sit_color'] = "#FF0000" # Red for RedZone (Handled by border in ESP32, but useful here)
                                game_obj['is_rz'] = True
                            game_obj['poss'] = sit.get('possession', '')

                        # NHL Logic
                        elif league_key == 'nhl':
                            try:
                                h_id = home['id']
                                a_id = away['id']
                                curr_per = event['status']['period']
                                curr_clk = event['status']['displayClock']
                                
                                pp_data = self.analyze_nhl_power_play(
                                    game_obj['id'], curr_per, curr_clk, 
                                    h_id, a_id, game_obj['h_abbr'], game_obj['a_abbr']
                                )
                                
                                if pp_data['powerPlay']:
                                    game_obj['sit'] = "PP"
                                    game_obj['sit_color'] = "#FFFF00" # Yellow
                                    game_obj['poss'] = pp_data['possession']
                            except: pass

                    games_list.append(game_obj)
            except: continue
        return games_list

# ================= FLASK SERVER =================
app = Flask(__name__)
fetcher = SportsFetcher()

def background_loop():
    while True:
        try:
            state['current_games'] = fetcher.get_games()
        except: pass
        time.sleep(10) # Refresh every 10s

# Start background thread
t = threading.Thread(target=background_loop)
t.daemon = True
t.start()

@app.route('/')
def home():
    return "Sports Ticker Server is Running."

@app.route('/esp32')
def esp32_api():
    """ Optimized JSON for ESP32 """
    return jsonify({"games": state['current_games']})

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=5000)