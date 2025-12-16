import sys, time, threading, io, json, os, requests
from datetime import datetime as dt, timedelta
from flask import Flask, jsonify, request
from PIL import Image, ImageDraw, ImageFont

# CONFIGURATION
TIMEZONE_OFFSET = -5
CONFIG_FILE = "ticker_config.json"

# STATE
state = {
    'active_sports': { 'nfl': True, 'ncf_fbs': True, 'ncf_fcs': True, 'mlb': True, 'nhl': True, 'nba': True },
    'mode': 'all', 'my_teams': [], 'current_games': [],
    'all_teams_data': {}, 'debug_mode': False, 'custom_date': None,
    'resolution': {'w': 64, 'h': 32} 
}

# FETCHING ENGINE
class SportsFetcher:
    def __init__(self):
        self.base_url = 'http://site.api.espn.com/apis/site/v2/sports/'
        self.leagues = {
            'nfl': {'path': 'football/nfl', 'scoreboard_params': {}},
            'ncf_fbs': {'path': 'football/college-football', 'scoreboard_params': {'groups': '80', 'limit': 100}},
            'ncf_fcs': {'path': 'football/college-football', 'scoreboard_params': {'groups': '81', 'limit': 100}},
            'mlb': {'path': 'baseball/mlb', 'scoreboard_params': {}},
            'nhl': {'path': 'hockey/nhl', 'scoreboard_params': {}},
            'nba': {'path': 'basketball/nba', 'scoreboard_params': {}}
        }

    def analyze_nhl_pp(self, game_id, curr_p, curr_c, h_id, a_id, h_abbr, a_abbr):
        try:
            r = requests.get(f"https://site.api.espn.com/apis/site/v2/sports/hockey/nhl/playbyplay?event={game_id}", timeout=2)
            pbp = r.json()
            def parse_time(p, c): parts=c.split(':'); return ((p-1)*1200) + (1200-(int(parts[0])*60+int(parts[1])))
            try: curr_sec = parse_time(curr_p, curr_c)
            except: return {'powerPlay': False}
            
            penalties = {h_id: 0, a_id: 0}
            for play in pbp.get('plays', []):
                txt = play.get('text', '').lower()
                if 'penalty' in txt and 'shot' not in txt:
                    if 'misconduct' in txt and 'game' not in txt: continue
                    dur = 300 if 'major' in txt else (240 if 'double' in txt else 120)
                    try:
                        start = parse_time(play['period']['number'], play['clock']['displayValue'])
                        if start + dur > curr_sec:
                            tid = play.get('team', {}).get('id')
                            if not tid:
                                if h_abbr.lower() in txt: tid = h_id
                                elif a_abbr.lower() in txt: tid = a_id
                            if tid in penalties: penalties[tid] += 1
                    except: continue
            
            if penalties[h_id] > penalties[a_id]: return {'powerPlay': True, 'possession': a_id}
            elif penalties[a_id] > penalties[h_id]: return {'powerPlay': True, 'possession': h_id}
            return {'powerPlay': False}
        except: return {'powerPlay': False}

    def fetch_games(self):
        if state['debug_mode']:
            if state['custom_date'] == 'TEST_PP': return [{"sport": "nhl", "id": "test", "status": "P2 14:00", "state": "in", "home_abbr": "NYR", "home_score": "3", "home_id": "h", "away_abbr": "BOS", "away_score": "2", "away_id": "a", "home_logo": "", "away_logo": "", "situation": {"powerPlay": True, "possession": "a"}}]
            if state['custom_date'] == 'TEST_RZ': return [{"sport": "nfl", "id": "test", "status": "3rd 4:00", "state": "in", "home_abbr": "KC", "home_score": "21", "home_id": "h", "away_abbr": "BUF", "away_score": "17", "away_id": "a", "home_logo": "", "away_logo": "", "situation": {"isRedZone": True, "downDist": "2nd & 5"}}]

        games = []
        today = (dt.utcnow() + timedelta(hours=TIMEZONE_OFFSET)).strftime("%Y-%m-%d")
        target_date = state['custom_date'] if (state['debug_mode'] and state['custom_date']) else today
        
        for league, cfg in self.leagues.items():
            if not state['active_sports'].get(league, False): continue
            try:
                params = cfg['scoreboard_params'].copy()
                if state['debug_mode']: params['dates'] = target_date.replace('-', '')
                
                data = requests.get(f"{self.base_url}{cfg['path']}/scoreboard", params=params, timeout=3).json()
                for e in data.get('events', []):
                    # Filter: Game MUST be today (local time) OR Live
                    utc = e['date'].replace('Z', '')
                    local_dt = dt.fromisoformat(utc) + timedelta(hours=TIMEZONE_OFFSET)
                    if local_dt.strftime("%Y-%m-%d") != target_date and e['status']['type']['state'] != 'in': continue

                    c = e['competitions'][0]
                    h = c['competitors'][0]
                    a = c['competitors'][1]
                    st = e['status']['type']
                    
                    g = {
                        'sport': league, 'id': e['id'], 'state': st['state'],
                        'status': st['shortDetail'].replace(" EST","").replace(" EDT","").replace("Final","FINAL"),
                        'home_abbr': h['team']['abbreviation'], 'home_id': h.get('id','0'), 'home_score': h.get('score','0'), 'home_logo': h['team'].get('logo',''),
                        'away_abbr': a['team']['abbreviation'], 'away_id': a.get('id','0'), 'away_score': a.get('score','0'), 'away_logo': a['team'].get('logo',''),
                        'situation': {}
                    }
                    
                    # Logic for Live Games
                    if g['state'] == 'in':
                        sit = c.get('situation', {})
                        if 'football' in cfg['path']:
                            g['situation'] = {'possession': sit.get('possession',''), 'downDist': sit.get('downDistanceText',''), 'isRedZone': sit.get('isRedZone',False)}
                        elif league == 'nhl':
                            g['situation'] = self.analyze_nhl_pp(g['id'], e['status']['period'], e['status']['displayClock'], g['home_id'], g['away_id'], g['home_abbr'], g['away_abbr'])
                    
                    # Logic for Pre-Game (Show Time)
                    elif g['state'] == 'pre':
                        g['status'] = local_dt.strftime("%I:%M %p").lstrip('0') # e.g. "7:00 PM"

                    games.append(g)
            except: continue
        return games

