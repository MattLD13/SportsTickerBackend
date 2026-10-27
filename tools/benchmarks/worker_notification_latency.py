"""Measure controlled Fastcast patches through real worker IPC and snapshot commits on Linux."""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
import multiprocessing
from pathlib import Path
import statistics
import sys
import tempfile
from threading import Condition, Thread
import time
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend_ops.worker import ProviderWorker, serve
from backend_ops.worker_contract import WorkerProvider
from sports_ticker.application import BackendRuntime, RefreshScheduler, RefreshService
from sports_ticker.application.state_store import SnapshotStore
from sports_ticker.domain import DisplaySettings
from sports_ticker.providers.espn import EspnScoreboardProvider
from sports_ticker.providers.espn_fastcast import EspnFastcastSource


class ControlledSource(EspnFastcastSource):
    def start(self):
        """Use explicit wire messages instead of an internet connection."""


class FixtureClient:
    def get_json(self, url, *, timeout):
        today = datetime.now(timezone.utc).isoformat()
        return {"events": [{"id": "controlled", "date": today,
                            "status": {"type": {"state": "pre", "shortDetail": "Scheduled"}},
                            "competitions": [{"competitors": [
                                {"homeAway": "home", "score": "0", "team": {"abbreviation": "BOS"}},
                                {"homeAway": "away", "score": "0", "team": {"abbreviation": "NYK"}},
                            ]}]}]}


def worker_main(directory, control):
    source = ControlledSource({"nba": "scoreboard-basketball-nba"})
    provider = EspnScoreboardProvider({"nba": "https://controlled.invalid/basketball/nba/scoreboard"},
                                     client=FixtureClient(), fastcast=source)
    thread = Thread(target=serve, args=(ProviderWorker("espn", provider), Path(directory) / "espn.sock"), daemon=True)
    thread.start()
    try:
        while True:
            number = control.recv()
            if number is None:
                return
            source._handle_wire_message(json.dumps({"op": "P", "tc": "scoreboard-basketball-nba", "mid": number,
                "pl": json.dumps({"ts": time.time() * 1000, "pl": json.dumps([
                    {"op": "replace", "path": "/events/0/competitions/0/competitors/0/score", "value": str(number)}])})}))
            control.send(number)
    finally:
        provider.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--samples', type=int, default=30)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if sys.platform == 'win32' or not 1 <= args.samples <= 1000:
        parser.error('Run on Linux with 1 to 1000 samples.')
    with tempfile.TemporaryDirectory(prefix='ticker-worker-latency-') as directory:
        context = multiprocessing.get_context('spawn')
        parent, child = context.Pipe()
        process = context.Process(target=worker_main, args=(directory, child))
        process.start()
        provider = WorkerProvider('espn', Path(directory))
        store = SnapshotStore()
        condition = Condition()
        rows = []

        def committed(identifier):
            with condition:
                condition.notify_all()

        store.add_change_listener(committed)
        scheduler = RefreshScheduler(RefreshService([], store), executor=ThreadPoolExecutor(max_workers=2))
        settings = DisplaySettings(active_sports={'nba': True}, timezone='UTC')
        scheduler.register_provider('espn', 60, provider.fetch_for_ticker, refresh_changed=provider.fetch_live_for_ticker,
                                    refresh_batch=provider.fetch_batch_for_tickers)
        scheduler.register_ticker('controlled', lambda _: settings)
        runtime = BackendRuntime(scheduler, SimpleNamespace(remove_expired=lambda: None), 0.2)
        runtime.add_change_source('espn', provider.wait_for_changes)
        runtime_thread = Thread(target=runtime.run, daemon=True)
        try:
            deadline = time.monotonic() + 10
            while not provider.socket.exists() and process.is_alive() and time.monotonic() < deadline:
                time.sleep(0.01)
            if not provider.socket.exists():
                raise RuntimeError('The controlled worker did not start.')
            runtime_thread.start()

            def matches(number):
                snapshot = store.get('controlled')
                return snapshot is not None and snapshot.content and snapshot.content[0].data['home_score'] == str(number)

            with condition:
                if not condition.wait_for(lambda: matches(0), timeout=10):
                    raise RuntimeError('The initial worker result did not reach the snapshot.')
            for number in range(1, args.samples + 1):
                parent.send(number)
                if not parent.poll(5) or parent.recv() != number:
                    raise RuntimeError('The controlled wire input was not accepted.')
                with condition:
                    if not condition.wait_for(lambda: matches(number), timeout=5):
                        raise RuntimeError('The source notification did not publish its matching score.')
                snapshot = store.get('controlled')
                timing = snapshot.content[0].data['_source_timing']
                rows.append({'score': number, 'source': timing['source'],
                             'input_to_snapshot_ms': snapshot.committed_at_ms - timing['ingested_at_ms'],
                             'input_to_core_ms': timing['core_received_at_ms'] - timing['ingested_at_ms']})
                time.sleep(0.05)
        finally:
            runtime.stop()
            if runtime_thread.ident is not None:
                runtime_thread.join(timeout=8)
            scheduler.close()
            if process.is_alive():
                parent.send(None)
                process.join(timeout=3)
            if process.is_alive():
                process.terminate()
                process.join(timeout=3)
            parent.close()
            child.close()
        values = sorted(row['input_to_snapshot_ms'] for row in rows)
        result = {'context': 'Controlled wire patches, real worker process and Unix socket, production scheduler and snapshot store. No internet or physical display.',
                  'samples': len(rows), 'p50_ms': statistics.median(values),
                  'p95_ms': values[min(len(values)-1, int(len(values)*0.95))] if len(values) >= 20 else None,
                  'min_ms': min(values), 'max_ms': max(values), 'records': rows}
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2), encoding='utf-8')
        print(json.dumps({key: value for key, value in result.items() if key != 'records'}))


if __name__ == '__main__':
    main()
