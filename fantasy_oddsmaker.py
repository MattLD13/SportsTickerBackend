import requests
import json
import time
import random
import statistics
import difflib
import os
import hashlib
from datetime import datetime, timedelta

# ================= CONFIGURATION =================
API_KEY = "63661f0d0d00232fd1e8964ed1cdca1f"
CBS_FILE = "cbs_data.json"
ESPN_FILE = "espn_data.json"
CACHE_FILE = "odds_cache.json"
OUTPUT_FILE = "fantasy_output.json"

# === TIMING CONFIGURATION ===
# FAST LOOP: Updates scores/win % using ESPN (Free)
FAST_INTERVAL = 300  # 5 Minutes

# SLOW LOOP: Updates Vegas Odds (Costly)
# 493 Credits / ~40 cost per run = ~12 runs left.
# 120 Hours / 12 runs = ~10 Hours per update.
SLOW_INTERVAL = 10 * 3600 

LEAGUE_PAYOUTS = {
    "CBS": {"win": 1770, "loss": 1100},
    "ESPN": {"win": 1000, "loss": 500}
}

PROP_MARKETS = ["player_pass_yds", "player_rush_yds", "player_reception_yds"]

class LiveESPNFetcher:
    """ Fetches REAL-TIME stats from ESPN (Free/Unlimited) """
    def __init__(self):
        self.url = "http://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard"
        self.live_data = {}

    def fetch_live_stats(self):
        try:
            r = requests.get(self.url, params={'limit': 100})
            if r.status_code == 200:
                data = r.json()
                self._parse_events(data.get('events', []))
        except: pass

    def _parse_events(self, events):
        temp_map = {}
        for e in events:
            status = e.get('status', {})
            state = status.get('type', {}).get('state', 'pre')
            period = status.get('period', 1)
            
            time_rem_pct = 1.0
            if state == 'in':
                q_rem = 4 - period
                time_rem_pct = (q_rem * 15) / 60.0
            elif state == 'post':
                time_rem_pct = 0.0

            if state == 'in':
                self._fetch_game_summary(e['id'], temp_map, time_rem_pct)
        self.live_data = temp_map

    def _fetch_game_summary(self, event_id, player_map, time_rem_pct):
        url = f"http://site.api.espn.com/apis/site/v2/sports/football/nfl/summary?event={event_id}"
        try:
            r = requests.get(url)
            d = r.json()
            box = d.get('boxscore', {})
            for team in box.get('players', []):
                for stat_group in team.get('statistics', []):
                    stat_type = stat_group['name'] 
                    keys = stat_group['keys']
                    for athlete in stat_group.get('athletes', []):
                        name = athlete['athlete']['displayName']
                        stats = athlete['stats']
                        pts = 0.0
                        try:
                            if stat_type == 'passing':
                                yds = int(stats[keys.index('yds')])
                                tds = int(stats[keys.index('tds')])
                                ints = int(stats[keys.index('ints')])
                                pts += (yds * 0.04) + (tds * 4) - (ints * 2)
                            elif stat_type == 'rushing':
                                yds = int(stats[keys.index('yds')])
                                tds = int(stats[keys.index('tds')])
                                pts += (yds * 0.1) + (tds * 6)
                            elif stat_type == 'receiving':
                                yds = int(stats[keys.index('yds')])
                                tds = int(stats[keys.index('tds')])
                                rec = int(stats[keys.index('rec')])
                                pts += (yds * 0.1) + (tds * 6) + (rec * 0.5)
                        except: pass

                        if name not in player_map:
                            player_map[name] = {'score': 0.0, 'rem': time_rem_pct}
                        player_map[name]['score'] += pts
        except: pass

    def get_player_live(self, name):
        clean_target = name.split('.')[-1].strip().lower()
        for k, v in self.live_data.items():
            if clean_target in k.lower(): return v
        return None

