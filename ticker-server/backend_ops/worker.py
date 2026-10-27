"""Run one fetcher behind a bounded, local JSON contract."""
from __future__ import annotations

import argparse
import faulthandler
import json
import os
from pathlib import Path
import signal
import socketserver
import threading
import time
import traceback

from .incidents import IncidentStore, atomic_json, redact, release_id
from .worker_contract import MAX_BATCH, MAX_MESSAGE, PROVIDERS, contract_id, encode, encode_batch


class ProviderWorker:
    def __init__(self, name, provider, *, incidents=None, replay_directory=None, clock=time.monotonic):
        self.name, self.provider, self.clock = name, provider, clock
        self.incidents, self.replays = incidents, replay_directory
        self.lock = threading.Lock()
        self.started = None
        self.completed = None
        self.failures = 0
        self.error_type = None
        self.replay_id = None
        self.protocol = contract_id()

    def handle(self, message):
        envelope = {"protocol": 1, "contract": self.protocol, "component": self.name, "release": release_id()}
        if message.get("protocol") != 1 or message.get("contract") != self.protocol:
            return {**envelope, "error": "worker contract mismatch"}
        if message.get("op") == "health":
            return {**envelope, "ready": True, "busy_seconds": max(0, self.clock() - self.started) if self.started is not None else 0,
                    "failures": self.failures, "error_type": self.error_type, "replay_id": self.replay_id}
        if message.get("op") == "changes" and self.name == "espn":
            after, timeout = message.get("after"), message.get("timeout")
            if (not isinstance(after, dict) or len(after) > 64
                    or any(not isinstance(key, str) or not isinstance(value, str) for key, value in after.items())
                    or isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not 0 <= timeout <= 5):
                return {**envelope, "error": "invalid source change request"}
            return {**envelope, "versions": self.provider.wait_for_changes(after, timeout)}
        operation = message.get("op")
        if operation == "fetch_batch":
            tickers = message.get("tickers")
            if (self.name != "espn" or not isinstance(tickers, dict) or not 1 <= len(tickers) <= MAX_BATCH
                    or any(not isinstance(key, str) or not key or len(key) > 200 or not isinstance(value, dict)
                           for key, value in tickers.items()) or type(message.get("live_only")) is not bool):
                return {**envelope, "error": "invalid worker batch request"}
        if operation not in {"fetch", "fetch_live", "fetch_batch"} or (operation == "fetch_live" and self.name != "espn") or not self.lock.acquire(blocking=False):
            return {**envelope, "error": "worker is busy or operation is invalid"}
        from sports_ticker.domain import DisplaySettings
        from sports_ticker.providers.contracts import ProviderHealth, ProviderResult
        self.started = self.clock()
        try:
            if operation == "fetch_batch":
                from sports_ticker.providers.normalization import normalize_provider_result
                settings = {key: DisplaySettings(**value) for key, value in tickers.items()}
                values = self.provider.fetch_batch_for_tickers(settings, live_only=message["live_only"])
                if set(values) != set(settings):
                    raise ValueError("provider batch returned the wrong ticker identifiers")
                results = {}
                for key, value in values.items():
                    if isinstance(value, Exception):
                        value = ProviderResult(health=ProviderHealth(healthy=False, provider=self.name, error=str(value),
                            diagnostic={"exception_type": type(value).__name__, "traceback": "".join(traceback.format_exception(value))}))
                    result = normalize_provider_result(value, settings[key], provider=self.name)
                    results[key] = result
                failures = [result for result in results.values() if not result.health.healthy]
                self._record_result(failures[0] if failures else next(iter(results.values())), message)
                return {**envelope, "batch": encode_batch(results)}
            try:
                from sports_ticker.providers.normalization import normalize_provider_result
                settings = DisplaySettings(**message["settings"])
                fetch = self.provider.fetch_live_for_ticker if operation == "fetch_live" else getattr(self.provider, "fetch_for_ticker", None)
                value = fetch(message["ticker_id"], settings) if callable(fetch) else self.provider.fetch(settings)
                result = normalize_provider_result(value, settings, provider=self.name)
            except Exception as error:
                result = ProviderResult(health=ProviderHealth(healthy=False, provider=self.name, error=str(error),
                    diagnostic={"exception_type": type(error).__name__, "traceback": "".join(traceback.format_exception(error))}))
            self._record_result(result, message)
            return {**envelope, "result": encode(result)}
        finally:
            self.started = None
            self.completed = self.clock()
            self.lock.release()

    def _record_result(self, result, message):
        if result.health.healthy:
            self.failures = 0
            self.error_type = None
        else:
            self.failures += 1
            self.error_type = (result.health.diagnostic or {}).get("exception_type")
            if self.replays is not None:
                self.replay_id = self.name + "-last-failure"
                atomic_json(Path(self.replays) / (self.replay_id + ".json"), message)
            if self.incidents is not None:
                self.incidents.record("fetcher_failure", component=self.name, error=result.health.error,
                                      context={"source_failure": dict(result.health.diagnostic or {}), "replay_id": self.replay_id})



def serve(worker, socket_path):
    class Handler(socketserver.StreamRequestHandler):
        def handle(self):
            body = self.rfile.readline(MAX_MESSAGE + 1)
            if len(body) > MAX_MESSAGE or not body.endswith(b"\n"):
                return
            try:
                result = worker.handle(json.loads(body))
                payload = json.dumps(result, separators=(",", ":")).encode() + b"\n"
                if len(payload) <= MAX_MESSAGE:
                    self.wfile.write(payload)
                else:
                    self.wfile.write(json.dumps({"protocol": 1, "contract": worker.protocol,
                                                 "error": "worker response exceeds the contract limit"}).encode() + b"\n")
            except (ValueError, KeyError, OSError) as error:
                self.wfile.write(json.dumps({"protocol": 1, "contract": worker.protocol, "error": redact(str(error))}).encode() + b"\n")
    class Server(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
        daemon_threads = True
    socket_path.parent.mkdir(parents=True, exist_ok=True)
    socket_path.unlink(missing_ok=True)
    with Server(str(socket_path), Handler) as server:
        os.chmod(socket_path, 0o600)
        server.serve_forever(poll_interval=0.25)


def main():
    from dotenv import load_dotenv
    from sports_ticker.providers.factory import create_provider
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--component", choices=PROVIDERS, required=True)
    parser.add_argument("--socket", type=Path, required=True)
    parser.add_argument("--env-file", type=Path, default=Path("/home/ubuntu/.env"))
    args = parser.parse_args()
    load_dotenv(args.env_file)
    faulthandler.enable()
    if hasattr(signal, "SIGUSR2"):
        faulthandler.register(signal.SIGUSR2, all_threads=True)
    database = Path(os.environ.get("TICKER_DATABASE_PATH", "/home/ubuntu/ticker_data/ticker-v2.sqlite3"))
    provider = create_provider(args.component, database_path=database)
    worker = ProviderWorker(args.component, provider, incidents=IncidentStore(database.parent / "backend-incidents"),
                            replay_directory=database.parent / "backend-control/replays")
    try:
        serve(worker, args.socket)
    finally:
        close = getattr(provider, "close", None)
        if callable(close):
            close()
        args.socket.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
