"""Drive V2 ticker controls without an iOS build."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

_REPOSITORY = Path(__file__).resolve().parents[1]
if str(_REPOSITORY) not in sys.path:
    sys.path.insert(0, str(_REPOSITORY))

from sports_ticker.projections import select_display_content
from sports_ticker.application import SnapshotStore
from sports_ticker.domain import ContentItem, DisplaySettings, TickerSnapshot
from ticker_core.protocol import TickerResponse
from ticker_core.runtime import TickerRuntime, classify_content


_SETTINGS_FIELDS = (
    "active_sports",
    "my_teams",
    "mode",
    "sports_filter",
    "sports_presentation",
    "pinned_content_id",
    "brightness",
    "inverted",
    "timezone",
    "weather_city",
    "weather_lat",
    "weather_lon",
    "airport_code_iata",
    "airport_code_icao",
    "airport_name",
    "track_flight_id",
    "track_guest_name",
    "live_delay_mode",
    "live_delay_seconds",
    "scroll_seamless",
    "scroll_speed",
    "score_alerts",
)


@dataclass(slots=True)
class V2ControlHarness:
    """Mirror the app's V2 control contract with explicit state changes."""

    base_url: str
    ticker_id: str
    controller_token: str = ""
    session: requests.Session = field(default_factory=requests.Session)
    settings: dict[str, Any] = field(default_factory=dict)

    @property
    def data_url(self) -> str:
        return f"{self.base_url.rstrip('/')}/api/v2/tickers/{self.ticker_id}/data"

    @property
    def ticker_url(self) -> str:
        return f"{self.base_url.rstrip('/')}/api/v2/tickers/{self.ticker_id}"

    def load(self) -> Mapping[str, Any]:
        """Load the server settings that the iOS app edits."""

        response = self.session.get(self.data_url, timeout=10)
        response.raise_for_status()
        payload = _object(response.json(), "data response")
        self.settings = _settings(payload)
        return payload

    def set_sports_filter(self, value: str) -> Mapping[str, Any]:
        """Set all, live, or my_teams through the real V2 settings route."""

        if value not in {"all", "live", "my_teams"}:
            raise ValueError("sports filter must be all, live, or my_teams")
        self.settings["sports_filter"] = value
        return self.save()

    def pin(self, content_id: str) -> Mapping[str, Any]:
        """Pin one sports item through the same V2 fields as the app."""

        identifier = str(content_id).strip()
        if not identifier:
            raise ValueError("content id must not be empty")
        self.settings.update(
            {
                "mode": "sports",
                "sports_presentation": "pinned",
                "pinned_content_id": identifier,
            }
        )
        return self.save()

    def unpin(self) -> Mapping[str, Any]:
        """Return sports to rotation with no pinned content id."""

        self.settings.update(
            {"sports_presentation": "rotation", "pinned_content_id": ""}
        )
        return self.save()

    def set_live_delay(self, seconds: int | None) -> Mapping[str, Any]:
        """Enable one bounded source delay or disable it with None."""

        if seconds is None:
            self.settings["live_delay_mode"] = False
            return self.save()
        if seconds < 15 or seconds > 120 or seconds % 15:
            raise ValueError("live delay must be 15 through 120 seconds in 15-second steps")
        self.settings["live_delay_mode"] = True
        self.settings["live_delay_seconds"] = seconds
        return self.save()

    def save(self) -> Mapping[str, Any]:
        """Write one complete V2 display settings document."""

        if not self.settings:
            raise RuntimeError("load settings before saving")
        body = {key: self.settings[key] for key in _SETTINGS_FIELDS if key in self.settings}
        headers = {"Authorization": f"Bearer {self.controller_token}"} if self.controller_token else {}
        response = self.session.patch(
            self.ticker_url,
            json={"display_settings": body},
            headers=headers,
            timeout=10,
        )
        response.raise_for_status()
        saved = _object(response.json(), "ticker response")
        self.settings = _object(saved.get("display_settings"), "display settings")
        return saved


