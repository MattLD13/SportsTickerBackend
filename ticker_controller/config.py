"""Display constants, panel geometry, and WiFi portal HTML template."""

import os

import requests

BACKEND_URL = "https://ticker.mattdicks.org"

PANEL_W = 384
PANEL_H = 32
GAME_SEPARATOR_W = 1
GAME_SEPARATOR_COLOR = (45, 45, 45, 255)
SETUP_SSID = "SportsTicker_Setup"
SETUP_PASS = "setup1234"
PAGE_HOLD_TIME = 8.0
REFRESH_RATE = 0
ID_FILE_PATH = "/boot/ticker_id.txt"
ID_FILE_FALLBACK = "ticker_id.txt"
# Use project-relative path so it resolves correctly regardless of which user
# (root or mld) the service runs as.
ASSETS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'caches')

requests.packages.urllib3.disable_warnings()

HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        body { background-color: #121212; color: #e0e0e0; font-family: "SFMono-Regular", Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace; display: flex; justify-content: center; align-items: center; min-height: 100vh; margin: 0; }
        .card { background-color: #1e1e1e; padding: 2rem; border-radius: 12px; box-shadow: 0 4px 6px rgba(0,0,0,0.3); width: 100%; max-width: 350px; }
        h2 { text-align: center; color: #ffffff; margin-top: 0; margin-bottom: 0.5rem; }
        p.desc { text-align: center; color: #888; font-size: 0.9rem; margin-bottom: 1.5rem; }
        label { display: block; margin-bottom: 5px; font-size: 0.9rem; color: #aaa; font-weight: 500; }
        select, input { width: 100%; padding: 12px; margin-bottom: 15px; background: #2c2c2c; border: 1px solid #333; border-radius: 8px; color: white; font-size: 16px; box-sizing: border-box; appearance: none; -webkit-appearance: none; }
        .select-wrapper { position: relative; }
        .select-wrapper::after { content: '▼'; position: absolute; top: 18px; right: 15px; color: #888; font-size: 12px; pointer-events: none; }
        input:focus, select:focus { outline: none; border-color: #4a90e2; background: #333; }
        button { width: 100%; padding: 14px; background-color: #4a90e2; color: white; border: none; border-radius: 8px; font-size: 1rem; font-weight: bold; cursor: pointer; transition: background 0.2s; margin-top: 10px; }
        button:hover { background-color: #357abd; }
        .hidden { display: none; }
    </style>
    <script>
        function checkManual() {
            var val = document.getElementById("net_select").value;
            var manualInput = document.getElementById("manual_ssid");
            if (val === "__manual__") {
                manualInput.classList.remove("hidden");
                manualInput.required = true;
                manualInput.focus();
            } else {
                manualInput.classList.add("hidden");
                manualInput.required = false;
            }
        }
    </script>
</head>
<body>
    <div class="card">
        <h2>Setup Wi-Fi</h2>
        <p class="desc">Select your network to get started.</p>
        <form action="/connect" method="POST">
            <label for="net_select">Network</label>
            <div class="select-wrapper">
                <select id="net_select" name="ssid_select" onchange="checkManual()" required>
                    <option value="" disabled selected>Choose a Network...</option>
                    {% for net in networks %}
                    <option value="{{ net }}">{{ net }}</option>
                    {% endfor %}
                    <option value="__manual__">Enter Manually...</option>
                </select>
            </div>
            <input type="text" name="ssid_manual" id="manual_ssid" class="hidden" placeholder="Type Network Name">
            <label for="password">Password</label>
            <input type="password" name="password" placeholder="Enter password" required>
            <button type="submit">Connect</button>
        </form>
    </div>
</body>
</html>
"""
