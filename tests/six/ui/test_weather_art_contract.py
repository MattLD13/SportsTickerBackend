"""Keep the exported Mini track aligned with the shared weather drawing period."""
import pytest

from ticker.six.ui.weather_art import ANIMATION_PERIOD
from tools.mini.generate_mini_weather import FRAMES, STEP_MS, animation_frame_count

pytestmark = pytest.mark.critical


def test_mini_weather_track_uses_the_exact_shared_period():
    assert FRAMES == 126
    assert FRAMES * STEP_MS == round(ANIMATION_PERIOD * 1000)
    assert animation_frame_count(24, 100) == 240


@pytest.mark.parametrize("period,step", [(0, 100), (-1, 100), (12.6, 0), (12.6, -1), (1.05, 100)])
def test_invalid_or_partial_weather_frames_are_rejected(period, step):
    with pytest.raises(ValueError):
        animation_frame_count(period, step)
