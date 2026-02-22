import time
import threading
import io
import requests
import requests.adapters
import os
import uuid
import subprocess
import socket
import json
import concurrent.futures
import hashlib
import math
import random
import colorsys
import unicodedata
from datetime import datetime
from PIL import Image, ImageDraw, ImageFont, ImageOps, ImageStat
from rgbmatrix import RGBMatrix, RGBMatrixOptions
from flask import Flask, request, render_template_string

# ================= CONFIGURATION =================
BACKEND_URL = "https://ticker.mattdicks.org"

PANEL_W = 384
PANEL_H = 32
SETUP_SSID = "SportsTicker_Setup"
SETUP_PASS = "setup1234"
PAGE_HOLD_TIME = 8.0
REFRESH_RATE = 0
ID_FILE_PATH = "/boot/ticker_id.txt"
ID_FILE_FALLBACK = "ticker_id.txt"
ASSETS_DIR = os.path.expanduser("~/ticker/assets")

requests.packages.urllib3.disable_warnings()


# --- UI TEMPLATE ---
HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        body { background-color: #121212; color: #e0e0e0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; display: flex; justify-content: center; align-items: center; min-height: 100vh; margin: 0; }
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

# ================= FONT MAPS =================
TINY_FONT_MAP = {
    'A': [0x6, 0x9, 0xF, 0x9, 0x9], 'B': [0xE, 0x9, 0xE, 0x9, 0xE], 'C': [0x6, 0x9, 0x8, 0x9, 0x6],
    'D': [0xE, 0x9, 0x9, 0x9, 0xE], 'E': [0xF, 0x8, 0xE, 0x8, 0xF], 'F': [0xF, 0x8, 0xE, 0x8, 0x8],
    'G': [0x6, 0x9, 0xB, 0x9, 0x6], 'H': [0x9, 0x9, 0xF, 0x9, 0x9], 'I': [0xE, 0x4, 0x4, 0x4, 0xE],
    'J': [0x7, 0x2, 0x2, 0xA, 0x4], 'K': [0x9, 0xA, 0xC, 0xA, 0x9], 'L': [0x8, 0x8, 0x8, 0x8, 0xF],
    'M': [0x9, 0xF, 0xF, 0x9, 0x9], 'N': [0x9, 0xD, 0xF, 0xB, 0x9], 'O': [0x6, 0x9, 0x9, 0x9, 0x6],
    'P': [0xE, 0x9, 0xE, 0x8, 0x8], 'Q': [0x6, 0x9, 0x9, 0xA, 0x5], 'R': [0xE, 0x9, 0xE, 0xA, 0x9],
    'S': [0x7, 0x8, 0x6, 0x1, 0xE], 'T': [0xF, 0x4, 0x4, 0x4, 0x4], 'U': [0x9, 0x9, 0x9, 0x9, 0x6],
    'V': [0x9, 0x9, 0x9, 0xA, 0x4], 'W': [0x9, 0x9, 0xF, 0xF, 0x9], 'X': [0x9, 0x9, 0x6, 0x9, 0x9],
    'Y': [0x9, 0x9, 0x6, 0x2, 0x2], 'Z': [0xF, 0x1, 0x6, 0x8, 0xF],
    '0': [0x6, 0x9, 0x9, 0x9, 0x6], '1': [0x4, 0xC, 0x4, 0x4, 0xE], '2': [0xE, 0x1, 0x6, 0x8, 0xF],
    '3': [0xE, 0x1, 0x6, 0x1, 0xE], '4': [0x9, 0x9, 0xF, 0x1, 0x1], '5': [0xF, 0x8, 0xE, 0x1, 0xE],
    '6': [0x6, 0x8, 0xE, 0x9, 0x6], '7': [0xF, 0x1, 0x2, 0x4, 0x4], '8': [0x6, 0x9, 0x6, 0x9, 0x6],
    '9': [0x6, 0x9, 0x7, 0x1, 0x6], '+': [0x0, 0x4, 0xE, 0x4, 0x0], '-': [0x0, 0x0, 0xE, 0x0, 0x0],
    '.': [0x0, 0x0, 0x0, 0x0, 0x4], ' ': [0x0, 0x0, 0x0, 0x0, 0x0], '/': [0x1, 0x2, 0x4, 0x8, 0x0],
    "'": [0x4, 0x4, 0x0, 0x0, 0x0], '$': [0x4, 0xF, 0x5, 0xF, 0x4], '%': [0x9, 0x2, 0x4, 0x8, 0x12],
    '^': [0x4, 0xA, 0x0, 0x0, 0x0], ':': [0x0, 0x4, 0x0, 0x4, 0x0], ',': [0x0, 0x0, 0x0, 0x4, 0x8],
    '!': [0x4, 0x4, 0x4, 0x0, 0x4], '?': [0x6, 0x1, 0x2, 0x0, 0x2], '@': [0x6, 0xB, 0xB, 0x8, 0x6],
    '#': [0xA, 0xF, 0xA, 0xF, 0xA], '&': [0x4, 0xA, 0x5, 0xA, 0x5], '*': [0x0, 0xA, 0x4, 0xA, 0x0],
    '=': [0x0, 0xF, 0x0, 0xF, 0x0], '_': [0x0, 0x0, 0x0, 0x0, 0xF], '<': [0x1, 0x2, 0x4, 0x2, 0x1],
    '>': [0x4, 0x2, 0x1, 0x2, 0x4], '[': [0x6, 0x4, 0x4, 0x4, 0x6], ']': [0x6, 0x2, 0x2, 0x2, 0x6],
    '"': [0xA, 0xA, 0x0, 0x0, 0x0], ';': [0x0, 0x4, 0x0, 0x4, 0x8], '~': [0x0, 0x0, 0x0, 0x0, 0x0],
    '(': [0x2, 0x4, 0x4, 0x4, 0x2], ')': [0x4, 0x2, 0x2, 0x2, 0x4],
    '▲': [0x4, 0xE, 0x1F, 0x0, 0x0], '▼': [0x1F, 0xE, 0x4, 0x0, 0x0],
}

HYBRID_FONT_MAP = {
    'A': [0x6, 0x9, 0x9, 0xF, 0x9, 0x9], 'B': [0xE, 0x9, 0xE, 0x9, 0x9, 0xE], 'C': [0x6, 0x9, 0x8, 0x8, 0x9, 0x6],
    'D': [0xE, 0x9, 0x9, 0x9, 0x9, 0xE], 'E': [0xF, 0x8, 0xE, 0x8, 0x8, 0xF], 'F': [0xF, 0x8, 0xE, 0x8, 0x8, 0x8],
    'G': [0x6, 0x9, 0x8, 0xB, 0x9, 0x6], 'H': [0x9, 0x9, 0x9, 0xF, 0x9, 0x9], 'I': [0xE, 0x4, 0x4, 0x4, 0x4, 0xE],
    'J': [0x7, 0x2, 0x2, 0x2, 0xA, 0x4], 'K': [0x9, 0xA, 0xC, 0xC, 0xA, 0x9], 'L': [0x8, 0x8, 0x8, 0x8, 0x8, 0xF],
    'M': [0x9, 0xF, 0xF, 0x9, 0x9, 0x9], 'N': [0x9, 0xD, 0xF, 0xB, 0x9, 0x9], 'O': [0x6, 0x9, 0x9, 0x9, 0x9, 0x6],
    'P': [0xE, 0x9, 0x9, 0xE, 0x8, 0x8], 'Q': [0x6, 0x9, 0x9, 0x9, 0xA, 0x5], 'R': [0xE, 0x9, 0x9, 0xE, 0xA, 0x9],
    'S': [0x7, 0x8, 0x6, 0x1, 0x1, 0xE], 'T': [0xF, 0x4, 0x4, 0x4, 0x4, 0x4], 'U': [0x9, 0x9, 0x9, 0x9, 0x9, 0x6],
    'V': [0x0, 0x0, 0xA, 0x4, 0x0, 0x0], 'W': [0x9, 0x9, 0x9, 0xF, 0xF, 0x9], 'X': [0x9, 0x9, 0x6, 0x6, 0x9, 0x9],
    'Y': [0x9, 0x9, 0x9, 0x6, 0x2, 0x2], 'Z': [0xF, 0x1, 0x2, 0x4, 0x8, 0xF],
    '0': [0x6, 0x9, 0x9, 0x9, 0x9, 0x6], '1': [0x4, 0xC, 0x4, 0x4, 0x4, 0xE], '2': [0xE, 0x9, 0x2, 0x4, 0x8, 0xF],
    '3': [0xE, 0x9, 0x2, 0x1, 0x9, 0xE], '4': [0x9, 0x9, 0xF, 0x1, 0x1, 0x1], '5': [0xF, 0x8, 0xE, 0x1, 0x9, 0xE],
    '6': [0x6, 0x8, 0xE, 0x9, 0x9, 0x6], '7': [0xF, 0x1, 0x2, 0x4, 0x8, 0x8], '8': [0x6, 0x9, 0x6, 0x9, 0x9, 0x6],
    '9': [0x6, 0x9, 0x9, 0x7, 0x1, 0x6], '+': [0x0, 0x0, 0x4, 0xE, 0x4, 0x0], '-': [0x0, 0x0, 0x0, 0xE, 0x0, 0x0],
    '.': [0x0, 0x0, 0x0, 0x0, 0x0, 0x4], ' ': [0x0, 0x0, 0x0, 0x0, 0x0, 0x0], ':': [0x0, 0x6, 0x6, 0x0, 0x6, 0x6],
    '~': [0x0, 0x0, 0x0, 0x0, 0x0, 0x0], '/': [0x1, 0x2, 0x2, 0x4, 0x4, 0x8], "'": [0x4, 0x4, 0x0, 0x0, 0x0, 0x0],
    ',': [0x0, 0x0, 0x0, 0x0, 0x4, 0x8], '!': [0x4, 0x4, 0x4, 0x4, 0x0, 0x4], '?': [0x6, 0x9, 0x2, 0x4, 0x0, 0x4],
    '@': [0x6, 0x9, 0xB, 0xB, 0x8, 0x6], '#': [0xA, 0xF, 0xA, 0xA, 0xF, 0xA], '&': [0x4, 0xA, 0x4, 0xA, 0x9, 0x6],
    '*': [0x0, 0xA, 0x4, 0xA, 0x0, 0x0], '=': [0x0, 0xF, 0x0, 0x0, 0xF, 0x0], '_': [0x0, 0x0, 0x0, 0x0, 0x0, 0xF],
    '<': [0x1, 0x2, 0x4, 0x4, 0x2, 0x1], '>': [0x4, 0x2, 0x1, 0x1, 0x2, 0x4], '[': [0x6, 0x4, 0x4, 0x4, 0x4, 0x6],
    ']': [0x6, 0x2, 0x2, 0x2, 0x2, 0x6], '"': [0xA, 0xA, 0x0, 0x0, 0x0, 0x0], ';': [0x0, 0x4, 0x0, 0x0, 0x4, 0x8],
    '$': [0x4, 0xF, 0xC, 0x6, 0xF, 0x4], '%': [0x9, 0x2, 0x2, 0x4, 0x4, 0x9], '(': [0x2, 0x4, 0x4, 0x4, 0x4, 0x2],
    ')': [0x4, 0x2, 0x2, 0x2, 0x2, 0x4], '^': [0x0, 0x0, 0x4, 0xA, 0x0, 0x0],
}

# ================= SPECIAL CHARACTER HANDLING =================
SPECIAL_CHAR_MAP = {
    'Ä': 'A', 'ä': 'a', 'Ö': 'O', 'ö': 'o', 'Ü': 'U', 'ü': 'u', 'ß': 'ss',
    'À': 'A', 'à': 'a', 'Â': 'A', 'â': 'a', 'Ç': 'C', 'ç': 'c',
    'È': 'E', 'è': 'e', 'É': 'E', 'é': 'e', 'Ê': 'E', 'ê': 'e', 'Ë': 'E', 'ë': 'e',
    'Î': 'I', 'î': 'i', 'Ï': 'I', 'ï': 'i',
    'Ô': 'O', 'ô': 'o', 'Ù': 'U', 'ù': 'u', 'Û': 'U', 'û': 'u',
    'Œ': 'O', 'œ': 'o',
    'Á': 'A', 'á': 'a', 'Í': 'I', 'í': 'i', 'Ñ': 'N', 'ñ': 'n',
    'Ó': 'O', 'ó': 'o', 'Ú': 'U', 'ú': 'u',
    'Ã': 'A', 'ã': 'a', 'Õ': 'O', 'õ': 'o',
    'Å': 'A', 'å': 'a', 'Æ': 'A', 'æ': 'a', 'Ø': 'O', 'ø': 'o',
    'Ł': 'L', 'ł': 'l', 'Ś': 'S', 'ś': 's', 'Ź': 'Z', 'ź': 'z', 'Ż': 'Z', 'ż': 'z',
    'Č': 'C', 'č': 'c', 'Ř': 'R', 'ř': 'r', 'Š': 'S', 'š': 's', 'Ž': 'Z', 'ž': 'z',
    'Ć': 'C', 'ć': 'c', 'Đ': 'D', 'đ': 'd',
    'Ğ': 'G', 'ğ': 'g', 'İ': 'I', 'ı': 'i', 'Ş': 'S', 'ş': 's',
    'Ð': 'D', 'ð': 'd', 'Þ': 'T', 'þ': 't',
    '\u2018': "'", '\u2019': "'", '\u201c': '"', '\u201d': '"', '\u201e': '"',
    '\u2013': '-', '\u2014': '-', '\u2026': '...',
    '\u00d7': 'x', '\u00f7': '/', '\u00b1': '+/-',
    '\u00b0': 'o', '\u00a9': '(c)', '\u00ae': '(r)', '\u2122': 'tm',
    '\u20ac': 'E', '\u00a3': 'L', '\u00a5': 'Y', '\u00a2': 'c',
    '\u00bd': '1/2', '\u00bc': '1/4', '\u00be': '3/4',
    '\u00b2': '2', '\u00b3': '3', '\u00b9': '1',
    '\u00a1': '!', '\u00bf': '?', '\u00ab': '<<', '\u00bb': '>>', '\u00b7': '.', '\u2022': '*',
}

def normalize_special_chars(text):
    if not text:
        return text
    result = []
    for char in str(text):
        if char in SPECIAL_CHAR_MAP:
            result.append(SPECIAL_CHAR_MAP[char])
        elif char.upper() in SPECIAL_CHAR_MAP:
            result.append(SPECIAL_CHAR_MAP[char.upper()])
        else:
            try:
                normalized = unicodedata.normalize('NFD', char)
                ascii_char = ''.join(c for c in normalized if not unicodedata.combining(c))
                if ascii_char and all(ord(c) < 128 for c in ascii_char):
                    result.append(ascii_char)
                elif ord(char) < 128:
                    result.append(char)
                else:
                    try:
                        ascii_repr = char.encode('ascii', 'ignore').decode('ascii')
                        result.append(ascii_repr if ascii_repr else '?')
                    except:
                        result.append('?')
            except:
                result.append('?' if ord(char) >= 128 else char)
    return ''.join(result)

# ================= PIL TEXT HELPERS =================
def draw_tiny_text(draw, x, y, text_str, color):
    text_str = normalize_special_chars(str(text_str)).upper()
    x_cursor = x
    for char in text_str:
        if char == '~':
            x_cursor += 2
            continue
        bitmap = TINY_FONT_MAP.get(char, TINY_FONT_MAP.get(' ', [0x0]*5))
        for r, row_byte in enumerate(bitmap):
            if row_byte & 0x8: draw.point((x_cursor+0, y+r), fill=color)
            if row_byte & 0x4: draw.point((x_cursor+1, y+r), fill=color)
            if row_byte & 0x2: draw.point((x_cursor+2, y+r), fill=color)
            if row_byte & 0x1: draw.point((x_cursor+3, y+r), fill=color)
            if len(bitmap) > 4 and (row_byte & 0x10): draw.point((x_cursor+4, y+r), fill=color)
        x_cursor += 5
    return x_cursor - x

def draw_hybrid_text(draw, x, y, text_str, color):
    text_str = normalize_special_chars(str(text_str)).upper()
    x_cursor = x
    for char in text_str:
        if char == '~':
            x_cursor += 2
            continue
        bitmap = HYBRID_FONT_MAP.get(char, HYBRID_FONT_MAP.get(' ', [0x0]*6))
        for r, row_byte in enumerate(bitmap):
            if row_byte & 0x8: draw.point((x_cursor+0, y+r), fill=color)
            if row_byte & 0x4: draw.point((x_cursor+1, y+r), fill=color)
            if row_byte & 0x2: draw.point((x_cursor+2, y+r), fill=color)
            if row_byte & 0x1: draw.point((x_cursor+3, y+r), fill=color)
        x_cursor += 5
    return x_cursor

# ================= DEVICE ID =================
def get_device_id():
    path_to_use = ID_FILE_PATH
    if not os.path.isfile(ID_FILE_PATH):
        try:
            test_uuid = str(uuid.uuid4())
            with open(ID_FILE_PATH, 'w') as f: f.write(test_uuid)
        except:
            path_to_use = ID_FILE_FALLBACK
    if os.path.exists(path_to_use):
        with open(path_to_use, 'r') as f: return f.read().strip()
    return str(uuid.uuid4())

# --- WIFI PORTAL ---
class WifiPortal:
    def __init__(self, matrix, font):
        self.matrix = matrix; self.font = font; self.app = Flask(__name__)
        @self.app.route('/')
        def home(): return render_template_string(HTML_TEMPLATE, networks=self.get_available_networks())
        @self.app.route('/connect', methods=['POST'])
        def connect():
            ssid = request.form.get('ssid_manual') if request.form.get('ssid_select') == "__manual__" else request.form.get('ssid_select')
            threading.Thread(target=self.apply_and_reboot, args=(ssid, request.form['password'])).start()
            return "<html><body><h2>Settings Saved. Rebooting...</h2></body></html>"
    def apply_and_reboot(self, s, p):
        try: subprocess.run(['nmcli', 'dev', 'wifi', 'connect', s, 'password', p])
        except: pass
        time.sleep(3); subprocess.run(['reboot'])
    def get_available_networks(self):
        try:
            r = subprocess.run(['nmcli', '-t', '-f', 'SSID', 'dev', 'wifi', 'list'], capture_output=True, text=True)
            return sorted(list(set([n for n in r.stdout.split('\n') if n.strip()])))
        except: return []
    def check_internet(self):
        try: socket.create_connection(("8.8.8.8", 53), timeout=3); return True
        except: return False
    def run(self):
        if self.check_internet(): return True
        img = Image.new("RGB", (PANEL_W, PANEL_H), (0,0,0)); d = ImageDraw.Draw(img)
        d.text((2, 2), "WIFI SETUP MODE", font=self.font, fill=(255, 255, 0))
        d.text((2, 12), f"SSID: {SETUP_SSID}", font=self.font, fill=(255, 255, 255))
        self.matrix.SetImage(img.convert("RGB"))
        subprocess.run(['nmcli', 'dev', 'wifi', 'hotspot', 'ifname', 'wlan0', 'ssid', SETUP_SSID, 'password', SETUP_PASS])
        try: self.app.run(host='0.0.0.0', port=80)
        except: pass

# ================= MAIN CONTROLLER =================
class TickerStreamer:
    def __init__(self):
        print("Starting Ticker System...")
        self.device_id = get_device_id()
        print(f"  Device ID: {self.device_id}")
        if not os.path.exists(ASSETS_DIR):
            os.makedirs(ASSETS_DIR, exist_ok=True)

        self.mode = 'sports'
        self.mode_override = None
        self.running = True

        options = RGBMatrixOptions()
        options.rows = 32
        options.cols = 64
        options.chain_length = 6
        options.parallel = 1
        options.hardware_mapping = 'regular'
        options.gpio_slowdown = 2
        options.disable_hardware_pulsing = True
        options.drop_privileges = False
        self.matrix = RGBMatrix(options=options)

        try: self.font = ImageFont.truetype("DejaVuSans-Bold.ttf", 10)
        except: self.font = ImageFont.load_default()
        try: self.medium_font = ImageFont.truetype("DejaVuSans-Bold.ttf", 12)
        except: self.medium_font = ImageFont.load_default()
        try: self.big_font = ImageFont.truetype("DejaVuSans-Bold.ttf", 14)
        except: self.big_font = ImageFont.load_default()
        try: self.huge_font = ImageFont.truetype("DejaVuSans-Bold.ttf", 20)
        except: self.huge_font = ImageFont.load_default()
        try: self.clock_giant = ImageFont.truetype("DejaVuSans-Bold.ttf", 32)
        except: self.clock_giant = ImageFont.load_default()
        try: self.tiny = ImageFont.truetype("DejaVuSans.ttf", 9)
        except: self.tiny = ImageFont.load_default()
        try: self.micro = ImageFont.truetype("DejaVuSans.ttf", 7)
        except: self.micro = ImageFont.load_default()
        try: self.nano = ImageFont.truetype("DejaVuSans.ttf", 5)
        except: self.nano = ImageFont.load_default()

        self.portal = WifiPortal(self.matrix, self.font)
        threading.Thread(target=self.portal.run, daemon=True).start()

        self.games = []
        self.brightness = 1.0
        self.scroll_sleep = 0.05
        self.inverted = False
        self.is_pairing = False
        self.pairing_code = ""
        self.logo_cache = {}
        self.game_render_cache = {}
        self.anim_tick = 0

        # Active state management
        self.active_strip = None
        self.bg_strip = None
        self.bg_strip_ready = False
        self.new_games_list = []
        self.static_items = []
        self.static_index = 0
        self.showing_static = False
        self.static_until = 0.0
        self.static_current_image = None
        self.static_current_game = None
        self.last_applied_hash = ""
        self.current_data_hash = ""

        # Music state
        self.VINYL_SIZE = 51
        self.COVER_SIZE = 42
        self.vinyl_mask = Image.new("L", (self.COVER_SIZE, self.COVER_SIZE), 0)
        ImageDraw.Draw(self.vinyl_mask).ellipse((0, 0, self.COVER_SIZE, self.COVER_SIZE), fill=255)
        self.scratch_layer = Image.new("RGBA", (self.VINYL_SIZE, self.VINYL_SIZE), (0,0,0,0))
        self._init_vinyl_scratch()
        self.vinyl_rotation = 0.0
        self.text_scroll_pos = 0.0
        self.last_frame_time = time.time()
        self.dominant_color = (29, 185, 84)
        self.spindle_color = "black"
        self.last_cover_url = ""
        self.vinyl_cache = None
        self.prev_vinyl_cache = None
        self.prev_dominant_color = (29, 185, 84)
        self.fade_alpha = 1.0
        self.transitioning_out = False
        self.viz_heights = [2.0] * 16
        self.viz_phase = [random.random() * 10 for _ in range(16)]

        # Flight HUD colors
        self.C_BG = (5, 5, 8)
        self.C_AMBER = (255, 170, 0)
        self.C_BLUE_TXT = (80, 180, 255)
        self.C_WHT = (220, 220, 230)
        self.C_GRN = (80, 255, 80)
        self.C_RED = (255, 60, 60)
        self.C_GRY = (120, 120, 130)

        self.executor = concurrent.futures.ThreadPoolExecutor(max_workers=4)

        threading.Thread(target=self.poll_backend, daemon=True).start()

    def _init_vinyl_scratch(self):
        ds = ImageDraw.Draw(self.scratch_layer)
        ds.ellipse((0, 0, self.VINYL_SIZE-1, self.VINYL_SIZE-1), fill=(20, 20, 20), outline=(50,50,50))

    # ================= DISPLAY =================
    def update_display(self, pil_image):
        img = pil_image.convert("RGB")
        if self.inverted:
            img = img.rotate(180)
        target_b = int(max(0, min(100, self.brightness * 100)))
        self.matrix.brightness = target_b
        self.matrix.SetImage(img)

    # ================= MODE =================
    def set_mode(self, new_mode):
        self.mode = new_mode
        self.mode_override = new_mode
        print(f"  Mode -> {new_mode}")
        self.push_setting_to_server('mode', new_mode)
        self.last_applied_hash = ''
        self.current_data_hash = ''

    # ================= SERVER COMMUNICATION =================
    def push_setting_to_server(self, key, value):
        def _push():
            try:
                requests.post(
                    f"{BACKEND_URL}/ticker/{self.device_id}",
                    json={key: value},
                    headers={"X-Client-ID": self.device_id},
                    timeout=3, verify=False
                )
            except Exception as ex:
                print(f"  Setting push failed: {ex}")
        threading.Thread(target=_push, daemon=True).start()

    def push_flight_config(self, config_dict):
        def _push():
            try:
                payload = dict(config_dict)
                payload['ticker_id'] = self.device_id
                has_flight = bool(config_dict.get('track_flight_id', '').strip())
                has_airport = bool(config_dict.get('airport_code_iata', '').strip())
                if has_flight:
                    payload['mode'] = 'flight2'
                    payload['active_sports'] = {'flight_visitor': True, 'flight_airport': False}
                elif has_airport:
                    payload['mode'] = 'flights'
                    payload['active_sports'] = {'flight_visitor': False, 'flight_airport': True}
                resp = requests.post(
                    f"{BACKEND_URL}/api/config",
                    json=payload,
                    headers={"X-Client-ID": self.device_id},
                    timeout=5, verify=False
                )
                print(f"  Flight config pushed: {config_dict} -> {resp.status_code}")
            except Exception as ex:
                print(f"  Flight config push failed: {ex}")
        threading.Thread(target=_push, daemon=True).start()

    # ================= PAIRING SCREEN =================
    def draw_pairing_screen(self):
        img = Image.new("RGB", (PANEL_W, PANEL_H), (0, 0, 0))
        d = ImageDraw.Draw(img)
        code = self.pairing_code or "------"
        spaced = "  ".join(code)
        header = "PAIR CODE"
        hw = d.textlength(header, font=self.font)
        d.text(((PANEL_W - hw) / 2, 0), header, font=self.font, fill=(255, 200, 0))
        cw = d.textlength(spaced, font=self.huge_font)
        cx = (PANEL_W - cw) / 2
        d.text((cx, 10), spaced, font=self.huge_font, fill=(255, 255, 255))
        if int(time.time() * 2) % 2 == 0:
            d.ellipse((PANEL_W - 8, 2, PANEL_W - 3, 7), fill=(0, 200, 255))
        return img

    # ================= LOGO MANAGEMENT =================
    def download_and_process_logo(self, url, size=(24,24)):
        if not url:
            return
        cache_key = f"{url}_{size}"
        if cache_key in self.logo_cache:
            return
        try:
            filename = f"{hashlib.md5(url.encode()).hexdigest()}_{size[0]}x{size[1]}.png"
            local = os.path.join(ASSETS_DIR, filename)
            if os.path.exists(local):
                self.logo_cache[cache_key] = Image.open(local).convert("RGBA")
                return
            r = requests.get(url, timeout=5)
            if r.status_code == 200:
                img = Image.open(io.BytesIO(r.content)).convert("RGBA")
                # Resize in premultiplied alpha mode to prevent LANCZOS from blending
                # colored pixels with transparent-black pixels (causes desaturation)
                img = img.convert("RGBa")
                img.thumbnail(size, Image.Resampling.LANCZOS)
                img = img.convert("RGBA")
                final = Image.new("RGBA", size, (0,0,0,0))
                final.paste(img, ((size[0]-img.width)//2, (size[1]-img.height)//2))
                final.save(local, "PNG")
                self.logo_cache[cache_key] = final
        except:
            pass

    def get_logo(self, url, size=(24,24)):
        return self.logo_cache.get(f"{url}_{size}")

    # ================= DRAWING HELPERS =================
    def draw_arrow(self, d, x, y, is_up, color):
        if is_up:
            d.polygon([(x+2, y), (x, y+4), (x+4, y+4)], fill=color)
        else:
            d.polygon([(x, y), (x+4, y), (x+2, y+4)], fill=color)

    def draw_hockey_stick(self, draw, cx, cy, size):
        WOOD = (150, 75, 0); TAPE = (255, 255, 255)
        pattern = [[0,0,0,0,0,1,1,0],[0,0,0,0,0,1,1,0],[0,0,0,0,0,1,1,0],[0,0,0,0,1,1,1,0],
                   [0,0,0,0,1,1,0,0],[1,2,2,1,1,1,0,0],[1,2,2,1,1,0,0,0],[0,0,0,0,0,0,0,0]]
        sx, sy = cx - 4, cy - 4
        for y in range(8):
            for x in range(8):
                if pattern[y][x] == 1: draw.point((sx+x, sy+y), fill=WOOD)
                elif pattern[y][x] == 2: draw.point((sx+x, sy+y), fill=TAPE)

    def draw_shootout_indicators(self, draw, results, start_x, y):
        display_results = results[-3:]
        while len(display_results) < 3: display_results.append('pending')
        x_off = start_x
        for res in display_results:
            if res == 'pending': draw.rectangle((x_off, y, x_off+3, y+3), outline=(80,80,80))
            elif res == 'miss': draw.line((x_off, y, x_off+3, y+3), fill=(255,0,0)); draw.line((x_off, y+3, x_off+3, y), fill=(255,0,0))
            elif res == 'goal': draw.rectangle((x_off, y, x_off+3, y+3), fill=(0,255,0))
            x_off += 6

    def draw_soccer_shootout(self, draw, results, start_x, y):
        display_results = results[-5:]
        while len(display_results) < 5: display_results.append('pending')
        x_off = start_x
        if len(results) > 0: x_off -= 2
        for res in display_results:
            if res == 'pending': draw.rectangle((x_off, y, x_off+1, y+1), outline=(60,60,60))
            elif res == 'miss': draw.point((x_off, y), fill=(255,0,0)); draw.point((x_off+1, y+1), fill=(255,0,0))
            elif res == 'goal': draw.rectangle((x_off, y, x_off+1, y+1), fill=(0,255,0))
            x_off += 4

    def draw_baseball_hud(self, draw, x, y, o):
        for i in range(3): draw.rectangle((x+(i*4), y, x+(i*4)+1, y+1), fill=((255, 0, 0) if i < o else (40, 40, 40)))

    def shorten_status(self, status, sport=''):
        if not status: return ""
        sp = str(sport).lower()
        # Baseball: ^/V arrows for top/bottom, ordinal suffix preserved, no other munging
        if 'baseball' in sp or 'mlb' in sp:
            su = str(status).upper()
            for old, new in [("TOP ", "^"), ("BOTTOM ", "V"), ("BOT ", "V")]:
                su = su.replace(old, new)
            return su
        # All other sports: original logic unchanged
        s = str(status).upper().replace(" - ", " ").replace("FINAL", "FINAL").replace("/OT", " OT").replace("HALFTIME", "HALF")
        for old, new in [("TOP ", "^"), ("BOTTOM ", "V"), ("BOT ", "V")]:
            s = s.replace(old, new)
        for num in ["10", "11", "12", "1", "2", "3", "4", "5", "6", "7", "8", "9"]:
            for suf in ["TH", "ST", "ND", "RD"]:
                s = s.replace(f"{num}{suf}", num)
        s = s.replace("1ST", "P1").replace("2ND", "P2").replace("3RD", "P3").replace("4TH", "P4").replace("FULL TIME", "FT")
        for r in ["P1", "P2", "P3", "P4", "Q1", "Q2", "Q3", "Q4", "OT"]:
            s = s.replace(f"{r} ", f"{r}~")
        return s

    def draw_weather_pixel_art(self, d, icon_name, x, y):
        icon = str(icon_name).lower()
        SUN_Y = (255, 200, 0); CLOUD_W = (200, 200, 200); RAIN_B = (60, 100, 255); SNOW_W = (255, 255, 255)
        if 'sun' in icon or 'clear' in icon:
            d.ellipse((x+2, y+2, x+12, y+12), fill=SUN_Y)
            for rx, ry in [(x+7, y), (x+7, y+14), (x, y+7), (x+14, y+7), (x+2, y+2), (x+12, y+2), (x+2, y+12), (x+12, y+12)]:
                d.point((rx, ry), fill=SUN_Y)
        elif 'rain' in icon or 'drizzle' in icon:
            d.ellipse((x+2, y+2, x+14, y+10), fill=CLOUD_W)
            d.line((x+4, y+11, x+3, y+14), fill=RAIN_B); d.line((x+8, y+11, x+7, y+14), fill=RAIN_B); d.line((x+12, y+11, x+11, y+14), fill=RAIN_B)
        elif 'snow' in icon:
            d.ellipse((x+2, y+2, x+14, y+10), fill=CLOUD_W)
            d.point((x+4, y+12), fill=SNOW_W); d.point((x+8, y+14), fill=SNOW_W); d.point((x+12, y+12), fill=SNOW_W); d.point((x+6, y+15), fill=SNOW_W)
        elif 'storm' in icon or 'thunder' in icon:
            d.ellipse((x+2, y+2, x+14, y+10), fill=(100, 100, 100))
            d.line([(x+8, y+10), (x+6, y+13), (x+9, y+13), (x+7, y+16)], fill=SUN_Y, width=1)
        elif 'cloud' in icon or 'overcast' in icon:
            d.ellipse((x+4, y+4, x+16, y+12), fill=CLOUD_W); d.ellipse((x, y+6, x+10, y+12), fill=(180,180,180))
        else:
            d.ellipse((x+6, y+2, x+12, y+8), fill=SUN_Y); d.ellipse((x+2, y+6, x+14, y+14), fill=CLOUD_W)

    def get_aqi_color(self, aqi):
        try:
            val = int(aqi)
            if val <= 50: return (0, 255, 0)
            if val <= 100: return (255, 255, 0)
            if val <= 150: return (255, 126, 0)
            return (255, 0, 0)
        except:
            return (100, 100, 100)

    # ================= MUSIC HELPERS =================
    def extract_colors_and_spindle(self, pil_img):
        stat = ImageStat.Stat(pil_img)
        r, g, b = stat.mean[:3]
        lum = (0.299*r + 0.587*g + 0.114*b)
        self.spindle_color = "white" if lum < 140 else "black"
        h, s, v = colorsys.rgb_to_hsv(r/255.0, g/255.0, b/255.0)
        if s < 0.2: s = 0.0
        elif s < 0.5: s = min(1.0, s * 1.5)
        if v < 0.3: v = 0.5
        elif v < 0.8: v = min(1.0, v * 1.3)
        nr, ng, nb = colorsys.hsv_to_rgb(h, s, v)
        self.dominant_color = (int(nr*255), int(ng*255), int(nb*255))

    def render_visualizer(self, draw, x, y, width, height, is_playing=True):
        bar_count = 16; bar_w = 2; gap = 3
        center_y = y + (height // 2)
        t = time.time()
        base_r, base_g, base_b = self.dominant_color
        grad_colors = []
        for i in range(bar_count):
            factor = i / (bar_count - 1) * 0.6
            nr = int(base_r + (255 - base_r) * factor)
            ng = int(base_g + (255 - base_g) * factor)
            nb = int(base_b + (255 - base_b) * factor)
            grad_colors.append((nr, ng, nb))
        for i in range(bar_count):
            if is_playing:
                base = math.sin(t * 4 + self.viz_phase[i])
                noise = math.sin(t * 12 + (i * 0.5)) * random.uniform(0.5, 1.2)
                if i < 5: amp = 8.0 + (math.sin(t * 2) * 2)
                elif i < 11: amp = 6.0
                else: amp = 4.0 + (noise * 2)
                target_h = max(2, min(height, abs(base + noise) * amp))
            else:
                target_h = 2.0
            self.viz_heights[i] += (target_h - self.viz_heights[i]) * 0.25
            h_int = int(self.viz_heights[i])
            start_y = center_y - (h_int // 2)
            bx = x + (i * (bar_w + gap))
            draw.rectangle((bx, start_y, bx+bar_w-1, start_y + h_int), fill=grad_colors[i])

    def draw_scrolling_text(self, canvas, text_str, font, x, y, max_width, scroll_pos, color="white"):
        text_str = normalize_special_chars(str(text_str).strip())
        temp_d = ImageDraw.Draw(canvas)
        text_w = temp_d.textlength(text_str, font=font)
        max_width = int(max_width); x = int(x); y = int(y)
        if text_w <= (max_width - 2):
            temp_d.text((x, y), text_str, font=font, fill=color)
            return
        GAP = 40
        total_loop = text_w + GAP
        current_offset = scroll_pos % total_loop
        txt_img = Image.new("RGBA", (max_width, 32), (0,0,0,0))
        d_txt = ImageDraw.Draw(txt_img)
        d_txt.text((int(-current_offset), 0), text_str, font=font, fill=color)
        if (-current_offset + text_w) < max_width:
            d_txt.text((int(-current_offset + total_loop), 0), text_str, font=font, fill=color)
        canvas.paste(txt_img, (x, y), txt_img)

    # ================= FLIGHT PIXEL HELPERS =================
    def _pixel(self, draw, x, y, color):
        if 0 <= x < PANEL_W and 0 <= y < PANEL_H:
            draw.point((x, y), fill=color)

    def _icon_plane(self, draw, x, y, color):
        pts = [(x+2,y),(x+1,y+1),(x+2,y+1),(x+3,y+1),(x,y+2),(x+1,y+2),(x+2,y+2),
               (x+3,y+2),(x+4,y+2),(x+2,y+3),(x+1,y+4),(x+2,y+4),(x+3,y+4)]
        for px, py in pts:
            self._pixel(draw, px, py, color)

    # ================= CARD RENDERERS =================

    def draw_stock_card(self, game):
        img = Image.new("RGBA", (128, 32), (0, 0, 0, 255))
        d = ImageDraw.Draw(img)
        try:
            symbol = str(game.get('home_abbr', 'UNK'))
            if not symbol.startswith('$') and not any(c.isdigit() for c in symbol): symbol = "$" + symbol
            price = str(game.get('home_score', '0.00'))
            if not price.startswith('$'): price = "$" + price
            change_pct = str(game.get('away_score', '0.00%'))
            change_amt = str(game.get('situation', {}).get('change', '0.00'))
            if not change_amt.startswith('$') and not change_amt.startswith('-'): change_amt = "$" + change_amt
            if change_amt.startswith('-'): change_amt = change_amt.replace('-', '-$')
            logo = self.get_logo(game.get('home_logo'), size=(24, 24))
            is_up = not change_pct.startswith('-')
            color = (0, 255, 0) if is_up else (255, 0, 0)
            if logo: img.paste(logo, (2, 4), logo)
            x_text_start = 28 if logo else 2
            d.text((x_text_start, -2), symbol, font=self.big_font, fill=(255, 255, 255))
            d.text((x_text_start, 11), price, font=self.huge_font, fill=color)
            RIGHT_ALIGN = 126
            w_pct = d.textlength(change_pct, font=self.medium_font)
            pct_x = int(RIGHT_ALIGN - w_pct)
            arrow_x = pct_x - 6
            self.draw_arrow(d, arrow_x, 4, is_up, color)
            d.text((pct_x, -1), change_pct, font=self.medium_font, fill=color)
            w_price = d.textlength(price, font=self.huge_font)
            overlap_x = x_text_start + w_price + 6
            if arrow_x > overlap_x:
                w_amt = d.textlength(change_amt, font=self.medium_font)
                amt_x = int(RIGHT_ALIGN - w_amt)
                d.text((amt_x, 15), change_amt, font=self.medium_font, fill=color)
        except Exception as e:
            print(f"Stock Render Err: {e}")
        return img

    def draw_leaderboard_card(self, game):
        img = Image.new("RGBA", (64, 32), (0, 0, 0, 255))
        d = ImageDraw.Draw(img)
        try:
            sport = str(game.get('sport', '')).lower()
            accent_color = (100, 100, 100)
            if 'f1' in sport: accent_color = (255, 0, 0)
            elif 'nascar' in sport: accent_color = (255, 215, 0)
            elif 'indy' in sport: accent_color = (0, 144, 255)
            d.rectangle((0, 0, 63, 7), fill=(20, 20, 20))
            d.line((0, 8, 63, 8), fill=accent_color, width=1)
            t_name = str(game.get('tourney_name', '')).upper().replace("GRAND PRIX", "GP").replace("TT", "").strip()[:14]
            header_w = len(t_name) * 5
            hx = (64 - header_w) // 2
            draw_tiny_text(d, hx, 1, t_name, (220, 220, 220))
            leaders = game.get('leaders', [])
            if not isinstance(leaders, list): leaders = []
            y_off = 10
            for i, p in enumerate(leaders[:3]):
                rank_color = (200, 200, 200)
                if i == 0: rank_color = (255, 215, 0)
                elif i == 1: rank_color = (192, 192, 192)
                elif i == 2: rank_color = (205, 127, 50)
                acronym = str(p.get('name', 'UNK'))[:3].upper()
                raw_score = str(p.get('score', ''))
                display_score = "LDR" if "LEADER" in raw_score.upper() else raw_score
                draw_tiny_text(d, 1, y_off, str(i+1), rank_color)
                draw_tiny_text(d, 8, y_off, acronym, (255, 255, 255))
                score_w = len(display_score) * 5
                draw_tiny_text(d, 63 - score_w, y_off, display_score, (255, 100, 100))
                y_off += 8
        except:
            pass
        return img

    def draw_weather_detailed(self, game):
        img = Image.new("RGBA", (384, 32), (0, 0, 0, 255))
        d = ImageDraw.Draw(img)
        sit = game.get('situation', {})
        stats = sit.get('stats', {})
        forecast = sit.get('forecast', [])
        cur_icon = sit.get('icon', 'cloud')
        self.draw_weather_pixel_art(d, cur_icon, 4, 8)
        location_name = str(game.get('away_abbr', 'CITY')).upper()
        d.text((28, -2), location_name, font=self.tiny, fill=(255, 255, 255))
        temp_f = str(game.get('home_abbr', '00')).replace('°', '')
        d.text((28, 8), f"{temp_f}°F", font=self.big_font, fill=(255, 255, 255))
        aqi_val = stats.get('aqi', '0')
        aqi_col = self.get_aqi_color(aqi_val)
        uv_val = str(stats.get('uv', '0'))
        d.rectangle((28, 20, 70, 27), fill=aqi_col)
        d.text((30, 19), f"AQI:{aqi_val}", font=self.micro, fill=(0,0,0))
        d.text((75, 19), f"UV:{uv_val}", font=self.micro, fill=(255, 100, 255))
        d.line((115, 2, 115, 30), fill=(50, 50, 50))
        if not forecast:
            forecast = [
                {'day': 'MON', 'icon': 'sun', 'high': 80, 'low': 70},
                {'day': 'TUE', 'icon': 'rain', 'high': 75, 'low': 65},
                {'day': 'WED', 'icon': 'cloud', 'high': 78, 'low': 68},
                {'day': 'THU', 'icon': 'storm', 'high': 72, 'low': 60},
                {'day': 'FRI', 'icon': 'sun', 'high': 82, 'low': 72}
            ]
        x_cursor = 125
        for day in forecast[:5]:
            d.text((x_cursor, 0), day.get('day', 'UNK')[:3], font=self.micro, fill=(150, 150, 150))
            self.draw_weather_pixel_art(d, day.get('icon', 'cloud'), x_cursor, 11)
            hi = day.get('high', '--')
            lo = day.get('low', '--')
            d.text((x_cursor, 22), f"{hi}", font=self.nano, fill=(255, 100, 100))
            d.text((x_cursor + 14, 22), "/", font=self.nano, fill=(100, 100, 100))
            d.text((x_cursor + 20, 22), f"{lo}", font=self.nano, fill=(100, 100, 255))
            x_cursor += 50
        return img

    def draw_clock_modern(self):
        img = Image.new("RGBA", (PANEL_W, 32), (0, 0, 0, 255))
        d = ImageDraw.Draw(img)
        now = datetime.now()
        date_str = now.strftime("%A %B %d").upper()
        w_date = d.textlength(date_str, font=self.tiny)
        d.text(((PANEL_W - w_date)/2, 0), date_str, font=self.tiny, fill=(200, 200, 200))
        time_str = now.strftime("%I:%M:%S").lstrip('0')
        w_time = d.textlength(time_str, font=self.clock_giant)
        d.text(((PANEL_W - w_time)/2, 14), time_str, font=self.clock_giant, fill=(255, 255, 255))
        sec_val = now.second
        ms_val = now.microsecond
        total_seconds = sec_val + (ms_val / 1000000.0)
        bar_width = int((total_seconds / 60.0) * PANEL_W)
        d.rectangle((0, 31, PANEL_W, 31), fill=(30, 30, 30))
        d.rectangle((0, 31, bar_width, 31), fill=(0, 200, 255))
        return img

    def draw_music_card(self, game):
        img = Image.new("RGBA", (PANEL_W, 32), (0, 0, 0, 255))
        d = ImageDraw.Draw(img)
        artist = str(game.get('home_abbr', 'Unknown')).strip()
        song = str(game.get('away_abbr', 'Unknown')).strip()
        cover_url = game.get('home_logo')
        next_covers = game.get('next_logos', [])
        sit = game.get('situation', {})
        is_playing = sit.get('is_playing', False)
        server_progress = float(sit.get('progress', 0.0))
        server_fetch_ts = float(sit.get('fetch_ts', time.time()))
        total_dur = float(sit.get('duration', 1.0))
        if total_dur <= 0: total_dur = 1.0
        now = time.time()
        dt_frame = now - self.last_frame_time
        self.last_frame_time = now
        if is_playing:
            time_since_fetch = now - server_fetch_ts
            local_progress = server_progress + time_since_fetch
            self.vinyl_rotation = (self.vinyl_rotation - (100.0 * dt_frame)) % 360
            self.text_scroll_pos += (15.0 * dt_frame)
        else:
            local_progress = server_progress
        local_progress = min(local_progress, total_dur)

        time_remaining = total_dur - local_progress
        if is_playing and time_remaining <= 5.0 and not self.transitioning_out:
            self.transitioning_out = True
            self.prev_vinyl_cache = self.vinyl_cache
            self.prev_dominant_color = self.dominant_color
            self.fade_alpha = 0.5
            if next_covers and next_covers[0]:
                try:
                    next_url = next_covers[0]
                    raw_next = self.get_logo(next_url, (self.COVER_SIZE, self.COVER_SIZE))
                    if not raw_next:
                        raw_next = Image.open(io.BytesIO(requests.get(next_url, timeout=1).content)).convert("RGBA")
                    raw_next = raw_next.resize((self.COVER_SIZE, self.COVER_SIZE))
                    next_art = ImageOps.fit(raw_next, (self.COVER_SIZE, self.COVER_SIZE), centering=(0.5, 0.5))
                    next_art.putalpha(self.vinyl_mask)
                    self.vinyl_cache = next_art
                    stat = ImageStat.Stat(raw_next)
                    self.dominant_color = tuple(int(x) for x in stat.mean[:3])
                except:
                    pass

        if cover_url != self.last_cover_url:
            if not self.transitioning_out:
                self.fade_alpha = 1.0
                self.prev_vinyl_cache = None
            else:
                self.transitioning_out = False
            self.last_cover_url = cover_url
            if cover_url:
                try:
                    raw = self.get_logo(cover_url, (self.COVER_SIZE, self.COVER_SIZE))
                    if not raw:
                        raw = Image.open(io.BytesIO(requests.get(cover_url, timeout=1).content)).convert("RGBA")
                    self.extract_colors_and_spindle(raw)
                    raw = raw.resize((self.COVER_SIZE, self.COVER_SIZE))
                    output = ImageOps.fit(raw, (self.COVER_SIZE, self.COVER_SIZE), centering=(0.5, 0.5))
                    output.putalpha(self.vinyl_mask)
                    self.vinyl_cache = output
                except:
                    pass

        if self.fade_alpha < 1.0:
            self.fade_alpha = min(1.0, self.fade_alpha + (0.1 * dt_frame))
        t_alpha = self.fade_alpha
        smooth_alpha = t_alpha * t_alpha * (3 - 2 * t_alpha)
        def blend_colors(c1, c2, alpha):
            return tuple(int(c1[i] + (c2[i] - c1[i]) * alpha) for i in range(3))
        current_ui_color = blend_colors(self.prev_dominant_color, self.dominant_color, smooth_alpha)

        composite = self.scratch_layer.copy()
        if self.vinyl_cache:
            if smooth_alpha < 1.0 and self.prev_vinyl_cache:
                blended_cover = Image.blend(self.prev_vinyl_cache, self.vinyl_cache, smooth_alpha)
                offset = (self.VINYL_SIZE - self.COVER_SIZE) // 2
                composite.paste(blended_cover, (offset, offset), blended_cover)
            else:
                offset = (self.VINYL_SIZE - self.COVER_SIZE) // 2
                composite.paste(self.vinyl_cache, (offset, offset), self.vinyl_cache)
        draw_comp = ImageDraw.Draw(composite)
        draw_comp.ellipse((22, 22, 28, 28), fill="#222")
        draw_comp.ellipse((23, 23, 27, 27), fill=self.spindle_color)
        rotated = composite.rotate(self.vinyl_rotation, resample=Image.Resampling.BICUBIC)
        img.paste(rotated, (4, -9), rotated)

        TEXT_X = 60
        self.draw_scrolling_text(img, song, self.medium_font, TEXT_X, 0, 188, self.text_scroll_pos, "white")
        self.draw_scrolling_text(img, artist, self.tiny, TEXT_X + 16, 17, 172, self.text_scroll_pos, (180, 180, 180))

        d.ellipse((TEXT_X, 15, TEXT_X+12, 15+12), fill=current_ui_color)
        d.arc((TEXT_X+3, 15+3, TEXT_X+9, 15+9), 190, 350, fill="black", width=1)
        d.arc((TEXT_X+3, 15+5, TEXT_X+9, 15+11), 190, 350, fill="black", width=1)
        d.arc((TEXT_X+4, 15+7, TEXT_X+8, 15+12), 190, 350, fill="black", width=1)

        old_dom = self.dominant_color
        self.dominant_color = current_ui_color
        self.render_visualizer(d, 248, 6, 80, 20, is_playing=is_playing)
        self.dominant_color = old_dom

        pct = min(1.0, max(0.0, local_progress / total_dur))
        d.rectangle((0, 31, int(PANEL_W * pct), 31), fill=current_ui_color)
        def fmt_time(seconds):
            m, s = divmod(int(max(0, seconds)), 60)
            return f"{m}:{s:02d}"
        rem_str = f"-{fmt_time(total_dur - local_progress)}"
        d.text((PANEL_W - d.textlength(rem_str, font=self.micro) - 5, 10), rem_str, font=self.micro, fill="white")
        return img

    # ================= FLIGHT RENDERERS =================

    def draw_flight_visitor(self, game):
        """Full-width (384x32) visitor tracking display — amber themed."""
        img = Image.new("RGBA", (PANEL_W, PANEL_H), self.C_BG + (255,))
        d = ImageDraw.Draw(img)

        guest_name = str(game.get('guest_name', game.get('id', '???')))
        flight_id = str(game.get('id', '???'))
        route_origin = str(game.get('origin_city', '???'))
        route_dest = str(game.get('dest_city', '???'))
        alt = int(game.get('alt', 0))
        dist = int(game.get('dist', 0))
        speed = int(game.get('speed', 0))
        eta_str = str(game.get('eta_str', '--'))
        progress = int(game.get('progress', 0))
        status = str(game.get('status', 'scheduled'))
        is_live = game.get('is_live', False)
        try:
            delay_min = int(float(game.get('delay_min', 0) or 0))
        except (TypeError, ValueError):
            delay_min = 0
        is_delayed = bool(game.get('is_delayed', False)) or delay_min > 0 or ('delay' in status.lower())
        plane_type = str(game.get('aircraft_type', '') or '').strip()
        if plane_type:
            plane_type = plane_type[:60]

        def with_plane_label(text):
            return f"{text}  {plane_type}" if plane_type else text

        if is_delayed:
            plane_color = self.C_RED
        else:
            plane_color = self.C_GRN if is_live else self.C_AMBER
        self._icon_plane(d, 6, 2, plane_color)
        draw_tiny_text(d, 18, 2, guest_name, self.C_AMBER)
        if guest_name.upper() != flight_id.upper():
            id_w = len(flight_id) * 5
            draw_tiny_text(d, PANEL_W - id_w - 8, 2, flight_id, self.C_GRY)

        route_str = f"{route_origin} > {route_dest}"
        draw_tiny_text(d, 6, 10, route_str, self.C_BLUE_TXT)

        if is_live:
            stats = f"{dist} MI  {eta_str}  {speed} MPH  {alt:,} FT"
            draw_tiny_text(d, 6, 18, with_plane_label(stats), self.C_WHT)
        else:
            draw_tiny_text(d, 6, 18, with_plane_label(status.upper()), self.C_AMBER)

        bar_x, bar_y, bar_w, bar_h = 6, 27, 372, 3
        bar_bg = (15, 35, 15)
        bar_fill = self.C_GRN
        if is_delayed:
            bar_bg = (60, 10, 10)
            bar_fill = self.C_RED
        d.rectangle((bar_x, bar_y, bar_x + bar_w, bar_y + bar_h), fill=bar_bg)
        pct = progress / 100.0 if is_live else 0.02
        fill_w = int(bar_w * max(0.02, min(0.98, pct)))
        d.rectangle((bar_x, bar_y, bar_x + fill_w, bar_y + bar_h), fill=bar_fill)
        return img

    def draw_flight_airport(self, weather_item, arrivals, departures):
        """Full-width (384x32) airport HUD — composites weather + arrivals + departures."""
        img = Image.new("RGBA", (PANEL_W, PANEL_H), self.C_BG + (255,))
        d = ImageDraw.Draw(img)

        d.rectangle((0, 0, PANEL_W, 6), fill=(20, 30, 45))
        d.rectangle((0, 7, PANEL_W, 7), fill=(40, 90, 160))

        airport_name = str(weather_item.get('home_abbr', 'AIRPORT')) if weather_item else 'AIRPORT'
        draw_tiny_text(d, 3, 1, airport_name, self.C_BLUE_TXT)

        weather_temp = str(weather_item.get('away_abbr', '--')) if weather_item else '--'
        weather_cond = str(weather_item.get('status', '')) if weather_item else ''
        weather_str = f"{weather_temp} {weather_cond}"
        wx_w = len(weather_str) * 5
        draw_tiny_text(d, PANEL_W - wx_w - 3, 1, weather_str, self.C_WHT)

        d.rectangle((2, 9, 189, 30), fill=(25, 35, 50))
        draw_tiny_text(d, 5, 10, "NEXT ARRIVAL", self.C_GRY)
        for i, arr in enumerate(arrivals[:2]):
            flight_id = str(arr.get('away_abbr', '???'))
            from_city = str(arr.get('home_abbr', '???'))
            text_str = f"{flight_id} FROM {from_city}"[:36]
            draw_tiny_text(d, 5, 18 + i * 7, text_str, self.C_GRN)
        if not arrivals:
            draw_tiny_text(d, 5, 18, "--", self.C_GRY)

        d.rectangle((194, 9, 381, 30), fill=(25, 35, 50))
        draw_tiny_text(d, 197, 10, "NEXT DEPARTURE", self.C_GRY)
        for i, dep in enumerate(departures[:2]):
            flight_id = str(dep.get('away_abbr', '???'))
            to_city = str(dep.get('home_abbr', '???'))
            text_str = f"{flight_id} TO {to_city}"[:36]
            draw_tiny_text(d, 197, 18 + i * 7, text_str, self.C_RED)
        if not departures:
            draw_tiny_text(d, 197, 18, "--", self.C_GRY)

        return img

    # ================= SPORTS CARD RENDERER =================
    def draw_single_game(self, game):
        game_hash = self.get_game_hash(game)

        if game.get('type') == 'music' or game.get('sport') == 'music':
            return self.draw_music_card(game)

        if game.get('sport') == 'clock':
            return self.draw_clock_modern()

        if game.get('type') != 'weather':
            if game_hash in self.game_render_cache:
                return self.game_render_cache[game_hash]

        if game.get('type') == 'weather':
            img = self.draw_weather_detailed(game)
            self.game_render_cache[game_hash] = img
            return img

        if game.get('type') == 'stock_ticker' or str(game.get('sport', '')).startswith('stock'):
            img = self.draw_stock_card(game)
            self.game_render_cache[game_hash] = img
            return img

        if game.get('type') == 'leaderboard':
            img = self.draw_leaderboard_card(game)
            self.game_render_cache[game_hash] = img
            return img

        if game.get('type') == 'flight_visitor':
            img = self.draw_flight_visitor(game)
            self.game_render_cache[game_hash] = img
            return img

        if game.get('type') == 'flight_airport_hud':
            img = self.draw_flight_airport(
                game.get('_weather_item'),
                game.get('_arrivals', []),
                game.get('_departures', [])
            )
            self.game_render_cache[game_hash] = img
            return img

        # --- SPORTS SCOREBOARD ---
        img = Image.new("RGBA", (64, 32), (0, 0, 0, 0))
        if not isinstance(game, dict):
            return img
        try:
            d = ImageDraw.Draw(img)
            sport = str(game.get('sport', '')).lower()
            is_football = 'football' in sport or 'nfl' in sport or 'ncf' in sport
            is_hockey = 'hockey' in sport or 'nhl' in sport
            is_baseball = 'baseball' in sport or 'mlb' in sport
            is_soccer = 'soccer' in sport
            is_march_madness = 'march_madness' in sport
            is_active = (game.get('state') == 'in')
            sit = game.get('situation', {}) or {}
            poss = sit.get('possession')
            shootout = sit.get('shootout')

            a_score = str(game.get('away_score', ''))
            h_score = str(game.get('home_score', ''))
            has_indicator = is_active and (poss or sit.get('powerPlay') or sit.get('emptyNet'))
            is_wide = ((is_football and is_active) or len(a_score) >= 2 or len(h_score) >= 2 or has_indicator)
            if is_march_madness:
                is_wide = False
            if is_baseball:
                is_wide = (len(a_score) >= 2 or len(h_score) >= 2)

            logo_size = (16, 16) if is_wide else (24, 24)
            logo_y = 5 if is_wide else 0
            l1_pos = (2, logo_y) if is_wide else (0, logo_y)
            l2_pos = (46, logo_y) if is_wide else (40, logo_y)

            score_y = 10 if is_wide else 12

            l1 = self.get_logo(game.get('away_logo'), logo_size)
            if l1: img.paste(l1, l1_pos, l1)
            else: d.text(l1_pos, str(game.get('away_abbr','UNK'))[:3], font=self.micro, fill=(150,150,150))
            l2 = self.get_logo(game.get('home_logo'), logo_size)
            if l2: img.paste(l2, l2_pos, l2)
            else: d.text(l2_pos, str(game.get('home_abbr','UNK'))[:3], font=self.micro, fill=(150,150,150))

            score = f"{a_score}-{h_score}"
            w_sc = d.textlength(score, font=self.font)
            d.text(((64-w_sc)/2, score_y), score, font=self.font, fill=(255,255,255), stroke_width=1, stroke_fill=(0,0,0))

            status = self.shorten_status(game.get('status', ''), game.get('sport', ''))
            st_x = (64 - len(status.replace('~', ''))*5) // 2
            draw_hybrid_text(d, st_x, 25, status, (180, 180, 180))

            if is_march_madness:
                h_seed = str(game.get('home_seed', ''))
                a_seed = str(game.get('away_seed', ''))
                if a_seed:
                    w = len(a_seed) * 5
                    sx = 12 - (w // 2)
                    draw_tiny_text(d, sx, 26, a_seed, (200, 200, 200))
                if h_seed:
                    w = len(h_seed) * 5
                    sx = 52 - (w // 2)
                    draw_tiny_text(d, sx, 26, h_seed, (200, 200, 200))

            elif shootout:
                away_so = shootout.get('away', []) if isinstance(shootout, dict) else []
                home_so = shootout.get('home', []) if isinstance(shootout, dict) else []
                if is_soccer:
                    self.draw_soccer_shootout(d, away_so, 2, 26)
                    self.draw_soccer_shootout(d, home_so, 46, 26)
                else:
                    self.draw_shootout_indicators(d, away_so, 2, 26)
                    self.draw_shootout_indicators(d, home_so, 46, 26)

            elif is_active and not is_march_madness:
                icon_y = logo_y + logo_size[1] + 3
                tx = -1
                side = None
                if (is_football or is_soccer) and poss: side = poss
                elif is_hockey and (sit.get('powerPlay') or sit.get('emptyNet')) and poss: side = poss

                away_id = str(game.get('away_id', '')); home_id = str(game.get('home_id', ''))
                away_abbr = str(game.get('away_abbr', '')); home_abbr = str(game.get('home_abbr', ''))
                side_str = str(side)

                poss_side = "none"
                if side_str and (side_str == away_abbr or side_str == away_id):
                    tx = l1_pos[0] + (logo_size[0]//2) - 2; poss_side = "away"
                elif side_str and (side_str == home_abbr or side_str == home_id):
                    tx = l2_pos[0] + (logo_size[0]//2) + 2; poss_side = "home"

                if tx != -1:
                    if is_football:
                        d.ellipse([tx-3, icon_y, tx+3, icon_y+4], fill=(170,85,0))
                        d.line([(tx, icon_y+1), (tx, icon_y+3)], fill='white', width=1)
                    elif is_hockey:
                        self.draw_hockey_stick(d, tx+2, icon_y+5, 3)
                    elif is_soccer:
                        d.ellipse((tx-2, icon_y, tx+2, icon_y+4), fill='white'); d.point((tx, icon_y+2), fill='black')

                if is_hockey:
                    if sit.get('emptyNet'):
                        w = d.textlength("EN", font=self.micro)
                        d.text(((64-w)/2, -1), "EN", font=self.micro, fill=(255,255,0))
                    elif sit.get('powerPlay'):
                        w = d.textlength("PP", font=self.micro)
                        d.text(((64-w)/2, -1), "PP", font=self.micro, fill=(255,255,0))
                elif is_baseball:
                    bases = [(31,2), (27,6), (35,6)]
                    active_bases = [sit.get('onSecond'), sit.get('onThird'), sit.get('onFirst')]
                    for i, p in enumerate(bases):
                        color = (255,255,150) if active_bases[i] else (45,45,45)
                        d.rectangle((p[0], p[1], p[0]+3, p[1]+3), fill=color)
                    b_count = int(sit.get('balls', 0)); s_count = int(sit.get('strikes', 0)); o_count = int(sit.get('outs', 0))
                    raw_st = str(game.get('status', '')).upper()
                    is_mid = any(x in raw_st for x in ['MID', 'MIDDLE', 'END'])
                    if not is_mid:
                        # Outs: 3 orange dots centered (between score and status)
                        o_x = (64 - 10) // 2
                        self.draw_baseball_hud(d, o_x, 23, o_count)
                        # S-B count on the side: strikes (orange) dash (grey) balls (green)
                        is_bot = 'BOT' in raw_st or 'BOTTOM' in raw_st
                        sb_x = 44 if is_bot else 5
                        draw_tiny_text(d, sb_x,      26, str(s_count), (255, 100,   0))
                        draw_tiny_text(d, sb_x +  5, 26, '-',          (100, 100, 100))
                        draw_tiny_text(d, sb_x + 10, 26, str(b_count), (  0, 200,   0))
                elif is_football:
                    dd = sit.get('downDist', '')
                    if dd:
                        s_dd = dd.split(' at ')[0]
                        w = d.textlength(s_dd, font=self.micro)
                        d.text(((64-w)/2, -1), s_dd, font=self.micro, fill=(0,255,0))
                if is_football and sit.get('isRedZone'):
                    d.rectangle((0, 0, 63, 31), outline=(255, 0, 0), width=1)
        except Exception as e:
            print(f"Game render error: {e}")

        self.game_render_cache[game_hash] = img
        return img

    def get_game_hash(self, game):
        s = f"{game.get('id')}_{game.get('home_score')}_{game.get('away_score')}_{game.get('situation', {}).get('change')}_{game.get('status')}"
        return hashlib.md5(s.encode()).hexdigest()

    def get_item_width(self, game):
        t = game.get('type')
        s = game.get('sport', '')
        if t == 'music' or s == 'music': return PANEL_W
        if t == 'stock_ticker' or (s and str(s).startswith('stock')): return 128
        if t == 'weather': return PANEL_W
        if t == 'flight_visitor': return PANEL_W
        if t == 'flight_airport_hud': return PANEL_W
        return 64

    # ================= STRIP BUILDER =================
    def build_seamless_strip(self, playlist):
        if not playlist:
            return None
        safe_playlist = playlist[:60]
        total_w = sum(self.get_item_width(g) for g in safe_playlist)
        strip = Image.new("RGBA", (total_w + PANEL_W, PANEL_H), (0,0,0,255))
        x = 0
        for g in safe_playlist:
            card = self.draw_single_game(g)
            strip.paste(card, (x, 0), card)
            x += card.width
        bx = x; i = 0
        while bx < total_w + PANEL_W and len(safe_playlist) > 0:
            g = safe_playlist[i % len(safe_playlist)]
            card = self.draw_single_game(g)
            strip.paste(card, (bx, 0), card)
            bx += card.width
            i += 1
        return strip

    def start_static_display(self):
        if not self.static_items:
            return False
        game = self.static_items[self.static_index % len(self.static_items)]
        self.static_index += 1
        self.static_current_game = game
        self.static_current_image = self.draw_single_game(game)
        self.static_until = time.time() + PAGE_HOLD_TIME
        self.showing_static = True
        return True

    # ================= RENDER LOOP =================
    def render_loop(self):
        strip_offset = 0.0

        while self.running:
            try:
                # Pairing screen
                if self.is_pairing:
                    frame = self.draw_pairing_screen()
                    self.update_display(frame)
                    time.sleep(0.1)
                    continue

                # Brightness zero = black screen
                if self.brightness <= 0.001:
                    self.matrix.Fill(0, 0, 0)
                    time.sleep(0.5)
                    continue

                # Detect music in static items
                spotify_data = next((g for g in self.static_items if g.get('id') == 'spotify_now'), None)
                music_is_playing = False
                if spotify_data:
                    music_is_playing = spotify_data.get('situation', {}).get('is_playing', False)
                if self.mode != 'music':
                    music_is_playing = False

                # PATH A: Static display (weather, clock, music, flights)
                if self.showing_static:
                    # If the server has sent new content (mode changed), exit immediately
                    # so PATH B can apply it on the next iteration instead of waiting
                    # for the PAGE_HOLD_TIME timer to expire.
                    if self.bg_strip_ready and self.current_data_hash != self.last_applied_hash:
                        self.showing_static = False
                        time.sleep(0.033)
                        continue

                    if self.static_current_game:
                        game_type = str(self.static_current_game.get('type', ''))
                        sport = str(self.static_current_game.get('sport', '')).lower()

                        if sport.startswith('clock') or game_type == 'music' or sport == 'music':
                            if game_type == 'music' or sport == 'music':
                                if spotify_data:
                                    self.static_current_game = spotify_data
                                    if music_is_playing:
                                        self.static_until = time.time() + 2.0
                            self.static_current_image = self.draw_single_game(self.static_current_game)
                            if self.static_current_image:
                                self.update_display(self.static_current_image)
                            if time.time() >= self.static_until:
                                self.showing_static = False
                            time.sleep(0.033)
                            continue

                    if self.static_current_image:
                        self.update_display(self.static_current_image)
                    if time.time() >= self.static_until:
                        self.showing_static = False
                    time.sleep(0.033)
                    continue

                # PATH B: Scrolling strip
                if self.bg_strip_ready:
                    new_hash = self.current_data_hash
                    if new_hash != self.last_applied_hash:
                        if self.bg_strip is not None:
                            if self.active_strip is None:
                                self.active_strip = self.bg_strip
                                self.games = self.new_games_list
                                strip_offset = 0
                            else:
                                current_x = int(strip_offset)
                                old_total_width = self.active_strip.width - PANEL_W if self.active_strip else 1
                                if old_total_width <= 0:
                                    old_total_width = 1
                                progress_pct = current_x / float(old_total_width)
                                new_total_width = self.bg_strip.width - PANEL_W
                                if new_total_width <= 0:
                                    new_total_width = 1
                                new_offset = int(progress_pct * new_total_width)
                                if new_offset < 0:
                                    new_offset = 0
                                if new_offset > new_total_width:
                                    new_offset = 0
                                self.active_strip = self.bg_strip
                                self.games = self.new_games_list
                                strip_offset = float(new_offset)
                                accum_w = 0
                                visible_item_id = None
                                pixel_delta = 0
                                for g in self.games:
                                    w = self.get_item_width(g)
                                    if accum_w + w > current_x:
                                        visible_item_id = g.get('id')
                                        pixel_delta = current_x - accum_w
                                        break
                                    accum_w += w
                                new_offset = -1
                                new_accum_w = 0
                                if visible_item_id:
                                    for g in self.new_games_list:
                                        w = self.get_item_width(g)
                                        if g.get('id') == visible_item_id:
                                            new_offset = new_accum_w + pixel_delta
                                            break
                                        new_accum_w += w
                                self.active_strip = self.bg_strip
                                self.games = self.new_games_list
                                strip_offset = float(new_offset) if new_offset >= 0 else 0.0
                        else:
                            self.active_strip = None
                        self.last_applied_hash = new_hash
                    self.bg_strip_ready = False

                    if music_is_playing and spotify_data:
                        self.static_current_game = spotify_data
                        self.static_current_image = self.draw_single_game(spotify_data)
                        self.static_until = time.time() + 2.0
                        self.showing_static = True
                        continue

                if self.active_strip:
                    total_w = self.active_strip.width - PANEL_W
                    if total_w <= 0: total_w = 1
                    if strip_offset >= total_w:
                        strip_offset = 0
                        if self.static_items:
                            if self.start_static_display():
                                continue
                    x = int(strip_offset)
                    view = self.active_strip.crop((x, 0, x + PANEL_W, PANEL_H))
                    self.update_display(view)
                    strip_offset += 1
                    if self.scroll_sleep > 0:
                        time.sleep(self.scroll_sleep)
                    # REFRESH_RATE = 0: tight loop for maximum speed
                else:
                    if self.static_items and self.start_static_display():
                        continue
                    self.update_display(self.draw_clock_modern())
                    time.sleep(0.033)

            except Exception as e:
                print(f"Render Error: {e}")
                time.sleep(0.5)

    # ================= BACKEND POLLER =================
    def poll_backend(self):
        print("Backend Poller Started...")
        last_hash = ""
        session = requests.Session()
        adapter = requests.adapters.HTTPAdapter(pool_connections=1, pool_maxsize=1)
        session.mount('http://', adapter)
        session.mount('https://', adapter)

        while self.running:
            try:
                url = f"{BACKEND_URL}/data?id={self.device_id}"
                r = session.get(url, timeout=5, verify=False)
                if r.status_code != 200:
                    time.sleep(2)
                    continue

                data = r.json()
                server_status = data.get('status', 'active')

                # Auto-pairing
                if server_status == 'pairing':
                    print(f"Server requests pairing. Auto-pairing as {self.device_id}...")
                    try:
                        r_pair = session.post(
                            f"{BACKEND_URL}/pair/id",
                            json={"id": self.device_id, "name": "Ticker"},
                            headers={"X-Client-ID": self.device_id},
                            timeout=5, verify=False
                        )
                        if r_pair.status_code == 200 and r_pair.json().get('success'):
                            print("Auto-pairing successful!")
                            self.is_pairing = False
                            time.sleep(0.5)
                            continue
                        else:
                            print(f"Auto-pairing failed: {r_pair.text}")
                    except Exception as pair_ex:
                        print(f"Auto-pairing error: {pair_ex}")
                    self.is_pairing = True
                    self.pairing_code = data.get('code', '------')
                    time.sleep(1)
                    continue
                else:
                    if self.is_pairing:
                        print("Paired successfully!")
                    self.is_pairing = False

                # Configuration
                local_conf = data.get('local_config') or {}
                if self.mode_override:
                    server_mode = local_conf.get('mode', 'sports')
                    if server_mode == self.mode_override:
                        self.mode_override = None
                else:
                    self.mode = local_conf.get('mode', 'sports')

                if server_status == 'sleep':
                    self.brightness = 0.0
                else:
                    raw_brightness = local_conf.get('brightness', 100)
                    self.brightness = float(raw_brightness) / 100.0

                self.scroll_sleep = local_conf.get('scroll_speed', 0.05)
                self.inverted = local_conf.get('inverted', False)

                # Content processing
                content = data.get('content', {})
                new_games = content.get('sports', [])

                current_payload = {'games': new_games, 'config': local_conf, 'status': server_status}
                current_hash = hashlib.md5(json.dumps(current_payload, sort_keys=True).encode()).hexdigest()
                self.current_data_hash = current_hash

                if current_hash != last_hash:
                    static_items = []
                    scrolling_items = []
                    logos_to_fetch = []

                    # Composite flight airport items
                    flight_weather = None
                    flight_arrivals = []
                    flight_departures = []
                    other_games = []

                    for g in new_games:
                        ft = g.get('type', '')
                        if ft == 'flight_weather':
                            flight_weather = g
                        elif ft == 'flight_arrival':
                            flight_arrivals.append(g)
                        elif ft == 'flight_departure':
                            flight_departures.append(g)
                        else:
                            other_games.append(g)

                    if flight_weather or flight_arrivals or flight_departures:
                        hud_item = {
                            'type': 'flight_airport_hud',
                            'sport': 'flight',
                            'id': 'airport_hud',
                            'is_shown': True,
                            '_weather_item': flight_weather,
                            '_arrivals': flight_arrivals,
                            '_departures': flight_departures,
                        }
                        other_games.append(hud_item)

                    for g in other_games:
                        sport = str(g.get('sport', '')).lower()
                        g_type = g.get('type', '')
                        is_music = (g_type == 'music' or sport == 'music')

                        if is_music:
                            if g.get('home_logo'): logos_to_fetch.append((g.get('home_logo'), (42, 42)))
                            for nurl in g.get('next_logos', []):
                                if nurl: logos_to_fetch.append((nurl, (42, 42)))
                        else:
                            if g.get('home_logo'):
                                logos_to_fetch.append((g.get('home_logo'), (24, 24)))
                                logos_to_fetch.append((g.get('home_logo'), (16, 16)))
                            if g.get('away_logo'):
                                logos_to_fetch.append((g.get('away_logo'), (24, 24)))
                                logos_to_fetch.append((g.get('away_logo'), (16, 16)))

                        if g_type == 'weather' or sport.startswith('clock') or is_music or g_type == 'flight_visitor' or g_type == 'flight_airport_hud':
                            static_items.append(g)
                        else:
                            scrolling_items.append(g)

                    unique_logos = list(set(logos_to_fetch))
                    if unique_logos:
                        fs = [self.executor.submit(self.download_and_process_logo, u, s) for u, s in unique_logos]
                        concurrent.futures.wait(fs)

                    self.new_games_list = scrolling_items
                    self.static_items = static_items
                    self.static_index = 0

                    if scrolling_items:
                        self.bg_strip = self.build_seamless_strip(scrolling_items)
                    else:
                        self.bg_strip = None

                    self.game_render_cache.clear()
                    self.bg_strip_ready = True
                    last_hash = current_hash

                time.sleep(0.5)

            except Exception as e:
                print(f"Poll Error: {e}")
                time.sleep(2)


# ================= ENTRY POINT =================
if __name__ == "__main__":
    ticker = TickerStreamer()
    try:
        ticker.render_loop()
    except KeyboardInterrupt:
        print("Stopping...")
        ticker.running = False
