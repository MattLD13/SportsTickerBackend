import requests
import json
import time
import random
import statistics
import difflib
import os
import shutil
import gc
import re
from datetime import datetime

# ================= CONFIGURATION =================
API_KEY = "5da338be7ba612d5e88f889f93dd832f" 
CBS_FILE = "cbs_data.json"
ESPN_FILE = "espn_data.json"
CACHE_FILE = "odds_cache.json"
OUTPUT_FILE = "fantasy_output.json"
DEBUG_FILE = "fantasy_debug.json"

FAST_INTERVAL = 60    
SLOW_INTERVAL = 10800 
SIM_COUNT = 20000 

LEAGUE_VOLATILITY = { "CBS": 0.55, "ESPN": 0.65, "DEFAULT": 0.60 }
LEAGUE_PAYOUTS = { "CBS": {"win": 1770, "loss": 1100}, "ESPN": {"win": 1000, "loss": 500} }
LEAGUE_PROJ_MULTIPLIERS = { "CBS": 0.91, "ESPN": 1.05, "DEFAULT": 1.0 }

PROP_MARKETS = [
    "player_pass_yds", "player_pass_tds", "player_pass_interceptions",
    "player_rush_yds", "player_rush_tds", "player_reception_yds", 
    "player_reception_tds", "player_receptions", "player_anytime_td"
]

HISTORICAL_RATES = {
    'QB': {'pass_td_per_yd': 0.0064, 'rush_td_per_yd': 0.003}, 
    'RB': {'rush_td_per_yd': 0.0090, 'rec_td_per_yd': 0.005},  
    'WR': {'rush_td_per_yd': 0.0050, 'rec_td_per_yd': 0.0062}, 
    'TE': {'rec_td_per_yd': 0.0083},                           
    'DEFAULT': {'pass': 0.006, 'rush': 0.007, 'rec': 0.006}
}

FANTASY_LOGO = "https://a.espncdn.com/i/teamlogos/ncaa/500/172.png" 
OPPONENT_LOGO = "https://a.espncdn.com/i/teamlogos/ncaa/500/193.png" 

def atomic_write(filename, data):
    temp_file = f"{filename}.tmp"
    try:
        with open(temp_file, 'w') as f: json.dump(data, f)
        os.replace(temp_file, filename)
    except:
        if os.path.exists(temp_file): os.remove(temp_file)

