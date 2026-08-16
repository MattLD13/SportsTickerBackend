"""Exercise the direct version two Pi client contract."""

from dataclasses import dataclass
from typing import Any

import pytest
import requests

from ticker_core.protocol import BackendClient, BackendHttpError, BackendPayloadError, BackendTransportError


def _payload() -> dict[str, Any]:
    return {
        "api_version": "v2",
        "snapshot": {"ticker_id": "pi-1", "revision": 1, "observed_at": "2026-08-11T00:00:00+00:00", "stale": False},
        "settings": {"mode": "sports", "sports_presentation": "rotation", "pinned_content_id": "", "brightness": 100, "scroll_speed": 0.05, "inverted": False},
        "content": {"sports": []}, "events": {"alerts": [], "news": []},
        "health": {"provider": "refresh", "healthy": True, "error": None}, "meta": {"pairing": {"paired": True, "code": None}},
    }


@dataclass
class FakeResponse:
    status_code: int = 200
    payload: Any = None
    text: str = "response body"
    json_error: ValueError | None = None
    content: bytes = b""

    def json(self) -> Any:
        if self.json_error:
            raise self.json_error
        return self.payload


class FakeSession:
    def __init__(self, response: FakeResponse | Exception) -> None:
        self.response = response
        self.calls: list[tuple[str, str, dict[str, Any]]] = []
        self.closed = False

    def request(self, method: str, url: str, **kwargs: Any) -> FakeResponse:
        self.calls.append((method, url, kwargs))
        if isinstance(self.response, Exception):
            raise self.response
        return self.response

    def close(self) -> None:
        self.closed = True


def test_client_fetches_the_version_two_data_endpoint() -> None:
    session = FakeSession(FakeResponse(payload=_payload(), content=b"payload"))
    client = BackendClient("https://ticker.test/", session=session, timeout_seconds=7)

    response = client.fetch_data("pi-1")

    assert response.ticker_id == "pi-1"
    method, url, options = session.calls[0]
    assert (method, url) == ("GET", "https://ticker.test/api/v2/tickers/pi-1/data")
    assert options["timeout"] == 7
    assert options["verify"] is True


def test_client_registers_before_the_first_display_poll() -> None:
    session = FakeSession(
        FakeResponse(
            payload={
                "ticker_id": "pi-1",
                "paired": False,
                "pairing_code": "123456",
                "ticker": {"ticker_id": "pi-1"},
            }
        )
    )
    client = BackendClient("https://ticker.test", session=session)

    registration = client.register_device(
        "pi-1", name="Kitchen", metadata={"build": "test"}
    )

    assert registration.ticker_id == "pi-1"
    assert registration.pairing_code == "123456"
    method, url, options = session.calls[0]
    assert (method, url) == ("POST", "https://ticker.test/api/v2/devices/register")
    assert options["json"] == {
        "device_id": "pi-1",
        "name": "Kitchen",
        "metadata": {"build": "test"},
    }


def test_client_reports_http_json_and_transport_failures() -> None:
    with pytest.raises(BackendHttpError):
        BackendClient("https://ticker.test", session=FakeSession(FakeResponse(status_code=503))).fetch_data("pi-1")
    with pytest.raises(BackendPayloadError, match="invalid JSON"):
        BackendClient("https://ticker.test", session=FakeSession(FakeResponse(json_error=ValueError("bad")))).fetch_data("pi-1")
    with pytest.raises(BackendTransportError, match="offline"):
        BackendClient("https://ticker.test", session=FakeSession(requests.ConnectionError("offline"))).fetch_data("pi-1")
