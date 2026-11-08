"""Check bounded timing capture and percentile output."""
import json
from ticker_core.app import temporary_profile as profile


def test_profile_records_intervals_and_finishes(monkeypatch, tmp_path):
    class InlineThread:
        def __init__(self, *, target, **kwargs):
            self.target = target
        def start(self):
            self.target()
    monkeypatch.setattr(profile, 'Thread', InlineThread)
    monkeypatch.setattr(profile, 'RESULT_PATH', tmp_path / 'report.json')
    monkeypatch.setattr(profile, 'SAMPLE_COUNT', 2)
    monkeypatch.setattr(profile, 'rows', [])
    monkeypatch.setattr(profile, 'matrix', {'vsync_swap': 2.0})
    monkeypatch.setattr(profile, '_finished', False)
    monkeypatch.setattr(profile, '_previous_present', None)
    profile.add({'frame_total': 4.0}, 1.0)
    profile.add({'frame_total': 6.0}, 1.03)
    report = json.loads(profile.RESULT_PATH.read_text())
    assert report['frames'] == 2
    assert report['stages']['frame_total']['p50_ms'] == 5.0
    assert report['stages']['present_interval']['p50_ms'] == 30.0
    assert report['stages']['vsync_swap']['count'] == 2
