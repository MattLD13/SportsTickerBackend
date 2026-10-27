"""Standalone display-alert test page."""

from flask import Blueprint


display_alerts = Blueprint(
    "display_alerts",
    __name__,
    template_folder="templates",
)

from . import routes as _routes  # noqa: E402,F401

__all__ = ["display_alerts"]
