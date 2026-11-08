"""Check the temporary benchmark output before deploying to a ticker."""

from pathlib import Path

from ticker_core.platform.temporary_benchmark import run


def test_synthetic_stream_benchmark_reports_bounded_results():
    result = run(Path(__file__).resolve().parents[3])
    assert result["experiment"] == "synthetic-stream-20261108"
    assert result["deltas"] == 500
    assert result["digest"] == "e02608188b168caba8a4a60a2278ff28908b07185d31ca492158b68de02d7bc5"
    assert 0 <= result["delta_p50_ms"] <= result["delta_p95_ms"] <= result["delta_max_ms"]
