from PIL import Image, ImageDraw

from ticker_controller.modes.racing import _draw_racing_empty_state


def test_racing_empty_state_has_no_green_loading_bar():
    img = Image.new('RGBA', (128, 32), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    _draw_racing_empty_state(draw, 128, 32)

    greenish_pixels = 0
    for pixel in img.getdata():
        r, g, b, a = pixel
        if a and g > r + 20 and g > b + 20:
            greenish_pixels += 1

    assert greenish_pixels == 0