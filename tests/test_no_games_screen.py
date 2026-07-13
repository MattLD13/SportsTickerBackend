from PIL import Image, ImageDraw, ImageFont

from ticker_controller.modes.misc import MiscMixin


class _DummyMisc(MiscMixin):
    def __init__(self):
        self.font = ImageFont.load_default()
        self.tiny = ImageFont.load_default()


def test_no_games_screen_is_neutral():
    dummy = _DummyMisc()
    img = dummy.draw_no_games_screen()

    greenish_pixels = 0
    for pixel in img.getdata():
        r, g, b, a = pixel
        if a and g > r + 20 and g > b + 20:
            greenish_pixels += 1

    assert greenish_pixels == 0
