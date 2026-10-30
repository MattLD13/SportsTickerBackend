from __future__ import annotations

import io
from pathlib import Path
from concurrent.futures import Future
from threading import Event, Thread
from types import SimpleNamespace

from PIL import Image
import pytest

from ticker_core.assets import AssetPlanner, AssetRequest, LogoAssetView, PreparedAssetStore, ShortTermContentCache
from ticker_core.platform import AssetCoordinator, LongTermAssetCache


def test_completed_asset_future_registers_callback_outside_coordinator_lock(tmp_path) -> None:
    """Let an already completed asset future clear itself without reacquiring an owned lock."""
    request = AssetRequest("https://assets.example/cached.png", "logo", (8, 8))
    coordinator = AssetCoordinator(tmp_path)

    class LockCheckingFuture(Future):
        def add_done_callback(self, callback, *, context=None) -> None:
            acquired = coordinator._lock.acquire(blocking=False)
            assert acquired, "Asset callback registration held the coordinator lock."
            coordinator._lock.release()
            super().add_done_callback(callback)

    class ImmediateExecutor:
        def submit(self, _function, *_args) -> Future:
            future = LockCheckingFuture()
            future.set_result(None)
            return future

        def shutdown(self, *, wait=True, cancel_futures=False) -> None:
            return None

    coordinator._executor = ImmediateExecutor()
    try:
        future = coordinator.prefetch((request,))[0]
        assert future.done()
        assert request not in coordinator._inflight
    finally:
        coordinator.close()


def test_coordinator_reuses_persistent_original_bytes(tmp_path) -> None:
    raw = _png()
    calls: list[str] = []
    request = AssetRequest("https://assets.example/logo.png", "logo", (8, 8))
    writer = AssetCoordinator(tmp_path, fetch=lambda url: calls.append(url) or raw)
    try:
        assert writer.prefetch((request,))[0].result() is not None
    finally:
        writer.close()

    reader = AssetCoordinator(tmp_path, fetch=lambda _url: (_ for _ in ()).throw(AssertionError("Fetched despite persistent bytes.")))
    try:
        assert reader.prefetch((request,))[0].result() is not None
    finally:
        reader.close()

    assert calls == [request.url]


@pytest.mark.critical
def test_asset_fetch_only_advertises_installed_image_decoders(monkeypatch) -> None:
    from ticker_core.platform.assets import _fetch_with_requests

    Image.init()
    monkeypatch.delitem(Image.OPEN, "AVIF", raising=False)
    raw = _png()

    def get(url, *, headers: dict, timeout):
        assert url == "https://media.formula1.com/car.webp"
        assert timeout > 0
        assert "image/avif" not in headers["Accept"]
        assert "image/*" not in headers["Accept"]
        assert "image/png" in headers["Accept"]
        return SimpleNamespace(status_code=200, content=raw)

    monkeypatch.setattr("requests.get", get)
    assert _fetch_with_requests("https://media.formula1.com/car.webp") == raw


@pytest.mark.critical
def test_undecodable_original_is_replaced_with_a_verified_download(tmp_path) -> None:
    request = AssetRequest("https://media.formula1.com/car.webp", "car", (130, 20))
    raw = _png()
    calls = []
    coordinator = AssetCoordinator(tmp_path, fetch=lambda url: calls.append(url) or raw)
    coordinator.long_term.originals.store(request.url, b"cached image from an unavailable decoder")
    try:
        assert coordinator.prefetch((request,))[0].result() is not None
        assert coordinator.long_term.originals.load(request.url) == raw
        assert coordinator.image(request.url, request.processor, request.size) is not None
        assert calls == [request.url]
    finally:
        coordinator.close()


