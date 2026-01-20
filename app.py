import time
import threading
import os
import sys
from flask import Flask, jsonify, request
from flask_cors import CORS
from dotenv import load_dotenv

# Import Modules
from modules.config import (
    SERVER_VERSION, SPORTS_UPDATE_INTERVAL, STOCKS_UPDATE_INTERVAL,
    LEAGUE_OPTIONS, DEFAULT_TICKER_SETTINGS
)
from modules.state import (
    state, tickers, data_lock, load_state, save_global_config, save_specific_ticker
)
from modules.utils import Tee, generate_pairing_code
from modules.fetchers.sports import SportsFetcher

# Load environment variables
load_dotenv()

# ================= LOGGING SETUP =================
try:
    if not os.path.exists("ticker.log"):
        with open("ticker.log", "w") as f: f.write("--- Log Started ---\n")
    Tee("ticker.log", "a")
except Exception as e:
    print(f"Logging setup failed: {e}")

# ================= CACHE CLEANUP ON STARTUP =================
if os.path.exists("stock_cache.json"):
    try:
        print("🧹 Wiping old stock cache on startup...")
        os.remove("stock_cache.json")
    except: pass

# ================= LOAD STATE =================
load_state()

# Initialize Global Fetcher
fetcher = SportsFetcher(
    initial_city=state['weather_city'], 
    initial_lat=state['weather_lat'], 
    initial_lon=state['weather_lon']
)

# ================= WORKER LOOPS =================
def sports_worker():
    try: fetcher.fetch_all_teams()
    except: pass
    
    while True:
        start_time = time.time()
        
        try: 
            fetcher.update_buffer_sports()
        except Exception as e: 
            print(f"Sports Worker Error: {e}")
            
        execution_time = time.time() - start_time
        sleep_dur = max(0, SPORTS_UPDATE_INTERVAL - execution_time)
        time.sleep(sleep_dur)

def stocks_worker():
    while True:
        try: 
            with data_lock:
                active_cats = [k for k, v in state['active_sports'].items() if k.startswith('stock_') and v]
            fetcher.stocks.update_market_data(active_cats)
            fetcher.update_buffer_stocks()
        except Exception as e: 
            print(f"Stock worker error: {e}")
        time.sleep(1)

# ================= FLASK API =================
app = Flask(__name__)
CORS(app) 

@app.route('/api/config', methods=['POST'])
def api_config():
    try:
        new_data = request.json
        if not isinstance(new_data, dict): return jsonify({"error": "Invalid payload"}), 400
        
        # 1. Determine which ticker is being targeted
        target_id = new_data.get('ticker_id') or request.args.get('id')
        
        cid = request.headers.get('X-Client-ID')
        
        # If we have a CID, try to find the associated ticker
        if not target_id and cid:
            for tid, t_data in tickers.items():
                if cid in t_data.get('clients', []):
                    target_id = tid
                    break
        
        # Fallback for single-ticker setups
        if not target_id and len(tickers) == 1: 
            target_id = list(tickers.keys())[0]

        # ================= SECURITY CHECK START =================
        if target_id and target_id in tickers:
            rec = tickers[target_id]
            if cid not in rec.get('clients', []):
                print(f"⛔ Blocked unauthorized config change from {cid}")
                return jsonify({"error": "Unauthorized: Device not paired"}), 403
        # ================== SECURITY CHECK END ==================

        with data_lock:
            # Update Weather (Global)
            new_city = new_data.get('weather_city')
            if new_city: 
                fetcher.weather.update_config(city=new_city, lat=new_data.get('weather_lat'), lon=new_data.get('weather_lon'))
            
            allowed_keys = {'active_sports', 'mode', 'layout_mode', 'my_teams', 'debug_mode', 'custom_date', 'weather_city', 'weather_lat', 'weather_lon', 'utc_offset'}
            
            for k, v in new_data.items():
                if k not in allowed_keys: continue
                
                # HANDLE TEAMS
                if k == 'my_teams' and isinstance(v, list):
                    cleaned = []
                    seen = set()
                    for e in v:
                        if e:
                            k_str = str(e).strip()
                            if k_str == "LV": k_str = "ahl:LV"
                            if k_str not in seen:
                                seen.add(k_str)
                                cleaned.append(k_str)
                    
                    if target_id and target_id in tickers:
                        tickers[target_id]['my_teams'] = cleaned
                    else:
                        state['my_teams'] = cleaned
                    continue

                # HANDLE ACTIVE SPORTS
                if k == 'active_sports' and isinstance(v, dict): 
                    state['active_sports'].update(v)
                    continue
                
                # HANDLE MODES & SETTINGS
                if v is not None: state[k] = v
                
                # SYNC TO TICKER SETTINGS
                if target_id and target_id in tickers:
                    if k in tickers[target_id]['settings'] or k == 'mode':
                        tickers[target_id]['settings'][k] = v
            
            fetcher.merge_buffers()
        
        if target_id:
            save_specific_ticker(target_id)
        else:
            save_global_config()
        
        current_teams = tickers[target_id].get('my_teams', []) if (target_id and target_id in tickers) else state['my_teams']
        
        return jsonify({"status": "ok", "saved_teams": current_teams, "ticker_id": target_id})
        
    except Exception as e:
        print(f"Config Error: {e}") 
        return jsonify({"error": "Failed"}), 500

