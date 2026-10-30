"""Compare full-frame and production matrix transfers with identical RGB inputs.

Stop ticker-controller.service before a hardware run. Use an EXIT trap to restart it.
Use --hardware explicitly. The benchmark writes no controller settings or release files.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import statistics
import sys
import time

from PIL import Image


class PixelCanvas:
    """Reconstruct the RGB pixels submitted to the native canvas API."""

    def __init__(self):
        self.image = Image.new("RGB", (384, 32))

    def SetImage(self, image, x=0, y=0):
        self.image.paste(image, (x, y))


def summary(samples):
    values = sorted(samples)
    return {"p50_ms": statistics.median(values), "p95_ms": values[min(len(values) - 1, int(len(values) * 0.95))]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", type=Path, default=Path.cwd())
    parser.add_argument("--frames", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repeats", type=int, default=15)
    parser.add_argument("--cpu", type=int, help="Pin this benchmark thread to the selected Pi CPU.")
    parser.add_argument("--interval", type=float, default=0.03, help="Use this cadence for complete presentation measurements.")
    parser.add_argument("--production-first", action="store_true", help="Reverse the presentation order in a paired repeat.")
    parser.add_argument("--hardware", action="store_true", help="Use the physical matrix after stopping its normal controller.")
    parser.add_argument("--present", action="store_true", help="Also measure complete image preparation and vertical-sync presentation.")
    args = parser.parse_args()
    if args.repeats < 1:
        parser.error("--repeats must be positive")
    if not math.isfinite(args.interval) or args.interval < 0:
        parser.error("--interval must be finite and nonnegative")
    if args.cpu is not None:
        if not hasattr(os, "sched_setaffinity"):
            parser.error("--cpu requires CPU affinity support")
        os.sched_setaffinity(0, {args.cpu})
    sys.path.insert(0, str(args.repository.resolve()))
    from ticker.six.drivers.memory import _prepare_frame
    from ticker.six.drivers.rgbmatrix import RgbMatrixFrameSink, _set_image

    frames = [(path.stem, Image.open(path).convert("RGB")) for path in sorted(args.frames.glob("*.png"))]
    if not frames or any(image.size != (384, 32) for _, image in frames):
        parser.error("Provide at least one 384x32 PNG.")
    reference = PixelCanvas()
    for _, frame in frames:
        _set_image(reference, frame)
        if reference.image.tobytes() != frame.tobytes():
            raise AssertionError("Production transfer changed RGB pixels")
    sink = RgbMatrixFrameSink.create() if args.hardware else None
    canvas = sink._matrix.CreateFrameCanvas() if sink is not None else PixelCanvas()
    samples = {name: {method: {"wall": [], "cpu": []} for method in ("full", "production")} for name, _ in frames}
    present = {method: {"wall": [], "cpu": []} for method in ("full", "production")}
    try:
        for _ in range(3):
            for _, frame in frames:
                canvas.SetImage(frame)
                _set_image(canvas, frame)
        for repeat in range(args.repeats):
            for name, frame in frames:
                methods = ("full", "production") if repeat % 2 == 0 else ("production", "full")
                for method in methods:
                    clock, cpu = time.perf_counter(), time.thread_time()
                    if method == "full":
                        canvas.SetImage(frame)
                    else:
                        _set_image(canvas, frame)
                    samples[name][method]["cpu"].append((time.thread_time() - cpu) * 1000)
                    samples[name][method]["wall"].append((time.perf_counter() - clock) * 1000)
        if args.present and sink is not None:
            baseline_canvas = sink._matrix.CreateFrameCanvas()
            methods = ("production", "full") if args.production_first else ("full", "production")
            for method in methods:
                deadline = time.monotonic()
                for repeat in range(args.repeats):
                    for _, frame in frames:
                        time.sleep(max(0.0, deadline - time.monotonic()))
                        deadline += args.interval
                        clock, cpu = time.perf_counter(), time.thread_time()
                        if method == "full":
                            prepared = _prepare_frame(frame, 384, 32, False)
                            baseline_canvas.brightness = 100
                            baseline_canvas.SetImage(prepared)
                            baseline_canvas = sink._matrix.SwapOnVSync(baseline_canvas)
                        else:
                            sink.present(frame)
                        present[method]["cpu"].append((time.thread_time() - cpu) * 1000)
                        present[method]["wall"].append((time.perf_counter() - clock) * 1000)
    finally:
        if sink is not None:
            sink._matrix.Clear()
    report = {
        "hardware": args.hardware, "frames": len(frames), "repeats": args.repeats,
        "cpu": args.cpu, "presentation_interval_seconds": args.interval,
        "pixel_sha256": {name: hashlib.sha256(frame.tobytes()).hexdigest() for name, frame in frames},
        "transfer": {name: {method: {kind: summary(values) for kind, values in row.items()}
                             for method, row in methods.items()} for name, methods in samples.items()},
        "presentation": {method: {kind: summary(values) for kind, values in row.items()}
                         for method, row in present.items()} if args.present and args.hardware else {},
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({"frames": len(frames), "hardware": args.hardware, "presentation": report["presentation"]}, indent=2))


if __name__ == "__main__":
    main()
