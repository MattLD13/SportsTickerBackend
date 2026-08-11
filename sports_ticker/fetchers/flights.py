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
        # The SDK client is not thread-safe, and three separate callers reach
        # it: the flights worker for the airport board, the same worker for
        # visitor tracking, and Flask request threads via /api routes. When two
        # overlap one returns an empty list, which is why tracking a flight
        # worked only sometimes. Serialise every call through this.
        self._fr_lock = threading.Lock()
    
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

    @staticmethod
    def _code_candidates(code):
        """Every plausible (airline, number) split of a flight code.

        The split is genuinely ambiguous for carriers whose IATA code contains a
        digit: F92201 is Frontier 2201 or 'F' 92201, and B61004 is JetBlue 1004
        or 'B' 61004. Return both readings and let the caller decide, rather
        than guessing — the ambiguity appears on the requested code and on the
        flight's own fields independently, so guessing wrong on either loses the
        match. Leading zeros are dropped so UAL0072 and UA72 compare equal.
        """
        text = str(code or '').upper().replace(' ', '').replace('-', '')
        out = []
        for pattern in (r'^([A-Z]*?)0*(\d+)$',      # shortest alpha prefix
                        r'^([A-Z]\d)0*(\d+)$',      # IATA code containing a digit
                        r'^([A-Z]{2,3})0*(\d+)$'):  # plain IATA / ICAO prefix
            match = re.match(pattern, text)
            if match:
                pair = (match.group(1), match.group(2))
                if pair not in out:
                    out.append(pair)
        return out

    @classmethod
    def _split_flight_code(cls, code):
        """The single most likely (airline, number) split, or ('', '')."""
        candidates = cls._code_candidates(code)
        return candidates[0] if candidates else ('', '')

    @staticmethod
    def _airline_aliases(*codes):
        """Every airline code that means the same carrier as any of `codes`.

        Walks the IATA/ICAO maps in both directions and closes over the result,
        so a lookup succeeds through whichever code the data happens to carry.
        The maps are also stale in places — RPA resolves to 'RW' where Republic
        now uses 'YX' — and following both directions recovers from that as long
        as any one code lines up.
        """
        seen = set()
        pending = [str(c).upper() for c in codes if c]
        while pending:
            code = pending.pop()
            if not code or code in seen:
                continue
            seen.add(code)
            for other in (_ICAO_TO_IATA.get(code), _IATA_TO_ICAO.get(code)):
                if other:
                    pending.append(str(other).upper())
        return seen

    def _find_live_fr24_search(self, flight_code, aliases, wanted_numbers):
        """Find an exact live flight through FR24's search endpoint."""
        try:
            response = self._fr_call(self.fr_api.search, flight_code)
        except Exception as e:
            self.log("DEBUG", f"FR24 live search failed: {e}")
            return None

        matches = []
        requested = str(flight_code).upper().replace(' ', '').replace('-', '')
        for item in (response or {}).get('live', []):
            details = item.get('detail') or {}
            score = 0
            for value in (details.get('flight'), details.get('callsign')):
                compact = str(value or '').upper().replace(' ', '').replace('-', '')
                if compact == requested:
                    score = max(score, 2)
                for prefix, number in self._code_candidates(compact):
                    if number in wanted_numbers and prefix in aliases:
                        score = max(score, 1)
            if score:
                matches.append((score, item, details))

        if not matches:
            return None
        _, item, details = max(matches, key=lambda match: match[0])
        return type('FR24SearchFlight', (), {
            'id': str(item.get('id') or ''),
            'number': str(details.get('flight') or ''),
            'callsign': str(details.get('callsign') or ''),
            'origin_airport_iata': str(details.get('schd_from') or ''),
            'destination_airport_iata': str(details.get('schd_to') or ''),
            'latitude': details.get('lat'),
            'longitude': details.get('lon'),
            'altitude': 0,
            'ground_speed': 0,
            'aircraft_code': str(details.get('ac_type') or ''),
            'aircraft_model': '',
        })()

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
            
            # Parse the flight code. An unrecognised prefix is not fatal — the
            # raw code is still searched against every callsign below.
            try:
                icao, iata, flight_num = self.parse_flight_code(flight_id)
            except Exception as e:
                self.log("DEBUG", f"Could not parse {flight_id} ({e}); searching the code as typed")
                icao, iata, flight_num = '', '', ''

            self.log("INFO", f"Searching for flight {flight_id} (ICAO: {icao}, IATA: {iata}, #: {flight_num})")
            
            # Everything the code could mean, worked out before any request so
            # the airline filter can be tried under each of them.
            raw = str(flight_id).upper().replace(" ", "")
            wanted = self._code_candidates(raw)
            want_numbers = {n for _, n in wanted}
            if flight_num:
                want_numbers.add(str(flight_num).lstrip('0'))
            aliases = self._airline_aliases(*[pfx for pfx, _ in wanted], icao, iata)

            # Try the airline filter under each code meaning this carrier. FR24
            # indexes some regionals under one code and not another —
            # airline='RPA' returns nothing for Republic — and the unfiltered
            # fallback is a capped global sample the flight may simply not be
            # in, so exhausting the filters first is what gives full coverage.
            filter_codes = [c for c in (icao, iata) if c]
            filter_codes += [c for c in sorted(aliases) if c not in filter_codes and len(c) in (2, 3)]

            flights = None
            for code in filter_codes[:3]:
                try:
                    flights = self._fr_call(self.fr_api.get_flights, airline=code)
                except Exception as e:
                    self.log("DEBUG", f"Airline filter {code} failed: {e}")
                    flights = None
                if flights:
                    self.log("INFO", f"Got {len(flights)} {code} flights from API")
                    break
                self.log("DEBUG", f"Airline filter {code} came back empty")

            if not flights:
                # A filter matching nothing returns an empty list rather than
                # raising, and the fallback only ran on an exception — so any
                # carrier FR24 does not index under its ICAO code could never be
                # tracked. RPA4601 parsed correctly and still died here.
                self.log("DEBUG", "No airline filter matched; searching all flights")
                flights = self._fr_call(self.fr_api.get_flights)
                if flights:
                    self.log("INFO", f"Got {len(flights)} total flights from API")

            if not flights:
                self.log("DEBUG", "No flights returned by API. Trying exact live search.")
                flights = []

            # Match on the number plus any code meaning the same carrier, rather
            # than on reconstructed strings. The code a passenger holds is often
            # not the callsign: Republic flies RPA4601 while the ticket and
            # FR24's own 'number' field say YX4601.
            target_flight = None
            digit_only = {}
            for flight in flights:
                for field in (getattr(flight, 'number', ''), getattr(flight, 'callsign', '')):
                    for prefix, digits in self._code_candidates(field):
                        if digits not in want_numbers:
                            continue
                        if prefix and prefix in aliases:
                            target_flight = flight
                            break
                        # Same number under an unrelated prefix — a regional
                        # operating for a mainline carrier. Keep as a candidate.
                        digit_only[id(flight)] = flight
                    if target_flight:
                        break
                if target_flight:
                    break

            if target_flight:
                self.log("INFO", f"✓ Found {flight_id}: {target_flight.number} ({target_flight.callsign})")
            elif len(digit_only) == 1:
                target_flight = next(iter(digit_only.values()))
                self.log("INFO", f"✓ {flight_id} matched {target_flight.callsign} "
                                 f"({target_flight.number}) on flight number alone")
            elif digit_only:
                self.log("WARNING", f"{flight_id}: {len(digit_only)} flights share that number, "
                                    f"none under a known {icao or iata} code")

            if not target_flight:
                target_flight = self._find_live_fr24_search(raw, aliases, want_numbers)
                if target_flight:
                    self.log("INFO", f"✓ Found {flight_id} through FR24 live search: "
                             f"{target_flight.number} ({target_flight.callsign})")

            if not target_flight:
                self.log("WARNING", f"Flight {flight_id} not found - may not be airborne right now")
                self.log("DEBUG", f"Wanted #{sorted(want_numbers)} under any of {sorted(aliases)}")
                return None
            
            # Get detailed information if available
            details = None
            try:
                details = self._fr_call(self.fr_api.get_flight_details, target_flight)
                if hasattr(target_flight, 'set_flight_details'):
                    target_flight.set_flight_details(details)
                trail = (details or {}).get('trail') or []
                if trail:
                    position = trail[0]
                    target_flight.latitude = position.get('lat', target_flight.latitude)
                    target_flight.longitude = position.get('lng', target_flight.longitude)
                    target_flight.altitude = position.get('alt', target_flight.altitude)
                    target_flight.ground_speed = position.get('spd', target_flight.ground_speed)
            except Exception as e:
                self.log("DEBUG", f"Could not get detailed info: {e}")

            delay_min, status_text, est_arr = _extract_delay_minutes(details)

            # Aircraft type: prefer detailed model from FR24, fall back to ICAO type code normalization
            fr24_model = (getattr(target_flight, 'aircraft_model', None) or
                          ((details or {}).get('aircraft', {}).get('model', {}) or {}).get('text', ''))
            icao_type = (getattr(target_flight, 'aircraft_code', None) or
                         ((details or {}).get('aircraft', {}).get('model', {}) or {}).get('code', ''))
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
