"""Render the authenticated version two controller shell."""

from __future__ import annotations

from flask import render_template

from . import dashboard_v2


@dashboard_v2.get("/")
@dashboard_v2.get("/dashboard")
def index():
    """Render the controller shell before the browser supplies its token."""

    return render_template("dashboard_v2/index.html")