@app.route('/leagues', methods=['GET'])
def get_league_options():
    league_meta = []
    for item in LEAGUE_OPTIONS:
         league_meta.append({
             'id': item['id'], 
             'label': item['label'], 
             'type': item['type'],
             'enabled': state['active_sports'].get(item['id'], False)
         })
    return jsonify(league_meta)

@app.route('/data', methods=['GET'])
def get_ticker_data():
    ticker_id = request.args.get('id')
    
    # 1. Default to the first ticker if none specified
    if not ticker_id and len(tickers) == 1: 
        ticker_id = list(tickers.keys())[0]
    
    # 2. Safety check: If ID is invalid, return generic config to prevent crash
    if not ticker_id or ticker_id not in tickers:
        return jsonify({
            "status": "ok",
            "global_config": state,
            "local_config": DEFAULT_TICKER_SETTINGS,
            "content": { "sports": fetcher.get_snapshot_for_delay(0) }
        })

    rec = tickers[ticker_id]
    rec['last_seen'] = time.time()
    
    # Pairing Check
    if not rec.get('clients') or not rec.get('paired'):
        if not rec.get('pairing_code'):
            rec['pairing_code'] = generate_pairing_code(tickers)
            save_specific_ticker(ticker_id)
        return jsonify({ "status": "pairing", "code": rec['pairing_code'] })

    # 3. Standard Data Fetching
    t_settings = rec['settings']
    saved_teams = rec.get('my_teams', []) 
    current_mode = t_settings.get('mode', 'all') 

    delay_seconds = t_settings.get('live_delay_seconds', 0) if t_settings.get('live_delay_mode') else 0
    raw_games = fetcher.get_snapshot_for_delay(delay_seconds)
    
    visible_games = []
    COLLISION_ABBRS = {'LV'} 

    for g in raw_games:
        should_show = True
        if current_mode == 'live' and g.get('state') not in ['in', 'half']: should_show = False
        elif current_mode == 'my_teams':
            sport = g.get('sport')
            h_abbr = str(g.get('home_abbr', '')).upper()
            a_abbr = str(g.get('away_abbr', '')).upper()
            h_scoped = f"{sport}:{h_abbr}"
            a_scoped = f"{sport}:{a_abbr}"
            
            if h_abbr in COLLISION_ABBRS: in_home = h_scoped in saved_teams
            else: in_home = (h_scoped in saved_teams or h_abbr in saved_teams)

            if a_abbr in COLLISION_ABBRS: in_away = a_scoped in saved_teams
            else: in_away = (a_scoped in saved_teams or a_abbr in saved_teams)
            
            if not (in_home or in_away): should_show = False

        status_lower = str(g.get('status', '')).lower()
        if any(k in status_lower for k in ["postponed", "suspended", "canceled", "ppd"]):
            should_show = False

        if should_show:
            visible_games.append(g)
    
    # Construct the response config
    g_config = { "mode": current_mode }
    
    # Handle Reboot Flag
    if rec.get('reboot_requested', False):
        g_config['reboot'] = True

    # Handle Update Flag (NEW)
    if rec.get('update_requested', False):
        g_config['update'] = True
        
    response = jsonify({ 
        "status": "ok", 
        "version": SERVER_VERSION,
        "global_config": g_config, 
        "local_config": t_settings, 
        "content": { "sports": visible_games } 
    })
    
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    
    return response

