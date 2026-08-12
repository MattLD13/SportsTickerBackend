from pathlib import Path

from ticker_core.platform import HealthCollector


def test_health_collector_reports_headers_and_caches_build(tmp_path: Path):
    temperature = tmp_path / "temp"
    temperature.write_text("42125", encoding="utf-8")
    calls = []

    def run(command, **kwargs):
        calls.append(command)
        return b"100" if "rev-list" in command else b"abc123"

    values = iter((10.0, 15.9, 20.0))
    collector = HealthCollector(tmp_path, temperature_path=temperature, wall_clock=lambda: next(values), run=run)
    first = collector.headers()
    second = collector.headers()
    assert first["X-Ticker-Uptime"] == "5"
    assert first["X-Ticker-Build"] == "r100+abc123"
    assert first["X-Ticker-Temp"] == "42.1"
    assert second["X-Ticker-Build"] == "r100+abc123"
    assert len(calls) == 2
