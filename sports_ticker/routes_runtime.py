"""Flask app construction and route registration."""

import logging
import os
import uuid
from flask import Flask
from flask_cors import CORS

# Suppress per-request access lines (200/304 noise) — errors still surface.
logging.getLogger('werkzeug').setLevel(logging.ERROR)

app = Flask(__name__)
CORS(app)
app.secret_key = os.getenv('FLASK_SECRET_KEY') or uuid.uuid4().hex
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'

from .routes.config import api_config, update_settings, indycar_event_config
n24_event_config = indycar_event_config  # legacy alias
from .routes.metadata import api_blank_logo, api_spotify, get_league_options
from .routes.state import api_pin_games, api_state, api_teams, check_my_teams, get_ticker_data
from .routes.ticker import list_tickers, pair_ticker, pair_ticker_by_id, register_ticker, unpair
from .routes.flight import api_airport_lookup, debug_flight_tracking, get_airlines, get_airports, get_flight_status
from .routes.debug import api_debug, api_hardware, api_timezone_debug, get_logs
from .routes.preview import preview_strip
from .routes.racing import racing as _racing_bp
from .dashboard import dashboard as _dashboard_bp
app.register_blueprint(_dashboard_bp)
app.register_blueprint(_racing_bp)

__all__ = [
    'app',
    'api_config', 'update_settings', 'indycar_event_config', 'n24_event_config',
    'api_blank_logo', 'api_spotify', 'get_league_options',
    'api_pin_games', 'api_state', 'api_teams', 'check_my_teams', 'get_ticker_data',
    'list_tickers', 'pair_ticker', 'pair_ticker_by_id', 'register_ticker', 'unpair',
    'api_airport_lookup', 'debug_flight_tracking', 'get_airlines', 'get_airports', 'get_flight_status',
    'api_debug', 'api_hardware', 'api_timezone_debug', 'get_logs',
    'preview_strip',
]
