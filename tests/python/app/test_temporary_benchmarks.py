"""Check the synthetic hardware benchmark before deployment."""
import json
from pathlib import Path

from ticker_core.app.temporary_benchmarks import stream_case, run_once
from ticker_core.drivers import MemoryFrameSink


def test_stream_case_preserves_sequence_and_bounded_output():
    path = Path(__file__).resolve().parents[2] / 'fixtures/display/v2_render_snapshot.json'
    result = stream_case(json.loads(path.read_text(encoding='utf-8')), 10)
    assert result['cards'] == 10
    assert result['delta']['count'] == 50
    assert result['last_payload_digest'] == 'c42576668b3e94a658ba33b2a0fd881f02ef7bd38bd81e4a83b9aa92286a2c85'


def test_non_hardware_sink_is_not_taken_over(tmp_path):
    assert run_once(MemoryFrameSink(), tmp_path) is False
