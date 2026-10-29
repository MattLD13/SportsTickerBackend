"""Errors, request bodies, authorization, and record views that every route group shares."""
from __future__ import annotations

import os
from collections.abc import Callable, Mapping
from datetime import datetime
from hmac import compare_digest
from typing import Any

from flask import current_app, jsonify, request

from sports_ticker.domain.settings import settings_to_mapping


class ApiError(Exception):
    """One answer with an HTTP status and a stable error code."""

    def __init__(self, message: str, status: int, code: str) -> None:
        super().__init__(message)
        self.message, self.status, self.code = message, status, code


def invalid(message: str) -> ApiError:
    return ApiError(message, 400, "invalid_request")


def not_found(message: str) -> ApiError:
    return ApiError(message, 404, "not_found")


def error_response(message: str, status: int, code: str):
    return jsonify({"error": {"code": code, "message": message}}), status


def application():
    """Return the backend application of the running server."""
    return current_app.extensions["ticker.application"]


def firmware():
    """Return the Mini firmware manifest and the folder of its binary. Either can be None."""
    return current_app.extensions.get("ticker.firmware_manifest"), current_app.extensions.get("ticker.firmware_directory")


# Request bodies

def body(allowed: set[str] | None = None) -> dict[str, Any]:
    """Return the JSON object body. Reject unknown fields when `allowed` is given."""
    if not request.is_json:
        raise ApiError("request body must be JSON", 415, "unsupported_media_type")
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        raise invalid("request body must be a JSON object")
    if allowed is not None:
        check_keys(payload, allowed)
    return payload


def check_keys(payload: Mapping[str, Any], allowed: set[str]) -> None:
    unknown = sorted(set(payload) - allowed)
    if unknown:
        raise invalid(f"unknown fields: {', '.join(unknown)}")


def text(payload: Mapping[str, Any], key: str, *, required: bool = True, empty: bool = False) -> str | None:
    """Return one string field. A missing optional field gives None."""
    if key not in payload or payload[key] is None:
        if required:
            raise invalid(f"{key} must be a non-empty string")
        return None
    value = payload[key]
    if not isinstance(value, str) or (not empty and not value.strip()):
        raise invalid(f"{key} must be a {'string' if empty else 'non-empty string'}")
    return value if empty else value.strip()


def mapping(payload: Mapping[str, Any], key: str) -> Mapping[str, Any] | None:
    value = payload.get(key)
    if value is not None and not isinstance(value, Mapping):
        raise invalid(f"{key} must be an object")
    return value


# Authorization

def device() -> str:
    """Return the ticker that owns the device token of the request."""
    token = request.headers.get("X-Device-Token", "")
    if not token:
        raise ApiError("device authorization is required", 401, "unauthorized")
    ticker_id = application().repository.ticker_for_device_token(token)
    if ticker_id is None:
        raise ApiError("device authorization is invalid", 403, "forbidden")
    return ticker_id


def controller_token() -> str:
    scheme, _, token = request.headers.get("Authorization", "").partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise ApiError("controller authorization is required", 401, "unauthorized")
    return token.strip()


def controller(ticker_id: str) -> str:
    """Return the ticker ID when the controller token of the request may control it."""
    identifier = ticker_id.strip()
    token = controller_token()
    if application().get_ticker(identifier) is None:
        raise not_found(f"ticker not found: {identifier}")
    if not application().authorize_controller(identifier, token):
        raise ApiError("controller authorization is invalid", 403, "forbidden")
    return identifier


def operator() -> None:
    """Require the deployment secret of the server."""
    expected = os.environ.get("TICKER_DEPLOY_TOKEN", "")
    supplied = request.headers.get("X-Deployment-Token", "")
    if not expected or not compare_digest(supplied, expected):
        raise ApiError("deployment authorization is required", 401, "unauthorized")


def require_ticker(ticker_id: str):
    ticker = application().get_ticker(ticker_id)
    if ticker is None:
        raise not_found(f"ticker not found: {ticker_id}")
    return ticker


# Record views

def ticker_view(ticker: Any) -> dict[str, Any]:
    backend = application()
    pairing, device_record = ticker.pairing, ticker.device
    return {
        "ticker_id": ticker.ticker_id,
        "name": ticker.name,
        "profile": ticker.profile.to_mapping(),
        "display_settings": settings_to_mapping(ticker.display_settings),
        "schedule_override": backend.schedule_override(ticker.ticker_id),
        "schedule_override_expires_at": backend.schedule_override_expires_at(ticker.ticker_id),
        "pairing": None if pairing is None else {"paired": pairing.paired},
        "device": {"last_seen_at": device_record.last_seen_at, "metadata": json_value(device_record.metadata)},
        "created_at": ticker.created_at,
        "updated_at": ticker.updated_at,
    }


def ticker_changes(payload: Mapping[str, Any], allowed: set[str]) -> dict[str, Any]:
    """Validate a ticker change request. `display_settings` holds only known settings fields."""
    from sports_ticker.domain import DisplaySettings

    check_keys(payload, allowed)
    changes: dict[str, Any] = {}
    if "name" in payload:
        if not isinstance(payload["name"], str):
            raise invalid("name must be a string")
        changes["name"] = payload["name"]
    if "display_settings" in payload:
        settings = mapping(payload, "display_settings")
        if settings is not None:
            check_keys(settings, set(DisplaySettings.__dataclass_fields__))
        changes["display_settings"] = settings
    if "schedule_override" in payload:
        if not isinstance(payload["schedule_override"], bool):
            raise invalid("schedule_override must be a boolean")
        changes["schedule_override"] = payload["schedule_override"]
    return changes


def data_view(ticker_id: str, *, compact: bool = False):
    backend = application()
    if backend.get_snapshot(ticker_id) is None:
        raise not_found(f"ticker data is not ready: {ticker_id}")
    return jsonify(backend.project_data(ticker_id, {"stale": False}, device_view=compact))


def json_value(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Mapping):
        return {str(key): json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [json_value(item) for item in value]
    raise TypeError(f"value of type {type(value).__name__} is not JSON-ready")


Check = Callable[[str, Any], None]


def fields(payload: Mapping[str, Any], spec: tuple[tuple[str, Check], ...], required: tuple[str, ...], *,
           require_all: bool) -> dict[str, Any]:
    """Validate the fields in `spec`. A create request must have every required field."""
    check_keys(payload, {key for key, _ in spec})
    if require_all:
        missing = sorted(set(required) - set(payload))
        if missing:
            raise invalid(f"missing fields: {', '.join(missing)}")
    values = {}
    for key, check in spec:
        if key in payload:
            check(key, payload[key])
            values[key] = list(payload[key]) if isinstance(payload[key], (list, tuple, set)) else payload[key]
    return values


def is_text(key: str, value: Any) -> None:
    if not isinstance(value, str):
        raise invalid(f"{key} must be a string")


def is_text_or_null(key: str, value: Any) -> None:
    if value is not None and not isinstance(value, str):
        raise invalid(f"{key} must be a string or null")


def is_integer(key: str, value: Any) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise invalid(f"{key} must be an integer")


def is_boolean(key: str, value: Any) -> None:
    if not isinstance(value, bool):
        raise invalid(f"{key} must be a boolean")


def is_weekdays(key: str, value: Any) -> None:
    if isinstance(value, (str, bytes)) or not isinstance(value, (list, tuple, set)):
        raise invalid(f"{key} must be an array")
    if not value or any(isinstance(item, bool) or not isinstance(item, int) for item in value):
        raise invalid(f"{key} must contain integers")
