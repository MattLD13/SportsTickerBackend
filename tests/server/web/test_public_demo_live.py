"""Check public live feeds and smooth production-rendered animation chunks."""

from datetime import datetime, timedelta, timezone
from io import BytesIO
from threading import Event
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest
from PIL import Image

from ticker.shared.domain import ContentItem
from ticker.server.providers.contracts import ProviderHealth, ProviderResult
from ticker.server.offline import create_offline_application
from ticker.server.web.live_demo import PublicDemoData
from ticker.server.web.preview import layout_case

pytestmark = pytest.mark.critical


def stock(symbol, group="stock_tech_ai"):
    return ContentItem(id=f"stock:{symbol}", family="stock", kind="stock", data={
        "type": "stock_ticker", "sport": "stock", "market_group": group,
        "home_abbr": symbol, "home_score": "123.45", "away_score": "+1.25%",
        "home_logo": f"https://financialmodelingprep.com/image-stock/{symbol}.png",
        "situation": {"change": "+1.52"},
    })


def test_public_stock_refresh_is_shared_and_does_not_use_saved_apple_sample():
    started, release = Event(), Event()
    calls = []

    def fetch(settings):
        calls.append(settings)
        started.set()
        assert release.wait(3)
        return ProviderResult(content=(stock("MSFT"), stock("NVDA"), stock("JPM", "stock_finance")))

    source = PublicDemoData({"stock": SimpleNamespace(fetch=fetch)})
    try:
        source.content("stock")
        assert started.wait(3)
        for _ in range(50):
            assert source.content("stock") == ({"stock": []}, "unavailable")
        release.set()
    finally:
        release.set()
        source.close()
    content, state = source.content("stock")
    assert len(calls) == 1
    assert state == "live"
    assert [row["data"]["home_abbr"] for row in content["stock"]] == ["MSFT", "NVDA"]
    assert content["stock"][0]["data"]["situation"] == {"change": "+1.52"}
    assert all(row["data"]["home_logo"] for row in content["stock"])


def test_public_ewr_board_selects_a_real_arrival_without_personal_settings():
    calls = []
    board = ContentItem(id="airport:EWR", family="airports", kind="flight_airport_hud", data={
        "type": "flight_airport_hud", "weather": {"icao": "KEWR"},
        "arrivals": [{"flight_number": "OLD1", "actual_timestamp": 123},
                     {"flight_number": "UA123", "is_live": True, "origin_iata": "SFO"}],
    })

    def fetch(settings):
        calls.append(settings)
        if not settings.track_flight_id:
            return ProviderResult(content=(board,))
        assert settings.track_flight_id == "UA123"
        return ProviderResult(content=(ContentItem(id="UA123", family="flights", kind="flight_visitor",
            data={"type": "flight_visitor", "route": "SFO > EWR", "dest_iata": "EWR", "guest_name": settings.track_guest_name}), board))

    source = PublicDemoData({"flights": SimpleNamespace(fetch=fetch)})
    source.content("airports")
    source.close()
    assert source.content("airports")[0]["airports"][0]["id"] == "airport:EWR"
    content, state = source.content("flights")
    assert state == "live"
    assert content["flights"][0]["data"]["route"] == "SFO > EWR"
    assert all(settings.airport_code_iata == "EWR" for settings in calls)
    assert calls[0].track_guest_name == ""
    assert calls[1].track_guest_name == "UA123"


def test_public_provider_failure_is_explicit_and_old_quotes_expire():
    now = [0]
    failing = SimpleNamespace(fetch=lambda settings: ProviderResult(health=ProviderHealth(healthy=False, provider="stock")))
    source = PublicDemoData({"stock": failing}, clock=lambda: now[0])
    source.content("stock")
    source.close()
    assert source.content("stock") == ({"stock": []}, "unavailable")
    source._content["stock"] = [{"id": "stock:MSFT"}]
    source._updated["stock"] = 0
    assert source.content("stock")[1] == "stale"
    now[0] = 601
    assert source.content("stock") == ({"stock": []}, "unavailable")


@pytest.fixture
def demo_app(tmp_path, monkeypatch):
    from ticker.server.web import routes
    from ticker.panel.assets import storage as asset_module
    monkeypatch.setattr(asset_module, "_fetch_with_requests", lambda url: None)
    monkeypatch.setattr(routes, "time", lambda: 1792168467.0)
    monkeypatch.setattr(routes, "_SAMPLE_STARTED", 1792168355.0)
    app = create_offline_application(tmp_path / "test.sqlite3", [])
    yield app
    assets = app.extensions.get("ticker.dashboard_preview_assets")
    if assets:
        assets.close()
    app.extensions["ticker.application"].close()


