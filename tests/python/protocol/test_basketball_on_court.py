"""Verify basketball lineups from provider flags through the V2 client boundary."""

from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path

import pytest

from sports_ticker.application.state_store import SnapshotStore
from sports_ticker.domain import ContentItem, DisplaySettings, TickerSnapshot
from sports_ticker.providers.espn import EspnScoreboardProvider
from sports_ticker.providers.sports_display import basketball_on_court, project_sports_display
from sports_ticker.projections.data_api import project_data_v2
from ticker_core.protocol.model import TickerResponse


pytestmark = pytest.mark.critical
FIXTURE = Path(__file__).parents[2] / 'fixtures/display/basketball_on_court_espn.json'


@pytest.fixture
def summary():
    """Replay public ESPN game 401809234 from October 22, 2025."""
    return json.loads(FIXTURE.read_text(encoding='utf-8'))


def _item(sport='nba'):
    return ContentItem('401809234', 'sports', 'scoreboard', True, {
        'sport': sport, 'state': 'in', 'status': 'Q4 0:15',
        'away_abbr': 'CLE', 'home_abbr': 'NY', 'away_score': 111, 'home_score': 119,
        'situation': {},
    })


def test_explicit_active_flags_select_current_players_and_source_sides(summary):
    result = basketball_on_court(summary)
    assert {p['name'] for p in result['away']} == {
        'Evan Mobley', 'Donovan Mitchell', 'Dean Wade', 'Lonzo Ball', 'Tyrese Proctor',
    }
    assert {p['name'] for p in result['home']} == {
        'OG Anunoby', 'Mikal Bridges', 'Jalen Brunson', 'Landry Shamet', 'Miles McBride',
    }
    assert next(p for p in result['away'] if p['name'] == 'Donovan Mitchell') == {
        'id': '3908809', 'name': 'Donovan Mitchell', 'jerseyNumber': '45', 'position': 'G',
    }
    rows = summary['boxscore']['players'][0]['statistics'][0]['athletes']
    rows[0]['active'] = True
    rows[1]['active'] = False
    assert 'Jarrett Allen' in {p['name'] for p in basketball_on_court(summary)['away']}
    assert 'Evan Mobley' not in {p['name'] for p in basketball_on_court(summary)['away']}


def test_lineups_preserve_double_zero_and_do_not_invent_positions(summary):
    active = next(r for r in summary['boxscore']['players'][0]['statistics'][0]['athletes'] if r['active'])
    active['athlete'].update(jersey='00', position={})
    result = basketball_on_court(summary)
    player = next(p for p in result['away'] if p['id'] == active['athlete']['id'])
    assert player['jerseyNumber'] == '00'
    assert player['position'] == ''


def test_missing_flags_and_conflicting_lineups_are_unavailable(summary):
    rows = summary['boxscore']['players'][0]['statistics'][0]['athletes']
    rows[0]['active'] = True
    assert basketball_on_court(summary)['away'] == []
    for row in rows:
        row.pop('active', None)
    assert basketball_on_court(summary)['away'] == []
    assert basketball_on_court({}) == {'away': [], 'home': []}
    summary['header'] = {}
    assert basketball_on_court(summary) == {'away': [], 'home': []}


@pytest.mark.parametrize('sport', ['nba', 'march_madness'])
def test_live_enrichment_replaces_lineups_and_clears_missing_flags(summary, sport):
    provider = EspnScoreboardProvider({sport: 'https://example.test/basketball/nba/scoreboard'})
    enriched = provider._enrich_live_item(sport, _item(sport), update=summary)
    assert enriched.data['situation']['basketballOnCourt'] == {side: tuple(players) for side, players in basketball_on_court(summary).items()}
    cleared = provider._enrich_live_item(sport, enriched, update={})
    assert cleared.data['situation']['basketballOnCourt'] == {'away': (), 'home': ()}


