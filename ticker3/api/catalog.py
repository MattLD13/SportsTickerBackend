"""Public lists that the app uses to build its settings screens."""
from __future__ import annotations

from flask import Blueprint, current_app, jsonify, request

from .common import ApiError, application

routes = Blueprint("catalog", __name__)


def _catalog():
    catalog = application().catalog
    if catalog is None:
        raise ApiError("team catalog is not configured", 503, "catalog_unavailable")
    return catalog


@routes.get("/modes")
def modes():
    return jsonify({"modes": list(_catalog().modes())})


@routes.get("/leagues")
def leagues():
    return jsonify({"leagues": list(_catalog().leagues())})


@routes.get("/leagues/<league_id>/teams")
def teams(league_id: str):
    return jsonify({"teams": list(_catalog().teams(league_id))})


@routes.get("/stocks")
def stocks():
    try:
        return jsonify({"stocks": current_app.extensions["ticker.stock_catalog"].search(request.args.get("q", ""))})
    except ValueError as error:
        raise ApiError(str(error), 400, "invalid_request") from error
    except RuntimeError as error:
        raise ApiError(str(error), 503, "stock_search_unavailable") from error
