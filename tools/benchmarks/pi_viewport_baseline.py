"""Measure the existing card worker, frame builder, and desktop frame sink."""

from __future__ import annotations

import argparse
import ctypes
from dataclasses import fields, replace
from datetime import datetime
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import subprocess
import sys
import time

STARTED = time.perf_counter()
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from PIL import __version__ as pillow_version
from ticker_core.bootstrap import create_default_frame_builder
from ticker_core.context import RenderContext
from ticker_core.drivers.memory import MemoryFrameSink
from ticker_core.platform.assets import AssetCoordinator
from ticker_core.rendering.fonts import load_default_font_set
from ticker_core.runtime import Content, FrameDecision, FrameKind, RuntimeConfig
from tools.rendering.render_frame import content_items, normalize_snapshot


def process_metrics(pid: int) -> dict:
    """Read Windows process CPU time and working set without extra packages."""
    if sys.platform != "win32":
        return {"available": False}
    from ctypes import wintypes

    class Counters(ctypes.Structure):
        _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD)] + [
            (name, ctypes.c_size_t) for name in (
                "PeakWorkingSetSize", "WorkingSetSize", "QuotaPeakPagedPoolUsage",
                "QuotaPagedPoolUsage", "QuotaPeakNonPagedPoolUsage", "QuotaNonPagedPoolUsage",
                "PagefileUsage", "PeakPagefileUsage",
            )
        ]

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4
    psapi = ctypes.WinDLL("psapi", use_last_error=True)
    psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(Counters), wintypes.DWORD]
    handle = kernel.OpenProcess(0x410, False, pid)
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        timestamps = [wintypes.FILETIME() for _ in range(4)]
        if not kernel.GetProcessTimes(handle, *(ctypes.byref(value) for value in timestamps)):
            raise ctypes.WinError(ctypes.get_last_error())
        counters = Counters()
        counters.cb = ctypes.sizeof(counters)
        if not psapi.GetProcessMemoryInfo(handle, ctypes.byref(counters), counters.cb):
            raise ctypes.WinError(ctypes.get_last_error())
        ticks = sum((value.dwHighDateTime << 32) + value.dwLowDateTime for value in timestamps[2:])
        return {"available": True, "cpu_seconds": ticks / 10_000_000,
                "working_set_bytes": counters.WorkingSetSize,
                "peak_working_set_bytes": counters.PeakWorkingSetSize}
    finally:
        kernel.CloseHandle(handle)


def summary(values: list[float]) -> dict:
    """Report nearest-rank percentiles in milliseconds."""
    ordered = sorted(value * 1000 for value in values)
    return {"samples": len(values), "p50_ms": ordered[math.ceil(len(values) * .5) - 1],
            "p95_ms": ordered[math.ceil(len(values) * .95) - 1], "max_ms": ordered[-1]}


def wait_ready(viewport, cadence: float) -> float:
    """Install completed cards at the configured scroll frame cadence."""
    started = time.perf_counter()
    deadline = started
    while True:
        viewport.install_completed()
        status = viewport.status
        if not status["pending"]:
            assert status["failed"] == 0, status
            assert status["ready"] == status["desired"], status
            assert status["committed_generation"] == status["staging_generation"], status
            return time.perf_counter() - started
        if time.perf_counter() - started > 120:
            raise TimeoutError(str(status))
        deadline += cadence
        time.sleep(max(0, deadline - time.perf_counter()))


def fonts_manifest() -> list[dict]:
    """Record the exact resolved fonts and file hashes."""
    fonts = load_default_font_set()
    manifest = []
    for field in fields(fonts):
        font = getattr(fonts, field.name)
        path = getattr(font, "path", None)
        entry = {"role": field.name, "name": font.getname(), "size": getattr(font, "size", None),
                 "file": Path(path).name if isinstance(path, (str, os.PathLike)) else "Pillow embedded font"}
        if isinstance(path, (str, os.PathLike)) and Path(path).is_file():
            entry["sha256"] = hashlib.sha256(Path(path).read_bytes()).hexdigest()
        elif hasattr(path, "getvalue"):
            entry["sha256"] = hashlib.sha256(path.getvalue()).hexdigest()
        manifest.append(entry)
    return manifest


