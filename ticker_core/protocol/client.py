"""Call the deployed backend with one persistent HTTP session."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import requests
from requests.adapters import HTTPAdapter

from .model import PayloadValidationError, TickerResponse


DATA_ENDPOINT = "/data"
CONFIG_ENDPOINT = "/api/config"
TICKER_ENDPOINT_TEMPLATE = "/ticker/{device_id}"


class BackendError(RuntimeError):
    """Report a backend request failure."""


class BackendTransportError(BackendError):
    """Report a network failure."""


@dataclass(slots=True)
class BackendHttpError(BackendError):
    """Report a backend response with an unexpected status."""

    method: str
    url: str
    status_code: int
    body: str

    def __str__(self) -> str:
        return f"{self.method} {self.url} returned HTTP {self.status_code}"


class BackendPayloadError(BackendError):
    """Report a backend response that is not a valid display payload."""


class BackendClient:
    """Own backend HTTP details for one ticker process."""

    def __init__(
        self,
        backend_url: str,
        *,
        timeout_seconds: float = 5.0,
        verify_tls: bool = False,
        session: requests.Session | None = None,
    ) -> None:
        if not backend_url.strip():
            raise ValueError("backend_url must not be empty")
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self.backend_url = backend_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.verify_tls = verify_tls
        self.session = session or requests.Session()
        if session is None:
            adapter = HTTPAdapter(pool_connections=1, pool_maxsize=1)
            self.session.mount("http://", adapter)
            self.session.mount("https://", adapter)

    def close(self) -> None:
        """Close the persistent HTTP session."""

        self.session.close()

    def fetch_data(self, device_id: str, telemetry_headers: Mapping[str, str] | None = None) -> TickerResponse:
        """Fetch and validate the display response for one ticker."""

        if not device_id.strip():
            raise ValueError("device_id must not be empty")
        response = self._request(
            "GET",
            DATA_ENDPOINT,
            params={"id": device_id},
            headers=dict(telemetry_headers or {}),
        )
        payload = self._json_object(response, "GET /data")
        try:
            return TickerResponse.from_payload(payload)
        except PayloadValidationError as error:
            raise BackendPayloadError(str(error)) from error

    def get_data(self, device_id: str, telemetry_headers: Mapping[str, str] | None = None) -> TickerResponse:
        """Fetch display data through the legacy method name."""

        return self.fetch_data(device_id, telemetry_headers)

    def push_setting(self, device_id: str, key: str, value: Any) -> Mapping[str, Any]:
        """Store one local ticker setting through the deployed endpoint."""

        if not device_id.strip() or not key.strip():
            raise ValueError("device_id and key must not be empty")
        response = self._request(
            "POST",
            TICKER_ENDPOINT_TEMPLATE.format(device_id=device_id),
            json={key: value},
            headers={"X-Client-ID": device_id},
        )
        return self._json_object(response, "POST /ticker")

    def push_flight_config(self, device_id: str, config: Mapping[str, Any]) -> Mapping[str, Any]:
        """Store flight settings through the deployed config endpoint."""

        if not device_id.strip():
            raise ValueError("device_id must not be empty")
        payload = dict(config)
        payload["ticker_id"] = device_id
        has_flight = bool(str(payload.get("track_flight_id", "")).strip())
        has_airport = bool(str(payload.get("airport_code_iata", "")).strip())
        if has_flight:
            payload["mode"] = "flight_tracker"
            payload["active_sports"] = {"flight_visitor": True, "flight_airport": False}
        elif has_airport:
            payload["mode"] = "flights"
            payload["active_sports"] = {"flight_visitor": False, "flight_airport": True}
        response = self._request(
            "POST",
            CONFIG_ENDPOINT,
            json=payload,
            headers={"X-Client-ID": device_id},
        )
        return self._json_object(response, "POST /api/config")

    def _request(self, method: str, path: str, **kwargs: Any) -> requests.Response:
        url = f"{self.backend_url}{path}"
        try:
            response = self.session.request(
                method,
                url,
                timeout=self.timeout_seconds,
                verify=self.verify_tls,
                **kwargs,
            )
        except requests.RequestException as error:
            raise BackendTransportError(f"{method} {url} failed: {error}") from error
        if not 200 <= response.status_code < 300:
            raise BackendHttpError(method, url, response.status_code, response.text[:500])
        return response

    @staticmethod
    def _json_object(response: requests.Response, request_name: str) -> Mapping[str, Any]:
        try:
            payload = response.json()
        except ValueError as error:
            raise BackendPayloadError(f"{request_name} returned invalid JSON") from error
        if not isinstance(payload, Mapping):
            raise BackendPayloadError(f"{request_name} returned a non-object JSON body")
        return payload
