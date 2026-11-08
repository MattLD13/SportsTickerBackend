"""Check the temporary frame pacing trial."""
from ticker_core.app.temporary_motion_trial import run_once, summarize
from ticker_core.drivers import MemoryFrameSink


def test_summary_and_non_hardware_guard():
    assert summarize([1.0, 2.0, 3.0])['p50_ms'] == 2.0
    assert run_once(MemoryFrameSink()) is False


def test_trial_restores_priority_and_records_result(monkeypatch, tmp_path):
    import json
    from ticker_core.app import temporary_motion_trial as module
    from ticker_core.drivers import RgbMatrixFrameSink

    class InlineThread:
        def __init__(self, *, target, **kwargs):
            self.target = target
        def start(self):
            self.target()

    class Matrix:
        pass

    priorities = iter((0, -5))
    changes = []
    monkeypatch.setattr(module, 'RESULT_PATH', tmp_path / 'result.json')
    monkeypatch.setattr(module, '_started', False)
    monkeypatch.setattr(module, 'Thread', InlineThread)
    monkeypatch.setattr(module.os, 'getpriority', lambda *args: next(priorities))
    monkeypatch.setattr(module.os, 'nice', lambda value: changes.append(value))
    monkeypatch.setattr(module, 'trial', lambda sink: {'experiment': module.EXPERIMENT})
    assert module.run_once(RgbMatrixFrameSink(Matrix())) is True
    result = json.loads(module.RESULT_PATH.read_text())
    assert changes == [-5, 5]
    assert result['initial_nice'] == 0 and result['trial_nice'] == -5
    assert result['priority_error'] is None
