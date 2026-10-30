"""The ticker API. docs/api.md lists every route."""
from __future__ import annotations

from pathlib import Path

from flask import Flask, request

from ticker.server.spotify import SpotifyIntegrationError

from ticker.server.api import catalog, control, device, files, operator
from ticker.server.api.common import ApiError, error_response


def create_app(application, *, firmware_manifest=None, firmware_directory: str | Path | None = None, stock_catalog=None) -> Flask:
    """Build the Flask application for one backend application. It starts no background work."""
    from ticker.server.providers.stock_catalog import StockSymbolCatalog
    from ticker.server.web import web

    app = Flask("ticker", static_folder=None)
    app.json.sort_keys = False
    app.extensions["ticker.application"] = application
    app.extensions["ticker.firmware_manifest"] = firmware_manifest
    app.extensions["ticker.firmware_directory"] = firmware_directory
    if stock_catalog is None:
        stock_catalog = StockSymbolCatalog()
        application.own_resource(stock_catalog)
    app.extensions["ticker.stock_catalog"] = stock_catalog
    for blueprint in (device.routes, files.routes, control.routes, catalog.routes, operator.routes, web):
        app.register_blueprint(blueprint)
    _errors(app)
    return app


def _errors(app: Flask) -> None:
    @app.errorhandler(ApiError)
    def api_error(error: ApiError):
        return error_response(error.message, error.status, error.code)

    @app.errorhandler(KeyError)
    def missing(error: KeyError):
        return error_response(f"ticker not found: {error.args[0] if error.args else 'resource'}", 404, "not_found")

    @app.errorhandler(TypeError)
    @app.errorhandler(ValueError)
    def bad_value(error: Exception):
        return error_response(str(error), 400, "invalid_request")

    @app.errorhandler(SpotifyIntegrationError)
    def spotify_error(error: SpotifyIntegrationError):
        return error_response(str(error), 400, "spotify_authorization_failed")

    @app.errorhandler(404)
    def no_route(error):
        return error_response("route not found", 404, "not_found")

    @app.errorhandler(405)
    def wrong_method(error):
        return error_response("method not allowed", 405, "method_not_allowed")

    @app.after_request
    def tell_streams(response):
        # A change request can change any display, so the stream checks each connected ticker again.
        if request.method not in {"GET", "HEAD", "OPTIONS"} and response.status_code < 400:
            hub = app.extensions.get("ticker.stream")
            if hub is not None:
                hub.changed_all()
        return response


__all__ = ["create_app"]
