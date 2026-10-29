"""Start one feature worker: python -m ticker3.sdk.run --feature ticker3.features.weather --socket PATH --release ID."""
from __future__ import annotations

import argparse
import asyncio
import importlib
import signal

from .runner import Runner


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--feature", required=True, help="Module that defines create().")
    parser.add_argument("--socket", required=True)
    parser.add_argument("--release", required=True)
    parser.add_argument("--orphan-seconds", type=float, default=600)
    parser.add_argument("--health-seconds", type=float, default=5)
    parser.add_argument("--connect-seconds", type=float, default=1)
    args = parser.parse_args(argv)
    feature = importlib.import_module(args.feature).create()
    runner = Runner(feature, args.socket, args.release, orphan_seconds=args.orphan_seconds,
                    health_seconds=args.health_seconds, connect_seconds=args.connect_seconds)

    async def run() -> int:
        loop = asyncio.get_running_loop()
        task = asyncio.current_task()
        for number in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(number, task.cancel)
        try:
            return await runner.run()
        except asyncio.CancelledError:
            return 0

    return asyncio.run(run())


if __name__ == "__main__":
    raise SystemExit(main())
