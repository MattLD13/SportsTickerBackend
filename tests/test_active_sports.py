"""Per-ticker league switches: two boards can follow different sports."""

import pytest

from sports_ticker.core import (
    create_ticker_record, effective_active_sports, set_ticker_active_sports,
    state, tickers, union_active_sports,
)


def test_ticker_leagues_fall_back_to_global(clean_state):
    """A ticker only overrides the leagues it disagrees about."""
    state['active_sports'].update({'nhl': True, 'nba': False, 'mlb': True})
    rec = create_ticker_record()
    rec['active_sports'] = {'nhl': False, 'nba': True}

    effective = effective_active_sports(rec)

    cases = [('nhl', False), ('nba', True), ('mlb', True)]
    for league, expected in cases:
        assert effective[league] is expected, league
    # No override at all means the global map, whole.
    assert effective_active_sports(create_ticker_record())['nhl'] is True


def test_only_disagreements_are_stored(clean_state):
    """A league that matches the global value is dropped, so a later global
    change still reaches the ticker."""
    state['active_sports'].update({'nhl': True, 'nba': False})
    rec = create_ticker_record()

    set_ticker_active_sports(rec, {'nhl': True, 'nba': True})
    assert rec['active_sports'] == {'nba': True}

    # Agreeing about everything means following the global map again.
    set_ticker_active_sports(rec, {'nba': False})
    assert rec['active_sports'] is None


def test_fetch_union_covers_every_board(clean_state):
    """One board wanting a league is enough to fetch it, and no board can
    switch a league off for the fleet."""
    state['active_sports'].update({'nhl': True, 'nba': False, 'mlb': False})
    tickers['a'] = create_ticker_record()
    tickers['a']['active_sports'] = {'nba': True, 'nhl': False}
    tickers['b'] = create_ticker_record()

    union = union_active_sports()

    cases = [('nba', True), ('nhl', True), ('mlb', False)]
    for league, expected in cases:
        assert union[league] is expected, league


def test_data_filters_leagues_per_ticker(client, monkeypatch):
    """Two boards asking at once each get only their own leagues."""
    import sports_ticker.routes.state as route_state

    state['active_sports'].update({'nhl': True, 'nba': True})
    for tid, override in (('board_nhl', {'nba': False}), ('board_nba', {'nhl': False})):
        tickers[tid] = create_ticker_record(client_id=tid)
        tickers[tid]['active_sports'] = override

    games = [
        {'type': 'scoreboard', 'sport': 'nhl', 'id': '1', 'status': 'P1'},
        {'type': 'scoreboard', 'sport': 'nba', 'id': '2', 'status': 'Q1'},
    ]
    monkeypatch.setattr(route_state.fetcher, 'get_mode_snapshot', lambda m, d=0: games)

    for tid, expected in (('board_nhl', ['nhl']), ('board_nba', ['nba'])):
        payload = client.get(f"/data?id={tid}").get_json()
        assert [g['sport'] for g in payload['content']['sports']] == expected, tid


def test_config_targets_one_ticker(client):
    """A targeted league change leaves the global map and other boards alone."""
    tid = 'league_config_ticker'
    tickers[tid] = create_ticker_record(client_id='owner')
    state['active_sports']['nhl'] = True

    response = client.post('/api/config',
                           json={'ticker_id': tid, 'active_sports': {'nhl': False}},
                           headers={'X-Client-ID': 'owner'})

    assert response.status_code == 200
    assert tickers[tid]['active_sports'] == {'nhl': False}
    assert state['active_sports']['nhl'] is True
