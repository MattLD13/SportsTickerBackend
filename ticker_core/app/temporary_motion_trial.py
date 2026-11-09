"""Temporarily compare changed-region transfers on live card pixels."""
from __future__ import annotations

import json
import statistics
import time
from pathlib import Path
from threading import Thread

from PIL import ImageChops

RESULT_PATH = Path('/tmp/ticker-live-panel120-20261109.json')
EXPERIMENT = 'live-panel120-20261109'
_started = False


def summarize(values):
    if not values:
        return None
    ordered = sorted(values)
    return {'count': len(values), 'mean_ms': round(statistics.fmean(values), 4),
            'p95_ms': round(ordered[int((len(ordered) - 1) * .95)], 4),
            'max_ms': round(ordered[-1], 4)}


def transfer(canvas, frame, previous, tile_width):
    """Update only changed 2-row tiles; return transferred pixel count."""
    from ticker_core.drivers.rgbmatrix import _set_image
    if tile_width == 0 or previous is None:
        _set_image(canvas, frame)
        return frame.width * frame.height
    difference = ImageChops.difference(frame, previous)
    pixels = 0
    for top in range(0, frame.height, 2):
        for left in range(0, frame.width, tile_width):
            right = min(left + tile_width, frame.width)
            bottom = min(top + 2, frame.height)
            box = (left, top, right, bottom)
            if difference.crop(box).getbbox() is not None:
                canvas.SetImage(frame.crop(box), left, top)
                pixels += (right - left) * (bottom - top)
    return pixels


def trial(sink, strip, decision, tile_width, count=600):
    """Run timed real-pixel frames at 60 target slots/s, dropping stale slots."""
    from ticker_core.drivers.memory import _prepare_frame
    target = 1 / 60
    start = time.perf_counter()
    samples = {'total': [], 'transfer': [], 'transfer_cpu': [], 'interval': []}
    previous_frames = [None, None]
    canvas_index = 0
    pixels = 0
    skipped = 0
    index = 0
    previous_time = None
    while index < count:
        time.sleep(max(0.0, start + index * target - time.perf_counter()))
        begun = time.perf_counter()
        current = max(index, int((begun - start) / target))
        skipped += min(current, count) - index
        index = current
        if index >= count:
            break
        offset = (index * 5) // 9
        frame = strip.crop((offset, 0, offset + sink.width, sink.height))
        frame = _prepare_frame(frame, sink.width, sink.height, decision.inverted, copy=False)
        sink._canvas.brightness = decision.brightness
        cpu_start = time.thread_time()
        transfer_start = time.perf_counter()
        pixels += transfer(sink._canvas, frame, previous_frames[canvas_index], tile_width)
        cpu_end = time.thread_time()
        transfer_end = time.perf_counter()
        previous_frames[canvas_index] = frame.copy()
        sink._canvas = sink._matrix.SwapOnVSync(sink._canvas)
        canvas_index = 1 - canvas_index
        done = time.perf_counter()
        samples['total'].append((done - begun) * 1000)
        samples['transfer'].append((transfer_end - transfer_start) * 1000)
        samples['transfer_cpu'].append((cpu_end - cpu_start) * 1000)
        if previous_time is not None:
            samples['interval'].append((done - previous_time) * 1000)
        previous_time = done
        index += 1
    duration = time.perf_counter() - start
    frames = len(samples['total'])
    return {'tile_width': tile_width, 'frames': frames, 'skipped_slots': skipped,
            'fps': round(frames / duration, 4), 'transferred_pixel_fraction': round(pixels / max(1, frames * sink.width * sink.height), 4),
            'stages': {name: summarize(values) for name, values in samples.items()}}


def run_once(sink, viewport, decision):
    from ticker_core.drivers import RgbMatrixFrameSink
    from ticker_core.runtime import FrameKind
    global _started
    if (not isinstance(sink, RgbMatrixFrameSink) or sink._canvas is None or _started or RESULT_PATH.exists()
            or decision.kind is not FrameKind.SCROLL or decision.news is not None
            or decision.connection_lost or decision.update_failure is not None):
        return False
    _started = True
    try:
        strip = viewport.frame(decision.scroll_offset or 0, width=sink.width + 400, height=sink.height)
        cases = [trial(sink, strip, decision, tile_width) for tile_width in (0, 0)]
        report = {'experiment': EXPERIMENT, 'requested_refresh_hz': 120, 'cases': cases}
    except Exception as exc:
        report = {'experiment': EXPERIMENT, 'error': type(exc).__name__, 'message': str(exc)[:160]}
    def save():
        temp = RESULT_PATH.with_suffix('.tmp')
        temp.write_text(json.dumps(report), encoding='utf-8')
        temp.replace(RESULT_PATH)
    Thread(target=save, name='temporary-motion-save', daemon=True).start()
    return True
