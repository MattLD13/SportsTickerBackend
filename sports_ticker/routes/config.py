from .. import core as _core
from .. import workers as _workers
from ..routes_runtime import app
globals().update({k: v for k, v in vars(_core).items() if not k.startswith('__')})
globals().update({k: v for k, v in vars(_workers).items() if not k.startswith('__')})

@app.route('/api/config', methods=['POST'])
def api_config():
    try:
        new_data = request.json
        if not isinstance(new_data, dict): return jsonify({"error": "Invalid payload"}), 400

        # Migrate legacy modes to canonical mode names
        incoming_submode = new_data.get('flight_submode')
        def _infer_legacy_flight_mode(payload_mode: str | None, submode: str | None) -> str | None:
            submode_norm = str(submode or '').strip().lower()
            payload_mode_norm = str(payload_mode or '').strip().lower()
            if submode_norm == 'track' and payload_mode_norm in ('', 'sports', 'all', 'flights'):
                return 'flight_tracker'
            if submode_norm == 'airport' and payload_mode_norm in ('', 'sports', 'all', 'flight_tracker'):
                return 'flights'
            return None

        # Pin normalization (ticker-scoped): always keep a single pinned game.
        normalized_pin = None
        normalized_pin_list = None
        if 'pinned_game' in new_data or 'pinned_games' in new_data:
            normalized_pin, normalized_pin_list = _normalize_single_pin(
                pinned_game=new_data.get('pinned_game'),
                pinned_games=new_data.get('pinned_games')
            )

        if 'mode' in new_data:
            new_data['mode'] = normalize_mode(new_data['mode'])
            # Submode compatibility: allow both directions
            if incoming_submode == 'track':
                new_data['mode'] = 'flight_tracker'
            elif incoming_submode == 'airport' and new_data['mode'] == 'flight_tracker':
                new_data['mode'] = 'flights'
            else:
                inferred_mode = _infer_legacy_flight_mode(new_data['mode'], incoming_submode)
                if inferred_mode:
                    new_data['mode'] = inferred_mode
        elif incoming_submode in ('track', 'airport'):
            new_data['mode'] = 'flight_tracker' if incoming_submode == 'track' else 'flights'
        else:
            inferred_mode = _infer_legacy_flight_mode(new_data.get('mode'), incoming_submode)
            if inferred_mode:
                new_data['mode'] = inferred_mode
        # Drop flight_submode — no longer a valid key
        new_data.pop('flight_submode', None)
        
        cid = request.headers.get('X-Client-ID')

        # 1. Determine which ticker is being targeted
        target_id = resolve_ticker_id(new_data.get('ticker_id') or request.args.get('id'), cid)

        # If a specific ticker is targeted but doesn't exist yet, create it so
        # mode and other settings are applied locally instead of falling back to
        # global state.
        if target_id and target_id not in tickers:
            seed_client = cid or target_id
            tickers[target_id] = create_ticker_record(client_id=seed_client)
            save_specific_ticker(target_id)

        # ================= SECURITY CHECK START =================
        if target_id and target_id in tickers:
            rec = tickers[target_id]
            
            # If the client ID is not in the list, block them. 
            if cid not in rec.get('clients', []):
                print(f"⛔ Blocked unauthorized config change from {cid}")
                return jsonify({"error": "Unauthorized: Device not paired"}), 403
        # ================== SECURITY CHECK END ==================

        with data_lock:
            # Update Weather (Global)
            new_city = new_data.get('weather_city')
            if new_city: 
                fetcher.weather.update_config(city=new_city, lat=new_data.get('weather_lat'), lon=new_data.get('weather_lon'))

            # Update Flight Tracker (Global)
            if flight_tracker:
                flight_changed = False
                if 'track_flight_id' in new_data:
                    flight_tracker.track_flight_id = new_data.get('track_flight_id', '')
                    flight_changed = True
                if 'track_guest_name' in new_data:
                    flight_tracker.track_guest_name = new_data.get('track_guest_name', '')
                
                # Auto-fill airport information when any airport code is provided
                airport_code_input = None
                if 'airport_code_iata' in new_data:
                    airport_code_input = new_data.get('airport_code_iata', '').strip()
                elif 'airport_code_icao' in new_data:
                    airport_code_input = new_data.get('airport_code_icao', '').strip()
                
                if airport_code_input:
                    # Perform airport lookup
                    airport_info = lookup_and_auto_fill_airport(airport_code_input)
                    legacy_flights_payload = incoming_submode in ('airport', 'track')
                    
                    if airport_info['iata']:  # Only update if airport was found
                        flight_tracker.airport_code_iata = airport_info['iata']
                        flight_tracker.airport_code_icao = airport_info['icao']
                        flight_tracker.airport_name = airport_info['name']
                        print(f"✅ Airport auto-fill: {airport_info['iata']} ({airport_info['icao']}) - {airport_info['name']}")
                        flight_changed = True
                    else:
                        print(f"⚠️ Airport code '{airport_code_input}' not found in database")
                        if 3 <= len(airport_code_input) <= 4:
                            # Preserve raw airport codes even when the lookup database misses them.
                            # This keeps the flight worker functional for airportsdata gaps and
                            # older app builds that still send a valid airport code.
                            flight_tracker.airport_code_iata = airport_code_input.upper()
                            incoming_icao = str(new_data.get('airport_code_icao', '') or '').strip().upper()
                            incoming_name = str(new_data.get('airport_name', '') or '').strip()
                            if incoming_icao:
                                flight_tracker.airport_code_icao = incoming_icao
                            elif len(airport_code_input) == 4:
                                flight_tracker.airport_code_icao = airport_code_input.upper()
                            if incoming_name:
                                flight_tracker.airport_name = incoming_name
                            elif not flight_tracker.airport_name:
                                flight_tracker.airport_name = airport_code_input.upper()
                        else:
                            # Clear airport info if the input is not even airport-like.
                            flight_tracker.airport_code_iata = ''
                            flight_tracker.airport_code_icao = ''
                            flight_tracker.airport_name = ''
                        flight_changed = True
                elif 'airport_code_icao' in new_data:
                    flight_tracker.airport_code_icao = new_data.get('airport_code_icao', '')
                    flight_changed = True
                if 'airport_name' in new_data and not airport_code_input:
                    flight_tracker.airport_name = new_data.get('airport_name', '')
                if flight_changed:
                    # Clear stale data immediately so old airport/flight info doesn't linger
                    with flight_tracker.lock:
                        flight_tracker.airport_arrivals = []
                        flight_tracker.airport_departures = []
                        flight_tracker.airport_weather = {"temp": "--", "cond": "LOADING"}
                        if not flight_tracker.track_flight_id:
                            flight_tracker.visitor_flight = None
                    # Signal the flights_worker to fetch immediately (no 30s wait)
                    flight_tracker.force_update()
            
            allowed_keys = {
                'active_sports', 'mode', 'layout_mode', 'my_teams', 'debug_mode', 'custom_date',
                'weather_city', 'weather_lat', 'weather_lon', 'utc_offset',
                'timezone_name',
                'track_flight_id', 'track_guest_name', 'airport_code_icao',
                'airport_code_iata', 'airport_name',
                'test_mode', 'test_spotify', 'test_stocks', 'test_sports_date', 'test_flights',
                'pinned_game', 'pinned_games'
            }
            
            for k, v in new_data.items():
                if k not in allowed_keys: continue
                
                # HANDLE TEAMS
                if k == 'my_teams':
                    if v is None or (isinstance(v, list) and not v):
                        # null or empty list = reset ticker to use global fallback (always [])
                        if target_id and target_id in tickers:
                            tickers[target_id]['my_teams'] = None
                            tickers[target_id].pop('my_teams_set', None)
                        continue
                    elif isinstance(v, list):
                        cleaned = []
                        seen = set()
                        for e in v:
                            if e:
                                entry = str(e).strip()
                                if ':' in entry:
                                    # Already prefixed: normalize to lowercase_league:UPPER_ABBR
                                    lg, ab = entry.split(':', 1)
                                    raw = f"{lg.lower()}:{ab.upper()}"
                                else:
                                    # Plain abbr: look up league and normalize
                                    ab = entry.upper()
                                    matches = [lg for lg, idx in fetcher._teams_abbr_index.items() if ab in idx]
                                    raw = f"{matches[0]}:{ab}" if len(matches) == 1 else ab
                                if raw not in seen:
                                    seen.add(raw)
                                    cleaned.append(raw)
                        if target_id and target_id in tickers:
                            tickers[target_id]['my_teams'] = cleaned if cleaned else None
                            tickers[target_id].pop('my_teams_set', None)
                        # else: global my_teams always stays [] — ignore untargeted team updates
                        continue

                # HANDLE ACTIVE SPORTS — only accept keys that exist in LEAGUE_OPTIONS
                if k == 'active_sports' and isinstance(v, dict):
                    for ak, av in v.items():
                        if ak in _VALID_LEAGUE_IDS:
                            state['active_sports'][ak] = av
                    continue
                
                # HANDLE MODE — per-ticker isolation
                if k == 'mode':
                    if target_id and target_id in tickers:
                        # Targeted request: only update this ticker's mode
                        tickers[target_id]['settings']['mode'] = v
                    else:
                        # No specific target: update the global default
                        state['mode'] = v
                    continue

                # HANDLE PINS — already normalized above; skip raw assignment
                if k in ('pinned_game', 'pinned_games'):
                    if target_id and target_id in tickers:
                        tickers[target_id]['settings']['pinned_game'] = normalized_pin or ''
                        tickers[target_id]['settings']['pinned_games'] = list(normalized_pin_list or [])
                    continue

                # HANDLE ALL OTHER SETTINGS
                if v is not None: state[k] = v

                # SYNC TO TICKER SETTINGS (non-mode keys only)
                if target_id and target_id in tickers:
                    if k in tickers[target_id]['settings']:
                        tickers[target_id]['settings'][k] = v
            
            # Sync auto-filled airport info back to state dictionary
            # (This ensures /api/state returns the validated airport data)
            if flight_tracker:
                state['airport_code_iata'] = flight_tracker.airport_code_iata
                state['airport_code_icao'] = flight_tracker.airport_code_icao
                state['airport_name'] = flight_tracker.airport_name
                state['track_flight_id'] = flight_tracker.track_flight_id
                state['track_guest_name'] = flight_tracker.track_guest_name

                # Also sync to ticker-specific settings if a ticker is targeted
                if target_id and target_id in tickers:
                    tickers[target_id]['settings']['airport_code_iata'] = flight_tracker.airport_code_iata
                    tickers[target_id]['settings']['airport_code_icao'] = flight_tracker.airport_code_icao
                    tickers[target_id]['settings']['airport_name'] = flight_tracker.airport_name
                    tickers[target_id]['settings']['track_flight_id'] = flight_tracker.track_flight_id
                    tickers[target_id]['settings']['track_guest_name'] = flight_tracker.track_guest_name

            # Force airline_filter to always be empty (support all airlines)
            state['airline_filter'] = ''

        # Sync TestMode whenever any test_* or debug key changes
        if any(k.startswith('test_') or k in ('debug_mode', 'custom_date') for k in new_data):
            sync_test_mode_from_state()

        # For flights modes, wake the background worker immediately so data is
        # ready as soon as possible (otherwise it can take up to 30 s to fetch).
        # Check effective mode: use targeted ticker's mode if set, else global.
        new_mode = (tickers[target_id]['settings'].get('mode') if (target_id and target_id in tickers)
                    else None) or state.get('mode', '')
        if new_mode in ('flights', 'flight_tracker') and flight_tracker:
            flight_tracker.force_update()

        # Rebuild buffer via centralized refresh queue (coalesced, non-overlapping).
        request_refresh('api_config')

        if target_id:
            save_specific_ticker(target_id)
            # Also persist global config for flight/weather settings that live globally
            save_global_config()
        else:
            save_global_config()
        
        current_teams = tickers[target_id].get('my_teams', []) if (target_id and target_id in tickers) else state['my_teams']
        
        resolved = {}
        if flight_tracker:
            resolved = {
                "airport_code_iata": flight_tracker.airport_code_iata,
                "airport_code_icao": flight_tracker.airport_code_icao,
                "airport_name":      flight_tracker.airport_name}
        return jsonify({"status": "ok", "saved_teams": current_teams, "ticker_id": target_id, **resolved})
        
    except Exception as e:
        print(f"Config Error: {e}") 
        return jsonify({"error": "Failed"}), 500


@app.route('/ticker/<tid>', methods=['POST'])
def update_settings(tid):
    if tid not in tickers: return jsonify({"error":"404"}), 404

    cid = request.headers.get('X-Client-ID')
    rec = tickers[tid]
    
    if not cid or cid not in rec.get('clients', []):
        print(f"⛔ Blocked unauthorized settings change from {cid}")
        return jsonify({"error": "Unauthorized: Device not paired"}), 403

    data = request.json
    rec['settings'].update(data)
    
    # --- FIX: Sync Mode (per-ticker only — do NOT touch global state['mode']) ---
    if 'mode' in data:
        new_mode = normalize_mode(data['mode'])

        with data_lock:
            # Only update this ticker's mode setting; other tickers keep theirs
            rec['settings']['mode'] = new_mode

        # Trigger immediate buffer rebuild through centralized queue.
        if new_mode in ('flights', 'flight_tracker') and flight_tracker:
            flight_tracker.force_update()
        request_refresh('ticker_mode_update')

    save_specific_ticker(tid)
    
    print(f"✅ Updated Settings for {tid}: {data}") 
    return jsonify({"success": True})


