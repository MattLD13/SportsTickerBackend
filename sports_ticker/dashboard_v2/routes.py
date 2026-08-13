"""HTML route for the standalone version two dashboard."""

from flask import render_template

from . import dashboard_v2


@dashboard_v2.get("/")
@dashboard_v2.get("/dashboard")
def index():
    """Render the dashboard shell. Browser code reads all state from v2 APIs."""

    return render_template("dashboard_v2/index.html")