# ================= LIVE SCORING ENGINE =================
class LiveGameManager:
    def __init__(self):
        self.base_url = "http://site.api.espn.com/apis/site/v2/sports/football/nfl"
        self.player_stats = {} 
        self.team_status = {} 

    def update(self):
        self.player_stats = {}
        self.team_status = {}
        
        try:
            # 1. GET SCOREBOARD
            r = requests.get(f"{self.base_url}/scoreboard", params={'limit': 100}, timeout=5)
            data = r.json()
            
            active_games = []
            
            for e in data.get('events', []):
                game_id = e['id']
                status = e.get('status', {})
                state = status.get('type', {}).get('state', 'pre')
                
                # Calculate Time Remaining
                mins_remaining = 60.0 # Default Pre-Game
                if state == 'in':
                    period = status.get('period', 1)
                    clock = status.get('displayClock', '15:00')
                    try:
                        c_min = int(clock.split(':')[0])
                        mins_remaining = ((4 - period) * 15) + c_min
                    except: mins_remaining = 45.0 # Fallback
                elif state == 'post':
                    mins_remaining = 0.0
                
                # Map Teams
                for c in e['competitions'][0]['competitors']:
                    abbr = c['team']['abbreviation']
                    self.team_status[abbr] = mins_remaining
                
                # Add to fetch list
                if state in ['in', 'post']:
                    active_games.append(game_id)
            
            print(f"[Live] Found {len(active_games)} active games.")
            for gid in active_games:
                self._fetch_boxscore(gid)
                
            print(f"[Live] Tracked stats for {len(self.player_stats)} players.")
                    
        except Exception as e:
            print(f"Live Data Error: {e}")

    def _fetch_boxscore(self, game_id):
        try:
            r = requests.get(f"{self.base_url}/summary?event={game_id}", timeout=5)
            d = r.json()
            
            # [FIXED] Path is boxscore -> PLAYERS (not teams)
            # 'players' is a list (one object per team)
            for team_group in d.get('boxscore', {}).get('players', []):
                for grp in team_group.get('statistics', []):
                    keys = grp['keys']
                    for ath in grp.get('athletes', []):
                        name = ath['athlete']['displayName']
                        stats = ath['stats']
                        
                        clean_name = self._clean_name(name)
                        if clean_name not in self.player_stats:
                            self.player_stats[clean_name] = {'pass_yds':0,'pass_td':0,'int':0,'rush_yds':0,'rush_td':0,'rec_yds':0,'rec_td':0,'rec':0}
                        
                        try:
                            s = self.player_stats[clean_name]
                            # ESPN stats come as strings, sometimes with "--"
                            def get_stat(idx):
                                try: return float(stats[idx])
                                except: return 0.0

                            if grp['name'] == 'passing':
                                if 'yds' in keys: s['pass_yds'] = get_stat(keys.index('yds'))
                                if 'tds' in keys: s['pass_td'] = get_stat(keys.index('tds'))
                                if 'ints' in keys: s['int'] = get_stat(keys.index('ints'))
                            elif grp['name'] == 'rushing':
                                if 'yds' in keys: s['rush_yds'] = get_stat(keys.index('yds'))
                                if 'tds' in keys: s['rush_td'] = get_stat(keys.index('tds'))
                            elif grp['name'] == 'receiving':
                                if 'yds' in keys: s['rec_yds'] = get_stat(keys.index('yds'))
                                if 'tds' in keys: s['rec_td'] = get_stat(keys.index('tds'))
                                if 'rec' in keys: s['rec'] = get_stat(keys.index('rec'))
                        except: pass
        except: pass

    def _clean_name(self, name):
        # Normalize for matching
        return name.lower().replace('.', '').replace(' jr', '').replace(' sr', '').replace(' iii', '').strip()

    def get_player_live(self, name, team_abbr, scoring_rules):
        # 1. Get Game Status
        mins = self.team_status.get(team_abbr, 60.0)
        
        # 2. Get Player Stats
        clean_name = self._clean_name(name)
        stats = self.player_stats.get(clean_name)
        
        if not stats: return 0.0, mins
            
        # 3. Calculate Points
        pts = 0.0
        pts += (stats['pass_yds'] * scoring_rules['passing']['yards'])
        pts += (stats['pass_td'] * scoring_rules['passing']['touchdown'])
        pts += (stats['int'] * scoring_rules['passing']['interception'])
        pts += (stats['rush_yds'] * scoring_rules['rushing']['yards'])
        pts += (stats['rush_td'] * scoring_rules['rushing']['touchdown'])
        pts += (stats['rec_yds'] * scoring_rules['receiving']['yards'])
        pts += (stats['rec_td'] * scoring_rules['receiving']['touchdown'])
        pts += (stats['rec'] * scoring_rules['receiving'].get('ppr', 0))
        
        return pts, mins

# ================= ODDS FETCHER =================
class OddsAPIFetcher:
    def __init__(self, api_key):
        self.key = api_key; self.base = "https://api.the-odds-api.com/v4/sports/americanfootball_nfl"
        self.cache = {}; self.last_fetch = 0; self.load_cache()
    def load_cache(self):
        if os.path.exists(CACHE_FILE):
            try: 
                with open(CACHE_FILE, 'r') as f: d = json.load(f); self.cache = d.get('payload', {}); self.last_fetch = d.get('timestamp', 0)
            except: pass
    def save_cache(self):
        atomic_write(CACHE_FILE, {'timestamp': time.time(), 'payload': self.cache})
    def fetch_fresh(self):
        if time.time() - self.last_fetch < SLOW_INTERVAL: return
        print("Fetching Vegas Data...")
        try:
            r = requests.get(f"{self.base}/events?apiKey={self.key}", timeout=10)
            if r.status_code == 200:
                events = r.json(); self.cache = {'events': events}
                for e in events:
                    mkts = ",".join(PROP_MARKETS)
                    time.sleep(0.2) 
                    r2 = requests.get(f"{self.base}/events/{e['id']}/odds?apiKey={self.key}&regions=us&markets={mkts}&oddsFormat=american", timeout=5)
                    if r2.status_code == 200: self.cache[f"props_{e['id']}"] = r2.json()
                self.last_fetch = time.time(); self.save_cache()
        except: pass
    def get_props(self):
        res = {}; events = self.cache.get('events', [])
        for e in events:
            p = self.cache.get(f"props_{e['id']}")
            if p: res[e['id']] = p
        return res

