"""Call the deployed backend with one persistent HTTP session."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import requests
from requests.adapters import HTTPAdapter

from .model import PayloadValidationError, TickerResponse


DATA_ENDPOINT_TEMPLATE = "/api/v2/tickers/{device_id}/data"
REGISTRATION_ENDPOINT = "/api/v2/devices/register"
TICKER_ENDPOINT_TEMPLATE = "/api/v2/tickers/{device_id}"
HEARTBEAT_ENDPOINT_TEMPLATE = "/api/v2/tickers/{device_id}/heartbeat"
UPDATE_ACK_ENDPOINT_TEMPLATE = "/api/v2/tickers/{device_id}/updates/ack"
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
    ) -> None:
        if not backend_url.strip():
            raise ValueError("backend_url must not be empty")
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self.backend_url = backend_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.verify_tls = verify_tls
        self.session = session or requests.Session()
        self._last_data_body: bytes | None = None
        self.last_response_bytes: int | None = None
        self._last_data_response: TickerResponse | None = None
        self._settings_by_ticker: dict[str, dict[str, Any]] = {}
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
        self._settings_by_ticker[device_id] = _thaw_settings(parsed.settings.data)
        return parsed

    def register_device(
        self,
        device_id: str,
        *,
        name: str = "Ticker",
        metadata: Mapping[str, Any] | None = None,
    ) -> DeviceRegistration:
        """Register one Pi before its first V2 display poll."""

        if not device_id.strip():
            raise ValueError("device_id must not be empty")
        if not isinstance(name, str) or not name.strip():
            raise ValueError("name must be a non-empty string")
        if metadata is not None and not isinstance(metadata, Mapping):
            raise ValueError("metadata must be an object")
        response = self._request(
            "POST",
            REGISTRATION_ENDPOINT,
            json={
                "device_id": device_id,
                "name": name.strip(),
                "metadata": dict(metadata or {}),
            },
        )
        registration = DeviceRegistration.from_payload(
            self._json_object(response, "POST /api/v2/devices/register")
        )
        if registration.ticker_id != device_id.strip():
            raise BackendPayloadError(
                "device registration returned a ticker_id different from device_id"
            )
        return registration

    def get_data(self, device_id: str) -> TickerResponse:
        """Fetch display data for one version two ticker."""

        return self.fetch_data(device_id)

    def push_setting(self, device_id: str, key: str, value: Any) -> Mapping[str, Any]:
        """Store one display setting through the version two ticker endpoint."""

        if not device_id.strip() or not key.strip():
            raise ValueError("device_id and key must not be empty")
        settings = dict(self._settings_by_ticker.get(device_id, {}))
        if not settings:
            raise BackendPayloadError("fetch data before changing a ticker setting")
        settings[key] = value
        response = self._request(
            "PATCH",
            TICKER_ENDPOINT_TEMPLATE.format(device_id=device_id),
            json={"display_settings": settings},
        )
        saved = self._json_object(response, "PATCH /api/v2/tickers/<id>")
        display = saved.get("display_settings")
        if isinstance(display, Mapping):
            self._settings_by_ticker[device_id] = dict(display)
        return saved

    def push_flight_config(self, device_id: str, config: Mapping[str, Any]) -> Mapping[str, Any]:
        """Store flight or airport settings through the version two ticker endpoint."""

        if not device_id.strip():
            raise ValueError("device_id must not be empty")
        settings = dict(self._settings_by_ticker.get(device_id, {}))
        if not settings:
            raise BackendPayloadError("fetch data before changing flight settings")
        settings.update(config)
        has_flight = bool(str(settings.get("track_flight_id", "")).strip())
        has_airport = bool(str(settings.get("airport_code_iata", "")).strip())
        if has_flight:
            settings["mode"] = "flights"
        elif has_airport:
            settings["mode"] = "airports"
        response = self._request(
            "PATCH",
            TICKER_ENDPOINT_TEMPLATE.format(device_id=device_id),
            json={"display_settings": settings},
        )
        saved = self._json_object(response, "PATCH /api/v2/tickers/<id>")
        display = saved.get("display_settings")
        if isinstance(display, Mapping):
            self._settings_by_ticker[device_id] = dict(display)
        return saved

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

    def acknowledge_update(self, device_id: str, version: str) -> Mapping[str, Any]:
        """Acknowledge one received update before the updater restarts the Pi."""

        if not device_id.strip() or not version.strip():
            raise ValueError("device_id and version must not be empty")
        response = self._request(
            "POST",
            UPDATE_ACK_ENDPOINT_TEMPLATE.format(device_id=device_id),
            json={"version": version},
        )
        return self._json_object(response, "POST /api/v2/tickers/<id>/updates/ack")

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


def _thaw_settings(value: Mapping[str, Any]) -> dict[str, Any]:
    """Copy immutable parsed settings before a local settings mutation."""

    result: dict[str, Any] = {}
    for key, item in value.items():
        if isinstance(item, Mapping):
            result[key] = _thaw_settings(item)
        elif isinstance(item, tuple):
            result[key] = [
                _thaw_settings(entry) if isinstance(entry, Mapping) else entry
                for entry in item
            ]
        else:
            result[key] = item
    return result
