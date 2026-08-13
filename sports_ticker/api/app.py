"""Create the rewrite Flask application."""

from __future__ import annotations

from flask import Flask

from sports_ticker.application.composition import BackendApplication
from sports_ticker.bootstrap_v2 import create_backend_application
from sports_ticker.dashboard_v2 import dashboard_v2

from .routes import register_routes


def create_app(application: BackendApplication) -> Flask:
    """Create a Flask application from an injected backend application."""

    app = Flask("sports_ticker.api")
    app.json.sort_keys = False
    register_routes(app, application)
    app.register_blueprint(dashboard_v2)
    return app


__all__ = ["create_app", "create_backend_application"]
