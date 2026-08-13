from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Mapping

import pytest

from ticker_core.runtime import (
    FrameKind,
    RuntimeConfig,
    StripLayout,
    StripSegment,
    TickerRuntime,
    classify_content,
    remap_strip_offset,
)
from ticker_core.protocol import TickerResponse


class Clocks:
    def __init__(self) -> None:
        self.monotonic_value = 0.0
        self.wall_value = datetime(2026, 8, 11, 12, 0, tzinfo=timezone.utc)

    def monotonic(self) -> float:
        return self.monotonic_value

    def wall(self) -> datetime:
        return self.wall_value

    def advance(self, seconds: float) -> None:
        self.monotonic_value += seconds


@dataclass(frozen=True)
class Item:
    id: str
    data: Mapping[str, object]


@dataclass(frozen=True)
class Response:
    status: str = "active"
    pairing_code: str = "------"
    local_config: Mapping[str, object] = None  # type: ignore[assignment]
    global_config: Mapping[str, object] = None  # type: ignore[assignment]
    content: tuple[Item, ...] = ()
    alerts: tuple[Item, ...] = ()
    news: tuple[Item, ...] = ()
    payload_key: str = "first"

    def __post_init__(self) -> None:
        if self.local_config is None:
            object.__setattr__(self, "local_config", {"mode": "sports", "brightness": 100, "scroll_speed": 0.05})
        if self.global_config is None:
            object.__setattr__(self, "global_config", {})


def item(identifier: str, item_type: str = "game", sport: str = "nba", **extra: object) -> Item:
    return Item(identifier, {"id": identifier, "type": item_type, "sport": sport, **extra})


def runtime(clocks: Clocks, **config: object) -> TickerRuntime:
    return TickerRuntime(
        monotonic=clocks.monotonic,
        wall_clock=clocks.wall,
        config=RuntimeConfig(offline_after=10, static_hold=3, alert_duration=2, news_duration=3, **config),
    )


def test_content_classification_aggregates_flight_items() -> None:
    result = classify_content(
        (item("weather", "flight_weather", "flight"), item("arrive", "flight_arrival", "flight"), item("score")),
        "flights",
    )

    assert not result.scrolling
    assert [entry.id for entry in result.static] == ["airport_hud"]
    assert result.static[0].data["arrivals"][0]["id"] == "arrive"


@pytest.mark.parametrize(
    ("mode", "entry", "scrolling", "static"),
    [
        ("sports", item("game"), True, False),
        ("sports_full", item("race", "racing", "f1"), False, True),
        ("weather", item("weather", "weather"), False, True),
        ("music", item("music", "music", "music"), False, True),
        ("flights", item("visitor", "flight_visitor", "flight"), False, True),
        ("clock", item("clock", "game", "clock_local"), False, True),
    ],
)
def test_content_classification_gates_content_by_canonical_mode(mode: str, entry: Item, scrolling: bool, static: bool) -> None:
    result = classify_content((item(entry.id, str(entry.data["type"]), str(entry.data["sport"])),), mode)

    assert bool(result.scrolling) is scrolling
    assert bool(result.static) is static


def test_accept_response_retains_payload_and_acknowledges_mode_override() -> None:
    clocks = Clocks()
    ticker = runtime(clocks)
    ticker.request_mode("clock")
    assert ticker.mode == "clock"
    assert ticker.take_mode_request().mode == "clock"

    ticker.accept_response(Response(local_config={"mode": "sports", "brightness": 45, "scroll_speed": 0.2, "inverted": True}))
    assert ticker.mode == "clock"
    frame = ticker.next_frame()
    assert frame.brightness == 45
    assert frame.inverted is True

    ticker.accept_response(Response(payload_key="ack", local_config={"mode": "clock", "brightness": 45, "scroll_speed": 0.2}))
    ticker.accept_response(Response(payload_key="server", local_config={"mode": "weather", "brightness": 45, "scroll_speed": 0.2}))
    assert ticker.mode == "weather"
    assert ticker.next_frame().mode == "weather"


def test_runtime_accepts_the_protocol_response_without_importing_it() -> None:
    clocks = Clocks()
    ticker = runtime(clocks)
    response = TickerResponse.from_payload(
        {
            "status": "ok",
            "local_config": {"mode": "sports", "brightness": 75, "scroll_speed": 0.04, "inverted": False},
            "global_config": {},
            "content": {"sports": [{"id": "game", "type": "game", "sport": "nba"}]},
            "alerts": [],
            "news": [],
        }
    )

    snapshot = ticker.accept_response(response)

    assert snapshot.key == response.payload_key
    assert snapshot.content[0].id == "game"
    assert snapshot.brightness == 0.75


def test_priority_order_is_update_pairing_sleep_then_offline() -> None:
    clocks = Clocks()
    ticker = runtime(clocks)
    ticker.accept_response(Response(status="pairing", pairing_code="123456", global_config={"update": True, "update_version": "r100"}))
    assert ticker.next_frame().kind is FrameKind.UPDATE
    assert ticker.take_update_request().version == "r100"
    ticker.finish_update()
    assert ticker.next_frame().kind is FrameKind.PAIRING

    ticker.accept_response(Response(local_config={"mode": "sports", "brightness": 0, "scroll_speed": 0.05}))
    assert ticker.next_frame().kind is FrameKind.SLEEP
    clocks.advance(11)
    assert ticker.next_frame().kind is FrameKind.SLEEP

    ticker.accept_response(Response(local_config={"mode": "sports", "brightness": 100, "scroll_speed": 0.05}))
    ticker.mark_disconnected(expires_in=10)
    clocks.advance(11)
    assert ticker.next_frame().kind is FrameKind.OFFLINE


