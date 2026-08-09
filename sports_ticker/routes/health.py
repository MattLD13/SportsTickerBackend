"""Fleet and server health as JSON."""

import time

from flask import jsonify, request

from ..routes_runtime import app
from ..core import SERVER_VERSION, tickers, data_lock
from ..services.telemetry import fleet_health, server_snapshot, ticker_health


@app.route('/api/health', methods=['GET'])
def api_health():
    """Report the server process and every board it knows about.

    Query parameters:
      id   Limit the report to one ticker.

    A board that is dark carries ``dark_reason``, which names the gate that is
    keeping it dark. That field is the point of this endpoint: without it, an
    unpaired board, a sleeping board, and an unplugged board are all just a
    panel showing nothing.
    """
    now = time.time()
    ticker_id = request.args.get('id')

    if ticker_id:
        with data_lock:
            rec = tickers.get(ticker_id)
        if rec is None:
            return jsonify({"status": "error", "message": "Ticker not found"}), 404
        boards = [ticker_health(ticker_id, rec, now)]
    else:
        boards = fleet_health(now)

    return jsonify({
        "status": "ok",
        "version": SERVER_VERSION,
        "server": server_snapshot(),
        "tickers": boards,
        "online": sum(1 for b in boards if b['link'] == 'online'),
        "dark": sum(1 for b in boards if b['dark_reason']),
    })
