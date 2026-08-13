"""Standalone dashboard for the version two API."""

from flask import Blueprint


dashboard_v2 = Blueprint(
    "dashboard_v2",
    __name__,
    template_folder="templates",
    static_folder="static",
    static_url_path="/dashboard/static/v2",
)

from . import routes as _routes  # noqa: E402,F401

__all__ = ["dashboard_v2"]
