"""Prove shared Fastcast versions, bounded wire batches, and isolated ticker alerts."""

from copy import deepcopy
from datetime import datetime, timezone
import json

import pytest

from sports_ticker.domain import DisplaySettings
from sports_ticker.providers.espn import EspnScoreboardProvider
from sports_ticker.providers.espn_fastcast import EspnFastcastSource

pytestmark = pytest.mark.critical
LEAGUE = 'ncf_fbs'
TOPIC = 'scoreboard-football-college-football-80'


class ControlledSource(EspnFastcastSource):
    def start(self):
        """Accept explicit wire input without opening an internet connection."""


class Client:
    def __init__(self, games=150):
        self.calls = []
        self.payload = {'events': [
            {'id': str(index), 'date': '2026-10-26T17:00:00Z',
             'status': {'type': {'state': 'pre', 'shortDetail': 'Scheduled'}},
             'competitions': [{'competitors': [
                 {'homeAway': side, 'score': '0', 'team': {'id': f'{index}-{side}', 'abbreviation': f'{side}{index}',
                    'conferenceId': '4' if index % 2 == 0 else '8'}} for side in ('home', 'away')]}]}
            for index in range(games)]}

    def get_json(self, url, *, timeout):
        self.calls.append(url)
        if '/rankings' in url:
            return {'data': []}
        if '/schools-index' in url:
            return []
        if '/scoreboard' in url:
            return deepcopy(self.payload)
        raise AssertionError(f'Unexpected HTTP read: {url}')


def create(games=150):
    client = Client(games)
    source = ControlledSource({LEAGUE: TOPIC})
    provider = EspnScoreboardProvider({LEAGUE: 'https://controlled.invalid/football/college-football/scoreboard?groups=80'},
        client=client, fastcast=source, now=lambda: datetime(2026, 10, 26, 12, tzinfo=timezone.utc), monotonic=lambda: 1.0)
    return provider, source, client


def update(source, score, games=150):
    operations = [{'op': 'replace', 'path': f'/events/{index}/competitions/0/competitors/0/score', 'value': str(score)}
                  for index in range(games)]
    source._handle_wire_message(json.dumps({'op': 'P', 'tc': TOPIC, 'mid': score, 'pl': json.dumps(operations)}))


def settings(**values):
    return DisplaySettings(active_sports={LEAGUE: True}, timezone='UTC', **values)


def test_150_game_batch_encodes_shared_content_once_and_reprojects_only_changed_games(monkeypatch):
    provider, source, client = create()
    selected = {f'ticker-{index}': settings(score_alerts=bool(index % 2)) for index in range(150)}
    provider.fetch_batch_for_tickers(selected)
    calls = len(client.calls)
    projected = []
    projector_type = type(provider._display)
    original = projector_type.project

    def project(self, item, event, **values):
        projected.append(item.id)
        return original(self, item, event, **values)

    monkeypatch.setattr(projector_type, 'project', project)
    update(source, 7)
    results = provider.fetch_batch_for_tickers(selected, live_only=True)
    assert len(projected) == 150
    assert len(client.calls) == calls
    assert all(len(value.content) == 150 for value in results.values())
    assert results['ticker-0'].content[0] is results['ticker-149'].content[0]
    projected.clear()
    update(source, 8, games=1)
    next_results = provider.fetch_batch_for_tickers(selected, live_only=True)
    assert projected == ['0']
    assert next_results['ticker-0'].content[1] is results['ticker-0'].content[1]
    assert len(client.calls) == calls


def test_batch_captures_one_version_and_keeps_conference_filters_separate(monkeypatch):
    provider, source, client = create(4)
    selected = {'all': settings(), 'filtered': settings(active_conferences={'ncf_fbs:4': False})}
    provider.fetch_batch_for_tickers(selected)
    update(source, 7, games=4)
    original = provider._result_from_source
    injected = []

    def result(*args):
        if not injected:
            injected.append(True)
            update(source, 8, games=4)
        return original(*args)

    monkeypatch.setattr(provider, '_result_from_source', result)
    results = provider.fetch_batch_for_tickers(selected, live_only=True)
    assert {item.data['home_score'] for value in results.values() for item in value.content} == {'7'}
    assert {item.id for item in results['filtered'].content} == {'1', '3'}
    assert {item.id for item in results['all'].content} == {'0', '1', '2', '3'}
    next_results = provider.fetch_batch_for_tickers(selected, live_only=True)
    assert {item.data['home_score'] for value in next_results.values() for item in value.content} == {'8'}


def test_shared_batch_keeps_existing_new_and_muted_alert_histories_separate():
    provider, source, client = create(1)
    followed = {'my_teams': ('ncf_fbs:home0',)}
    provider.fetch_batch_for_tickers({'existing': settings(**followed)})
    source._handle_wire_message(json.dumps({'op': 'P', 'tc': TOPIC, 'mid': 1, 'pl': json.dumps([
        {'op': 'replace', 'path': '/events/0/competitions/0/competitors/0/score', 'value': '7'},
        {'op': 'replace', 'path': '/events/0/status/type/state', 'value': 'in'},
    ])}))
    results = provider.fetch_batch_for_tickers({'existing': settings(**followed), 'new': settings(**followed),
                                               'muted': settings(score_alerts=False, **followed)}, live_only=True)
    assert results['existing'].alerts
    assert not results['new'].alerts
    assert not results['muted'].alerts
    assert results['existing'].content[0] is results['new'].content[0]
