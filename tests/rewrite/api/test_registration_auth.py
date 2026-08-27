"""Exercise the device bootstrap and controller ownership boundaries."""

from __future__ import annotations

from datetime import datetime, timezone
import pytest

from sports_ticker.bootstrap_v2 import create_backend_application
from ticker_core.protocol import DeviceState, TickerResponse
from ticker_core.app.frame_builder import FrameBuilder
from ticker_core.features.alerts import NewsBannerRenderer, ScoreAlertRenderer
from ticker_core.features.utility import UtilityRenderer
from ticker_core.rendering import ContentRendererCatalog, load_default_font_set
from ticker_core.runtime import FrameDecision, FrameKind

pytestmark = pytest.mark.critical


def _register(client, ticker_id: str) -> dict:
    response = client.post(
        "/api/v2/devices/register",
        json={"device_id": ticker_id, "name": ticker_id, "metadata": {}},
    )
    assert response.status_code == 201
    return response.get_json()


def test_empty_repository_registers_pairing_snapshot_for_pi_bootstrap(tmp_path) -> None:
    """Register one unknown Pi, then parse its immediate pairing response."""

    app = create_backend_application(tmp_path / "ticker.sqlite3", [], scheduler=None)
    try:
        client = app.test_client()
        registration = _register(client, "pi-1")

        assert registration["ticker_id"] == "pi-1"
        assert registration["paired"] is False
        assert registration["pairing_code"]
        assert registration["ticker"]["profile"]["product_family"] == "full"

        response = client.get("/api/v2/tickers/pi-1/data")
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
            ContentRendererCatalog(),
            UtilityRenderer(fonts),
            ScoreAlertRenderer(fonts, Logos()),
            NewsBannerRenderer(fonts),
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
        app.extensions["sports_ticker.backend_application"].close()


def test_partial_display_settings_patch_preserves_other_ticker_controls(tmp_path) -> None:
    """Preserve inversion when a controller patches only shared team settings."""

    app = create_backend_application(tmp_path / "ticker.sqlite3", [], scheduler=None)
    try:
        client = app.test_client()
        registration = _register(client, "pi-settings")
        exchange = client.post(
            "/api/v2/pairings/exchange",
            json={"pairing_code": registration["pairing_code"]},
        )
        assert exchange.status_code == 201
        headers = {"Authorization": f"Bearer {exchange.get_json()['controller_token']}"}

        enabled = client.patch(
            "/api/v2/tickers/pi-settings",
            headers=headers,
            json={"display_settings": {"inverted": True}},
        )
        assert enabled.status_code == 200
        shared_update = client.patch(
            "/api/v2/tickers/pi-settings",
            headers=headers,
            json={"display_settings": {"my_teams": ["nfl:DAL"]}},
        )

        assert shared_update.status_code == 200
        settings = shared_update.get_json()["display_settings"]
        assert settings["inverted"] is True
        assert settings["my_teams"] == ["nfl:DAL"]
    finally:
        app.extensions["sports_ticker.backend_application"].close()


def test_live_delay_patch_isolated_to_target_ticker(tmp_path) -> None:
    """Keep live delay changes isolated when one controller owns multiple tickers."""

    app = create_backend_application(tmp_path / "ticker.sqlite3", [], scheduler=None)
    try:
        client = app.test_client()
        first = _register(client, "delay-one")
        first_exchange = client.post(
            "/api/v2/pairings/exchange",
            json={"pairing_code": first["pairing_code"]},
        )
        assert first_exchange.status_code == 201
        first_payload = first_exchange.get_json()
        second = _register(client, "delay-two")
        second_exchange = client.post(
            "/api/v2/pairings/exchange",
            json={
                "pairing_code": second["pairing_code"],
                "controller_group_id": first_payload["controller_group_id"],
                "controller_group_secret": first_payload["controller_group_secret"],
            },
        )
        assert second_exchange.status_code == 201
        headers = {"Authorization": f"Bearer {second_exchange.get_json()['controller_token']}"}

        other_enabled = client.patch(
            "/api/v2/tickers/delay-two",
            headers=headers,
            json={"display_settings": {"live_delay_mode": True, "live_delay_seconds": 60}},
        )
        assert other_enabled.status_code == 200

        enabled = client.patch(
            "/api/v2/tickers/delay-one",
            headers=headers,
            json={"display_settings": {"live_delay_mode": True, "live_delay_seconds": 120}},
        )
        assert enabled.status_code == 200

        disabled = client.patch(
            "/api/v2/tickers/delay-one",
            headers=headers,
            json={"display_settings": {"live_delay_mode": False}},
        )
        assert disabled.status_code == 200
        assert disabled.get_json()["display_settings"]["live_delay_mode"] is False
        assert app.extensions["sports_ticker.backend_application"].get_ticker(
            "delay-two"
        ).display_settings.live_delay_mode is True
    finally:
        app.extensions["sports_ticker.backend_application"].close()


