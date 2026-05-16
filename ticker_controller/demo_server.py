"""Browser demo server — lightweight proxy only. All rendering happens in the browser."""

import os
import requests
import requests.packages.urllib3
from flask import Flask, Response, jsonify, request

requests.packages.urllib3.disable_warnings()

BACKEND_URL = "https://ticker.mattdicks.org"
DEMO_DEVICE = "browser-demo"
HTML_PATH   = os.path.join(os.path.dirname(__file__), "demo.html")

app = Flask(__name__)


@app.route("/")
def index():
    with open(HTML_PATH, encoding="utf-8") as f:
        return Response(f.read(), mimetype="text/html")


@app.route("/api/data")
def proxy_data():
    try:
        r = requests.get(f"{BACKEND_URL}/data?id={DEMO_DEVICE}", timeout=8, verify=False)
        return Response(r.content, status=r.status_code, mimetype="application/json")
    except Exception as e:
        return jsonify({"error": str(e), "content": {"sports": []}}), 502


@app.route("/api/set_mode", methods=["POST"])
def set_mode():
    data = request.get_json(silent=True) or {}
    mode = data.get("mode", "sports")
    # Client-only sport-filtered views → sports_full on the server
    SERVER_MODE_MAP = {
        "nhl_full": "sports_full", "mlb_full": "sports_full",
        "nfl_full": "sports_full", "nba_full": "sports_full",
    }
    server_mode = SERVER_MODE_MAP.get(mode, mode)
    payload = {"ticker_id": DEMO_DEVICE, "mode": server_mode}
    if server_mode == "stocks":
        payload["active_sports"] = {"stocks_us": True}
    try:
        requests.post(f"{BACKEND_URL}/api/config", json=payload,
                      headers={"X-Client-ID": DEMO_DEVICE}, timeout=5, verify=False)
    except Exception:
        pass
    return jsonify({"status": "ok", "mode": mode, "server_mode": server_mode})


@app.route("/api/pin_games", methods=["POST"])
def pin_games():
    data = request.get_json(silent=True) or {}
    game_ids = data.get("game_ids", [])
    payload = {"ticker_id": DEMO_DEVICE, "game_ids": game_ids}
    try:
        requests.post(f"{BACKEND_URL}/api/pin_games", json=payload,
                      headers={"X-Client-ID": DEMO_DEVICE}, timeout=5, verify=False)
    except Exception:
        pass
    return jsonify({"status": "ok", "game_ids": game_ids})


@app.route("/proxy/logo")
def proxy_logo():
    url = request.args.get("url", "")
    if not url:
        return "", 404
    try:
        r = requests.get(url, timeout=5, verify=False, headers={"User-Agent": "SportsTicker/1.0"})
        ct = r.headers.get("Content-Type", "image/png")
        return Response(r.content, status=r.status_code, mimetype=ct,
                        headers={"Cache-Control": "public, max-age=3600",
                                 "Access-Control-Allow-Origin": "*"})
    except Exception:
        return "", 404


if __name__ == "__main__":
    print(f"Ticker Demo → http://localhost:5001  (device={DEMO_DEVICE})")
    app.run(host="0.0.0.0", port=5001, debug=False, threaded=True)
