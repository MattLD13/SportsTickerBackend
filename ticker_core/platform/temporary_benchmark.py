"""Collect one synthetic stream baseline for the temporary device experiment."""

from __future__ import annotations

import copy
import hashlib
import json
import platform
import statistics
import time
from pathlib import Path

from ticker_core.protocol import DeviceStreamState, StreamMessage


def run(repository: Path) -> dict[str, object]:
    """Measure synthetic stream updates and return bounded, non-customer data."""
    payload = json.loads((repository / "tests/fixtures/display/v2_render_snapshot.json").read_text(encoding="utf-8"))
    common = {"protocol_version": 1, "stream_id": "benchmark", "server_time": "2026-10-14T00:00:00+00:00"}
    messages = [dict(common, type="snapshot", seq=1, base_seq=1, payload=payload)]
    for seq in range(2, 102):
        content = copy.deepcopy(payload["content"])
        content["sports"][0]["data"]["away_score"] = str(seq)
        messages.append(dict(common, type="delta", seq=seq, base_seq=seq - 1, changes={"content": content}, removed=[]))
    encoded = [json.dumps(message, separators=(",", ":")) for message in messages]
    durations = []
    digest = hashlib.sha256()
    for _ in range(5):
        state = DeviceStreamState()
        for raw in encoded:
            start = time.perf_counter()
            message = StreamMessage.from_payload(json.loads(raw))
            response = state.apply(message)
            elapsed = (time.perf_counter() - start) * 1000
            if message.kind == "delta":
                durations.append(elapsed)
            if response is not None:
                digest.update(response.payload_key.encode())
    values = sorted(durations)
    return {"experiment": "synthetic-stream-20261108", "machine": platform.machine(),
            "python": platform.python_version(), "deltas": len(values),
            "delta_p50_ms": round(statistics.median(values), 3),
            "delta_p95_ms": round(values[int(len(values) * .95)], 3),
            "delta_max_ms": round(max(values), 3), "digest": digest.hexdigest()}


_result: dict[str, object] | None = None
_started = False


def result() -> dict[str, object] | None:
    """Start once in a background thread and return the completed result."""
    global _started
    if not _started:
        from threading import Thread

        _started = True

        def collect() -> None:
            global _result
            try:
                _result = run(Path(__file__).resolve().parents[2])
            except Exception as exc:
                _result = {"experiment": "synthetic-stream-20261108", "error": type(exc).__name__}

        Thread(target=collect, name="temporary-benchmark", daemon=True).start()
    return _result
