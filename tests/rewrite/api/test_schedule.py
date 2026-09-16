"""Verify the shared weekly schedule API and effective mode precedence."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from sports_ticker.bootstrap_v2 import create_backend_application
from sports_ticker.domain import ContentItem, DisplaySettings, TickerSnapshot


pytestmark = pytest.mark.critical


def _register_and_exchange(client, ticker_id: str) -> str:
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


def test_schedule_routes_use_the_server_fleet_and_persist_weekly_rules(tmp_path) -> None:
    """Load and edit shared schedule rules from the server-owned fleet."""

    app = create_backend_application(tmp_path / "ticker.sqlite3", [], scheduler=None)
    try:
        client = app.test_client()
        _register_and_exchange(client, "schedule-pi")

        initial = client.get("/api/v2/schedule")
        assert initial.status_code == 200
        assert initial.get_json()["tickers"] == [
            {"id": "schedule-pi", "name": "schedule-pi"}
        ]

        block = client.post(
            "/api/v2/schedule/blocks",
            json={
                "day_group": "weekdays",
                "start_minute": 480,
                "end_minute": 600,
                "mode": "weather",
                "enabled": True,
            },
        )
        assert block.status_code == 201
        block_id = block.get_json()["id"]

        overlap = client.post(
            "/api/v2/schedule/blocks",
            json={
                "day_group": "weekdays",
                "start_minute": 540,
                "end_minute": 660,
                "mode": "clock",
            },
        )
        assert overlap.status_code == 400
        assert "cannot overlap" in overlap.get_json()["error"]["message"]

        condition = client.post(
            "/api/v2/schedule/conditions",
            json={"kind": "live_games", "threshold": 2, "mode": "sports"},
        )
        assert condition.status_code == 201
        condition_id = condition.get_json()["id"]

        document = client.get("/api/v2/schedule")
        assert document.status_code == 200
        payload = document.get_json()
        assert payload["timezone_policy"] == "ticker"
        assert payload["day_groups"] == ["weekdays", "weekends"]
        assert [item["id"] for item in payload["blocks"]["weekdays"]] == [block_id]
        assert [item["id"] for item in payload["conditions"]] == [condition_id]

        deleted = client.delete(
            f"/api/v2/schedule/blocks/{block_id}"
        )
        assert deleted.status_code == 200
        assert client.delete(
            f"/api/v2/schedule/conditions/{condition_id}"
        ).status_code == 200
        assert client.get("/api/v2/schedule").get_json()["blocks"] == {
            "weekdays": [],
            "weekends": [],
        }
    finally:
        app.extensions["sports_ticker.backend_application"].close()


def test_schedule_uses_ticker_timezone_condition_priority_and_app_override(tmp_path) -> None:
    """Apply local time rules, then live-game conditions, then the app override."""

    now = datetime(2026, 9, 16, 14, 30, tzinfo=timezone.utc)
    app = create_backend_application(
        tmp_path / "ticker.sqlite3",
        [],
        scheduler=None,
        clock=lambda: now.timestamp(),
    )
    try:
        client = app.test_client()
        token = _register_and_exchange(client, "effective-pi")
        _register_and_exchange(client, "other-effective-pi")
        headers = {"Authorization": f"Bearer {token}"}
        backend = app.extensions["sports_ticker.backend_application"]
        backend.update_ticker(
            "effective-pi",
            display_settings={"timezone": "America/New_York"},
        )
        backend.create_schedule_block(
            day_group="weekdays",
            start_minute=600,
            end_minute=660,
            mode="weather",
        )

        status = backend.schedule_status("effective-pi")
        assert status["source"] == "time"
        assert status["mode"] == "weather"
        assert status["local_time"] == "10:30"

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
                observed_at=now,
                content=(live_game,),
                alerts=(),
                news=(),
                effective_settings=DisplaySettings(),
            )
        )
        backend.create_schedule_condition(
            kind="live_games",
            threshold=1,
            mode="clock",
        )

        status = backend.schedule_status("effective-pi")
        assert status["source"] == "condition"
        assert status["mode"] == "clock"
        assert status["live_games"] == 1
        assert status["scheduled_mode"] == "clock"
        assert backend.schedule_status("other-effective-pi")["mode"] == "clock"
        assert backend.schedule_status("other-effective-pi")["source"] == "condition"
        projected = client.get("/api/v2/tickers/effective-pi/data")
        assert projected.status_code == 200
        assert projected.get_json()["settings"]["mode"] == "clock"
        assert projected.get_json()["meta"]["schedule"]["source"] == "condition"

        override = client.patch(
            "/api/v2/tickers/effective-pi",
            headers=headers,
            json={"display_settings": {"mode": "music"}, "schedule_override": True},
        )
        assert override.status_code == 200
        assert override.get_json()["schedule_override"] is True
        status = backend.schedule_status("effective-pi")
        assert status["source"] == "app_override"
        assert status["mode"] == "music"
        assert client.get("/api/v2/tickers/effective-pi/data").get_json()["settings"]["mode"] == "music"

        clear = client.patch(
            "/api/v2/tickers/effective-pi",
            headers=headers,
            json={"schedule_override": False},
        )
        assert clear.status_code == 200
        assert clear.get_json()["schedule_override"] is False
        assert backend.schedule_status("effective-pi")["source"] == "condition"
    finally:
        app.extensions["sports_ticker.backend_application"].close()


def test_schedule_page_exposes_both_timeline_lanes_and_mode_palette(tmp_path) -> None:
    """Expose the browser editor without leaking ticker data into its initial HTML."""

    app = create_backend_application(tmp_path / "ticker.sqlite3", [], scheduler=None)
    try:
        client = app.test_client()
        response = app.test_client().get("/schedule")
        assert response.status_code == 200
        source = response.get_data(as_text=True)
        assert 'data-day-group="weekdays"' in source
        assert 'data-day-group="weekends"' in source
        assert 'data-mode="sports"' in source
        assert 'href="/dashboard/static/dashboard_v2/style.css?v=' in source
        assert 'href="/dashboard/static/dashboard_v2/schedule.css?v=' in source
        assert 'src="/dashboard/static/dashboard_v2/schedule.js?v=' in source
        assert 'draggable="true"' not in source
        assert "schedule-pi" not in source
        assert client.get("/dashboard/static/dashboard_v2/schedule.js").status_code == 200
        assert client.get("/dashboard/static/dashboard_v2/schedule.css").status_code == 200
        script = client.get("/dashboard/static/dashboard_v2/schedule.js").get_data(as_text=True)
        assert 'button.addEventListener("pointerdown"' in script
        assert 'block.addEventListener("pointerdown"' in script
        assert "day_group: currentGroup" in script
    finally:
        app.extensions["sports_ticker.backend_application"].close()
