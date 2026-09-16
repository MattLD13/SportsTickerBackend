"""Verify per-ticker weekly schedules, conditions, precedence, and expiry."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from sports_ticker.bootstrap_v2 import create_backend_application
from sports_ticker.domain import ContentItem, DisplaySettings, TickerSnapshot


pytestmark = pytest.mark.critical


def _register_and_exchange(client, ticker_id: str) -> str:
    """Register one ticker and return its controller token."""

    registration = client.post(
        "/api/v2/devices/register",
        json={"device_id": ticker_id, "name": ticker_id, "metadata": {}},
    )
    assert registration.status_code == 201
    exchange = client.post(
        "/api/v2/pairings/exchange",
        json={"pairing_code": registration.get_json()["pairing_code"]},
    )
    assert exchange.status_code == 201
    return exchange.get_json()["controller_token"]


def test_schedule_routes_are_ticker_owned_and_use_weekly_days(tmp_path) -> None:
    """Persist recurring rules under one ticker and reject the removed global endpoint."""

    app = create_backend_application(tmp_path / "ticker.sqlite3", [], scheduler=None)
    try:
        client = app.test_client()
        token = _register_and_exchange(client, "schedule-pi")
        _register_and_exchange(client, "other-schedule-pi")
        headers = {"Authorization": f"Bearer {token}"}

        assert client.get("/api/v2/schedule").status_code == 404
        initial = client.get("/api/v2/tickers/schedule-pi/schedule", headers=headers)
        assert initial.status_code == 200
        assert initial.get_json()["blocks"] == []
        assert client.get(
            "/api/v2/tickers/other-schedule-pi/schedule",
            headers=headers,
        ).status_code == 403

        block = client.post(
            "/api/v2/tickers/schedule-pi/schedule/blocks",
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
            f"/api/v2/tickers/schedule-pi/schedule/blocks/{block_id}",
            headers=headers,
            json={"end_minute": 720},
        )
        assert resized.status_code == 200
        assert resized.get_json()["end_minute"] == 720

        overlap = client.post(
            "/api/v2/tickers/schedule-pi/schedule/blocks",
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
            "/api/v2/tickers/schedule-pi/schedule/conditions",
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
            "/api/v2/tickers/schedule-pi/schedule",
            headers=headers,
        ).get_json()
        assert "timezone" in document
        assert [item["id"] for item in document["blocks"]] == [block_id]
        assert [item["id"] for item in document["conditions"]] == [condition_id]
        assert document["days"][0]["blocks"][0]["id"] == block_id
        assert client.get(
            "/api/v2/tickers/other-schedule-pi/schedule",
            headers=headers,
        ).status_code == 403

        assert client.delete(
            f"/api/v2/tickers/schedule-pi/schedule/blocks/{block_id}",
            headers=headers,
        ).status_code == 200
        assert client.delete(
            f"/api/v2/tickers/schedule-pi/schedule/conditions/{condition_id}",
            headers=headers,
        ).status_code == 200
    finally:
        app.extensions["sports_ticker.backend_application"].close()


def test_schedule_uses_ticker_timezone_condition_precedence_and_expiry(tmp_path) -> None:
    """Apply local time, live-game conditions, pinned precedence, and expiring app overrides."""

    now = [datetime(2026, 9, 16, 14, 30, tzinfo=timezone.utc).timestamp()]
    app = create_backend_application(
        tmp_path / "ticker.sqlite3",
        [],
        scheduler=None,
        clock=lambda: now[0],
    )
    try:
        client = app.test_client()
        token = _register_and_exchange(client, "effective-pi")
        other_token = _register_and_exchange(client, "other-effective-pi")
        headers = {"Authorization": f"Bearer {token}"}
        other_headers = {"Authorization": f"Bearer {other_token}"}
        backend = app.extensions["sports_ticker.backend_application"]
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
        projected = client.get("/api/v2/tickers/effective-pi/data")
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
            "/api/v2/tickers/effective-pi",
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
            "/api/v2/tickers/effective-pi/schedule",
            headers=headers,
        ).get_json()["effective"]["source"] == "base"
        assert client.get(
            "/api/v2/tickers/other-effective-pi/schedule",
            headers=other_headers,
        ).status_code == 200
    finally:
        app.extensions["sports_ticker.backend_application"].close()


def test_schedule_dashboard_path_is_removed(tmp_path) -> None:
    """Keep schedule ownership in the native controller instead of the former global dashboard editor."""

    app = create_backend_application(tmp_path / "ticker.sqlite3", [], scheduler=None)
    try:
        client = app.test_client()
        assert client.get("/schedule").status_code == 404
        assert client.get("/dashboard/static/dashboard_v2/schedule.js").status_code == 404
        assert client.get("/dashboard/static/dashboard_v2/schedule.css").status_code == 404
    finally:
        app.extensions["sports_ticker.backend_application"].close()
