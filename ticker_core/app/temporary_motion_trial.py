"""Temporarily measure panel refresh and live presentation at GPIO slowdown 2."""
from __future__ import annotations

import json
import statistics
import time
from pathlib import Path
from threading import Thread

RESULT_PATH = Path('/tmp/ticker-gpio-slowdown2-forced-20261109.json')
EXPERIMENT = 'gpio-slowdown2-forced-20261109'
_started = False


def summarize(values):
    if not values:
        return None
    ordered = sorted(values)
    return {'count': len(values), 'mean_ms': round(statistics.fmean(values), 4),
            'p50_ms': round(statistics.median(values), 4),
            'p95_ms': round(ordered[int((len(ordered) - 1) * .95)], 4),
            'max_ms': round(ordered[-1], 4)}


def _read(path):
    try:
        return Path(path).read_text(encoding='utf-8').strip()
    except OSError:
        return None


def system_facts():
    temperature = _read('/sys/class/thermal/thermal_zone0/temp')
    frequency = _read('/sys/devices/system/cpu/cpu0/cpufreq/scaling_cur_freq')
    return {'temperature_c': round(int(temperature) / 1000, 1) if temperature and temperature.isdigit() else None,
            'cpu0_khz': int(frequency) if frequency and frequency.isdigit() else None,
            'governor': _read('/sys/devices/system/cpu/cpu0/cpufreq/scaling_governor')}


def refresh_intervals(sink, frame, brightness, count=300):
    """Swap identical canvases back to back. Each interval is one complete refresh pass."""
    from ticker_core.drivers.rgbmatrix import _set_image
    for _ in range(2):
        sink._canvas.brightness = brightness
        _set_image(sink._canvas, frame)
        sink._canvas = sink._matrix.SwapOnVSync(sink._canvas)
    times = []
    for _ in range(count + 1):
        sink._canvas = sink._matrix.SwapOnVSync(sink._canvas)
        times.append(time.perf_counter())
    intervals = [(after - before) * 1000 for before, after in zip(times, times[1:])]
    middle = statistics.median(intervals)
    return {'interval': summarize(intervals), 'refresh_hz_p50': round(1000 / middle, 2) if middle else None,
            'passes_over_10_5ms': sum(value > 10.5 for value in intervals)}


def live_trial(sink, viewport, decision, count=333):
    """Present live strip pixels at the production 30 ms scroll cadence."""
    target = 0.03
    first_offset = decision.scroll_offset or 0
    samples = {'present': [], 'interval': [], 'lateness': []}
    start = time.perf_counter()
    previous = None
    for index in range(count):
        deadline = start + index * target
        time.sleep(max(0.0, deadline - time.perf_counter()))
        frame = viewport.frame(first_offset + index, width=sink.width, height=sink.height)
        begun = time.perf_counter()
        sink.present(frame, brightness=decision.brightness, inverted=decision.inverted)
        done = time.perf_counter()
        samples['present'].append((done - begun) * 1000)
        samples['lateness'].append(max(0.0, done - (deadline + target)) * 1000)
        if previous is not None:
            samples['interval'].append((done - previous) * 1000)
        previous = done
    return {'frames': count, 'late_frames': sum(value > 0 for value in samples['lateness']),
            'stages': {name: summarize(values) for name, values in samples.items()}}


def run_once(sink, viewport, decision):
    from dataclasses import asdict

    from ticker_core.drivers import RgbMatrixFrameSink, RgbMatrixSettings
    from ticker_core.runtime import FrameKind
    global _started
    if (not isinstance(sink, RgbMatrixFrameSink) or sink._canvas is None or _started or RESULT_PATH.exists()
            or decision is None or decision.kind is not FrameKind.SCROLL or decision.news is not None
            or decision.connection_lost or decision.update_failure is not None
            or getattr(viewport, 'layout', None) is None):
        return False
    _started = True
    try:
        settings = asdict(RgbMatrixSettings.from_environment())
        frame = viewport.frame(decision.scroll_offset or 0, width=sink.width, height=sink.height)
        report = {'experiment': EXPERIMENT, 'settings': settings, 'system_start': system_facts(),
                  'refresh': refresh_intervals(sink, frame, decision.brightness),
                  'live': live_trial(sink, viewport, decision),
                  'system_end': system_facts()}
    except Exception as exc:
        report = {'experiment': EXPERIMENT, 'error': type(exc).__name__, 'message': str(exc)[:160]}

    def save():
        temporary = RESULT_PATH.with_suffix('.tmp')
        temporary.write_text(json.dumps(report), encoding='utf-8')
        temporary.replace(RESULT_PATH)
    Thread(target=save, name='temporary-motion-save', daemon=True).start()
    return True
