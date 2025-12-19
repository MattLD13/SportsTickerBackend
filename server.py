import time
import threading
import json
import os
import datetime
import subprocess 
from datetime import datetime as dt, timezone, timedelta
import requests
from flask import Flask, jsonify, request

# IMPORT TEAMS
try:
    from valid_teams import FBS_TEAMS, FCS_TEAMS
except ImportError:
    FBS_TEAMS = []
    FCS_TEAMS = []

# ================= CONFIGURATION =================
TIMEZONE_OFFSET = -5  # Set to -5 for EST/EDT
CONFIG_FILE = "ticker_config.json"
UPDATE_INTERVAL = 8

# --- NHL LOGO FIXES ---
NHL_LOGO_MAP = {
    "SJS": "sj",  "NJD": "nj",  "TBL": "tb",    
    "LAK": "la",  "VGK": "vgs", "VEG": "vgs"
}

# ================= WEB UI =================
DASHBOARD_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Ticker Backend</title>
    <style>body{background:#111;color:#eee;font-family:sans-serif;padding:20px;}</style>
</head>
<body>
    <h1>Ticker Backend Active</h1>
    <p>Use the App or API to control.</p>
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
    'custom_date': None,
    'brightness': 0.5,
    'inverted': False,
    'panel_count': 2,
    'test_pattern': False
}

state = default_state.copy()

if os.path.exists(CONFIG_FILE):
    try:
        with open(CONFIG_FILE, 'r') as f:
            loaded = json.load(f)
            for k, v in loaded.items():
                state[k] = v
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
                                    logos = item['team'].get('logos', [])
                                    t_logo = logos[0].get('href', '') if len(logos) > 0 else ''
                                    team_obj = {'abbr': t_abbr, 'logo': t_logo}
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
        is_nhl_enabled = state['active_sports'].get('nhl', False)
        schedule_url = "https://api-web.nhle.com/v1/schedule/now"
        try:
            response = requests.get(schedule_url, timeout=5)
            if response.status_code != 200: return
            schedule_data = response.json()
        except: return

        for date_entry in schedule_data.get('gameWeek', []):
            if date_entry.get('date') != target_date_str: continue 
            for game in date_entry.get('games', []):
                self._process_single_nhl_game(game['id'], games_list, is_nhl_enabled)

    def _process_single_nhl_game(self, game_id, games_list, is_enabled):
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
        
        # --- NEW: Playoff Detection (GameType 3 = Playoffs) ---
        game_type = data.get('gameType', 2)
        is_playoff = (game_type == 3)

        away_code = NHL_LOGO_MAP.get(away_abbr, away_abbr.lower())
        home_code = NHL_LOGO_MAP.get(home_abbr, home_abbr.lower())
        
        if away_abbr.upper() in ['WSH', 'WAS']: away_logo = "https://a.espncdn.com/guid/cbe677ee-361e-91b4-5cae-6c4c30044743/logos/secondary_logo_on_black_color.png"
        else: away_logo = f"https://a.espncdn.com/i/teamlogos/nhl/500/{away_code}.png"
            
        if home_abbr.upper() in ['WSH', 'WAS']: home_logo = "https://a.espncdn.com/guid/cbe677ee-361e-91b4-5cae-6c4c30044743/logos/secondary_logo_on_black_color.png"
        else: home_logo = f"https://a.espncdn.com/i/teamlogos/nhl/500/{home_code}.png"

        game_state = data.get('gameState', 'OFF') 
        mapped_state = 'in' if game_state in ['LIVE', 'CRIT'] else 'post'
        if game_state in ['PRE', 'FUT']: mapped_state = 'pre'

        is_shown = is_enabled
        if is_shown:
            if state['mode'] == 'live' and mapped_state != 'in': is_shown = False
            if state['mode'] == 'my_teams':
                if (home_abbr not in state['my_teams']) and (away_abbr not in state['my_teams']): is_shown = False

        clock = data.get('clock', {})
        time_rem = clock.get('timeRemaining', '00:00')
        period = data.get('periodDescriptor', {}).get('number', 1)
        
        if game_state in ['FINAL', 'OFF']: status_disp = "FINAL"
        elif game_state in ['PRE', 'FUT']: status_disp = "Scheduled"
        elif clock.get('inIntermission'): status_disp = f"P{period} INT"
        else: status_disp = f"P{period} {time_rem}"

        sit_code = data.get('situation', {}).get('situationCode', '1551')
        try:
            away_skaters = int(sit_code[1]); home_skaters = int(sit_code[2])
            away_goalie = int(sit_code[0]); home_goalie = int(sit_code[3])
        except: away_skaters, home_skaters, away_goalie, home_goalie = 5,5,1,1

        is_pp = False; possession = ""; is_empty_net = False
        if away_skaters > home_skaters: is_pp = True; possession = away_abbr 
        elif home_skaters > away_skaters: is_pp = True; possession = home_abbr
        if away_goalie == 0 or home_goalie == 0: is_empty_net = True

        game_obj = {
            'sport': 'nhl', 'id': str(game_id), 'status': status_disp, 'state': mapped_state,
            'is_shown': is_shown, 'is_playoff': is_playoff,
            'home_abbr': home_abbr, 'home_score': home_score, 'home_logo': home_logo, 'home_id': home_abbr, 
            'away_abbr': away_abbr, 'away_score': away_score, 'away_logo': away_logo, 'away_id': away_abbr,
            'period': period,
            'situation': { 'powerPlay': is_pp, 'possession': possession, 'emptyNet': is_empty_net }
        }
        games_list.append(game_obj)

    def get_real_games(self):
        games = []
        req_params = {}
        if state['debug_mode'] and state['custom_date']:
            target_date_str = state['custom_date']
            req_params['dates'] = target_date_str.replace('-', '')
        else:
            local_now = dt.now(timezone.utc) + timedelta(hours=TIMEZONE_OFFSET)
            target_date_str = local_now.strftime("%Y-%m-%d")
        
        for league_key, config in self.leagues.items():
            is_sport_enabled = state['active_sports'].get(league_key, False)
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
                        
                        # --- NEW: Playoff Detection (Season Type 3 = Post) ---
                        season_type = event.get('season', {}).get('type', 2)
                        is_playoff = (season_type == 3)
                        
                        raw_status = status_type.get('shortDetail', 'Scheduled')
                        status_display = raw_status 
                        period = status_obj.get('period', 1)
                        clock = status_obj.get('displayClock', '')
                        is_halftime = (status_state == 'half') or (period == 2 and clock == '0:00')

                        if is_halftime:
                            status_display = "HALFTIME"; status_state = 'half' 
                        elif status_state == 'in' and ('football' in config['path'] or league_key == 'nba'):
                            if clock: status_display = f"Q{period} - {clock}"
                            else: status_display = f"Q{period}" 
                        else:
                            status_display = raw_status.replace("Final", "FINAL").replace(" EST", "").replace(" EDT", "").replace("/OT", "")
                            if " - " in status_display: status_display = status_display.split(" - ")[-1]
                        
                        is_shown = is_sport_enabled
                        if is_shown:
                            if state['mode'] == 'live' and status_state not in ['in', 'half']: is_shown = False
                            elif state['mode'] == 'my_teams':
                                h_abbr = home['team']['abbreviation']; a_abbr = away['team']['abbreviation']
                                if (h_abbr not in state['my_teams']) and (a_abbr not in state['my_teams']): is_shown = False
                        
                        home_logo_url = home['team'].get('logo', '')
                        away_logo_url = away['team'].get('logo', '')
                        if league_key == 'nhl' and home['team']['abbreviation'].upper() in ['WSH', 'WAS']: home_logo_url = "https://a.espncdn.com/guid/cbe677ee-361e-91b4-5cae-6c4c30044743/logos/secondary_logo_on_black_color.png"
                        if league_key == 'nhl' and away['team']['abbreviation'].upper() in ['WSH', 'WAS']: away_logo_url = "https://a.espncdn.com/guid/cbe677ee-361e-91b4-5cae-6c4c30044743/logos/secondary_logo_on_black_color.png"

                        game_obj = {
                            'sport': league_key, 'id': event['id'], 'status': status_display, 'state': status_state,
                            'is_shown': is_shown, 'is_playoff': is_playoff,
                            'home_abbr': home['team']['abbreviation'], 'home_score': home.get('score', '0'), 
                            'home_logo': home_logo_url, 'home_id': home.get('id'),
                            'away_abbr': away['team']['abbreviation'], 'away_score': away.get('score', '0'), 
                            'away_logo': away_logo_url, 'away_id': away.get('id'),
                            'period': period,
                            'situation': {}
                        }

                        if status_state == 'in' and not is_halftime:
                            if 'football' in config['path']:
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

