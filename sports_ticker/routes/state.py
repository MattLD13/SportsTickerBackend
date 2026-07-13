import time
from flask import request, jsonify
from ..routes_runtime import app
from ..core import (
    state, tickers, data_lock,
    normalize_mode, _normalize_single_pin,
    resolve_ticker_id, create_ticker_record, save_specific_ticker, generate_pairing_code,
    SPORTS_MODE_FAMILY, NON_SCOREBOARD_TYPES, HIDDEN_STATUS_KEYWORDS, _ACTIVE_STATES,
    _get_ticker_timezone_context, _apply_timezone_to_game_times,
    _materialize_blank_logo_urls, _maybe_update_ticker_timezone_from_request,
    SERVER_VERSION,
)
from ..workers import request_refresh, fetcher


def _no_games_placeholder_object(now_label: str = ''):
    return {
        'type': 'clock',
        'sport': 'clock',
        'id': 'no_games_available',
        'is_shown': True,
        'no_games': True,
        'status': 'NO GAMES AVAILABLE',
        'home_abbr': 'NO GAMES',
        'away_abbr': 'AVAILABLE',
        'home_score': '',
        'away_score': '',
        'situation': {
            'message': 'NO GAMES AVAILABLE',
            'clock': now_label,
        },
    }

@app.route('/data', methods=['GET'])
def get_ticker_data():
    ticker_id = request.args.get('id')
    
    # 1. Resolve Ticker ID
    ticker_id = resolve_ticker_id(ticker_id)
    
    if not ticker_id:
        return jsonify({"status": "ok", "content": {"sports": []}})

    # Auto-create ticker if ID is unknown
    if ticker_id not in tickers:
        # Hardware device self-authorizes: its device_id is both the ticker key
        # and its client identity, so add it to clients automatically.
        tickers[ticker_id] = create_ticker_record(client_id=ticker_id)
        save_specific_ticker(ticker_id)

    rec = tickers[ticker_id]
    rec['last_seen'] = time.time()

    # Auto-detect ticker timezone from its public IP (ip-api.com) and persist.
    _maybe_update_ticker_timezone_from_request(ticker_id, request)
    
    # 2. Pairing Check
    if not rec.get('clients') or not rec.get('paired'):
        if not rec.get('pairing_code'):
            rec['pairing_code'] = generate_pairing_code()
            save_specific_ticker(ticker_id)
        return jsonify({ "status": "pairing", "code": rec['pairing_code'], "ticker_id": ticker_id })

    t_settings = rec['settings']

    # Per-ticker mode: use the ticker's own mode setting, fall back to global.
    # Dashboard previews may request any mode without persisting a ticker/global
    # mode change, matching /api/state and /api/preview/strip.png behavior.
    preview_mode = request.args.get('mode')
    if preview_mode:
        current_mode = normalize_mode(preview_mode)
    else:
        current_mode = normalize_mode(t_settings.get('mode') or state.get('mode', 'sports'), state.get('mode', 'sports'))
    
    # --- FORCE SPORTS_FULL IF TICKER HAS A PIN ---
    t_pinned_game = str(rec.get('settings', {}).get('pinned_game', '')).strip()
    t_pins = rec.get('settings', {}).get('pinned_games', [])
    has_pinned_game = bool(t_pinned_game) or (isinstance(t_pins, list) and any(str(p).strip() for p in t_pins))
    effective_pin = t_pinned_game if t_pinned_game else ''
    if not effective_pin and isinstance(t_pins, list):
        non_empty = [str(p).strip() for p in t_pins if str(p).strip()]
        if non_empty:
            effective_pin = non_empty[0]

    pin_league = ''
    pin_game_id = ''
    if effective_pin:
        pin_norm = str(effective_pin).strip().lower()
        if ':' in pin_norm:
            pin_league, pin_game_id = pin_norm.split(':', 1)
        else:
            pin_game_id = pin_norm
            # Backward compatibility for legacy unsuffixed masters pins.
            if pin_norm.startswith('masters'):
                pin_league = 'masters'

    # Pin overrides should only remap sports-family modes. Non-sports modes
    # (clock/weather/music/flights/etc.) must remain user-selectable.
    if has_pinned_game and current_mode in SPORTS_MODE_FAMILY:
        if pin_league in ('golf', 'masters'):
            current_mode = 'golf'
        else:
            current_mode = 'sports_full'

    # Sleep Mode: dim the display but still fetch real game data so it's
    # immediately available when the ticker wakes up (no stale-data bug).
    is_sleep = t_settings.get('brightness', 100) <= 0

    # 4. Content Fetching
    # Live delay only applies to sports content (history buffer only exists for sports)
    is_sports_mode = current_mode in SPORTS_MODE_FAMILY
    delay_seconds = (t_settings.get('live_delay_seconds', 0)
                     if (is_sports_mode and t_settings.get('live_delay_mode'))
                     else 0)
    if effective_pin and current_mode == 'sports_full':
        raw_games = fetcher.get_mode_snapshot('sports_full', delay_seconds)
        pin_id = str(effective_pin).split(':', 1)[-1]
        raw_games = [g for g in raw_games if str(g.get('id', '')) == pin_id]
    elif effective_pin and current_mode == 'golf':
        raw_games = fetcher.get_mode_snapshot('golf', delay_seconds)
    elif effective_pin and current_mode == 'masters':
        raw_games = fetcher.get_mode_snapshot('masters', 0)
        pin_id = (pin_game_id or str(effective_pin).split(':', 1)[-1]).strip().lower()
        raw_games = [
            g for g in raw_games
            if str(g.get('id', '')).strip().lower() == pin_id or str(g.get('sport', '')).lower() == 'masters'
        ]
    else:
        raw_games = fetcher.get_mode_snapshot(current_mode, delay_seconds)
    active_sports = state.get('active_sports', {})
    visible_items = []

    def _sport_for_data_mode(sport_name: str) -> str:
        sport_norm = str(sport_name or '').lower()
        return 'mlb' if sport_norm == 'wbc' else sport_norm

    # 5. Filter Buffer based on current_mode
    if current_mode == 'music':
        for g in raw_games:
            if g.get('type') == 'music':
                g['is_shown'] = True
                visible_items.append(g)
        
        # Fallback: If buffer is empty, fetch immediately
        if not visible_items:
            music_obj = fetcher.get_music_object(require_enabled=False)
            if music_obj: visible_items.append(music_obj)

    elif current_mode == 'my_teams':
        _ticker_teams = rec.get('my_teams')
        saved_teams = set(state.get('my_teams', []) if _ticker_teams is None else _ticker_teams)
        COLLISION_ABBRS = {'LV'}
        for g in raw_games:
            sport = _sport_for_data_mode(g.get('sport', ''))
            if not active_sports.get(sport, True): continue
            h_ab, a_ab = str(g.get('home_abbr', '')).upper(), str(g.get('away_abbr', '')).upper()
            in_home = f"{sport}:{h_ab}" in saved_teams or (h_ab in saved_teams and h_ab not in COLLISION_ABBRS)
            in_away = f"{sport}:{a_ab}" in saved_teams or (a_ab in saved_teams and a_ab not in COLLISION_ABBRS)
            if in_home or in_away:
                g_copy = g.copy()
                g_copy['sport'] = sport
                g_copy['is_shown'] = True
                visible_items.append(g_copy)

    elif current_mode == 'live':
        for g in raw_games:
            if g.get('type') == 'masters':
                continue
            sport = _sport_for_data_mode(g.get('sport', ''))
            if not active_sports.get(sport, True): continue
            if g.get('state') in _ACTIVE_STATES:
                g_copy = g.copy()
                g_copy['sport'] = sport
                g_copy['is_shown'] = True
                visible_items.append(g_copy)

    elif current_mode == 'sports_full':
        # Pinned game override — show everything without active_sports filtering
        for g in raw_games:
            if g.get('type') == 'masters':
                continue
            sport = _sport_for_data_mode(g.get('sport', ''))
            g_copy = g.copy()
            g_copy['sport'] = sport
            g_copy['is_shown'] = True
            visible_items.append(g_copy)

    elif current_mode == 'soccer_full':
        for g in raw_games:
            sport = _sport_for_data_mode(g.get('sport', ''))
            if not str(sport).startswith('soccer_'):
                continue
            g_copy = g.copy()
            g_copy['sport'] = sport
            g_copy['is_shown'] = True
            visible_items.append(g_copy)

    elif current_mode == 'golf':
        for g in raw_games:
            g_type = str(g.get('type', '')).lower()
            sport = str(g.get('sport', '')).lower()
            if g_type not in ('golf', 'masters') and sport not in ('golf', 'masters'):
                continue
            g_copy = g.copy()
            g_copy['sport'] = 'golf'
            g_copy['is_shown'] = True
            visible_items.append(g_copy)

    elif current_mode == 'sports':
        for g in raw_games:
            sport = _sport_for_data_mode(g.get('sport', ''))
            if not active_sports.get(sport, True): continue
            if g.get('type') in NON_SCOREBOARD_TYPES:
                continue
            status_lower = str(g.get('status', '')).lower()
            if any(k in status_lower for k in HIDDEN_STATUS_KEYWORDS):
                continue
            g_copy = g.copy()
            g_copy['sport'] = sport
            g_copy['is_shown'] = True
            visible_items.append(g_copy)

    else:
        # Stocks, Weather, Clock, Flights
        for g in raw_games:
            g_type, g_sport = g.get('type', ''), g.get('sport', '')
            match = False
            if current_mode == 'stocks' and g_type == 'stock_ticker': match = True
            elif current_mode == 'weather' and g_type == 'weather': match = True
            elif current_mode == 'clock' and g_type == 'clock': match = True
            elif current_mode == 'masters' and (g_type == 'masters' or str(g_sport).lower() == 'masters'): match = True
            elif current_mode == 'flights' and g_sport == 'flight': match = True
            elif current_mode == 'flight_tracker' and g_type == 'flight_visitor': match = True
            elif current_mode in ('indycar', 'indycar_full') and str(g_sport).lower() == 'indycar': match = True
            elif current_mode in ('f1', 'f1_full') and str(g_sport).lower() == 'f1': match = True
            elif current_mode in ('nascar', 'nascar_full') and str(g_sport).lower() == 'nascar': match = True

            if match:
                g['is_shown'] = True
                visible_items.append(g)

    _materialize_blank_logo_urls(visible_items, request)

    tz_name, tz_offset = _get_ticker_timezone_context(rec)
    _apply_timezone_to_game_times(visible_items, tz_name=tz_name, utc_offset=tz_offset)

    if not visible_items and current_mode in SPORTS_MODE_FAMILY:
        now_label = time.strftime('%I:%M %p').lstrip('0')
        visible_items = [_no_games_placeholder_object(now_label)]

    # 6. Final Response
    # Display-only override: if normal sports mode has exactly one item,
    # render it as full-bleed without persisting ticker/global mode changes.
    response_local_config = dict(t_settings)
    response_local_config['timezone_name'] = tz_name
    response_local_config['utc_offset'] = tz_offset
    effective_mode_for_response = current_mode
    if current_mode == 'sports' and len(visible_items) == 1:
        effective_mode_for_response = 'sports_full'
    response_local_config['mode'] = effective_mode_for_response

    # Report global config from global state only. Do not reflect per-ticker
    # pin overrides here, otherwise global_config.mode appears to change.
    g_config = { "mode": state.get('mode', 'sports') }
    if rec.get('reboot_requested'):
        g_config['reboot'] = True
        rec['reboot_requested'] = False
    if rec.get('update_requested'):
        g_config['update'] = True
        if rec.get('update_version'):
            g_config['update_version'] = rec['update_version']
        rec['update_requested'] = False
        
    return jsonify({
        "status": "sleep" if is_sleep else "ok",
        "version": SERVER_VERSION,
        "ticker_id": ticker_id,
        "global_config": g_config,
        "local_config": response_local_config,
        "content": { "sports": visible_items }
    })


