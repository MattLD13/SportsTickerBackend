from sports_ticker.core import tickers, create_ticker_record
from sports_ticker.fetchers.transactions import _acting_team, _shorten
from sports_ticker.services.news_alerts import (
    NewsAlertTracker, build_item, news_alerts, pick_team_color,
)

MLB_NAMES = {'detroit tigers': 'DET', 'san diego padres': 'SD',
             'chicago white sox': 'CWS', 'chicago cubs': 'CHC'}

TRADE = {'kind': 'TRADE', 'sport': 'nhl', 'from': 'VAN', 'to': 'NYR',
         'text': 'J.T. Miller for Kakko and a 2027 first'}


def _ticker(tid, mode, teams):
    tickers[tid] = create_ticker_record('Board', client_id=f'c_{tid}')
    tickers[tid]['my_teams'] = teams
    tickers[tid]['settings']['mode'] = mode
    return tid


def test_an_item_is_stored_once():
    t = NewsAlertTracker()
    item = build_item('TRADE', 'A for B', sport='nhl', from_abbr='VAN', to_abbr='NYR')
    assert t.add(item) is not None
    assert t.add(item) is None          # same id, already seen
    assert len(t.recent()) == 1


def test_trade_direction_comes_from_the_sentence():
    """One trade writes a row per player and the rows run both ways.

    Mize leaves Detroit on one row and Mayfield arrives on another, so row
    order points the arrow against the detail printed under it half the time.
    """
    desc = ("Detroit Tigers traded RHP Casey Mize and 3B Gage Workman to "
            "San Diego Padres for LHP Kash Mayfield.")
    assert _acting_team(desc, MLB_NAMES) == 'DET'
    # Longest name first, so "Chicago White Sox" is not read as "Chicago Cubs".
    assert _acting_team("Chicago White Sox traded X to Detroit Tigers.", MLB_NAMES) == 'CWS'
    assert _acting_team('Something else happened.', MLB_NAMES) == ''


def test_shorten_drops_the_verb_and_the_club_names():
    desc = ("Detroit Tigers traded RHP Casey Mize and 3B Gage Workman to "
            "San Diego Padres for LHP Kash Mayfield.")
    out = _shorten(desc, 'Casey Mize', ('detroit tigers', 'san diego padres'))
    assert out == "RHP Casey Mize and 3B Gage Workman for LHP Kash Mayfield"


def test_push_then_serve_to_a_following_board(client):
    news_alerts.clear()
    tid = _ticker('news_a', 'my_teams', ['nhl:NYR'])

    res = client.post('/api/news', json=TRADE).get_json()
    assert res['status'] == 'ok'
    assert tid in res['tickers_following']

    news = client.get(f'/data?id={tid}').get_json()['news']
    assert len(news) == 1
    assert (news[0]['from_abbr'], news[0]['to_abbr']) == ('VAN', 'NYR')


def test_each_domain_stays_in_its_own_mode(client):
    news_alerts.clear()
    client.post('/api/news', json=TRADE)
    client.post('/api/news', json={'domain': 'stocks', 'symbol': 'NVDA',
                                   'text': 'Nvidia beats on earnings'})
    for mode, expect_kind in (('my_teams', 'TRADE'), ('stocks', 'NEWS'), ('weather', None)):
        tid = _ticker(f'news_{mode}', mode, ['nhl:NYR'])
        news = client.get(f'/data?id={tid}').get_json()['news']
        assert [n['kind'] for n in news] == ([expect_kind] if expect_kind else [])


def test_an_unfollowed_club_is_not_served(client):
    news_alerts.clear()
    tid = _ticker('news_b', 'my_teams', ['mlb:STL'])
    client.post('/api/news', json=TRADE)
    assert client.get(f'/data?id={tid}').get_json()['news'] == []


def test_a_bad_body_is_rejected_with_a_reason(client):
    for body, missing in (
        ({'kind': 'TRADE', 'to': 'NYR'}, 'text'),
        ({'text': 'x', 'kind': 'TRADE'}, 'to'),
        ({'text': 'x', 'domain': 'stocks'}, 'symbol'),
    ):
        res = client.post('/api/news', json=body)
        assert res.status_code == 400
        assert missing in res.get_json()['message']


def test_pick_team_color_never_returns_black():
    # The banner lifts a dark colour by scaling its channels, and scaling black
    # leaves black. Pittsburgh's primary is black, so the gold has to win.
    assert pick_team_color({'color': 'C41E3A', 'alt_color': '0C2340'}) == '#C41E3A'
    assert pick_team_color({'color': '000000', 'alt_color': 'FDB827'}) == '#FDB827'
    assert pick_team_color({}) == '#8B93A3'


def test_nfl_trade_parsing():
    """ESPN gives the acting club as data and the rest as English.

    The other club is safe to read only because names are a closed set of 32,
    so this is a lookup rather than a guess.
    """
    from sports_ticker.fetchers.transactions import _counterparty, _nfl_text
    needles = sorted(
        [('pittsburgh steelers', 'PIT'), ('pittsburgh', 'PIT'), ('steelers', 'PIT'),
         ('philadelphia eagles', 'PHI'), ('philadelphia', 'PHI'), ('eagles', 'PHI'),
         ('new england patriots', 'NE'), ('new england', 'NE')],
        key=lambda n: len(n[0]), reverse=True)

    desc = "Traded S Kyle Dugger to the Pittsburgh Steelers. Signed S John Saunders Jr."
    assert _counterparty(desc, needles, 'NE') == 'PIT'
    # Only the first sentence is the trade; the signing is a separate move.
    assert _nfl_text(desc) == 'S Kyle Dugger'
    # The acting club never matches itself.
    assert _counterparty("Traded RB Tank Bigsby to Philadelphia", needles, 'PHI') == ''