# ================= SIMULATOR =================
class FantasySimulator:
    def __init__(self, fetcher, live_manager):
        self.fetcher = fetcher; self.live = live_manager
    def load_json(self, path):
        if not os.path.exists(path): return None
        try:
            with open(path, 'r') as f: return json.load(f)
        except: return None
    
    def fuzzy_match(self, name, api_names):
        target = name.lower().replace('.', '').replace(' jr', '').strip()
        best = None; hi = 0.0
        for api in api_names:
            clean = api.lower().replace('.', '').replace(' jr', '').strip()
            if target == clean: return api
            ratio = difflib.SequenceMatcher(None, target, clean).ratio()
            if ratio > hi: hi = ratio; best = api
        return best if hi > 0.85 else None
    
    def get_proj(self, name, props):
        stats = {}; agg = {m: [] for m in PROP_MARKETS}; atd = []
        if not props: return {}, 0
        for book in props.get('bookmakers', []):
            for m in book.get('markets', []):
                key = m['key']
                if key == "player_anytime_td":
                    for o in m['outcomes']:
                        if o['name'] == name: atd.append(o['price'])
                    continue
                if key in agg:
                    for o in m['outcomes']:
                        if o.get('description') == name and 'point' in o: agg[key].append(o['point'])
        count = 0
        for k, v in agg.items():
            if v: stats[k] = statistics.mean(v); count += 1
        if atd:
            avg = statistics.mean(atd); prob = 100/(avg+100) if avg>0 else abs(avg)/(abs(avg)+100)
            stats['anytime_td_prob'] = prob; count += 1
        return stats, count

    def calc_pts(self, stats, pos, rules):
        s = 0.0
        p_yds = stats.get('player_pass_yds', 0); p_tds = stats.get('player_pass_tds', 0)
        s += (p_yds * 0.04) + (p_tds * rules['passing']['touchdown'])
        if p_yds > 0 and p_tds == 0:
            rate = HISTORICAL_RATES.get('QB', {}).get('pass_td_per_yd', 0.006)
            s += (p_yds * rate * rules['passing']['touchdown'])

        r_yds = stats.get('player_rush_yds', 0); r_tds = stats.get('player_rush_tds', 0)
        s += (r_yds * 0.1)
        if r_yds > 0 and r_tds == 0:
            rate = HISTORICAL_RATES.get(pos, HISTORICAL_RATES['DEFAULT']).get('rush_td_per_yd', 0.007)
            s += (r_yds * rate * 6.0)
        else: s += (r_tds * 6.0)

        rec_yds = stats.get('player_reception_yds', 0); rec_tds = stats.get('player_reception_tds', 0)
        recs = stats.get('player_receptions', 0)
        s += (rec_yds * 0.1)
        if rec_yds > 0 and recs == 0: recs = rec_yds / 13.0
        s += recs * rules['receiving'].get('ppr', 0)
        if rec_yds > 0 and rec_tds == 0:
            rate = HISTORICAL_RATES.get(pos, HISTORICAL_RATES['DEFAULT']).get('rec_td_per_yd', 0.006)
            s += (rec_yds * rate * 6.0)
        else: s += (rec_tds * 6.0)
        return s

    def run_sim(self, json_data, props_map, debug_list):
        if not json_data: return None
        home = json_data['matchup']['home_team']; away = json_data['matchup']['away_team']
        plat = json_data.get('league_settings', {}).get('platform', 'Fantasy')
        tag = "CBS" if "CBS" in plat else ("ESPN" if "ESPN" in plat else "Fantasy")
        
        vol = LEAGUE_VOLATILITY.get(tag, 0.60)
        proj_mult = LEAGUE_PROJ_MULTIPLIERS.get(tag, 1.0)
        payouts = LEAGUE_PAYOUTS.get(tag, {"win":0, "loss":0})
        
        matchup = {'home': [], 'away': []}
        dbg = {"platform": tag, "home_team": home['name'], "away_team": away['name'], "players": []}

        for side in ['home', 'away']:
            team = home if side == 'home' else away
            for p in team['roster']:
                base = p['proj']
                b_std = max(base * vol, 4.0)
                src = "League"
                
                live_pts, mins_rem = self.live.get_player_live(p['name'], p.get('team',''), json_data['scoring_rules'])
                decay = max(0.0, min(1.0, mins_rem / 60.0))
                
                base_rem = base * decay
                vegas_rem = None
                
                if decay > 0:
                    for eid, pm in props_map.items():
                        names = set()
                        for b in pm.get('bookmakers', []):
                            for m in b.get('markets', []):
                                for o in m.get('outcomes', []):
                                    if 'description' in o: names.add(o['description'])
                        match = self.fuzzy_match(p['name'], list(names))
                        if match:
                            stats, cnt = self.get_proj(match, pm)
                            if cnt > 0:
                                raw_vegas = self.calc_pts(stats, p['pos'], json_data['scoring_rules'])
                                vegas_rem = (raw_vegas * proj_mult) * decay
                                b_std = max(raw_vegas * vol, 4.0)
                                src = "Vegas"
                            break
                
                if vegas_rem is None or (vegas_rem < (base_rem * 0.5)):
                    vegas_rem = base_rem
                    if src == "Vegas": src = "League (Low Vegas)"
                
                final_mean_vegas = live_pts + vegas_rem
                final_mean_league = live_pts + base_rem
                
                if p['pos'] in ['DST', 'K']: final_mean_vegas = final_mean_league; src = "League"
                
                matchup[side].append({'name': p['name'], 'mean': final_mean_vegas, 'std': b_std * decay})
                
                dbg['players'].append({
                    "name": p['name'], "pos": p['pos'], "team": side.upper(),
                    "live_score": round(live_pts, 2),
                    "league_proj": round(final_mean_league, 2),
                    "my_proj": round(final_mean_vegas, 2),
                    "source": src
                })
        
        debug_list.append(dbg)
        
        h_wins = 0
        for _ in range(SIM_COUNT):
            hs = 0; as_ = 0
            for p in matchup['home']: hs += random.gauss(p['mean'], p['std'])
            for p in matchup['away']: as_ += random.gauss(p['mean'], p['std'])
            hs += random.gauss(0, 12.0)
            as_ += random.gauss(0, 12.0)
            if hs > as_: h_wins += 1
            
        win_pct = (h_wins / SIM_COUNT) * 100
        hedge = int((payouts['win'] - payouts['loss']) * 0.20)
        
        return {
            "sport": "nfl", "id": str(hash(home['name']+away['name'])%100000), 
            "status": tag, "state": "in", "is_shown": True,
            "home_abbr": "ME", "home_score": f"{win_pct:.2f}", 
            "home_logo": FANTASY_LOGO, "home_id": "998",
            "away_abbr": "OTH", "away_score": f"{(100-win_pct):.2f}", 
            "away_logo": OPPONENT_LOGO, "away_id": "999",
            "startTimeUTC": datetime.utcnow().isoformat() + "Z", "period": 4,
            "situation": { "possession": "ME", "downDist": f"Hedge: ${hedge}", "isRedZone": False }
        }

def run_loop():
    print(f"Fantasy Oddsmaker Started (Sim: {SIM_COUNT})")
    odds = OddsAPIFetcher(API_KEY); live = LiveGameManager()
    
    # [FIX] Run update IMMEDIATELY on boot
    print("Performing initial live data fetch...")
    live.update()
    
    while True:
        odds.fetch_fresh(); props = odds.get_props()
        live.update() 
        sim = FantasySimulator(odds, live); games = []; dbg = []
        if os.path.exists(CBS_FILE):
            try: games.append(sim.run_sim(sim.load_json(CBS_FILE), props, dbg))
            except: pass
        if os.path.exists(ESPN_FILE):
            try: games.append(sim.run_sim(sim.load_json(ESPN_FILE), props, dbg))
            except: pass
        
        games = [g for g in games if g]
        atomic_write(OUTPUT_FILE, games)
        atomic_write(DEBUG_FILE, dbg)
        gc.collect()
        print(f"Updated: {datetime.now().strftime('%H:%M:%S')}")
        time.sleep(FAST_INTERVAL)

if __name__ == "__main__": run_loop()
