import threading
import json
import os
import subprocess
import re
import time
from datetime import datetime as dt, timezone, timedelta
import requests
from flask import Flask, jsonify, request

# ================= CONFIGURATION =================
TIMEZONE_OFFSET = -5  # Set to -5 for EST/EDT
CONFIG_FILE = "ticker_config.json"
UPDATE_INTERVAL = 15  # Thread Lock for safety
data_lock = threading.Lock()

# --- LOGO OVERRIDES (League-Specific) ---
# Format: "LEAGUE:ABBR": "URL"
# This prevents Washington (NHL) from overriding Washington (NFL)
LOGO_OVERRIDES = {
    # --- NHL FIXES ---
    "NHL:SJS": "https://a.espncdn.com/i/teamlogos/nhl/500/sj.png",
    "NHL:NJD": "https://a.espncdn.com/i/teamlogos/nhl/500/nj.png",
    "NHL:TBL": "https://a.espncdn.com/i/teamlogos/nhl/500/tb.png",
    "NHL:LAK": "https://a.espncdn.com/i/teamlogos/nhl/500/la.png",
    "NHL:VGK": "https://a.espncdn.com/i/teamlogos/nhl/500/vgs.png",
    "NHL:VEG": "https://a.espncdn.com/i/teamlogos/nhl/500/vgs.png",
    "NHL:UTA": "https://a.espncdn.com/i/teamlogos/nhl/500/utah.png",
    # Washington Capitals (Specific Eagle/Secondary Logo)
    "NHL:WSH": "https://a.espncdn.com/guid/cbe677ee-361e-91b4-5cae-6c4c30044743/logos/secondary_logo_on_black_color.png",
    "NHL:WAS": "https://a.espncdn.com/guid/cbe677ee-361e-91b4-5cae-6c4c30044743/logos/secondary_logo_on_black_color.png",
    # --- NFL FIXES ---
    "NFL:WSH": "https://a.espncdn.com/i/teamlogos/nfl/500/wsh.png",  # Commanders
    "NFL:WAS": "https://a.espncdn.com/i/teamlogos/nfl/500/wsh.png",
    # --- MLB FIXES ---
    "MLB:WSH": "https://a.espncdn.com/i/teamlogos/mlb/500/wsh.png",  # Nationals
    "MLB:WAS": "https://a.espncdn.com/i/teamlogos/mlb/500/wsh.png",
    # --- NBA FIXES ---
    "NBA:WSH": "https://a.espncdn.com/i/teamlogos/nba/500/was.png",  # Wizards
    "NBA:WAS": "https://a.espncdn.com/i/teamlogos/nba/500/was.png",
    "NBA:UTA": "https://a.espncdn.com/i/teamlogos/nba/500/utah.png",
    "NBA:NOP": "https://a.espncdn.com/i/teamlogos/nba/500/no.png",
    # --- NCAA FIXES ---
    # Note: NCAA codes often vary, so we map the common 3-letter codes
    "NCF_FBS:CAL": "https://a.espncdn.com/i/teamlogos/ncaa/500/25.png",
    "NCF_FBS:OSU": "https://a.espncdn.com/i/teamlogos/ncaa/500/194.png",
    "NCF_FBS:ORST": "https://a.espncdn.com/i/teamlogos/ncaa/500/204.png",
    "NCF_FBS:MIA": "https://a.espncdn.com/i/teamlogos/ncaa/500/2390.png",
    "NCF_FBS:MIAMI": "https://a.espncdn.com/i/teamlogos/ncaa/500/2390.png",
    "NCF_FBS:HOU": "https://a.espncdn.com/i/teamlogos/ncaa/500/248.png",
    "NCF_FBS:IND": "https://a.espncdn.com/i/teamlogos/ncaa/500/84.png",
    # Lower divisions (FCS)
    "NCF_FCS:LIN": "https://a.espncdn.com/i/teamlogos/ncaa/500/2815.png",
    "NCF_FCS:LEH": "https://a.espncdn.com/i/teamlogos/ncaa/500/2329.png"
}

# ================= DEFAULT STATE =================
default_state = {
    'active_sports': {
        'nfl': True, 'ncf_fbs': True, 'ncf_fcs': True,
        'mlb': True, 'nhl': True, 'nba': True,
        'weather': False, 'clock': False
    },
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
    'test_pattern': False,
    'reboot_requested': False,
    'weather_location': "New York"
}

state = default_state.copy()

# ================= LOAD CONFIG =================
if os.path.exists(CONFIG_FILE):
    try:
        with open(CONFIG_FILE, 'r') as f:
            loaded = json.load(f)
            for k, v in loaded.items():
                if k in state:
                    if isinstance(state[k], dict) and isinstance(v, dict):
                        state[k].update(v)
                    else:
                        state[k] = v
    except:
        pass