class OddsAPIFetcher:
    """ Fetches Vegas Props (Costly/Limited) """
    def __init__(self, api_key):
        self.key = api_key
        self.base = "https://api.the-odds-api.com/v4/sports/americanfootball_nfl"
        self.cache = {}
        self.last_fetch_time = 0
        self.load_cache()

    def load_cache(self):
        if os.path.exists(CACHE_FILE):
            try:
                with open(CACHE_FILE, 'r') as f:
                    data = json.load(f)
                    self.cache = data.get('payload', {})
                    self.last_fetch_time = data.get('timestamp', 0)
            except: pass

    def save_cache(self):
        try:
            with open(CACHE_FILE, 'w') as f:
                json.dump({'timestamp': time.time(), 'payload': self.cache}, f)
        except: pass

    def fetch_fresh_props(self):
        # Only run if SLOW_INTERVAL has passed
        if time.time() - self.last_fetch_time < SLOW_INTERVAL:
            print("Using Cached Vegas Data (Economy Mode).")
            return
        
        print("Fetching FRESH Vegas Data (Spending Credits)...")
        url = f"{self.base}/events?apiKey={self.key}"
        try:
            r = requests.get(url)
            if r.status_code == 200:
                events = r.json()
                # Economy: Only first 12 games
                relevant = events[:12] if len(events) > 12 else events
                
                # Clear old props to force refresh
                self.cache = {'events': events} 
                
                for e in relevant:
                    mkts = ",".join(PROP_MARKETS)
                    u2 = f"{self.base}/events/{e['id']}/odds?apiKey={self.key}&regions=us&markets={mkts}&oddsFormat=american"
                    r2 = requests.get(u2)
                    if r2.status_code == 200:
                        self.cache[f"props_{e['id']}"] = r2.json()
                
                self.last_fetch_time = time.time()
                self.save_cache()
        except Exception as e: print(f"Odds API Error: {e}")

    def get_all_props(self):
        # Returns dict of all cached props {event_id: props}
        res = {}
        events = self.cache.get('events', [])
        for e in events:
            p = self.cache.get(f"props_{e['id']}")
            if p: res[e['id']] = p
        return res

