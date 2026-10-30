"""Routes for the operator: health, fleet state, firmware releases, credentials, and overlays."""
from __future__ import annotations

import time
from collections.abc import Mapping
from typing import Any

from flask import Blueprint, current_app, jsonify

from ticker.ops.incidents import redact

from ticker.server.api.common import ApiError, not_found, application, body, check_keys, firmware, invalid, json_value, operator, require_ticker, text, \
    ticker_view

routes = Blueprint("operator", __name__)


@routes.get("/health")
def health():
    """Report server, engine, and provider health. This route is public."""
    backend = application()
    scheduler = backend.scheduler_health()
    providers = {} if scheduler is None else {str(name): _provider_health(item) for name, item in scheduler.items()}
    runtime = current_app.extensions.get("ticker.runtime")
    runtime_health = runtime.status() if runtime is not None else {"enabled": False, "ready": True}
    degraded = any(not item["healthy"] for item in providers.values()) or not runtime_health["ready"]
    return jsonify({
        "status": "degraded" if degraded else "ok",
        "release": current_app.config.get("BACKEND_RELEASE", "development"),
        "deployment": current_app.extensions.get("ticker.deployment_status", lambda: {})(),
        "runtime": runtime_health,
        "diagnostics": {"stack_signal": current_app.config.get("STACK_DUMP_SIGNAL")},
        "scheduler": {"enabled": scheduler is not None, "providers": providers,
                      "recovery": backend.scheduler.recovery_health() if backend.scheduler is not None else {}},
    })


@routes.get("/fleet")
def fleet():
    """Report heartbeat age and bounded telemetry for every ticker."""
    operator()
    now = application().clock()
    entries = []
    for ticker in application().list_tickers():
        seen = ticker.device.last_seen_at
        age = None if seen is None else max(0.0, now - float(seen))
        metadata = dict(ticker.device.metadata)
        entries.append({
            "ticker_id": ticker.ticker_id, "name": ticker.name, "online": age is not None and age <= 90,
            "heartbeat_age_seconds": None if age is None else round(age, 1),
            **{key: metadata.get(key) for key in ("build", "temperature_c", "wifi_available", "wifi_setup_active")},
            "pairing": None if ticker.pairing is None else {"paired": ticker.pairing.paired},
            "profile": ticker.profile.to_mapping(),
        })
    return jsonify({"observed_at": now, "tickers": entries})


@routes.get("/fleet/updates")
def fleet_updates():
    operator()
    return jsonify(application().repository.updates.history())


@routes.post("/tickers/<ticker_id>/update")
def request_update(ticker_id: str):
    """Ask one ticker to install a release. A Mini needs the configured firmware for its hardware."""
    operator()
    version = text(body({"version"}), "version")
    ticker = require_ticker(ticker_id.strip())
    if ticker.profile.product_family == "mini":
        manifest, _ = firmware()
        if manifest is None or manifest.version != version:
            raise ApiError("requested mini firmware manifest is unavailable", 409, "firmware_unavailable")
        if manifest.hardware != ticker.profile.hardware:
            raise ApiError("firmware hardware does not match ticker hardware", 409, "firmware_incompatible")
    return jsonify(ticker_view(application().request_update(ticker.ticker_id, version))), 201


@routes.post("/tickers/<ticker_id>/credential")
def enroll_credential(ticker_id: str):
    operator()
    ticker = require_ticker(ticker_id.strip())
    application().enroll_device_credential(ticker.ticker_id, body({"token_sha256"}).get("token_sha256"))
    return jsonify({"ticker_id": ticker.ticker_id, "enrolled": True})


@routes.get("/workers")
def workers():
    """Report the release, connection, and health of each provider worker."""
    operator()
    return jsonify({"workers": json_value(_engine().workers())})


@routes.post("/workers/<name>/deploy")
def deploy_worker(name: str):
    """Start a release of one provider worker next to the active release, and promote it when it syncs."""
    operator()
    release = text(body({"release"}), "release")
    engine = _engine()
    if name not in engine.providers:
        raise not_found(f"worker not found: {name}")
    try:
        deployed = engine.deploy(name, release)
    except RuntimeError as error:
        raise ApiError(str(error), 409, "deploy_refused") from error
    status = engine.workers()[name]
    return jsonify({"worker": name, "release": release, "deployed": deployed, "active": status["active"],
                    "bad": status["bad"]}), 200 if deployed else 409


def _engine():
    engine = current_app.extensions.get("ticker3.engine")
    if engine is None:
        raise ApiError("this server has no provider workers", 503, "workers_unavailable")
    return engine


@routes.post("/alerts")
def publish_alert():
    operator()
    return jsonify(_event_view(application().publish_alert_event(**_event_values(body(), "score_alert")))), 201


@routes.post("/news")
def publish_news():
    operator()
    return jsonify(_event_view(application().publish_news_event(**_event_values(body(), "news")))), 201


def _event_values(payload: Mapping[str, Any], default_kind: str) -> dict[str, Any]:
    check_keys(payload, {"event_id", "kind", "payload", "created_at", "expires_at", "ticker_ids", "ttl_seconds"})
    event_payload = payload.get("payload", {})
    if not isinstance(event_payload, Mapping):
        raise invalid("payload must be an object")
    targets = payload.get("ticker_ids")
    if targets is not None and (isinstance(targets, (str, bytes)) or not isinstance(targets, (list, tuple))
                                or not all(isinstance(item, str) and item.strip() for item in targets)):
        raise invalid("ticker_ids must be an array of non-empty strings or null")
    kind = payload.get("kind", default_kind)
    if not isinstance(kind, str) or not kind.strip():
        raise invalid("kind must be a non-empty string")
    values = {"payload": event_payload, "kind": kind, "target_ticker_ids": targets}
    values.update((key, payload[key]) for key in ("event_id", "created_at", "expires_at", "ttl_seconds") if key in payload)
    return values


def _event_view(event: Any) -> dict[str, Any]:
    return {"event_id": event.event_id, "kind": event.kind, "payload": json_value(event.payload),
            "created_at": event.created_at, "expires_at": event.expires_at,
            "ticker_ids": None if event.target_ticker_ids is None else list(event.target_ticker_ids),
            "delivery_state": event.delivery_state}


def _provider_health(health: Any) -> dict[str, Any]:
    error = getattr(health, "last_error", None)
    return {"healthy": not error, "last_success": json_value(getattr(health, "last_success", None)),
            "last_error": redact(json_value(error)), "next_due": json_value(getattr(health, "next_due", None)),
            "consecutive_failures": int(getattr(health, "consecutive_failures", 0)),
            "refresh_calls": int(getattr(health, "refresh_calls", 0)),
            "paused_refreshes": int(getattr(health, "paused_refreshes", 0))}
