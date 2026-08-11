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

    # Werkzeug's dev server dedicates one OS thread per connection and sets no
    # socket timeout, so every client that disappears without closing (Pi power
    # cut, Wi-Fi drop, port scanner) pins a thread and an fd for the lifetime of
    # the process. Waitress uses a fixed worker pool and reaps idle channels.
    try:
        from waitress import serve as _waitress_serve
    except ImportError:
        _waitress_serve = None

    if _waitress_serve is not None:
        print(f"Starting waitress on port {port}...")
        waitress_threads = int(os.environ.get("WAITRESS_THREADS", 12))
        _waitress_serve(
            app,
            host='0.0.0.0',
            port=port,
            threads=waitress_threads,
            channel_timeout=120,     # drop connections idle longer than this
            connection_limit=200,
            ident='sports-ticker',
        )
        return

    # Fallback: dev server, but with a socket timeout so an abandoned
    # keep-alive connection can't hold its thread forever.
    from werkzeug.serving import WSGIRequestHandler
    WSGIRequestHandler.timeout = 60
    print(f"Starting Flask dev server on port {port} (waitress not installed)...")
    app.run(host='0.0.0.0', port=port, threaded=True)
