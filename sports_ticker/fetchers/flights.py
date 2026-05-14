from .. import core as _core
globals().update({k: v for k, v in vars(_core).items() if not k.startswith('__')})

from .test_mode import TestMode

class FlightTracker:
    def __init__(self):
        self.session = build_pooled_session(pool_size=10)
        self.lock = threading.Lock()
        self.visitor_flight = None
        self.airport_arrivals = []
        self.airport_departures = []
        self.airport_weather = {"temp": "--", "cond": "LOADING"}
        self.track_flight_id = ""
        self.track_guest_name = ""
        self.airport_code_icao = ""
        self.airport_code_iata = ""
        self.airport_name = ""
        self.airline_filter = ""
        self.last_visitor_fetch = 0
        self.last_airport_fetch = 0
        self.running = True
        self._force_refresh = False
        # Event to force immediate fetch when config changes
        self.wake_event = threading.Event()
        # Initialize FlightRadarAPI SDK if available
        self.fr_api = FlightRadar24API() if FR24_SDK_AVAILABLE else None
    
    def force_update(self):
        """Signal the flights_worker to immediately fetch new data."""
        self._force_refresh = True
        self.wake_event.set()
    
    def log(self, cat, msg):
        # Suppress DEBUG-category output unless test_flights is on
        if cat == 'DEBUG' and not TestMode.is_enabled('flights'):
            return
        print(f"[{dt.now().strftime('%H:%M:%S')}] {cat:<12} | {msg}")
    
    def fetch_fr24_schedule(self, mode='arrivals'):
        """Includes delayed flights and sorts by closest arrival/departure time."""
        if not self.airport_code_iata:
            return []
        try:
            timestamp = int(time.time())
            url = f"https://api.flightradar24.com/common/v1/airport.json?code={self.airport_code_iata}&plugin[]=schedule&plugin-setting[schedule][mode]={mode}&plugin-setting[schedule][timestamp]={timestamp}&page=1&limit=100"
            headers = {'User-Agent': 'Mozilla/5.0', 'Accept': 'application/json'}
            
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

                    # 1. Extract timestamps first so delay can gate the filter
                    time_info = safe_get(f_data, 'time', default={})
                    t_bucket = 'arrival' if mode == 'arrivals' else 'departure'

                    sched_ts = safe_get(time_info, 'scheduled', t_bucket) or 0
                    est_ts   = (safe_get(time_info, 'estimated', t_bucket)
                                or safe_get(time_info, 'other', t_bucket))

                    sort_ts = est_ts if est_ts else sched_ts
                    if sort_ts == 0: continue  # skip if absolutely no time data

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
                        if dest_iata and dest_iata.upper() != self.airport_code_iata.upper():
                            continue
                    else:
                        origin_iata = safe_get(f_data, 'airport', 'origin', 'code', 'iata', default='')
                        if origin_iata and origin_iata.upper() != self.airport_code_iata.upper():
                            continue

                    # 3. Filter finished flights — delayed flights always pass through
                    if not is_delayed:
                        if mode == 'arrivals' and status_text == 'landed': continue
                        if mode == 'departures' and status_text == 'departed': continue

                    # 4. Build display identifier — prefer ICAO callsign (3-letter) over IATA flight number
                    callsign   = safe_get(f_data, 'identification', 'callsign', default='').strip()
                    iata_num   = safe_get(f_data, 'identification', 'number', 'default', default='').strip()
                    alt_num    = safe_get(f_data, 'identification', 'number', 'alternative', default='').strip()
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
                    city_code = safe_get(f_data, 'airport', city_key, 'code', 'iata', default='')
                    
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
            return processed_list[:2] # Return only the 2 closest flights
            
        except Exception as e:
            self.log("ERROR", f"FR24 Schedule: {e}")
            return []

    def parse_flight_code(self, flight_code):
        """
        Parse flight code and return (icao_code, iata_code, flight_num)
        Examples: 
        B61004 -> ('JBU', 'B6', '1004')
        JBU1004 -> ('JBU', 'B6', '1004')
        NK1149 -> ('NKS', 'NK', '1149')
        UA72 -> ('UAL', 'UA', '72')
        """
        flight_code = flight_code.replace(" ", "").upper()

        # Try 3-letter ICAO code first (JBU1004, UAL72)
        if len(flight_code) >= 4:
            potential_icao = flight_code[:3]
            if potential_icao in _ICAO_TO_IATA:
                return potential_icao, _ICAO_TO_IATA[potential_icao], flight_code[3:]

        # Try 2-character IATA code (B61004, UA72, NK1149)
        if len(flight_code) >= 3:
            potential_iata = flight_code[:2]
            if potential_iata in _IATA_TO_ICAO:
                return _IATA_TO_ICAO[potential_iata], potential_iata, flight_code[2:]

        # AI fallback — try both prefix lengths (3-letter ICAO first, then 2-letter IATA)
        for prefix_len in (3, 2):
            if len(flight_code) > prefix_len:
                prefix = flight_code[:prefix_len]
                icao, iata = ai_lookup_airline_codes(prefix)
                if icao and iata:
                    return icao, iata, flight_code[prefix_len:]

        raise ValueError(f"Invalid flight code format: {flight_code}")

    def fetch_airport_weather(self):
        if not self.airport_code_iata: return {"temp": "--", "cond": "UNKNOWN"}
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
            target_iata = self.airport_code_iata
            if not target_iata:
                return
            self.log("DEBUG", f"Starting airport fetch for {target_iata}")

            # Fetch arrivals, departures, and weather in parallel
            with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
                f_arr = pool.submit(self.fetch_fr24_schedule, 'arrivals')
                f_dep = pool.submit(self.fetch_fr24_schedule, 'departures')
                f_wx  = pool.submit(self.fetch_airport_weather)
                arrivals   = f_arr.result()
                departures = f_dep.result()
                weather    = f_wx.result()

            # Single airport-change guard after all three complete
            if self.airport_code_iata != target_iata:
                self.log("DEBUG", f"Airport changed mid-fetch, discarding results")
                return

            with self.lock:
                self.airport_arrivals = arrivals
                self.airport_departures = departures
                self.airport_weather = weather
            self.log("AIRPORT", f"{target_iata}: {len(arrivals)} arr, {len(departures)} dep | Weather: {weather['temp']}")
        except Exception as e:
            self.log("ERROR", f"Airport Loop: {e}")
    
    def fetch_visitor_tracking(self):
        if not self.track_flight_id: return
        
        try:
            self.log("TRACKER", f"Fetching flight: {self.track_flight_id}")
            fr24_data = self.fetch_fr24_flight(self.track_flight_id)
            
            if fr24_data:
                dest = fr24_data['destination']
                origin = fr24_data['origin']
                
                speed_mph = int(fr24_data['speed_kts'] * 1.15078)
                is_live = fr24_data['is_live']
                delay_min = fr24_data.get('delay_min')
                status_text = (fr24_data.get('status_text') or '').lower()
                is_delayed = (delay_min is not None and delay_min >= 15) or ('delay' in status_text)
                status = 'delayed' if is_delayed else ('en-route' if is_live else 'scheduled')
                eta_str = "DELAYED" if is_delayed else ("EN ROUTE" if is_live else "SCHEDULED")
                
                dist = 0
                progress = 0
                
                if is_live and dest in AIRPORTS_DB:
                    to_airport = AIRPORTS_DB[dest]
                    lat, lon = fr24_data['latitude'], fr24_data['longitude']
                    
                    if lat and lon:
                        dist_nm = haversine(lat, lon, to_airport['lat'], to_airport['lon'])
                        dist = int(dist_nm * 1.15078)
                        
                        if origin in AIRPORTS_DB:
                            from_airport = AIRPORTS_DB[origin]
                            total_dist = haversine(from_airport['lat'], from_airport['lon'], 
                                                   to_airport['lat'], to_airport['lon'])
                            dist_from = haversine(from_airport['lat'], from_airport['lon'], lat, lon)
                            
                            if total_dist > 0:
                                progress = max(0, min(100, int((dist_from / total_dist) * 100)))
                        
                        est_arr = fr24_data.get('est_arr')
                        if est_arr:
                            remaining_secs = est_arr - int(time.time())
                            if remaining_secs > 0:
                                mins = int(remaining_secs / 60)
                                h, m = divmod(mins, 60)
                                eta_str = f"{h}H {m}M" if h > 0 else f"{m} MIN"
                            else:
                                eta_str = "LANDING"
                        elif speed_mph > 0:
                            mins = int((dist / speed_mph) * 60)
                            h, m = divmod(mins, 60)
                            eta_str = f"{h}H {m}M" if h > 0 else f"{m} MIN"

                with self.lock:
                    self.visitor_flight = {
                        'type': 'flight_visitor',
                        'sport': 'flight',
                        'id': self.track_flight_id,
                        'guest_name': self.track_guest_name or self.track_flight_id,
                        'route': f"{origin} > {dest}",
                        'origin_city': get_airport_display_name(origin), # Shortened Name
                        'dest_city': get_airport_display_name(dest),     # Shortened Name
                        'alt': fr24_data['altitude'],
                        'dist': dist,
                        'eta_str': eta_str,
                        'speed': speed_mph,
                        'progress': progress,
                        'status': status,
                        'delay_min': delay_min,
                        'is_delayed': is_delayed,
                        'is_live': is_live,
                        'aircraft_type': fr24_data.get('aircraft_type', ''),
                        'aircraft_code': fr24_data.get('aircraft_code', ''),
                        'is_shown': True
                    }
                self.log("TRACKER", f"{self.track_flight_id} (FR24) {status} | {fr24_data['altitude']}ft")
                return
            else:
                self.log("TRACKER", f"No FR24 match for {self.track_flight_id}")
                
            # Fallback
            with self.lock:
                self.visitor_flight = {
                    'type': 'flight_visitor',
                    'sport': 'flight',
                    'id': self.track_flight_id,
                    'guest_name': self.track_guest_name or self.track_flight_id,
                    'route': "UNK > UNK",
                    'origin_city': "UNKNOWN",
                    'dest_city': "UNKNOWN",
                    'alt': 0, 'dist': 0, 'eta_str': "PENDING", 'speed': 0, 'progress': 0,
                    'status': "pending", 'is_shown': True
                }

        except Exception as e:
            self.log("ERROR", f"Visitor Tracking: {e}")

    def fetch_fr24_flight(self, flight_id):
        """Fetch flight data using FlightRadarAPI SDK"""
        try:
            if not self.fr_api: 
                self.log("ERROR", "FlightRadar24 API not initialized")
                return None

            def _parse_ts(value):
                if isinstance(value, dict):
                    for key in ['utc', 'unix', 'time', 'timestamp']:
                        if key in value:
                            value = value.get(key)
                            break
                try:
                    return int(value)
                except Exception:
                    return None

            def _get_time(time_info, bucket, point):
                block = time_info.get(bucket) or {}
                raw = block.get(point)
                return _parse_ts(raw)

            def _extract_delay_minutes(details):
                if not details:
                    return None, "", None
                time_info = details.get('time') or {}
                sched_arr = _get_time(time_info, 'scheduled', 'arrival')
                est_arr = (_get_time(time_info, 'estimated', 'arrival') or
                           _get_time(time_info, 'real', 'arrival') or
                           _get_time(time_info, 'actual', 'arrival'))
                sched_dep = _get_time(time_info, 'scheduled', 'departure')
                est_dep = (_get_time(time_info, 'estimated', 'departure') or
                           _get_time(time_info, 'real', 'departure') or
                           _get_time(time_info, 'actual', 'departure'))
                delay_min = None
                if sched_arr and est_arr:
                    delay_min = max(0, int((est_arr - sched_arr) / 60))
                elif sched_dep and est_dep:
                    delay_min = max(0, int((est_dep - sched_dep) / 60))

                status_block = details.get('status') or {}
                status_text = str(
                    status_block.get('text') or
                    status_block.get('description') or
                    status_block.get('status') or
                    details.get('statusText') or ''
                )
                return delay_min, status_text, est_arr
            
            # Parse the flight code
            icao, iata, flight_num = self.parse_flight_code(flight_id)
            
            self.log("INFO", f"Searching for flight {flight_id} (ICAO: {icao}, IATA: {iata}, #: {flight_num})")
            
            # Try airline-filtered search first
            try:
                flights = self.fr_api.get_flights(airline=icao)
                if flights:
                    self.log("INFO", f"Got {len(flights)} {icao} flights from API")
            except Exception as e:
                self.log("DEBUG", f"Airline filter failed, trying all flights: {e}")
                flights = self.fr_api.get_flights()
                if flights:
                    self.log("INFO", f"Got {len(flights)} total flights from API")
            
            if not flights:
                self.log("WARNING", f"No flights returned by API - service may be down")
                return None
            
            # Build search variants
            search_strings = [
                f"{icao}{flight_num}",      # UAL72, JBU1004
                f"{iata}{flight_num}",      # UA72, B61004
            ]
            
            # Add zero-padded variants for short flight numbers
            if len(flight_num) < 4:
                search_strings.extend([
                    f"{icao}{flight_num.zfill(4)}",  # UAL0072
                    f"{iata}{flight_num.zfill(4)}",  # UA0072
                ])
            
            # Search for the flight
            target_flight = None
            
            for flight in flights:
                f_num = (flight.number or "").upper().replace(" ", "")
                f_call = (flight.callsign or "").upper().replace(" ", "")
                
                for search_str in search_strings:
                    if search_str in [f_num, f_call]:
                        target_flight = flight
                        self.log("INFO", f"✓ Found {flight_id}: {f_num} ({f_call})")
                        break
                
                if target_flight:
                    break
            
            if not target_flight:
                self.log("WARNING", f"Flight {flight_id} not found - may not be airborne right now")
                self.log("DEBUG", f"Searched for: {search_strings}")
                return None
            
            # Get detailed information if available
            details = None
            try:
                details = self.fr_api.get_flight_details(target_flight)
                target_flight.set_flight_details(details)
            except Exception as e:
                self.log("DEBUG", f"Could not get detailed info: {e}")

            delay_min, status_text, est_arr = _extract_delay_minutes(details)

            # Aircraft type: prefer detailed model from FR24, fall back to ICAO type code normalization
            fr24_model = getattr(target_flight, 'aircraft_model', None) or ''
            icao_type = getattr(target_flight, 'aircraft_code', None) or ''
            aircraft_type = normalize_aircraft_type(icao_type, fr24_model if fr24_model else None)
            if aircraft_type:
                self.log("INFO", f"Aircraft type for {flight_id}: {aircraft_type} (code: {icao_type})")

            return {
                'flight_id': flight_id,
                'origin': target_flight.origin_airport_iata or 'UNK',
                'destination': target_flight.destination_airport_iata or 'UNK',
                'latitude': target_flight.latitude,
                'longitude': target_flight.longitude,
                'altitude': target_flight.altitude or 0,
                'speed_kts': target_flight.ground_speed or 0,
                'is_live': (target_flight.altitude or 0) > 0,
                'delay_min': delay_min,
                'status_text': status_text,
                'est_arr': est_arr,
                'aircraft_type': aircraft_type,
                'aircraft_code': icao_type
            }
            
        except ValueError as e:
            self.log("ERROR", f"Invalid flight code '{flight_id}': {e}")
            return None
        except Exception as e:
            self.log("ERROR", f"Error fetching flight {flight_id}: {e}")
            return None
    
    def get_visitor_object(self):
        with self.lock:
            return self.visitor_flight.copy() if self.visitor_flight else None
    
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
