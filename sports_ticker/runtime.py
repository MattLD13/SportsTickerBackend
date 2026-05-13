"""Runtime orchestration for the Sports Ticker backend."""

import os
import sys

from . import routes_runtime as _routes
from . import core as _core
from . import workers as _workers

app = _routes.app
state = _core.state
tickers = _core.tickers
data_lock = _core.data_lock
fetcher = _workers.fetcher
spotify_fetcher = _workers.spotify_fetcher
flight_tracker = _workers.flight_tracker


def create_runtime():
    """Return the module-backed runtime namespace for compatibility."""
    return sys.modules[__name__]


def create_app(runtime=None):
    """Return the configured Flask app without starting background workers."""
    app.config['runtime'] = runtime or create_runtime()
    return app


def start_background_workers():
    _workers.start_background_workers()


def run_server():
    start_background_workers()
    port = int(os.environ.get("PORT", 5000))
    print(f"Starting Flask on port {port}...")
    app.run(host='0.0.0.0', port=port)