@app.route('/pair', methods=['POST'])
def pair_ticker():
    try:
        cid = request.headers.get('X-Client-ID')
        json_body = request.json or {}
        code = json_body.get('code')
        friendly_name = json_body.get('name', 'My Ticker')
        
        print(f"🔗 Pairing Attempt from Client: {cid} | Code: {code}")

        if not cid or not code:
            print("❌ Missing CID or Code")
            return jsonify({"success": False, "message": "Missing Data"}), 400
        
        input_code = str(code).strip()

        for uid, rec in tickers.items():
            known_code = str(rec.get('pairing_code', '')).strip()
            
            if known_code == input_code:
                if cid not in rec.get('clients', []):
                    rec['clients'].append(cid)
                
                rec['paired'] = True
                rec['name'] = friendly_name
                save_specific_ticker(uid)
                
                print(f"✅ Paired Successfully to Ticker: {uid}")
                return jsonify({"success": True, "ticker_id": uid})
        
        print(f"❌ Invalid Code. Input: {input_code}")
        return jsonify({"success": False, "message": "Invalid Pairing Code"}), 200

    except Exception as e:
        print(f"🔥 Pairing Server Error: {e}")
        return jsonify({"success": False, "message": "Server Logic Error"}), 500

@app.route('/pair/id', methods=['POST'])
def pair_ticker_by_id():
    cid = request.headers.get('X-Client-ID')
    tid = request.json.get('id')
    friendly_name = request.json.get('name', 'My Ticker')
    
    if not cid or not tid: return jsonify({"success": False}), 400
    
    if tid in tickers:
        if cid not in tickers[tid]['clients']: tickers[tid]['clients'].append(cid)
        tickers[tid]['paired'] = True
        tickers[tid]['name'] = friendly_name
        save_specific_ticker(tid)
        return jsonify({"success": True, "ticker_id": tid})
        
    return jsonify({"success": False}), 404

@app.route('/ticker/<tid>/unpair', methods=['POST'])
def unpair(tid):
    cid = request.headers.get('X-Client-ID')
    if tid in tickers and cid in tickers[tid]['clients']:
        tickers[tid]['clients'].remove(cid)
        if not tickers[tid]['clients']: tickers[tid]['paired'] = False; tickers[tid]['pairing_code'] = generate_pairing_code(tickers)
        save_specific_ticker(tid)
    return jsonify({"success": True})

@app.route('/tickers', methods=['GET'])
def list_tickers():
    cid = request.headers.get('X-Client-ID'); 
    if not cid: return jsonify([])
    res = []
    for uid, rec in tickers.items():
        if cid in rec.get('clients', []): res.append({ "id": uid, "name": rec.get('name', 'Ticker'), "settings": rec['settings'], "last_seen": rec.get('last_seen', 0) })
    return jsonify(res)

@app.route('/ticker/<tid>', methods=['POST'])
def update_settings(tid):
    if tid not in tickers: return jsonify({"error":"404"}), 404

    cid = request.headers.get('X-Client-ID')
    rec = tickers[tid]
    
    if not cid or cid not in rec.get('clients', []):
        print(f"⛔ Blocked unauthorized settings change from {cid}")
        return jsonify({"error": "Unauthorized: Device not paired"}), 403

    rec['settings'].update(request.json)
    save_specific_ticker(tid)
    
    print(f"✅ Updated Settings for {tid}: {request.json}")
    return jsonify({"success": True})

@app.route('/api/state', methods=['GET'])
def api_state():
    ticker_id = request.args.get('id')
    if not ticker_id:
        cid = request.headers.get('X-Client-ID')
        if cid:
            for tid, t_data in tickers.items():
                if cid in t_data.get('clients', []):
                    ticker_id = tid
                    break
    
    if not ticker_id and len(tickers) == 1:
        ticker_id = list(tickers.keys())[0]

    response_settings = state.copy()
    
    if ticker_id and ticker_id in tickers:
        local_settings = tickers[ticker_id]['settings']
        response_settings.update(local_settings)
        response_settings['my_teams'] = tickers[ticker_id].get('my_teams', [])
        response_settings['ticker_id'] = ticker_id 
    
    # 1. Get ALL raw games
    raw_games = fetcher.get_snapshot_for_delay(0)
    
    # 2. Create a copy to modify 'is_shown' without affecting the global cache
    processed_games = []

    current_mode = response_settings.get('mode', 'all')
    saved_teams = response_settings.get('my_teams', [])
    COLLISION_ABBRS = {'LV'}

    for g in raw_games:
        game_copy = g.copy()
        should_show = True
        
        if current_mode == 'live' and game_copy.get('state') not in ['in', 'half']: 
            should_show = False
        elif current_mode == 'my_teams':
            sport = game_copy.get('sport')
            h_abbr = str(game_copy.get('home_abbr', '')).upper()
            a_abbr = str(game_copy.get('away_abbr', '')).upper()
            h_scoped = f"{sport}:{h_abbr}"
            a_scoped = f"{sport}:{a_abbr}"
            
            if h_abbr in COLLISION_ABBRS: in_home = h_scoped in saved_teams
            else: in_home = (h_scoped in saved_teams or h_abbr in saved_teams)

            if a_abbr in COLLISION_ABBRS: in_away = a_scoped in saved_teams
            else: in_away = (a_scoped in saved_teams or a_abbr in saved_teams)
            
            if not (in_home or in_away): 
                should_show = False

        status_lower = str(game_copy.get('status', '')).lower()
        if any(k in status_lower for k in ["postponed", "suspended", "canceled", "ppd"]):
            should_show = False

        game_copy['is_shown'] = should_show
        processed_games.append(game_copy)

    return jsonify({
        "status": "ok",
        "settings": response_settings,
        "games": processed_games 
    })

