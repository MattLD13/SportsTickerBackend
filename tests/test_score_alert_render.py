from PIL import Image

from ticker_controller.config import PANEL_H, PANEL_W
from ticker_controller.fonts import (
    TINY_FONT_MAP, load_display_font, load_monospace_font, normalize_special_chars,
)
from ticker_controller.modes.score_alert import ScoreAlertMixin


class _Renderer(ScoreAlertMixin):
    """Just enough of TickerStreamer for the alert mixin to draw."""

    def __init__(self):
        self.medium_font = load_monospace_font(12, bold=True)
        self.big_font = load_monospace_font(14, bold=True)
        self.huge_font = load_display_font(20, bold=True)

    def get_logo(self, url, size=(24, 24)):
        return None

    def _parse_hex_color(self, value):
        c = str(value or '').strip().lstrip('#')
        return tuple(int(c[i:i + 2], 16) for i in (0, 2, 4)) if len(c) == 6 else None

    def _is_near_black(self, color, **kw):
        return bool(color) and max(color[:3]) <= 42

    def _is_near_white(self, color, **kw):
        return bool(color) and min(color[:3]) >= 226

    def _logo_nonblack_dominant_colors(self, logo, limit=2):
        return []

    def shorten_status(self, status, sport=''):
        return str(status).upper()

    def draw_outlined_text(self, d, x, y, text, font, fill, outline, anchor="mm"):
        d.text((x, y), text, font=font, fill=fill, anchor=anchor)


ALERT = {
    "id": "t", "sport": "mlb", "headline": "GRAND SLAM", "detail": "JUDGE",
    "status": "Bottom 7", "big": True, "team_abbr": "NYY",
    "team_color": "#132448", "team_alt_color": "#C4CED3",
    "home_abbr": "NYY", "away_abbr": "BOS", "home_score": 9, "away_score": 3,
}


def test_arrow_glyphs_are_drawable_and_centred():
    # They live in TINY_FONT_MAP, so they must reach draw_tiny_text intact
    # instead of hitting the ASCII fallback and becoming '?'.
    assert normalize_special_chars('▲7') == '▲7'
    # Columns map 0x8,0x4,0x2,0x1,0x10, so a centred apex is 0x2, not 0x4.
    assert sorted(r for r in TINY_FONT_MAP['▲'] if r) == [0x2, 0x7, 0x1F]
    # The substitutions the fonts genuinely need still happen.
    assert normalize_special_chars('Café') == 'Cafe'


def test_baseball_innings_use_arrows_and_other_sports_do_not():
    r = _Renderer()
    cases = [("Bottom 6", ('▼', '6')), ("Top 4", ('▲', '4')), ("V7", ('▼', '7'))]
    for status, expected in cases:
        assert r._alert_status_label(dict(ALERT, status=status)) == expected
    # No half to point at, so no arrow.
    assert r._alert_status_label(dict(ALERT, status="FINAL"))[0] == ''
    assert r._alert_status_label(dict(ALERT, sport='nhl', status='P2 6:03'))[0] == ''


def test_a_frame_is_panel_sized():
    frame = _Renderer().draw_score_alert(ALERT, 1.5)
    assert frame.size == (PANEL_W, PANEL_H)
    assert frame.mode == "RGB"


def test_the_shutters_reveal_what_was_underneath():
    under = Image.new("RGB", (PANEL_W, PANEL_H), (0, 200, 0))
    frame = _Renderer().draw_score_alert(ALERT, 0.02, under)
    # Barely open, so the edges still show the ticker rather than black.
    assert frame.getpixel((2, 16)) == (0, 200, 0)


def test_the_headline_flaps_then_settles():
    r = _Renderer()
    assert r._flap_headline("GRAND SLAM", 0.0) != "GRAND SLAM"
    assert r._flap_headline("GRAND SLAM", 5.0) == "GRAND SLAM"
    # Punctuation holds still, so the shape does not move while letters cycle.
    assert r._flap_headline("2-PT CONVERSION", 0.5)[1] == '-'


def test_missing_fields_do_not_raise():
    _Renderer().draw_score_alert({"headline": "GOAL"}, 1.0)
