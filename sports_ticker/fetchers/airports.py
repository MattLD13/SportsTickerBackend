import concurrent.futures
import re

from .. import core as _core
globals().update({k: v for k, v in vars(_core).items() if not k.startswith('__')})


# Rows the panel shows per side. The board renders four; fetching exactly
# that avoids carrying rows nothing will draw.
BOARD_ROWS = 4

# How long a good board survives failed fetches before it is allowed to empty.
# FR24 returns an empty list when throttled, which is indistinguishable from a
# quiet airport, so hold the last good result rather than blanking the display.
AIRPORT_HOLD_SECONDS = 300


class AirportMixin:
    def _get_airline_identifiers(self, flight_code):
        code = str(flight_code or '').strip().upper().replace(' ', '')
        if not code:
            return '', '', ''

        match = re.match(r'^([A-Z]{2,3})(.*)$', code)
        if not match:
            return '', '', code

        prefix = match.group(1)
        number = match.group(2).lstrip()
        if len(prefix) == 2:
            icao = _IATA_TO_ICAO.get(prefix, '')
            if not icao:
                icao, _ = ai_lookup_airline_codes(prefix)
            return str(icao or '').upper(), prefix, number

        iata = _ICAO_TO_IATA.get(prefix, '')
        if not iata:
            _, iata = ai_lookup_airline_codes(prefix)
        return prefix, str(iata or '').upper(), number

    def _get_airline_logo_url(self, airline_code):
        code = str(airline_code or '').strip().upper()
        if not code:
            return ''
        # Fast-path map for common carriers (avoids an AI call on first render)
        _KNOWN_DOMAINS = {
            'UA': 'united.com',       'UAL': 'united.com',
            'DL': 'delta.com',        'DAL': 'delta.com',
            'AA': 'aa.com',           'AAL': 'aa.com',
            'WN': 'southwest.com',    'SWA': 'southwest.com',
            'B6': 'jetblue.com',      'JBU': 'jetblue.com',
            'AS': 'alaskaair.com',    'ASA': 'alaskaair.com',
            'NK': 'spirit.com',       'NKS': 'spirit.com',
            'F9': 'flyfrontier.com',  'FFT': 'flyfrontier.com',
            'AC': 'aircanada.com',    'ACA': 'aircanada.com',
            'BA': 'britishairways.com', 'BAW': 'britishairways.com',
            'LH': 'lufthansa.com',    'DLH': 'lufthansa.com',
            'AF': 'airfrance.com',    'AFR': 'airfrance.com',
            'KL': 'klm.com',          'KLM': 'klm.com',
            'EK': 'emirates.com',     'UAE': 'emirates.com',
            'QR': 'qatarairways.com', 'QTR': 'qatarairways.com',
            'SQ': 'singaporeair.com', 'SIA': 'singaporeair.com',
            'VS': 'virginatlantic.com', 'VIR': 'virginatlantic.com',
            'CX': 'cathaypacific.com', 'CPA': 'cathaypacific.com',
            'JL': 'jal.com',          'JAL': 'jal.com',
            'NH': 'ana.co.jp',        'ANA': 'ana.co.jp',
        }
        domain = _KNOWN_DOMAINS.get(code)
        if not domain:
            domain = ai_lookup_airline_domain(code)
        if domain:
            return f"https://www.google.com/s2/favicons?domain={domain}&sz=64"
        return ''

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

    @staticmethod
    def _parse_ts(value):
        """Extract an integer Unix timestamp from either a plain int or a dict like {"utc": 123}."""
        if isinstance(value, dict):
            for key in ('utc', 'unix', 'time', 'timestamp'):
                if key in value:
                    value = value[key]
                    break
        try:
            return int(value)
        except Exception:
            return None

    @staticmethod
    def _flight_iata(flight, role):
        """IATA code for a live flight's origin or destination.

        Read through the same helper for both roles so the two directions
        cannot drift apart, and tolerate the SDK naming the attribute
        differently between versions.
        """
        names = {
            'origin': ('origin_airport_iata', 'origin_airport', 'origin'),
            'destination': ('destination_airport_iata', 'destination_airport',
                            'destination'),
        }[role]
        for name in names:
            value = str(getattr(flight, name, '') or '').strip().upper()
            if len(value) == 3 and value.isalpha():
                return value
        return ''

    # FR24 answers a too-soon call with an empty list rather than an error or a
    # 429, so spacing is the only way to tell the difference between "no
    # traffic" and "asked again too fast".
    _FR_MIN_GAP = 2.0
    _FR_RETRY_DELAY = 1.5

    def _fr_call(self, fn, *args, **kwargs):
        """Run one FR24 SDK call: serialised, spaced, and retried once on empty.

        The client is shared by the airport board, the visitor tracker and
        Flask request threads. Beyond not being thread-safe it also rate-limits
        silently — the log shows the board receiving 1500 flights and the
        tracker receiving nothing one second later, then both succeeding on the
        next pass. Hold the lock across the wait so the spacing applies between
        callers, not just within one.
        """
        with self._fr_lock:
            result = None
            for attempt in (0, 1):
                gap = time.time() - getattr(self, '_fr_last_call', 0.0)
                if gap < self._FR_MIN_GAP:
                    time.sleep(self._FR_MIN_GAP - gap)
                try:
                    result = fn(*args, **kwargs)
                finally:
                    self._fr_last_call = time.time()
                if result:
                    return result
                if attempt == 0:
                    time.sleep(self._FR_RETRY_DELAY)
            return result

    def _airport_bounds(self, degrees=2.0):
        """FR24 bounds box around the configured airport, or None.

        Filtering the global sample does not surface the traffic that is
        actually at the airport. LAS — a top-ten US airport — yielded four
        arrivals and one departure from 1500 flights, and every one was a
        long-haul at cruise: Manchester and Frankfurt inbound at 38,000ft, the
        Seoul departure already over the Pacific. The snapshot skews to
        long-haul, so the short-haul traffic that fills the airport never
        appears. Asking for the box around the airport returns the aircraft on
        approach and just departed instead.
        """
        code = str(getattr(self, 'airport_code_iata', '') or '').strip().upper()
        ap = (AIRPORTS_DB or {}).get(code) or {}
        try:
            lat = float(ap['lat'])
            lon = float(ap['lon'])
        except (KeyError, TypeError, ValueError):
            return None
        # north, south, west, east
        return f"{lat + degrees},{lat - degrees},{lon - degrees},{lon + degrees}"

    def fetch_fr24_board(self):
        """Arrivals and departures for the configured airport, from one query.

        These used to run as two concurrent calls to the same SDK client, each
        pulling the identical global flight list and differing only in how they
        filtered it. The client is not thread-safe, so the two races and one
        side comes back empty — which side varied from one refresh to the next,
        showing as arrivals-only or departures-only. One fetch, two filters.
        """
        if not self.fr_api:
            return [], []
        airport_iata = str(getattr(self, 'airport_code_iata', '') or '').strip().upper()
        if not airport_iata:
            return [], []
        try:
            details = self._fr_call(
                self.fr_api.get_airport_details, airport_iata, flight_limit=20
            )
        except Exception as e:
            self.log("ERROR", f"FR24 airport schedule: {e}")
            return [], []
        if not details:
            self.log("DEBUG", "FR24 airport schedule returned nothing")
            return [], []
        return (self._fr24_schedule_side(details, 'arrivals'),
                self._fr24_schedule_side(details, 'departures'))

    def _fr24_schedule_side(self, details, mode):
        """Convert one FR24 airport schedule side to ticker rows."""
        try:
            schedule = (details.get('airport', {}).get('pluginData', {})
                         .get('schedule', {}).get(mode, {}))
            flights = schedule.get('data') or []
            role = 'origin' if mode == 'arrivals' else 'destination'
            city_key = 'from' if mode == 'arrivals' else 'to'
            iata_key = f'{city_key}_iata'
            status_label = 'ARRIVING' if mode == 'arrivals' else 'DEPARTING'
            now = int(time.time())
            rows = []

            for item in flights:
                flight = item.get('flight') or {}
                identification = flight.get('identification') or {}
                display_id = str((identification.get('number') or {}).get('default')
                                 or identification.get('callsign') or '').strip()
                airport = ((flight.get('airport') or {}).get(role) or {})
                code = str((airport.get('code') or {}).get('iata') or '').upper()
                if not display_id or len(code) != 3:
                    continue

                time_info = flight.get('time') or {}
                point = 'arrival' if mode == 'arrivals' else 'departure'
                scheduled = self._parse_ts((time_info.get('scheduled') or {}).get(point))
                estimated = self._parse_ts((time_info.get('estimated') or {}).get(point))
                actual = self._parse_ts((time_info.get('real') or {}).get(point))
                event_time = actual or estimated or scheduled
                if event_time and event_time < now - 3600:
                    continue

                airline_icao, airline_iata, flight_number = self._get_airline_identifiers(display_id)
                rows.append({
                    'id': display_id,
                    'airline': airline_iata or airline_icao,
                    'airline_icao': airline_icao,
                    'airline_iata': airline_iata,
                    'flight_number': flight_number or display_id,
                    city_key: get_city_name(code),
                    iata_key: code,
                    'status_label': status_label,
                    'altitude': None,
                    'sort_time': event_time or now,
                })

            rows.sort(key=lambda row: row['sort_time'])
            deduped = []
            seen = set()
            for row in rows:
                key = (row['id'], row[iata_key])
                if key not in seen:
                    seen.add(key)
                    deduped.append(row)
            self.log("DEBUG", f"FR24 airport {mode}: {len(flights)} scheduled → {min(len(deduped), BOARD_ROWS)} rows")
            return deduped[:BOARD_ROWS]
        except Exception as e:
            self.log("ERROR", f"FR24 airport schedule {mode}: {e}")
            return []

    def _fr24_board_side(self, flights, airport_iata, mode):
        """Filter one already-fetched flight list down to one side of the board."""
        try:
            now = int(time.time())
            processed_list = []

            for flight in flights:
                try:
                    altitude = getattr(flight, 'altitude', 0) or 0
                    on_ground = getattr(flight, 'on_ground', None)
                    if altitude <= 0 or on_ground in (1, True, '1'):
                        # Aircraft on the ground still name this airport as
                        # their origin or destination, and the list is sorted
                        # lowest-altitude-first — so anything parked or taxiing
                        # sorted to the very top. Inbound filled with flights
                        # that had already landed, and they had no altitude to
                        # show because theirs is zero.
                        continue
                    callsign = str(getattr(flight, 'callsign', '') or '').strip()
                    number = str(getattr(flight, 'number', '') or '').strip()
                    display_id = callsign or number
                    if not display_id:
                        continue

                    origin = self._flight_iata(flight, 'origin')
                    dest = self._flight_iata(flight, 'destination')
                    if mode == 'arrivals':
                        if dest != airport_iata:
                            continue
                        entry = {
                            # City, not airport name: "Newark" rather than
                            # "Newark Liberty", "Atlanta" rather than
                            # "Hartsfield/Jackson Atlanta". The IATA code rides
                            # along so multi-airport cities stay unambiguous.
                            'from': get_city_name(origin),
                            'from_iata': origin,
                            'status_label': 'ARRIVING',
                        }
                    else:
                        if origin != airport_iata:
                            continue
                        entry = {
                            'to': get_city_name(dest),
                            'to_iata': dest,
                            'status_label': 'DEPARTING',
                        }

                    airline_icao, airline_iata, flight_number = self._get_airline_identifiers(display_id)
                    airline_code = airline_iata or airline_icao

                    # Lower altitude = closer to landing (arrivals) or just departed (departures)
                    # Negate altitude so lower altitude sorts first (highest sort_time)
                    entry['id'] = display_id
                    entry['airline'] = airline_code
                    entry['airline_icao'] = airline_icao
                    entry['airline_iata'] = airline_iata
                    entry['flight_number'] = flight_number or display_id
                    entry['altitude'] = int(altitude)
                    entry['sort_time'] = now - altitude
                    processed_list.append(entry)
                except:
                    continue

            # Sort by descending sort_time: lowest altitude (closest to landing/just departed) first
            processed_list.sort(key=lambda x: x['sort_time'], reverse=True)

            # Deduplicate flights with same city and similar altitude
            seen_keys = set()
            deduped = []
            for entry in processed_list:
                city = entry.get('to') or entry.get('from') or ''
                altitude_bucket = round(entry['sort_time'] / 300)  # 5-min buckets
                key = (altitude_bucket, city)
                if key not in seen_keys:
                    seen_keys.add(key)
                    deduped.append(entry)

            self.log("DEBUG", f"FR24 SDK {mode}: {len(flights)} total → {len(processed_list)} at {airport_iata} → returning {min(len(deduped), BOARD_ROWS)}")
            return deduped[:BOARD_ROWS]

        except Exception as e:
            self.log("ERROR", f"FR24 SDK board {mode}: {e}")
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

            # Both sides of the board come from one FR24 query — the SDK client
            # is not thread-safe and cannot serve two at once. Weather is a
            # plain HTTP call on a separate session, so it still overlaps.
            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
                f_board = pool.submit(self.fetch_fr24_board)
                f_wx = pool.submit(self.fetch_airport_weather)
                arrivals, departures = f_board.result()
                weather = f_wx.result()

            # Single airport-change guard after all three complete
            if self._get_airport_query_code() != target_code:
                self.log("DEBUG", "Airport changed mid-fetch, discarding results")
                return

            now = time.time()
            with self.lock:
                if arrivals or departures:
                    self.airport_arrivals = arrivals
                    self.airport_departures = departures
                    self._airport_data_ts = now
                elif now - getattr(self, '_airport_data_ts', 0.0) > AIRPORT_HOLD_SECONDS:
                    # Nothing for several minutes running — let it empty rather
                    # than keep showing aircraft that have long since landed.
                    self.airport_arrivals = []
                    self.airport_departures = []
                else:
                    # One throttled or failed fetch used to blank a board that
                    # was correct half a minute earlier. Keep the last good one.
                    self.log("DEBUG", "empty board fetch — holding previous flights")
                    arrivals = self.airport_arrivals
                    departures = self.airport_departures
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
                'iata': str(getattr(self, 'airport_code_iata', '') or '').upper(),
                # Short city for the board header — the configured airport_name is
                # the full legal name ("Newark Liberty International Airport").
                'city': get_city_name(str(getattr(self, 'airport_code_iata', '') or '').upper()),
                'away_abbr': self.airport_weather['temp'], 'status': self.airport_weather['cond'], 'is_shown': True
            })
            for i, arr in enumerate(self.airport_arrivals[:BOARD_ROWS]):
                # Use specific status if available, else fallback
                st = arr.get('status_label', 'ARRIVING')
                result.append({'type': 'flight_arrival', 'sport': 'flight', 'id': f"arr_{i}", 'status': st,
                               'home_abbr': arr['from'], 'away_abbr': arr['id'],
                               'other_iata': arr.get('from_iata', ''),
                               'altitude': arr.get('altitude'), 'is_shown': True})
            for i, dep in enumerate(self.airport_departures[:BOARD_ROWS]):
                st = dep.get('status_label', 'DEPARTING')
                result.append({'type': 'flight_departure', 'sport': 'flight', 'id': f"dep_{i}", 'status': st,
                               'home_abbr': dep['to'], 'away_abbr': dep['id'],
                               'other_iata': dep.get('to_iata', ''),
                               'altitude': dep.get('altitude'), 'is_shown': True})
            return result
