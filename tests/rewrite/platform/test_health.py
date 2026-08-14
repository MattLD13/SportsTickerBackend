from pathlib import Path

from ticker_core.platform import HealthCollector


def test_health_collector_reports_snapshot_and_caches_build(tmp_path: Path):
    temperature = tmp_path / "temp"
    temperature.write_text("42125", encoding="utf-8")
    calls = []

    def run(command, **kwargs):
        calls.append(command)
        return b"100" if "rev-list" in command else b"abc123"

    values = iter((10.0, 15.9, 20.0))
    collector = HealthCollector(tmp_path, temperature_path=temperature, wall_clock=lambda: next(values), run=run)
    first = collector.snapshot()
    second = collector.snapshot()
    assert first.uptime_seconds == 5
    assert first.build == "r100+abc123"
    assert first.temperature_c == 42.1
    assert second.build == "r100+abc123"
    assert len(calls) == 2
