"""Exercise the device bootstrap and controller ownership boundaries."""

from __future__ import annotations

from datetime import datetime, timezone

from sports_ticker.bootstrap_v2 import create_backend_application
from ticker_core.protocol import DeviceState, TickerResponse
from ticker_core.app.frame_builder import FrameBuilder
from ticker_core.features.alerts import NewsBannerRenderer, ScoreAlertRenderer
from ticker_core.features.utility import UtilityRenderer
from ticker_core.rendering import ContentRendererCatalog, load_default_font_set
from ticker_core.runtime import FrameDecision, FrameKind


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
