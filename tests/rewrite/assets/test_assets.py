from __future__ import annotations

import io
from threading import Event, Thread

from PIL import Image

from ticker_core.assets import AssetPlanner, AssetRequest, LogoAssetView, PreparedAssetStore, ShortTermContentCache
from ticker_core.platform import AssetCoordinator, LongTermAssetCache


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


def test_coordinator_reuses_prepared_logo_after_restart(tmp_path) -> None:
    """Load a prepared logo from the long-term cache without refetching it."""
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
        {"id": "music", "type": "music", "home_logo": "album", "next_logos": ["next-album"]},
        {"id": "flight", "type": "flight_visitor", "airline_logo": "airline"},
        {"id": "race", "type": "racing", "sport": "nascar", "nascar": {"drivers": [{"team_logo": "team", "car_illustration": "https://nascar.com/car.jpg"}]}},
    ]

    plan = AssetPlanner().plan(content)

    signatures = {(request.url, request.processor, request.size) for request in plan.requests}
    assert ("sports-home", "logo", (24, 24)) in signatures
    assert ("album", "logo", (42, 42)) in signatures
    assert ("next-album", "logo", (42, 42)) in signatures
    assert ("airline", "logo", (24, 24)) in signatures
    assert ("team", "logo", (18, 18)) in signatures
    assert ("team", "logo", (21, 21)) in signatures
    assert ("https://nascar.com/car.jpg", "car", (130, 20)) in signatures


def _png() -> bytes:
    image = Image.new("RGBA", (8, 4), (30, 150, 220, 255))
    output = io.BytesIO()
    image.save(output, "PNG")
    return output.getvalue()
