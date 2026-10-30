"""Exercise the device bootstrap and controller ownership boundaries."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone

import pytest

from ticker.server.offline import create_offline_application
from ticker.six.app.frame_builder import FrameBuilder
from ticker.six.ui.news_banner import NewsBanner
from ticker.six.ui.score_alert import ScoreAlert
from ticker.six.ui.screens import Screens
from ticker.six.protocol import DeviceState, TickerResponse
from ticker.six.ui import CardCatalog, load_default_font_set
from ticker.six.runtime import FrameDecision, FrameKind

pytestmark = pytest.mark.critical


def device_token(ticker_id: str) -> str:
    """Return the device token of one test device. The token alone names the ticker."""
    return hashlib.sha256(ticker_id.encode()).hexdigest()


def _register(client, ticker_id: str) -> dict:
    response = client.post(
        "/register",
        json={"device_id": ticker_id, "name": ticker_id, "metadata": {}},
        headers={"X-Device-Token": device_token(ticker_id)},
    )
    assert response.status_code == 201
    return response.get_json()


def test_empty_repository_registers_pairing_snapshot_for_pi_bootstrap(tmp_path) -> None:
    """Register one unknown Pi, then parse its immediate pairing response."""

    app = create_offline_application(tmp_path / "ticker.sqlite3", [])
    try:
        client = app.test_client()
        registration = _register(client, "pi-1")

        assert registration["ticker_id"] == "pi-1"
        assert registration["paired"] is False
        assert registration["pairing_code"]
        assert registration["ticker"]["profile"]["product_family"] == "full"

        response = client.get("/data", headers={"X-Device-Token": device_token("pi-1")})
        assert response.status_code == 200
        parsed = TickerResponse.from_payload(response.get_json())
        assert parsed.status is DeviceState.PAIRING
        assert parsed.pairing_code == registration["pairing_code"]

        class Viewport:
            def frame(self, offset: int) -> object:
                del offset
                raise AssertionError("pairing frames do not read the viewport")

        class Logos:
            def get(self, value: object, size: tuple[int, int]) -> object:
                del value, size
                return None

        fonts = load_default_font_set()
        builder = FrameBuilder(
            CardCatalog(),
            Screens(fonts),
            ScoreAlert(fonts, Logos()),
            NewsBanner(),
            Viewport(),
        )
        frame = builder.build(
            FrameDecision(
                kind=FrameKind.PAIRING,
                interval=0.1,
                brightness=100,
                inverted=False,
                wall_time=datetime(2026, 8, 15, tzinfo=timezone.utc),
                mode="pairing",
                pairing_code=parsed.pairing_code,
            )
        )
        assert frame.size == (384, 32)
    finally:
        app.extensions["ticker.application"].close()


def test_partial_display_settings_patch_preserves_other_ticker_controls(tmp_path) -> None:
    """Preserve inversion when a controller patches only shared team settings."""

    app = create_offline_application(tmp_path / "ticker.sqlite3", [])
    try:
        client = app.test_client()
        registration = _register(client, "pi-settings")
        exchange = client.post(
            "/pair",
            json={"pairing_code": registration["pairing_code"]},
        )
        assert exchange.status_code == 201
        headers = {"Authorization": f"Bearer {exchange.get_json()['controller_token']}"}

        enabled = client.patch(
            "/tickers/pi-settings",
            headers=headers,
            json={"display_settings": {"inverted": True, "score_alerts": False}},
        )
        assert enabled.status_code == 200
        shared_update = client.patch(
            "/tickers/pi-settings",
            headers=headers,
            json={"display_settings": {"my_teams": ["nfl:DAL"]}},
        )

        assert shared_update.status_code == 200
        settings = shared_update.get_json()["display_settings"]
        assert settings["inverted"] is True
        assert settings["score_alerts"] is False
        assert "fan_duel_joke_ad" not in settings
        assert settings["my_teams"] == ["nfl:DAL"]
    finally:
        app.extensions["ticker.application"].close()


def test_conference_filter_patch_round_trips_without_changing_my_teams(tmp_path) -> None:
    """Persist conference filters while retaining the existing CFB team selection."""

    app = create_offline_application(tmp_path / "ticker.sqlite3", [])
    try:
        client = app.test_client()
        registration = _register(client, "pi-cfb")
        exchange = client.post(
            "/pair",
            json={"pairing_code": registration["pairing_code"]},
        )
        headers = {"Authorization": f"Bearer {exchange.get_json()['controller_token']}"}

        response = client.patch(
            "/tickers/pi-cfb",
            headers=headers,
            json={
                "display_settings": {
                    "active_sports": {"ncf_fbs:4": False},
                    "my_teams": ["ncf_fbs:TCU"],
                }
            },
        )

        assert response.status_code == 200
        settings = response.get_json()["display_settings"]
        assert settings["active_sports"]["ncf_fbs:4"] is False
        assert settings["active_conferences"] == {"ncf_fbs:4": False}
        assert settings["my_teams"] == ["ncf_fbs:TCU"]
        assert app.extensions["ticker.application"].get_ticker(
            "pi-cfb"
        ).display_settings.active_conferences == {"ncf_fbs:4": False}
    finally:
        app.extensions["ticker.application"].close()


def test_live_delay_patch_isolated_to_target_ticker(tmp_path) -> None:
    """Keep live delay changes isolated when one controller owns multiple tickers."""

    app = create_offline_application(tmp_path / "ticker.sqlite3", [])
    try:
        client = app.test_client()
        first = _register(client, "delay-one")
        first_exchange = client.post(
            "/pair",
            json={"pairing_code": first["pairing_code"]},
        )
        assert first_exchange.status_code == 201
        first_payload = first_exchange.get_json()
        second = _register(client, "delay-two")
        second_exchange = client.post(
            "/pair",
            json={
                "pairing_code": second["pairing_code"],
                "controller_group_id": first_payload["controller_group_id"],
                "controller_group_secret": first_payload["controller_group_secret"],
            },
        )
        assert second_exchange.status_code == 201
        headers = {"Authorization": f"Bearer {second_exchange.get_json()['controller_token']}"}

        other_enabled = client.patch(
            "/tickers/delay-two",
            headers=headers,
            json={"display_settings": {"live_delay_mode": True, "live_delay_seconds": 60}},
        )
        assert other_enabled.status_code == 200

        enabled = client.patch(
            "/tickers/delay-one",
            headers=headers,
            json={"display_settings": {"live_delay_mode": True, "live_delay_seconds": 120}},
        )
        assert enabled.status_code == 200

        disabled = client.patch(
            "/tickers/delay-one",
            headers=headers,
            json={"display_settings": {"live_delay_mode": False}},
        )
        assert disabled.status_code == 200
        assert disabled.get_json()["display_settings"]["live_delay_mode"] is False
        assert app.extensions["ticker.application"].get_ticker(
            "delay-two"
        ).display_settings.live_delay_mode is True
    finally:
        app.extensions["ticker.application"].close()


def test_device_registration_renews_expired_pairing_code(tmp_path) -> None:
    """Give an offline ticker a fresh code after its previous code expires."""

    now = [1_000.0]
    app = create_offline_application(tmp_path / "ticker.sqlite3", [], clock=lambda: now[0])
    try:
        client = app.test_client()
        first = _register(client, "pi-expired")
        now[0] = 2_000.0
        second_response = client.post(
            "/register",
            json={"device_id": "pi-expired", "name": "pi-expired", "metadata": {}},
            headers={"X-Device-Token": device_token("pi-expired")},
        )

        assert second_response.status_code == 200
        second = second_response.get_json()
        assert second["pairing_code"]
        assert second["pairing_code"] != first["pairing_code"]
    finally:
        app.extensions["ticker.application"].close()


def test_device_registration_renews_the_code_exposed_by_ble_session(tmp_path) -> None:
    """Keep one expired BLE code stable until the controller exchanges it."""

    now = [1_000.0]
    app = create_offline_application(tmp_path / "ticker.sqlite3", [], clock=lambda: now[0])
    try:
        client = app.test_client()
        first = _register(client, "pi-ble")
        now[0] = 2_000.0
        second_response = client.post(
            "/register",
            json={
                "device_id": "pi-ble",
                "name": "pi-ble",
                "metadata": {},
                "pairing_code": first["pairing_code"],
            },
            headers={"X-Device-Token": device_token("pi-ble")},
        )

        assert second_response.status_code == 200
        second = second_response.get_json()
        assert second["pairing_code"] == first["pairing_code"]

        exchange = client.post(
            "/pair",
            json={"pairing_code": first["pairing_code"]},
        )
        assert exchange.status_code == 201
    finally:
        app.extensions["ticker.application"].close()


def test_controller_routes_return_only_the_owner_and_protect_mutations(tmp_path) -> None:
    """Require controller authorization while leaving device routes unauthenticated."""

    app = create_offline_application(tmp_path / "ticker.sqlite3", [])
    try:
        client = app.test_client()
        first = _register(client, "pi-1")
        second = _register(client, "pi-2")
        first_exchange = client.post(
            "/pair", json={"pairing_code": first["pairing_code"]}
        )
        second_exchange = client.post(
            "/pair", json={"pairing_code": second["pairing_code"]}
        )
        first_token = first_exchange.get_json()["controller_token"]
        second_token = second_exchange.get_json()["controller_token"]

        assert client.post("/tickers", json={"ticker_id": "manual"}).status_code == 405
        assert client.get("/tickers").status_code == 401
        assert client.get(
            "/tickers", headers={"Authorization": "Bearer invalid"}
        ).status_code == 403
        listing = client.get(
            "/tickers", headers={"Authorization": f"Bearer {first_token}"}
        )
        assert listing.status_code == 200
        assert [item["ticker_id"] for item in listing.get_json()["tickers"]] == ["pi-1"]

        assert client.get(
            "/tickers/pi-2", headers={"Authorization": f"Bearer {first_token}"}
        ).status_code == 403
        assert client.patch(
            "/tickers/pi-2",
            headers={"Authorization": f"Bearer {first_token}"},
            json={"name": "Not mine"},
        ).status_code == 403
        assert client.patch(
            "/tickers/pi-1",
            headers={"Authorization": f"Bearer {first_token}"},
            json={"name": "Owned"},
        ).status_code == 200

        assert client.get("/data", headers={"X-Device-Token": device_token("pi-1")}).status_code == 200
        assert client.post(
            "/heartbeat", json={"metadata": {"build": "test"}}
        , headers={"X-Device-Token": device_token("pi-1")}).status_code == 200
        assert client.delete(
            "/tickers/pi-1",
            headers={"Authorization": f"Bearer {first_token}"},
        ).status_code == 200
        assert client.get(
            "/tickers", headers={"Authorization": f"Bearer {first_token}"}
        ).status_code == 403
        remaining = client.get(
            "/tickers", headers={"Authorization": f"Bearer {second_token}"}
        )
        assert [item["ticker_id"] for item in remaining.get_json()["tickers"]] == ["pi-2"]
        assert second_token != first_token
    finally:
        app.extensions["ticker.application"].close()


def test_deployment_fleet_health_reports_bounded_heartbeat_facts(tmp_path, monkeypatch) -> None:
    """Expose fleet heartbeat age and safe telemetry only with deployment authorization."""

    monkeypatch.setenv("TICKER_DEPLOY_TOKEN", "deploy-secret")
    app = create_offline_application(tmp_path / "ticker.sqlite3", [])
    try:
        client = app.test_client()
        _register(client, "pi-1")
        response = client.get("/fleet")
        assert response.status_code == 401
        response = client.get(
            "/fleet",
            headers={"X-Deployment-Token": "deploy-secret"},
        )
        assert response.status_code == 200
        payload = response.get_json()
        assert payload["tickers"][0]["ticker_id"] == "pi-1"
        assert "metadata" not in payload["tickers"][0]
    finally:
        app.extensions["ticker.application"].close()


def test_registration_persists_mini_profile_and_limits_modes(tmp_path) -> None:
    """Persist the mini geometry and project only supported sports content."""

    app = create_offline_application(tmp_path / "ticker.sqlite3", [])
    try:
        client = app.test_client()
        response = client.post(
            "/register",
            json={
                "device_id": "mini-1",
                "name": "Mini",
                "metadata": {"build": "mini-1.0.0"},
                "profile": {
                    "product_family": "mini",
                    "hardware": "esp32-s3",
                    "display": {"width": 64, "height": 32, "panel_count": 1},
                    "capabilities": {"modes": ["sports"], "asset_cache": False, "ota": True},
                },
            },
            headers={"X-Device-Token": device_token("mini-1")},
        )
        assert response.status_code == 201
        payload = response.get_json()
        assert payload["ticker"]["profile"]["product_family"] == "mini"
        assert payload["ticker"]["profile"]["display"]["width"] == 64
        assert payload["ticker"]["profile"]["capabilities"]["modes"] == ["sports"]
        exchange = client.post("/pair", json={"pairing_code": payload["pairing_code"]})
        token = exchange.get_json()["controller_token"]
        updated = client.patch(
            "/tickers/mini-1",
            headers={"Authorization": f"Bearer {token}"},
            json={"display_settings": {"mode": "weather"}},
        )
        assert updated.status_code == 200
        data = client.get("/data", headers={"X-Device-Token": device_token("mini-1")}).get_json()
        assert data["settings"]["mode"] == "sports"
    finally:
        app.extensions["ticker.application"].close()


def test_reboot_command_is_durable_and_single_use(tmp_path) -> None:
    """Expose one queued reboot command until the Pi acknowledges it."""

    app = create_offline_application(tmp_path / "ticker.sqlite3", [])
    try:
        client = app.test_client()
        registration = _register(client, "pi-command")
        exchange = client.post("/pair", json={"pairing_code": registration["pairing_code"]})
        token = exchange.get_json()["controller_token"]
        headers = {"Authorization": f"Bearer {token}"}
        queued = client.post("/tickers/pi-command/reboot", headers=headers)
        assert queued.status_code == 201
        command_id = queued.get_json()["command_id"]
        payload = client.get("/data", headers={"X-Device-Token": device_token("pi-command")}).get_json()
        assert payload["meta"]["reboot"]["id"] == command_id
        acknowledged = client.post(
            "/reboot-ack",
            json={"id": command_id},
            headers={"X-Device-Token": device_token("pi-command")},
        )
        assert acknowledged.get_json()["acknowledged"] is True
        assert "reboot" not in client.get("/data", headers={"X-Device-Token": device_token("pi-command")}).get_json()["meta"]
        assert client.post(
            "/reboot-ack",
            json={"id": command_id},
            headers={"X-Device-Token": device_token("pi-command")},
        ).get_json()["acknowledged"] is False
    finally:
        app.extensions["ticker.application"].close()


def test_custom_registration_requires_display_geometry(tmp_path) -> None:
    """Reject incomplete custom hardware declarations at the API boundary."""

    app = create_offline_application(tmp_path / "ticker.sqlite3", [])
    try:
        response = app.test_client().post(
            "/register",
            json={
                "device_id": "custom-1",
                "profile": {"product_family": "custom"},
            },
            headers={"X-Device-Token": device_token("custom-1")},
        )
        assert response.status_code == 400
    finally:
        app.extensions["ticker.application"].close()


def test_pairing_code_expiry_survives_backend_restart(tmp_path) -> None:
    """Reject an expired pairing code after reopening the same SQLite database."""

    now = [1000.0]
    database = tmp_path / "ticker.sqlite3"
    first_app = create_offline_application(database, [], clock=lambda: now[0])
    first_client = first_app.test_client()
    registration = _register(first_client, "restart-pairing")
    first_app.extensions["ticker.application"].close()

    now[0] += 601.0
    second_app = create_offline_application(database, [], clock=lambda: now[0])
    try:
        response = second_app.test_client().post(
            "/pair",
            json={"pairing_code": registration["pairing_code"]},
        )
        assert response.status_code == 400
        assert response.get_json()["error"]["message"] == "pairing code has expired"
    finally:
        second_app.extensions["ticker.application"].close()


def test_controller_group_pairs_multiple_tickers_and_lists_the_fleet(tmp_path) -> None:
    """Let one app group authorize multiple tickers without sharing ticker tokens."""

    app = create_offline_application(tmp_path / "ticker.sqlite3", [])
    try:
        client = app.test_client()
        first = _register(client, "group-pi")
        first_exchange = client.post(
            "/pair",
            json={"pairing_code": first["pairing_code"]},
        )
        first_payload = first_exchange.get_json()
        assert first_exchange.status_code == 201
        assert first_payload["controller_group_id"]
        assert first_payload["controller_group_secret"]

        second = _register(client, "group-mini")
        second_exchange = client.post(
            "/pair",
            json={
                "pairing_code": second["pairing_code"],
                "controller_group_id": first_payload["controller_group_id"],
                "controller_group_secret": first_payload["controller_group_secret"],
            },
        )
        second_payload = second_exchange.get_json()
        assert second_exchange.status_code == 201
        assert second_payload["controller_group_id"] == first_payload["controller_group_id"]
        assert "controller_group_secret" not in second_payload

        listing = client.get(
            "/tickers",
            headers={"Authorization": f"Bearer {second_payload['controller_token']}"},
        )
        assert [item["ticker_id"] for item in listing.get_json()["tickers"]] == ["group-mini", "group-pi"]
        shared_update = client.patch(
            "/tickers/group-pi",
            headers={"Authorization": f"Bearer {second_payload['controller_token']}"},
            json={"name": "Shared Pi"},
        )
        assert shared_update.status_code == 200

        fresh_code = client.post(
            "/tickers/group-mini/pairing-code",
            headers={"Authorization": f"Bearer {first_payload['controller_token']}"},
        ).get_json()["pairing_code"]
        other_exchange = client.post(
            "/pair", json={"pairing_code": fresh_code}
        )
        other_listing = client.get(
            "/tickers",
            headers={"Authorization": f"Bearer {other_exchange.get_json()['controller_token']}"},
        )
        assert [item["ticker_id"] for item in other_listing.get_json()["tickers"]] == ["group-mini"]
    finally:
        app.extensions["ticker.application"].close()