def test_device_registration_renews_expired_pairing_code(tmp_path) -> None:
    """Give an offline ticker a fresh code after its previous code expires."""

    now = [1_000.0]
    app = create_backend_application(tmp_path / "ticker.sqlite3", [], scheduler=None, clock=lambda: now[0])
    try:
        client = app.test_client()
        first = _register(client, "pi-expired")
        now[0] = 2_000.0
        second_response = client.post(
            "/api/v2/devices/register",
            json={"device_id": "pi-expired", "name": "pi-expired", "metadata": {}},
        )

        assert second_response.status_code == 200
        second = second_response.get_json()
        assert second["pairing_code"]
        assert second["pairing_code"] != first["pairing_code"]
    finally:
        app.extensions["sports_ticker.backend_application"].close()


def test_device_registration_renews_the_code_exposed_by_ble_session(tmp_path) -> None:
    """Keep one expired BLE code stable until the controller exchanges it."""

    now = [1_000.0]
    app = create_backend_application(tmp_path / "ticker.sqlite3", [], scheduler=None, clock=lambda: now[0])
    try:
        client = app.test_client()
        first = _register(client, "pi-ble")
        now[0] = 2_000.0
        second_response = client.post(
            "/api/v2/devices/register",
            json={
                "device_id": "pi-ble",
                "name": "pi-ble",
                "metadata": {},
                "pairing_code": first["pairing_code"],
            },
        )

        assert second_response.status_code == 200
        second = second_response.get_json()
        assert second["pairing_code"] == first["pairing_code"]

        exchange = client.post(
            "/api/v2/pairings/exchange",
            json={"pairing_code": first["pairing_code"]},
        )
        assert exchange.status_code == 201
    finally:
        app.extensions["sports_ticker.backend_application"].close()


def test_controller_routes_return_only_the_owner_and_protect_mutations(tmp_path) -> None:
    """Require controller authorization while leaving device routes unauthenticated."""

    app = create_backend_application(tmp_path / "ticker.sqlite3", [], scheduler=None)
    try:
        client = app.test_client()
        first = _register(client, "pi-1")
        second = _register(client, "pi-2")
        first_exchange = client.post(
            "/api/v2/pairings/exchange", json={"pairing_code": first["pairing_code"]}
        )
        second_exchange = client.post(
            "/api/v2/pairings/exchange", json={"pairing_code": second["pairing_code"]}
        )
        first_token = first_exchange.get_json()["controller_token"]
        second_token = second_exchange.get_json()["controller_token"]

        assert client.post("/api/v2/tickers", json={"ticker_id": "manual"}).status_code == 405
        assert client.get("/api/v2/tickers").status_code == 401
        assert client.get(
            "/api/v2/tickers", headers={"Authorization": "Bearer invalid"}
        ).status_code == 403
        listing = client.get(
            "/api/v2/tickers", headers={"Authorization": f"Bearer {first_token}"}
        )
        assert listing.status_code == 200
        assert [item["ticker_id"] for item in listing.get_json()["tickers"]] == ["pi-1"]

        assert client.get(
            "/api/v2/tickers/pi-2", headers={"Authorization": f"Bearer {first_token}"}
        ).status_code == 403
        assert client.patch(
            "/api/v2/tickers/pi-2",
            headers={"Authorization": f"Bearer {first_token}"},
            json={"name": "Not mine"},
        ).status_code == 403
        assert client.patch(
            "/api/v2/tickers/pi-1",
            headers={"Authorization": f"Bearer {first_token}"},
            json={"name": "Owned"},
        ).status_code == 200

        assert client.get("/api/v2/tickers/pi-1/data").status_code == 200
        assert client.post(
            "/api/v2/tickers/pi-1/heartbeat", json={"metadata": {"build": "test"}}
        ).status_code == 200
        assert client.delete(
            "/api/v2/tickers/pi-1",
            headers={"Authorization": f"Bearer {first_token}"},
        ).status_code == 200
        assert client.get(
            "/api/v2/tickers", headers={"Authorization": f"Bearer {first_token}"}
        ).status_code == 403
        remaining = client.get(
            "/api/v2/tickers", headers={"Authorization": f"Bearer {second_token}"}
        )
        assert [item["ticker_id"] for item in remaining.get_json()["tickers"]] == ["pi-2"]
        assert second_token != first_token
    finally:
        app.extensions["sports_ticker.backend_application"].close()