@app.route('/api/teams')
def api_teams():
    with data_lock: return jsonify(state['all_teams_data'])

@app.route('/api/hardware', methods=['POST'])
def api_hardware():
    try:
        data = request.json or {}
        action = data.get('action')
        ticker_id = data.get('ticker_id')
        
        if action == 'update':
            with data_lock:
                for t in tickers.values(): t['update_requested'] = True
            threading.Timer(60, lambda: [t.update({'update_requested':False}) for t in tickers.values()]).start()
            return jsonify({"status": "ok", "message": "Updating Fleet"})

        if action == 'reboot':
            if ticker_id and ticker_id in tickers:
                with data_lock:
                    tickers[ticker_id]['reboot_requested'] = True
                def clear_flag(tid):
                    with data_lock:
                        if tid in tickers: tickers[tid]['reboot_requested'] = False
                threading.Timer(15, clear_flag, args=[ticker_id]).start()
                return jsonify({"status": "ok", "message": f"Rebooting {ticker_id}"})
            elif len(tickers) > 0:
                target = list(tickers.keys())[0]
                with data_lock:
                    tickers[target]['reboot_requested'] = True
                threading.Timer(15, lambda: tickers[target].update({'reboot_requested': False})).start()
                return jsonify({"status": "ok"})
                
        return jsonify({"status": "ignored"})
    except Exception as e:
        print(f"Hardware API Error: {e}")
        return jsonify({"status": "error"}), 500

@app.route('/api/debug', methods=['POST'])
def api_debug():
    with data_lock: state.update(request.json)
    return jsonify({"status": "ok"})

@app.route('/errors', methods=['GET'])
def get_logs():
    log_file = "ticker.log"
    if not os.path.exists(log_file):
        return "Log file not found", 404
    
    try:
        file_size = os.path.getsize(log_file)
        read_size = min(file_size, 102400) 
        
        log_content = ""
        with open(log_file, 'rb') as f:
            if file_size > read_size:
                f.seek(file_size - read_size)
            data = f.read()
            log_content = data.decode('utf-8', errors='replace')

        html_response = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>Server Logs</title>
            <meta http-equiv="refresh" content="10">
            <style>
                body {{ background-color: #1e1e1e; color: #00ff00; font-family: 'Courier New', monospace; margin: 0; padding: 20px; }}
                pre {{ white-space: pre-wrap; word-wrap: break-word; }}
            </style>
            <script>
                window.onload = function() {{
                    window.scrollTo(0, document.body.scrollHeight);
                }};
            </script>
        </head>
        <body>
            <h3>Last {read_size / 1024:.0f}KB of Logs (Auto-scrolled)</h3>
            <pre>{log_content}</pre>
        </body>
        </html>
        """
        response = app.response_class(response=html_response, status=200, mimetype='text/html')
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
        return response

    except Exception as e:
        return f"Error reading log: {str(e)}", 500

@app.route('/api/my_teams', methods=['GET'])
def check_my_teams():
    ticker_id = request.args.get('id')
    with data_lock:
        global_teams = state.get('my_teams', [])
        if not ticker_id:
            return jsonify({
                "status": "ok",
                "scope": "Global (Default)",
                "count": len(global_teams),
                "teams": global_teams
            })

        if ticker_id in tickers:
            rec = tickers[ticker_id]
            specific_teams = rec.get('my_teams', [])
            using_fallback = len(specific_teams) == 0
            effective = global_teams if using_fallback else specific_teams

            return jsonify({
                "status": "ok",
                "ticker_id": ticker_id,
                "scope": "Ticker Specific",
                "using_global_fallback": using_fallback,
                "saved_specifically_for_ticker": specific_teams,
                "what_the_ticker_actually_sees": effective
            })
        
        return jsonify({"error": "Ticker ID not found"}), 404

@app.route('/')
def root(): return "Ticker Server Running on Version: " + SERVER_VERSION

if __name__ == "__main__":
    threading.Thread(target=sports_worker, daemon=True).start()
    threading.Thread(target=stocks_worker, daemon=True).start()
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 5000)))
