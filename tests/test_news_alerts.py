import time

import pytest

from sports_ticker.core import tickers, state, create_ticker_record
from sports_ticker.fetchers.transactions import _acting_team, _shorten
from sports_ticker.services.news_alerts import (
    SPORTS, STOCKS, NewsAlertTracker, build_item, make_id, news_alerts,
)


# ── item store ───────────────────────────────────────────────────────────────

def test_an_item_is_stored_once():
    t = NewsAlertTracker()
    item = build_item('TRADE', 'A for B', sport='nhl', from_abbr='VAN', to_abbr='NYR')
    assert t.add(item) is not None
    assert t.add(item) is None          # same id, already seen
    assert len(t.recent()) == 1


def test_ids_are_stable_for_the_same_trade():
    a = make_id('mlb', '2026-07-29', 'Tigers traded Mize')
    b = make_id('mlb', '2026-07-29', 'Tigers traded Mize')
    assert a == b
    assert a != make_id('mlb', '2026-07-30', 'Tigers traded Mize')


def test_recent_filters_by_domain():
    t = NewsAlertTracker()
    t.add(build_item('TRADE', 'a trade', domain=SPORTS, to_abbr='NYR'))
    t.add(build_item('NEWS', 'a headline', domain=STOCKS, to_abbr='NVDA'))
    assert len(t.recent(domain=SPORTS)) == 1
    assert len(t.recent(domain=STOCKS)) == 1
    assert len(t.recent()) == 2


def test_recent_respects_the_live_delay():
    t = NewsAlertTracker()
    item = t.add(build_item('TRADE', 'a trade', to_abbr='NYR'))
    item['ts'] = time.time() - 10
    t._items[0]['ts'] = item['ts']
    assert t.recent(delay=45) == []           # not due yet
    t._items[0]['ts'] = time.time() - 60
    assert len(t.recent(delay=45)) == 1       # now due


def test_both_clubs_go_in_the_team_filter():
    # A board following either club wants the trade.
    item = build_item('TRADE', 'x', sport='nhl', from_abbr='VAN', to_abbr='NYR',
                      teams=['VAN', 'NYR'])
    assert item['teams'] == ['VAN', 'NYR']


# ── MLB feed handling ────────────────────────────────────────────────────────

MLB_NAMES = {'detroit tigers': 'DET', 'san diego padres': 'SD',
             'chicago white sox': 'CWS', 'chicago cubs': 'CHC'}


def test_acting_team_comes_from_the_start_of_the_sentence():
    # Direction cannot be read from the rows: one trade writes a row per player
    # and they run both ways.
    desc = ("Detroit Tigers traded RHP Casey Mize and 3B Gage Workman to "
            "San Diego Padres for LHP Kash Mayfield.")
    assert _acting_team(desc, MLB_NAMES) == 'DET'


def test_acting_team_prefers_the_longest_club_name():
    # "Chicago White Sox" must not match as "Chicago Cubs" or vice versa.
    desc = "Chicago White Sox traded RHP Someone to Detroit Tigers for cash."
    assert _acting_team(desc, MLB_NAMES) == 'CWS'


def test_acting_team_is_empty_when_no_club_leads():
    assert _acting_team('Something else entirely happened.', MLB_NAMES) == ''


def test_shorten_drops_the_verb_and_the_club_names():
    desc = ("Detroit Tigers traded RHP Casey Mize and 3B Gage Workman to "
            "San Diego Padres for LHP Kash Mayfield.")
    out = _shorten(desc, 'Casey Mize', ('detroit tigers', 'san diego padres'))
    assert out == "RHP Casey Mize and 3B Gage Workman for LHP Kash Mayfield"
    assert 'Padres' not in out          # already in the header
    assert 'traded' not in out


def test_shorten_falls_back_to_the_player():
    assert _shorten('', 'Casey Mize') == 'Casey Mize'


# ── push route ───────────────────────────────────────────────────────────────

def _ticker(tid, mode, teams):
    tickers[tid] = create_ticker_record('Board', client_id=f'c_{tid}')
    tickers[tid]['my_teams'] = teams
    tickers[tid]['settings']['mode'] = mode
    return tid


