import concurrent.futures
import re

from .. import core as _core
globals().update({k: v for k, v in vars(_core).items() if not k.startswith('__')})


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
            flights = self.fr_api.get_flights()
        except Exception as e:
            self.log("ERROR", f"FR24 SDK get_flights: {e}")
            return [], []
        if not flights:
            self.log("DEBUG", "FR24 SDK: get_flights returned nothing")
            return [], []
        return (self._fr24_board_side(flights, airport_iata, 'arrivals'),
                self._fr24_board_side(flights, airport_iata, 'departures'))

    def _fr24_board_side(self, flights, airport_iata, mode):
        """Filter one already-fetched flight list down to one side of the board."""
        try:
            now = int(time.time())
            processed_list = []

            for flight in flights:
                try:
                    altitude = getattr(flight, 'altitude', 0) or 0
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
                    airline_logo = self._get_airline_logo_url(airline_code)

                    # Lower altitude = closer to landing (arrivals) or just departed (departures)
                    # Negate altitude so lower altitude sorts first (highest sort_time)
                    entry['id'] = display_id
                    entry['airline'] = airline_code
                    entry['airline_icao'] = airline_icao
                    entry['airline_iata'] = airline_iata
                    entry['airline_logo'] = airline_logo
                    entry['flight_number'] = flight_number or display_id
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

            self.log("DEBUG", f"FR24 SDK {mode}: {len(flights)} total → {len(processed_list)} at {airport_iata} → returning {min(len(deduped), 2)}")
            return deduped[:2]

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
                result.append({'type': 'flight_arrival', 'sport': 'flight', 'id': f"arr_{i}", 'status': st,
                               'home_abbr': arr['from'], 'away_abbr': arr['id'],
                               'other_iata': arr.get('from_iata', ''), 'is_shown': True})
            for i, dep in enumerate(self.airport_departures[:2]):
                st = dep.get('status_label', 'DEPARTING')
                result.append({'type': 'flight_departure', 'sport': 'flight', 'id': f"dep_{i}", 'status': st,
                               'home_abbr': dep['to'], 'away_abbr': dep['id'],
                               'other_iata': dep.get('to_iata', ''), 'is_shown': True})
            return result
