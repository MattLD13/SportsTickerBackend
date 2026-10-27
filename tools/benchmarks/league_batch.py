"""Compare per-ticker RPC and shared league batches with controlled 150-game updates on Linux."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import hashlib
import multiprocessing
from pathlib import Path
import statistics
import sys
import tempfile
from threading import Thread
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend_ops.worker import ProviderWorker, serve
import backend_ops.worker_contract as wire
from sports_ticker.domain import DisplaySettings
from sports_ticker.providers.espn import EspnScoreboardProvider
from sports_ticker.providers.espn_fastcast import EspnFastcastSource

LEAGUE = 'ncf_fbs'
TOPIC = 'scoreboard-football-college-football-80'


class ControlledSource(EspnFastcastSource):
    def start(self):
        """Use controlled wire messages instead of an internet subscription."""


class FixtureClient:
    def __init__(self, games):
        self.calls = 0
        self.payload = {'events': [
            {'id': str(index), 'date': datetime.now(timezone.utc).isoformat(),
             'status': {'type': {'state': 'pre', 'shortDetail': 'Scheduled'}},
             'competitions': [{'competitors': [
                 {'homeAway': side, 'score': '0', 'team': {'id': f'{index}-{side}', 'abbreviation': f'{side}{index}',
                                                         'conferenceId': str(index % 12)}} for side in ('home', 'away')]}]}
            for index in range(games)]}

    def get_json(self, url, *, timeout):
        self.calls += 1
        if '/rankings' in url:
            return {'data': []}
        if '/schools-index' in url:
            return []
        if '/scoreboard' in url:
            return self.payload
        raise AssertionError('Unexpected controlled HTTP request')


def worker_main(directory, control, games):
    source = ControlledSource({LEAGUE: TOPIC})
    client = FixtureClient(games)
    provider = EspnScoreboardProvider({LEAGUE: 'https://controlled.invalid/football/college-football/scoreboard?groups=80'},
                                     client=client, fastcast=source)
    Thread(target=serve, args=(ProviderWorker('espn', provider), Path(directory) / 'espn.sock'), daemon=True).start()
    try:
        while True:
            command = control.recv()
            if command is None:
                return
            number, changed = command
            operations = []
            for index in range(changed):
                operations.extend([
                    {'op': 'replace', 'path': f'/events/{index}/competitions/0/competitors/0/score', 'value': str(number)},
                    {'op': 'replace', 'path': f'/events/{index}/status/type/state', 'value': 'in'},
                    {'op': 'replace', 'path': f'/events/{index}/status/type/shortDetail', 'value': 'Q1 12:00'},
                ])
            source._handle_wire_message(json.dumps({'op': 'P', 'tc': TOPIC, 'mid': number,
                                                     'pl': json.dumps({'ts': time.time() * 1000, 'pl': json.dumps(operations)})}))
            control.send({'number': number, 'http_calls': client.calls})
    finally:
        provider.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--games', type=int, default=150)
    parser.add_argument('--tickers', type=int, default=150)
    parser.add_argument('--pairs', type=int, default=6)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if sys.platform == 'win32' or not 1 <= args.games <= 1000 or not 1 <= args.tickers <= 256 or not 2 <= args.pairs <= 100:
        parser.error('Run on Linux with 1-1000 games, 1-256 tickers, and 2-100 paired trials.')
    context = multiprocessing.get_context('spawn')
    parent, child = context.Pipe()
    with tempfile.TemporaryDirectory(prefix='ticker-league-batch-') as directory:
        process = context.Process(target=worker_main, args=(directory, child, args.games))
        process.start()
        provider = wire.WorkerProvider('espn', Path(directory))
        selected = {f'ticker-{index}': DisplaySettings(active_sports={LEAGUE: True}, timezone='UTC',
                    sports_presentation='pinned', pinned_content_id=str(index % args.games), score_alerts=False)
                    for index in range(args.tickers)}
        records = []
        original_request = wire.request
        try:
            deadline = time.monotonic() + 15
            while not provider.socket.exists() and process.is_alive() and time.monotonic() < deadline:
                time.sleep(0.01)
            if not provider.socket.exists():
                raise RuntimeError('The controlled worker did not start.')
            provider.fetch_batch_for_tickers(selected)
            for pair in range(args.pairs):
                number = pair + 1
                changed = args.games if (pair // 2) % 2 == 0 else 1
                parent.send((number, changed))
                if not parent.poll(10):
                    raise RuntimeError('The controlled patch was not accepted.')
                accepted = parent.recv()
                order = ('individual', 'batch') if pair % 2 == 0 else ('batch', 'individual')
                for method in order:
                    responses = []

                    def counted(*values, **options):
                        response = original_request(*values, **options)
                        responses.append(response)
                        return response

                    wire.request = counted
                    cpu_started, started = time.process_time(), time.perf_counter()
                    if method == 'individual':
                        results = {key: provider.fetch_live_for_ticker(key, settings) for key, settings in selected.items()}
                    else:
                        results = provider.fetch_batch_for_tickers(selected, live_only=True)
                    elapsed = (time.perf_counter() - started) * 1000
                    cpu_ms = (time.process_time() - cpu_started) * 1000
                    wire.request = original_request
                    assert len(results) == args.tickers
                    assert all(len(result.content) == args.games for result in results.values())
                    assert all(next(item for item in result.content if item.id == '0').data['home_score'] == str(number)
                               for result in results.values())
                    byte_count = sum(len(json.dumps(value, separators=(',', ':')).encode()) + 1 for value in responses)
                    unique_items = len({id(item) for result in results.values() for item in result.content})
                    canonical = {key: [{name: wire.encode(value) for name, value in item.data.items() if name != '_source_timing'}
                                       for item in result.content] for key, result in results.items()}
                    digest = hashlib.sha256(json.dumps(canonical, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
                    records.append({'pair': pair, 'method': method, 'first': order[0] == method, 'changed_games': changed,
                                    'wall_ms': elapsed, 'core_cpu_ms': cpu_ms, 'responses': len(responses),
                                    'response_bytes': byte_count, 'decoded_game_objects': unique_items,
                                    'http_reads_before_pair': accepted['http_calls'], 'display_digest': digest})
                assert records[-1]['display_digest'] == records[-2]['display_digest']
        finally:
            wire.request = original_request
            if process.is_alive():
                parent.send(None)
                process.join(timeout=5)
            if process.is_alive():
                process.terminate()
                process.join(timeout=5)
            parent.close()
            child.close()
    summary = {}
    assert len({row['http_reads_before_pair'] for row in records}) == 1
    for method in ('individual', 'batch'):
        rows = [row for row in records if row['method'] == method]
        summary[method] = {key: statistics.median(row[key] for row in rows)
                           for key in ('wall_ms', 'core_cpu_ms', 'responses', 'response_bytes', 'decoded_game_objects')}
    result = {'context': 'Controlled live-shaped college-football patches, real Linux worker process and Unix socket. Paired order alternates. No internet or display measurement.',
              'games': args.games, 'tickers': args.tickers, 'pairs': args.pairs,
              'summary': summary, 'records': records}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps({key: value for key, value in result.items() if key != 'records'}, indent=2))


if __name__ == '__main__':
    main()
