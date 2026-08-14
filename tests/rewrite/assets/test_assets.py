from __future__ import annotations

import io

from PIL import Image

from ticker_core.assets import AssetPlanner, AssetRequest, ShortTermContentCache
from ticker_core.platform import AssetCoordinator


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


def test_content_cache_recovers_then_expires_last_good_payload(tmp_path) -> None:
    clock = [0.0]
    cache = ShortTermContentCache(tmp_path / "last-good.json", ttl=300, clock=lambda: clock[0])
    cache.store({"content": {"sports": [{"id": "game"}]}})
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
    first_write = path.stat().st_mtime_ns
    clock[0] = 0.5
    cache.refresh()

    assert path.stat().st_mtime_ns == first_write
    assert cache.remaining(cache.load()) == 300


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
