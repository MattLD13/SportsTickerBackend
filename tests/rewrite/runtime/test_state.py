"""Exercise the version two runtime state boundary."""

from datetime import datetime, timezone

import pytest

from ticker_core.protocol import TickerResponse
from ticker_core.runtime import FrameKind, RuntimeConfig, StripLayout, StripSegment, TickerRuntime, classify_content, remap_strip_offset


def _response(
    *,
    mode: str = "sports",
    presentation: str = "rotation",
    state: str = "in",
    scroll_speed: float = 0.04,
) -> TickerResponse:
    return TickerResponse.from_payload(
        {
            "api_version": "v2",
            "snapshot": {"ticker_id": "ticker-1", "revision": 1, "observed_at": "2026-08-11T00:00:00+00:00", "stale": False},
            "settings": {"mode": mode, "sports_presentation": presentation, "pinned_content_id": "game", "brightness": 75, "scroll_speed": scroll_speed, "inverted": True},
            "content": {"sports": [{"id": "game", "family": "sports", "kind": "scoreboard", "is_shown": True, "data": {"sport": "nfl", "state": state}}]},
            "events": {"alerts": [], "news": []}, "health": {"provider": "refresh", "healthy": True, "error": None},
            "meta": {"pairing": {"paired": True, "code": None}},
        }
    )


def _runtime(clock: list[float]) -> TickerRuntime:
    return TickerRuntime(
        monotonic=lambda: clock[0],
        wall_clock=lambda: datetime(2026, 8, 11, tzinfo=timezone.utc),
        config=RuntimeConfig(offline_after=10),
    )


def test_runtime_uses_v2_settings_for_scroll_and_panel_controls() -> None:
    clock = [0.0]
    runtime = _runtime(clock)
    response = _response()

    snapshot = runtime.accept_response(response)
    runtime.install_strip(snapshot.strip_key, StripLayout(10, (StripSegment("game", 10),)))
    frame = runtime.next_frame()

    assert frame.kind is FrameKind.SCROLL
    assert frame.brightness == 75
    assert frame.inverted is True


@pytest.mark.parametrize(
    ("scroll_speed", "expected_offsets"),
    (
        (0.10, (0.0, 0.3, 0.6, 0.9)),
        (0.03, (0.0, 1.0, 2.0, 3.0)),
        (0.01, (0.0, 3.0, 6.0, 9.0)),
    ),
)
def test_scroll_speed_changes_distance_without_changing_smooth_cadence(
    scroll_speed: float,
    expected_offsets: tuple[float, ...],
) -> None:
    """Move through fractional pixels while every speed retains the proven Pi cadence."""

    clock = [0.0]
    runtime = _runtime(clock)
    snapshot = runtime.accept_response(_response(scroll_speed=scroll_speed))
    runtime.install_strip(snapshot.strip_key, StripLayout(20, (StripSegment("game", 20),)))

    frames = tuple(runtime.next_frame() for _ in expected_offsets)

    assert tuple(frame.interval for frame in frames) == (0.03,) * len(expected_offsets)
    assert tuple(frame.scroll_offset for frame in frames) == pytest.approx(expected_offsets)


def test_strip_refresh_preserves_the_visible_card_and_fractional_position() -> None:
    """Keep the same card and subpixel phase when one card changes width."""

    previous = StripLayout(20, (StripSegment("first", 10), StripSegment("second", 10)))
    current = StripLayout(24, (StripSegment("first", 12), StripSegment("second", 12)))

    assert remap_strip_offset(previous, 12.25, current) == pytest.approx(14.25)


def test_sports_pinned_is_a_presentation_not_a_second_mode() -> None:
    clock = [0.0]
    runtime = _runtime(clock)
    runtime.accept_response(_response(presentation="pinned"))

    frame = runtime.next_frame()

    assert runtime.mode == "sports"
    assert frame.kind is FrameKind.STATIC
    assert frame.content is not None and frame.content.id == "game"
    assert frame.content_elapsed == 0.0

    clock[0] = 2.5
    assert runtime.next_frame().content_elapsed == 2.5

    clock[0] = 100.0
    frame = runtime.next_frame()
    assert frame.kind is FrameKind.STATIC
    assert frame.content_elapsed == 100.0


def test_pinned_animation_survives_payload_refresh_and_empty_strip_install() -> None:
    clock = [0.0]
    runtime = _runtime(clock)
    runtime.accept_response(_response(presentation="pinned"))
    assert runtime.next_frame().content_elapsed == 0.0

    clock[0] = 12.0
    second = runtime.accept_response(_response(presentation="pinned", state="post"))
    assert runtime.install_strip(second.strip_key, None) is True
    frame = runtime.next_frame()

    assert frame.kind is FrameKind.STATIC
    assert frame.content_elapsed == 12.0
    assert frame.content is not None and frame.content.data["state"] == "post"


def test_flights_and_airports_have_separate_content_classes() -> None:
    visitor = {"id": "visitor", "type": "flight_visitor", "sport": "flight"}
    airport = {"id": "airport", "type": "flight_airport_hud", "sport": "flight"}

    flights = classify_content((visitor, airport), "flights")
    airports = classify_content((visitor, airport), "airports")

    assert [entry.id for entry in flights.static] == ["visitor"]
    assert [entry.id for entry in airports.static] == ["airport"]


def test_disconnect_keeps_content_until_the_cache_expiry() -> None:
    clock = [0.0]
    runtime = _runtime(clock)
    response = _response()
    snapshot = runtime.accept_response(response)
    runtime.install_strip(snapshot.strip_key, StripLayout(10, (StripSegment("game", 10),)))
    runtime.mark_disconnected(expires_in=5)

    assert runtime.next_frame().connection_lost is True
    clock[0] = 5.1
    assert runtime.next_frame().kind is FrameKind.OFFLINE
