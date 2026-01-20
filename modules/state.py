import threading
import os
import json
import glob
from modules.config import DEFAULT_STATE, GLOBAL_CONFIG_FILE, TICKER_DATA_DIR, DEFAULT_TICKER_SETTINGS
from modules.utils import save_json_atomically

data_lock = threading.Lock()

# Initialize state with a proper deep copy logic where needed
state = {
    'active_sports': DEFAULT_STATE['active_sports'].copy(),
    'mode': DEFAULT_STATE['mode'],
    'layout_mode': DEFAULT_STATE['layout_mode'],
    'my_teams': list(DEFAULT_STATE['my_teams']),
    'current_games': list(DEFAULT_STATE['current_games']),
    'buffer_sports': list(DEFAULT_STATE['buffer_sports']),
    'buffer_stocks': list(DEFAULT_STATE['buffer_stocks']),
    'all_teams_data': DEFAULT_STATE['all_teams_data'].copy(),
    'debug_mode': DEFAULT_STATE['debug_mode'],
    'custom_date': DEFAULT_STATE['custom_date'],
    'weather_city': DEFAULT_STATE['weather_city'],
    'weather_lat': DEFAULT_STATE['weather_lat'],
    'weather_lon': DEFAULT_STATE['weather_lon'],
    'utc_offset': DEFAULT_STATE['utc_offset'],
    'show_debug_options': DEFAULT_STATE['show_debug_options']
}

tickers = {}

def load_state():
    # 1. Load Global Config (Defaults)
    if os.path.exists(GLOBAL_CONFIG_FILE):
        try:
            with open(GLOBAL_CONFIG_FILE, 'r') as f:
                loaded = json.load(f)
                for k, v in loaded.items():
                    if k in state:
                        if isinstance(state[k], dict) and isinstance(v, dict):
                            state[k].update(v)
                        else:
                            state[k] = v
        except Exception as e:
            print(f"⚠️ Error loading global config: {e}")

    # 2. Load Individual Ticker Files (Robust)
    if not os.path.exists(TICKER_DATA_DIR):
        os.makedirs(TICKER_DATA_DIR)

    ticker_files = glob.glob(os.path.join(TICKER_DATA_DIR, "*.json"))
    print(f"📂 Found {len(ticker_files)} saved tickers in '{TICKER_DATA_DIR}'")

    for t_file in ticker_files:
        try:
            with open(t_file, 'r') as f:
                t_data = json.load(f)
                tid = os.path.splitext(os.path.basename(t_file))[0]

                # Repair missing keys on load
                if 'settings' not in t_data: t_data['settings'] = DEFAULT_TICKER_SETTINGS.copy()
                if 'my_teams' not in t_data: t_data['my_teams'] = []
                if 'clients' not in t_data: t_data['clients'] = []

                tickers[tid] = t_data
        except Exception as e:
            print(f"❌ Failed to load ticker file {t_file}: {e}")

def save_global_config():
    """Saves only the global server settings (weather, sports mode, etc)"""
    try:
        with data_lock:
            # Create a clean copy of state to save
            export_data = {
                'active_sports': state['active_sports'],
                'mode': state['mode'],
                'my_teams': state['my_teams'], # Global default teams
                'weather_city': state['weather_city'],
                'weather_lat': state['weather_lat'],
                'weather_lon': state['weather_lon'],
                'utc_offset': state['utc_offset']
            }

        # Atomic Write
        save_json_atomically(GLOBAL_CONFIG_FILE, export_data)
    except Exception as e:
        print(f"Error saving global config: {e}")

def save_specific_ticker(tid):
    """Saves ONLY the specified ticker to its own file"""
    if tid not in tickers: return
    try:
        data = tickers[tid]
        filepath = os.path.join(TICKER_DATA_DIR, f"{tid}.json")
        save_json_atomically(filepath, data)
        print(f"💾 Saved Ticker: {tid}")
    except Exception as e:
        print(f"Error saving ticker {tid}: {e}")