def test_stock_web_frame_uses_real_card_and_prepared_logos(demo_app, monkeypatch, tmp_path):
    from ticker.panel.cards.stock import StockCard
    from ticker.panel.assets import storage as asset_module
    from ticker.panel import load_default_font_set

    records = [{"data": {**dict(item.data), "situation": dict(item.data["situation"])}} for item in (stock("MSFT"), stock("NVDA"))]
    demo_app.extensions["ticker.public_demo"] = SimpleNamespace(content=lambda mode: ({mode: records}, "live"))
    logo = Image.new("RGBA", (24, 24), (255, 0, 255, 255))
    encoded = BytesIO()
    logo.save(encoded, format="PNG")
    fetched = []
    def fetch(url):
        fetched.append(url)
        return encoded.getvalue()
    monkeypatch.setattr(asset_module, "_fetch_with_requests", fetch)
    demo_app.config["DASHBOARD_ASSET_CACHE"] = tmp_path / "assets"
    response = demo_app.test_client().get("/demo/frame.png?mode=stock")
    assert response.headers["X-Ticker-Data"] == "live"
    actual = Image.open(BytesIO(response.data)).convert("RGBA")
    assert actual.size == (258, 32)
    expected = StockCard(load_default_font_set(), SimpleNamespace(get=lambda url, size: logo)).pane(records[0]["data"])
    assert actual.crop((1, 0, 129, 32)).tobytes() == expected.tobytes()
    assert actual.getpixel((3, 4))[:3] == (255, 0, 255)
    assert set(fetched) == {row["data"]["home_logo"] for row in records}


@pytest.mark.parametrize("mode", ["music", "weather"])
def test_animation_atlas_contains_consecutive_production_frames(demo_app, mode):
    from ticker.server.web import routes
    from ticker.panel.frame import RenderContext
    from ticker.panel.cards.weather import WeatherCard
    from ticker.panel import load_default_font_set

    weather = layout_case("MD04")["game"]
    demo_app.extensions["ticker.public_demo"] = SimpleNamespace(content=lambda value: ({value: [{"data": weather}]}, "live"))
    client = demo_app.test_client()
    segment = 1792168467 // 3
    response = client.get(f"/demo/animation.png?mode={mode}&segment={segment}")
    assert response.status_code == 200
    assert response.headers["X-Ticker-Frames"] == "90"
    assert response.headers["X-Ticker-FPS"] == "30"
    atlas = Image.open(BytesIO(response.data)).convert("RGB")
    assert atlas.size == (384, 2880)
    assert atlas.crop((0, 0, 384, 32)).tobytes() != atlas.crop((0, 960, 384, 992)).tobytes()
    if mode == "weather":
        when = datetime.fromtimestamp(segment * 3, ZoneInfo("America/New_York")) + timedelta(seconds=43 / 30)
        expected = WeatherCard(load_default_font_set()).frame(when, weather)
        assert atlas.crop((0, 43 * 32, 384, 44 * 32)).tobytes() == expected.convert("RGB").tobytes()
    else:
        with demo_app.app_context():
            content = routes._demo_content("music")
            assets = routes._preview_assets()
            first = assets.renderer.animation([content["music"][0]["data"]], "music", datetime.fromtimestamp(segment * 3, timezone.utc))
        assert Image.open(BytesIO(first)).tobytes() == atlas.tobytes()
    assert client.get(f"/demo/animation.png?mode={mode}&segment={segment}", headers={"If-None-Match": response.headers["ETag"]}).status_code == 304
    assert client.get(f"/demo/animation.png?mode={mode}&segment={segment + 2}").status_code == 400
    assert client.get(f"/demo/animation.png?mode={mode}&segment=bad").status_code == 400
    assert client.get("/demo/animation.png?mode=stock").status_code == 400


def test_missing_public_feed_does_not_show_fake_flight_or_apple_quote(demo_app):
    for mode in ("stock", "flights", "airports"):
        response = demo_app.test_client().get(f"/demo/frame.png?mode={mode}")
        assert response.status_code == 200
        assert response.headers["X-Ticker-Data"] == "unavailable"


