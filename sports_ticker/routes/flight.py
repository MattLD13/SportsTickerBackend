from .. import core as _core
from .. import workers as _workers
from ..routes_runtime import app
globals().update({k: v for k, v in vars(_core).items() if not k.startswith('__')})
globals().update({k: v for k, v in vars(_workers).items() if not k.startswith('__')})

@app.route('/api/airport/lookup', methods=['GET'])
def api_airport_lookup():
    """
    Lookup airport information by IATA or ICAO code.
    Query params: code=ABE or code=KABE
    Returns: {iata, icao, name}
    """
    try:
        code = request.args.get('code', '').strip()
        if not code:
            return jsonify({"error": "Please provide an airport code"}), 400
        
        airport_info = lookup_and_auto_fill_airport(code)
        
        if airport_info['iata']:
            return jsonify({
                "status": "found",
                "iata": airport_info['iata'],
                "icao": airport_info['icao'],
                "name": airport_info['name']
            })
        else:
            return jsonify({
                "status": "not_found",
                "message": f"Airport code '{code}' not found"
            }), 404
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/flight/debug', methods=['GET'])
def debug_flight_tracking():
    """Diagnostic endpoint to see what's happening with flight tracking"""
    if not flight_tracker:
        return jsonify({'error': 'Flight tracking not available'})
    
    # Force an immediate fetch
    try:
        flight_tracker.fetch_visitor_tracking()
    except Exception as e:
        return jsonify({'error': f'Fetch failed: {str(e)}'})
    
    # Get the current state
    with flight_tracker.lock:
        visitor_data = flight_tracker.visitor_flight.copy() if flight_tracker.visitor_flight else None
    
    return jsonify({
        'config': {
            'track_flight_id': flight_tracker.track_flight_id,
            'track_guest_name': flight_tracker.track_guest_name,
            'fr_api_available': flight_tracker.fr_api is not None
        },
        'visitor_flight': visitor_data,
        'last_fetch': {
            'visitor': flight_tracker.last_visitor_fetch,
            'time_since': time.time() - flight_tracker.last_visitor_fetch
        }
    })


@app.route('/api/airports', methods=['GET'])
def get_airports():
    airports = [
        {'icao': 'KEWR', 'iata': 'EWR', 'name': 'Newark', 'city': 'New York'},
        {'icao': 'KJFK', 'iata': 'JFK', 'name': 'JFK', 'city': 'New York'},
        {'icao': 'KLGA', 'iata': 'LGA', 'name': 'LaGuardia', 'city': 'New York'},
        {'icao': 'KORD', 'iata': 'ORD', 'name': "O'Hare", 'city': 'Chicago'},
        {'icao': 'KLAX', 'iata': 'LAX', 'name': 'LAX', 'city': 'Los Angeles'},
        {'icao': 'KSFO', 'iata': 'SFO', 'name': 'San Francisco', 'city': 'San Francisco'},
        {'icao': 'KATL', 'iata': 'ATL', 'name': 'Hartsfield', 'city': 'Atlanta'},
        {'icao': 'KDEN', 'iata': 'DEN', 'name': 'Denver Intl', 'city': 'Denver'},
        {'icao': 'KDFW', 'iata': 'DFW', 'name': 'Dallas/Fort Worth', 'city': 'Dallas'},
        {'icao': 'KBOS', 'iata': 'BOS', 'name': 'Logan', 'city': 'Boston'},
        {'icao': 'KSEA', 'iata': 'SEA', 'name': 'SeaTac', 'city': 'Seattle'},
        {'icao': 'KMIA', 'iata': 'MIA', 'name': 'Miami Intl', 'city': 'Miami'},
    ]
    return jsonify(airports)


@app.route('/api/airlines', methods=['GET'])
def get_airlines():
    airlines = [
        {'code': '', 'name': 'All Airlines'},
        {'code': 'UA', 'name': 'United Airlines'},
        {'code': 'DL', 'name': 'Delta'},
        {'code': 'AA', 'name': 'American'},
        {'code': 'WN', 'name': 'Southwest'},
        {'code': 'B6', 'name': 'JetBlue'},
        {'code': 'AS', 'name': 'Alaska'},
    ]
    return jsonify(airlines)


@app.route('/api/flight/status', methods=['GET'])
def get_flight_status():
    if not flight_tracker:
        return jsonify({'available': False})
    # Optional: force a fresh fetch for debugging
    force = request.args.get('force') == '1'
    if force:
        try:
            flight_tracker.fetch_visitor_tracking()
        except Exception as e:
            print(f"[DEBUG] force fetch failed: {e}")
    with data_lock:
        return jsonify({
            'available': True,
            'visitor_enabled': state['active_sports'].get('flight_tracker', False),
            'airport_enabled': state['active_sports'].get('flight_airport', False),
            'tracking': {
                'flight_id': state.get('track_flight_id', ''),
                'guest_name': state.get('track_guest_name', ''),
                'airport': {
                    'icao': state.get('airport_code_icao', ''),
                    'iata': state.get('airport_code_iata', ''),
                    'name': state.get('airport_name', ''),
                    'airline': ''  # Always empty - support all airlines
                }
            },
            'visitor': flight_tracker.get_visitor_object() if force else None
        })


