"""Check the temporary GPIO slowdown trial."""
from types import SimpleNamespace

from PIL import Image

from ticker_core.app import temporary_motion_trial as module
from ticker_core.drivers import MemoryFrameSink


def test_summary_and_non_hardware_guard():
    assert module.summarize([1.0, 2.0, 3.0])['p50_ms'] == 2.0
    assert module.run_once(MemoryFrameSink(), None, None) is False


def test_refresh_intervals_measure_each_swap(monkeypatch):
    now = [0.0]

    class Canvas:
        brightness = 100

        def SetImage(self, image, x=0, y=0):
            pass

    class Matrix:
        def SwapOnVSync(self, canvas):
            now[0] += 0.010
            return canvas

    sink = SimpleNamespace(_canvas=Canvas(), _matrix=Matrix())
    monkeypatch.setattr(module.time, 'perf_counter', lambda: now[0])
    result = module.refresh_intervals(sink, Image.new('RGB', (384, 32)), 40, count=20)
    assert result['interval']['count'] == 20
    assert result['refresh_hz_p50'] == 100.0
    assert result['passes_over_10_5ms'] == 0


def test_live_trial_presents_consecutive_offsets(monkeypatch):
    now = [0.0]
    offsets = []

    class Viewport:
        def frame(self, offset, width, height):
            offsets.append(offset)
            return Image.new('RGB', (width, height))

    sink = MemoryFrameSink()
    monkeypatch.setattr(module.time, 'perf_counter', lambda: now[0])
    monkeypatch.setattr(module.time, 'sleep', lambda delay: now.__setitem__(0, now[0] + delay))
    decision = SimpleNamespace(scroll_offset=7, brightness=40, inverted=False)
    result = module.live_trial(sink, Viewport(), decision, count=5)
    assert offsets == [7, 8, 9, 10, 11]
    assert result['frames'] == 5
    assert result['late_frames'] == 0