def test_music_chunks_match_continuous_playback_even_with_a_future_fetch_anchor(demo_app):
    from ticker.server.web import routes
    from ticker.panel.bootstrap import CachedLogoView
    from ticker.panel.frame import RenderContext
    from ticker.panel.cards.music import MusicCard, MusicState
    from ticker.panel import load_default_font_set

    start = datetime.fromtimestamp(1792168467, ZoneInfo("America/New_York"))
    game = dict(routes._demo_content("music")["music"][0]["data"])
    game.update(progress=112, fetch_ts=start.timestamp() + 60)
    with demo_app.app_context():
        assets = routes._preview_assets()
        first = Image.open(BytesIO(assets.renderer.animation([game], "music", start))).convert("RGB")
        next_chunk = Image.open(BytesIO(assets.renderer.animation([game], "music", start + timedelta(seconds=3)))).convert("RGB")
        renderer = MusicCard(load_default_font_set(), CachedLogoView(assets))
        warm = start - timedelta(seconds=2)
        age = game["progress"] + warm.timestamp() - game["fetch_ts"]
        state = MusicState(rotation=(-100 * age) % 360, scroll=15 * age, previous_time=warm.timestamp())
        for index in range(151):
            frame, state = renderer.frame(warm + timedelta(seconds=index / 30), game, state)
            if index == 149:
                assert first.crop((0, 89 * 32, 384, 90 * 32)).tobytes() == frame.convert("RGB").tobytes()
            elif index == 150:
                assert next_chunk.crop((0, 0, 384, 32)).tobytes() == frame.convert("RGB").tobytes()


def test_fleet_modes_stock_options_and_device_specific_specs(demo_app, monkeypatch):
    import re

    from ticker.shared.domain import DISPLAY_MODES, DisplaySettings, TickerSnapshot
    from ticker.server.store.models import DeviceMetadata, PairingState, TickerRecord
    from ticker.server.store.profiles import TickerProfile

    now = datetime.now(timezone.utc).timestamp()
    def ticker(identifier, family, mode, seen, build, uptime, active):
        profile = TickerProfile.from_mapping({"product_family": family, "capabilities": {"modes": DISPLAY_MODES}})
        return TickerRecord(identifier, identifier, DisplaySettings(mode=mode, active_sports=active),
            PairingState(paired=True), DeviceMetadata(seen, {"profile": profile.to_mapping(), "build": build, "uptime_seconds": uptime}))

    six = ticker("six", "full", "sports", now, "six-device-build", 3600, {"stock_finance": True})
    mini = ticker("mini", "mini", "clock", now, "mini-device-build", 120, {"stock_momentum": True})
    offline = ticker("old", "full", "music", now - 180, "old-build", 10, {"stock_consumer": True})
    backend = demo_app.extensions["ticker.application"]
    monkeypatch.setattr(backend, "list_tickers", lambda: (six, mini, offline))
    monkeypatch.setattr(backend.schedule_service, "effective_settings", lambda identifier, settings, **kwargs:
        DisplaySettings(mode="stock", active_sports=settings.active_sports) if identifier == "mini" else settings)
    backend.snapshot_store.replace(TickerSnapshot("mini", 1, datetime.now(timezone.utc), (stock("MSFT", "stock_momentum"),), (), (), mini.display_settings))
    page = demo_app.test_client().get("/").get_data(as_text=True)
    def mode_block(mode):
        return page.split(f'data-mode-option="{mode}"', 1)[1].split('data-mode-option=', 1)[0]
    assert "On air" in mode_block("sports")
    assert "On air" in mode_block("stock")
    assert "On air" not in mode_block("clock")
    assert "On air" not in mode_block("music")
    assert page.count('class="mode-flag"') == 2
    assert re.search(r'data-active-mode-count[^>]*>2</div>', page)
    assert "Sports / Stocks" in page
    assert 'data-market-option="stock_tech_ai"' in page
    assert 'data-market-option="stock_momentum"' in page
    assert 'data-market-option="stock_energy"' in page
    assert 'data-market-option="stock_finance"' in page
    assert 'data-market-option="stock_consumer"' in page
    assert 'is-live" data-market-option="stock_momentum"' in page
    assert 'is-on" data-market-option="stock_energy"' in page
    assert 'is-on" data-market-option="stock_consumer"' in page
    assert len(re.findall('data-market-option=', page)) == 5
    six_card = page.split('data-hardware="Ticker Six"', 1)[1].split('data-hardware="Ticker Mini"', 1)[0]
    mini_card = page.split('data-hardware="Ticker Mini"', 1)[1].split('</section>', 1)[0]
    for expected in ("384X32", "6 X 64X32", "six-device-build", "1h 0m", "33 PX/SEC"):
        assert expected in six_card
    for expected in ("64X32", "1 X 64X32", "mini-device-build", ">2m</span>", "3 SEC/PAGE"):
        assert expected in mini_card
    assert "six-device-build" not in mini_card
    assert "mini-device-build" not in six_card
    assert '<header class="spec-header">' in six_card
    assert '<header class="spec-header">' in mini_card