def test_alerts_dedupe_expire_and_preempt_content() -> None:
    clocks = Clocks()
    ticker = runtime(clocks)
    alert = item("run-1", headline="HOME RUN")
    ticker.accept_response(Response(content=(item("game"),), alerts=(alert,)))
    ticker.install_strip("first", StripLayout(10, (StripSegment("game", 10),)))
    alert_frame = ticker.next_frame()
    assert alert_frame.kind is FrameKind.SCORE_ALERT
    assert alert_frame.alert_elapsed == 0
    clocks.advance(2.1)
    assert ticker.next_frame().kind is FrameKind.SCROLL

    ticker.accept_response(Response(payload_key="same", content=(item("game"),), alerts=(alert,)))
    ticker.install_strip("same", StripLayout(10, (StripSegment("game", 10),)))
    assert ticker.next_frame().kind is FrameKind.SCROLL


def test_expired_alert_is_dropped_before_display() -> None:
    clocks = Clocks()
    ticker = runtime(clocks, alert_max_age=1)
    ticker.accept_response(Response(content=(item("game"),), alerts=(item("old"),)))
    clocks.advance(1.1)
    ticker.install_strip("first", StripLayout(3, (StripSegment("game", 3),)))

    assert ticker.next_frame().kind is FrameKind.SCROLL


def test_news_attaches_to_a_static_mode_and_expires() -> None:
    clocks = Clocks()
    ticker = runtime(clocks)
    ticker.accept_response(Response(
        local_config={"mode": "weather", "brightness": 100, "scroll_speed": 0.05},
        content=(item("weather", "weather", "weather"),),
        news=(item("trade", text="A to B"),),
    ))

    frame = ticker.next_frame()
    assert frame.kind is FrameKind.STATIC
    assert frame.news["id"] == "trade"
    assert frame.news_elapsed == 0
    clocks.advance(3.1)
    assert ticker.next_frame().news is None


def test_identical_poll_keeps_the_current_static_page_timing() -> None:
    clocks = Clocks()
    ticker = runtime(clocks)
    full = {"mode": "sports_full", "brightness": 100, "scroll_speed": 0.05}
    response = Response(local_config=full, content=(item("a"), item("b")))
    ticker.accept_response(response)
    assert ticker.next_frame().content.id == "a"

    clocks.advance(1)
    ticker.accept_response(response)
    clocks.advance(2.1)

    assert ticker.next_frame().content.id == "b"


def test_mode_rejects_noncanonical_values() -> None:
    clocks = Clocks()
    ticker = runtime(clocks)

    with pytest.raises(ValueError, match="Unsupported ticker mode"):
        ticker.request_mode("f1_full")


def test_disconnect_lifecycle_retains_content_then_recovers() -> None:
    clocks = Clocks()
    ticker = runtime(clocks)
    ticker.accept_response(Response(content=(item("game"),)))
    ticker.install_strip("first", StripLayout(3, (StripSegment("game", 3),)))
    assert ticker.next_frame().connection_lost is False

    ticker.mark_disconnected(expires_in=5)
    disconnected = ticker.next_frame()
    assert disconnected.kind is FrameKind.SCROLL
    assert disconnected.connection_lost is True
    assert disconnected.disconnected_for == 0
    clocks.advance(5.1)
    assert ticker.next_frame().kind is FrameKind.OFFLINE

    ticker.accept_response(Response(payload_key="recovered", content=(item("game"),)))
    ticker.install_strip("recovered", StripLayout(3, (StripSegment("game", 3),)))
    recovered = ticker.next_frame()
    assert recovered.connection_lost is False


def test_strip_replacement_tracks_visible_item_then_falls_back_to_progress() -> None:
    old = StripLayout(10, (StripSegment("a", 4), StripSegment("b", 6)))
    same = StripLayout(12, (StripSegment("b", 8), StripSegment("a", 4)))
    missing = StripLayout(20, (StripSegment("z", 20),))

    assert remap_strip_offset(old, 6, same) == 2
    assert remap_strip_offset(old, 5, missing) == 10


def test_install_strip_rejects_stale_work_and_preserves_offset() -> None:
    clocks = Clocks()
    ticker = runtime(clocks)
    ticker.accept_response(Response(content=(item("a"), item("b", "weather"))))
    first = StripLayout(4, (StripSegment("a", 4),))
    assert ticker.install_strip("first", first) is True
    ticker.next_frame()
    ticker.next_frame()

    ticker.accept_response(Response(payload_key="next", content=(item("a"), item("b", "weather"))))
    assert ticker.install_strip("first", first) is False
    assert ticker.install_strip("next", StripLayout(8, (StripSegment("a", 8),))) is True
    assert ticker.next_frame().scroll_offset == 2


def test_stop_clears_work_and_never_emits_a_render_scene() -> None:
    clocks = Clocks()
    ticker = runtime(clocks)
    ticker.accept_response(Response(alerts=(item("alert"),)))
    ticker.stop()

    stopped = ticker.next_frame()
    assert stopped.kind is FrameKind.STOPPED
    assert stopped.interval == 0
