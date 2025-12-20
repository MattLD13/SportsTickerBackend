import threading
import json
import os
import re
import time
from datetime import datetime as dt, timezone, timedelta
import requests
from flask import Flask, jsonify, request

# ================= CONFIGURATION =================
TIMEZONE_OFFSET = -5  # Set to -5 for EST/EDT
CONFIG_FILE = "ticker_config.json"
UPDATE_INTERVAL = 15  # seconds

# Thread Lock for safety
data_lock = threading.Lock()

# --- LOGO OVERRIDES (League-Specific) ---
LOGO_OVERRIDES = {
    # --- NHL FIXES ---
    "NHL:SJS": "https://a.espncdn.com/i/teamlogos/nhl/500/sj.png",
    "NHL:NJD": "https://a.espncdn.com/i/teamlogos/nhl/500/nj.png",
    "NHL:TBL": "https://a.espncdn.com/i/teamlogos/nhl/500/tb.png",
    "NHL:LAK": "https://a.espncdn.com/i/teamlogos/nhl/500/la.png",
    "NHL:VGK": "https://a.espncdn.com/i/teamlogos/nhl/500/vgs.png",
    "NHL:VEG": "https://a.espncdn.com/i/teamlogos/nhl/500/vgs.png",
    "NHL:UTA": "https://a.espncdn.com/i/teamlogos/nhl/500/utah.png",
    "NHL:WSH": "https://a.espncdn.com/guid/cbe677ee-361e-91b4-5cae-6c4c30044743/logos/secondary_logo_on_black_color.png",
    "NHL:WAS": "https://a.espncdn.com/guid/cbe677ee-361e-91b4-5cae-6c4c30044743/logos/secondary_logo_on_black_color.png",
    # --- NFL FIXES ---
    "NFL:WSH": "https://a.espncdn.com/i/teamlogos/nfl/500/wsh.png",
    "NFL:WAS": "https://a.espncdn.com/i/teamlogos/nfl/500/wsh.png",
    # --- MLB FIXES ---
    "MLB:WSH": "https://a.espncdn.com/i/teamlogos/mlb/500/wsh.png",
    "MLB:WAS": "https://a.espncdn.com/i/teamlogos/mlb/500/wsh.png",
    # --- NBA FIXES ---
    "NBA:WSH": "https://a.espncdn.com/i/teamlogos/nba/500/was.png",
    "NBA:WAS": "https://a.espncdn.com/i/teamlogos/nba/500/was.png",
    "NBA:UTA": "https://a.espncdn.com/i/teamlogos/nba/500/utah.png",
    "NBA:NOP": "https://a.espncdn.com/i/teamlogos/nba/500/no.png",
    # --- NCAA FIXES ---
    "NCF_FBS:CAL": "https://a.espncdn.com/i/teamlogos/ncaa/500/25.png",
    "NCF_FBS:OSU": "https://a.espncdn.com/i/teamlogos/ncaa/500/194.png",
    "NCF_FBS:ORST": "https://a.espncdn.com/i/teamlogos/ncaa/500/204.png",
    "NCF_FBS:MIA": "https://a.espncdn.com/i/teamlogos/ncaa/500/2390.png",
    "NCF_FBS:MIAMI": "https://a.espncdn.com/i/teamlogos/ncaa/500/2390.png",
    "NCF_FBS:HOU": "https://a.espncdn.com/i/teamlogos/ncaa/500/248.png",
    "NCF_FBS:IND": "https://a.espncdn.com/i/teamlogos/ncaa/500/84.png",
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
        self.lat = 40.7128
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
                    "stats": {"high": high, "low": low, "uv": uv, "aqi": "MOD"},
                    "forecast": forecast
                }
            }
            self.cache = weather_obj
            self.last_fetch = time.time()
            return weather_obj
        except:
            return None


