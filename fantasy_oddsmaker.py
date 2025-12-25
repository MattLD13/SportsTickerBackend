import requests
import json
import time
import random
import statistics
import difflib
import os
from datetime import datetime

# ================= CONFIGURATION =================
API_KEY = "63661f0d0d00232fd1e8964ed1cdca1f"
CBS_FILE = "cbs_data.json"
ESPN_FILE = "espn_data.json"
CACHE_FILE = "odds_cache.json"
OUTPUT_FILE = "fantasy_output.json"
UPDATE_INTERVAL_HOURS = 12

PROP_MARKETS = [
    "player_pass_yds", "player_pass_tds", "player_pass_interceptions",
    "player_rush_yds", "player_rush_tds", "player_reception_yds", 
    "player_reception_tds", "player_receptions"
]

class OddsAPIFetcher:
    def __init__(self, api_key):
        self.key = api_key
        self.base = "https://api.the-odds-api.com/v4/sports/americanfootball_nfl"
        self.cache = {}
        self.load_cache()

    def load_cache(self):
        if os.path.exists(CACHE_FILE):
            try:
                with open(CACHE_FILE, 'r') as f:
                    data = json.load(f)
                    if time.time() - data.get('timestamp', 0) < (UPDATE_INTERVAL_HOURS * 3600):
                        self.cache = data.get('payload', {})
            except: pass

    def save_cache(self):
        try:
            with open(CACHE_FILE, 'w') as f:
                json.dump({'timestamp': time.time(), 'payload': self.cache}, f)
        except: pass

    def get_events(self):
        if 'events' in self.cache: return self.cache['events']
        url = f"{self.base}/events?apiKey={self.key}"
        try:
            r = requests.get(url)
            if r.status_code == 200:
                events = r.json()
                self.cache['events'] = events
                self.save_cache()
                return events
        except: return []
        return []

    def get_player_props(self, event_id):
        cache_key = f"props_{event_id}"
        if cache_key in self.cache: return self.cache[cache_key]
        
        markets_str = ",".join(PROP_MARKETS)
        url = f"{self.base}/events/{event_id}/odds?apiKey={self.key}&regions=us&markets={markets_str}&oddsFormat=american"
        try:
            r = requests.get(url)
            if r.status_code == 200:
                data = r.json()
                self.cache[cache_key] = data
                self.save_cache()
                return data
        except: return None
        return None

