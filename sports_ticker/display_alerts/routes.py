"""Expose the isolated display-alert test page."""

from __future__ import annotations

from flask import render_template

from . import display_alerts


@display_alerts.get("/display-alerts")
def index():
    """Render the alert and news test page without changing the main website."""

    return render_template("display_alerts/index.html")
