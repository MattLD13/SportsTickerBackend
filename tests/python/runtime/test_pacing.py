import pytest

from ticker_core.runtime import FramePacer

pytestmark = pytest.mark.critical


class Clock:
    def __init__(self, value: float = 0.0) -> None:
        self.value = value

    def __call__(self) -> float:
        return self.value


def test_frame_pacer_keeps_deadlines_after_fast_frames() -> None:
    clock = Clock()
    pacer = FramePacer(clock)

    assert pacer.next_delay(0.1) == pytest.approx(0.1)
    clock.value = 0.02
    assert pacer.next_delay(0.1) == pytest.approx(0.18)


def test_frame_pacer_rebases_after_a_slow_frame() -> None:
    clock = Clock()
    pacer = FramePacer(clock)
    pacer.next_delay(0.1)
    clock.value = 0.25

    assert pacer.next_delay(0.1) == pytest.approx(0.0)
    clock.value = 0.26
    assert pacer.next_delay(0.1) == pytest.approx(0.09)


def test_frame_pacer_resets_and_rejects_negative_intervals() -> None:
    clock = Clock()
    pacer = FramePacer(clock)
    pacer.next_delay(1.0)
    pacer.reset()

    assert pacer.next_delay(0.5) == pytest.approx(0.5)
    try:
        pacer.next_delay(-1.0)
    except ValueError as error:
        assert "cannot be negative" in str(error)
    else:
        raise AssertionError("Expected a ValueError.")
