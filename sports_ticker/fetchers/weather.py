from .. import core as _core
globals().update({k: v for k, v in vars(_core).items() if not k.startswith('__')})

class WeatherFetcher:
    def __init__(self, initial_lat=40.7128, initial_lon=-74.0060, city="New York"):
        self.lat = initial_lat
        self.lon = initial_lon
        self.city_name = city
        self.last_fetch = 0
        self.cache = None
        self.session = build_pooled_session(pool_size=10)

    def update_config(self, city=None, lat=None, lon=None):
        try:
            if lat is not None: self.lat = float(lat)
            if lon is not None: self.lon = float(lon)
            if city is not None: self.city_name = str(city)
            self.last_fetch = 0 # Force refresh
            print(f"✅ Weather config updated: {self.city_name} ({self.lat}, {self.lon})")
        except Exception as e:
            print(f"⚠️ Error updating weather config: {e}")

    def get_weather_icon(self, wmo_code):
        try:
            code = int(wmo_code)
        except:
            return 'cloud'
            
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
        # 1. Return Cache if fresh (< 15 mins)
        if time.time() - self.last_fetch < CACHE_TTL['weather'] and self.cache:
            return self.cache
        
        try:
            # 2. Validate coordinates
            if self.lat is None or self.lon is None:
                print("❌ Weather Error: Invalid Coordinates (None)")
                return self.cache

            # 3. Fetch Forecast (Independent Step)
            w_data = {}
            try:
                w_url = f"https://api.open-meteo.com/v1/forecast?latitude={self.lat}&longitude={self.lon}&current=temperature_2m,weather_code,apparent_temperature,wind_speed_10m,relative_humidity_2m&daily=weather_code,temperature_2m_max,temperature_2m_min,uv_index_max&temperature_unit=fahrenheit&wind_speed_unit=mph&timezone=auto"
                w_resp = self.session.get(w_url, timeout=TIMEOUTS['slow'])
                if w_resp.status_code == 200:
                    w_data = w_resp.json()
                else:
                    print(f"⚠️ Weather API Error: {w_resp.status_code} - {w_resp.text}")
                    return self.cache # Keep showing old data if fetch fails
            except Exception as e:
                print(f"⚠️ Weather Connection Failed: {e}")
                return self.cache

            # 4. Fetch Air Quality (Separate Step - Fail Safe)
            aqi = 0
            try:
                a_url = f"https://air-quality-api.open-meteo.com/v1/air-quality?latitude={self.lat}&longitude={self.lon}&current=us_aqi"
                a_resp = self.session.get(a_url, timeout=TIMEOUTS['stock'])
                if a_resp.status_code == 200:
                    a_data = a_resp.json()
                    aqi = a_data.get('current', {}).get('us_aqi', 0)
            except Exception:
                pass # If AQI fails, just show 0, don't crash the widget

            # 5. Parse Data
            current = w_data.get('current', {})
            daily = w_data.get('daily', {})

            if not current:
                print("⚠️ Weather Error: Missing 'current' data in response")
                return self.cache

            current_temp = int(round(current.get('temperature_2m', 0)))
            current_code = current.get('weather_code', 0)
            current_icon = self.get_weather_icon(current_code)
            feels_like = int(round(current.get('apparent_temperature', current_temp)))
            wind_mph = int(round(current.get('wind_speed_10m', 0)))
            humidity = int(round(current.get('relative_humidity_2m', 0)))

            uv = 0
            if 'uv_index_max' in daily and len(daily['uv_index_max']) > 0:
                uv = daily['uv_index_max'][0]

            forecast_list = []
            if 'time' in daily:
                days_count = len(daily['time'])
                # Safe loop that won't crash if API returns fewer days than expected
                for i in range(min(5, days_count)): 
                    try:
                        f_day = {
                            "day": self.get_day_name(daily['time'][i]),
                            "icon": self.get_weather_icon(daily['weather_code'][i]),
                            "high": int(round(daily['temperature_2m_max'][i])),
                            "low": int(round(daily['temperature_2m_min'][i]))
                        }
                        forecast_list.append(f_day)
                    except: continue

            # 6. Build Object
            self.cache = {
                "type": "weather",
                "sport": "weather",
                "id": "weather_main",
                "away_abbr": str(self.city_name).upper(), 
                "home_abbr": str(current_temp), 
                "situation": {
                    "icon": current_icon,
                    "stats": {
                        "aqi": str(aqi),
                        "uv": str(uv),
                        "feels": str(feels_like),
                        "wind": str(wind_mph),
                        "humidity": str(humidity),
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
            print(f"❌ Critical Weather Error: {e}")
            return self.cache
