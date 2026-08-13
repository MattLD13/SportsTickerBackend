"""Run the complete v2 backend with one refresh runtime and Waitress."""

from __future__ import annotations

import atexit
import os

from dotenv import load_dotenv
from waitress import serve

from .production import create_production_application, start_runtime


def main() -> None:
    """Load deployment configuration, start refresh work, and serve v2 HTTP."""

    load_dotenv()
    app = create_production_application()
    stop = start_runtime(app)
    atexit.register(stop)
    serve(
        app,
        host=os.environ.get("TICKER_BIND_HOST", "127.0.0.1"),
        port=int(os.environ.get("TICKER_PORT", "5000")),
        threads=int(os.environ.get("TICKER_HTTP_THREADS", "8")),
    )


if __name__ == "__main__":
    main()
