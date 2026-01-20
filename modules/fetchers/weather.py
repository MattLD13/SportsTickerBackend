import time
from datetime import datetime as dt
from modules.utils import build_pooled_session

class WeatherFetcher:
    def __init__(self, initial_lat=40.7128, initial_lon=-74.0060, city="New York"):
        self.lat = initial_lat
        self.lon = initial_lon
        self.city_name = city
        self.last_fetch = 0
        self.cache = None
        self.session = build_pooled_session(pool_size=10)

    def update_config(self, city=None, lat=None, lon=None):
        if lat is not None: self.lat = lat
        if lon is not None: self.lon = lon
        if city is not None: self.city_name = city
        self.last_fetch = 0

    def get_weather_icon(self, wmo_code):
        code = int(wmo_code)
        if code == 0: return 'sun'
        if code in [1, 2, 3, 45, 48]: return 'cloud'
        if code in [51, 53, 55, 56, 57, 61, 63, 65, 66, 67, 80, 81, 82]: return 'rain'
        if code in [71, 73, 75, 77, 85, 86]: return 'snow'
        if code in [95, 96, 99]: return 'storm'
        return 'cloud'

    def get_day_name(self, date_str):
        try:
            date_obj = dt.strptime(date_str, '%Y-%m-%d')
            return date_obj.strftime('%a').upper()
        except: return "DAY"

    def get_weather(self):
        if time.time() - self.last_fetch < 900 and self.cache: return self.cache

        try:
            w_url = f"https://api.open-meteo.com/v1/forecast?latitude={self.lat}&longitude={self.lon}&current=temperature_2m,weather_code&daily=weather_code,temperature_2m_max,temperature_2m_min,uv_index_max&temperature_unit=fahrenheit&timezone=auto"
            w_res = self.session.get(w_url, timeout=5).json()

            a_url = f"https://air-quality-api.open-meteo.com/v1/air-quality?latitude={self.lat}&longitude={self.lon}&current=us_aqi"
            a_res = self.session.get(a_url, timeout=5).json()

            current_temp = int(round(w_res['current']['temperature_2m']))
            current_code = w_res['current']['weather_code']
            current_icon = self.get_weather_icon(current_code)

            aqi = a_res.get('current', {}).get('us_aqi', 0)
            uv = w_res['daily']['uv_index_max'][0]

            forecast_list = []
            daily = w_res['daily']

            for i in range(0, 5):
                f_day = {
                    "day": self.get_day_name(daily['time'][i]),
                    "icon": self.get_weather_icon(daily['weather_code'][i]),
                    "high": int(round(daily['temperature_2m_max'][i])),
                    "low": int(round(daily['temperature_2m_min'][i]))
                }
                forecast_list.append(f_day)

            self.cache = {
                "type": "weather",
                "sport": "weather",
                "id": "weather_main",
                "away_abbr": self.city_name.upper(),
                "home_abbr": str(current_temp),
                "situation": {
                    "icon": current_icon,
                    "stats": {
                        "aqi": str(aqi),
                        "uv": str(uv)
                    },
                    "forecast": forecast_list
                },
                "home_score": str(current_temp),
                "away_score": "0",
                "status": "Active",
                "is_shown": True
            }
            self.last_fetch = time.time()
            return self.cache

        except Exception as e:
            print(f"Weather fetch failed: {e}")
            return None
