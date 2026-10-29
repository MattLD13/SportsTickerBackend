"""Start one provider worker: python -m ticker3.worker --provider espn --socket PATH --release ID."""
from __future__ import annotations

import argparse
import asyncio
import faulthandler
import importlib
import os
import signal
from pathlib import Path

from .runner import ProviderWorker


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provider", required=True)
    parser.add_argument("--socket", required=True)
    parser.add_argument("--release", required=True)
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--database", type=Path, help="The fleet database. Music reads its Spotify tokens there.")
    parser.add_argument("--factory", default="sports_ticker.providers.factory:create_provider",
                        help="module:callable that makes the provider from its name.")
    parser.add_argument("--interval", type=float)
    parser.add_argument("--health-seconds", type=float, default=5)
    parser.add_argument("--connect-seconds", type=float, default=1)
    parser.add_argument("--orphan-seconds", type=float, default=600)
    args = parser.parse_args(argv)
    if args.env_file is not None:
        from dotenv import load_dotenv
        load_dotenv(args.env_file)
    faulthandler.enable()
    if hasattr(signal, "SIGUSR2"):
        faulthandler.register(signal.SIGUSR2, all_threads=True)
    database = (args.database or Path(os.environ.get("TICKER_DATABASE_PATH", "ticker_data/ticker-v2.sqlite3"))).resolve()
    module, _, attribute = args.factory.partition(":")
    provider = getattr(importlib.import_module(module), attribute)(args.provider, database_path=database)
    from backend_ops.incidents import IncidentStore
    worker = ProviderWorker(args.provider, provider, args.socket, args.release, interval=args.interval,
                            incidents=IncidentStore(database.parent / "backend-incidents"),
                            health_seconds=args.health_seconds, connect_seconds=args.connect_seconds,
                            orphan_seconds=args.orphan_seconds)

    async def run() -> int:
        loop = asyncio.get_running_loop()
        task = asyncio.current_task()
        for number in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(number, task.cancel)
        try:
            return await worker.run()
        except asyncio.CancelledError:
            return 0

    return asyncio.run(run())


if __name__ == "__main__":
    raise SystemExit(main())
