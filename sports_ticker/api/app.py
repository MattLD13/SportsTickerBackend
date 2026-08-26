"""Create the rewrite Flask application."""

from __future__ import annotations

from pathlib import Path

from flask import Flask

from sports_ticker.application.composition import BackendApplication
from sports_ticker.firmware import FirmwareManifest
from sports_ticker.bootstrap_v2 import create_backend_application
from sports_ticker.dashboard_v2 import dashboard_v2
from sports_ticker.display_alerts import display_alerts

from .routes import register_routes


def create_app(
    application: BackendApplication,
    *,
    firmware_manifest: FirmwareManifest | None = None,
    firmware_directory: str | Path | None = None,
) -> Flask:
    """Create a Flask application from an injected backend application."""

    app = Flask("sports_ticker.api")
    app.json.sort_keys = False
    register_routes(
        app,
        application,
        firmware_manifest=firmware_manifest,
        firmware_directory=firmware_directory,
    )
    app.register_blueprint(dashboard_v2)
    app.register_blueprint(display_alerts)
    return app


__all__ = ["create_app", "create_backend_application"]
