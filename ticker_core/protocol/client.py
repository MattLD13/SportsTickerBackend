"""Call the deployed backend with one persistent HTTP session."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote, urlencode, urlsplit, urlunsplit

import requests
from requests.adapters import HTTPAdapter

from .model import PayloadValidationError, TickerResponse


DATA_ENDPOINT_TEMPLATE = "/api/v2/tickers/{device_id}/data"
STREAM_ENDPOINT_TEMPLATE = "/api/v2/tickers/{device_id}/stream"
REGISTRATION_ENDPOINT = "/api/v2/devices/register"
TICKER_ENDPOINT_TEMPLATE = "/api/v2/tickers/{device_id}"
HEARTBEAT_ENDPOINT_TEMPLATE = "/api/v2/tickers/{device_id}/heartbeat"
UPDATE_RESULT_ENDPOINT_TEMPLATE = "/api/v2/tickers/{device_id}/updates/result"
REBOOT_ACK_ENDPOINT_TEMPLATE = "/api/v2/tickers/{device_id}/commands/reboot/ack"


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


@dataclass(frozen=True, slots=True)
class DeviceRegistration:
    """Represent the validated V2 bootstrap response for one device."""

    ticker_id: str
    paired: bool
    pairing_code: str | None
    ticker: Mapping[str, Any]

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> "DeviceRegistration":
        """Validate the registration contract before polling display data."""

        ticker_id = payload.get("ticker_id")
        if not isinstance(ticker_id, str) or not ticker_id.strip():
            raise BackendPayloadError("device registration returned an invalid ticker_id")
        paired = payload.get("paired")
        if not isinstance(paired, bool):
            raise BackendPayloadError("device registration returned an invalid paired state")
        pairing_code = payload.get("pairing_code")
        if pairing_code is not None and not isinstance(pairing_code, str):
            raise BackendPayloadError("device registration returned an invalid pairing_code")
        ticker = payload.get("ticker")
        if not isinstance(ticker, Mapping):
            raise BackendPayloadError("device registration returned an invalid ticker")
        return cls(ticker_id.strip(), paired, pairing_code, dict(ticker))


class BackendClient:
    """Own backend HTTP details for one ticker process."""

    def __init__(
        self,
        backend_url: str,
        *,
        timeout_seconds: float = 5.0,
        verify_tls: bool = True,
        session: requests.Session | None = None,
        device_token: str | None = None,
        stream_connector: Callable[..., object] | None = None,
    ) -> None:
        if not backend_url.strip():
            raise ValueError("backend_url must not be empty")
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self.device_token = device_token
        self.backend_url = backend_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.verify_tls = verify_tls
        self.session = session or requests.Session()
        self._stream_connector = stream_connector
        self._last_data_body: bytes | None = None
        self.last_response_bytes: int | None = None
        self._last_data_response: TickerResponse | None = None
        if session is None:
            adapter = HTTPAdapter(pool_connections=1, pool_maxsize=1)
            self.session.mount("http://", adapter)
            self.session.mount("https://", adapter)

    def close(self) -> None:
        """Close the persistent HTTP session."""

        self.session.close()

    def fetch_data(self, device_id: str) -> TickerResponse:
        """Fetch and validate the display response for one ticker."""

        if not device_id.strip():
            raise ValueError("device_id must not be empty")
        response = self._request(
            "GET",
            DATA_ENDPOINT_TEMPLATE.format(device_id=device_id),
        )
        body = response.content
        self.last_response_bytes = len(body)
        if body and body == self._last_data_body and self._last_data_response is not None:
            return self._last_data_response
        payload = self._json_object(response, "GET /api/v2/tickers/<id>/data")
        try:
            parsed = TickerResponse.from_payload(payload)
        except PayloadValidationError as error:
            raise BackendPayloadError(str(error)) from error
        self._last_data_body = body
        self._last_data_response = parsed
        return parsed

    def open_device_stream(
        self,
        device_id: str,
        *,
        stream_id: str | None = None,
        after_seq: int | None = None,
        timeout_seconds: float = 1.0,
    ):
        """Open one version two device WebSocket with an optional replay cursor."""
        if not device_id.strip():
            raise ValueError("device_id must not be empty")
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if (stream_id is None) != (after_seq is None):
            raise ValueError("stream_id and after_seq must be provided together")
        if stream_id is not None and not stream_id.strip():
            raise ValueError("stream_id must not be empty")
        if after_seq is not None and (
            isinstance(after_seq, bool) or not isinstance(after_seq, int) or after_seq < 0
        ):
            raise ValueError("after_seq must be a non-negative integer")
        try:
            import websocket
        except ImportError as error:
            raise BackendTransportError("websocket-client is required for the device stream") from error
        parsed = urlsplit(self.backend_url)
        scheme = {"http": "ws", "https": "wss"}.get(parsed.scheme)
        if scheme is None or not parsed.netloc:
            raise ValueError("backend_url must use http or https")
        prefix = parsed.path.rstrip("/")
        path = f"{prefix}{STREAM_ENDPOINT_TEMPLATE.format(device_id=quote(device_id.strip(), safe=''))}"
        query = urlencode({"stream_id": stream_id, "after_seq": after_seq}) if stream_id is not None else ""
        url = urlunsplit((scheme, parsed.netloc, path, query, ""))
        sslopt = None
        if scheme == "wss":
            import ssl

            sslopt = {
                "cert_reqs": ssl.CERT_REQUIRED if self.verify_tls else ssl.CERT_NONE,
                "check_hostname": self.verify_tls,
            }
        try:
            connector = self._stream_connector or websocket.create_connection
            return connector(
                url,
                timeout=timeout_seconds,
                subprotocols=["ticker-v2"],
                sslopt=sslopt,
                enable_multithread=True,
                header={"X-Device-Token": self.device_token} if self.device_token else {},
            )
        except (OSError, websocket.WebSocketException) as error:
            raise BackendTransportError(f"WebSocket {url} failed: {error}") from error

    def remember_stream_response(self, device_id: str, response: TickerResponse) -> None:
        """Keep the latest streamed projection as the current display response."""
        if not device_id.strip():
            raise ValueError("device_id must not be empty")
        self._last_data_response = response
        self._last_data_body = None

    def register_device(
        self,
        device_id: str,
        *,
        name: str = "Ticker",
        metadata: Mapping[str, Any] | None = None,
        profile: Mapping[str, Any] | None = None,
    ) -> DeviceRegistration:
        """Register one Pi before its first V2 display poll."""

        if not device_id.strip():
            raise ValueError("device_id must not be empty")
        if not isinstance(name, str) or not name.strip():
            raise ValueError("name must be a non-empty string")
        if metadata is not None and not isinstance(metadata, Mapping):
            raise ValueError("metadata must be an object")
        if profile is not None and not isinstance(profile, Mapping):
            raise ValueError("profile must be an object")
        request_payload: dict[str, Any] = {
            "device_id": device_id,
            "name": name.strip(),
            "metadata": dict(metadata or {}),
        }
        if profile:
            request_payload["profile"] = dict(profile)
        response = self._request(
            "POST",
            REGISTRATION_ENDPOINT,
            json=request_payload,
        )
        registration = DeviceRegistration.from_payload(
            self._json_object(response, "POST /api/v2/devices/register")
        )
        if registration.ticker_id != device_id.strip():
            raise BackendPayloadError(
                "device registration returned a ticker_id different from device_id"
            )
        return registration

    def heartbeat(self, device_id: str, telemetry: Mapping[str, Any]) -> Mapping[str, Any]:
        """Send bounded device telemetry through the version two heartbeat route."""

        if not device_id.strip():
            raise ValueError("device_id must not be empty")
        response = self._request(
            "POST",
            HEARTBEAT_ENDPOINT_TEMPLATE.format(device_id=device_id),
            json={"metadata": dict(telemetry)},
        )
        return self._json_object(response, "POST /api/v2/tickers/<id>/heartbeat")

    def report_update(self, device_id: str, result: Mapping[str, Any]) -> Mapping[str, Any]:
        """Send one durable installation result for an assigned update attempt."""
        response = self._request("POST", UPDATE_RESULT_ENDPOINT_TEMPLATE.format(device_id=device_id), json=dict(result))
        return self._json_object(response, "POST /api/v2/tickers/<id>/updates/result")

    def acknowledge_reboot(self, device_id: str, command_id: str) -> Mapping[str, Any]:
        """Acknowledge one reboot command before the controller restarts."""

        if not device_id.strip() or not command_id.strip():
            raise ValueError("device_id and command_id must not be empty")
        response = self._request(
            "POST",
            REBOOT_ACK_ENDPOINT_TEMPLATE.format(device_id=device_id),
            json={"id": command_id},
        )
        return self._json_object(response, "POST /api/v2/tickers/<id>/commands/reboot/ack")

    def _request(self, method: str, path: str, **kwargs: Any) -> requests.Response:
        url = f"{self.backend_url}{path}"
        if self.device_token:
            kwargs["headers"] = {**kwargs.pop("headers", {}), "X-Device-Token": self.device_token}
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


