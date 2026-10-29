import json

import pytest

from ticker3.contract.templates import bundle
from ticker3.core.devices import Assets, DeviceSession
from ticker3.core.hub import App, Composition
from ticker3.core.store import Store

pytestmark = pytest.mark.critical

TEMPLATES = {"demo.card": {"id": "demo.card", "version": 1, "panels": {
    "w64h32": {"box": [64, 32], "flow": "page", "parts": [
        {"part": "text", "at": [0, 0], "font": "tiny", "value": "{score}"},
        {"part": "logo", "at": [40, 10], "size": 16, "value": "{logo}"}]}}}}
LOGO = "https://a.espncdn.com/i/teamlogos/nfl/500/scoreboard/gb.png"


def screen(identifier, **values):
    return {"id": identifier, "template": "demo.card", "values": values}


def composition(*screens):
    return Composition(tuple(screens), ())


def session():
    sent = []
    return DeviceSession("t", "w64h32", sent.append, Assets()), sent


def test_templates_go_once_and_a_change_sends_only_the_changed_value():
    device, sent = session()
    device.start(TEMPLATES, composition(screen("a/g1", score="7-0", logo=LOGO, status="Q1 9:00")), None)
    assert [message["t"] for message in sent] == ["templates", "screens"]
    asset = sent[1]["screens"][0]["values"]["logo"]
    assert len(asset) == 16 and device.assets.urls[asset] == LOGO
    sent.clear()
    device.update(TEMPLATES, composition(screen("a/g1", score="14-0", logo=LOGO, status="Q1 9:00")))
    assert sent == [{"t": "delta", "upsert": [{"id": "a/g1", "values": {"score": "14-0"}}]}]
    assert len(json.dumps(sent[0], separators=(",", ":"))) < 70
    sent.clear()
    device.update(TEMPLATES, composition(screen("a/g1", score="14-0", logo=LOGO, status="Q1 9:00")))
    assert sent == []


def test_device_with_the_current_bundle_gets_no_templates():
    device, sent = session()
    digest, _ = bundle(TEMPLATES, "w64h32")
    device.start(TEMPLATES, composition(screen("a/g1", score="1")), digest)
    assert [message["t"] for message in sent] == ["screens"]


def test_removed_values_screens_and_new_order_are_sent():
    device, sent = session()
    device.start(TEMPLATES, composition(screen("a/g1", score="1", down="3RD & 4"), screen("a/g2", score="2")), None)
    sent.clear()
    device.update(TEMPLATES, composition(screen("a/g3", score="3"), screen("a/g1", score="1")))
    [delta] = sent
    assert delta["upsert"] == [{"id": "a/g3", "template": "demo.card", "values": {"score": "3"}},
                               {"id": "a/g1", "values": {}, "unset": ["down"]}]
    assert delta["remove"] == ["a/g2"] and delta["order"] == ["a/g3", "a/g1"]


def test_store_keeps_token_hashes_pairs_once_and_keeps_playlists(tmp_path):
    now = [1000.0]
    store = Store(tmp_path / "ticker3.sqlite3", clock=lambda: now[0])
    created = store.create_ticker("Kitchen", "America/Chicago")
    assert store.ticker_for_device(created.device_token).name == "Kitchen"
    raw = (tmp_path / "ticker3.sqlite3").read_bytes() + (tmp_path / "ticker3.sqlite3-wal").read_bytes()
    assert created.device_token.encode() not in raw
    ticker_id, app_token = store.pair(created.pairing_code)
    assert ticker_id == created.ticker.id and store.pair(created.pairing_code) is None
    assert store.ticker_for_app(app_token, ticker_id).timezone == "America/Chicago"
    assert store.ticker_for_app(app_token, "000000000000") is None
    store.set_apps(ticker_id, [App("s", "sports", {"leagues": ["nfl"]}), App("c", "clock", {})])
    assert store.apps(ticker_id) == [App("s", "sports", {"leagues": ["nfl"]}), App("c", "clock", {})]
    late = store.pairing_code(ticker_id)
    now[0] += 901
    assert store.pair(late) is None


def test_core_keeps_each_worker_manifest_so_playlists_load_before_workers_connect(tmp_path):
    from ticker3.core.app import CoreApp
    from ticker3.core.hub import Hub
    from ticker3.features import weather

    store = Store(tmp_path / "ticker3.sqlite3")
    hub = Hub()
    CoreApp(hub, store, admin_token=None)
    hub.register(weather.MANIFEST)
    created = store.create_ticker("Den", "America/Denver")
    store.set_apps(created.ticker.id, [App("w", "weather", {"latitude": 39.7, "longitude": -105.0})])
    store.close()

    reopened = Store(tmp_path / "ticker3.sqlite3")
    restarted = Hub()
    for manifest in reopened.manifests():
        restarted.register(manifest)
    app = CoreApp(restarted, reopened, admin_token=None)
    app._load(created.ticker.id)
    assert restarted.wanted("weather") and restarted.composition(created.ticker.id).errors == ()
