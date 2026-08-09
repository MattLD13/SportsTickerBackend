"""Fleet health: what a board reports, and why a dark board is dark."""

import time

from sports_ticker.core import create_ticker_record, tickers
from sports_ticker.services import telemetry


def test_poll_headers_become_telemetry(client):
    """A board's own facts ride in on the poll it already makes."""
    tid = 'health_ticker'
    tickers[tid] = create_ticker_record(client_id=tid)

    client.get(f"/data?id={tid}", headers={
        'X-Ticker-Uptime': '3600',
        'X-Ticker-Temp': '48.5',
        'X-Ticker-Build': 'r412+abc1234',
    })

    reported = tickers[tid]['telemetry']
    assert (reported['uptime'], reported['temp_c'], reported['build']) == (3600.0, 48.5, 'r412+abc1234')

    # A later poll without headers keeps the last reading rather than clearing it.
    client.get(f"/data?id={tid}")
    assert tickers[tid]['telemetry']['build'] == 'r412+abc1234'


def test_link_state_follows_last_poll(clean_state):
    """How long ago a board last asked for content decides its link state."""
    now = time.time()
    cases = [(1, 'online'), (60, 'stale'), (3600, 'offline')]
    for ago, expected in cases:
        rec = create_ticker_record(client_id='c')
        rec['last_seen'] = now - ago
        assert telemetry.ticker_health('t', rec, now)['link'] == expected, ago


def test_dark_board_names_its_reason(clean_state):
    """Each way of showing nothing reports which gate is holding the panel."""
    now = time.time()

    unpaired = create_ticker_record(paired=False)
    unpaired['last_seen'] = now
    assert 'not paired' in telemetry.ticker_health('t', unpaired, now)['dark_reason']

    asleep = create_ticker_record(client_id='c')
    asleep['last_seen'] = now
    asleep['settings']['brightness'] = 0
    assert 'asleep' in telemetry.ticker_health('t', asleep, now)['dark_reason']

    gone = create_ticker_record(client_id='c')
    gone['last_seen'] = now - 3600
    assert 'offline screen' in telemetry.ticker_health('t', gone, now)['dark_reason']

    # A board that is polling, paired and lit has nothing to explain.
    live = create_ticker_record(client_id='c')
    live['last_seen'] = now
    assert telemetry.ticker_health('t', live, now)['dark_reason'] is None


def test_health_endpoint_reports_the_fleet(client):
    """/api/health answers with the server process and every board."""
    tickers['fleet_a'] = create_ticker_record('Kitchen', client_id='a')
    tickers['fleet_a']['last_seen'] = time.time()

    payload = client.get('/api/health').get_json()

    assert payload['status'] == 'ok'
    assert payload['online'] == 1
    assert [b['name'] for b in payload['tickers']] == ['Kitchen']
    assert 'threads' in payload['server']

    assert client.get('/api/health?id=missing').status_code == 404
