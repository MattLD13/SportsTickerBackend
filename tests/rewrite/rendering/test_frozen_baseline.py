"""Render four production frames with frozen real-device logo sources."""
import pytest
from tools.benchmarks.frozen_render_baseline import run

pytestmark = pytest.mark.critical


def test_production_frames_match_the_reviewed_offline_baseline(tmp_path):
    report = run(tmp_path, repeats=2)
    assert report["pixels_match"]
    assert report["frozen_logos"] == 4
    assert report["network_requests"] == 0
    assert len(report["cases"]) == 4
