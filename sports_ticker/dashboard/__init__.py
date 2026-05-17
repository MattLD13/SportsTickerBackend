"""Sports Ticker web dashboard — Flask Blueprint."""

from flask import Blueprint

dashboard = Blueprint(
    'dashboard',
    __name__,
    static_folder='static',
    static_url_path='/dashboard/static',
    template_folder='templates',
)

from . import routes  # noqa: F401, E402
