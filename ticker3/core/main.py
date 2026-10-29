"""Run the Ticker 3 core: python -m ticker3.core.main

| Variable | Default | Meaning |
|---|---|---|
| `TICKER3_DATA` | `ticker_data/ticker3` | Folder for the database, the supervisor state, and the logs |
| `TICKER3_SOCKET` | `<TICKER3_DATA>/core.sock` | Worker socket. A Unix socket path must be at most 100 bytes. |
| `TICKER3_BIND` | `127.0.0.1:5300` | Address of the HTTP API and the device stream |
| `TICKER3_FEATURES` | `weather,sports,racing` | Features that run in worker processes |
| `TICKER3_RELEASES` | none | Folder with one folder for each release. Without it, the release `dev` is this checkout. |
| `TICKER3_RELEASE` | `dev` | The first active release of each feature |
| `TICKER3_ADMIN_TOKEN` | none | Token for ticker creation and deploys. Without it, those routes are closed. |
"""
from __future__ import annotations

import asyncio
import os
import signal
from pathlib import Path

from ticker3.contract import ContractError

from .app import CoreApp
from .builtin import BUILTINS
from .hub import Hub
from .store import Store
from .supervisor import Supervisor, WorkerSpec

CHECKOUT = Path(__file__).resolve().parents[2]


def release_path(name: str) -> Path:
    releases = os.environ.get("TICKER3_RELEASES")
    if name == "dev" and not releases:
        return CHECKOUT
    if not releases or "/" in name or name.startswith("."):
        raise ValueError(f"release {name!r} has no folder")
    return Path(releases) / name


async def fetch_image(url: str) -> bytes | None:
    import urllib3

    def read() -> bytes | None:
        try:
            response = _pool().request("GET", url, timeout=urllib3.Timeout(connect=5, read=10), preload_content=True)
        except (urllib3.exceptions.HTTPError, OSError):
            return None
        return response.data if response.status == 200 and len(response.data) < 2_000_000 else None

    return await asyncio.to_thread(read)


_POOL = None


def _pool():
    global _POOL
    if _POOL is None:
        import ssl

        import certifi
        import urllib3
        context = ssl.create_default_context(cafile=os.environ.get("TICKER3_CA_BUNDLE") or certifi.where())
        _POOL = urllib3.PoolManager(num_pools=8, maxsize=4, ssl_context=context)
    return _POOL


def build(data: Path) -> tuple[CoreApp, Supervisor]:
    store = Store(data / "ticker3.sqlite3")
    hub = Hub()
    for builtin in BUILTINS.values():
        hub.register(builtin.manifest, builtin=builtin)
    for manifest in store.manifests():
        try:
            hub.register(manifest)
        except ContractError:
            continue
    app = CoreApp(hub, store, admin_token=os.environ.get("TICKER3_ADMIN_TOKEN"), fetch_image=fetch_image)
    for ticker in store.tickers():
        app._load(ticker.id)
    names = [name.strip() for name in os.environ.get("TICKER3_FEATURES", "weather,sports,racing").split(",") if name.strip()]
    socket_path = Path(os.environ.get("TICKER3_SOCKET") or data / "core.sock")
    supervisor = Supervisor(hub, socket_path, data / "supervisor.json",
                            [WorkerSpec(name, f"ticker3.features.{name}") for name in names], release_path,
                            initial_release=os.environ.get("TICKER3_RELEASE", "dev"), log_directory=data / "logs")
    app.supervisor = supervisor
    return app, supervisor


async def serve() -> None:
    from hypercorn.asyncio import serve as hypercorn_serve
    from hypercorn.config import Config

    data = Path(os.environ.get("TICKER3_DATA", "ticker_data/ticker3"))
    app, supervisor = build(data)
    config = Config()
    config.bind = [os.environ.get("TICKER3_BIND", "127.0.0.1:5300")]
    config.accesslog = None
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for number in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(number, stop.set)
    await supervisor.start()

    async def tick() -> None:
        while True:
            app.hub.tick()
            await asyncio.sleep(1)

    ticker = asyncio.create_task(tick())
    try:
        await hypercorn_serve(app, config, shutdown_trigger=stop.wait)
    finally:
        ticker.cancel()
        # Workers keep running, so a core restart costs no upstream reads.
        await supervisor.stop()
        app.store.close()


if __name__ == "__main__":
    asyncio.run(serve())