def test_deployment_fleet_health_reports_bounded_heartbeat_facts(tmp_path, monkeypatch) -> None:
    """Expose fleet heartbeat age and safe telemetry only with deployment authorization."""

    monkeypatch.setenv("TICKER_DEPLOY_TOKEN", "deploy-secret")
    app = create_backend_application(tmp_path / "ticker.sqlite3", [], scheduler=None)
    try:
        client = app.test_client()
        _register(client, "pi-1")
        response = client.get("/api/v2/fleet/health")
        assert response.status_code == 401
        response = client.get(
            "/api/v2/fleet/health",
            headers={"X-Deployment-Token": "deploy-secret"},
        )
        assert response.status_code == 200
        payload = response.get_json()
        assert payload["api_version"] == "v2"
        assert payload["tickers"][0]["ticker_id"] == "pi-1"
        assert "metadata" not in payload["tickers"][0]
    finally:
        app.extensions["sports_ticker.backend_application"].close()


def test_registration_persists_mini_profile_and_limits_modes(tmp_path) -> None:
    """Persist the mini geometry and project only supported sports content."""

    app = create_backend_application(tmp_path / "ticker.sqlite3", [], scheduler=None)
    try:
        client = app.test_client()
        response = client.post(
            "/api/v2/devices/register",
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
        )
        assert response.status_code == 201
        payload = response.get_json()
        assert payload["ticker"]["profile"]["product_family"] == "mini"
        assert payload["ticker"]["profile"]["display"]["width"] == 64
        assert payload["ticker"]["profile"]["capabilities"]["modes"] == ["sports"]
        exchange = client.post("/api/v2/pairings/exchange", json={"pairing_code": payload["pairing_code"]})
        token = exchange.get_json()["controller_token"]
        updated = client.patch(
            "/api/v2/tickers/mini-1",
            headers={"Authorization": f"Bearer {token}"},
            json={"display_settings": {"mode": "weather"}},
        )
        assert updated.status_code == 200
        data = client.get("/api/v2/tickers/mini-1/data").get_json()
        assert data["settings"]["mode"] == "sports"
    finally:
        app.extensions["sports_ticker.backend_application"].close()


