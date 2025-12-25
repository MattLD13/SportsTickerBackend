import time
import threading
import json
import os
import requests
import random
import statistics
import difflib
import gc
from datetime import datetime as dt
from flask import Flask, jsonify

# ================= CONFIGURATION =================
API_KEY = "5da338be7ba612d5e88f889f93dd832f"
CBS_FILE = "cbs_data.json"
ESPN_FILE = "espn_data.json"

# === PORT CONFIGURATION (CRITICAL FIX) ===
# Railway provides the port in the environment variable. 
# We must use it, or the container will be killed.
PORT = int(os.environ.get("PORT", 5000))
UPDATE_INTERVAL = 60  

# TUNING (Low Memory Mode)
SIM_COUNT = 1000 
LEAGUE_VOLATILITY = { "CBS": 0.40, "ESPN": 0.65, "DEFAULT": 0.50 }
LEAGUE_PAYOUTS = { "CBS": {"win": 1770, "loss": 1100}, "ESPN": {"win": 1000, "loss": 500} }

PROP_MARKETS = [
    "player_pass_yds", "player_pass_tds", "player_pass_interceptions",
    "player_rush_yds", "player_rush_tds", "player_reception_yds", 
    "player_reception_tds", "player_receptions", "player_anytime_td"
]

# GLOBAL STATE (In-Memory)
data_lock = threading.Lock()
GLOBAL_STATE = {
    'ticker_data': [],      
    'fantasy_debug': [],    
    'last_updated': "Initializing...",
    'status': "Booting..."
}

# ================= 1. DATA FETCHERS =================
class LiveESPNFetcher:
    def __init__(self):
        self.url = "http://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard"
        self.live_data = {}

    def fetch_live_stats(self):
        try:
            r = requests.get(self.url, params={'limit': 100}, timeout=5)
            if r.status_code == 200: self._parse_events(r.json().get('events', []))
        except: pass

    def _parse_events(self, events):
        temp_map = {}
        for e in events:
            st = e.get('status', {}); state = st.get('type', {}).get('state', 'pre')
            period = st.get('period', 1); time_rem = 1.0
            if state == 'in': time_rem = ((4 - period) * 15) / 60.0
            elif state == 'post': time_rem = 0.0
            if state == 'in': self._fetch_summary(e['id'], temp_map, time_rem)
        self.live_data = temp_map

    def _fetch_summary(self, evt_id, p_map, rem):
        try:
            r = requests.get(f"http://site.api.espn.com/apis/site/v2/sports/football/nfl/summary?event={evt_id}", timeout=5)
            d = r.json(); bx = d.get('boxscore', {})
            if not bx: return
            for tm in bx.get('players', []):
                for grp in tm.get('statistics', []):
                    keys = grp.get('keys', [])
                    for ath in grp.get('athletes', []):
                        try:
                            nm = ath['athlete']['displayName']; stats = ath['stats']; pts = 0.0
                            if grp['name'] == 'passing':
                                pts += (float(stats[keys.index('yds')])*0.04) + (float(stats[keys.index('tds')])*4) - (float(stats[keys.index('ints')])*2)
                            elif grp['name'] == 'rushing':
                                pts += (float(stats[keys.index('yds')])*0.1) + (float(stats[keys.index('tds')])*6)
                            elif grp['name'] == 'receiving':
                                pts += (float(stats[keys.index('yds')])*0.1) + (float(stats[keys.index('tds')])*6) + (float(stats[keys.index('rec')])*0.5)
                            if nm not in p_map: p_map[nm] = {'score': 0.0, 'rem': rem}
                            p_map[nm]['score'] += pts
                        except: pass
        except: pass

    def get_live(self, name):
        clean = name.split('.')[-1].strip().lower()
        for k, v in self.live_data.items():
            if clean in k.lower(): return v
        return None

class OddsAPIFetcher:
    def __init__(self, api_key):
        self.key = api_key; self.base = "https://api.the-odds-api.com/v4/sports/americanfootball_nfl"
        self.cache = {}; self.last_fetch = 0

    def fetch_fresh(self):
        if time.time() - self.last_fetch < 600: return
        print("[Vegas] Updating odds...")
        try:
            r = requests.get(f"{self.base}/events?apiKey={self.key}", timeout=5)
            if r.status_code == 200:
                events = r.json(); self.cache = {'events': events}
                for e in events:
                    mkts = ",".join(PROP_MARKETS)
                    time.sleep(0.2) 
                    r2 = requests.get(f"{self.base}/events/{e['id']}/odds?apiKey={self.key}&regions=us&markets={mkts}&oddsFormat=american", timeout=5)
                    if r2.status_code == 200: self.cache[f"props_{e['id']}"] = r2.json()
                self.last_fetch = time.time()
        except: pass

    def get_props(self):
        res = {}; events = self.cache.get('events', [])
        for e in events:
            p = self.cache.get(f"props_{e['id']}")
            if p: res[e['id']] = p
        return res

# ================= 2. CALCULATOR =================
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
        max_std = 0; risk_p = "None"
        for n, vals in p_vol.items():
            s = statistics.stdev(vals)
            if s > max_std: max_std = s; risk_p = n
        
        poss = ""; risk_h = False
        for p in matchup['home']:
            if p['name'] == risk_p: poss = "ME"; risk_h = True; break
        if not poss: poss = "OTH"
        
        hedge = int((payouts['win'] - payouts['loss']) * 0.20)
        
        return {
            "sport": "nfl", "id": str(hash(home['name']+away['name'])%100000), "status": tag,
            "home_abbr": "ME", "home_score": f"{win_pct:.2f}",
            "away_abbr": "OTH", "away_score": f"{(100-win_pct):.2f}",
            "is_shown": True,
            "situation": {"possession": poss, "downDist": f"Hedge: ${hedge}"}
        }

