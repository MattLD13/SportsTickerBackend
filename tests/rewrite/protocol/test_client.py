from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest
import requests

from ticker_core.protocol import BackendClient, BackendHttpError, BackendPayloadError, BackendTransportError


@dataclass
class FakeResponse:
    status_code: int = 200
    payload: Any = None
    text: str = "response body"
    json_error: ValueError | None = None

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


def test_fetch_data_preserves_deployed_endpoint_and_telemetry_headers() -> None:
    session = FakeSession(FakeResponse(payload={"status": "ok", "content": {"sports": []}}))
    client = BackendClient("https://ticker.test/", session=session, timeout_seconds=7)

    response = client.fetch_data("pi-1", {"X-Ticker-Build": "r1+x"})

    assert response.status == "ok"
    method, url, options = session.calls[0]
    assert (method, url) == ("GET", "https://ticker.test/data")
    assert options["params"] == {"id": "pi-1"}
    assert options["headers"] == {"X-Ticker-Build": "r1+x"}
    assert options["timeout"] == 7
    assert options["verify"] is False


def test_pushes_local_setting_and_flight_config_with_device_header() -> None:
    session = FakeSession(FakeResponse(payload={"success": True}))
    client = BackendClient("https://ticker.test", session=session)

    client.push_setting("pi-1", "mode", "clock")
    client.push_flight_config("pi-1", {"track_flight_id": "UA1"})

    _, setting_url, setting = session.calls[0]
    assert setting_url == "https://ticker.test/ticker/pi-1"
    assert setting["headers"] == {"X-Client-ID": "pi-1"}
    assert setting["json"] == {"mode": "clock"}
    _, flight_url, flight = session.calls[1]
    assert flight_url == "https://ticker.test/api/config"
    assert flight["json"]["ticker_id"] == "pi-1"
    assert flight["json"]["mode"] == "flight_tracker"


def test_client_reports_http_json_and_transport_failures() -> None:
    client = BackendClient("https://ticker.test", session=FakeSession(FakeResponse(status_code=503)))
    with pytest.raises(BackendHttpError):
        client.fetch_data("pi-1")

    client = BackendClient("https://ticker.test", session=FakeSession(FakeResponse(json_error=ValueError("bad"))))
    with pytest.raises(BackendPayloadError, match="invalid JSON"):
        client.fetch_data("pi-1")

    client = BackendClient("https://ticker.test", session=FakeSession(requests.ConnectionError("offline")))
    with pytest.raises(BackendTransportError, match="offline"):
        client.fetch_data("pi-1")
