"""The public landing page, the controller dashboard, the panel demos, and the alert gallery."""

from flask import Blueprint

web = Blueprint("web", __name__, template_folder="templates", static_folder="static", static_url_path="/static")

from . import routes as _routes  # noqa: E402,F401

__all__ = ["web"]