def test_empty_fleet_has_no_on_air_badge_and_shows_all_stock_options(demo_app):
    page = demo_app.test_client().get("/").get_data(as_text=True)
    assert 'class="mode-flag"' not in page
    assert page.count('data-market-option=') == 5
    assert 'data-hardware="Ticker Six"' in page
    assert 'data-hardware="Ticker Mini"' in page
    assert 'class="led-chip is-off" data-market-option=' not in page
    assert 'class="led-chip is-live" data-market-option=' not in page
    assert page.count('class="led-chip is-on" data-market-option=') == 5


def test_live_provider_envelopes_keep_renderer_identity(demo_app):
    from ticker.server.providers.flights import FlightsProvider
    from ticker.server.providers.stocks import StockProvider
    from ticker.server.web.routes import _preview_items

    quote = {**dict(stock("MSFT").data), "situation": {"change": "+1.52"}}
    airport = {"id": "airport:EWR", "type": "flight_airport_hud", "sport": "airport",
        "weather": {"icao": "KEWR"}, "arrivals": [{"flight_number": "UA123"}], "departures": []}
    tracked = {"id": "UA123", "type": "flight_visitor", "sport": "flight",
        "guest_name": "UA123", "route": "SFO > EWR", "origin_iata": "SFO", "dest_iata": "EWR"}
    stocks = StockProvider(SimpleNamespace(fetch=lambda settings: {"content": [quote]}))
    flights = FlightsProvider(SimpleNamespace(fetch=lambda settings: {"content": [airport, tracked]}))
    source = PublicDemoData({"stock": stocks, "flights": flights})
    source._refresh("stock")
    source._refresh("flights")
    source.close()
    demo_app.extensions["ticker.public_demo"] = source
    for mode, expected in (("stock", "stock"), ("flights", "flight_visitor"), ("airports", "flight_airport_hud")):
        content, _ = source.content(mode)
        assert "type" not in content[mode][0]["data"]
        assert _preview_items(content)[0]["type"] == expected
        response = demo_app.test_client().get(f"/demo/frame.png?mode={mode}")
        assert response.status_code == 200
        assert response.headers["X-Ticker-Data"] == "live"
        assert response.headers["X-Ticker-Items"] == "1"
        image = Image.open(BytesIO(response.data))
        assert image.size == ((129 if mode == "stock" else 384), 32)


@pytest.mark.parametrize("raw,label", [
    ("r1757+558782a", "Build 1757"), ("r1757", "Build 1757"),
    ("mini-1.3.36", "Build 1.3.36"), ("mini-1.4.0-beta.1", "Build 1.4.0-beta.1"),
    (None, "Not reported"), ("custom-build", "custom-build"),
])
def test_device_build_labels_keep_existing_version_numbers(raw, label):
    from ticker.server.web.routes import _build_label
    assert _build_label(raw) == label


def test_page_versions_stylesheet_and_preserves_full_device_build_on_hover(demo_app, monkeypatch):
    import re

    from ticker.shared.domain import DisplaySettings
    from ticker.server.store.models import DeviceMetadata, PairingState, TickerRecord
    from ticker.server.store.profiles import TickerProfile

    now = datetime.now(timezone.utc).timestamp()
    records = [TickerRecord(name, name, DisplaySettings(), PairingState(paired=True), DeviceMetadata(now, {
        "profile": TickerProfile.from_mapping({"product_family": family}).to_mapping(), "build": build,
    })) for name, family, build in (("Six", "full", "r1757+558782a"), ("Mini", "mini", "mini-1.3.36"))]
    backend = demo_app.extensions["ticker.application"]
    monkeypatch.setattr(backend, "list_tickers", lambda: records)
    monkeypatch.setattr(backend.schedule_service, "effective_settings", lambda identifier, settings, **kwargs: settings)
    demo_app.config["VERSION"] = "first"
    first = demo_app.test_client().get("/").get_data(as_text=True)
    assert 'title="r1757+558782a">Build 1757</span>' in first
    assert 'title="mini-1.3.36">Build 1.3.36</span>' in first
    assert re.search(r'data-active-mode-count[^>]*>1</div>', first)
    assert '/static/style.css?v=first' in first
    demo_app.config["VERSION"] = "next"
    second = demo_app.test_client().get("/").get_data(as_text=True)
    assert '/static/style.css?v=next' in second