class FantasySimulator:
    def __init__(self, fetcher, live_fetcher):
        self.fetcher = fetcher
        self.live_fetcher = live_fetcher

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
        score += p_yds * rules['passing'].get('yards_factor', 0.04)
        if 'bonuses' in rules['passing'] and p_yds >= 300:
            score += rules['passing']['bonuses'].get('300_yards', 0)
        
        r_yds = stats.get('player_rush_yds', 0)
        score += r_yds * rules['rushing'].get('yards_factor', 0.1)
        
        rec_yds = stats.get('player_reception_yds', 0)
        score += rec_yds * rules['receiving'].get('yards_factor', 0.1)
        
        # Regression Estimates for missing props
        est_pass_td = p_yds / 160.0
        est_rush_td = r_yds / 90.0
        est_rec_td = rec_yds / 90.0
        est_recs = rec_yds / 11.0
        
        score += est_pass_td * rules['passing']['touchdown']
        score += est_rush_td * rules['rushing']['touchdown']
        score += est_rec_td * rules['receiving']['touchdown']
        score += est_recs * rules['receiving'].get('ppr', 0)
        return score

    def generate_numeric_id(self, string_input):
        hash_val = int(hashlib.sha256(string_input.encode('utf-8')).hexdigest(), 16)
        return str(hash_val % 1000000000)

    def simulate_game(self, json_data, events_map):
        home = json_data['matchup']['home_team']
        away = json_data['matchup']['away_team']
        rules = json_data['scoring_rules']
        platform = json_data.get('league_settings', {}).get('platform', 'Fantasy')
        
        status_tag = "CBS" if "CBS" in platform else ("ESPN" if "ESPN" in platform else "Fantasy")
        payouts = LEAGUE_PAYOUTS.get(status_tag, {"win": 0, "loss": 0})

        matchup_models = {'home': [], 'away': []}
        
        for side in ['home', 'away']:
            team_data = home if side == 'home' else away
            for p in team_data['roster']:
                base_proj = p['proj']
                base_std = base_proj * 0.4 
                live_info = self.live_fetcher.get_player_live(p['name'])
                live_score = 0.0; rem_pct = 1.0

                if live_info:
                    live_score = live_info['score']
                    rem_pct = live_info['rem']

                vegas_proj = None
                if rem_pct > 0: 
                    for eid, props in events_map.items():
                        all_names = set()
                        for b in props.get('bookmakers', []):
                            for m in b.get('markets', []):
                                for o in m.get('outcomes', []): all_names.add(o['description'])
                        matched = self.fuzzy_match_player(p['name'], list(all_names))
                        if matched:
                            stats, count = self.get_projected_stats(matched, props)
                            if count > 0:
                                vegas_proj = self.calculate_fantasy_points(stats, rules)
                                base_std = vegas_proj * 0.35
                            break
                
                remainder_proj = (vegas_proj if vegas_proj else base_proj) * rem_pct
                final_mean = live_score + remainder_proj
                
                if p['pos'] in ['DST', 'K']:
                    final_mean = live_score + (p['proj'] * rem_pct)
                    base_std = 4.0 * rem_pct

                matchup_models[side].append({'name': p['name'], 'mean': final_mean, 'std': base_std})

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
            if std > max_std: max_std = std; risk_player = name

        h_abbr = "ME"
        a_abbr = "OTH"

        upside_val = payouts['win'] - payouts['loss']
        hedge_bet_amount = int(upside_val * 0.20)

        risk_on_home = False
        possession_abbr = ""
        for p in matchup_models['home']:
            if p['name'] == risk_player:
                possession_abbr = h_abbr; risk_on_home = True; break
        if not possession_abbr: possession_abbr = a_abbr

        hedge_msg = f"Hedge: Bet ${hedge_bet_amount}"

        game_id = self.generate_numeric_id(f"{home['name']}_vs_{away['name']}")
        h_val = f"{win_pct:.2f}"
        a_val = f"{(100 - win_pct):.2f}"

        return {
            "sport": "nfl",
            "id": game_id,
            "status": status_tag,
            "state": "in",
            "is_shown": True,
            "home_abbr": h_abbr,
            "home_score": h_val,
            "home_logo": "https://a.espncdn.com/i/teamlogos/ncaa/500/172.png", 
            "home_id": h_abbr,
            "away_abbr": a_abbr,
            "away_score": a_val,
            "away_logo": "https://a.espncdn.com/i/teamlogos/ncaa/500/193.png", 
            "away_id": a_abbr,
            "startTimeUTC": datetime.utcnow().isoformat() + "Z",
            "period": 4,
            "situation": {
                "possession": possession_abbr,
                "isRedZone": False,
                "downDist": hedge_msg
            }
        }

def run_loop():
    print("Fantasy Oddsmaker Started.")
    
    odds_fetcher = OddsAPIFetcher(API_KEY)
    live_fetcher = LiveESPNFetcher()
    
    # Run continuously
    while True:
        # 1. Slow Loop: Check if we need new Vegas Data
        odds_fetcher.fetch_fresh_props() 
        cached_props = odds_fetcher.get_all_props()
        
        # 2. Fast Loop: Get Live Scores & Run Sim
        live_fetcher.fetch_live_stats()
        
        sim = FantasySimulator(odds_fetcher, live_fetcher)
        games = []
        
        if os.path.exists(CBS_FILE):
            try:
                games.append(sim.simulate_game(sim.load_json(CBS_FILE), cached_props))
            except: pass

        if os.path.exists(ESPN_FILE):
            try:
                games.append(sim.simulate_game(sim.load_json(ESPN_FILE), cached_props))
            except: pass
        
        with open(OUTPUT_FILE, 'w') as f: json.dump(games, f)
        
        print(f"Updated: {datetime.now().strftime('%H:%M:%S')}")
        time.sleep(FAST_INTERVAL)

if __name__ == "__main__":
    run_loop()