@app.route('/api/state', methods=['GET'])
def api_state():
    ticker_id = request.args.get('id')
    
    # 1. Resolve Ticker ID (Manual, Header, or Single-Ticker Fallback)
    if not ticker_id:
        cid = request.headers.get('X-Client-ID')
        ticker_id = resolve_ticker_id(client_id=cid)

    # Initialize with global state, then override with ticker-specific settings if found
    with data_lock:
        response_settings = dict(state)
    if ticker_id and ticker_id in tickers:
        response_settings.update(tickers[ticker_id]['settings'])
        response_settings['active_sports'] = dict(state['active_sports'])  # global always wins
        _t_teams = tickers[ticker_id].get('my_teams')
        # None = use global fallback (always []); non-empty list = ticker's saved teams
        response_settings['my_teams'] = list(state.get('my_teams', [])) if _t_teams is None else _t_teams
        response_settings['ticker_id'] = ticker_id

        # Include stored timezone context (learned from /data ticker requests).
        _tz_name, _tz_offset = _get_ticker_timezone_context(tickers[ticker_id])
        response_settings['timezone_name'] = _tz_name
        response_settings['utc_offset'] = _tz_offset

    pinned_game = ''
    pinned_games = []
    if ticker_id and ticker_id in tickers:
        _settings = tickers[ticker_id].get('settings', {})
        pinned_game, pinned_games = _normalize_single_pin(
            pinned_game=_settings.get('pinned_game'),
            pinned_games=_settings.get('pinned_games', [])
        )
    response_settings['pinned_game'] = pinned_game
    response_settings['pinned_games'] = pinned_games
    response_settings['is_pinned'] = bool(pinned_game)

    current_mode = normalize_mode(response_settings.get('mode', 'sports'))

    # Allow web dashboard to preview any mode without changing ticker state
    _preview_mode = request.args.get('mode')
    if _preview_mode:
        current_mode = normalize_mode(_preview_mode)

    # Legacy app behavior: reflect pin by forcing a dedicated mode in /api/state.
    # Golf pins should use the golf UI; other sports-family pins use sports_full.
    if pinned_game and current_mode in SPORTS_MODE_FAMILY:
        current_mode = 'golf' if current_mode == 'masters' else 'sports_full'
        if str(pinned_game).split(':', 1)[0].strip().lower() in ('golf', 'masters'):
            current_mode = 'golf'
        response_settings['mode'] = current_mode

    response_settings['mode'] = current_mode
        
    response_settings['flight_submode'] = 'track' if current_mode == 'flight_tracker' else 'airport'

    is_sports_mode = current_mode in SPORTS_MODE_FAMILY
    delay_seconds = (response_settings.get('live_delay_seconds', 0)
                     if (is_sports_mode and response_settings.get('live_delay_mode'))
                     else 0)
    raw_games = fetcher.get_mode_snapshot(current_mode, delay_seconds)
    if pinned_game and current_mode == 'sports_full':
        pin_id = str(pinned_game).split(':', 1)[-1]
        raw_games = [g for g in raw_games if str(g.get('id', '')) == pin_id]
    elif pinned_game and current_mode == 'golf':
        raw_games = [
            g for g in raw_games
            if str(g.get('type', '')).lower() in ('golf', 'masters')
            or str(g.get('sport', '')).lower() in ('golf', 'masters')
        ]
    elif pinned_game and current_mode == 'masters':
        pin_id = str(pinned_game).split(':', 1)[-1].strip().lower()
        raw_games = [
            g for g in raw_games
            if str(g.get('id', '')).strip().lower() == pin_id or str(g.get('sport', '')).lower() == 'masters'
        ]
    processed_games = []
    saved_teams = set(response_settings.get('my_teams', []))
    COLLISION_ABBRS = {'LV'}
    _active_sports = state.get('active_sports', {})

    for g in raw_games:
        game_copy = g.copy()
        sport = game_copy.get('sport', '')
        g_type = game_copy.get('type', '')
        if current_mode in ('sports', 'live', 'my_teams'):
            should_show = _active_sports.get(sport, True)
        else:
            should_show = True

        if current_mode == 'my_teams':
            h_ab = str(game_copy.get('home_abbr', '')).upper()
            a_ab = str(game_copy.get('away_abbr', '')).upper()
            in_home = f"{sport}:{h_ab}" in saved_teams or (h_ab in saved_teams and h_ab not in COLLISION_ABBRS)
            in_away = f"{sport}:{a_ab}" in saved_teams or (a_ab in saved_teams and a_ab not in COLLISION_ABBRS)
            if not (in_home or in_away):
                should_show = False
        elif current_mode == 'live':
            if game_copy.get('state') not in ('in', 'half', 'crit'):
                should_show = False
        elif current_mode == 'sports':
            if g_type in NON_SCOREBOARD_TYPES:
                should_show = False
            else:
                status_lower = str(game_copy.get('status', '')).lower()
                if any(k in status_lower for k in HIDDEN_STATUS_KEYWORDS):
                    should_show = False
        elif current_mode == 'soccer_full':
            if not str(sport).startswith('soccer_'):
                should_show = False
        elif current_mode == 'golf':
            if g_type not in ('golf', 'masters') and str(sport).lower() not in ('golf', 'masters'):
                should_show = False
        elif current_mode == 'music':
            if g_type != 'music':
                should_show = False
        elif current_mode == 'stocks':
            if g_type != 'stock_ticker':
                should_show = False
        elif current_mode == 'weather':
            if g_type != 'weather':
                should_show = False
        elif current_mode == 'clock':
            if g_type != 'clock':
                should_show = False
        elif current_mode == 'masters':
            if g_type != 'masters':
                should_show = False
        elif current_mode == 'golf':
            if g_type not in ('golf', 'masters') and str(sport).lower() not in ('golf', 'masters'):
                should_show = False
        elif current_mode == 'flights':
            if sport != 'flight':
                should_show = False
        elif current_mode == 'flight_tracker':
            if g_type != 'flight_visitor':
                should_show = False
        elif current_mode in ('indycar', 'indycar_full'):
            if str(sport).lower() != 'indycar':
                should_show = False
        elif current_mode in ('f1', 'f1_full'):
            if str(sport).lower() != 'f1':
                should_show = False
        elif current_mode in ('nascar', 'nascar_full'):
            if str(sport).lower() != 'nascar':
                should_show = False

        game_copy['is_shown'] = should_show
        processed_games.append(game_copy)

    tz_name = str(response_settings.get('timezone_name', '')).strip()
    tz_offset = response_settings.get('utc_offset', state.get('utc_offset', -5))
    _materialize_blank_logo_urls(processed_games, request)
    _apply_timezone_to_game_times(processed_games, tz_name=tz_name, utc_offset=tz_offset)

    return jsonify({
        "status": "ok",
        "settings": response_settings,
        "games": processed_games,
        "is_pinned": bool(pinned_game),
        "pinned_game": pinned_game,
        "pinned_games": pinned_games
    })


