from PIL import Image, ImageChops
from ticker_core.app.temporary_motion_trial import transfer, summarize


def test_dirty_transfer_matches_complete_frame_for_reused_canvas():
    class Canvas:
        def __init__(self):
            self.image = Image.new('RGB', (384, 32))
        def SetImage(self, image, x, y):
            self.image.paste(image, (x, y))
    first = Image.new('RGB', (384, 32), (10, 20, 30))
    current = first.copy()
    current.paste((200, 80, 70), (60, 3, 80, 9))
    for width in (0, 64, 128):
        canvas = Canvas()
        transfer(canvas, first, None, width)
        pixels = transfer(canvas, current, first, width)
        assert ImageChops.difference(canvas.image, current).getbbox() is None
        assert pixels <= 384 * 32
        if width:
            assert pixels < 384 * 32


def test_empty_summary():
    assert summarize([]) is None
