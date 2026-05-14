from .. import core as _core
globals().update({k: v for k, v in vars(_core).items() if not k.startswith('__')})


class AirportMixin:
    def _get_airport_query_code(self):
        for attr in ('airport_code_iata', 'airport_code_icao'):
            code = str(getattr(self, attr, '') or '').strip().upper()
            if code:
                return code
        return ''

    def _get_airport_code_candidates(self):
        candidates = set()
        for attr in ('airport_code_iata', 'airport_code_icao'):
            code = str(getattr(self, attr, '') or '').strip().upper()
            if code:
                candidates.add(code)
                airport_info = lookup_and_auto_fill_airport(code)
                for paired_code in (airport_info.get('iata', ''), airport_info.get('icao', '')):
                    paired_code = str(paired_code or '').strip().upper()
                    if paired_code:
                        candidates.add(paired_code)
        return candidates

    def fetch_fr24_schedule(self, mode='arrivals'):
        """Includes delayed flights and sorts by closest arrival/departure time."""
        airport_code = self._get_airport_query_code()
        if not airport_code:
            return []
        try:
            timestamp = int(time.time())
            url = f"https://api.flightradar24.com/common/v1/airport.json?code={airport_code}&plugin[]=schedule&plugin-setting[schedule][mode]={mode}&plugin-setting[schedule][timestamp]={timestamp}&page=1&limit=100"
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
                'Accept': 'application/json, text/plain, */*',
                'Accept-Language': 'en-US,en;q=0.9',
                'Referer': 'https://www.flightradar24.com/',
            }

            res = self.session.get(url, headers=headers, timeout=TIMEOUTS['slow'])
            if res.status_code != 200:
                return []

            data = res.json()
            schedule = safe_get(data, 'result', 'response', 'airport', 'pluginData', 'schedule', mode, default={})

            if not schedule or 'data' not in schedule:
                return []

            total_raw = len(schedule['data'])
            processed_list = []
            for flight in schedule['data']:
                try:
                    f_data = safe_get(flight, 'flight', default={})
                    status_text = safe_get(f_data, 'status', 'generic', 'status', 'text', default='').lower()
                    airport_candidates = self._get_airport_code_candidates()

                    # 1. Extract timestamps first so delay can gate the filter
                    time_info = safe_get(f_data, 'time', default={})
                    t_bucket = 'arrival' if mode == 'arrivals' else 'departure'

                    sched_ts = safe_get(time_info, 'scheduled', t_bucket) or 0
                    est_ts = (safe_get(time_info, 'estimated', t_bucket)
                              or safe_get(time_info, 'other', t_bucket))

                    sort_ts = est_ts if est_ts else sched_ts
                    if sort_ts == 0:
                        continue  # skip if absolutely no time data

                    # Detect delay: status text OR estimated 15+ min later than scheduled
                    is_delayed = (
                        'delay' in status_text or
                        (sched_ts and est_ts and
                         isinstance(sched_ts, (int, float)) and isinstance(est_ts, (int, float)) and
                         (est_ts - sched_ts) >= 900)
                    )

                    # 2. Validate the flight actually operates at this airport
                    # FR24 occasionally returns flights that route through but don't originate/terminate here
                    if mode == 'arrivals':
                        dest_iata = safe_get(f_data, 'airport', 'destination', 'code', 'iata', default='')
                        dest_icao = safe_get(f_data, 'airport', 'destination', 'code', 'icao', default='')
                        dest_codes = {str(dest_iata or '').strip().upper(), str(dest_icao or '').strip().upper()} - {''}
                        if dest_codes and airport_candidates and not (airport_candidates & dest_codes):
                            continue
                    else:
                        origin_iata = safe_get(f_data, 'airport', 'origin', 'code', 'iata', default='')
                        origin_icao = safe_get(f_data, 'airport', 'origin', 'code', 'icao', default='')
                        origin_codes = {str(origin_iata or '').strip().upper(), str(origin_icao or '').strip().upper()} - {''}
                        if origin_codes and airport_candidates and not (airport_candidates & origin_codes):
                            continue

                    # 3. Filter finished flights — delayed flights always pass through
                    if not is_delayed:
                        if mode == 'arrivals' and status_text == 'landed':
                            continue
                        if mode == 'departures' and status_text == 'departed':
                            continue

                    # 4. Build display identifier — prefer ICAO callsign (3-letter) over IATA flight number
                    callsign = safe_get(f_data, 'identification', 'callsign', default='').strip()
                    iata_num = safe_get(f_data, 'identification', 'number', 'default', default='').strip()
                    alt_num = safe_get(f_data, 'identification', 'number', 'alternative', default='').strip()
                    airline_icao = safe_get(f_data, 'airline', 'code', 'icao', default='').strip()
                    airline_iata = safe_get(f_data, 'airline', 'code', 'iata', default='').strip()

                    if callsign:
                        # e.g. "UAE210", "UAL264" — already in 3-letter ICAO format
                        display_id = callsign
                    elif iata_num and airline_icao:
                        # Strip IATA prefix and replace with ICAO: "EK210" → "UAE210"
                        num_only = iata_num[len(airline_iata):] if (airline_iata and iata_num.startswith(airline_iata)) else iata_num
                        display_id = f"{airline_icao}{num_only}"
                    elif iata_num:
                        display_id = iata_num
                    elif alt_num:
                        display_id = alt_num
                    else:
                        continue  # no usable identifier

                    display_status = "DELAYED" if is_delayed else ("ARRIVING" if mode == 'arrivals' else "DEPARTING")

                    city_key = 'origin' if mode == 'arrivals' else 'destination'
                    city_code = safe_get(f_data, 'airport', city_key, 'code', 'iata', default='') or safe_get(f_data, 'airport', city_key, 'code', 'icao', default='')

                    entry = {
                        'id': display_id,
                        'status_label': display_status,
                        'sort_time': sort_ts
                    }
                    if mode == 'arrivals':
                        entry['from'] = get_airport_display_name(city_code)
                    else:
                        entry['to'] = get_airport_display_name(city_code)

                    processed_list.append(entry)
                except:
                    continue

            # Deduplicate: same airline + same city + same departure minute = same flight
            # (EK210 and UAE36K are identical — one is the IATA number, the other the ICAO callsign)
            seen_keys = set()
            deduped = []
            for entry in processed_list:
                city = entry.get('to') or entry.get('from') or ''
                time_bucket = round(entry['sort_time'] / 60)  # bucket by minute
                key = (time_bucket, city)
                if key not in seen_keys:
                    seen_keys.add(key)
                    deduped.append(entry)
            processed_list = deduped

            # Sort by time so the closest 2 flights are selected
            processed_list.sort(key=lambda x: x['sort_time'])

            self.log("DEBUG", f"FR24 {mode}: {total_raw} raw → {len(processed_list)} after filter/dedup → returning {min(len(processed_list), 2)}")
            return processed_list[:2]  # Return only the 2 closest flights

        except Exception as e:
            self.log("ERROR", f"FR24 Schedule: {e}")
            return []

    def fetch_airport_weather(self):
        if not self.airport_code_iata:
            return {"temp": "--", "cond": "UNKNOWN"}
        try:
            # Use airport lat/lon from airportsdata for accurate weather
            lat, lon = None, None
            if AIRPORTS_DB and self.airport_code_iata in AIRPORTS_DB:
                ap = AIRPORTS_DB[self.airport_code_iata]
                lat, lon = ap.get('lat'), ap.get('lon')

            if lat is None or lon is None:
                self.log("WEATHER", f"No coordinates for {self.airport_code_iata}")
                return {"temp": "--", "cond": "UNKNOWN"}

            # Use Open-Meteo (same API as main weather widget) — free, no key, reliable
            url = (f"https://api.open-meteo.com/v1/forecast?"
                   f"latitude={lat}&longitude={lon}"
                   f"&current=temperature_2m,weather_code"
                   f"&temperature_unit=fahrenheit&timezone=auto")

            self.log("WEATHER", f"Fetching weather from Open-Meteo for {self.airport_code_iata} ({lat},{lon})")
            res = self.session.get(url, timeout=TIMEOUTS['slow'])
            if res.status_code == 200:
                data = res.json()
                current = data.get('current', {})
                temp_f = current.get('temperature_2m')
                wmo_code = current.get('weather_code', -1)
                cond = WMO_DESCRIPTIONS.get(wmo_code, "UNKNOWN")
                if temp_f is not None:
                    return {"temp": f"{int(round(temp_f))}F", "cond": cond}
        except Exception as e:
            self.log("ERROR", f"Airport weather fetch failed: {e}")
        return {"temp": "--", "cond": "UNKNOWN"}

    def fetch_airport_activity(self):
        try:
            target_code = self._get_airport_query_code()
            if not target_code:
                return
            self.log("DEBUG", f"Starting airport fetch for {target_code}")

            # Fetch arrivals, departures, and weather in parallel
            with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
                f_arr = pool.submit(self.fetch_fr24_schedule, 'arrivals')
                f_dep = pool.submit(self.fetch_fr24_schedule, 'departures')
                f_wx = pool.submit(self.fetch_airport_weather)
                arrivals = f_arr.result()
                departures = f_dep.result()
                weather = f_wx.result()

            # Single airport-change guard after all three complete
            if self._get_airport_query_code() != target_code:
                self.log("DEBUG", "Airport changed mid-fetch, discarding results")
                return

            with self.lock:
                self.airport_arrivals = arrivals
                self.airport_departures = departures
                self.airport_weather = weather
            self.log("AIRPORT", f"{target_code}: {len(arrivals)} arr, {len(departures)} dep | Weather: {weather['temp']}")
        except Exception as e:
            self.log("ERROR", f"Airport Loop: {e}")

    def get_airport_objects(self):
        with self.lock:
            result = []
            self.log("DEBUG", f"get_airport_objects called - arrivals: {len(self.airport_arrivals)}, departures: {len(self.airport_departures)}")
            result.append({
                'type': 'flight_weather', 'sport': 'flight', 'id': 'airport_wx',
                'home_abbr': self.airport_name or self.airport_code_icao,
                'away_abbr': self.airport_weather['temp'], 'status': self.airport_weather['cond'], 'is_shown': True
            })
            for i, arr in enumerate(self.airport_arrivals[:2]):
                # Use specific status if available, else fallback
                st = arr.get('status_label', 'ARRIVING')
                result.append({'type': 'flight_arrival', 'sport': 'flight', 'id': f"arr_{i}", 'status': st, 'home_abbr': arr['from'], 'away_abbr': arr['id'], 'is_shown': True})
            for i, dep in enumerate(self.airport_departures[:2]):
                st = dep.get('status_label', 'DEPARTING')
                result.append({'type': 'flight_departure', 'sport': 'flight', 'id': f"dep_{i}", 'status': st, 'home_abbr': dep['to'], 'away_abbr': dep['id'], 'is_shown': True})
            return result
