"""Check the temporary frame pacing trial."""
from ticker_core.app.temporary_motion_trial import run_once, summarize
from ticker_core.drivers import MemoryFrameSink


def test_summary_and_non_hardware_guard():
    assert summarize([1.0, 2.0, 3.0])['p50_ms'] == 2.0
    assert run_once(MemoryFrameSink()) is False


def test_trial_skips_stale_frames_instead_of_accumulating_delay(monkeypatch):
    from ticker_core.app import temporary_motion_trial as module

    now = [0.0]
    class SlowSink:
        width, height = 384, 32
        def present(self, image, *, brightness, inverted):
            now[0] += 0.040
    monkeypatch.setattr(module.time, 'perf_counter', lambda: now[0])
    monkeypatch.setattr(module.time, 'thread_time', lambda: now[0])
    monkeypatch.setattr(module.time, 'sleep', lambda delay: now.__setitem__(0, now[0] + delay))
    result = module.trial(SlowSink(), count=600)
    assert result['skipped_slots'] > 0
    assert result['frames'] + result['skipped_slots'] == 600
    assert result['elapsed_seconds'] <= 10.04


def test_affinity_is_restored_even_when_trial_fails(monkeypatch, tmp_path):
    from ticker_core.app import temporary_motion_trial as module
    from ticker_core.drivers import RgbMatrixFrameSink

    class InlineThread:
        def __init__(self, *, target, **kwargs):
            self.target = target
        def start(self):
            self.target()
    class Matrix:
        pass
    changes = []
    monkeypatch.setattr(module, 'Thread', InlineThread)
    monkeypatch.setattr(module, 'RESULT_PATH', tmp_path / 'report.json')
    monkeypatch.setattr(module, '_started', False)
    monkeypatch.setattr(module.os, 'sched_getaffinity', lambda pid: {1})
    monkeypatch.setattr(module.os, 'sched_setaffinity', lambda pid, cpus: changes.append(set(cpus)))
    def fail(sink):
        raise RuntimeError('test')
    monkeypatch.setattr(module, 'trial', fail)
    assert module.run_once(RgbMatrixFrameSink(Matrix())) is True
    assert changes == [{0}, {1}]
