"""Verify per-ticker weekly schedules, conditions, precedence, and expiry."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone

import pytest

from ticker.shared.domain import ContentItem, DisplaySettings, TickerSnapshot
from ticker.server.offline import create_offline_application

pytestmark = pytest.mark.critical


def device_token(ticker_id: str) -> str:
    """Return the device token of one test device. The token alone names the ticker."""
    return hashlib.sha256(ticker_id.encode()).hexdigest()


def test_live_rule_counts_only_its_ticker_and_reverts_below_threshold(tmp_path) -> None:
    """Exclude other tickers, duplicates, hidden records, and stale snapshots."""
    now = [datetime(2026, 10, 20, 20, tzinfo=timezone.utc).timestamp()]
    app = create_offline_application(tmp_path / "ticker.sqlite3", [], clock=lambda: now[0])
    try:
        client = app.test_client()
        token = _register_and_exchange(client, "one-live")
        _register_and_exchange(client, "other-games")
        backend = app.extensions["ticker.application"]
        backend.update_ticker("one-live", display_settings={"mode": "sports", "sports_filter": "all"})
        backend.create_schedule_condition("one-live", kind="live_games", threshold=1, operator="gt",
                                          when_mode="sports", action_sports_filter="live", ignore_pinned=True)

        def publish(identifier, items, offset=0):
            backend.snapshot_store.replace(TickerSnapshot(ticker_id=identifier, revision=0,
                observed_at=datetime.fromtimestamp(now[0] + offset, tz=timezone.utc), content=tuple(items),
                alerts=(), news=(), effective_settings=DisplaySettings()))

        def game(identifier, *, state="in", shown=True, family="sports"):
            return ContentItem(id=identifier, family=family, kind="scoreboard", is_shown=shown,
                               data={"sport": "nba", "state": state})

        publish("one-live", [game("own"), game("own"), game("hidden", shown=False),
                             game("pregame", state="pre"), game("weather", family="weather")])
        publish("other-games", [game(str(i)) for i in range(10)])
        status = backend.schedule_status("one-live")
        assert status["live_games"] == 1
        assert status["sports_filter"] == "all"
        assert status["source"] == "base"
        document = client.get("/tickers/one-live/schedule", headers={"Authorization": f"Bearer {token}"}).get_json()
        assert document["live_games"] == document["effective"]["live_games"] == 1
        publish("one-live", [game("own"), game("second", state="half")])
        assert backend.schedule_status("one-live")["source"] == "condition"
        assert backend.schedule_status("one-live")["sports_filter"] == "live"
        publish("one-live", [game("own"), game("second", state="post")])
        assert backend.schedule_status("one-live")["sports_filter"] == "all"
        for age in [-121, 1]:
            publish("one-live", [game("own"), game("second")], offset=age)
            assert backend.schedule_status("one-live")["live_games"] == 0
        assert backend.schedule_service.live_game_count("missing") == 0
    finally:
        app.extensions["ticker.application"].close()


def test_schedule_presence_uses_only_enabled_rules_for_this_ticker(tmp_path) -> None:
    """Keep empty and disabled schedules distinct from inactive enabled schedules."""
    app = create_offline_application(tmp_path / "ticker.sqlite3", [])
    try:
        client = app.test_client()
        _register_and_exchange(client, "empty")
        _register_and_exchange(client, "configured")
        backend = app.extensions["ticker.application"]
        assert backend.schedule_status("empty")["has_enabled_rules"] is False
        block = backend.create_schedule_block("configured", days_of_week=[0], start_minute=1, end_minute=2,
                                               mode="weather", enabled=False)
        assert backend.schedule_status("configured")["has_enabled_rules"] is False
        backend.update_schedule_block("configured", block.id, enabled=True)
        assert backend.schedule_status("configured")["has_enabled_rules"] is True
        assert backend.schedule_status("empty")["has_enabled_rules"] is False
        backend.delete_schedule_block("configured", block.id)
        condition = backend.create_schedule_condition("configured", kind="live_games", threshold=5, enabled=False)
        assert backend.schedule_status("configured")["has_enabled_rules"] is False
        backend.update_schedule_condition("configured", condition.id, enabled=True)
        assert backend.schedule_status("configured")["has_enabled_rules"] is True
        backend.delete_schedule_condition("configured", condition.id)
        assert backend.schedule_status("configured")["has_enabled_rules"] is False
    finally:
        app.extensions["ticker.application"].close()


def _register_and_exchange(client, ticker_id: str) -> str:
    """Register one ticker and return its controller token."""

    registration = client.post(
        "/register",
        json={"device_id": ticker_id, "name": ticker_id, "metadata": {}},
        headers={"X-Device-Token": device_token(ticker_id)},
    )
    assert registration.status_code == 201
    exchange = client.post(
        "/pair",
        json={"pairing_code": registration.get_json()["pairing_code"]},
    )
    assert exchange.status_code == 201
    return exchange.get_json()["controller_token"]


def test_schedule_routes_are_ticker_owned_and_use_weekly_days(tmp_path) -> None:
    """Persist recurring rules under one ticker and reject the removed global endpoint."""

    app = create_offline_application(tmp_path / "ticker.sqlite3", [])
    try:
        client = app.test_client()
        token = _register_and_exchange(client, "schedule-pi")
        _register_and_exchange(client, "other-schedule-pi")
        headers = {"Authorization": f"Bearer {token}"}

        assert client.get("/api/v2/schedule").status_code == 404
        initial = client.get("/tickers/schedule-pi/schedule", headers=headers)
        assert initial.status_code == 200
        assert initial.get_json()["blocks"] == []
        assert client.get(
            "/tickers/other-schedule-pi/schedule",
            headers=headers,
        ).status_code == 403

        block = client.post(
            "/tickers/schedule-pi/schedule/blocks",
            headers=headers,
            json={
                "days_of_week": [0, 1, 2, 3, 4],
                "start_minute": 480,
                "end_minute": 600,
                "mode": "weather",
                "enabled": True,
            },
        )
        assert block.status_code == 201
        block_id = block.get_json()["id"]
        assert block.get_json()["day_names"] == [
            "monday",
            "tuesday",
            "wednesday",
            "thursday",
            "friday",
        ]

        resized = client.patch(
            f"/tickers/schedule-pi/schedule/blocks/{block_id}",
            headers=headers,
            json={"end_minute": 720},
        )
        assert resized.status_code == 200
        assert resized.get_json()["end_minute"] == 720

        overlap = client.post(
            "/tickers/schedule-pi/schedule/blocks",
            headers=headers,
            json={
                "days_of_week": [2],
                "start_minute": 540,
                "end_minute": 660,
                "mode": "clock",
            },
        )
        assert overlap.status_code == 400
        assert "cannot overlap" in overlap.get_json()["error"]["message"]

        condition = client.post(
            "/tickers/schedule-pi/schedule/conditions",
            headers=headers,
            json={
                "kind": "live_games",
                "threshold": 5,
                "operator": "gt",
                "when_mode": "sports",
                "action_sports_filter": "live",
                "ignore_pinned": True,
            },
        )
        assert condition.status_code == 201
        condition_id = condition.get_json()["id"]
        assert condition.get_json()["action_sports_filter"] == "live"

        document = client.get(
            "/tickers/schedule-pi/schedule",
            headers=headers,
        ).get_json()
        assert "timezone" in document
        assert [item["id"] for item in document["blocks"]] == [block_id]
        assert [item["id"] for item in document["conditions"]] == [condition_id]
        assert document["days"][0]["blocks"][0]["id"] == block_id
        assert client.get(
            "/tickers/other-schedule-pi/schedule",
            headers=headers,
        ).status_code == 403

        assert client.delete(
            f"/tickers/schedule-pi/schedule/blocks/{block_id}",
            headers=headers,
        ).status_code == 200
        assert client.delete(
            f"/tickers/schedule-pi/schedule/conditions/{condition_id}",
            headers=headers,
        ).status_code == 200
    finally:
        app.extensions["ticker.application"].close()


def test_schedule_uses_ticker_timezone_condition_precedence_and_expiry(tmp_path) -> None:
    """Apply local time, live-game conditions, pinned precedence, and expiring app overrides."""

    now = [datetime(2026, 9, 16, 14, 30, tzinfo=timezone.utc).timestamp()]
    app = create_offline_application(
        tmp_path / "ticker.sqlite3",
        [],
        clock=lambda: now[0],
    )
    try:
        client = app.test_client()
        token = _register_and_exchange(client, "effective-pi")
        other_token = _register_and_exchange(client, "other-effective-pi")
        headers = {"Authorization": f"Bearer {token}"}
        other_headers = {"Authorization": f"Bearer {other_token}"}
        backend = app.extensions["ticker.application"]
        backend.update_ticker(
            "effective-pi",
            display_settings={
                "timezone": "America/New_York",
                "mode": "sports",
                "sports_filter": "all",
            },
        )
        backend.create_schedule_block(
            "effective-pi",
            days_of_week=[2],
            start_minute=600,
            end_minute=660,
            mode="sports",
            sports_filter="all",
        )

        status = backend.schedule_status("effective-pi")
        assert status["source"] == "time"
        assert status["mode"] == "sports"
        assert status["local_time"] == "10:30"
        assert backend.schedule_status("other-effective-pi")["source"] == "base"

        live_game = ContentItem(
            id="live-mlb-game",
            family="sports",
            kind="scoreboard",
            data={"sport": "mlb", "state": "in"},
        )
        backend.snapshot_store.replace(
            TickerSnapshot(
                ticker_id="effective-pi",
                revision=1,
                observed_at=datetime.fromtimestamp(now[0], tz=timezone.utc),
                content=(live_game,),
                alerts=(),
                news=(),
                effective_settings=DisplaySettings(),
            )
        )
        backend.create_schedule_condition(
            "effective-pi",
            kind="live_games",
            threshold=1,
            operator="gte",
            when_mode="sports",
            action_sports_filter="live",
            ignore_pinned=True,
        )

        status = backend.schedule_status("effective-pi")
        assert status["source"] == "condition"
        assert status["mode"] == "sports"
        assert status["sports_filter"] == "live"
        assert status["live_games"] == 1
        assert backend.schedule_status("other-effective-pi")["source"] == "base"
        assert backend.schedule_status("other-effective-pi")["sports_filter"] == "all"
        projected = client.get("/data", headers={"X-Device-Token": device_token("effective-pi")})
        assert projected.status_code == 200
        assert projected.get_json()["settings"]["sports_filter"] == "live"
        assert projected.get_json()["meta"]["schedule"]["source"] == "condition"

        backend.update_ticker(
            "effective-pi",
            display_settings={
                "sports_presentation": "pinned",
                "pinned_content_id": "live-mlb-game",
            },
        )
        pinned_status = backend.schedule_status("effective-pi")
        assert pinned_status["source"] == "time"
        assert pinned_status["sports_filter"] == "all"

        override = client.patch(
            "/tickers/effective-pi",
            headers=headers,
            json={"display_settings": {"mode": "music"}, "schedule_override": True},
        )
        assert override.status_code == 200
        assert override.get_json()["schedule_override"] is True
        assert override.get_json()["schedule_override_expires_at"] > now[0]
        status = backend.schedule_status("effective-pi")
        assert status["source"] == "app_override"
        assert status["mode"] == "music"

        now[0] = datetime(2026, 9, 16, 15, 1, tzinfo=timezone.utc).timestamp()
        expired = backend.schedule_status("effective-pi")
        assert expired["source"] == "base"
        assert expired["override"] is False
        assert client.get(
            "/tickers/effective-pi/schedule",
            headers=headers,
        ).get_json()["effective"]["source"] == "base"
        assert client.get(
            "/tickers/other-effective-pi/schedule",
            headers=other_headers,
        ).status_code == 200
    finally:
        app.extensions["ticker.application"].close()


def test_schedule_dashboard_path_is_removed(tmp_path) -> None:
    """Keep schedule ownership in the native controller instead of the former global dashboard editor."""

    app = create_offline_application(tmp_path / "ticker.sqlite3", [])
    try:
        client = app.test_client()
        assert client.get("/schedule").status_code == 404
        assert client.get("/static/control/schedule.js").status_code == 404
        assert client.get("/static/control/schedule.css").status_code == 404
    finally:
        app.extensions["ticker.application"].close()