@pytest.mark.critical
def test_undecodable_download_does_not_replace_a_valid_expired_original(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("ticker_core.platform.assets.time.time", lambda: 301 * 86400.0)
    request = AssetRequest("https://media.formula1.com/car.webp", "car", (130, 20))
    raw = _png()
    coordinator = AssetCoordinator(tmp_path, fetch=lambda _url: b"unsupported image response")
    coordinator.long_term.originals.store(request.url, raw, now=1.0)
    try:
        assert coordinator.prefetch((request,))[0].result() is not None
        assert coordinator.long_term.originals.load(request.url, ignore_expiry=True) == raw
    finally:
        coordinator.close()


def test_series_aware_ttl_caching(tmp_path) -> None:
    from ticker_core.platform.assets import PersistentAssetStore
    store = PersistentAssetStore(tmp_path)
    raw = _png()
    nascar_url = "https://www.nascar.com/wp-content/uploads/sites/7/2026/08/12/26_NCS_26Richmond_1-922x400.jpg"
    imsa_url = "https://www.imsa.com/wp-content/uploads/sites/32/2025/01/18/25_WT_GTP_10_WTR.png"
    base_time = 1000000.0

    store.store(nascar_url, raw, now=base_time)
    store.store(imsa_url, raw, now=base_time)

    # 3 days later (within 1 week): both valid
    assert store.load(nascar_url, now=base_time + 3 * 86400) is not None
    assert store.load(imsa_url, now=base_time + 3 * 86400) is not None

    # 10 days later (past 1 week): NASCAR expired, IMSA still valid
    assert store.load(nascar_url, now=base_time + 10 * 86400) is None
    assert store.load(imsa_url, now=base_time + 10 * 86400) is not None

    # 350 days later (past 300 days): IMSA expired
    assert store.load(imsa_url, now=base_time + 350 * 86400) is None


def test_coordinator_reuses_prepared_logo_after_restart(tmp_path) -> None:
    raw = _png()
    request = AssetRequest("https://assets.example/logo.png", "logo", (8, 8))
    writer = AssetCoordinator(tmp_path, fetch=lambda _url: raw)
    try:
        assert writer.prefetch((request,))[0].result() is not None
    finally:
        writer.close()

    reader = AssetCoordinator(tmp_path, fetch=lambda _url: (_ for _ in ()).throw(AssertionError("Refetched prepared logo.")))
    try:
        assert reader.long_term.prepared.contains(request)
        assert reader.image(request.url, request.processor, request.size) is not None
    finally:
        reader.close()


def test_logo_view_changes_from_fallback_to_prepared_image(tmp_path) -> None:
    """Expose a prepared logo through the renderer read boundary after fetch."""
    request = AssetRequest("https://assets.example/logo.png", "logo", (22, 22))
    coordinator = AssetCoordinator(tmp_path, fetch=lambda _url: _png())
    view = LogoAssetView(coordinator)
    try:
        assert view.get(request.url, request.size) is None
        assert coordinator.prefetch((request,))[0].result() is not None
        image = view.get(request.url, request.size)
        assert image is not None
        assert image.size == request.size
    finally:
        coordinator.close()


def test_failed_logo_fetch_retries_after_negative_lifetime(tmp_path) -> None:
    """Retry a failed logo after its negative preparation entry expires."""
    now = [0.0]
    calls: list[str] = []
    request = AssetRequest("https://assets.example/retry.png", "logo", (8, 8))
    prepared = PreparedAssetStore(clock=lambda: now[0], negative_ttl=5.0)
    coordinator = AssetCoordinator(
        tmp_path,
        fetch=lambda url: calls.append(url) or (None if len(calls) == 1 else _png()),
        prepared=prepared,
    )
    try:
        assert coordinator.prefetch((request,))[0].result() is None
        now[0] = 6.0
        assert coordinator.prefetch((request,))[0].result() is not None
        assert calls == [request.url, request.url]
    finally:
        coordinator.close()


def test_asset_revision_tracks_material_readiness_only(tmp_path) -> None:
    """Advance revision for readiness transitions, not repeated failures or successful refreshes."""
    request = AssetRequest("https://assets.example/revision.png", "logo", (8, 8))
    store = PreparedAssetStore(negative_ttl=30.0)
    assert store.revision == 0
    store.put(request, None)
    assert store.revision == 0
    store.put(request, None)
    assert store.revision == 0
    store.put(request, Image.new("RGBA", request.size, (20, 30, 40, 255)))
    assert store.revision == 1
    store.put(request, Image.new("RGBA", request.size, (20, 30, 40, 255)))
    assert store.revision == 1

    now = [0.0]
    expiring = PreparedAssetStore(clock=lambda: now[0], negative_ttl=1.0, ttl=1.0)
    expiring.put(request, None)
    now[0] = 2.0
    assert not expiring.contains_memory(request)
    assert expiring.revision == 0
    expiring.put(request, Image.new("RGBA", request.size, (20, 30, 40, 255)))
    now[0] = 4.0
    assert expiring.image(request.url, request.processor, request.size) is None
    assert expiring.revision == 2


def test_running_durable_asset_view_observes_new_prepared_file(tmp_path) -> None:
    """Read a logo prepared after a separate view started without restarting that view."""
    request = AssetRequest("https://assets.example/process.png", "logo", (8, 8))
    writer = AssetCoordinator(tmp_path, fetch=lambda _url: _png())
    reader = LongTermAssetCache(tmp_path)
    try:
        assert reader.image(request.url, request.processor, request.size) is None
        assert writer.prefetch((request,))[0].result() is not None
        image = reader.image(request.url, request.processor, request.size)
        assert image is not None
        assert image.size == request.size
    finally:
        writer.close()


def test_default_positive_logo_remains_memory_readable_past_fifteen_minutes() -> None:
    """Keep a prepared logo available beyond the negative retry window by default."""
    now = [0.0]
    request = AssetRequest("https://assets.example/long-lived.png", "logo", (8, 8))
    store = PreparedAssetStore(clock=lambda: now[0])
    store.put(request, Image.new("RGBA", request.size, (20, 30, 40, 255)))
    now[0] = 901.0
    assert store.get_memory(request) is not None


def test_capacity_eviction_rehydrates_from_durable_cache_before_render_read(tmp_path) -> None:
    """Rehydrate an evicted logo from its durable prepared file during later prefetch."""
    first = AssetRequest("https://assets.example/first.png", "logo", (8, 8))
    second = AssetRequest("https://assets.example/second.png", "logo", (8, 8))
    calls: list[str] = []
    prepared = PreparedAssetStore(capacity=1, directory=tmp_path / "prepared")
    coordinator = AssetCoordinator(
        tmp_path,
        prepared=prepared,
        fetch=lambda url: calls.append(url) or _png(),
    )
    try:
        assert coordinator.prefetch((first,))[0].result() is not None
        assert coordinator.prefetch((second,))[0].result() is not None
        assert coordinator.image(first.url, first.processor, first.size) is None
        assert coordinator.prefetch((first,))[0].result() is not None
        assert coordinator.image(first.url, first.processor, first.size) is not None
        assert calls == [first.url, second.url]
    finally:
        coordinator.close()


def test_content_cache_recovers_then_expires_last_good_payload(tmp_path) -> None:
    clock = [0.0]
    cache = ShortTermContentCache(tmp_path / "last-good.json", ttl=300, clock=lambda: clock[0])
    cache.store({"content": {"sports": [{"id": "game"}]}})
    cache.flush()
    recovered = ShortTermContentCache(tmp_path / "last-good.json", ttl=300, clock=lambda: clock[0]).load()

    assert recovered is not None
    assert recovered.payload["content"]["sports"][0]["id"] == "game"
    clock[0] = 301
    assert cache.load() is None


def test_content_cache_keeps_repeated_payloads_in_memory(tmp_path) -> None:
    """Avoid rewriting the same payload on every backend poll."""
    clock = [0.0]
    path = tmp_path / "last-good.json"
    cache = ShortTermContentCache(path, ttl=300, clock=lambda: clock[0])
    payload = {"content": {"sports": [{"id": "game"}]}}

    cache.store(payload)
    cache.flush()
    first_write = path.stat().st_mtime_ns
    clock[0] = 0.5
    cache.refresh()

    assert path.stat().st_mtime_ns == first_write
    assert cache.remaining(cache.load()) == 300


def test_content_cache_store_does_not_wait_for_disk(tmp_path) -> None:
    """Keep a blocked removable-storage write outside the display thread."""
    started = Event()
    release = Event()
    cache = ShortTermContentCache(tmp_path / "last-good.json", ttl=300)
    write = cache._write

    def delayed_write(entry) -> None:
        started.set()
        assert release.wait(timeout=1)
        write(entry)

    cache._write = delayed_write
    stored = Event()

    def store() -> None:
        cache.store({"content": {"sports": [{"id": "game"}]}})
        stored.set()

    worker = Thread(target=store)
    worker.start()
    assert stored.wait(timeout=1)
    assert started.wait(timeout=1)
    assert cache.load() is not None
    release.set()
    worker.join(timeout=1)
    cache.flush()
    cache.close()


def test_planner_extracts_every_family_without_mode_filtering() -> None:
    content = [
        {"id": "game", "home_logo": "sports-home", "away_logo": "sports-away"},
        {"id": "joke-ad", "kind": "fan_duel_joke_ad", "logo": "brand-logo"},
        {"id": "music", "type": "music", "home_logo": "album", "next_logos": ["next-album"]},
        {"id": "flight", "type": "flight_visitor", "airline_logo": "airline"},
        {"id": "race", "type": "racing", "sport": "nascar", "nascar": {"drivers": [{"team_logo": "team", "car_illustration": "https://nascar.com/car.jpg"}]}},
    ]

    plan = AssetPlanner().plan(content)

    signatures = {(request.url, request.processor, request.size) for request in plan.requests}
    assert ("sports-home", "logo", (24, 24)) in signatures
    assert ("brand-logo", "logo", (18, 18)) in signatures
    assert ("album", "logo", (42, 42)) in signatures
    assert ("next-album", "logo", (42, 42)) in signatures
    assert ("airline", "logo", (22, 22)) in signatures
    assert ("team", "logo", (18, 18)) in signatures
    assert ("team", "logo", (21, 21)) in signatures
    assert ("https://nascar.com/car.jpg", "nascar_car", (130, 20)) in signatures


def test_planner_reads_team_logos_from_v2_content_envelopes() -> None:
    jets_logo = "https://a.espncdn.com/i/teamlogos/nfl/500/scoreboard/nyj.png"
    payload = {
        "content": {
            "sports": [
                {
                    "id": "jets",
                    "family": "sports",
                    "kind": "scoreboard",
                    "data": {"sport": "nfl", "away_logo": jets_logo},
                }
            ]
        },
    }

    plan = AssetPlanner().plan(payload)

    assert (jets_logo, "logo", (24, 24)) in {
        (request.url, request.processor, request.size) for request in plan.requests
    }


def test_f1_car_photo_reaches_the_six_frame_from_a_parsed_v2_response(tmp_path) -> None:
    from datetime import datetime, timezone
    from sports_ticker.providers.racing_live import _f1_car_url
    from ticker_core.ui.frame import RenderContext
    from ticker_core.assets import MemoryAssetView as MemoryRacingAssets
    from ticker_core.ui.cards.racing import RacingCard
    from ticker_core.protocol import TickerResponse
    from ticker_core.ui import ContentScene, load_default_font_set

    url = _f1_car_url("Mercedes")
    raw = (Path(__file__).resolve().parents[2] / "fixtures/assets/f1_mercedes_2026.webp").read_bytes()
    data = {"type": "racing", "sport": "f1", "state": "in", "sports_presentation": "pinned", "f1": {
        "short_name": "United States GP", "session_type": "Practice 2", "drivers": [{
            "pos": 1, "name": "George Russell", "abbr": "RUS", "team": "Mercedes", "car_illustration": url,
        }],
    }}
    payload = {"snapshot": {"ticker_id": "f1-six"}, "content": {"racing": [{
        "id": "f1-fp2", "family": "racing", "kind": "f1", "data": data,
    }]}}
    response = TickerResponse.from_payload(payload)
    plan = AssetPlanner().plan(response)
    assert AssetRequest(url, "car", (130, 20)) in plan.requests
    coordinator = AssetCoordinator(tmp_path, fetch=lambda _url: raw)
    try:
        for future in coordinator.prefetch_payload(response):
            assert future.result() is not None
        assert coordinator.image(url, "car", (130, 20)) is not None
        context = RenderContext(datetime(2026, 10, 23, tzinfo=timezone.utc))
        scene = ContentScene(data, "sports")
        fonts = load_default_font_set()
        photo = RacingCard(fonts, coordinator).render(context, scene).image
        placeholder = RacingCard(fonts, MemoryRacingAssets()).render(context, scene).image
        assert photo.size == (384, 32)
        assert photo.tobytes() != placeholder.tobytes()
    finally:
        coordinator.close()


def _png() -> bytes:
    image = Image.new("RGBA", (8, 4), (30, 150, 220, 255))
    output = io.BytesIO()
    image.save(output, "PNG")
    return output.getvalue()


def test_v2_alert_only_logo_reaches_the_production_frame(tmp_path) -> None:
    from ticker_core.features.alerts import ScoreAlertRenderer
    from ticker_core.protocol.model import OverlayItem
    from ticker_core.ui import load_default_font_set

    logo = "https://assets.example/alert-only.png"
    envelope = {"event_id": "nfl:6-0:home", "kind": "rushing_td", "payload": {
        "sport": "nfl", "headline": "RUSH TD", "team_abbr": "NYG", "team_logo": logo,
        "home_abbr": "NYG", "away_abbr": "DAL", "home_score": 6, "away_score": 0,
        "player": "WILLIAMS", "data": "RUSH 1YD", "team_color": "0B2265",
    }}
    raw = {"content": {}, "events": {"alerts": [envelope], "news": []}}
    parsed = OverlayItem.from_payload(envelope, "events.alerts[0]")
    raw_plan = AssetPlanner().plan(raw)
    assert raw_plan == AssetPlanner().plan({"alerts": [parsed]})
    assert AssetRequest(logo, "logo", (24, 24)) in raw_plan.requests
    coordinator = AssetCoordinator(tmp_path, fetch=lambda _url: _png())
    try:
        for future in coordinator.prefetch_payload(raw):
            assert future.result() is not None
        view = LogoAssetView(coordinator)
        assert view.get(logo, (24, 24)) is not None
        renderer = ScoreAlertRenderer(load_default_font_set(), view)
        frame = renderer.render(parsed.data, 2.0)
        assert frame.size == (384, 32)
        assert frame.tobytes() != renderer.render({**parsed.data, "team_logo": ""}, 2.0).tobytes()
    finally:
        coordinator.close()


def test_planner_requests_only_the_drawn_airline_logo() -> None:
    content = [
        {"id": "UA12", "type": "flight_visitor", "airline_logo": "united", "airline_iata": "UA"},
        {"id": "hud", "type": "flight_airport_hud",
         "arrivals": [{"airline_logo": "arrival-airline"}], "departures": [{"airline_logo": "departure-airline"}]},
    ]

    plan = AssetPlanner().plan(content)

    assert {(request.url, request.size) for request in plan.requests} == {("united", (22, 22))}
