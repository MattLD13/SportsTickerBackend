"""Compare stream publication and profile identical captured projections with bounded client fanout."""

from __future__ import annotations

import argparse
import asyncio
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
import statistics
import sys
import time


def projections(messages):
    result = []
    current = None
    for message in messages:
        if message['type'] == 'snapshot':
            current = deepcopy(message['payload'])
        elif message['type'] == 'delta':
            current.update(deepcopy(message['changes']))
            for key in message.get('removed', []):
                current.pop(key, None)
        else:
            continue
        result.append(deepcopy(current))
    return result


def measure(values):
    values = sorted(values)
    return {'count': len(values), 'p50_ms': statistics.median(values),
            'p95_ms': values[min(len(values) - 1, int(len(values) * 0.95))]}


async def replay(args, module, payloads):
    module._server_time = lambda: '2026-10-25T00:00:00+00:00'
    hub = module.DeviceStreamHub()
    hub.stream_id = 'benchmark-stream'

    def prepare(payload):
        return payload if args.baseline_source else module.StreamProjection.from_payload(payload)

    initial = prepare(payloads[0])
    clients = [hub.subscribe('benchmark', initial, resume_stream_id=None, after_seq=None)[0] for _ in range(args.clients)]
    samples = {'preparation': [], 'event_loop': [], 'combined': []}
    digest = hashlib.sha256()
    steps = max(1, int(args.seconds * args.rate)) if args.seconds else args.repeats * len(payloads)
    deadline = time.monotonic()
    started_run = time.perf_counter()
    for index in range(steps):
        if args.seconds:
            await asyncio.sleep(max(0.0, deadline - time.monotonic()))
            deadline += 1 / args.rate
        raw = payloads[(index + 1) % len(payloads)]
        started = time.perf_counter()
        projection = await asyncio.to_thread(prepare, raw)
        prepared = time.perf_counter()
        hub.publish('benchmark', projection)
        output = []
        for client in clients:
            while not client.queue.empty():
                message = client.queue.get_nowait()
                output.append(module.encode_message(message) if args.baseline_source else message.encoded)
        finished = time.perf_counter()
        if len(samples['combined']) < 10000:
            samples['preparation'].append((prepared - started) * 1000)
            samples['event_loop'].append((finished - prepared) * 1000)
            samples['combined'].append((finished - started) * 1000)
        if not args.seconds:
            for encoded in output:
                value = json.loads(encoded)
                digest.update(json.dumps(value, separators=(',', ':'), sort_keys=True, ensure_ascii=False).encode())
    report = {'clients': args.clients, 'steps': steps, 'elapsed_seconds': time.perf_counter() - started_run,
              'timings': {key: measure(values) for key, values in samples.items()},
              'published_deltas': hub.published_deltas, 'queue_resets': hub.queue_resets,
              'output_sha256': digest.hexdigest() if not args.seconds else None}
    for client in clients:
        hub.unsubscribe('benchmark', client)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repository', type=Path, default=Path.cwd())
    parser.add_argument('--messages', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--baseline-source', type=Path, help='Load the captured former hub implementation for an explicit comparison.')
    parser.add_argument('--repeats', type=int, default=30)
    parser.add_argument('--clients', type=int, default=3)
    parser.add_argument('--seconds', type=float, default=0, help='Use a paced workload for sampling. This mode omits digest work.')
    parser.add_argument('--rate', type=float, default=20)
    args = parser.parse_args()
    if args.repeats < 1 or args.clients < 1 or args.seconds < 0 or args.rate <= 0:
        parser.error('Use positive counts and rate, with nonnegative seconds.')
    sys.path.insert(0, str(args.repository.resolve()))
    if args.baseline_source:
        spec = importlib.util.spec_from_file_location('_stream_baseline', args.baseline_source)
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
    else:
        from sports_ticker import device_stream as module
    payloads = projections(json.loads(args.messages.read_text(encoding='utf-8-sig')))
    report = asyncio.run(replay(args, module, payloads))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
