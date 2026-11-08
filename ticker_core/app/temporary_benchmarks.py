"""Temporary on-device performance experiment with synthetic input."""
from __future__ import annotations

import copy
import hashlib
import json
import os
import platform
import resource
import statistics
import time
from pathlib import Path

from PIL import Image, ImageDraw
from ticker_core.protocol import DeviceStreamState, StreamMessage

EXPERIMENT = "hardware-suite-20261108"
RESULT_PATH = Path("/tmp/ticker-hardware-suite-20261108.json")


def stats(values):
    ordered = sorted(values)
    return {"count": len(ordered), "p50_ms": round(statistics.median(ordered), 3),
            "p95_ms": round(ordered[int((len(ordered) - 1) * .95)], 3),
            "max_ms": round(ordered[-1], 3)}


def temperature():
    try:
        return round(int(Path('/sys/class/thermal/thermal_zone0/temp').read_text().strip()) / 1000, 1)
    except (ValueError, OSError):
        return None


def stream_case(payload, count):
    base = {"type": "snapshot", "protocol_version": 1, "stream_id": "bench", "seq": 1,
            "base_seq": 1, "server_time": "2026-10-14T00:00:00+00:00", "payload": copy.deepcopy(payload)}
    source = base["payload"]["content"]["sports"]
    expanded = []
    for i in range(count):
        item = copy.deepcopy(source[i % len(source)])
        item["id"] = f"benchmark-{i}"
        expanded.append(item)
    base["payload"]["content"]["sports"] = expanded
    state = DeviceStreamState()
    started = time.perf_counter()
    response = state.apply(StreamMessage.from_payload(json.loads(json.dumps(base))))
    snapshot_ms = (time.perf_counter() - started) * 1000
    durations = []
    for seq in range(2, 52):
        content = copy.deepcopy(base["payload"]["content"])
        content["sports"][0]["data"]["away_score"] = str(seq)
        message = {"type": "delta", "protocol_version": 1, "stream_id": "bench", "seq": seq,
                   "base_seq": seq - 1, "server_time": "2026-10-14T00:00:00+00:00", "changes": {"content": content}, "removed": []}
        raw = json.dumps(message, separators=(",", ":"))
        started = time.perf_counter()
        response = state.apply(StreamMessage.from_payload(json.loads(raw)))
        durations.append((time.perf_counter() - started) * 1000)
    assert response is not None
    return {"cards": count, "input_bytes": len(raw.encode()), "snapshot_ms": round(snapshot_ms, 3),
            "delta": stats(durations), "last_payload_digest": response.payload_key}


def run(sink, repository):
    """Use the owned sink, then return to the caller even when one case fails."""
    fixture = (repository / "tests/fixtures/display/v2_render_snapshot.json").read_bytes()
    payload = json.loads(fixture)
    report = {"experiment": EXPERIMENT, "machine": platform.machine(), "python": platform.python_version(),
              "fixture_sha256": hashlib.sha256(fixture).hexdigest(), "temperature_start_c": temperature()}
    cpu = time.process_time()
    wall = time.perf_counter()
    banner = Image.new("RGB", (sink.width, sink.height), (0, 0, 25))
    ImageDraw.Draw(banner).text((8, 9), "BENCHMARK IN PROGRESS", fill=(255, 255, 255))
    sink.present(banner, brightness=30, inverted=False)
    report["stream"] = [stream_case(payload, n) for n in (1, 10, 60)]
    frame = Image.new("RGB", (sink.width, sink.height), (8, 8, 30))
    draw = ImageDraw.Draw(frame)
    draw.text((8, 9), "MATRIX TIMING TEST", fill=(255, 255, 255))
    durations, intervals = [], []
    start = time.perf_counter()
    previous = None
    for i in range(150):
        image = frame.copy()
        ImageDraw.Draw(image).rectangle((i % sink.width, 0, min(i % sink.width + 3, sink.width - 1), 31), fill=(0, 180, 80))
        begun = time.perf_counter()
        sink.present(image, brightness=30, inverted=False)
        end = time.perf_counter()
        durations.append((end - begun) * 1000)
        if previous is not None:
            intervals.append((end - previous) * 1000)
        previous = end
        time.sleep(max(0, start + (i + 1) * .03 - time.perf_counter()))
    report["matrix"] = {"present": stats(durations), "interval": stats(intervals),
                        "elapsed_seconds": round(time.perf_counter() - start, 3), "target_interval_ms": 30,
                        "intervals_over_30ms": sum(x > 30 for x in intervals)}
    source = Image.new("RGB", (sink.width * 2, sink.height), (0, 80, 160))
    composition = []
    for i in range(500):
        t = time.perf_counter()
        source.crop((i % sink.width, 0, i % sink.width + sink.width, sink.height))
        composition.append((time.perf_counter() - t) * 1000)
    report["pillow_crop"] = stats(composition)
    report["resources"] = {"wall_seconds": round(time.perf_counter() - wall, 3),
                           "process_cpu_seconds": round(time.process_time() - cpu, 3),
                           "max_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                           "temperature_end_c": temperature(), "logical_cpus": os.cpu_count()}
    return report


def run_once(sink, repository):
    from ticker_core.drivers import RgbMatrixFrameSink
    if not isinstance(sink, RgbMatrixFrameSink) or RESULT_PATH.exists():
        return False
    try:
        report = run(sink, repository)
    except Exception as exc:
        report = {"experiment": EXPERIMENT, "error": type(exc).__name__, "message": str(exc)[:160]}
    temporary = RESULT_PATH.with_suffix('.tmp')
    temporary.write_text(json.dumps(report), encoding='utf-8')
    temporary.replace(RESULT_PATH)
    return True
