"""Temporary bounded wall-clock profile of presented scrolling frames."""
from __future__ import annotations

import json
import statistics
import time
from pathlib import Path
from threading import Thread

RESULT_PATH = Path('/tmp/ticker-scroll-profile-20261108.json')
EXPERIMENT = 'scroll-profile-20261108'
SAMPLE_COUNT = 600
rows: list[dict[str, float]] = []
matrix: dict[str, float] = {}
_previous_present: float | None = None
_finished = RESULT_PATH.exists()


def clock() -> float:
    return time.perf_counter()


def add(row: dict[str, float], finish: float) -> None:
    global _previous_present, _finished
    if _finished:
        return
    if _previous_present is not None:
        row['present_interval'] = (finish - _previous_present) * 1000
    _previous_present = finish
    row.update(matrix)
    rows.append(row)
    if len(rows) < SAMPLE_COUNT:
        return
    _finished = True
    captured = tuple(rows)

    def save() -> None:
        stages = {}
        for key in sorted({key for item in captured for key in item}):
            values = sorted(item[key] for item in captured if key in item)
            stages[key] = {'count': len(values), 'p50_ms': round(statistics.median(values), 4),
                           'p95_ms': round(values[int((len(values) - 1) * .95)], 4),
                           'max_ms': round(values[-1], 4), 'mean_ms': round(statistics.fmean(values), 4)}
        total = [item['frame_total'] for item in captured]
        report = {'experiment': EXPERIMENT, 'frames': len(captured), 'stages': stages,
                  'over_30ms': sum(item > 30 for item in total),
                  'instrumentation': 'Wall clock; 600 presented scrolling frames, including scheduling delays.'}
        temp = RESULT_PATH.with_suffix('.tmp')
        temp.write_text(json.dumps(report), encoding='utf-8')
        temp.replace(RESULT_PATH)

    Thread(target=save, name='temporary-profile-save', daemon=True).start()
