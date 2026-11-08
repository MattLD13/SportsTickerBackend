"""Temporarily measure fractional-pixel scrolling at a 60 Hz target."""
from __future__ import annotations

import hashlib
import json
import statistics
import time
from pathlib import Path
from threading import Thread

from PIL import Image, ImageDraw, ImageFont

RESULT_PATH = Path('/tmp/ticker-transfer-band30-paired-20261108.json')
EXPERIMENT = 'transfer-band30-paired-20261108'
_started = False


def summarize(values):
    ordered = sorted(values)
    return {'count': len(values), 'mean_ms': round(statistics.fmean(values), 4),
            'p50_ms': round(statistics.median(values), 4),
            'p95_ms': round(ordered[int((len(ordered) - 1) * .95)], 4),
            'max_ms': round(ordered[-1], 4)}


def trial(sink, count=300):
    width, height = sink.width, sink.height
    strip = Image.new('RGB', (width * 3, height), (0, 0, 0))
    draw = ImageDraw.Draw(strip)
    font = ImageFont.load_default()
    for offset in range(0, width * 3, 96):
        draw.text((offset + 4, 6), 'SCORE 24 - 17', font=font, fill=(255, 255, 255))
        draw.line((offset, 27, offset + 86, 27), fill=(0, 120, 255))
    shifted = strip.crop((1, 0, strip.width + 1, height))
    prepared = [Image.blend(strip, shifted, phase / 9) for phase in range(9)]
    samples = {'frame_work': [], 'composition': [], 'presentation': [], 'presentation_cpu': [], 'interval': [], 'lateness': []}
    target = .03
    start = time.perf_counter()
    previous = None
    index = 0
    skipped = 0
    while index < count:
        deadline = start + index * target
        time.sleep(max(0.0, deadline - time.perf_counter()))
        begun = time.perf_counter()
        current = max(index, int((begun - start) / target))
        skipped += min(current, count) - index
        index = current
        if index >= count:
            break
        deadline = start + index * target
        displacement = index * 9
        whole = (displacement // 9) % width
        phase = displacement % 9
        frame = prepared[phase].crop((whole, 0, whole + width, height))
        built = time.perf_counter()
        cpu_started = time.thread_time()
        sink.present(frame, brightness=30, inverted=False)
        cpu_ended = time.thread_time()
        done = time.perf_counter()
        samples['frame_work'].append((done - begun) * 1000)
        samples['composition'].append((built - begun) * 1000)
        samples['presentation'].append((done - built) * 1000)
        samples['presentation_cpu'].append((cpu_ended - cpu_started) * 1000)
        samples['lateness'].append(max(0, done - (deadline + target)) * 1000)
        if previous is not None:
            samples['interval'].append((done - previous) * 1000)
        previous = done
        index += 1
    duration = time.perf_counter() - start
    return {'experiment': EXPERIMENT, 'frames': len(samples['frame_work']), 'skipped_slots': skipped, 'target_fps': round(1 / .03, 4),
            'requested_matrix_refresh_hz': 100, 'requested_pwm_bits': 11, 'requested_pwm_lsb_ns': 130, 'scroll_pixels_per_second': round(1 / .03, 4),
            'elapsed_seconds': round(duration, 4), 'presentations_per_second': round(len(samples['frame_work']) / duration, 4),
            'late_frames': sum(x > 0 for x in samples['lateness']),
            'late_over_1ms': sum(x > 1 for x in samples['lateness']),
            'last_frame_sha256': hashlib.sha256(frame.tobytes()).hexdigest(),
            'stages': {name: summarize(values) for name, values in samples.items()}}


def transfer_bands(canvas, frame, rows):
    """Transfer the complete frame in the selected horizontal band size."""
    for top in range(0, frame.height, rows):
        band = frame.crop((0, top, frame.width, min(top + rows, frame.height)))
        canvas.SetImage(band, 0, top)


def run_once(sink):
    from ticker_core.drivers import RgbMatrixFrameSink
    global _started
    if not isinstance(sink, RgbMatrixFrameSink) or _started or RESULT_PATH.exists():
        return False
    _started = True
    from ticker_core.drivers import rgbmatrix
    original = rgbmatrix._set_image
    def measured_transfer(canvas, frame):
        transfer_bands(canvas, frame, band_rows[0])
    band_rows = [4]
    try:
        rgbmatrix._set_image = measured_transfer
        cases = []
        for rows in (2, 4, 4, 2):
            band_rows[0] = rows
            value = trial(sink)
            cases.append({'band_rows': rows, 'frames': value['frames'], 'skipped_slots': value['skipped_slots'],
                          'fps': value['presentations_per_second'], 'presentation': value['stages']['presentation'],
                          'presentation_cpu': value['stages']['presentation_cpu'], 'interval': value['stages']['interval'],
                          'last_frame_sha256': value['last_frame_sha256']})
        report = {'experiment': EXPERIMENT, 'requested_pwm_bits': 11, 'requested_pwm_lsb_ns': 130,
                  'requested_matrix_refresh_hz': 100, 'cases': cases}
    except Exception as exc:
        report = {'experiment': EXPERIMENT, 'error': type(exc).__name__, 'message': str(exc)[:160]}
    finally:
        rgbmatrix._set_image = original
    def save():
        temp = RESULT_PATH.with_suffix('.tmp')
        temp.write_text(json.dumps(report), encoding='utf-8')
        temp.replace(RESULT_PATH)
    Thread(target=save, name='temporary-motion-save', daemon=True).start()
    return True