def test_markets_allow_multiple_green_groups_and_keep_unused_groups_orange():
    from ticker.shared.domain import DisplaySettings
    from ticker.server.web.routes import _market_rows

    tickers = [SimpleNamespace(display_settings=DisplaySettings(active_sports={group: True}))
               for group in ("stock_finance", "stock_momentum", "stock_energy", "stock_consumer")]
    fleet = [{"mode": "stock", "link": "online"}, {"mode": "stock", "link": "online"},
             {"mode": "sports", "link": "online"}, {"mode": "stock", "link": "off"}]
    states = {row["id"]: row["state"] for row in _market_rows(tickers, fleet)}
    assert states == {"stock_tech_ai": "on", "stock_momentum": "live", "stock_energy": "on",
                      "stock_finance": "live", "stock_consumer": "on"}


def test_public_weather_uses_nyc_coordinates_without_ticker_settings():
    calls = []
    def fetch(settings):
        calls.append(settings)
        return ProviderResult(content=(ContentItem(id="weather:nyc", family="weather", kind="weather", data={
            "type": "weather", "away_abbr": settings.weather_city, "home_abbr": "68", "situation": {"icon": "cloud"},
        }),))
    source = PublicDemoData({"weather": SimpleNamespace(fetch=fetch)})
    source.content("weather")
    source.close()
    content, state = source.content("weather")
    assert state == "live"
    assert content["weather"][0]["data"]["away_abbr"] == "NYC"
    assert [(settings.weather_lat, settings.weather_lon) for settings in calls] == [(40.7128, -74.0060)]
    assert calls[0].airport_code_iata == "EWR"


@pytest.mark.parametrize("mode,path", [("flights", "frame"), ("weather", "frame"), ("weather", "animation")])
def test_live_pixels_are_not_stored_by_browsers_or_cdns(demo_app, mode, path):
    response = demo_app.test_client().get(f"/demo/{path}.png?mode={mode}")
    assert response.status_code == 200
    assert response.cache_control.no_store
    assert response.cache_control.private
    assert response.cache_control.max_age == 0
    assert response.headers["CDN-Cache-Control"] == "no-store"
    assert response.headers["Cloudflare-CDN-Cache-Control"] == "no-store"
    assert response.headers["Expires"] == "0"


def test_flight_demo_tries_next_candidate_and_keeps_real_schedule_when_tracking_fails():
    board = ContentItem(id="airport:EWR", family="airports", kind="flight_airport_hud", data={
        "arrivals": [{"flight_number": "UA1", "origin_iata": "ORD", "origin_city": "CHICAGO", "status": "Scheduled"},
                     {"flight_number": "UA2", "origin_iata": "SFO", "status": "En-route"}],
    })
    calls = []
    tracking = [False]
    def fetch(settings):
        calls.append(settings.track_flight_id)
        if settings.track_flight_id == "UA2" and tracking[0]:
            return ProviderResult(content=(ContentItem(id="UA2", family="flights", kind="flight_visitor", data={
                "id": "UA2", "origin_iata": "SFO", "dest_iata": "EWR", "status": "en-route",
            }),))
        return ProviderResult(content=(board,))
    source = PublicDemoData({"flights": SimpleNamespace(fetch=fetch)})
    try:
        source._refresh("flights")
        source._closed = True
        content, state = source.content("flights")
        game = content["flights"][0]["data"]
        assert state == "live"
        assert game["route"] == "ORD > EWR"
        assert game["status"] == "Scheduled"
        assert "alt" not in game and "speed" not in game
        assert calls == ["", "UA1", "UA2"]
        tracking[0] = True
        source._refresh("flights")
        assert source.content("flights")[0]["flights"][0]["id"] == "UA2"
    finally:
        source.close()


def test_hardware_catalog_includes_server_with_its_own_build_and_runtime(demo_app):
    demo_app.config["VERSION"] = "abcdef1234567890"
    page = demo_app.test_client().get("/").get_data(as_text=True)
    assert 'data-hardware="Ticker Server"' in page
    assert 'role="tablist" aria-label="Ticker hardware"' in page
    assert 'aria-controls="hardware-card-3"' in page
    assert 'hardware-catalog.js?v=abcdef123456' in page
    server = page.split('data-hardware="Ticker Server"', 1)[1].split('catalog-hint', 1)[0]
    assert "Shared backend" in server
    assert "Build abcdef1" in server
    assert "Threads" in server
    assert "Memory" in server
    assert "Resolution" not in server