def save_config_file():
    try:
        with data_lock:
            export_data = {
                'active_sports': state['active_sports'],
                'mode': state['mode'],
                'scroll_seamless': state['scroll_seamless'],
                'my_teams': state['my_teams'],
                'brightness': state['brightness'],
                'inverted': state['inverted'],
                'panel_count': state['panel_count'],
                'weather_location': state['weather_location']
            }
            with open(CONFIG_FILE, 'w') as f:
                json.dump(export_data, f)
    except Exception as e:
        print(f"Save Config Error: {e}")


# ================= WEATHER FETCHER =================
class WeatherFetcher:
    def __init__(self):
        self.lat = 40.7128  # Default NY
        self.lon = -74.0060
        self.location_name = "New York"
        self.last_fetch = 0
        self.cache = None

    def update_coords(self, location_query):
        clean_query = str(location_query).strip()
        if re.fullmatch(r'\d{5}', clean_query):
            try:
                zip_url = f"https://api.zippopotam.us/us/{clean_query}"
                r = requests.get(zip_url, timeout=5)
                if r.status_code == 200:
                    data = r.json()
                    place = data['places'][0]
                    self.lat = float(place['latitude'])
                    self.lon = float(place['longitude'])
                    self.location_name = place['place name']
                    self.last_fetch = 0
                    return
            except:
                pass
        try:
            url = f"https://geocoding-api.open-meteo.com/v1/search?name={location_query}&count=1&language=en&format=json"
            r = requests.get(url, timeout=5)
            data = r.json()
            if 'results' in data and len(data['results']) > 0:
                res = data['results'][0]
                self.lat = res['latitude']
                self.lon = res['longitude']
                self.location_name = res['name']
                self.last_fetch = 0
        except:
            pass

    def get_icon(self, code, is_day=1):
        if code in [0, 1]:
            return "sun" if is_day else "moon"
        elif code == 2:
            return "partly_cloudy"
        elif code == 3:
            return "cloud"
        elif code in [45, 48]:
            return "fog"
        elif code in [51, 53, 55, 61, 63, 65, 80, 81, 82]:
            return "rain"
        elif code in [71, 73, 75, 77, 85, 86]:
            return "snow"
        elif code in [95, 96, 99]:
            return "storm"
        return "cloud"

    def get_weather(self):
        if time.time() - self.last_fetch < 900 and self.cache:
            return self.cache
        try:
            url = (
                f"https://api.open-meteo.com/v1/forecast?latitude={self.lat}&longitude={self.lon}"
                f"&current=temperature_2m,weather_code,is_day"
                f"&daily=weather_code,temperature_2m_max,temperature_2m_min,uv_index_max"
                f"&temperature_unit=fahrenheit&timezone=auto"
            )
            r = requests.get(url, timeout=5)
            data = r.json()
            curr = data.get('current', {})
            daily = data.get('daily', {})
            cur_temp = int(curr.get('temperature_2m', 0))
            cur_code = curr.get('weather_code', 0)
            is_day = curr.get('is_day', 1)
            cur_icon = self.get_icon(cur_code, is_day)
            high = int(daily['temperature_2m_max'][0])
            low = int(daily['temperature_2m_min'][0])
            uv = float(daily['uv_index_max'][0])
            forecast = []
            days = daily.get('time', [])
            codes = daily.get('weather_code', [])
            maxs = daily.get('temperature_2m_max', [])
            mins = daily.get('temperature_2m_min', [])
            for i in range(1, 4):
                if i < len(days):
                    dt_obj = dt.strptime(days[i], "%Y-%m-%d")
                    day_name = dt_obj.strftime("%a").upper()
                    f_icon = self.get_icon(codes[i], 1)
                    forecast.append({
                        "day": day_name,
                        "high": int(maxs[i]),
                        "low": int(mins[i]),
                        "icon": f_icon
                    })
            weather_obj = {
                "sport": "weather",
                "id": "weather_widget",
                "status": "Live",
                "home_abbr": f"{cur_temp}°",
                "away_abbr": self.location_name,
                "home_score": "",
                "away_score": "",
                "is_shown": True,
                "home_logo": "",
                "away_logo": "",
                "situation": {
                    "icon": cur_icon,
                    "is_day": is_day,
                    "stats": {
                        "high": high,
                        "low": low,
                        "uv": uv,
                        "aqi": "MOD"
                    },
                    "forecast": forecast
                }
            }
            self.cache = weather_obj
            self.last_fetch = time.time()
            return weather_obj
        except Exception as e:
            return None
