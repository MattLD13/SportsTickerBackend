import requests
import json
import time
import random
import statistics
import difflib
import os
import shutil
import gc
from datetime import datetime

# ================= CONFIGURATION =================
API_KEY = "5da338be7ba612d5e88f889f93dd832f" 
CBS_FILE = "cbs_data.json"
ESPN_FILE = "espn_data.json"
CACHE_FILE = "odds_cache.json"
OUTPUT_FILE = "fantasy_output.json"
DEBUG_FILE = "fantasy_debug.json"

FAST_INTERVAL = 60    
SLOW_INTERVAL = 10800 # 3 Hours

SIM_COUNT = 20000 

LEAGUE_VOLATILITY = { "CBS": 0.20, "ESPN": 0.35, "DEFAULT": 0.25 }
LEAGUE_PAYOUTS = { "CBS": {"win": 1770, "loss": 1100}, "ESPN": {"win": 1000, "loss": 500} }

PROP_MARKETS = [
    "player_pass_yds", "player_pass_tds", "player_pass_interceptions",
    "player_rush_yds", "player_rush_tds", "player_reception_yds", 
    "player_reception_tds", "player_receptions", "player_anytime_td"
]

# GENERIC LOGOS FOR FANTASY
FANTASY_LOGO = "https://a.espncdn.com/i/teamlogos/ncaa/500/172.png" 
OPPONENT_LOGO = "https://a.espncdn.com/i/teamlogos/ncaa/500/193.png" 

def atomic_write(filename, data):
    temp_file = f"{filename}.tmp"
    try:
        with open(temp_file, 'w') as f: json.dump(data, f)
        os.replace(temp_file, filename)
    except:
        if os.path.exists(temp_file): os.remove(temp_file)

class LiveESPNFetcher:
    def __init__(self):
        self.url = "http://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard"
        self.live_data = {}
    def fetch_live_stats(self):
        try:
            r = requests.get(self.url, params={'limit': 100}, timeout=10)
            if r.status_code == 200: self._parse_events(r.json().get('events', []))
        except: pass
    def _parse_events(self, events):
        temp = {}
        for e in events:
            st = e.get('status', {}); state = st.get('type', {}).get('state', 'pre')
            period = st.get('period', 1); rem = 1.0
            if state == 'in': rem = ((4 - period) * 15) / 60.0
            elif state == 'post': rem = 0.0
            if state == 'in': self._fetch_summary(e['id'], temp, rem)
        self.live_data = temp
    def _fetch_summary(self, eid, p_map, rem):
        try:
            r = requests.get(f"http://site.api.espn.com/apis/site/v2/sports/football/nfl/summary?event={eid}", timeout=5)
            d = r.json()
            for tm in d.get('boxscore', {}).get('players', []):
                for grp in tm.get('statistics', []):
                    keys = grp['keys']
                    for ath in grp.get('athletes', []):
                        nm = ath['athlete']['displayName']; stats = ath['stats']; pts = 0.0
                        try:
                            if grp['name'] == 'passing':
                                pts += (float(stats[keys.index('yds')])*0.04) + (float(stats[keys.index('tds')])*4) - (float(stats[keys.index('ints')])*2)
                            elif grp['name'] == 'rushing':
                                pts += (float(stats[keys.index('yds')])*0.1) + (float(stats[keys.index('tds')])*6)
                            elif grp['name'] == 'receiving':
                                pts += (float(stats[keys.index('yds')])*0.1) + (float(stats[keys.index('tds')])*6) + (float(stats[keys.index('rec')])*0.5)
                        except: pass
                        if nm not in p_map: p_map[nm] = {'score': 0.0, 'rem': rem}
                        p_map[nm]['score'] += pts
        except: pass
    def get_live(self, name):
        clean = name.split('.')[-1].strip().lower()
        for k, v in self.live_data.items():
            if clean in k.lower(): return v
        return None

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

