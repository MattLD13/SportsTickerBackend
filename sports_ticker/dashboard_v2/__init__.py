"""Standalone dashboard for the version two API."""

from flask import Blueprint


dashboard_v2 = Blueprint(
    "dashboard_v2",
    __name__,
    template_folder="../dashboard/templates",
    static_folder="../dashboard/static",
    static_url_path="/dashboard/static",
)

from . import routes as _routes  # noqa: E402,F401

__all__ = ["dashboard_v2"]
