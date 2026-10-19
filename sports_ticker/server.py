"""Run the V2 backend through one Hypercorn ASGI worker."""

from __future__ import annotations

import asyncio
import os
import faulthandler
import signal

from dotenv import load_dotenv
from hypercorn.asyncio import serve
from hypercorn.config import Config

from .asgi import create_asgi_application


def server_config() -> Config:
    """Read the existing deployment bind settings for one ASGI worker."""

    config = Config()
    host = os.environ.get("TICKER_BIND_HOST", "127.0.0.1")
    port = int(os.environ.get("TICKER_PORT", "5000"))
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    config.bind = [f"{host}:{port}"]
    config.workers = 1
    config.websocket_ping_interval = 20.0
    return config


def main() -> None:
    """Load deployment settings and let ASGI lifespan own refresh work."""

    faulthandler.enable()
    stack_signal = getattr(signal, "SIGUSR2", None)
    if stack_signal is not None:
        faulthandler.register(stack_signal, all_threads=True)
    load_dotenv()
    config = server_config()
    app = create_asgi_application()
    app.flask_app.config["STACK_DUMP_SIGNAL"] = "SIGUSR2" if stack_signal is not None else None
    asyncio.run(serve(app, config, mode="asgi"))


if __name__ == "__main__":
    main()
