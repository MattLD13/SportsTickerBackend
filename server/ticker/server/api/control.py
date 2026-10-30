"""Routes for the controller app. A bearer token from POST /pair authorizes each request."""
from __future__ import annotations

from flask import Blueprint, jsonify, redirect, request

from ticker.server.services.schedule import block_to_mapping, condition_to_mapping

from ticker.server.api.common import (
    ApiError, application, body, controller, controller_token, data_view, fields, invalid, is_boolean, is_integer,
    is_text, is_text_or_null, is_weekdays, not_found, require_ticker, text, ticker_changes, ticker_view,
)

routes = Blueprint("control", __name__)

BLOCK_FIELDS = (("days_of_week", is_weekdays), ("start_minute", is_integer), ("end_minute", is_integer),
                ("mode", is_text), ("sports_filter", is_text_or_null), ("enabled", is_boolean))
CONDITION_FIELDS = (("kind", is_text), ("threshold", is_integer), ("operator", is_text), ("when_mode", is_text),
                    ("action_sports_filter", is_text), ("ignore_pinned", is_boolean), ("enabled", is_boolean))


# Pairing

@routes.post("/pair")
def pair():
    """Exchange a pairing code for a controller token, and join or start a controller group."""
    payload = body({"pairing_code", "controller_group_id", "controller_group_secret"})
    ticker, token, group_id, group_secret = application().exchange_pairing_code(
        text(payload, "pairing_code"), controller_group_id=text(payload, "controller_group_id", required=False),
        controller_group_secret=text(payload, "controller_group_secret", required=False))
    answer = {"ticker_id": ticker.ticker_id, "controller_token": token, "controller_group_id": group_id, "paired": True}
    if group_secret:
        answer["controller_group_secret"] = group_secret
    return jsonify(answer), 201


@routes.post("/tickers/<ticker_id>/pairing-code")
def pairing_code(ticker_id: str):
    identifier = controller(ticker_id)
    return jsonify({"ticker_id": identifier, "pairing_code": application().issue_pairing_code(identifier)}), 201


@routes.delete("/tickers/<ticker_id>/pairing")
def unpair(ticker_id: str):
    ticker, code = application().unpair_ticker(controller(ticker_id))
    return jsonify({"ticker_id": ticker.ticker_id, "paired": False, "pairing_code": code})


# Tickers

@routes.get("/tickers")
def tickers():
    backend = application()
    owned = backend.list_tickers_for_controller(controller_token())
    if not owned:
        raise ApiError("controller authorization is invalid", 403, "forbidden")
    return jsonify({"tickers": [ticker_view(ticker) for ticker in backend.visible_tickers(owned)]})


@routes.get("/tickers/<ticker_id>")
def ticker(ticker_id: str):
    return jsonify(ticker_view(require_ticker(controller(ticker_id))))


@routes.patch("/tickers/<ticker_id>")
def change_ticker(ticker_id: str):
    identifier = controller(ticker_id)
    changes = ticker_changes(body(), {"name", "display_settings", "schedule_override"})
    return jsonify(ticker_view(application().update_ticker(identifier, **changes)))


@routes.delete("/tickers/<ticker_id>")
def delete_ticker(ticker_id: str):
    identifier = controller(ticker_id)
    if not application().delete_ticker(identifier):
        raise not_found(f"ticker not found: {identifier}")
    return jsonify({"deleted": True, "ticker_id": identifier})


@routes.get("/tickers/<ticker_id>/data")
def data(ticker_id: str):
    return data_view(controller(ticker_id))


@routes.post("/tickers/<ticker_id>/reboot")
def reboot(ticker_id: str):
    record = application().request_reboot(controller(ticker_id))
    command = next(item for item in record.device.metadata["pending_commands"] if item["type"] == "reboot")
    return jsonify({"accepted": True, "command_id": command.get("id")}), 201


@routes.post("/tickers/<ticker_id>/events/<event_id>/ack")
def acknowledge_event(ticker_id: str, event_id: str):
    body()
    identifier = controller(ticker_id)
    if not application().acknowledge_event(identifier, event_id):
        raise not_found("event is not active for this ticker")
    return jsonify({"acknowledged": True, "event_id": event_id.strip(), "ticker_id": identifier})


# Schedule

@routes.get("/tickers/<ticker_id>/schedule")
def schedule(ticker_id: str):
    return jsonify(application().schedule_document(controller(ticker_id)))


