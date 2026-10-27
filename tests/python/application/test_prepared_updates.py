"""Test producer-side preparation and unchanged game identity across deltas."""

from copy import deepcopy
import json
from pathlib import Path
from queue import Empty
from threading import Event, Thread

import pytest

from ticker_core.app.poller import PollSucceeded
from ticker_core.app.updates import PreparedEventQueue, PreparedUpdate
from ticker_core.protocol import TickerResponse, display_delta

pytestmark = pytest.mark.critical


class Cache:
    def __init__(self, fail=False):
        self.fail = fail
        self.payloads = []

    def store(self, value):
        if self.fail:
            raise OSError('cache unavailable')
        self.payloads.append(value)


class Assets:
    def __init__(self, fail=False):
        self.fail = fail

    def prefetch_payload(self, value):
        if self.fail:
            raise OSError('assets unavailable')


def response():
    payload = json.loads(Path('tests/fixtures/display/v2_render_snapshot.json').read_text())
    original = payload['content']['sports'][0]
    payload['content'] = {'sports': [{**deepcopy(original), 'id': f'game-{index}'} for index in range(150)]}
    return payload


def test_consecutive_deltas_retain_unchanged_games_even_when_auxiliary_services_fail():
    payload = response()
    initial = TickerResponse.from_payload(payload)
    first = deepcopy(payload)
    first['content']['sports'][149]['data']['home_score'] = '21'
    updated = TickerResponse.from_payload(first)
    second = deepcopy(first)
    second['content']['sports'][148]['data']['home_score'] = '24'
    latest = TickerResponse.from_payload(second)
    queue = PreparedEventQueue(cache=Cache(fail=True), assets=Assets(fail=True))
    queue.put(PollSucceeded(initial))
    a = queue.get_nowait()
    assert isinstance(a, PreparedUpdate)
    assert {name for name, _ in a.issues} == {'content_cache', 'asset_prefetch'}
    queue.put(PollSucceeded(display_delta(initial, updated)))
    b = queue.get_nowait()
    queue.put(PollSucceeded(display_delta(updated, latest)))
    c = queue.get_nowait()
    assert b.changed_ids == {'game-149'}
    assert c.changed_ids == {'game-148'}
    assert c.response.content[149].data['home_score'] == '21'
    assert c.response.content[148].data['home_score'] == '24'
    assert a.content[0] is b.content[0] is c.content[0]
    assert b.content[149] is c.content[149]
    assert c.content[148] is not b.content[148]


def test_slow_producer_preparation_does_not_block_the_drawing_queue():
    started, release = Event(), Event()

    class SlowAssets:
        def prefetch_payload(self, value):
            started.set()
            assert release.wait(5)

    queue = PreparedEventQueue(cache=Cache(), assets=SlowAssets())
    producer = Thread(target=queue.put, args=(PollSucceeded(TickerResponse.from_payload(response())),))
    try:
        producer.start()
        assert started.wait(2)
        with pytest.raises(Empty):
            queue.get_nowait()
        release.set()
        producer.join(timeout=2)
        assert not producer.is_alive()
        assert isinstance(queue.get_nowait(), PreparedUpdate)
    finally:
        release.set()
        producer.join(timeout=2)
