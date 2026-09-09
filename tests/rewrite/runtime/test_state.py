"""Exercise the version two runtime state boundary."""

from datetime import datetime, timezone
import pytest

from ticker_core.protocol import TickerResponse
from ticker_core.runtime import FrameKind, RuntimeConfig, StripLayout, StripSegment, TickerRuntime, classify_content

pytestmark = pytest.mark.critical


def _response(
    *,
    mode: str = "sports",
    presentation: str = "rotation",
    state: str = "in",
    alerts: tuple[dict, ...] = (),
    game_count: int = 1,
    live_delay_mode: bool = False,
    live_delay_seconds: int = 0,
) -> TickerResponse:
    games = [
        {
            "id": "game" if index == 0 else f"game-{index}",
            "family": "sports",
            "kind": "scoreboard",
            "is_shown": True,
            "data": {"sport": "nfl", "state": state},
        }
        for index in range(game_count)
    ]
    return TickerResponse.from_payload(
        {
            "api_version": "v2",
            "snapshot": {"ticker_id": "ticker-1", "revision": 1, "observed_at": "2026-08-11T00:00:00+00:00", "stale": False},
            "settings": {"mode": mode, "sports_presentation": presentation, "pinned_content_id": "game" if presentation == "pinned" else "", "live_delay_mode": live_delay_mode, "live_delay_seconds": live_delay_seconds, "brightness": 75, "scroll_speed": 0.04, "inverted": True},
            "content": {"sports": games},
            "events": {"alerts": [{"event_id": alert["id"], "kind": "score", "payload": alert} for alert in alerts], "news": []}, "health": {"provider": "refresh", "healthy": True, "error": None},
            "meta": {"pairing": {"paired": True, "code": None}},
        }
    )


def _runtime(clock: list[float], wall=None) -> TickerRuntime:
    wall_time = wall or datetime(2026, 8, 11, tzinfo=timezone.utc)
    return TickerRuntime(
        monotonic=lambda: clock[0],
        wall_clock=lambda: wall_time[0] if isinstance(wall_time, list) else wall_time,
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


def test_scrolling_uses_payload_interval_and_integer_offsets() -> None:
    clock = [0.0]
    runtime = _runtime(clock)
    snapshot = runtime.accept_response(_response())
    runtime.install_strip(snapshot.strip_key, StripLayout(10, (StripSegment("game", 10),)))

    frames = tuple(runtime.next_frame() for _ in range(3))

    assert tuple(frame.kind for frame in frames) == (FrameKind.SCROLL,) * 3
    assert tuple(frame.interval for frame in frames) == (0.04,) * 3
    assert tuple(frame.scroll_offset for frame in frames) == (0, 1, 2)


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


def test_april_fools_ads_are_controller_only_and_ignore_live_delay() -> None:
    clock = [0.0]
    wall = [datetime(2026, 4, 1, 12, 0, tzinfo=timezone.utc)]
    runtime = _runtime(clock, wall)
    response = _response(game_count=12, live_delay_mode=False, live_delay_seconds=0)

    snapshot = runtime.accept_response(response)
    ads = [item for item in snapshot.content if item.type == "fan_duel_joke_ad"]

    assert not any(item.kind == "fan_duel_joke_ad" for item in response.content)
    assert len(ads) == 4
    assert [index for index, item in enumerate(snapshot.content) if item.type == "fan_duel_joke_ad"] == [3, 7, 11, 15]
    assert all(item.data["detail"] == "PARODY" for item in ads)
    assert all(item.data["tagline"] != "KALSHI" for item in ads)


def test_april_fools_ads_change_at_midnight_and_stop_after_april_first() -> None:
    clock = [0.0]
    wall = [datetime(2026, 3, 31, 23, 59, tzinfo=timezone.utc)]
    runtime = _runtime(clock, wall)
    response = _response(game_count=6)

    snapshot = runtime.accept_response(response)
    assert not any(item.type == "fan_duel_joke_ad" for item in snapshot.content)

    wall[0] = datetime(2026, 4, 1, 0, 0, tzinfo=timezone.utc)
    assert runtime.refresh_local_date() is True
    april_snapshot = runtime.snapshot
    assert april_snapshot is not None
    assert len([item for item in april_snapshot.content if item.type == "fan_duel_joke_ad"]) == 2
    assert april_snapshot.strip_key != snapshot.strip_key

    wall[0] = datetime(2026, 4, 2, 0, 0, tzinfo=timezone.utc)
    assert runtime.refresh_local_date() is True
    assert not any(item.type == "fan_duel_joke_ad" for item in runtime.snapshot.content)


def test_april_fools_ads_do_not_enter_pinned_presentation() -> None:
    clock = [0.0]
    wall = [datetime(2026, 4, 1, 12, 0, tzinfo=timezone.utc)]
    runtime = _runtime(clock, wall)

    snapshot = runtime.accept_response(_response(presentation="pinned", game_count=6))

    assert not any(item.type == "fan_duel_joke_ad" for item in snapshot.content)


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


def test_score_alert_stays_on_the_led_for_eight_seconds() -> None:
    clock = [0.0]
    runtime = _runtime(clock)
    runtime.accept_response(_response(alerts=({"id": "alert-1", "headline": "RBI SINGLE"},)))

    assert runtime.next_frame().kind is FrameKind.SCORE_ALERT
    clock[0] = 7.99
    assert runtime.next_frame().kind is FrameKind.SCORE_ALERT
    clock[0] = 8.0
    assert runtime.next_frame().kind is not FrameKind.SCORE_ALERT


def test_score_alerts_queue_in_fifo_order_for_full_residence() -> None:
    clock = [0.0]
    runtime = _runtime(clock)
    runtime.accept_response(_response(alerts=(
        {"id": "alert-1", "headline": "RBI SINGLE"},
        {"id": "alert-2", "headline": "2-RUN HOME RUN"},
    )))

    assert runtime.next_frame().alert["id"] == "alert-1"
    clock[0] = 7.99
    assert runtime.next_frame().alert["id"] == "alert-1"
    clock[0] = 8.0
    assert runtime.next_frame().alert["id"] == "alert-2"
    clock[0] = 15.99
    assert runtime.next_frame().alert["id"] == "alert-2"
    clock[0] = 16.0
    assert runtime.next_frame().kind is not FrameKind.SCORE_ALERT