@routes.post("/tickers/<ticker_id>/schedule/blocks")
def add_block(ticker_id: str):
    identifier = controller(ticker_id)
    values = fields(body(), BLOCK_FIELDS, ("days_of_week", "start_minute", "end_minute", "mode"), require_all=True)
    return jsonify(block_to_mapping(application().create_schedule_block(identifier, **values))), 201


@routes.patch("/tickers/<ticker_id>/schedule/blocks/<block_id>")
def change_block(ticker_id: str, block_id: str):
    identifier = controller(ticker_id)
    values = fields(body(), BLOCK_FIELDS, (), require_all=False)
    try:
        return jsonify(block_to_mapping(application().update_schedule_block(identifier, block_id, **values)))
    except KeyError as error:
        raise not_found(f"schedule block not found: {block_id}") from error


@routes.delete("/tickers/<ticker_id>/schedule/blocks/<block_id>")
def delete_block(ticker_id: str, block_id: str):
    if not application().delete_schedule_block(controller(ticker_id), block_id):
        raise not_found(f"schedule block not found: {block_id}")
    return jsonify({"deleted": True, "id": block_id.strip()})


@routes.post("/tickers/<ticker_id>/schedule/conditions")
def add_condition(ticker_id: str):
    identifier = controller(ticker_id)
    values = fields(body(), CONDITION_FIELDS, ("kind", "threshold"), require_all=True)
    return jsonify(condition_to_mapping(application().create_schedule_condition(identifier, **values))), 201


@routes.patch("/tickers/<ticker_id>/schedule/conditions/<condition_id>")
def change_condition(ticker_id: str, condition_id: str):
    identifier = controller(ticker_id)
    values = fields(body(), CONDITION_FIELDS, (), require_all=False)
    try:
        return jsonify(condition_to_mapping(application().update_schedule_condition(identifier, condition_id, **values)))
    except KeyError as error:
        raise not_found(f"schedule condition not found: {condition_id}") from error


@routes.delete("/tickers/<ticker_id>/schedule/conditions/<condition_id>")
def delete_condition(ticker_id: str, condition_id: str):
    if not application().delete_schedule_condition(controller(ticker_id), condition_id):
        raise not_found(f"schedule condition not found: {condition_id}")
    return jsonify({"deleted": True, "id": condition_id.strip()})


# Spotify

def _spotify():
    service = application().spotify_service
    if service is None:
        raise ApiError("Spotify integration is not configured", 503, "spotify_unavailable")
    return service


@routes.get("/tickers/<ticker_id>/spotify")
def spotify(ticker_id: str):
    return jsonify(_spotify().status(controller(ticker_id)))


@routes.delete("/tickers/<ticker_id>/spotify")
def unlink_spotify(ticker_id: str):
    identifier = controller(ticker_id)
    return jsonify({"disconnected": _spotify().disconnect(identifier), "ticker_id": identifier})


@routes.post("/tickers/<ticker_id>/spotify/login")
def spotify_login(ticker_id: str):
    return jsonify(_spotify().begin_authorization(controller(ticker_id))), 201


@routes.patch("/tickers/<ticker_id>/spotify/priority")
def spotify_priority(ticker_id: str):
    identifier = controller(ticker_id)
    payload = body({"spotify_account_id"})
    account_id = payload.get("spotify_account_id")
    if account_id is not None and (not isinstance(account_id, str) or not account_id.strip()):
        raise invalid("spotify_account_id must be a non-empty string or null")
    return jsonify(_spotify().set_priority(identifier, account_id))


@routes.delete("/tickers/<ticker_id>/spotify/<account_id>")
def unlink_spotify_account(ticker_id: str, account_id: str):
    identifier = controller(ticker_id)
    return jsonify({"disconnected": _spotify().disconnect(identifier, account_id), "ticker_id": identifier,
                    "spotify_account_id": account_id.strip()})


@routes.get("/spotify/callback")
def spotify_callback():
    """Finish a Spotify login, then send the browser back to the app."""
    if request.args.get("error"):
        raise ApiError("Spotify authorization was denied", 400, "spotify_authorization_denied")
    code, state = (request.args.get("code") or "").strip(), (request.args.get("state") or "").strip()
    if not code or not state:
        raise invalid("Spotify callback requires code and state")
    service = _spotify()
    result = service.complete_authorization(code, state)
    return redirect(service.app_completion_uri(result["attempt_id"], result["status"]), code=303)
