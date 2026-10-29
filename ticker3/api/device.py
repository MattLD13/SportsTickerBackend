"""Routes for a Six or a Mini. The device token identifies the ticker."""
from __future__ import annotations

from flask import Blueprint, jsonify, request

from sports_ticker.fleet.device_credentials import device_token_hash

from .common import ApiError, application, body, data_view, device, firmware as firmware_files, invalid, mapping, not_found, text, \
    ticker_view

routes = Blueprint("device", __name__)


@routes.post("/register")
def register():
    """Register a device, or refresh the record of a known device."""
    token = request.headers.get("X-Device-Token", "")
    if not token:
        raise ApiError("device authorization is required", 401, "unauthorized")
    digest = device_token_hash(token)
    payload = body({"device_id", "name", "metadata", "profile", "pairing_code"})
    device_id = text(payload, "device_id")
    name = payload.get("name", "Ticker")
    if not isinstance(name, str):
        raise invalid("name must be a string")
    try:
        ticker, pairing_code, created = application().register_device(
            device_id, credential_hash=digest, name=name, metadata=mapping(payload, "metadata") or {},
            profile=mapping(payload, "profile"), pairing_code=text(payload, "pairing_code", required=False))
    except PermissionError as error:
        raise ApiError(str(error), 403, "forbidden") from error
    paired = bool(ticker.pairing is not None and ticker.pairing.paired)
    return jsonify({"ticker_id": ticker.ticker_id, "paired": paired, "pairing_code": pairing_code,
                    "ticker": ticker_view(ticker)}), 201 if created else 200


@routes.post("/verify")
def verify():
    return jsonify({"ticker_id": device(), "authenticated": True})


@routes.get("/data")
def data():
    return data_view(device())


@routes.post("/poll")
def poll():
    """Record the telemetry of a polling device and answer with its compact data."""
    ticker_id = device()
    application().heartbeat(ticker_id, body({"metadata"}))
    return data_view(ticker_id, compact=True)


@routes.post("/heartbeat")
def heartbeat():
    return jsonify(ticker_view(application().heartbeat(device(), body())))


@routes.get("/firmware")
def firmware():
    """Return the Mini firmware manifest that fits this device."""
    backend = application()
    ticker_id = device()
    ticker = backend.get_ticker(ticker_id)
    manifest, _ = firmware_files()
    if ticker.profile.product_family != "mini" or not ticker.profile.capabilities.ota:
        raise ApiError("firmware updates are not available for this ticker", 409, "firmware_unavailable")
    if manifest is None:
        raise not_found("firmware manifest is unavailable")
    requested = (request.args.get("version") or "").strip()
    if requested and requested != manifest.version:
        raise not_found("requested firmware version is unavailable")
    if manifest.hardware != ticker.profile.hardware:
        raise ApiError("firmware hardware does not match ticker hardware", 409, "firmware_incompatible")
    if backend.repository.updates.quarantined(ticker.profile.product_family, manifest.version):
        raise ApiError("firmware release is quarantined", 409, "firmware_quarantined")
    return jsonify({"ticker_id": ticker_id, "firmware": manifest.to_mapping()})


@routes.post("/update-result")
def update_result():
    ticker_id = device()
    payload = body({"id", "version", "status", "running_version", "reason"})
    backend = application()
    return jsonify(backend.repository.updates.report(ticker_id, payload, backend.clock()))


@routes.post("/reboot-ack")
def reboot_ack():
    ticker_id = device()
    command_id = text(body({"id"}), "id")
    return jsonify({"acknowledged": application().acknowledge_reboot(ticker_id, command_id)})
