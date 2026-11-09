"""Collect a short, bounded system-load diagnostic for the Pi."""
from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import time
from threading import Thread

EXPERIMENT = 'ticker-system-load-20261109'
_started = False
_report = None


def cpu_snapshot():
    result = {}
    for line in Path('/proc/stat').read_text().splitlines():
        fields = line.split()
        if fields and fields[0].startswith('cpu') and fields[0][3:].isdigit():
            values = [int(value) for value in fields[1:9]]
            if len(values) >= 5:
                result[fields[0]] = (sum(values), values[3] + values[4])
    return result


def read_int(path):
    try:
        return int(Path(path).read_text().strip())
    except (OSError, ValueError):
        return None


def collect():
    time.sleep(20.0)
    before = cpu_snapshot()
    start = time.monotonic()
    time.sleep(2.0)
    after = cpu_snapshot()
    cpus = {}
    for name, (total, idle) in after.items():
        if name not in before:
            continue
        old_total, old_idle = before[name]
        elapsed = total - old_total
        cpus[name] = round(100 * (1 - (idle - old_idle) / elapsed), 1) if elapsed > 0 else None
    frequencies = {str(index): read_int(f'/sys/devices/system/cpu/cpu{index}/cpufreq/scaling_cur_freq')
                   for index in range(os.cpu_count() or 0)}
    throttled = None
    error = None
    executable = shutil.which('vcgencmd')
    if executable:
        try:
            text = subprocess.check_output([executable, 'get_throttled'], stderr=subprocess.DEVNULL, timeout=3, text=True).strip()
            if text.startswith('throttled=0x'):
                throttled = text.split('=', 1)[1]
        except (OSError, subprocess.SubprocessError) as exc:
            error = type(exc).__name__
    temperature = read_int('/sys/class/thermal/thermal_zone0/temp')
    return {'experiment': EXPERIMENT, 'sample_seconds': round(time.monotonic() - start, 3),
            'per_core_busy_pct': cpus, 'load_average': [round(value, 2) for value in os.getloadavg()],
            'current_frequency_khz': frequencies,
            'temperature_c': round(temperature / 1000, 1) if temperature is not None else None,
            'throttled_flags': throttled, 'vcgencmd_available': bool(executable), 'vcgencmd_error': error}


def result():
    global _started
    if not os.environ.get('TICKER_FRAME_HEALTH_PATH'):
        return None
    if not _started:
        _started = True
        def worker():
            global _report
            try:
                _report = collect()
            except Exception as exc:
                _report = {'experiment': EXPERIMENT, 'error': type(exc).__name__}
        Thread(target=worker, name='temporary-system-diagnostic', daemon=True).start()
    return _report