# ================= 3. THREAD WORKER =================
def oddsmaker_thread():
    print(">>> Startup Delay (5s) for Railway...")
    time.sleep(5)
    
    odds = OddsAPIFetcher(API_KEY)
    live = LiveESPNFetcher()
    sim = FantasySimulator(odds, live)
    
    while True:
        with data_lock: GLOBAL_STATE['status'] = "Updating..."
        try:
            odds.fetch_fresh()
            props = odds.get_props()
            live.fetch_live_stats()
            
            games_out = []; debug_out = []
            
            if os.path.exists(CBS_FILE):
                try: games_out.append(sim.run_sim(sim.load_json(CBS_FILE), props, debug_out))
                except: pass

            if os.path.exists(ESPN_FILE):
                try: games_out.append(sim.run_sim(sim.load_json(ESPN_FILE), props, debug_out))
                except: pass
                
            with data_lock:
                GLOBAL_STATE['ticker_data'] = [g for g in games_out if g]
                GLOBAL_STATE['fantasy_debug'] = debug_out
                GLOBAL_STATE['last_updated'] = dt.now().strftime("%I:%M:%S %p")
                GLOBAL_STATE['status'] = "Idle"
            gc.collect() 
        except Exception as e: print(f"Error: {e}")
        
        time.sleep(UPDATE_INTERVAL)

# ================= 4. FLASK SERVER =================
app = Flask(__name__)

@app.route('/')
def root():
    return """<html><body style='background:#111;color:#eee;font-family:sans-serif;padding:2rem'>
    <h1>Server Online</h1><ul><li><a style='color:#4dabf7' href='/fantasy'>Dashboard</a></li><li><a style='color:#4dabf7' href='/api/ticker'>JSON Output</a></li></ul></body></html>"""

@app.route('/fantasy')
def fantasy_page():
    with data_lock:
        data = GLOBAL_STATE['fantasy_debug']; ts = GLOBAL_STATE['last_updated']; st = GLOBAL_STATE['status']
    
    if not data: return f"<h3>Status: {st}</h3><p>Waiting for cycle...</p><script>setTimeout(()=>location.reload(), 3000)</script>"

    html = f"""<html><head><title>Fantasy Odds</title><meta http-equiv="refresh" content="30"><style>
        body{{font-family:sans-serif;background:#121212;color:#eee;padding:20px}}
        .matchup{{background:#1e1e1e;padding:20px;border-radius:10px;margin-bottom:20px; border:1px solid #333}}
        h2{{color:#4dabf7;border-bottom:1px solid #333;padding-bottom:10px; margin-top:0}}
        h3{{color:#bbb; margin-top:20px; border-bottom:1px solid #444; display:inline-block; font-size:1.1rem}}
        table{{width:100%;border-collapse:collapse;margin-top:5px; margin-bottom:15px; font-size:14px}}
        th{{text-align:left;color:#888;font-size:12px;padding:8px;background:#252525}}
        td{{padding:8px;border-bottom:1px solid #333}}
        .src-v{{color:#40c057;font-weight:bold; background:rgba(64,192,87,0.1); padding:2px 6px; border-radius:4px}}
        .good{{color:#40c057; font-weight:bold}} .bad{{color:#ff6b6b}}
        .time{{color:#555; font-size:12px; margin-bottom:20px; text-align:right}}
    </style></head><body><div class="time">Updated: {ts} | Status: {st}</div>"""
    
    for g in data:
        html += f"<div class='matchup'><h2>{g['platform']}: {g['home_team']} vs {g['away_team']}</h2>"
        for side in ['HOME', 'AWAY']:
            plys = [p for p in g['players'] if p['team'] == side]
            tm = g['home_team'] if side == 'HOME' else g['away_team']
            html += f"<h3>{tm}</h3><table><thead><tr><th width='30%'>PLAYER</th><th width='10%'>POS</th><th width='20%'>LEAGUE</th><th width='20%'>MY PROJ</th><th width='20%'>SOURCE</th></tr></thead><tbody>"
            l_sum = 0; m_sum = 0
            for p in plys:
                l_sum += p['league_proj']; m_sum += p['my_proj']
                cls = "good" if p['my_proj'] > p['league_proj'] else "bad"
                src = "src-v" if "Vegas" in p['source'] else ""
                html += f"<tr><td>{p['name']}</td><td>{p['pos']}</td><td>{p['league_proj']:.2f}</td><td class='{cls}'>{p['my_proj']:.2f}</td><td><span class='{src}'>{p['source']}</span></td></tr>"
            d = m_sum - l_sum; dc = "#40c057" if d > 0 else "#ff6b6b"
            html += f"<tr style='background:#2a2a2a;font-weight:bold'><td>TOTAL</td><td></td><td>{l_sum:.2f}</td><td style='color:{dc}'>{m_sum:.2f} ({d:+.2f})</td><td></td></tr></tbody></table>"
        html += "</div>"
    return html + "</body></html>"

@app.route('/api/ticker')
def api_ticker():
    with data_lock: return jsonify({'games': GLOBAL_STATE['ticker_data']})

if __name__ == "__main__":
    t = threading.Thread(target=oddsmaker_thread, daemon=True)
    t.start()
    
    # CRITICAL: BIND TO 0.0.0.0 AND THE PORT RAILWAY GIVES
    print(f"Starting server on port {PORT}")
    app.run(host='0.0.0.0', port=PORT, debug=False)
