import requests
import json
import time
import random
import statistics
import difflib
import os
import hashlib
from datetime import datetime

# ================= CONFIGURATION =================
API_KEY = "5da338be7ba612d5e88f889f93dd832f" 
CBS_FILE = "cbs_data.json"
ESPN_FILE = "espn_data.json"
CACHE_FILE = "odds_cache.json"
OUTPUT_FILE = "fantasy_output.json"
DEBUG_FILE = "fantasy_debug.json"

# === TURBO TIMING ===
FAST_INTERVAL = 60    # Live stats every 60 seconds
SLOW_INTERVAL = 600   # Vegas odds every 10 minutes

# SIMULATION SETTINGS
SIM_COUNT = 50000 

LEAGUE_VOLATILITY = {
    "CBS": 0.40,
    "ESPN": 0.65,
    "DEFAULT": 0.50
}

LEAGUE_PAYOUTS = {
    "CBS": {"win": 1770, "loss": 1100},
    "ESPN": {"win": 1000, "loss": 500}
}

PROP_MARKETS = [
    "player_pass_yds", "player_pass_tds", "player_pass_interceptions",
    "player_rush_yds", "player_rush_tds", "player_reception_yds", 
    "player_reception_tds", "player_receptions", "player_anytime_td"
]

class LiveESPNFetcher:
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
        try:
            r = requests.get(f"http://site.api.espn.com/apis/site/v2/sports/football/nfl/summary?event={event_id}")
            d = r.json(); box = d.get('boxscore', {})
            for team in box.get('players', []):
                for stat_group in team.get('statistics', []):
                    keys = stat_group['keys']
                    for athlete in stat_group.get('athletes', []):
                        name = athlete['athlete']['displayName']
                        stats = athlete['stats']
                        pts = 0.0
                        try:
                            if stat_group['name'] == 'passing':
                                pts += (int(stats[keys.index('yds')])*0.04) + (int(stats[keys.index('tds')])*4) - (int(stats[keys.index('ints')])*2)
                            elif stat_group['name'] == 'rushing':
                                pts += (int(stats[keys.index('yds')])*0.1) + (int(stats[keys.index('tds')])*6)
                            elif stat_group['name'] == 'receiving':
                                pts += (int(stats[keys.index('yds')])*0.1) + (int(stats[keys.index('tds')])*6) + (int(stats[keys.index('rec')])*0.5)
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
        if time.time() - self.last_fetch_time < SLOW_INTERVAL:
            return
        
        print("Fetching FRESH Vegas Data...")
        url = f"{self.base}/events?apiKey={self.key}"
        try:
            r = requests.get(url)
            if r.status_code == 200:
                events = r.json()
                self.cache = {'events': events} 
                for e in events:
                    mkts = ",".join(PROP_MARKETS)
                    u2 = f"{self.base}/events/{e['id']}/odds?apiKey={self.key}&regions=us&markets={mkts}&oddsFormat=american"
                    r2 = requests.get(u2)
                    if r2.status_code == 200:
                        self.cache[f"props_{e['id']}"] = r2.json()
                self.last_fetch_time = time.time()
                self.save_cache()
        except Exception as e: print(f"Odds API Error: {e}")

    def get_all_props(self):
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
        atd_odds = []

        for book in event_props.get('bookmakers', []):
            for market in book.get('markets', []):
                key = market['key']
                if key == "player_anytime_td":
                    for o in market['outcomes']:
                        if o['description'] == player_name: atd_odds.append(o['price'])
                    continue
                if key not in agg_lines: continue
                for outcome in market['outcomes']:
                    if outcome['description'] == player_name and 'point' in outcome:
                        agg_lines[key].append(outcome['point'])
        
        count = 0
        for market, lines in agg_lines.items():
            if lines:
                stats[market] = statistics.mean(lines)
                count += 1
        
        if atd_odds:
            avg_odds = statistics.mean(atd_odds)
            if avg_odds > 0: prob = 100 / (avg_odds + 100)
            else: prob = abs(avg_odds) / (abs(avg_odds) + 100)
            stats['anytime_td_prob'] = prob
            count += 1

        return stats, count

    def calculate_fantasy_points(self, stats, rules):
        score = 0.0
        
        # --- PASSING ---
        p_yds = stats.get('player_pass_yds', 0)
        p_tds = stats.get('player_pass_tds', 0)
        # Fallback: 1 TD per 160 yds if missing
        if p_yds > 0 and p_tds == 0: p_tds = p_yds / 160.0
            
        p_ints = stats.get('player_pass_interceptions', 0)
        if p_yds > 0 and p_ints == 0: p_ints = 0.8 

        score += (p_yds * 0.04) + (p_tds * rules['passing']['touchdown']) + (p_ints * rules['passing']['interception'])
        if p_yds >= 300: score += rules['passing']['bonuses'].get('300_yards', 0)
        
        # --- RUSHING/RECEIVING ---
        r_yds = stats.get('player_rush_yds', 0)
        r_tds = stats.get('player_rush_tds', 0) 
        rec_yds = stats.get('player_reception_yds', 0)
        rec_tds = stats.get('player_reception_tds', 0)
        recs = stats.get('player_receptions', 0)
        
        score += (r_yds * 0.1) + (rec_yds * 0.1)

        # TOUCHDOWN LOGIC (Anytime TD Fix)
        total_skill_tds = r_tds + rec_tds
        if total_skill_tds == 0 and 'anytime_td_prob' in stats:
            score += stats['anytime_td_prob'] * 6.0
        elif total_skill_tds > 0:
            score += (r_tds * 6) + (rec_tds * 6)
        else:
            # Fallback to yardage regression
            score += ((r_yds / 90.0) * 6) + ((rec_yds / 90.0) * 6)

        # Failsafe: PPR estimation
        if rec_yds > 0 and recs == 0: recs = rec_yds / 11.0
            
        score += recs * rules['receiving'].get('ppr', 0)
        return score

    def generate_numeric_id(self, string_input):
        hash_val = int(hashlib.sha256(string_input.encode('utf-8')).hexdigest(), 16)
        return str(hash_val % 1000000000)

    def simulate_game(self, json_data, events_map, debug_data_list):
        home = json_data['matchup']['home_team']
        away = json_data['matchup']['away_team']
        rules = json_data['scoring_rules']
        platform = json_data.get('league_settings', {}).get('platform', 'Fantasy')
        
        tag = "CBS" if "CBS" in platform else ("ESPN" if "ESPN" in platform else "Fantasy")
        payouts = LEAGUE_PAYOUTS.get(tag, {"win": 0, "loss": 0})
        vol = LEAGUE_VOLATILITY.get(tag, 0.50)

        matchup = {'home': [], 'away': []}
        debug = {"platform": tag, "home_team": home['name'], "away_team": away['name'], "players": []}

        for side in ['home', 'away']:
            team = home if side == 'home' else away
            for p in team['roster']:
                base_proj = p['proj']; base_std = base_proj * vol; source = "League"
                
                live_info = self.live_fetcher.get_player_live(p['name'])
                l_score = live_info['score'] if live_info else 0.0
                rem_pct = live_info['rem'] if live_info else 1.0

                vegas_proj = None
                if rem_pct > 0: 
                    for eid, props in events_map.items():
                        all_n = set()
                        for b in props.get('bookmakers', []):
                            for m in b.get('markets', []):
                                for o in m.get('outcomes', []): all_n.add(o['description'])
                        match = self.fuzzy_match_player(p['name'], list(all_n))
                        if match:
                            stats, cnt = self.get_projected_stats(match, props)
                            if cnt > 0:
                                vegas_proj = self.calculate_fantasy_points(stats, rules)
                                base_std = vegas_proj * vol 
                                source = "Vegas"
                            break
                
                # SAFETY FLOOR: If Vegas is missing props and result is too low, revert.
                if vegas_proj is not None:
                    if vegas_proj < (base_proj * 0.70):
                        vegas_proj = base_proj
                        source = "League (Low Vegas)"
                
                final_proj = (vegas_proj if vegas_proj else base_proj)
                final_mean = l_score + (final_proj * rem_pct)
                if vegas_proj: base_std = vegas_proj * vol

                if p['pos'] in ['DST', 'K']:
                    final_mean = l_score + (base_proj * rem_pct)
                    base_std = 4.0 * rem_pct
                    source = "League"

                matchup[side].append({'name': p['name'], 'mean': final_mean, 'std': base_std})
                
                debug['players'].append({
                    "name": p['name'], "pos": p['pos'], "team": side.upper(),
                    "league_proj": round(l_score + (base_proj * rem_pct), 2),
                    "my_proj": round(final_mean, 2), "source": source
                })

        debug_data_list.append(debug)

        h_wins = 0; p_vol = {}
        for _ in range(SIM_COUNT):
            hs = 0; as_ = 0
            for p in matchup['home']:
                v = random.gauss(p['mean'], p['std']); hs += v
                if p['name'] not in p_vol: p_vol[p['name']] = []
                p_vol[p['name']].append(v)
            for p in matchup['away']:
                v = random.gauss(p['mean'], p['std']); as_ += v
                if p['name'] not in p_vol: p_vol[p['name']] = []
                p_vol[p['name']].append(v)
            if hs > as_: h_wins += 1
            
        win_pct = (h_wins / SIM_COUNT) * 100
        max_std = 0; risk_p = "None"
        for n, vals in p_vol.items():
            s = statistics.stdev(vals)
            if s > max_std: max_std = s; risk_p = n

        poss_abbr = ""; risk_home = False
        for p in matchup['home']:
            if p['name'] == risk_p: poss_abbr = "ME"; risk_home = True; break
        if not poss_abbr: poss_abbr = "OTH"

        hedge = int((payouts['win'] - payouts['loss']) * 0.20)

        return {
            "id": str(hash(home['name']+away['name']) % 100000), "status": tag, 
            "home_abbr": "ME", "home_score": f"{win_pct:.2f}", 
            "away_abbr": "OTH", "away_score": f"{(100-win_pct):.2f}",
            "situation": {"possession": poss_abbr, "downDist": f"Hedge: Bet ${hedge}"}
        }

def run_loop():
    print(f"Fantasy Oddsmaker Started (Sim: {SIM_COUNT} | Vol: {LEAGUE_VOLATILITY})")
    odds = OddsAPIFetcher(API_KEY); live = LiveESPNFetcher()
    while True:
        odds.fetch_fresh_props(); props = odds.get_all_props()
        live.fetch_live_stats()
        sim = FantasySimulator(odds, live); games = []; dbg = []
        if os.path.exists(CBS_FILE):
            try: games.append(sim.simulate_game(sim.load_json(CBS_FILE), props, dbg))
            except: pass
        if os.path.exists(ESPN_FILE):
            try: games.append(sim.simulate_game(sim.load_json(ESPN_FILE), props, dbg))
            except: pass
        with open(OUTPUT_FILE, 'w') as f: json.dump(games, f)
        with open(DEBUG_FILE, 'w') as f: json.dump(dbg, f)
        print(f"Updated: {datetime.now().strftime('%H:%M:%S')}")
        time.sleep(FAST_INTERVAL)

if __name__ == "__main__":
    run_loop()
