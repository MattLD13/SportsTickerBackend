"""Define V2 JSON routes, request authorization, and payload validation."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import datetime
from hmac import compare_digest
import os
from pathlib import Path
import time
from typing import Any
from urllib.parse import urlparse

from flask import Flask, Response, jsonify, redirect, request, send_from_directory
from backend_ops.incidents import redact

from sports_ticker.fleet.device_credentials import device_token_hash
from sports_ticker.application.composition import BackendApplication
from sports_ticker.domain import DisplaySettings
from sports_ticker.domain.settings import settings_to_mapping
from sports_ticker.firmware import FirmwareManifest
from sports_ticker.integrations import SpotifyIntegrationError
from sports_ticker.application.schedule import block_to_mapping, condition_to_mapping
from sports_ticker.providers.stock_catalog import StockSymbolCatalog


class ApiError(Exception):
    """Represent one client-facing API error."""

    def __init__(self, message: str, status_code: int, code: str) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.code = code


def register_routes(
    app: Flask,
    application: BackendApplication,
    *,
    firmware_manifest: FirmwareManifest | None = None,
    firmware_directory: str | Path | None = None,
) -> None:
    """Register every V2 route against one injected application."""

    _register_error_handlers(app)
    _register_asset_routes(app, application, firmware_manifest, firmware_directory)
    _register_health_route(app, application)
    _register_catalog_routes(app, application)
    _register_fleet_routes(app, application)
    _register_ticker_routes(app, application)
    _register_update_routes(app, application, firmware_manifest)
    _register_command_routes(app, application)
    _register_spotify_routes(app, application)
    _register_event_routes(app, application)


def _register_error_handlers(app: Flask) -> None:
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


def _register_asset_routes(
    app: Flask,
    application: BackendApplication,
    firmware_manifest: FirmwareManifest | None,
    firmware_directory: str | Path | None,
) -> None:
    @app.get("/api/v2/assets/mini-sports/<asset_id>.mts")
    def mini_sports_sprite(asset_id: str):
        """Serve validated public team art under an immutable content identity."""
        return _immutable_asset(application.mini_sprites, asset_id, "application/vnd.sportsticker.rgb565-mask", "sprite is unavailable")

    @app.get("/api/v2/assets/mini-artwork/<asset_id>.mta")
    def mini_album_artwork(asset_id: str):
        """Serve prepared cover bytes from the bounded memory cache."""
        return _immutable_asset(application.mini_artwork, asset_id, "application/vnd.sportsticker.rgb565", "artwork is unavailable")

    @app.get("/firmware/<path:filename>")
    def firmware_binary(filename: str):
        """Serve only the currently configured mini firmware release binary."""

        if firmware_manifest is None or firmware_directory is None:
            raise ApiError("firmware binary is unavailable", 404, "not_found")
        if application.repository.updates.quarantined("mini", firmware_manifest.version):
            raise ApiError("firmware release is quarantined", 409, "firmware_quarantined")
        requested = Path(filename)
        published = Path(urlparse(firmware_manifest.binary_url).path).name
        if requested.name != filename or requested.name != published or requested.suffix != ".bin":
            raise ApiError("firmware binary is unavailable", 404, "not_found")
        directory = Path(firmware_directory)
        if not (directory / requested.name).is_file():
            raise ApiError("firmware binary is unavailable", 404, "not_found")
        return send_from_directory(
            directory,
            requested.name,
            mimetype="application/octet-stream",
            conditional=True,
        )


def _register_health_route(app: Flask, application: BackendApplication) -> None:
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
        runtime = app.extensions.get("sports_ticker.runtime")
        runtime_health = runtime.status() if runtime is not None else {"enabled": False, "ready": True}
        return jsonify(
            {
                "api_version": "v2",
                "status": "degraded" if degraded or not runtime_health["ready"] else "ok",
                "release": app.config.get("BACKEND_RELEASE", "development"),
                "deployment": app.extensions.get("sports_ticker.deployment_status", lambda: {})(),
                "runtime": runtime_health,
                "diagnostics": {"stack_signal": app.config.get("STACK_DUMP_SIGNAL")},
                "scheduler": {
                    "enabled": scheduler_health is not None,
                    "providers": providers,
                    "recovery": application.scheduler.recovery_health() if application.scheduler is not None else {},
                },
            }
        )


def _register_catalog_routes(app: Flask, application: BackendApplication) -> None:
    stock_catalog = StockSymbolCatalog()
    application.own_resource(stock_catalog)
    app.extensions["sports_ticker.stock_catalog"] = stock_catalog

    @app.get("/api/v2/catalog/stocks")
    def catalog_stocks():
        try:
            return jsonify({"stocks": app.extensions["sports_ticker.stock_catalog"].search(request.args.get("q", ""))})
        except ValueError as error:
            raise ApiError(str(error), 400, "invalid_request") from error
        except RuntimeError as error:
            raise ApiError(str(error), 503, "stock_search_unavailable") from error

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


def _register_fleet_routes(app: Flask, application: BackendApplication) -> None:
    @app.get("/api/v2/tickers")
    def list_tickers():
        token = _controller_token()
        tickers = application.list_tickers_for_controller(token)
        if not tickers:
            raise ApiError("controller authorization is invalid", 403, "forbidden")
        return jsonify(
            {
                "tickers": [
                    _ticker_value(item, application)
                    for item in application.visible_tickers(tickers)
                ]
            }
        )

    @app.get("/api/v2/fleet/health")
    def fleet_health():
        """Return deployment-authorized heartbeat age and bounded telemetry for every ticker."""
        _require_deployment_token()
        now = time.time()
        entries = []
        for ticker in application.list_tickers():
            last_seen = ticker.device.last_seen_at
            age = None if last_seen is None else max(0.0, now - float(last_seen))
            metadata = dict(ticker.device.metadata)
            entries.append(
                {
                    "ticker_id": ticker.ticker_id,
                    "name": ticker.name,
                    "online": age is not None and age <= 90,
                    "heartbeat_age_seconds": None if age is None else round(age, 1),
                    "build": metadata.get("build"),
                    "temperature_c": metadata.get("temperature_c"),
                    "wifi_available": metadata.get("wifi_available"),
                    "wifi_setup_active": metadata.get("wifi_setup_active"),
                    "pairing": None if ticker.pairing is None else {"paired": ticker.pairing.paired},
                    "profile": ticker.profile.to_mapping(),
                }
            )
        return jsonify({"api_version": "v2", "observed_at": now, "tickers": entries})

    @app.post("/api/v2/tickers/<ticker_id>/device-credential")
    def enroll_device_credential(ticker_id: str):
        _require_deployment_token()
        identifier = _ticker_id(ticker_id)
        _require_ticker(application, identifier)
        payload = _json_object()
        _check_keys(payload, {"token_sha256"})
        application.enroll_device_credential(identifier, payload.get("token_sha256"))
        return jsonify({"ticker_id": identifier, "enrolled": True})

    @app.post("/api/v2/tickers/<ticker_id>/device-credential/verify")
    def verify_device_credential(ticker_id: str):
        identifier = _device_ticker_owner(application, ticker_id)
        return jsonify({"ticker_id": identifier, "authenticated": True})

    @app.post("/api/v2/devices/register")
    def register_device():
        token = str(request.headers.get("X-Device-Token") or "")
        if not token:
            raise ApiError("device authorization is required", 401, "unauthorized")
        digest = device_token_hash(token)
        payload = _json_object()
        _check_keys(payload, {"device_id", "name", "metadata", "profile", "pairing_code"})
        device_id = _ticker_id(payload.get("device_id", ""))
        name = payload.get("name", "Ticker")
        if not isinstance(name, str):
            raise ApiError("name must be a string", 400, "invalid_request")
        pairing_code = payload.get("pairing_code")
        if pairing_code is not None and not isinstance(pairing_code, str):
            raise ApiError("pairing_code must be a string", 400, "invalid_request")
        metadata = payload.get("metadata", {})
        if not isinstance(metadata, Mapping):
            raise ApiError("metadata must be an object", 400, "invalid_request")
        profile = payload.get("profile")
        if profile is not None and not isinstance(profile, Mapping):
            raise ApiError("profile must be an object", 400, "invalid_request")
        try:
            ticker, pairing_code, created = application.register_device(
                device_id,
                credential_hash=digest,
                name=name,
                metadata=metadata,
                profile=profile,
                pairing_code=pairing_code,
            )
        except PermissionError as error:
            raise ApiError(str(error), 403, "forbidden") from error
        except ValueError as error:
            raise ApiError(str(error), 400, "invalid_request") from error
        return jsonify(
            {
                "ticker_id": ticker.ticker_id,
                "paired": bool(ticker.pairing is not None and ticker.pairing.paired),
                "pairing_code": pairing_code,
                "ticker": _ticker_value(ticker, application),
            }
        ), 201 if created else 200

    @app.post("/api/v2/pairings/exchange")
    def exchange_pairing_code():
        payload = _json_object()
        _check_keys(payload, {"pairing_code", "controller_group_id", "controller_group_secret"})
        pairing_code = payload.get("pairing_code")
        if not isinstance(pairing_code, str) or not pairing_code.strip():
            raise ApiError("pairing_code must be a non-empty string", 400, "invalid_request")
        group_id = payload.get("controller_group_id")
        group_secret = payload.get("controller_group_secret")
        if group_id is not None and not isinstance(group_id, str):
            raise ApiError("controller_group_id must be a string", 400, "invalid_request")
        if group_secret is not None and not isinstance(group_secret, str):
            raise ApiError("controller_group_secret must be a string", 400, "invalid_request")
        ticker, token, returned_group_id, returned_group_secret = application.exchange_pairing_code(
            pairing_code,
            controller_group_id=group_id,
            controller_group_secret=group_secret,
        )
        return jsonify(
            {
                "ticker_id": ticker.ticker_id,
                "controller_token": token,
                "controller_group_id": returned_group_id,
                **({"controller_group_secret": returned_group_secret} if returned_group_secret else {}),
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


def _register_ticker_routes(app: Flask, application: BackendApplication) -> None:
    @app.get("/api/v2/tickers/<ticker_id>")
    def get_ticker(ticker_id: str):
        identifier = _device_or_controller_owner(application, ticker_id)
        ticker = _require_ticker(application, identifier)
        return jsonify(_ticker_value(ticker, application))

    @app.patch("/api/v2/tickers/<ticker_id>")
    def update_ticker(ticker_id: str):
        identifier = _device_or_controller_owner(application, ticker_id)
        payload = _json_object()
        changes = _patch_values(payload)
        ticker = application.update_ticker(identifier, **changes)
        return jsonify(_ticker_value(ticker, application))

    @app.get("/api/v2/tickers/<ticker_id>/schedule")
    def get_ticker_schedule(ticker_id: str):
        """Return the recurring schedule and effective status for one authorized ticker."""

        identifier = _controller_ticker_owner(application, ticker_id)
        return jsonify(application.schedule_document(identifier))

    @app.post("/api/v2/tickers/<ticker_id>/schedule/blocks")
    def create_ticker_schedule_block(ticker_id: str):
        """Create one recurring block owned by the authorized ticker."""

        identifier = _controller_ticker_owner(application, ticker_id)
        values = _schedule_block_values(_json_object(), require_all=True)
        block = application.create_schedule_block(identifier, **values)
        return jsonify(block_to_mapping(block)), 201

    @app.patch("/api/v2/tickers/<ticker_id>/schedule/blocks/<block_id>")
    def update_ticker_schedule_block(ticker_id: str, block_id: str):
        """Update one recurring block only when it belongs to the authorized ticker."""

        identifier = _controller_ticker_owner(application, ticker_id)
        values = _schedule_block_values(_json_object(), require_all=False)
        try:
            block = application.update_schedule_block(identifier, block_id, **values)
        except KeyError as error:
            raise ApiError(f"schedule block not found: {block_id}", 404, "not_found") from error
        return jsonify(block_to_mapping(block))

    @app.delete("/api/v2/tickers/<ticker_id>/schedule/blocks/<block_id>")
    def delete_ticker_schedule_block(ticker_id: str, block_id: str):
        """Delete one recurring block only when it belongs to the authorized ticker."""

        identifier = _controller_ticker_owner(application, ticker_id)
        if not application.delete_schedule_block(identifier, block_id):
            raise ApiError(f"schedule block not found: {block_id}", 404, "not_found")
        return jsonify({"deleted": True, "id": str(block_id).strip()})

    @app.post("/api/v2/tickers/<ticker_id>/schedule/conditions")
    def create_ticker_schedule_condition(ticker_id: str):
        """Create one live-game condition owned by the authorized ticker."""

        identifier = _controller_ticker_owner(application, ticker_id)
        values = _schedule_condition_values(_json_object(), require_all=True)
        condition = application.create_schedule_condition(identifier, **values)
        return jsonify(condition_to_mapping(condition)), 201

    @app.patch("/api/v2/tickers/<ticker_id>/schedule/conditions/<condition_id>")
    def update_ticker_schedule_condition(ticker_id: str, condition_id: str):
        """Update one live-game condition only when it belongs to the authorized ticker."""

        identifier = _controller_ticker_owner(application, ticker_id)
        values = _schedule_condition_values(_json_object(), require_all=False)
        try:
            condition = application.update_schedule_condition(identifier, condition_id, **values)
        except KeyError as error:
            raise ApiError(
                f"schedule condition not found: {condition_id}",
                404,
                "not_found",
            ) from error
        return jsonify(condition_to_mapping(condition))

    @app.delete("/api/v2/tickers/<ticker_id>/schedule/conditions/<condition_id>")
    def delete_ticker_schedule_condition(ticker_id: str, condition_id: str):
        """Delete one live-game condition only when it belongs to the authorized ticker."""

        identifier = _controller_ticker_owner(application, ticker_id)
        if not application.delete_schedule_condition(identifier, condition_id):
            raise ApiError(f"schedule condition not found: {condition_id}", 404, "not_found")
        return jsonify({"deleted": True, "id": str(condition_id).strip()})

    @app.delete("/api/v2/tickers/<ticker_id>")
    def delete_ticker(ticker_id: str):
        identifier = _controller_ticker_owner(application, ticker_id)
        if not application.delete_ticker(identifier):
            raise ApiError(f"ticker not found: {identifier}", 404, "not_found")
        return jsonify({"deleted": True, "ticker_id": identifier})

    def ticker_data_response(identifier: str, *, device_view: bool = False):
        snapshot = application.get_snapshot(identifier)
        if snapshot is None:
            raise ApiError(f"ticker snapshot not found: {identifier}", 404, "not_found")
        return jsonify(application.project_data(identifier, {"stale": False}, device_view=device_view))

    @app.get("/api/v2/tickers/<ticker_id>/data")
    def ticker_data(ticker_id: str):
        return ticker_data_response(_device_or_controller_owner(application, ticker_id))

    @app.post("/api/v2/tickers/<ticker_id>/data")
    def poll_ticker_data(ticker_id: str):
        identifier = _device_ticker_owner(application, ticker_id)
        payload = _json_object()
        _check_keys(payload, {"metadata"})
        application.heartbeat(identifier, payload)
        return ticker_data_response(identifier, device_view=True)

    @app.post("/api/v2/tickers/<ticker_id>/heartbeat")
    def ticker_heartbeat(ticker_id: str):
        identifier = _device_ticker_owner(application, ticker_id)
        ticker = application.heartbeat(identifier, _json_object())
        return jsonify(_ticker_value(ticker, application))


def _register_update_routes(app: Flask, application: BackendApplication, firmware_manifest: FirmwareManifest | None) -> None:
    @app.post("/api/v2/tickers/<ticker_id>/updates")
    def request_ticker_update(ticker_id: str):
        _require_deployment_token()
        payload = _json_object()
        _check_keys(payload, {"version"})
        version = payload.get("version")
        if not isinstance(version, str) or not version.strip():
            raise ApiError("version must be a non-empty string", 400, "invalid_request")
        identifier = _ticker_id(ticker_id)
        ticker = _require_ticker(application, identifier)
        if ticker.profile.product_family == "mini":
            if firmware_manifest is None or firmware_manifest.version != version.strip():
                raise ApiError("requested mini firmware manifest is unavailable", 409, "firmware_unavailable")
            if firmware_manifest.hardware != ticker.profile.hardware:
                raise ApiError("firmware hardware does not match ticker hardware", 409, "firmware_incompatible")
        ticker = application.request_update(identifier, version)
        return jsonify(_ticker_value(ticker, application)), 201

    @app.get("/api/v2/tickers/<ticker_id>/firmware")
    def check_ticker_firmware(ticker_id: str):
        """Return one device-compatible firmware manifest after ticker identity lookup."""

        identifier = _device_or_controller_owner(application, ticker_id)
        ticker = _require_ticker(application, identifier)
        if ticker.profile.product_family != "mini" or not ticker.profile.capabilities.ota:
            raise ApiError("firmware updates are not available for this ticker", 409, "firmware_unavailable")
        if firmware_manifest is None:
            raise ApiError("firmware manifest is unavailable", 404, "not_found")
        requested_version = str(request.args.get("version") or "").strip()
        if requested_version and requested_version != firmware_manifest.version:
            raise ApiError("requested firmware version is unavailable", 404, "not_found")
        if firmware_manifest.hardware != ticker.profile.hardware:
            raise ApiError("firmware hardware does not match ticker hardware", 409, "firmware_incompatible")
        if application.repository.updates.quarantined(ticker.profile.product_family, firmware_manifest.version):
            raise ApiError("firmware release is quarantined", 409, "firmware_quarantined")
        return jsonify(
            {
                "api_version": "v2",
                "ticker_id": identifier,
                "firmware": firmware_manifest.to_mapping(),
            }
        )

    @app.post("/api/v2/tickers/<ticker_id>/updates/result")
    def report_ticker_update(ticker_id: str):
        identifier = _device_ticker_owner(application, ticker_id)
        payload = _json_object()
        _check_keys(payload, {"id", "version", "status", "running_version", "reason"})
        return jsonify(application.repository.updates.report(identifier, payload, application._clock()))

    @app.get("/api/v2/fleet/updates")
    def fleet_update_history():
        _require_deployment_token()
        return jsonify(application.repository.updates.history())


def _register_command_routes(app: Flask, application: BackendApplication) -> None:
    @app.post("/api/v2/tickers/<ticker_id>/commands/reboot")
    def request_ticker_reboot(ticker_id: str):
        identifier = _controller_ticker_owner(application, ticker_id)
        ticker = application.request_reboot(identifier)
        command = next(item for item in ticker.device.metadata["pending_commands"] if item["type"] == "reboot")
        return jsonify({"accepted": True, "command_id": command.get("id")}), 201

    @app.post("/api/v2/tickers/<ticker_id>/commands/reboot/ack")
    def acknowledge_ticker_reboot(ticker_id: str):
        identifier = _device_ticker_owner(application, ticker_id)
        payload = _json_object()
        _check_keys(payload, {"id"})
        command_id = payload.get("id")
        if not isinstance(command_id, str) or not command_id.strip():
            raise ApiError("id must be a non-empty string", 400, "invalid_request")
        return jsonify({"acknowledged": application.acknowledge_reboot(identifier, command_id)})


def _register_spotify_routes(app: Flask, application: BackendApplication) -> None:
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


def _register_event_routes(app: Flask, application: BackendApplication) -> None:
    @app.post("/api/v2/events/alerts")
    def publish_alert_event():
        _require_deployment_token()
        payload = _json_object()
        event = application.publish_alert_event(**_event_values(payload, "score_alert"))
        return jsonify(_event_value(event)), 201

    @app.post("/api/v2/events/news")
    def publish_news_event():
        _require_deployment_token()
        payload = _json_object()
        event = application.publish_news_event(**_event_values(payload, "news"))
        return jsonify(_event_value(event)), 201

    @app.post("/api/v2/tickers/<ticker_id>/events/<event_id>/ack")
    def acknowledge_ticker_event(ticker_id: str, event_id: str):
        _json_object()
        identifier = _controller_ticker_owner(application, ticker_id)
        if not application.acknowledge_event(identifier, event_id):
            raise ApiError("event is not active for this ticker", 404, "not_found")
        return jsonify(
            {
                "acknowledged": True,
                "event_id": str(event_id).strip(),
                "ticker_id": identifier,
            }
        )


def _immutable_asset(service: Any, asset_id: str, mimetype: str, missing_message: str) -> Response:
    """Serve one content-addressed Mini asset with immutable cache headers."""
    asset = None if service is None else service.read(asset_id)
    if asset is None:
        raise ApiError(missing_message, 404, "not_found")
    body, checksum = asset
    response = Response(body, mimetype=mimetype)
    response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
    response.headers["X-Content-SHA256"] = checksum
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.set_etag(checksum)
    return response.make_conditional(request)


def _json_object() -> dict[str, Any]:
    if not request.is_json:
        raise ApiError("request body must be JSON", 415, "unsupported_media_type")
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        raise ApiError("request body must be a JSON object", 400, "invalid_request")
    return payload


def _patch_values(payload: Mapping[str, Any]) -> dict[str, Any]:
    _check_keys(payload, {"name", "display_settings", "settings", "pairing", "device", "schedule_override"})
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
    if "schedule_override" in payload:
        if not isinstance(payload["schedule_override"], bool):
            raise ApiError("schedule_override must be a boolean", 400, "invalid_request")
        changes["schedule_override"] = payload["schedule_override"]
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


def _invalid(message: str) -> ApiError:
    return ApiError(message, 400, "invalid_request")


def _string(key: str, value: Any) -> None:
    if not isinstance(value, str):
        raise _invalid(f"{key} must be a string")


def _string_or_null(key: str, value: Any) -> None:
    if value is not None and not isinstance(value, str):
        raise _invalid(f"{key} must be a string or null")


def _integer(key: str, value: Any) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise _invalid(f"{key} must be an integer")


def _boolean(key: str, value: Any) -> None:
    if not isinstance(value, bool):
        raise _invalid(f"{key} must be a boolean")


def _weekdays(key: str, value: Any) -> None:
    if isinstance(value, (str, bytes)) or not isinstance(value, (list, tuple, set)):
        raise _invalid(f"{key} must be an array")
    if not value or any(isinstance(item, bool) or not isinstance(item, int) for item in value):
        raise _invalid(f"{key} must contain integers")


_Field = tuple[str, Callable[[str, Any], None]]

_SCHEDULE_BLOCK_FIELDS: tuple[_Field, ...] = (
    ("days_of_week", _weekdays),
    ("start_minute", _integer),
    ("end_minute", _integer),
    ("mode", _string),
    ("sports_filter", _string_or_null),
    ("enabled", _boolean),
)
_SCHEDULE_CONDITION_FIELDS: tuple[_Field, ...] = (
    ("kind", _string),
    ("threshold", _integer),
    ("operator", _string),
    ("when_mode", _string),
    ("action_sports_filter", _string),
    ("ignore_pinned", _boolean),
    ("enabled", _boolean),
)


def _validated_fields(
    payload: Mapping[str, Any],
    fields: tuple[_Field, ...],
    required: tuple[str, ...],
    *,
    require_all: bool,
) -> dict[str, Any]:
    """Reject unknown and missing fields, then check each present field in order."""
    _check_keys(payload, {key for key, _ in fields})
    if require_all:
        missing = sorted(set(required) - set(payload))
        if missing:
            raise _invalid(f"missing fields: {', '.join(missing)}")
    values: dict[str, Any] = {}
    for key, check in fields:
        if key in payload:
            check(key, payload[key])
            values[key] = list(payload[key]) if check is _weekdays else payload[key]
    return values


def _schedule_block_values(payload: Mapping[str, Any], *, require_all: bool) -> dict[str, Any]:
    """Validate one ticker-owned recurring weekly block request."""
    return _validated_fields(payload, _SCHEDULE_BLOCK_FIELDS, ("days_of_week", "start_minute", "end_minute", "mode"),
                             require_all=require_all)


def _schedule_condition_values(payload: Mapping[str, Any], *, require_all: bool) -> dict[str, Any]:
    """Validate one ticker-owned live-game condition request."""
    return _validated_fields(payload, _SCHEDULE_CONDITION_FIELDS, ("kind", "threshold"), require_all=require_all)


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


def _device_ticker_owner(application: BackendApplication, ticker_id: str) -> str:
    identifier = _ticker_id(ticker_id)
    token = str(request.headers.get("X-Device-Token") or "")
    if not token:
        raise ApiError("device authorization is required", 401, "unauthorized")
    if not application.authorize_device(identifier, token):
        raise ApiError("device authorization is invalid", 403, "forbidden")
    return identifier


def _device_or_controller_owner(application: BackendApplication, ticker_id: str) -> str:
    if "X-Device-Token" in request.headers:
        return _device_ticker_owner(application, ticker_id)
    return _controller_ticker_owner(application, ticker_id)


def _controller_ticker_owner(application: BackendApplication, ticker_id: str) -> str:
    """Require one opaque controller token for one ticker-owned integration."""

    identifier = _ticker_id(ticker_id)
    token = _controller_token()
    _require_ticker(application, identifier)
    if not application.authorize_controller(identifier, token):
        raise ApiError("controller authorization is invalid", 403, "forbidden")
    return identifier


def _controller_token() -> str:
    """Read one bearer token without exposing its stored hash."""

    authorization = str(request.headers.get("Authorization") or "")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise ApiError("controller authorization is required", 401, "unauthorized")
    return token.strip()


def _require_deployment_token() -> None:
    """Allow controller releases only from the configured deployment secret."""

    expected = os.environ.get("TICKER_DEPLOY_TOKEN", "")
    supplied = str(request.headers.get("X-Deployment-Token") or "")
    if not expected or not compare_digest(supplied, expected):
        raise ApiError("deployment authorization is required", 401, "unauthorized")


def _ticker_value(ticker: Any, application: BackendApplication) -> dict[str, Any]:
    settings = ticker.display_settings
    pairing = ticker.pairing
    device = ticker.device
    return {
        "ticker_id": ticker.ticker_id,
        "name": ticker.name,
        "profile": ticker.profile.to_mapping(),
        "display_settings": settings_to_mapping(settings),
        "schedule_override": application.schedule_override(ticker.ticker_id),
        "schedule_override_expires_at": application.schedule_override_expires_at(ticker.ticker_id),
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
        read = health.get
    else:
        def read(key: str, default: Any = None) -> Any:
            return getattr(health, key, default)
    last_error = read("last_error")
    return {
        "healthy": not bool(last_error),
        "last_success": _json_value(read("last_success")),
        "last_error": redact(_json_value(last_error)),
        "next_due": _json_value(read("next_due")),
        "consecutive_failures": int(read("consecutive_failures", 0)),
        # These counters come only from scheduler health objects.
        "refresh_calls": int(getattr(health, "refresh_calls", 0)),
        "paused_refreshes": int(getattr(health, "paused_refreshes", 0)),
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