class FantasySimulator:
    def __init__(self, fetcher, live_fetcher):
        self.fetcher = fetcher; self.live_fetcher = live_fetcher
    def load_json(self, path):
        if not os.path.exists(path): return None
        try:
            with open(path, 'r') as f: return json.load(f)
        except: return None
    def fuzzy_match(self, name, api_names):
        target = name.split('.')[-1].strip().lower(); best = None; hi = 0.0
        for api in api_names:
            clean = api.split(' ')[-1].strip().lower()
            if target == clean:
                if name[0].lower() == api[0].lower(): return api
            ratio = difflib.SequenceMatcher(None, name.lower(), api.lower()).ratio()
            if ratio > hi: hi = ratio; best = api
        return best if hi > 0.8 else None
    
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

    def calc_pts(self, stats, rules):
        s = 0.0
        p_yds = stats.get('player_pass_yds', 0); p_tds = stats.get('player_pass_tds', 0)
        if p_yds > 0 and p_tds == 0: p_tds = p_yds / 160.0
        s += (p_yds*0.04) + (p_tds*rules['passing']['touchdown'])
        if p_yds >= 300: s += rules['passing']['bonuses'].get('300_yards', 0)
        
        r_yds = stats.get('player_rush_yds', 0); r_tds = stats.get('player_rush_tds', 0)
        rec_yds = stats.get('player_reception_yds', 0); rec_tds = stats.get('player_reception_tds', 0)
        recs = stats.get('player_receptions', 0)
        s += (r_yds*0.1) + (rec_yds*0.1)
        
        tot_td = r_tds + rec_tds
        if tot_td == 0 and 'anytime_td_prob' in stats: s += stats['anytime_td_prob'] * 6.0
        elif tot_td > 0: s += (r_tds*6) + (rec_tds*6)
        else: s += ((r_yds/90.0)*6) + ((rec_yds/90.0)*6)
        
        if rec_yds > 0 and recs == 0: recs = rec_yds / 11.0
        s += recs * rules['receiving'].get('ppr', 0)
        return s

    def run_sim(self, json_data, props_map, debug_list):
        if not json_data: return None
        home = json_data['matchup']['home_team']; away = json_data['matchup']['away_team']
        plat = json_data.get('league_settings', {}).get('platform', 'Fantasy')
        tag = "CBS" if "CBS" in plat else ("ESPN" if "ESPN" in plat else "Fantasy")
        vol = LEAGUE_VOLATILITY.get(tag, 0.5); payouts = LEAGUE_PAYOUTS.get(tag, {"win":0, "loss":0})
        
        matchup = {'home': [], 'away': []}
        dbg = {"platform": tag, "home_team": home['name'], "away_team": away['name'], "players": []}

        for side in ['home', 'away']:
            team = home if side == 'home' else away
            for p in team['roster']:
                base = p['proj']; b_std = base*vol; src = "League"
                live = self.live_fetcher.get_live(p['name'])
                l_score = live['score'] if live else 0.0; rem = live['rem'] if live else 1.0
                
                v_proj = None
                if rem > 0:
                    for eid, pm in props_map.items():
                        names = set()
                        for b in pm.get('bookmakers', []):
                            for m in b.get('markets', []):
                                for o in m.get('outcomes', []):
                                    if 'description' in o: names.add(o['description'])
                                    if 'name' in o: names.add(o['name'])
                        match = self.fuzzy_match(p['name'], list(names))
                        if match:
                            stats, cnt = self.get_proj(match, pm)
                            if cnt > 0:
                                v_proj = self.calc_pts(stats, json_data['scoring_rules'])
                                b_std = v_proj*vol; src = "Vegas"
                            break
                
                if v_proj is not None and v_proj < (base * 0.7): v_proj = base; src = "League (Low Vegas)"
                
                final_proj = (v_proj if v_proj else base)
                final_mean = l_score + (final_proj * rem)
                if p['pos'] in ['DST', 'K']: final_mean = l_score + (base * rem); src = "League"
                
                matchup[side].append({'name': p['name'], 'mean': final_mean, 'std': b_std})
                dbg['players'].append({"name": p['name'], "pos": p['pos'], "team": side.upper(), "league_proj": round(l_score+(base*rem), 2), "my_proj": round(final_mean, 2), "source": src})
        
        debug_list.append(dbg)
        
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
        hedge = int((payouts['win'] - payouts['loss']) * 0.20)
        
        return {
            "sport": "nfl", 
            "id": str(hash(home['name']+away['name'])%100000), 
            "status": tag,
            "state": "in",
            "is_shown": True,
            "home_abbr": "ME", 
            "home_score": f"{win_pct:.2f}",
            "home_logo": FANTASY_LOGO,
            "home_id": "998",
            "away_abbr": "OTH", 
            "away_score": f"{(100-win_pct):.2f}",
            "away_logo": OPPONENT_LOGO,
            "away_id": "999",
            "startTimeUTC": datetime.utcnow().isoformat() + "Z",
            "period": 4,
            "situation": {
                "possession": "ME", 
                "downDist": f"Hedge: ${hedge}",
                "isRedZone": False
            }
        }

def run_loop():
    print(f"Fantasy Oddsmaker Started (Sim: {SIM_COUNT})")
    odds = OddsAPIFetcher(API_KEY); live = LiveESPNFetcher()
    time.sleep(5) 
    while True:
        odds.fetch_fresh(); props = odds.get_props()
        live.fetch_live_stats()
        sim = FantasySimulator(odds, live); games = []; dbg = []
        if os.path.exists(CBS_FILE):
            try: games.append(sim.run_sim(sim.load_json(CBS_FILE), props, dbg))
            except: pass
        if os.path.exists(ESPN_FILE):
            try: games.append(sim.run_sim(sim.load_json(ESPN_FILE), props, dbg))
            except: pass
        
        atomic_write(OUTPUT_FILE, games)
        atomic_write(DEBUG_FILE, dbg)
        gc.collect()
        print(f"Updated: {datetime.now().strftime('%H:%M:%S')}")
        time.sleep(FAST_INTERVAL)

if __name__ == "__main__": run_loop()
