"""Temporarily measure fractional-pixel scrolling at a 60 Hz target."""
from __future__ import annotations

import hashlib
import json
import statistics
import time
from pathlib import Path
from threading import Thread

from PIL import Image, ImageDraw, ImageFont

RESULT_PATH = Path('/tmp/ticker-motion-60hz-20261108.json')
EXPERIMENT = 'motion-60hz-20261108'
_started = False


def summarize(values):
    ordered = sorted(values)
    return {'count': len(values), 'mean_ms': round(statistics.fmean(values), 4),
            'p50_ms': round(statistics.median(values), 4),
            'p95_ms': round(ordered[int((len(ordered) - 1) * .95)], 4),
            'max_ms': round(ordered[-1], 4)}


def trial(sink):
    width, height = sink.width, sink.height
    strip = Image.new('RGB', (width * 3, height), (0, 0, 0))
    draw = ImageDraw.Draw(strip)
    font = ImageFont.load_default()
    for offset in range(0, width * 3, 96):
        draw.text((offset + 4, 6), 'SCORE 24 - 17', font=font, fill=(255, 255, 255))
        draw.line((offset, 27, offset + 86, 27), fill=(0, 120, 255))
    samples = {'frame_work': [], 'composition': [], 'presentation': [], 'interval': [], 'lateness': []}
    target = 1 / 60
    start = time.perf_counter()
    previous = None
    for index in range(600):
        deadline = start + index * target
        time.sleep(max(0.0, deadline - time.perf_counter()))
        begun = time.perf_counter()
        position = (index * target / 0.03) % width
        whole = int(position)
        fraction = position - whole
        a = strip.crop((whole, 0, whole + width, height))
        b = strip.crop((whole + 1, 0, whole + width + 1, height))
        frame = Image.blend(a, b, fraction)
        built = time.perf_counter()
        sink.present(frame, brightness=30, inverted=False)
        done = time.perf_counter()
        samples['frame_work'].append((done - begun) * 1000)
        samples['composition'].append((built - begun) * 1000)
        samples['presentation'].append((done - built) * 1000)
        samples['lateness'].append(max(0, done - (deadline + target)) * 1000)
        if previous is not None:
            samples['interval'].append((done - previous) * 1000)
        previous = done
    duration = time.perf_counter() - start
    return {'experiment': EXPERIMENT, 'frames': 600, 'target_fps': 60,
            'requested_matrix_refresh_hz': 120, 'scroll_pixels_per_second': round(1 / .03, 4),
            'elapsed_seconds': round(duration, 4), 'presentations_per_second': round(600 / duration, 4),
            'late_frames': sum(x > 0 for x in samples['lateness']),
            'late_over_1ms': sum(x > 1 for x in samples['lateness']),
            'last_frame_sha256': hashlib.sha256(frame.tobytes()).hexdigest(),
            'stages': {name: summarize(values) for name, values in samples.items()}}


def run_once(sink):
    from ticker_core.drivers import RgbMatrixFrameSink
    global _started
    if not isinstance(sink, RgbMatrixFrameSink) or _started or RESULT_PATH.exists():
        return False
    _started = True
    try:
        report = trial(sink)
    except Exception as exc:
        report = {'experiment': EXPERIMENT, 'error': type(exc).__name__, 'message': str(exc)[:160]}
    def save():
        temp = RESULT_PATH.with_suffix('.tmp')
        temp.write_text(json.dumps(report), encoding='utf-8')
        temp.replace(RESULT_PATH)
    Thread(target=save, name='temporary-motion-save', daemon=True).start()
    return True