def test_reboot_command_is_durable_and_single_use(tmp_path) -> None:
    """Expose one queued reboot command until the Pi acknowledges it."""

    app = create_backend_application(tmp_path / "ticker.sqlite3", [], scheduler=None)
    try:
        client = app.test_client()
        registration = _register(client, "pi-command")
        exchange = client.post("/api/v2/pairings/exchange", json={"pairing_code": registration["pairing_code"]})
        token = exchange.get_json()["controller_token"]
        headers = {"Authorization": f"Bearer {token}"}
        queued = client.post("/api/v2/tickers/pi-command/commands/reboot", headers=headers)
        assert queued.status_code == 201
        command_id = queued.get_json()["command_id"]
        payload = client.get("/api/v2/tickers/pi-command/data").get_json()
        assert payload["meta"]["reboot"]["id"] == command_id
        acknowledged = client.post(
            "/api/v2/tickers/pi-command/commands/reboot/ack",
            json={"id": command_id},
        )
        assert acknowledged.get_json()["acknowledged"] is True
        assert "reboot" not in client.get("/api/v2/tickers/pi-command/data").get_json()["meta"]
        assert client.post(
            "/api/v2/tickers/pi-command/commands/reboot/ack",
            json={"id": command_id},
        ).get_json()["acknowledged"] is False
    finally:
        app.extensions["sports_ticker.backend_application"].close()


def test_custom_registration_requires_display_geometry(tmp_path) -> None:
    """Reject incomplete custom hardware declarations at the API boundary."""

    app = create_backend_application(tmp_path / "ticker.sqlite3", [], scheduler=None)
    try:
        response = app.test_client().post(
            "/api/v2/devices/register",
            json={
                "device_id": "custom-1",
                "profile": {"product_family": "custom"},
            },
        )
        assert response.status_code == 400
    finally:
        app.extensions["sports_ticker.backend_application"].close()


def test_pairing_code_expiry_survives_backend_restart(tmp_path) -> None:
    """Reject an expired pairing code after reopening the same SQLite database."""

    now = [1000.0]
    database = tmp_path / "ticker.sqlite3"
    first_app = create_backend_application(database, [], scheduler=None, clock=lambda: now[0])
    first_client = first_app.test_client()
    registration = _register(first_client, "restart-pairing")
    first_app.extensions["sports_ticker.backend_application"].close()

    now[0] += 601.0
    second_app = create_backend_application(database, [], scheduler=None, clock=lambda: now[0])
    try:
        response = second_app.test_client().post(
            "/api/v2/pairings/exchange",
            json={"pairing_code": registration["pairing_code"]},
        )
        assert response.status_code == 400
        assert response.get_json()["error"]["message"] == "pairing code has expired"
    finally:
        second_app.extensions["sports_ticker.backend_application"].close()


def test_controller_group_pairs_multiple_tickers_and_lists_the_fleet(tmp_path) -> None:
    """Let one app group authorize multiple tickers without sharing ticker tokens."""

    app = create_backend_application(tmp_path / "ticker.sqlite3", [], scheduler=None)
    try:
        client = app.test_client()
        first = _register(client, "group-pi")
        first_exchange = client.post(
            "/api/v2/pairings/exchange",
            json={"pairing_code": first["pairing_code"]},
        )
        first_payload = first_exchange.get_json()
        assert first_exchange.status_code == 201
        assert first_payload["controller_group_id"]
        assert first_payload["controller_group_secret"]

        second = _register(client, "group-mini")
        second_exchange = client.post(
            "/api/v2/pairings/exchange",
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
            "/api/v2/tickers",
            headers={"Authorization": f"Bearer {second_payload['controller_token']}"},
        )
        assert [item["ticker_id"] for item in listing.get_json()["tickers"]] == ["group-mini", "group-pi"]
        shared_update = client.patch(
            "/api/v2/tickers/group-pi",
            headers={"Authorization": f"Bearer {second_payload['controller_token']}"},
            json={"name": "Shared Pi"},
        )
        assert shared_update.status_code == 200

        fresh_code = client.post(
            "/api/v2/tickers/group-mini/pairing-code",
            headers={"Authorization": f"Bearer {first_payload['controller_token']}"},
        ).get_json()["pairing_code"]
        other_exchange = client.post(
            "/api/v2/pairings/exchange", json={"pairing_code": fresh_code}
        )
        other_listing = client.get(
            "/api/v2/tickers",
            headers={"Authorization": f"Bearer {other_exchange.get_json()['controller_token']}"},
        )
        assert [item["ticker_id"] for item in other_listing.get_json()["tickers"]] == ["group-mini"]
    finally:
        app.extensions["sports_ticker.backend_application"].close()
