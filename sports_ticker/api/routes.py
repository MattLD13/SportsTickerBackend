"""Thin JSON routes for the rewrite backend."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from hmac import compare_digest
import os
from typing import Any

from flask import Flask, jsonify, redirect, request

from sports_ticker.application.composition import BackendApplication
from sports_ticker.domain import DisplaySettings
from sports_ticker.integrations import SpotifyIntegrationError


class ApiError(Exception):
    """Represent one client-facing API error."""

    def __init__(self, message: str, status_code: int, code: str) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.code = code


def register_routes(app: Flask, application: BackendApplication) -> None:
    """Register rewrite routes against one injected application."""

    @app.errorhandler(ApiError)
    def handle_api_error(error: ApiError):
        return _error_response(error.message, error.status_code, error.code)

    @app.errorhandler(KeyError)
    def handle_missing_resource(error: KeyError):
        identifier = error.args[0] if error.args else "resource"
        return _error_response(f"ticker not found: {identifier}", 404, "not_found")

    @app.errorhandler(TypeError)
    def handle_type_error(error: TypeError):
        return _error_response(str(error), 400, "invalid_request")

    @app.errorhandler(ValueError)
    def handle_value_error(error: ValueError):
        return _error_response(str(error), 400, "invalid_request")

    @app.errorhandler(SpotifyIntegrationError)
    def handle_spotify_error(error: SpotifyIntegrationError):
        return _error_response(str(error), 400, "spotify_authorization_failed")

    @app.errorhandler(404)
    def handle_http_not_found(error):
        return _error_response("route not found", 404, "not_found")

    @app.errorhandler(405)
    def handle_method_not_allowed(error):
        return _error_response("method not allowed", 405, "method_not_allowed")

    @app.get("/api/v2/health")
    def health():
        scheduler_health = application.scheduler_health()
        providers = {}
        if scheduler_health is not None:
            providers = {
                str(name): _scheduler_health_value(item)
                for name, item in scheduler_health.items()
            }
        degraded = any(not item["healthy"] for item in providers.values())
        return jsonify(
            {
                "api_version": "v2",
                "status": "degraded" if degraded else "ok",
                "scheduler": {
                    "enabled": scheduler_health is not None,
                    "providers": providers,
                },
            }
        )

    @app.get("/api/v2/catalog/leagues")
    def catalog_leagues():
        catalog = _catalog(application)
        return jsonify({"leagues": list(catalog.leagues())})

    @app.get("/api/v2/catalog/modes")
    def catalog_modes():
        catalog = _catalog(application)
        return jsonify({"modes": list(catalog.modes())})

    @app.get("/api/v2/catalog/leagues/<league_id>/teams")
    def catalog_teams(league_id: str):
        catalog = _catalog(application)
        return jsonify({"teams": list(catalog.teams(league_id))})

    @app.get("/api/v2/tickers")
    def list_tickers():
        return jsonify({"tickers": [_ticker_value(item) for item in application.list_tickers()]})

    @app.post("/api/v2/tickers")
    def create_ticker():
        payload = _json_object()
        values = _create_values(payload)
        ticker = application.create_ticker(**values)
        return jsonify(_ticker_value(ticker)), 201

    @app.post("/api/v2/pairings/exchange")
    def exchange_pairing_code():
        payload = _json_object()
        _check_keys(payload, {"pairing_code"})
        pairing_code = payload.get("pairing_code")
        if not isinstance(pairing_code, str) or not pairing_code.strip():
            raise ApiError("pairing_code must be a non-empty string", 400, "invalid_request")
        ticker, token = application.exchange_pairing_code(pairing_code)
        return jsonify(
            {
                "ticker_id": ticker.ticker_id,
                "controller_token": token,
                "paired": True,
            }
        ), 201

    @app.post("/api/v2/tickers/<ticker_id>/pairing-code")
    def issue_pairing_code(ticker_id: str):
        identifier = _controller_ticker_owner(application, ticker_id)
        return jsonify(
            {
                "ticker_id": identifier,
                "pairing_code": application.issue_pairing_code(identifier),
            }
        ), 201

    @app.delete("/api/v2/tickers/<ticker_id>/pairing")
    def unpair_ticker(ticker_id: str):
        identifier = _controller_ticker_owner(application, ticker_id)
        ticker, code = application.unpair_ticker(identifier)
        return jsonify(
            {
                "ticker_id": ticker.ticker_id,
                "paired": False,
                "pairing_code": code,
            }
        )

    @app.get("/api/v2/tickers/<ticker_id>")
    def get_ticker(ticker_id: str):
        ticker = _require_ticker(application, ticker_id)
        return jsonify(_ticker_value(ticker))

    @app.patch("/api/v2/tickers/<ticker_id>")
    def update_ticker(ticker_id: str):
        payload = _json_object()
        changes = _patch_values(payload)
        ticker = application.update_ticker(_ticker_id(ticker_id), **changes)
        return jsonify(_ticker_value(ticker))

    @app.delete("/api/v2/tickers/<ticker_id>")
    def delete_ticker(ticker_id: str):
        identifier = _ticker_id(ticker_id)
        if not application.delete_ticker(identifier):
            raise ApiError(f"ticker not found: {identifier}", 404, "not_found")
        return jsonify({"deleted": True, "ticker_id": identifier})

    @app.get("/api/v2/tickers/<ticker_id>/data")
    def ticker_data(ticker_id: str):
        identifier = _ticker_id(ticker_id)
        snapshot = application.get_snapshot(identifier)
        if snapshot is None:
            raise ApiError(f"ticker snapshot not found: {identifier}", 404, "not_found")
        data = application.project_data(identifier, {"stale": False})
        return jsonify(data)

    @app.post("/api/v2/tickers/<ticker_id>/heartbeat")
    def ticker_heartbeat(ticker_id: str):
        payload = _json_object()
        ticker = application.heartbeat(_ticker_id(ticker_id), payload)
        return jsonify(_ticker_value(ticker))

    @app.post("/api/v2/tickers/<ticker_id>/updates")
    def request_ticker_update(ticker_id: str):
        _require_deployment_token()
        payload = _json_object()
        _check_keys(payload, {"version"})
        version = payload.get("version")
        if not isinstance(version, str) or not version.strip():
            raise ApiError("version must be a non-empty string", 400, "invalid_request")
        ticker = application.request_update(_ticker_id(ticker_id), version)
        return jsonify(_ticker_value(ticker)), 201

    @app.post("/api/v2/tickers/<ticker_id>/updates/ack")
    def acknowledge_ticker_update(ticker_id: str):
        payload = _json_object()
        _check_keys(payload, {"version"})
        version = payload.get("version")
        if not isinstance(version, str) or not version.strip():
            raise ApiError("version must be a non-empty string", 400, "invalid_request")
        return jsonify({"acknowledged": application.acknowledge_update(_ticker_id(ticker_id), version)})

    @app.post("/api/v2/tickers/<ticker_id>/commands/reboot")
    def request_ticker_reboot(ticker_id: str):
        identifier = _controller_ticker_owner(application, ticker_id)
        ticker = application.request_reboot(identifier)
        command = ticker.device.metadata.get("pending_reboot", {})
        return jsonify({"accepted": True, "command_id": command.get("id")}), 201

    @app.post("/api/v2/tickers/<ticker_id>/commands/reboot/ack")
    def acknowledge_ticker_reboot(ticker_id: str):
        payload = _json_object()
        _check_keys(payload, {"id"})
        command_id = payload.get("id")
        if not isinstance(command_id, str) or not command_id.strip():
            raise ApiError("id must be a non-empty string", 400, "invalid_request")
        return jsonify({"acknowledged": application.acknowledge_reboot(_ticker_id(ticker_id), command_id)})

    @app.post("/api/v2/tickers/<ticker_id>/integrations/spotify/authorizations")
    def start_spotify_authorization(ticker_id: str):
        identifier = _controller_ticker_owner(application, ticker_id)
        service = _spotify_service(application)
        return jsonify(service.begin_authorization(identifier)), 201

    @app.get("/api/v2/tickers/<ticker_id>/integrations/spotify")
    def spotify_connection_status(ticker_id: str):
        identifier = _controller_ticker_owner(application, ticker_id)
        return jsonify(_spotify_service(application).status(identifier))

    @app.delete("/api/v2/tickers/<ticker_id>/integrations/spotify")
    def disconnect_spotify(ticker_id: str):
        identifier = _controller_ticker_owner(application, ticker_id)
        deleted = _spotify_service(application).disconnect(identifier)
        return jsonify({"disconnected": deleted, "ticker_id": identifier})

    @app.delete("/api/v2/tickers/<ticker_id>/integrations/spotify/<spotify_account_id>")
    def disconnect_spotify_account(ticker_id: str, spotify_account_id: str):
        identifier = _controller_ticker_owner(application, ticker_id)
        deleted = _spotify_service(application).disconnect(identifier, spotify_account_id)
        return jsonify(
            {
                "disconnected": deleted,
                "ticker_id": identifier,
                "spotify_account_id": str(spotify_account_id).strip(),
            }
        )

    @app.patch("/api/v2/tickers/<ticker_id>/integrations/spotify/priority")
    def set_spotify_priority(ticker_id: str):
        identifier = _controller_ticker_owner(application, ticker_id)
        payload = _json_object()
        _check_keys(payload, {"spotify_account_id"})
        account_id = payload.get("spotify_account_id")
        if account_id is not None and (
            not isinstance(account_id, str) or not account_id.strip()
        ):
            raise ApiError(
                "spotify_account_id must be a non-empty string or null",
                400,
                "invalid_request",
            )
        return jsonify(
            _spotify_service(application).set_priority(identifier, account_id)
        )

    @app.get("/api/v2/integrations/spotify/callback")
    def spotify_callback():
        if request.args.get("error"):
            raise ApiError("Spotify authorization was denied", 400, "spotify_authorization_denied")
        code = str(request.args.get("code") or "").strip()
        state = str(request.args.get("state") or "").strip()
        if not code or not state:
            raise ApiError("Spotify callback requires code and state", 400, "invalid_request")
        service = _spotify_service(application)
        result = service.complete_authorization(code, state)
        return redirect(service.app_completion_uri(result["attempt_id"], result["status"]), code=303)

    @app.post("/api/v2/events/alerts")
    def publish_alert_event():
        payload = _json_object()
        event = application.publish_alert_event(**_event_values(payload, "score_alert"))
        return jsonify(_event_value(event)), 201

    @app.post("/api/v2/events/news")
    def publish_news_event():
        payload = _json_object()
        event = application.publish_news_event(**_event_values(payload, "news"))
        return jsonify(_event_value(event)), 201

    @app.post("/api/v2/tickers/<ticker_id>/events/<event_id>/ack")
    def acknowledge_ticker_event(ticker_id: str, event_id: str):
        _json_object()
        identifier = _ticker_id(ticker_id)
        if not application.acknowledge_event(identifier, event_id):
            raise ApiError("event is not active for this ticker", 404, "not_found")
        return jsonify(
            {
                "acknowledged": True,
                "event_id": str(event_id).strip(),
                "ticker_id": identifier,
            }
        )

def _json_object() -> dict[str, Any]:
    if not request.is_json:
        raise ApiError("request body must be JSON", 415, "unsupported_media_type")
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        raise ApiError("request body must be a JSON object", 400, "invalid_request")
    return payload


def _create_values(payload: Mapping[str, Any]) -> dict[str, Any]:
    _check_keys(payload, {"ticker_id", "name", "display_settings", "settings", "pairing", "device"})
    if "display_settings" in payload and "settings" in payload:
        raise ApiError("provide display_settings or settings, not both", 400, "invalid_request")
    identifier = _ticker_id(payload.get("ticker_id", ""))
    name = payload.get("name", "Ticker")
    if not isinstance(name, str):
        raise ApiError("name must be a string", 400, "invalid_request")
    settings = _settings_value(payload)
    pairing = _optional_mapping(payload, "pairing")
    device = _optional_mapping(payload, "device")
    return {
        "ticker_id": identifier,
        "name": name,
        "display_settings": settings,
        "pairing": pairing,
        "device": device,
    }


def _patch_values(payload: Mapping[str, Any]) -> dict[str, Any]:
    _check_keys(payload, {"name", "display_settings", "settings", "pairing", "device"})
    if "display_settings" in payload and "settings" in payload:
        raise ApiError("provide display_settings or settings, not both", 400, "invalid_request")
    changes: dict[str, Any] = {}
    if "name" in payload:
        if not isinstance(payload["name"], str):
            raise ApiError("name must be a string", 400, "invalid_request")
        changes["name"] = payload["name"]
    if "display_settings" in payload or "settings" in payload:
        changes["display_settings"] = _settings_value(payload)
    if "pairing" in payload:
        changes["pairing"] = _optional_mapping(payload, "pairing")
    if "device" in payload:
        changes["device"] = _optional_mapping(payload, "device")
    return changes


def _settings_value(payload: Mapping[str, Any]) -> Mapping[str, Any] | None:
    value = payload.get("display_settings", payload.get("settings"))
    if value is not None and not isinstance(value, Mapping):
        raise ApiError("display_settings must be an object", 400, "invalid_request")
    if isinstance(value, Mapping):
        _check_keys(value, set(DisplaySettings.__dataclass_fields__))
    return value


def _event_values(payload: Mapping[str, Any], default_kind: str) -> dict[str, Any]:
    allowed = {
        "event_id",
        "kind",
        "payload",
        "created_at",
        "expires_at",
        "target_ticker_ids",
        "ticker_ids",
        "ttl_seconds",
    }
    _check_keys(payload, allowed)
    event_payload = payload.get("payload", {})
    if not isinstance(event_payload, Mapping):
        raise ApiError("payload must be an object", 400, "invalid_request")
    if "target_ticker_ids" in payload and "ticker_ids" in payload:
        raise ApiError("provide target_ticker_ids or ticker_ids, not both", 400, "invalid_request")
    targets = payload.get("target_ticker_ids", payload.get("ticker_ids"))
    if targets is not None:
        if isinstance(targets, (str, bytes)) or not isinstance(targets, (list, tuple, set)):
            raise ApiError("target_ticker_ids must be an array or null", 400, "invalid_request")
        if not all(isinstance(item, str) and item.strip() for item in targets):
            raise ApiError("target_ticker_ids must contain non-empty strings", 400, "invalid_request")
    kind = payload.get("kind", default_kind)
    if not isinstance(kind, str) or not kind.strip():
        raise ApiError("kind must be a non-empty string", 400, "invalid_request")
    values: dict[str, Any] = {
        "payload": event_payload,
        "kind": kind,
        "target_ticker_ids": targets,
    }
    for key in ("event_id", "created_at", "expires_at", "ttl_seconds"):
        if key in payload:
            values[key] = payload[key]
    return values


def _optional_mapping(payload: Mapping[str, Any], key: str) -> Mapping[str, Any] | None:
    value = payload.get(key)
    if value is not None and not isinstance(value, Mapping):
        raise ApiError(f"{key} must be an object or null", 400, "invalid_request")
    return value


def _check_keys(payload: Mapping[str, Any], allowed: set[str]) -> None:
    unknown = sorted(set(payload) - allowed)
    if unknown:
        raise ApiError(f"unknown fields: {', '.join(unknown)}", 400, "invalid_request")


def _ticker_id(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ApiError("ticker_id must be a non-empty string", 400, "invalid_request")
    return value.strip()


def _require_ticker(application: BackendApplication, ticker_id: str):
    identifier = _ticker_id(ticker_id)
    ticker = application.get_ticker(identifier)
    if ticker is None:
        raise ApiError(f"ticker not found: {identifier}", 404, "not_found")
    return ticker


def _spotify_service(application: BackendApplication):
    """Return the configured Spotify service or report unavailable integration."""

    service = application.spotify_service
    if service is None:
        raise ApiError("Spotify integration is not configured", 503, "spotify_unavailable")
    return service


def _catalog(application: BackendApplication):
    """Return the configured controller catalog service."""

    catalog = application.catalog
    if catalog is None:
        raise ApiError("team catalog is not configured", 503, "catalog_unavailable")
    return catalog


def _controller_ticker_owner(application: BackendApplication, ticker_id: str) -> str:
    """Require one opaque controller token for one ticker-owned integration."""

    identifier = _ticker_id(ticker_id)
    _require_ticker(application, identifier)
    authorization = str(request.headers.get("Authorization") or "")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise ApiError("controller authorization is required", 401, "unauthorized")
    if not application.authorize_controller(identifier, token.strip()):
        raise ApiError("controller authorization is invalid", 403, "forbidden")
    return identifier


def _require_deployment_token() -> None:
    """Allow controller releases only from the configured deployment secret."""

    expected = os.environ.get("TICKER_DEPLOY_TOKEN", "")
    supplied = str(request.headers.get("X-Deployment-Token") or "")
    if not expected or not compare_digest(supplied, expected):
        raise ApiError("deployment authorization is required", 401, "unauthorized")


def _ticker_value(ticker: Any) -> dict[str, Any]:
    settings = ticker.display_settings
    pairing = ticker.pairing
    device = ticker.device
    return {
        "ticker_id": ticker.ticker_id,
        "name": ticker.name,
        "display_settings": _display_settings_value(settings),
        "pairing": None
        if pairing is None
        else {
            "paired": pairing.paired,
        },
        "device": {
            "last_seen_at": device.last_seen_at,
            "metadata": _json_value(device.metadata),
        },
        "created_at": ticker.created_at,
        "updated_at": ticker.updated_at,
    }


def _display_settings_value(settings: DisplaySettings) -> dict[str, Any]:
    return {
        "active_sports": _json_value(settings.active_sports),
        "my_teams": list(settings.my_teams),
        "mode": settings.mode,
        "sports_filter": settings.sports_filter,
        "sports_presentation": settings.sports_presentation,
        "pinned_content_id": settings.pinned_content_id,
        "brightness": settings.brightness,
        "inverted": settings.inverted,
        "timezone": settings.timezone,
        "weather_city": settings.weather_city,
        "weather_lat": settings.weather_lat,
        "weather_lon": settings.weather_lon,
        "airport_code_iata": settings.airport_code_iata,
        "airport_code_icao": settings.airport_code_icao,
        "airport_name": settings.airport_name,
        "track_flight_id": settings.track_flight_id,
        "track_guest_name": settings.track_guest_name,
        "live_delay_mode": settings.live_delay_mode,
        "live_delay_seconds": settings.live_delay_seconds,
        "scroll_seamless": settings.scroll_seamless,
        "scroll_speed": settings.scroll_speed,
        "score_alerts": settings.score_alerts,
    }


def _event_value(event: Any) -> dict[str, Any]:
    return {
        "event_id": event.event_id,
        "kind": event.kind,
        "payload": _json_value(event.payload),
        "created_at": event.created_at,
        "expires_at": event.expires_at,
        "target_ticker_ids": None
        if event.target_ticker_ids is None
        else list(event.target_ticker_ids),
        "delivery_state": event.delivery_state,
    }


def _scheduler_health_value(health: Any) -> dict[str, Any]:
    if isinstance(health, Mapping):
        last_success = health.get("last_success")
        last_error = health.get("last_error")
        next_due = health.get("next_due")
        failures = health.get("consecutive_failures", 0)
    else:
        last_success = getattr(health, "last_success", None)
        last_error = getattr(health, "last_error", None)
        next_due = getattr(health, "next_due", None)
        failures = getattr(health, "consecutive_failures", 0)
    return {
        "healthy": not bool(last_error),
        "last_success": _json_value(last_success),
        "last_error": _json_value(last_error),
        "next_due": _json_value(next_due),
        "consecutive_failures": int(failures),
    }


def _json_value(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_json_value(item) for item in value]
    raise TypeError(f"value of type {type(value).__name__} is not JSON-ready")


def _error_response(message: str, status_code: int, code: str):
    return jsonify({"error": {"code": code, "message": message}}), status_code


__all__ = ["ApiError", "register_routes"]
