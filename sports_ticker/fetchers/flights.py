from .. import core as _core
globals().update({k: v for k, v in vars(_core).items() if not k.startswith('__')})

from .airports import AirportMixin
from .test_mode import TestMode

class FlightTracker(AirportMixin):
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
        line = f"[{dt.now().strftime('%H:%M:%S')}] {cat:<12} | {msg}"
        # Errors and warnings always go to console; everything else is file-only.
        if cat in ('ERROR', 'WARNING'):
            print(line)
        else:
            print(f"[DEBUG]{line}")
    
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

    def fetch_visitor_tracking(self):
        if not self.track_flight_id: return
        
        try:
            self.log("TRACKER", f"Fetching flight: {self.track_flight_id}")
            airline_icao, airline_iata, _flight_num = self.parse_flight_code(self.track_flight_id)
            airline_code = airline_iata or airline_icao
            airline_logo = self._get_airline_logo_url(airline_code)
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
                        'airline': airline_code,
                        'airline_iata': airline_iata,
                        'airline_icao': airline_icao,
                        'airline_logo': airline_logo,
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
                    'airline': airline_code,
                    'airline_iata': airline_iata,
                    'airline_icao': airline_icao,
                    'airline_logo': airline_logo,
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
