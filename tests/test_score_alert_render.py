import pytest
from PIL import Image

from ticker_controller.config import PANEL_H, PANEL_W
from ticker_controller.fonts import (
    HYBRID_FONT_MAP,
    TINY_FONT_MAP,
    load_display_font,
    load_monospace_font,
    normalize_special_chars,
)
from ticker_controller.modes.score_alert import ScoreAlertMixin, score_alert_duration


class _Renderer(ScoreAlertMixin):
    """Just enough of TickerStreamer for the alert mixin to draw."""

    def __init__(self):
        self.medium_font = load_monospace_font(12, bold=True)
        self.big_font = load_monospace_font(14, bold=True)
        self.huge_font = load_display_font(20, bold=True)
        self.logo_cache = {}

    # Borrowed verbatim from TickerStreamer; the mixin calls these.
    def get_logo(self, url, size=(24, 24)):
        return None

    def _parse_hex_color(self, value):
        c = str(value or '').strip().lstrip('#')
        if len(c) == 6:
            return tuple(int(c[i:i + 2], 16) for i in (0, 2, 4))
        return None

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


def alert(**kwargs):
    base = {
        "id": "t", "sport": "mlb", "headline": "GRAND SLAM", "detail": "JUDGE",
        "status": "Bottom 7", "big": True, "points": 4,
        "team_abbr": "NYY", "team_color": "#132448", "team_alt_color": "#C4CED3",
        "opp_abbr": "BOS", "home_abbr": "NYY", "away_abbr": "BOS",
        "home_score": 9, "away_score": 3, "team_logo": "",
    }
    base.update(kwargs)
    return base


# ── pixel-font glyphs ────────────────────────────────────────────────────────

def test_arrow_glyphs_survive_normalization():
    # They live in TINY_FONT_MAP, so they must reach draw_tiny_text intact
    # rather than being replaced with '?' by the ASCII fallback.
    assert normalize_special_chars('▲7') == '▲7'
    assert normalize_special_chars('▼6') == '▼6'


def test_normalization_still_substitutes_what_the_fonts_lack():
    assert normalize_special_chars('Café') == 'Cafe'
    assert normalize_special_chars('½') == '1/2'
    assert normalize_special_chars('–') == '-'


@pytest.mark.parametrize("glyph", ['▲', '▼'])
def test_arrow_bitmaps_are_centred(glyph):
    # Columns map 0x8,0x4,0x2,0x1,0x10 left to right. A lopsided triangle is
    # what the original 0x4/0xE rows produced.
    rows = TINY_FONT_MAP[glyph]
    apex = 0x2
    middle = 0x7
    full = 0x1F
    assert sorted(r for r in rows if r) == sorted([apex, middle, full])


def test_font_maps_have_no_conflicting_substitutions():
    # normalize_special_chars now prefers the font maps, so anything in both
    # would silently stop being substituted.
    from ticker_controller.fonts import SPECIAL_CHAR_MAP
    drawable = set(TINY_FONT_MAP) | set(HYBRID_FONT_MAP)
    assert not (drawable & set(SPECIAL_CHAR_MAP))


# ── status label ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize("status,expected", [
    ("Bottom 6", ('▼', '6')),
    ("BOT 9", ('▼', '9')),
    ("V7", ('▼', '7')),
    ("Top 4", ('▲', '4')),
    ("^1", ('▲', '1')),
])
def test_baseball_innings_use_arrows(status, expected):
    assert _Renderer()._alert_status_label(alert(status=status)) == expected


@pytest.mark.parametrize("status", ["Mid 5", "End 8", "FINAL", "Delayed"])
def test_between_innings_and_final_get_no_arrow(status):
    arrow, _ = _Renderer()._alert_status_label(alert(status=status))
    assert arrow == ''


def test_other_sports_are_untouched():
    assert _Renderer()._alert_status_label(
        alert(sport='nhl', status='P2 6:03')) == ('', 'P2 6:03')


# ── frame ────────────────────────────────────────────────────────────────────

def test_frame_is_panel_sized_rgb():
    frame = _Renderer().draw_score_alert(alert(), 1.5)
    assert frame.size == (PANEL_W, PANEL_H)
    assert frame.mode == "RGB"


def test_shutters_reveal_what_was_underneath():
    under = Image.new("RGB", (PANEL_W, PANEL_H), (0, 200, 0))
    frame = _Renderer().draw_score_alert(alert(), 0.02, under)
    # Barely open: the edges must still be showing the ticker, not black.
    assert frame.getpixel((2, 16)) == (0, 200, 0)
    assert frame.getpixel((PANEL_W - 3, 16)) == (0, 200, 0)


def test_headline_flaps_before_it_settles():
    r = _Renderer()
    assert r._flap_headline("GRAND SLAM", 0.0) != "GRAND SLAM"
    assert r._flap_headline("GRAND SLAM", 5.0) == "GRAND SLAM"
    # Spaces and punctuation never scramble, so the shape stays put.
    assert r._flap_headline("2-PT CONVERSION", 0.5)[1] == '-'


def test_flap_is_deterministic_for_a_given_moment():
    r = _Renderer()
    assert r._flap_headline("HAT TRICK", 0.6) == r._flap_headline("HAT TRICK", 0.6)


def test_big_plays_hold_longer():
    assert score_alert_duration(alert(big=True)) > score_alert_duration(alert(big=False))


def test_missing_fields_do_not_raise():
    _Renderer().draw_score_alert({"headline": "GOAL"}, 1.0)