class FantasySimulator:
    def __init__(self, fetcher):
        self.fetcher = fetcher

    def load_json(self, path):
        if not os.path.exists(path): return None
        with open(path, 'r') as f: return json.load(f)

    def fuzzy_match_player(self, fantasy_name, api_player_names):
        clean_target = fantasy_name.split('.')[-1].strip().lower()
        best_match = None
        highest_ratio = 0.0
        for api_name in api_player_names:
            clean_api = api_name.split(' ')[-1].strip().lower()
            if clean_target == clean_api:
                if fantasy_name[0].lower() == api_name[0].lower(): return api_name
            ratio = difflib.SequenceMatcher(None, fantasy_name.lower(), api_name.lower()).ratio()
            if ratio > highest_ratio:
                highest_ratio = ratio
                best_match = api_name
        return best_match if highest_ratio > 0.8 else None

    def get_projected_stats(self, player_name, event_props):
        stats = {}
        if not event_props: return {}, 0
        agg_lines = {m: [] for m in PROP_MARKETS}
        for book in event_props.get('bookmakers', []):
            for market in book.get('markets', []):
                key = market['key']
                if key not in agg_lines: continue
                for outcome in market['outcomes']:
                    if outcome['description'] == player_name and 'point' in outcome:
                        agg_lines[key].append(outcome['point'])
        count = 0
        for market, lines in agg_lines.items():
            if lines:
                stats[market] = statistics.mean(lines)
                count += 1
        return stats, count

    def calculate_fantasy_points(self, stats, rules):
        score = 0.0
        p_yds = stats.get('player_pass_yds', 0)
        p_tds = stats.get('player_pass_tds', 0)
        p_ints = stats.get('player_pass_interceptions', 0)
        score += p_yds * rules['passing'].get('yards_factor', 0.04)
        score += p_tds * rules['passing']['touchdown']
        score += p_ints * rules['passing']['interception']
        if 'bonuses' in rules['passing'] and p_yds >= 300:
            score += rules['passing']['bonuses'].get('300_yards', 0)
        
        r_yds = stats.get('player_rush_yds', 0)
        r_tds = stats.get('player_rush_tds', 0)
        score += r_yds * rules['rushing'].get('yards_factor', 0.1)
        score += r_tds * rules['rushing']['touchdown']
        
        rec_yds = stats.get('player_reception_yds', 0)
        rec_tds = stats.get('player_reception_tds', 0)
        recs = stats.get('player_receptions', 0)
        score += rec_yds * rules['receiving'].get('yards_factor', 0.1)
        score += rec_tds * rules['receiving']['touchdown']
        score += recs * rules['receiving'].get('ppr', 0)
        return score

    def smart_abbr(self, name):
        # Removes "Team" and takes first 3 chars
        clean = name.replace("Team ", "").strip()
        return clean[:3].upper()

    def simulate_game(self, json_data, events_map):
        home = json_data['matchup']['home_team']
        away = json_data['matchup']['away_team']
        rules = json_data['scoring_rules']
        
        matchup_models = {'home': [], 'away': []}
        
        for side in ['home', 'away']:
            team_data = home if side == 'home' else away
            for p in team_data['roster']:
                if p['pos'] in ['DST', 'K']:
                    matchup_models[side].append({'name': p['name'], 'mean': p['proj'], 'std': 4.0})
                    continue

                real_name = None
                player_props = None
                for eid, props in events_map.items():
                    all_names = set()
                    for b in props.get('bookmakers', []):
                        for m in b.get('markets', []):
                            for o in m.get('outcomes', []): all_names.add(o['description'])
                    matched = self.fuzzy_match_player(p['name'], list(all_names))
                    if matched:
                        real_name = matched; player_props = props; break
                
                if real_name and player_props:
                    stats, count = self.get_projected_stats(real_name, player_props)
                    if count > 0:
                        proj_score = self.calculate_fantasy_points(stats, rules)
                        matchup_models[side].append({'name': p['name'], 'mean': proj_score, 'std': proj_score * 0.35})
                    else:
                        matchup_models[side].append({'name': p['name'], 'mean': p['proj'], 'std': p['proj']*0.4})
                else:
                    matchup_models[side].append({'name': p['name'], 'mean': p['proj'], 'std': p['proj']*0.4})

        sims = 10000; home_wins = 0; player_volatility = {}
        for _ in range(sims):
            h_score = 0; a_score = 0
            for p in matchup_models['home']:
                val = random.gauss(p['mean'], p['std'])
                h_score += val
                if p['name'] not in player_volatility: player_volatility[p['name']] = []
                player_volatility[p['name']].append(val)
            for p in matchup_models['away']:
                val = random.gauss(p['mean'], p['std'])
                a_score += val
                if p['name'] not in player_volatility: player_volatility[p['name']] = []
                player_volatility[p['name']].append(val)
            if h_score > a_score: home_wins += 1
            
        win_pct = (home_wins / sims) * 100
        
        max_std = 0; risk_player = "None"
        for name, vals in player_volatility.items():
            std = statistics.stdev(vals)
            if std > max_std:
                max_std = std; risk_player = name
                
        try:
            parts = risk_player.split(' ')
            if len(parts) > 1 and '.' not in parts[0]: risk_str = f"{parts[0][0]}. {parts[-1]}"
            else: risk_str = risk_player
        except: risk_str = risk_player

        # Use Smart Abbreviation
        h_abbr = self.smart_abbr(home['name'])
        a_abbr = self.smart_abbr(away['name'])

        return {
            "sport": "nfl",
            "id": f"fantasy_{json_data['league_settings']['platform']}",
            "status": "Live",
            "state": "in",
            "is_shown": True,
            "home_abbr": h_abbr,
            "home_score": f"{int(win_pct)}%",
            "home_logo": "",
            "home_id": h_abbr,
            "away_abbr": a_abbr,
            "away_score": f"{int(100 - win_pct)}%",
            "away_logo": "",
            "away_id": a_abbr,
            "startTimeUTC": datetime.utcnow().isoformat() + "Z",
            "period": 4,
            "situation": {
                "possession": "",
                "isRedZone": False,
                "downDist": f"Risk: {risk_str}"
            }
        }

def run_model():
    fetcher = OddsAPIFetcher(API_KEY)
    events = fetcher.get_events()
    events_map = {}
    for e in events:
        props = fetcher.get_player_props(e['id'])
        if props: events_map[e['id']] = props
        
    sim = FantasySimulator(fetcher)
    games = []
    
    if os.path.exists(CBS_FILE):
        try:
            cbs_data = sim.load_json(CBS_FILE)
            g = sim.simulate_game(cbs_data, events_map)
            g['away_logo'] = "https://a.espncdn.com/i/teamlogos/nfl/500/cin.png"
            g['home_logo'] = "https://a.espncdn.com/i/teamlogos/nfl/500/lar.png"
            games.append(g)
        except: pass

    if os.path.exists(ESPN_FILE):
        try:
            espn_data = sim.load_json(ESPN_FILE)
            g = sim.simulate_game(espn_data, events_map)
            g['home_logo'] = "https://a.espncdn.com/i/teamlogos/nfl/500/dal.png"
            g['away_logo'] = "https://a.espncdn.com/i/teamlogos/nfl/500/buf.png"
            games.append(g)
        except: pass
    
    with open(OUTPUT_FILE, 'w') as f: json.dump(games, f)

if __name__ == "__main__":
    while True:
        run_model()
        time.sleep(UPDATE_INTERVAL_HOURS * 3600)