def test_push_then_serve_to_a_following_board(client):
    news_alerts.clear()
    tid = _ticker('news_a', 'my_teams', ['nhl:NYR'])

    res = client.post('/api/news', json={
        'kind': 'TRADE', 'sport': 'nhl', 'from': 'VAN', 'to': 'NYR',
        'text': 'J.T. Miller for Kakko and a 2027 first',
    })
    assert res.status_code == 200
    assert res.get_json()['status'] == 'ok'
    assert tid in res.get_json()['tickers_following']

    news = client.get(f'/data?id={tid}').get_json()['news']
    assert len(news) == 1
    assert news[0]['from_abbr'] == 'VAN'
    assert news[0]['to_abbr'] == 'NYR'


def test_a_trade_never_shows_in_stocks_mode(client):
    news_alerts.clear()
    tid = _ticker('news_b', 'stocks', ['nhl:NYR'])
    client.post('/api/news', json={'kind': 'TRADE', 'sport': 'nhl',
                                   'from': 'VAN', 'to': 'NYR', 'text': 'x'})
    assert client.get(f'/data?id={tid}').get_json()['news'] == []


def test_stock_news_never_shows_in_a_sports_mode(client):
    news_alerts.clear()
    tid = _ticker('news_c', 'my_teams', ['nhl:NYR'])
    client.post('/api/news', json={'domain': 'stocks', 'symbol': 'NVDA',
                                   'text': 'Nvidia beats on earnings'})
    assert client.get(f'/data?id={tid}').get_json()['news'] == []


def test_non_sports_modes_get_nothing(client):
    news_alerts.clear()
    tid = _ticker('news_d', 'weather', ['nhl:NYR'])
    client.post('/api/news', json={'kind': 'TRADE', 'sport': 'nhl',
                                   'from': 'VAN', 'to': 'NYR', 'text': 'x'})
    assert client.get(f'/data?id={tid}').get_json()['news'] == []


def test_an_unfollowed_club_is_not_served(client):
    news_alerts.clear()
    tid = _ticker('news_e', 'my_teams', ['mlb:STL'])
    client.post('/api/news', json={'kind': 'TRADE', 'sport': 'nhl',
                                   'from': 'VAN', 'to': 'NYR', 'text': 'x'})
    assert client.get(f'/data?id={tid}').get_json()['news'] == []


def test_pushing_the_same_item_twice_is_a_duplicate(client):
    news_alerts.clear()
    _ticker('news_f', 'my_teams', ['nhl:NYR'])
    body = {'kind': 'TRADE', 'sport': 'nhl', 'from': 'VAN', 'to': 'NYR', 'text': 'same'}
    assert client.post('/api/news', json=body).get_json()['status'] == 'ok'
    assert client.post('/api/news', json=body).get_json()['status'] == 'duplicate'


@pytest.mark.parametrize("body,missing", [
    ({'kind': 'TRADE', 'to': 'NYR'}, 'text'),
    ({'text': 'x', 'kind': 'TRADE'}, 'to'),
    ({'text': 'x', 'domain': 'stocks'}, 'symbol'),
    ({'text': 'x', 'domain': 'moon', 'to': 'NYR'}, 'domain'),
])
def test_bad_bodies_are_rejected_with_a_reason(client, body, missing):
    res = client.post('/api/news', json=body)
    assert res.status_code == 400
    assert missing in res.get_json()['message']


def test_get_lists_what_is_held(client):
    news_alerts.clear()
    client.post('/api/news', json={'kind': 'SIGNS', 'sport': 'nfl', 'from': 'FA',
                                   'to': 'NYG', 'text': 'Barkley to a three-year deal'})
    listed = client.get('/api/news').get_json()['news']
    assert len(listed) == 1
    assert listed[0]['kind'] == 'SIGNS'


def test_an_unresolved_club_gets_grey_not_black(client):
    # Black is the one colour the banner cannot lift to readable.
    news_alerts.clear()
    client.post('/api/news', json={'kind': 'TRADE', 'sport': 'nhl',
                                   'from': 'ZZZ', 'to': 'QQQ', 'text': 'x'})
    item = client.get('/api/news').get_json()['news'][0]
    assert item['from_color'] != '#000000'
    assert item['to_color'] != '#000000'


@pytest.mark.parametrize("info,expected", [
    ({'color': 'C41E3A', 'alt_color': '0C2340'}, '#C41E3A'),
    # Pittsburgh's primary is black. The alternate carries the gold.
    ({'color': '000000', 'alt_color': 'FDB827'}, '#FDB827'),
    ({'color': '', 'alt_color': ''}, '#8B93A3'),
    ({}, '#8B93A3'),
    (None, '#8B93A3'),
])
def test_pick_team_color(info, expected):
    from sports_ticker.services.news_alerts import pick_team_color
    assert pick_team_color(info) == expected
