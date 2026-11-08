"""Check the temporary frame pacing trial."""
from ticker_core.app.temporary_motion_trial import run_once, summarize
from ticker_core.drivers import MemoryFrameSink


def test_summary_and_non_hardware_guard():
    assert summarize([1.0, 2.0, 3.0])['p50_ms'] == 2.0
    assert run_once(MemoryFrameSink()) is False