@app.route('/api/pin_games', methods=['POST'])
def api_pin_games():
    try:
        payload = request.json or {}
        ticker_id = payload.get('ticker_id') or request.args.get('id')
        cid = request.headers.get('X-Client-ID')

        ticker_id = resolve_ticker_id(ticker_id, cid)

        if ticker_id and ticker_id in tickers:
            rec = tickers[ticker_id]
            if cid and cid not in rec.get('clients', []):
                print(f"⛔ Blocked unauthorized pin change from {cid}")
                return jsonify({"error": "Unauthorized: Device not paired"}), 403

        single_pin, pin_list = _normalize_single_pin(pinned_games=payload.get('game_ids', []))

        with data_lock:
            if ticker_id and ticker_id in tickers:
                tickers[ticker_id]['settings']['pinned_game'] = single_pin
                tickers[ticker_id]['settings']['pinned_games'] = pin_list

        if ticker_id and ticker_id in tickers:
            save_specific_ticker(ticker_id)

        request_refresh('pin_update')

        return jsonify({
            "status": "ok",
            "ticker_id": ticker_id,
            "pinned_game": single_pin,
            "pinned_games": pin_list
        })
    except Exception as e:
        print(f"Pin API Error: {e}")
        return jsonify({"error": "Failed to save pinned games"}), 500


@app.route('/api/teams')
def api_teams():
    with data_lock: return jsonify(state['all_teams_data'])


@app.route('/api/my_teams', methods=['GET'])
def check_my_teams():
    ticker_id = request.args.get('id')
    with data_lock:
        global_teams = state.get('my_teams', [])
        if not ticker_id:
            return jsonify({ "status": "ok", "scope": "Global", "teams": global_teams })

        if ticker_id in tickers:
            rec = tickers[ticker_id]
            specific_teams = rec.get('my_teams')
            using_fallback = specific_teams is None
            effective = global_teams if using_fallback else specific_teams
            return jsonify({ 
                "status": "ok", "scope": "Ticker Specific", 
                "using_global_fallback": using_fallback, 
                "teams": effective 
            })
        
        return jsonify({"error": "Ticker ID not found"}), 404


