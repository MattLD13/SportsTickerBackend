"""Keep racing and golf card palettes in the shared app projection."""
from datetime import datetime, timezone

import pytest

from sports_ticker.domain import ContentItem, DisplaySettings, TickerSnapshot
from sports_ticker.projections.data_api import project_data_v2


@pytest.mark.parametrize('sport,family,colors', [
    ('f1', 'racing', ('#E10600', '#3459A6')),
    ('indycar', 'racing', ('#006CB7', '#E54150')),
    ('nascar', 'racing', ('#2455A4', '#EAB83B')),
    ('wec', 'racing', ('#007EA8', '#7652B9')),
    ('imsa', 'racing', ('#D72638', '#1464A5')),
    ('golf', 'golf', ('#16875D', '#3F80A4')),
])
def test_series_has_two_app_colors(sport, family, colors):
    item = ContentItem(id=sport, family=family, kind=sport, data={'sport': sport, 'state': 'pre'})
    snap = TickerSnapshot('ticker', 1, datetime.now(timezone.utc), (item,), (), (), DisplaySettings())
    result = project_data_v2(snap, {}, {})['content'][family][0]['data']
    assert (result['away_color'], result['home_color']) == colors


def test_masters_colors_and_supplied_colors():
    item = ContentItem(id='masters', family='golf', kind='golf', data={'sport': 'golf', 'golf': {'brand': 'masters'}, 'away_color': '#123456'})
    snap = TickerSnapshot('ticker', 1, datetime.now(timezone.utc), (item,), (), (), DisplaySettings())
    result = project_data_v2(snap, {}, {})['content']['golf'][0]['data']
    assert result['away_color'] == '#123456'
    assert result['home_color'] == '#D1A735'