@pytest.mark.parametrize('state,status', [('pre', '7:00 PM'), ('post', 'Final'), ('in', 'Halftime'), ('in', 'Q1 END')])
def test_non_playing_phases_remove_current_lineups(summary, state, status):
    data = dict(_item().data)
    data.update(state=state, status=status, situation={'basketballOnCourt': basketball_on_court(summary)})
    assert 'basketballOnCourt' not in project_sports_display(data)['situation']


def test_snapshot_v2_projection_and_client_keep_lineup_records(summary):
    provider = EspnScoreboardProvider({'nba': 'https://example.test/basketball/nba/scoreboard'})
    enriched = provider._enrich_live_item('nba', _item(), update=summary)
    store = SnapshotStore()
    settings = DisplaySettings(sports_presentation='pinned', pinned_content_id=enriched.id)
    store.replace(TickerSnapshot('test-lineup', 0, datetime(2025, 10, 23, tzinfo=timezone.utc),
                                (enriched,), (), (), settings))
    original = deepcopy(summary)
    summary['boxscore']['players'].clear()
    document = project_data_v2(store.get('test-lineup'), {}, {})
    client = TickerResponse.from_payload(document)
    players = client.content[0].data['situation']['basketballOnCourt']
    assert len(players['away']) == len(players['home']) == 5
    assert {p['name'] for p in players['away']} == {p['name'] for p in basketball_on_court(original)['away']}


@pytest.mark.parametrize('count', [1, 5])
@pytest.mark.parametrize('use_fastcast', [False, True])
def test_provider_reads_lineups_during_dense_and_fastcast_refreshes(summary, count, use_fastcast):
    tick = [0.0]
    event = {'id': '401809234', 'date': '2025-10-23T00:00:00Z',
             'status': {'type': {'state': 'in', 'shortDetail': '4th Quarter'}, 'period': 4, 'displayClock': '0:15'},
             'competitions': [{'competitors': [
                 {'homeAway': 'away', 'team': {'id': '5', 'abbreviation': 'CLE'}, 'score': '111'},
                 {'homeAway': 'home', 'team': {'id': '18', 'abbreviation': 'NY'}, 'score': '119'},
             ]}]}
    events = [{**deepcopy(event), 'id': str(401809234 + index)} for index in range(count)]

    class Client:
        def __init__(self):
            self.urls = []

        def get_json(self, url, *, timeout):
            self.urls.append(url)
            return deepcopy(summary) if '/summary?' in url else {'events': deepcopy(events)}

    class Fastcast:
        def start(self):
            pass

        def active(self, league):
            return True

        def prime(self, league, payload):
            pass

        def snapshot(self, league):
            return {'events': deepcopy(events)}

        def event_updated_at(self, league, event_id):
            return tick[0]

        def prime_event(self, league, event, *, if_updated_at=None):
            pass

    client = Client()
    provider = EspnScoreboardProvider(
        {'nba': 'https://example.test/basketball/nba/scoreboard'}, client=client,
        fastcast=Fastcast() if use_fastcast else None,
        now=lambda: datetime(2025, 10, 23, 0, 0, 15, tzinfo=timezone.utc), monotonic=lambda: tick[0])
    settings = DisplaySettings(active_sports={'nba': True}, timezone='UTC')
    first = provider.fetch_for_ticker('lineup-one', settings)
    assert len(first.content) == count
    assert all(len(item.data['situation']['basketballOnCourt']['away']) == 5 for item in first.content)
    assert sum('/summary?' in url for url in client.urls) == count
    provider.fetch_for_ticker('lineup-two', settings)
    assert sum('/summary?' in url for url in client.urls) == count
    rows = summary['boxscore']['players'][0]['statistics'][0]['athletes']
    rows[0]['active'], rows[1]['active'] = True, False
    tick[0] = 6.0
    second = provider.fetch_for_ticker('lineup-one', settings)
    assert all('Jarrett Allen' in {p['name'] for p in item.data['situation']['basketballOnCourt']['away']}
               for item in second.content)
    assert sum('/summary?' in url for url in client.urls) == count * 2