@app.route('/api/ticker')
def get_ticker_data():
    visible_games = [g for g in state['current_games'] if g.get('is_shown', True)]
    return jsonify({
        'meta': { 
            'time': dt.now(timezone.utc).strftime("%I:%M %p"), 
            'count': len(visible_games), 
            'speed': 0.02, 
            'scroll_seamless': state.get('scroll_seamless', False),
            'brightness': state.get('brightness', 0.5),
            'inverted': state.get('inverted', False),
            'panel_count': state.get('panel_count', 2),
            'test_pattern': state.get('test_pattern', False)
        },
        'games': visible_games
    })

@app.route('/api/all_games')
def get_all_games(): return jsonify({ 'games': state['current_games'] })

@app.route('/api/state')
def get_full_state(): return jsonify({'settings': state, 'games': state['current_games']})

@app.route('/api/teams')
def get_teams(): return jsonify(state['all_teams_data'])

@app.route('/api/config', methods=['POST'])
def update_config():
    d = request.json
    for k in d: state[k] = d[k]
    threading.Thread(target=fetcher.get_real_games).start()
    return jsonify({"status": "ok"})

@app.route('/api/debug', methods=['POST'])
def set_debug():
    d = request.json
    if 'debug_mode' in d: state['debug_mode'] = d['debug_mode']
    if 'custom_date' in d: state['custom_date'] = d['custom_date']
    fetcher.get_real_games()
    return jsonify({"status": "ok"})

@app.route('/api/hardware', methods=['POST'])
def hardware_control():
    data = request.json
    action = data.get('action')
    if action == 'reboot':
        threading.Thread(target=lambda: (time.sleep(3), subprocess.run(["sudo", "reboot"]))).start()
        return jsonify({"status": "rebooting"})
    elif action == 'test_pattern':
        state['test_pattern'] = not state.get('test_pattern', False)
        return jsonify({"status": "ok", "test_pattern": state['test_pattern']})
    for k in data: state[k] = data[k]
    return jsonify({"status": "ok", "settings": state})

if __name__ == "__main__":
    t = threading.Thread(target=background_updater)
    t.daemon = True
    t.start()
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