# ================= SPORTS FETCHER =================
class SportsFetcher:
    def __init__(self):
        self.weather = WeatherFetcher()
        self.base_url = 'http://site.api.espn.com/apis/site/v2/sports/'
        self.last_weather_loc = ""
        self.leagues = {
            'nfl': {'path': 'football/nfl', 'scoreboard_params': {}, 'team_params': {'limit': 100}},
            'ncf_fbs': {'path': 'football/college-football', 'scoreboard_params': {'groups': '80', 'limit': 100}, 'team_params': {'limit': 1000}},
            'ncf_fcs': {'path': 'football/college-football', 'scoreboard_params': {'groups': '81', 'limit': 100}, 'team_params': {'limit': 1000}},
            'mlb': {'path': 'baseball/mlb', 'scoreboard_params': {}, 'team_params': {'limit': 100}},
            'nhl': {'path': 'hockey/nhl', 'scoreboard_params': {}, 'team_params': {'limit': 100}},
            'nba': {'path': 'basketball/nba', 'scoreboard_params': {}, 'team_params': {'limit': 100}}
        }

    def get_corrected_logo(self, league_key, abbr, default_logo):
        key = f"{league_key.upper()}:{abbr}"
        return LOGO_OVERRIDES.get(key, default_logo)

    # --- FULL TEAM FETCH ---
    def fetch_all_teams(self):
        try:
            teams_catalog = {k: [] for k in self.leagues.keys()}
            for league_key in ['nfl', 'mlb', 'nhl', 'nba']:
                self._fetch_simple_league(league_key, teams_catalog)

            # Fetch College Football teams (FBS/FCS)
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
                                    t_logo = self.get_corrected_logo('ncf_fbs', t_abbr, t_logo)
                                    teams_catalog['ncf_fbs'].append({'abbr': t_abbr, 'logo': t_logo})
                                except:
                                    continue
            except:
                pass

            with data_lock:
                state['all_teams_data'] = teams_catalog
        except Exception as e:
            print(e)

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
                            abbr = item['team'].get('abbreviation', 'unk')
                            logo = item['team'].get('logos', [{}])[0].get('href', '')
                            logo = self.get_corrected_logo(league_key, abbr, logo)
                            catalog[league_key].append({'abbr': abbr, 'logo': logo})
        except:
            pass

    # --- NHL NATIVE FETCH ---
    def _fetch_nhl_native(self, games_list, target_date_str):
        with data_lock:
            is_nhl_enabled = state['active_sports'].get('nhl', False)
        schedule_url = "https://api-web.nhle.com/v1/schedule/now"
        try:
            response = requests.get(schedule_url, timeout=5)
            if response.status_code != 200:
                return
            schedule_data = response.json()
        except:
            return

        for date_entry in schedule_data.get('gameWeek', []):
            if date_entry.get('date') != target_date_str:
                continue
            for game in date_entry.get('games', []):
                self._process_single_nhl_game(game['id'], games_list, is_nhl_enabled)

    def _process_single_nhl_game(self, game_id, games_list, is_enabled):
        pbp_url = f"https://api-web.nhle.com/v1/gamecenter/{game_id}/play-by-play"
        try:
            r = requests.get(pbp_url, timeout=3)
            if r.status_code != 200:
                return
            data = r.json()
        except:
            return

        away_abbr = data['awayTeam']['abbrev']
        home_abbr = data['homeTeam']['abbrev']
        away_score = str(data['awayTeam'].get('score', 0))
        home_score = str(data['homeTeam'].get('score', 0))
        game_type = data.get('gameType', 2)
        is_playoff = (game_type == 3)

        away_logo = self.get_corrected_logo('nhl', away_abbr, f"https://a.espncdn.com/i/teamlogos/nhl/500/{away_abbr.lower()}.png")
        home_logo = self.get_corrected_logo('nhl', home_abbr, f"https://a.espncdn.com/i/teamlogos/nhl/500/{home_abbr.lower()}.png")

        game_state = data.get('gameState', 'OFF')
        mapped_state = 'in' if game_state in ['LIVE', 'CRIT'] else 'post'
        if game_state in ['PRE', 'FUT']:
            mapped_state = 'pre'

        with data_lock:
            mode = state['mode']
            my_teams = state['my_teams']

        is_shown = is_enabled
        if is_shown:
            if mode == 'live' and mapped_state != 'in':
                is_shown = False
            if mode == 'my_teams':
                h_key = f"nhl:{home_abbr}"
                a_key = f"nhl:{away_abbr}"
                if h_key not in my_teams and a_key not in my_teams:
                    is_shown = False

        clock = data.get('clock', {})
        time_rem = clock.get('timeRemaining', '00:00')
        period = data.get('periodDescriptor', {}).get('number', 1)
        period_label = f"P{period}"
        if period == 4:
            period_label = "OT"
        elif period > 4:
            period_label = "2OT" if is_playoff else "S/O"

        if game_state in ['FINAL', 'OFF']:
            status_disp = "FINAL"
        elif game_state in ['PRE', 'FUT']:
            raw_time = data.get('startTimeUTC', '')
            if raw_time:
                try:
                    utc_dt = dt.strptime(raw_time, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
                    local_dt = utc_dt + timedelta(hours=TIMEZONE_OFFSET)
                    status_disp = local_dt.strftime("%I:%M %p").lstrip('0')
                except:
                    status_disp = "Scheduled"
            else:
                status_disp = "Scheduled"
        elif clock.get('inIntermission'):
            status_disp = f"{period_label} INT"
        else:
            if period > 4 and not is_playoff:
                status_disp = "S/O"
            else:
                status_disp = f"{period_label} {time_rem}"

        sit_code = data.get('situation', {}).get('powerPlayStrength', 'none')
        pp_map = {'pp': 'pp', 'sh': 'pk', 'ev': 'ev', 'en': 'en'}
        pp_display = pp_map.get(sit_code, 'ev')

        game_obj = {
            "sport": "nhl",
            "id": game_id,
            "status": status_disp,
            "home_abbr": home_abbr,
            "away_abbr": away_abbr,
            "home_score": home_score,
            "away_score": away_score,
            "is_shown": is_shown,
            "home_logo": home_logo,
            "away_logo": away_logo,
            "situation": {"strength": pp_display}
        }

        games_list.append(game_obj)


# ================= BACKGROUND THREAD =================
def background_updater():
    fetcher = SportsFetcher()
    while True:
        try:
            fetcher.fetch_all_teams()
        except:
            pass
        time.sleep(UPDATE_INTERVAL)


threading.Thread(target=background_updater, daemon=True).start()

# ================= FLASK APP =================
app = Flask(__name__)
sports_fetcher = SportsFetcher()


@app.route("/api/weather", methods=['GET'])
def api_weather():
    loc = request.args.get('location', state['weather_location'])
    if loc != sports_fetcher.weather.location_name:
        sports_fetcher.weather.update_coords(loc)
    weather = sports_fetcher.weather.get_weather()
    return jsonify(weather)


@app.route("/api/config", methods=['GET', 'POST'])
def api_config():
    if request.method == 'GET':
        with data_lock:
            return jsonify(state)
    elif request.method == 'POST':
        data = request.json
        with data_lock:
            for k, v in data.items():
                if k in state:
                    state[k] = v
        save_config_file()
        return jsonify({"status": "ok"})


@app.route("/api/teams", methods=['GET'])
def api_teams():
    with data_lock:
        return jsonify(state.get('all_teams_data', {}))


if __name__ == "__main__":
    app.run(host='0.0.0.0', port=5000)