def _object(value: object, name: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{name} must be an object")
    return dict(value)


def _settings(payload: Mapping[str, Any]) -> dict[str, Any]:
    return _object(payload.get("settings"), "settings")


def _content() -> dict[str, list[dict[str, Any]]]:
    return {
        "sports": [
            {
                "id": "nfl-live",
                "family": "sports",
                "kind": "scoreboard",
                "is_shown": True,
                "data": {"sport": "nfl", "state": "in", "away_abbr": "NYG", "home_abbr": "DAL"},
            },
            {
                "id": "nfl-later",
                "family": "sports",
                "kind": "scoreboard",
                "is_shown": True,
                "data": {"sport": "nfl", "state": "pre", "away_abbr": "PHI", "home_abbr": "WAS"},
            },
        ]
    }


def _response(content: Mapping[str, object], settings: Mapping[str, object]) -> TickerResponse:
    return TickerResponse.from_payload(
        {
            "api_version": "v2",
            "snapshot": {"ticker_id": "harness", "revision": 1, "observed_at": "2026-08-14T00:00:00+00:00", "stale": False},
            "settings": {"brightness": 100, "scroll_speed": 0.03, "inverted": False, **settings},
            "content": content,
            "events": {"alerts": [], "news": []},
            "health": {"provider": "harness", "healthy": True, "error": None},
            "meta": {"pairing": {"paired": True, "code": None}},
        }
    )


def run_self_test() -> None:
    """Exercise the V2 filter, pin, unpin, and strip-change contract."""

    source = _content()
    base = {"mode": "sports", "sports_presentation": "rotation", "pinned_content_id": ""}
    live = select_display_content(source, {**base, "sports_filter": "live"})
    no_live_source = _content()
    no_live_source["sports"][0]["data"]["state"] = "pre"
    empty_live = select_display_content(no_live_source, {**base, "sports_filter": "live"})
    all_items = select_display_content(source, {**base, "sports_filter": "all"})
    my_teams = select_display_content(source, {**base, "sports_filter": "my_teams", "my_teams": ["nfl:was"]})
    pinned = select_display_content(source, {**base, "pinned_content_id": "nfl-later"})

    assert [item["is_shown"] for item in live["sports"]] == [True, False]
    assert [item["is_shown"] for item in empty_live["sports"]] == [False, False]
    assert [item["is_shown"] for item in all_items["sports"]] == [True, True]
    assert [item["is_shown"] for item in my_teams["sports"]] == [False, True]
    assert [item["is_shown"] for item in pinned["sports"]] == [False, True]

    empty_response = _response(empty_live, {**base, "sports_filter": "live"})
    all_response = _response(all_items, {**base, "sports_filter": "all"})
    assert empty_response.payload_key != all_response.payload_key
    assert classify_content(empty_response.content, "sports").scrolling == ()
    assert len(classify_content(all_response.content, "sports").scrolling) == 2
    pinned_response = _response(
        pinned,
        {**base, "sports_presentation": "pinned", "pinned_content_id": "nfl-later"},
    )
    pinned_items = classify_content(
        pinned_response.content,
        "sports",
        sports_presentation="pinned",
        pinned_content_id="nfl-later",
    )
    assert [item.id for item in pinned_items.static] == ["nfl-later"]
    clock = [0.0]
    runtime = TickerRuntime(
        monotonic=lambda: clock[0],
        wall_clock=lambda: datetime(2026, 8, 14, tzinfo=timezone.utc),
    )
    empty_snapshot = runtime.accept_response(empty_response)
    all_snapshot = runtime.accept_response(all_response)
    assert empty_snapshot.strip_key != all_snapshot.strip_key

    delayed_clock = [0.0]
    store = SnapshotStore(clock=lambda: delayed_clock[0])
    first = TickerSnapshot(
        ticker_id="harness",
        revision=0,
        observed_at=datetime(2026, 8, 14, tzinfo=timezone.utc),
        content=(ContentItem("score", "sports", "scoreboard", data={"home_score": "1"}),),
        alerts=(),
        news=(),
        effective_settings=DisplaySettings(live_delay_mode=True, live_delay_seconds=45),
    )
    store.replace(first)
    delayed_clock[0] = 50.0
    second = TickerSnapshot(
        ticker_id="harness",
        revision=0,
        observed_at=datetime(2026, 8, 14, tzinfo=timezone.utc),
        content=(ContentItem("score", "sports", "scoreboard", data={"home_score": "2"}),),
        alerts=(),
        news=(),
        effective_settings=first.effective_settings,
    )
    store.replace(second)
    delayed_clock[0] = 60.0
    delayed = store.get_delayed("harness", 45)
    assert delayed is not None and delayed.content[0].data["home_score"] == "1"
    print("PASS: filters, pin, unpin, strip identity, and live delay")


def main() -> None:
    """Run local contract checks or mutate one paired ticker through V2."""

    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--base-url")
    parser.add_argument("--ticker-id")
    parser.add_argument("--controller-token", default="")
    parser.add_argument("--filter", choices=("all", "live", "my_teams"))
    parser.add_argument("--pin")
    parser.add_argument("--unpin", action="store_true")
    parser.add_argument("--live-delay", type=int)
    parser.add_argument("--disable-live-delay", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        run_self_test()
        return
    if not args.base_url or not args.ticker_id:
        parser.error("--base-url and --ticker-id are required without --self-test")
    requested = sum(bool(value) for value in (args.filter, args.pin, args.unpin, args.live_delay is not None, args.disable_live_delay))
    if requested > 1:
        parser.error("select one control action")
    control = V2ControlHarness(args.base_url, args.ticker_id, args.controller_token)
    payload = control.load()
    if args.filter:
        control.set_sports_filter(args.filter)
    elif args.pin:
        control.pin(args.pin)
    elif args.unpin:
        control.unpin()
    elif args.live_delay is not None:
        control.set_live_delay(args.live_delay)
    elif args.disable_live_delay:
        control.set_live_delay(None)
    else:
        print(json.dumps(payload, indent=2))
        return
    print(json.dumps(control.load(), indent=2))


if __name__ == "__main__":
    main()