fetcher = SportsFetcher()
app = Flask(__name__)

# THREADS
def loop_fetch():
    while True:
        state['current_games'] = fetcher.fetch_games()
        time.sleep(15)

# GRAPHICS FOR WEB PREVIEW
def loop_draw():
    # Simplified drawer for web preview only
    pass 

t = threading.Thread(target=loop_fetch); t.daemon = True; t.start()

# ROUTES
@app.route('/')
def index():
    # (PASTE THE FULL HTML BLOB FROM THE PREVIOUS MESSAGE HERE)
    # Use the HTML I provided in the previous "Restored Dashboard" answer.
    return """<!DOCTYPE html><html><body><h1>Backend Running</h1><p>Use client to view.</p></body></html>"""

@app.route('/client_data')
def client_data(): return jsonify({'games': state['current_games'], 'settings': state})

@app.route('/set_config', methods=['POST'])
def set_config():
    state.update(request.json)
    state['current_games'] = fetcher.fetch_games() # Force refresh
    return "OK"

@app.route('/toggle_debug')
def toggle_debug():
    state['debug_mode'] = not state['debug_mode']
    state['current_games'] = fetcher.fetch_games()
    return jsonify({'status': state['debug_mode']})

@app.route('/set_custom_date', methods=['POST'])
def set_date():
    state['custom_date'] = request.json.get('date')
    state['current_games'] = fetcher.fetch_games()
    return "OK"

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 5000)))
