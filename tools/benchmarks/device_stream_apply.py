"""Measure real captured stream messages without network or display writes."""

from __future__ import annotations

import argparse
from collections.abc import Mapping
import cProfile
import hashlib
import json
from pathlib import Path
import statistics
import os
import sys
import time


def _plain(value):
    if isinstance(value, Mapping):
        return {key: _plain(child) for key, child in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(child) for child in value]
    return value


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--messages", type=Path, required=True)
    parser.add_argument("--repository", type=Path, default=Path.cwd())
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--profile", type=Path)
    args = parser.parse_args()
    if args.repeats < 1:
        parser.error("--repeats must be positive")
    sys.path[:0] = [os.path.join(str(args.repository.resolve()), name) for name in ("shared", "server", "six", "")]
    from ticker.six.protocol import DeviceStreamState, StreamMessage

    raw_messages = json.loads(args.messages.read_text(encoding="utf-8-sig"))
    encoded = [json.dumps(message, separators=(",", ":")) for message in raw_messages]
    snapshot_times, delta_times, outputs = [], [], []

    def replay(*, record: bool) -> None:
        state = DeviceStreamState()
        for raw in encoded:
            started = time.perf_counter()
            message = StreamMessage.from_payload(json.loads(raw))
            response = state.apply(message)
            elapsed_ms = (time.perf_counter() - started) * 1000.0
            if not record:
                continue
            if message.kind == "snapshot":
                snapshot_times.append(elapsed_ms)
            elif message.kind == "delta":
                delta_times.append(elapsed_ms)
            if response is not None:
                outputs.append({
                    "cursor": state.cursor,
                    "key": response.payload_key,
                    "raw": response.to_payload(),
                    "content": [
                        (item.id, item.family, item.kind, item.is_shown, _plain(item.data))
                        for item in response.content
                    ],
                    "alerts": [(item.id, item.kind, _plain(item.data)) for item in response.alerts],
                    "news": [(item.id, item.kind, _plain(item.data)) for item in response.news],
                })

    for _ in range(args.repeats):
        replay(record=True)
    if args.profile:
        profiler = cProfile.Profile()
        profiler.runcall(replay, record=False)
        profiler.dump_stats(str(args.profile))

    def summary(samples):
        values = sorted(samples)
        return {
            "count": len(values),
            "p50_ms": round(statistics.median(values), 3),
            "p95_ms": round(values[min(len(values) - 1, int(len(values) * 0.95))], 3),
            "max_ms": round(max(values), 3),
        } if values else {}

    result = {
        "messages": len(encoded),
        "repeats": args.repeats,
        "input_bytes": sum(len(raw.encode("utf-8")) for raw in encoded),
        "snapshots": summary(snapshot_times),
        "deltas": summary(delta_times),
        "output_sha256": hashlib.sha256(json.dumps(outputs, sort_keys=True).encode()).hexdigest(),
    }
    args.output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