def run_case(args) -> dict:
    raw = args.snapshot.read_bytes()
    snapshot = json.loads(raw)
    source = content_items(normalize_snapshot(snapshot, "sports"), "sports")
    assert source, "The input snapshot has no sports records."
    cadence = float(snapshot["settings"]["scroll_speed"])
    assert cadence > 0
    now = datetime.fromisoformat("2026-08-13T00:00:00+00:00")
    context = RenderContext(now)
    items = tuple(Content(f"baseline-{index}-{source[index % len(source)]['id']}",
                          source[index % len(source)]["kind"], source[index % len(source)]["sport"],
                          dict(source[index % len(source)])) for index in range(args.case))
    assets_path = args.output / "empty-assets"
    assert not any(path.is_file() for path in assets_path.rglob("*")), "The asset baseline must stay empty."
    assets = AssetCoordinator(assets_path)
    builder, viewport = create_default_frame_builder(assets)
    sink = MemoryFrameSink()
    construction_ms = (time.perf_counter() - STARTED) * 1000
    try:
        started = time.perf_counter()
        viewport.update(items, context, "sports")
        wait_ready(viewport, cadence)
        ready_ms = (time.perf_counter() - started) * 1000
        decision = FrameDecision(FrameKind.SCROLL, cadence, 100, False, now, "sports", scroll_offset=0)
        frame = builder.build(decision)
        assert frame.size == (384, 32) and frame.getbbox() is not None
        sink.present(frame)
        first_present_ms = (time.perf_counter() - STARTED) * 1000
        assert sink.last_image.tobytes() == frame.tobytes()
        args.output.mkdir(parents=True, exist_ok=True)
        png = args.output / f"cards-{args.case}.png"
        frame.save(png)
        initial_hash = hashlib.sha256(frame.tobytes()).hexdigest()
        worker_pids = [process.pid for process in viewport._worker._processes.values()]
        pids = [os.getpid(), *worker_pids]
        memory_ready = [process_metrics(pid) for pid in pids]
        before = [process_metrics(pid) for pid in pids]
        wall = time.perf_counter()
        builds, presents = [], []
        for index in range(30 + args.frames):
            decision = replace(decision, scroll_offset=index % viewport.layout.width)
            started = time.perf_counter()
            frame = builder.build(decision)
            built = time.perf_counter()
            sink.present(frame, brightness=100, inverted=False)
            presented = time.perf_counter()
            if index >= 30:
                builds.append(built - started)
                presents.append(presented - built)
        frame_wall = time.perf_counter() - wall
        after = [process_metrics(pid) for pid in pids]
        cpu_seconds = sum(end["cpu_seconds"] - start["cpu_seconds"] for start, end in zip(before, after)
                          if start["available"] and end["available"])
        paced_start = time.perf_counter()
        paced_cpu_before = [process_metrics(pid) for pid in pids]
        for index in range(args.paced_frames):
            frame = builder.build(replace(decision, scroll_offset=index % viewport.layout.width))
            sink.present(frame)
            time.sleep(max(0, paced_start + (index + 1) * cadence - time.perf_counter()))
        paced_wall = time.perf_counter() - paced_start
        paced_cpu_after = [process_metrics(pid) for pid in pids]
        paced_cpu = sum(end["cpu_seconds"] - start["cpu_seconds"]
                        for start, end in zip(paced_cpu_before, paced_cpu_after) if start["available"])
        changed = dict(items[0].data)
        changed["away_score"] = str(int(changed["away_score"]) + 1)
        changed_items = (replace(items[0], data=changed), *items[1:])
        started = time.perf_counter()
        viewport.update(changed_items, context, "sports")
        queued = time.perf_counter()
        enqueue_ms = (queued - started) * 1000
        wait_ready(viewport, cadence)
        changed_frame = builder.build(replace(decision, scroll_offset=0))
        sink.present(changed_frame)
        update_ms = (time.perf_counter() - started) * 1000
        changed_hash = hashlib.sha256(changed_frame.tobytes()).hexdigest()
        assert changed_hash != initial_hash, "The changed score must reach the presented frame."
        changed_frame.save(args.output / f"cards-{args.case}-updated.png")
        started = time.perf_counter()
        viewport.invalidate()
        wait_ready(viewport, cadence)
        invalidation_ms = (time.perf_counter() - started) * 1000
        return {"cards": args.case, "source_records": len(source), "construction_with_imports_ms": construction_ms,
                "startup_queue_to_ready_ms": ready_ms, "startup_to_first_present_ms": first_present_ms,
                "status": dict(viewport.status), "layout_width": viewport.layout.width,
                "frame_build": summary(builds), "memory_sink_present": summary(presents),
                "unpaced_wall_seconds": frame_wall, "unpaced_cpu_seconds_parent_and_worker": cpu_seconds,
                "unpaced_cpu_percent_one_core": cpu_seconds / frame_wall * 100,
                "paced_frames": args.paced_frames, "paced_wall_seconds": paced_wall,
                "measured_memory_sink_fps": args.paced_frames / paced_wall,
                "paced_cpu_seconds_parent_and_worker": paced_cpu,
                "paced_cpu_percent_one_core": paced_cpu / paced_wall * 100,
                "memory_ready": memory_ready, "memory_after": [process_metrics(pid) for pid in pids],
                "one_score_update_enqueue_ms": enqueue_ms,
                "one_score_update_to_present_ms": update_ms, "full_asset_invalidation_to_ready_ms": invalidation_ms,
                "png": png.resolve().relative_to(ROOT).as_posix(),
                "rgb_sha256": initial_hash, "updated_rgb_sha256": changed_hash,
                "png_sha256": hashlib.sha256(png.read_bytes()).hexdigest(),
                "snapshot_sha256": hashlib.sha256(raw).hexdigest(), "fonts": fonts_manifest(),
                "cadence_seconds": cadence, "runtime_default_frame_seconds": RuntimeConfig().frame_interval}
    finally:
        viewport.close()
        assets.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", type=Path, default=ROOT / "tests/fixtures/display/v2_render_snapshot.json")
    parser.add_argument("--output", type=Path, default=ROOT / "previews/benchmarks/pi-baseline")
    parser.add_argument("--frames", type=int, default=6000)
    parser.add_argument("--paced-frames", type=int, default=300)
    parser.add_argument("--case", type=int, choices=(1, 10, 15, 60))
    args = parser.parse_args()
    assert args.frames > 0 and args.paced_frames > 0
    if args.case:
        result = run_case(args)
        (args.output / f"cards-{args.case}.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
        print(json.dumps({key: result[key] for key in ("cards", "startup_queue_to_ready_ms", "frame_build",
                                                      "one_score_update_to_present_ms", "measured_memory_sink_fps")}))
        return
    results = []
    for count in (1, 10, 60):
        subprocess.run([sys.executable, str(Path(__file__).resolve()), "--case", str(count),
                        "--snapshot", str(args.snapshot), "--output", str(args.output),
                        "--frames", str(args.frames), "--paced-frames", str(args.paced_frames)], check=True, cwd=ROOT)
        results.append(json.loads((args.output / f"cards-{count}.json").read_text(encoding="utf-8")))
    report = {"baseline_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
              "host": platform.platform(), "python": sys.version, "pillow": pillow_version,
              "processor": platform.processor(), "logical_cpus": os.cpu_count(),
              "limitations": ["Two existing snapshot records repeat with unique card IDs for capacity measurements.",
                              "No asset URLs exist in this snapshot. The prepared asset directory stays empty.",
                              "Windows MemoryFrameSink does not measure Pi matrix DMA or VSync.",
                              "The benchmark calls FrameBuilder and the sink directly, without application event or network work.",
                              "Memory values cover the parent and card worker. Resource tracker overhead is excluded.",
                              "Windows CPU counters use coarse accounting. Short samples can report zero or exceed 100 percent.",
                              "Font resolution follows the host. File hashes identify this baseline.",
                              "Readiness polling follows snapshot scroll cadence. It includes frame-boundary scheduling delay."],
              "cases": results}
    (args.output / "results.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"Saved {args.output / 'results.json'}")


if __name__ == "__main__":
    main()
