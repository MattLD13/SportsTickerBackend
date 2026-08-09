"""The panel a board draws once the backend stops answering."""

from PIL import ImageFont

from ticker_controller.modes.misc import MiscMixin, _offline_elapsed_label


class _DummyMisc(MiscMixin):
    def __init__(self):
        self.tiny = ImageFont.load_default()
        self.clock_giant = ImageFont.load_default()


def test_elapsed_label_picks_one_unit():
    cases = [(0, '0S'), (45, '45S'), (60, '1M'), (7200, '2H'), (172800, '2D')]
    for seconds, expected in cases:
        assert _offline_elapsed_label(seconds) == expected, seconds


def test_offline_screen_reads_as_a_warning():
    """Amber, so nobody mistakes a held frame for a live one."""
    img = _DummyMisc().draw_offline_screen(90)

    amber_pixels = sum(1 for r, g, b, a in img.getdata() if a and r > 150 and 80 < g < 200 and b < 60)
    assert amber_pixels > 0
    assert img.size == (384, 32)
