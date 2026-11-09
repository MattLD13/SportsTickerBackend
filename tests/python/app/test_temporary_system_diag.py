"""Check bounded aggregate diagnostics before device use."""
from ticker_core.app import temporary_system_diag as diag


def test_collect_calculates_core_utilization_without_exposing_processes(monkeypatch):
    snapshots = iter(({'cpu0': (100, 40)}, {'cpu0': (200, 65)}))
    monkeypatch.setattr(diag, 'cpu_snapshot', lambda: next(snapshots))
    monkeypatch.setattr(diag.time, 'sleep', lambda seconds: None)
    monkeypatch.setattr(diag.os, 'cpu_count', lambda: 1)
    monkeypatch.setattr(diag.os, 'getloadavg', lambda: (1.0, 2.0, 3.0))
    monkeypatch.setattr(diag, 'read_int', lambda path: 65000 if 'thermal' in path else 1000000)
    monkeypatch.setattr(diag.shutil, 'which', lambda name: None)
    result = diag.collect()
    assert result['per_core_busy_pct'] == {'cpu0': 75.0}
    assert result['temperature_c'] == 65.0
    assert result['current_frequency_khz'] == {'0': 1000000}
    assert result['throttled_flags'] is None
    assert 'processes' not in result
