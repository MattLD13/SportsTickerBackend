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
BACKEND_URL = "http://localhost:5000"

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


def load_monospace_font(size, bold=False):
    font_candidates = ["DejaVuSansMono-Bold.ttf", "DejaVuSansMono.ttf"] if bold else ["DejaVuSansMono.ttf"]
    for font_name in font_candidates:
        try:
            return ImageFont.truetype(font_name, size)
        except:
            continue
    return ImageFont.load_default()

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

        self.font = load_monospace_font(10, bold=True)
        self.medium_font = load_monospace_font(12, bold=True)
        self.big_font = load_monospace_font(14, bold=True)
        self.huge_font = load_monospace_font(20, bold=True)
        self.clock_giant = load_monospace_font(28, bold=True)
        self.tiny = load_monospace_font(9)
        self.micro = load_monospace_font(7)
        self.nano = load_monospace_font(5)
        self.score_default_font = ImageFont.load_default()

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
            
    def draw_side_arrow(self, draw, x, y, is_left, color):
        if is_left:
            draw.polygon([(x+4, y), (x, y+3), (x+4, y+6)], fill=color)
        else:
            draw.polygon([(x, y), (x+4, y+3), (x, y+6)], fill=color)

    def draw_bat(self, draw, cx, by):
        """
        Baseball bat icon. cx = horizontal center, by = top y.
        4px wide (cx-2..cx+1), 18px tall. Barrel at top, knob at bottom.
        """
        bc = (220, 180, 120)   # barrel wood
        hc = (180, 135,  65)   # handle
        kc = (150, 105,  40)   # knob
        draw.rectangle([cx-2, by+0,  cx+1, by+7],  fill=bc)   # barrel
        draw.rectangle([cx-1, by+8,  cx+0, by+9],  fill=bc)   # taper
        draw.rectangle([cx-1, by+10, cx+0, by+15], fill=hc)   # handle
        draw.rectangle([cx-2, by+16, cx+1, by+17], fill=kc)   # knob

    def draw_outlined_text(self, d, x, y, text, font, fill, outline, anchor="mm"):
        for dx in [-1, 0, 1]:
            for dy in [-1, 0, 1]:
                if dx == 0 and dy == 0: continue
                d.text((x+dx, y+dy), text, font=font, fill=outline, anchor=anchor)
        d.text((x, y), text, font=font, fill=fill, anchor=anchor)

    def get_team_color(self, game, side='home'):
        c = game.get(f'{side}_color')
        if c:
            try:
                c = c.lstrip('#')
                return tuple(int(c[i:i+2], 16) for i in (0, 2, 4))
            except: pass
        logo = self.get_logo(game.get(f'{side}_logo'), (24, 24))
        if logo:
            stat = ImageStat.Stat(logo)
            return tuple(int(x) for x in stat.mean[:3])
        return (60, 60, 60)

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
        if 'baseball' in sp or 'mlb' in sp or 'wbc' in sp:
            su = str(status).upper()
            for old, new in [("TOP ", "^"), ("BOTTOM ", "V"), ("BOT ", "V")]:
                su = su.replace(old, new)
            return su
        s = str(status).upper().replace(" - ", " ").replace("FINAL", "FINAL").replace("/OT", " OT").replace("HALFTIME", "HALF")
        for old, new in [("TOP ", "^"), ("BOTTOM ", "V"), ("BOT ", "V")]:
            s = s.replace(old, new)
        if s.startswith("END "):
            return s
        for num in ["10", "11", "12", "1", "2", "3", "4", "5", "6", "7", "8", "9"]:
            for suf in ["TH", "ST", "ND", "RD"]:
                s = s.replace(f"{num}{suf}", num)
        s = s.replace("1ST", "P1").replace("2ND", "P2").replace("3RD", "P3").replace("4TH", "P4").replace("FULL TIME", "FT")
        for r in ["P1", "P2", "P3", "P4", "Q1", "Q2", "Q3", "Q4", "OT"]:
            s = s.replace(f"{r} ", f"{r}~")
        return s

    def draw_weather_pixel_art(self, d, icon_name, x, y):
        icon = str(icon_name).lower()
        SUN_Y = (255, 200, 0); CLOUD_W = (205, 210, 220); RAIN_B = (60, 130, 255); SNOW_W = (210, 235, 255)
        if 'sun' in icon or 'clear' in icon:
            d.ellipse((x+3, y+3, x+11, y+11), fill=SUN_Y)
            for rx, ry in [(x+7, y), (x+7, y+14), (x, y+7), (x+14, y+7)]:
                d.line([(rx, ry), (rx, ry+1)], fill=SUN_Y)
            for rx, ry in [(x+2, y+2), (x+12, y+2), (x+2, y+12), (x+12, y+12)]:
                d.point((rx, ry), fill=SUN_Y)
        elif 'fog' in icon or 'mist' in icon or 'haze' in icon:
            for fy in [y+3, y+6, y+9, y+12]:
                d.line([(x+2, fy), (x+13, fy)], fill=(170, 175, 195))
        elif 'rain' in icon or 'drizzle' in icon or 'shower' in icon:
            d.ellipse((x+1, y+1, x+14, y+9), fill=CLOUD_W)
            for rx, ry in [(x+3, y+11), (x+7, y+12), (x+11, y+11), (x+5, y+14), (x+9, y+13)]:
                d.line([(rx, ry), (rx-1, ry+2)], fill=RAIN_B)
        elif 'snow' in icon or 'blizzard' in icon:
            d.ellipse((x+1, y+1, x+14, y+9), fill=(185, 195, 210))
            for rx, ry in [(x+3, y+12), (x+7, y+11), (x+11, y+12), (x+5, y+15), (x+9, y+14)]:
                d.point((rx, ry), fill=SNOW_W)
                d.point((rx, ry+1), fill=SNOW_W)
        elif 'storm' in icon or 'thunder' in icon or 'lightning' in icon:
            d.ellipse((x+1, y+1, x+14, y+9), fill=(75, 80, 100))
            d.line([(x+8, y+9), (x+6, y+13)], fill=(255, 220, 0), width=1)
            d.line([(x+6, y+13), (x+9, y+13)], fill=(255, 220, 0), width=1)
            d.line([(x+9, y+13), (x+7, y+16)], fill=(255, 220, 0), width=1)
        elif 'cloud' in icon or 'overcast' in icon:
            d.ellipse((x+5, y+3, x+15, y+11), fill=CLOUD_W)
            d.ellipse((x+0, y+6, x+11, y+13), fill=(175, 180, 192))
            d.ellipse((x+7, y+5, x+16, y+13), fill=(198, 202, 212))
        else:
            d.ellipse((x+5, y+1, x+12, y+8), fill=SUN_Y)
            d.point((x+11, y+1), fill=SUN_Y)
            d.ellipse((x+1, y+5, x+12, y+13), fill=(190, 195, 208))
            d.ellipse((x+7, y+4, x+16, y+12), fill=CLOUD_W)

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


    # ================= FULL BLEED SPORTS RENDERER =================
    def draw_sport_full_bleed(self, game):
        W = PANEL_W; H = PANEL_H
        img = Image.new("RGBA", (W, H), (0, 0, 0, 255))
        d = ImageDraw.Draw(img, "RGBA")

        sport    = str(game.get('sport', '')).lower()
        is_nfl   = 'football' in sport or 'nfl' in sport or 'ncf' in sport
        is_nhl   = 'hockey' in sport or 'nhl' in sport
        is_mlb   = 'baseball' in sport or 'mlb' in sport
        sit      = game.get('situation', {}) or {}
        home_clr = self.get_team_color(game, 'home')
        away_clr = self.get_team_color(game, 'away')
        h_score  = str(game.get('home_score', ''))
        a_score  = str(game.get('away_score', ''))
        home_ab  = str(game.get('home_abbr', '')).upper()
        away_ab  = str(game.get('away_abbr', '')).upper()
        poss_ab  = str(sit.get('possession', '')).upper()

        # ── FOOTBALL: full field matching HTML footballField() ───────────────
        if is_nfl:
            def _parse_hex_color(value):
                try:
                    c = str(value or '').strip().lstrip('#')
                    if len(c) == 6:
                        return tuple(int(c[i:i+2], 16) for i in (0, 2, 4))
                except Exception:
                    pass
                return None

            # Prefer explicit team colors; if missing, fall back to a readable
            # default palette (instead of logo-average grays).
            home_ez = _parse_hex_color(game.get('home_color')) or home_clr
            away_ez = _parse_hex_color(game.get('away_color')) or away_clr

            def _is_dull(c):
                return max(c) - min(c) < 25

            if _is_dull(home_ez):
                home_ez = (155, 32, 32)
            if _is_dull(away_ez):
                away_ez = (32, 62, 155)

            EZ_RATIO = 30 / 360
            ezW    = W * EZ_RATIO          # ~32 px
            playW  = W * (300 / 360)       # ~320 px
            hT     = H * (70.75 / 160)     # upper hash row
            hB     = H * (89.25 / 160)     # lower hash row

            # 1 · Grass bands (10 alternating strips)
            for i in range(10):
                bx = ezW + i * playW / 10
                d.rectangle([bx, 0, bx + playW / 10, H],
                            fill=(22, 52, 18) if i % 2 == 0 else (27, 64, 24))

            # 2 · End zones  HOME=left  AWAY=right
            d.rectangle([0, 0, ezW, H], fill=home_ez)
            d.rectangle([W - ezW, 0, W, H], fill=away_ez)
            d.line([(ezW, 0), (ezW, H)],         fill=(255, 255, 255, 230))
            d.line([(W - ezW, 0), (W - ezW, H)], fill=(255, 255, 255, 230))

            # 3 · 10-yard stripe lines
            for i in range(11):
                lx = ezW + i * playW / 10
                op = 115 if i == 5 else 64
                d.line([(lx, 0), (lx, H)], fill=(255, 255, 255, op))

            # 4 · Hash marks
            for y in range(1, 100):
                hx = ezW + y / 100 * playW
                is5 = (y % 5 == 0)
                hl  = H * 0.042 if is5 else H * 0.022
                op  = 128 if is5 else 66
                d.line([(hx, hT - hl), (hx, hT + hl)], fill=(255, 255, 255, op))
                d.line([(hx, hB - hl), (hx, hB + hl)], fill=(255, 255, 255, op))

            # 5 · Parse LOS and yards-to-go from situation
            los, ytg = -1, 10
            dd_text  = sit.get('downDist', '')
            at_team = ''
            is_goal_to_go = False
            drive_to_right = None  # True => offense driving toward right endzone
            parsed_yard = None
            if ' at ' in dd_text:
                after = dd_text.split(' at ', 1)[1].strip().split()
                if len(after) >= 2:
                    team, yard_s = after[0].upper(), after[1]
                    at_team = team
                    try:
                        yard = int(yard_s)
                        parsed_yard = yard
                        los = yard if team == home_ab else (100 - yard if team == away_ab else 50)
                    except ValueError:
                        pass
            if '&' in dd_text and los >= 0:
                ytg_raw = dd_text.split('&', 1)[1].strip().split()[0].lower()
                if ytg_raw in ('goal', 'gl'):
                    is_goal_to_go = True
                else:
                    try: ytg = int(ytg_raw)
                    except ValueError: ytg = 10

            # Infer drive direction once and use it everywhere (FD line + red-zone).
            if poss_ab == home_ab:
                drive_to_right = True
            elif poss_ab == away_ab:
                drive_to_right = False

            # Goal-to-go marker is most reliable for direction when possession is noisy.
            if is_goal_to_go and at_team:
                if poss_ab in (home_ab, away_ab):
                    if at_team == poss_ab:
                        # Offense on its own side: attacking opposite endzone.
                        drive_to_right = (poss_ab == home_ab)
                    else:
                        # Offense in opponent territory: attacking that side's endzone.
                        drive_to_right = (at_team == away_ab)
                elif at_team == home_ab:
                    drive_to_right = False
                elif at_team == away_ab:
                    drive_to_right = True

            if drive_to_right is None:
                drive_to_right = True

            if is_goal_to_go and los >= 0:
                if parsed_yard is not None:
                    ytg = max(1, parsed_yard)
                    los = max(0, min(100, 100 - parsed_yard if drive_to_right else parsed_yard))
                else:
                    goal_line = 100 if drive_to_right else 0
                    ytg = max(1, abs(goal_line - los))
                    # For goal-to-go visuals, place LOS near the attacking goal line
                    # so the ball/FD/red-zone all live on the scoring side.
                    los = max(0, min(100, 100 - ytg if drive_to_right else ytg))

            # 6 · Red zone tint
            is_rz = sit.get('isRedZone', False)
            if is_rz:
                rz_overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
                rz_d = ImageDraw.Draw(rz_overlay, "RGBA")
                if drive_to_right:
                    rz_d.rectangle([ezW + int(0.8 * playW), 0, W - ezW, H], fill=(220, 0, 0, 128))
                    d.line([(ezW + 0.8 * playW, 0), (ezW + 0.8 * playW, H)], fill=(255, 34, 34, 200), width=2)
                else:
                    rz_d.rectangle([ezW, 0, ezW + int(0.2 * playW), H], fill=(220, 0, 0, 128))
                    d.line([(ezW + 0.2 * playW, 0), (ezW + 0.2 * playW, H)], fill=(255, 34, 34, 200), width=2)
                img.alpha_composite(rz_overlay)

            # 7 · Center text overlay (period + context, matching HTML getBgText)
            prd     = self.shorten_status(game.get('status', ''), sport)
            ctx     = dd_text.split(' at ')[0].strip() if ' at ' in dd_text else dd_text
            ctx_clr = (255, 136, 0) if is_rz else (240, 216, 0)
            cx_mid  = W // 2
            if prd or ctx:
                y_prd = int(H * 0.32) if ctx else int(H * 0.5)
                self.draw_outlined_text(d, cx_mid, y_prd, prd, self.big_font, (255, 255, 255), (0, 0, 0, 200))
                if ctx:
                    self.draw_outlined_text(d, cx_mid, int(H * 0.72), ctx, self.font, ctx_clr, (0, 0, 0, 200))

            # 8 · Logos in end zones
            LOGO_SZ  = min(int(ezW * 0.85), int(H * 0.65))
            logo_top = max(0, int(H * 0.30) - LOGO_SZ // 2)
            h_logo_cx = int(ezW / 2)
            a_logo_cx = W - int(ezW / 2)
            hl = self.get_logo(game.get('home_logo'), (24, 24))
            al = self.get_logo(game.get('away_logo'), (24, 24))
            if hl:
                ls = hl.resize((LOGO_SZ, LOGO_SZ), Image.LANCZOS)
                img.paste(ls, (h_logo_cx - LOGO_SZ // 2, logo_top), ls)
            if al:
                ls = al.resize((LOGO_SZ, LOGO_SZ), Image.LANCZOS)
                img.paste(ls, (a_logo_cx - LOGO_SZ // 2, logo_top), ls)

            # 9 · Score badges
            score_y   = int(H * 0.82)
            slot_cx   = int(ezW + playW * 0.05)
            aslot_cx  = int(W - ezW - playW * 0.05)
            # Default: keep scores outside endzones
            h_sc_cx   = slot_cx
            a_sc_cx   = aslot_cx
            if is_rz:
                if poss_ab == home_ab:
                    h_sc_cx = slot_cx
                    a_sc_cx = a_logo_cx
                elif poss_ab == away_ab:
                    h_sc_cx = h_logo_cx
                    a_sc_cx = aslot_cx
            for scx, sc in [(h_sc_cx, h_score), (a_sc_cx, a_score)]:
                if not sc: continue
                sw = (len(str(sc)) * 5) + 6
                sh = 11
                box_left = scx - (sw // 2)
                box_top = score_y - (sh // 2)
                box_right = box_left + sw - 1
                box_bottom = box_top + sh - 1
                d.rectangle([box_left, box_top, box_right, box_bottom], fill=(0, 0, 0, 218))
                text_w = len(str(sc)) * 5
                text_h = 6
                text_x = box_left + ((sw - text_w) // 2)
                text_y = box_top + ((sh - text_h + 1) // 2)
                draw_hybrid_text(d, text_x, text_y, str(sc), (255, 255, 255))

            # 10 · First-down line + LOS line + football
            if 0 <= los <= 100:
                los_px = ezW + los * playW / 100
                fd_pct = min(100, los + ytg) if drive_to_right else max(0, los - ytg)
                fd_px  = ezW + fd_pct * playW / 100
                d.line([(fd_px, 0), (fd_px, H)],   fill=(240, 216, 0, 245), width=2)
                d.line([(los_px, 0), (los_px, H)],  fill=(200, 200, 200, 240), width=2)
                brx = max(4, int(H * 0.13))
                bry = max(2, int(H * 0.08))
                by  = H // 2
                d.ellipse([los_px - brx, by - bry, los_px + brx, by + bry], fill=(139, 69, 19), outline=(61, 26, 6))
                d.line([(los_px - int(brx * 0.7), by), (los_px + int(brx * 0.7), by)], fill=(255, 255, 255, 165))

            # 11 · Possession ▼ indicator
            pcx = None
            if poss_ab == home_ab: pcx = int(ezW / 2)
            elif poss_ab == away_ab: pcx = W - int(ezW / 2)
            if pcx:
                d.polygon([(pcx - 3, H - 4), (pcx + 3, H - 4), (pcx, H - 1)], fill=(255, 255, 255))

            return img

        # ── NON-FOOTBALL: sport background + side scrims ────────────────────
        if is_nhl:
            self._draw_hockey_rink(d, W, H)
        elif is_mlb:
            self._draw_baseball_diamond(d, W, H, sit)
        else:
            self._draw_basketball_court(d, W, H)

        # ── MLB: special full-width layout matching HTML L1 getBgText() ──────
        if is_mlb:
            # Parse inning from status string  e.g. "Top 7th" / "Bottom 3rd" / "Mid 8th"
            status_raw = str(game.get('status', '')).upper()
            is_top_inn = 'TOP' in status_raw
            is_bot_inn = 'BOT' in status_raw or 'BOTTOM' in status_raw
            is_mid_inn = not is_top_inn and not is_bot_inn  # MID / END

            # Extract inning number
            inn_num = ''
            for word in status_raw.split():
                clean = word.replace('TH','').replace('ST','').replace('ND','').replace('RD','')
                if clean.isdigit():
                    inn_num = clean
                    break

            def _ordinal(n):
                n = int(n)
                if 10 <= n % 100 <= 19: return f"{n}th"
                return f"{n}" + {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')

            inn_ordinal = _ordinal(inn_num) if inn_num else ''  # e.g. "9th"

            balls   = sit.get('balls',   0)
            strikes = sit.get('strikes', 0)
            outs    = sit.get('outs',    0)

            # ── Step 1: side scrims via alpha_composite (correct blending) ──
            # Drawing alpha lines directly on RGBA replaces pixels instead of blending.
            # Use a separate overlay and alpha_composite onto the base image.
            scrim = Image.new("RGBA", (W, H), (0, 0, 0, 0))
            sd = ImageDraw.Draw(scrim)
            SOLID, FADE = 45, 80
            for x in range(SOLID + FADE):
                a = 250 if x < SOLID else max(0, int(250 * (SOLID + FADE - x) / FADE))
                sd.line([(x, 0),         (x, H)],         fill=(0, 0, 0, a))
                sd.line([(W - 1 - x, 0), (W - 1 - x, H)], fill=(0, 0, 0, a))
            img.alpha_composite(scrim)
            d.rectangle([0, 0, 2, H],     fill=home_clr)
            d.rectangle([W - 3, 0, W, H], fill=away_clr)

            # ── Step 3: logos ────────────────────────────────────────────────
            LOGO_SZ  = 24
            logo_y   = (H - LOGO_SZ) // 2
            h_logo_x = 6
            a_logo_x = W - 3 - LOGO_SZ - 5
            hl = self.get_logo(game.get('home_logo'), (LOGO_SZ, LOGO_SZ))
            al = self.get_logo(game.get('away_logo'), (LOGO_SZ, LOGO_SZ))
            if hl: img.paste(hl, (h_logo_x, logo_y), hl)
            if al: img.paste(al, (a_logo_x, logo_y), al)

            # ── Step 4: scores ───────────────────────────────────────────────
            h_sc_x = h_logo_x + LOGO_SZ + 4
            a_sc_x = a_logo_x - 4
            self.draw_outlined_text(d, h_sc_x, H // 2, h_score,
                                    self.clock_giant, (255, 255, 255), (0, 0, 0, 200), anchor='lm')
            h_sc_w = d.textlength(h_score, font=self.clock_giant)
            self.draw_outlined_text(d, a_sc_x, H // 2, a_score,
                                    self.clock_giant, (255, 255, 255), (0, 0, 0, 200), anchor='rm')
            a_sc_w = d.textlength(a_score, font=self.clock_giant)

            # ── Step 5: inning text + BSO (drawn AFTER scrim so they're on top) ──
            # HTML: spread=75, leftX=W/2-75=117, rightX=W/2+75=267
            left_txt_x  = W // 2 - 75   # 117
            right_txt_x = W // 2 + 75   # 267

            bso_rows = [
                ('B', str(balls),   (74,  175, 255)),
                ('S', str(strikes), (255, 136,   0)),
                ('O', str(outs),    (224,  48,  48)),
            ]

            if not is_mid_inn:
                inn_cx  = left_txt_x  if is_top_inn else right_txt_x
                bso_cx  = right_txt_x if is_top_inn else left_txt_x
            else:
                inn_cx  = left_txt_x
                bso_cx  = right_txt_x

            def draw_inning_indicator(cx, cy, is_top, is_bot, ordinal_str):
                """Draw inning indicator: [▲/▼ arrow] [bold number] [suffix], all inline and centered."""
                if not ordinal_str:
                    return
                f_num = self.big_font   # 14pt bold
                f_sup = self.micro      # 7pt small suffix

                num_part = ''.join(c for c in ordinal_str if c.isdigit())
                suf_part = ''.join(c for c in ordinal_str if not c.isdigit())

                num_w = d.textlength(num_part, font=f_num)
                suf_w = d.textlength(suf_part, font=f_sup)
                arrow_w = 8
                gap     = 2
                total_w = arrow_w + gap + num_w + suf_w
                x = int(cx - total_w / 2)

                # Arrow — vertically centered at cy with ±5px half-height
                ah    = 4
                mid_x = x + arrow_w // 2
                if is_top:
                    d.polygon([(x-1, cy+ah+1), (x+arrow_w+1, cy+ah+1), (mid_x, cy-ah-1)], fill=(0, 0, 0))
                    d.polygon([(x,   cy+ah),   (x+arrow_w,   cy+ah),   (mid_x, cy-ah)],   fill=(255, 255, 255))
                elif is_bot:
                    d.polygon([(x-1, cy-ah-1), (x+arrow_w+1, cy-ah-1), (mid_x, cy+ah+1)], fill=(0, 0, 0))
                    d.polygon([(x,   cy-ah),   (x+arrow_w,   cy-ah),   (mid_x, cy+ah)],   fill=(255, 255, 255))
                else:
                    d.rectangle([x, cy-1, x+arrow_w, cy+1], fill=(180, 180, 180))
                x += arrow_w + gap

                # Number — anchor='mm' truly centers it on cy
                nx = x + int(num_w / 2)
                for dx in [-1, 0, 1]:
                    for dy in [-1, 0, 1]:
                        if dx == 0 and dy == 0: continue
                        d.text((nx+dx, cy+dy), num_part, font=f_num, fill=(0, 0, 0, 200), anchor='mm')
                d.text((nx, cy), num_part, font=f_num, fill=(255, 255, 255), anchor='mm')
                x += int(num_w)

                # Suffix — inline with inning number (no superscript raise)
                d.text((x, cy), suf_part, font=f_sup, fill=(190, 190, 190), anchor='lm')

            draw_inning_indicator(inn_cx, H // 2, is_top_inn, is_bot_inn, inn_ordinal)
            y_start = 4
            for (lbl, val, col) in bso_rows:
                draw_tiny_text(d, bso_cx - 8, y_start, lbl, (180, 180, 180))
                draw_tiny_text(d, bso_cx,     y_start, val, col)
                y_start += 8

            # ── Step 6: bat icon ─────────────────────────────────────────────
            if is_top_inn:
                self.draw_bat(d, int(a_sc_x - a_sc_w - 8), 7)   # cx between score and logo
            elif is_bot_inn:
                self.draw_bat(d, int(h_sc_x + h_sc_w + 8), 7)

            return img

        # ── NHL / NBA: side scrims (alpha_composite) then text on top ────────

        # Hockey PP / EN badges
        h_badge = a_badge = ''
        if is_nhl and sit.get('powerPlay'):
            if poss_ab == home_ab:   h_badge = 'PP'
            elif poss_ab == away_ab: a_badge = 'PP'
        elif is_nhl and sit.get('emptyNet'):
            en_side = str(sit.get('emptyNetSide', '')).upper()
            if en_side in ('HOME', home_ab):
                h_badge = 'EN'
            elif en_side in ('AWAY', away_ab):
                a_badge = 'EN'
            elif poss_ab == home_ab:
                a_badge = 'EN'
            elif poss_ab == away_ab:
                h_badge = 'EN'

        # Side scrims via alpha_composite (correct blending)
        scrim = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        sd = ImageDraw.Draw(scrim)
        SOLID, FADE = 45, 80
        for x in range(SOLID + FADE):
            a = 250 if x < SOLID else max(0, int(250 * (SOLID + FADE - x) / FADE))
            sd.line([(x, 0), (x, H)],             fill=(0, 0, 0, a))
            sd.line([(W - 1 - x, 0), (W - 1 - x, H)], fill=(0, 0, 0, a))
        img.alpha_composite(scrim)

        # Centre text (period + context) — drawn AFTER scrim so it's visible
        prd = self.shorten_status(game.get('status', ''), sport)
        cx  = W // 2
        if prd:
            self.draw_outlined_text(d, cx, H // 2, prd,
                                    self.big_font, (255, 255, 255), (0, 0, 0, 200))

        # Team-color borders
        d.rectangle([0, 0, 2, H],     fill=home_clr)
        d.rectangle([W - 3, 0, W, H], fill=away_clr)

        # Hockey badges: compact text-only labels (avoid full-height side blocks)
        l_used = 3; r_used = 3

        # Logos
        LOGO_SZ  = 24
        h_logo_x = l_used + 5
        a_logo_x = W - r_used - LOGO_SZ - 5
        logo_y   = (H - LOGO_SZ) // 2
        hl = self.get_logo(game.get('home_logo'), (LOGO_SZ, LOGO_SZ))
        al = self.get_logo(game.get('away_logo'), (LOGO_SZ, LOGO_SZ))
        if hl: img.paste(hl, (h_logo_x, logo_y), hl)
        if al: img.paste(al, (a_logo_x, logo_y), al)

        # Scores
        h_sc_x = h_logo_x + LOGO_SZ + 4
        a_sc_x = a_logo_x - 4
        self.draw_outlined_text(d, h_sc_x, H // 2, h_score,
                                self.clock_giant, (255, 255, 255), (0, 0, 0, 200), anchor='lm')
        h_sc_w = d.textlength(h_score, font=self.clock_giant)
        self.draw_outlined_text(d, a_sc_x, H // 2, a_score,
                                self.clock_giant, (255, 255, 255), (0, 0, 0, 200), anchor='rm')
        a_sc_w = d.textlength(a_score, font=self.clock_giant)

        if h_badge:
            h_col = (255, 204, 0) if h_badge == 'PP' else (255, 90, 90)
            h_badge_x = int(h_sc_x + h_sc_w + 9)
            self.draw_outlined_text(d, h_badge_x, H // 2, h_badge,
                                    self.tiny, h_col, (0, 0, 0, 220), anchor='mm')
        if a_badge:
            a_col = (255, 204, 0) if a_badge == 'PP' else (255, 90, 90)
            a_badge_x = int(a_sc_x - a_sc_w - 9)
            self.draw_outlined_text(d, a_badge_x, H // 2, a_badge,
                                    self.tiny, a_col, (0, 0, 0, 220), anchor='mm')

        # No possession arrow for hockey/basketball full-bleed mode.

        return img

    # ── Sport background helpers — exact ports of the HTML JS functions ──────

    def _draw_hockey_rink(self, d, W, H):
        """
        Port of HTML hockeyRink() — ice blue surface, blue lines, red lines,
        face-off circles, goal creases, and nets.
        HTML uses rounded clipPath corners; we approximate with a rounded rectangle
        drawn on top at the end.
        """
        bl1 = W * 0.28
        bl2 = W * 0.72
        gl1 = W * 0.085
        gl2 = W * 0.915

        # Ice surface + lighter zone tints
        d.rectangle([0, 0, W, H], fill=(205, 228, 248))
        d.rectangle([0, 0, bl1, H],    fill=(196, 219, 244))
        d.rectangle([bl2, 0, W, H],    fill=(196, 219, 244))

        # Removed horizontal texture lines to avoid stray white-line artifacts
        # on the LED matrix/emulator rendering.

        # Blue lines (2.5px wide each)
        d.rectangle([bl1 - 1, 0, bl1 + 1.5, H], fill=(34, 85, 204))
        d.rectangle([bl2 - 1, 0, bl2 + 1.5, H], fill=(34, 85, 204))

        # Neutral-zone faceoff dots just inside the neutral zone near each blue line
        neutral_dot_r = 2
        neutral_dot_fill = (204, 26, 26, 210)
        neutral_dot_outline = (140, 12, 12, 220)
        neutral_x_off = max(4, int(W * 0.02))
        for fx, fy in [
            (bl1 + neutral_x_off, H * 0.28),
            (bl1 + neutral_x_off, H * 0.72),
            (bl2 - neutral_x_off, H * 0.28),
            (bl2 - neutral_x_off, H * 0.72),
        ]:
            d.ellipse([fx - neutral_dot_r, fy - neutral_dot_r, fx + neutral_dot_r, fy + neutral_dot_r],
                      fill=neutral_dot_fill, outline=neutral_dot_outline)

        # Center red line — dashed (6 segments)
        dash_h = int(H / 6 * 0.7)
        for i in range(6):
            ry = int(i * H / 6)
            d.rectangle([W / 2 - 0.6, ry, W / 2 + 0.6, ry + dash_h], fill=(204, 26, 26))

        # Goal lines
        d.line([(gl1, 0), (gl1, H)], fill=(204, 26, 26), width=1)
        d.line([(gl2, 0), (gl2, H)], fill=(204, 26, 26), width=1)

        # Center circle + dot
        cr = H * 0.40
        d.ellipse([W/2 - cr, H/2 - cr, W/2 + cr, H/2 + cr],
                  outline=(204, 26, 26, 128), width=1)
        d.ellipse([W/2 - 2, H/2 - 2, W/2 + 2, H/2 + 2], fill=(204, 26, 26, 179))

        # Zone face-off dots + circles
        fo_r = H * 0.25
        fo_dot = 2.5
        for fx, fy in [
            (bl1 * 0.5,            H * 0.28),
            (bl1 * 0.5,            H * 0.72),
            (bl2 + (W - bl2) * 0.5, H * 0.28),
            (bl2 + (W - bl2) * 0.5, H * 0.72),
        ]:
            d.ellipse([fx - fo_dot, fy - fo_dot, fx + fo_dot, fy + fo_dot],
                      fill=(204, 26, 26, 179))
            d.ellipse([fx - fo_r, fy - fo_r, fx + fo_r, fy + fo_r],
                      outline=(204, 26, 26, 89), width=1)

        # Goal creases — arcs opening inward from each goal line
        cr2 = H * 0.32
        # Left crease opens rightward (arc from 270° to 90°, i.e. right half of circle)
        d.arc([gl1 - cr2, H/2 - cr2, gl1 + cr2, H/2 + cr2],
              start=270, end=90, fill=(68, 136, 238), width=1)
        # Right crease opens leftward
        d.arc([gl2 - cr2, H/2 - cr2, gl2 + cr2, H/2 + cr2],
              start=90, end=270, fill=(68, 136, 238), width=1)

        # Goalie nets (small rectangles just outside goal lines)
        nh = int(H * 0.28)
        ny = (H - nh) // 2
        d.rectangle([gl1,     ny, gl1 + 4, ny + nh], fill=(221, 221, 221), outline=(153, 153, 153))
        d.rectangle([gl2 - 4, ny, gl2,     ny + nh], fill=(221, 221, 221), outline=(153, 153, 153))

        # Rounded corner overlay (simulate HTML clipPath rx)
        cr_r = H * 0.45
        d.rounded_rectangle([0, 0, W - 1, H - 1], radius=int(cr_r),
                             outline=(122, 173, 206), width=1)

    def _draw_baseball_diamond(self, d, W, H, sit):
        """
        Port of HTML baseballDiamond().
        cx=W/2, cy=H*0.55, r=H*0.42, bs=H*0.16 (half-diagonal of rotated base).
        Base positions:  home=(cx,cy+r)  1B=(cx+r,cy)  2B=(cx,cy-r)  3B=(cx-r,cy)

        Key fix: the HTML dirt is an SVG arc path that bows UPWARD from below the canvas.
        Best PIL approximation is a filled ellipse centered at (cx, cy+r*0.1) with
        rx=r*1.4, ry=r*1.1 — this produces the correct kidney/infield-skin shape.
        """
        cx = W / 2
        cy = H * 0.55
        r  = H * 0.42
        bs = H * 0.16     # half-diagonal — bases are rotated squares drawn as diamonds

        home  = (cx,     cy + r)
        first = (cx + r, cy)
        sec   = (cx,     cy - r)
        third = (cx - r, cy)

        # 1 · Alternating grass bands (full width)
        for i in range(10):
            bx = i * W / 10
            d.rectangle([bx, 0, bx + W / 10, H],
                        fill=(17, 41, 17) if i % 2 == 0 else (21, 50, 21))

        # 2 · Dirt infield — ellipse centered just below diamond midpoint.
        #     The HTML uses an SVG arc path whose bottom goes off-canvas (y=home+3=~34)
        #     and whose curve bows upward; this ellipse replicates that visible shape.
        dc   = cy + r * 0.1     # ellipse centre y  (~19.0 for H=32)
        drx  = r * 1.4          # horizontal radius (~18.8)
        dry  = r * 1.1          # vertical radius   (~14.8)
        d.ellipse([cx - drx, dc - dry, cx + drx, dc + dry], fill=(158, 105, 68))

        # 3 · Inner grass diamond  (HTML: polygon with 2-px inset at each vertex)
        # The top vertex (2nd base) needs a larger inset so the grass doesn't
        # overlap the base: sec_y=4.2, bs=5.1, so base bottom=9.3 — inset by bs+1
        d.polygon([
            (cx,           home[1]  - 2),
            (first[0] - 2, first[1]),
            (cx,           sec[1]   + bs + 1),   # clear the base footprint
            (third[0] + 2, third[1]),
        ], fill=(17, 41, 17), outline=(158, 105, 68))

        # 4 · Pitcher's mound + rubber
        pr = r * 0.22
        d.ellipse([cx - pr, cy - pr, cx + pr, cy + pr], fill=(158, 105, 68))
        d.rectangle([cx - 1.5, cy - 0.5, cx + 1.5, cy + 0.5], fill=(255, 255, 255))

        # 5 · Home-plate dirt circle
        hpr = r * 0.28
        d.ellipse([home[0] - hpr, home[1] - hpr,
                   home[0] + hpr, home[1] + hpr], fill=(158, 105, 68))

        # 6 · Base lines
        for p1, p2 in [(home, first), (first, sec), (sec, third), (third, home)]:
            d.line([p1, p2], fill=(255, 255, 255, 204), width=1)

        # 7 · Bases — rotated squares (diamond polygons)
        # Note: 2nd base (sec) is at y=cy-r = H*0.13 ≈ 4px from top.
        # With bs=H*0.16≈5px the top point goes to y≈-1 (off screen).
        # Clip the top point of 2nd base to y=1 so it stays visible.
        def draw_base(pt, on):
            x, y = pt
            c = (255, 204, 0) if on else (255, 255, 255)
            top_y = max(1, y - bs)   # clamp top so it never goes off-canvas
            d.polygon([
                (x,      top_y),    # top  (clamped)
                (x + bs, y),        # right
                (x,      y + bs),   # bottom
                (x - bs, y),        # left
            ], fill=c, outline=(0, 0, 0))

        draw_base(third, sit.get('onThird',  False))
        draw_base(first, sit.get('onFirst',  False))
        draw_base(sec,   sit.get('onSecond', False))   # draw 2nd last — it's closest to top edge

        # 8 · Home plate — pentagon
        hp_s = r * 0.12
        d.polygon([
            (home[0],         home[1] + hp_s),
            (home[0] + hp_s,  home[1]),
            (home[0] + hp_s,  home[1] - hp_s),
            (home[0] - hp_s,  home[1] - hp_s),
            (home[0] - hp_s,  home[1]),
        ], fill=(255, 255, 255), outline=(0, 0, 0))

    def _draw_basketball_court(self, d, W, H):
        """
        Exact port of HTML basketballCourt().
        lW=W*0.18  lH=H*0.62  lY=(H-lH)/2  thR=H*0.54
        """
        lW  = W * 0.18
        lH  = H * 0.62
        lY  = (H - lH) / 2
        thR = H * 0.54

        # 1 · Floor (hardwood orange)
        d.rectangle([0, 0, W, H], fill=(200, 120, 58))

          # 2 · Court boundary
        d.rectangle([1, 1, W - 2, H - 2], outline=(255, 255, 255, 128))

          # 3 · Half-court line + centre circle
        d.line([(W / 2, 0), (W / 2, H)], fill=(255, 255, 255, 115))
        cr = H * 0.33
        d.ellipse([W/2 - cr, H/2 - cr, W/2 + cr, H/2 + cr], outline=(255, 255, 255, 97))

          # 4 · Paint lanes (left and right)
        d.rectangle([0,      lY, lW,     lY + lH], fill=(160, 80, 32), outline=(255, 255, 255, 140))
        d.rectangle([W - lW, lY, W,      lY + lH], fill=(160, 80, 32), outline=(255, 255, 255, 140))

          # 5 · Free-throw circles
        ftc_r = lH * 0.26
        d.ellipse([lW - ftc_r, H/2 - ftc_r, lW + ftc_r, H/2 + ftc_r],
                  outline=(255, 255, 255, 97))
        d.ellipse([W - lW - ftc_r, H/2 - ftc_r, W - lW + ftc_r, H/2 + ftc_r],
                  outline=(255, 255, 255, 97))

          # 6 · Three-point arcs
        d.arc([0 - thR, lY - 4, thR,     lY + lH + 4], start=270, end=90,
              fill=(255, 255, 255, 97))
        d.arc([W - thR, lY - 4, W + thR, lY + lH + 4], start=90,  end=270,
              fill=(255, 255, 255, 97))

          # 7 · Basket posts (vertical lines at ~45% of lane width from edge)
        px_l = lW * 0.45
        px_r = W - px_l
        d.line([(px_l, H * 0.33), (px_l, H * 0.67)], fill=(220, 220, 220, 165), width=1)
        d.line([(px_r, H * 0.33), (px_r, H * 0.67)], fill=(220, 220, 220, 165), width=1)

    # ================= GENERIC CARD RENDERERS =================
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
        img = Image.new("RGBA", (PANEL_W, PANEL_H), (0, 0, 0, 255))
        d = ImageDraw.Draw(img)
        sit = game.get('situation', {}) or {}
        stats = sit.get('stats', {}) or {}
        forecast = sit.get('forecast', []) or []
        cur_icon = sit.get('icon', 'cloud')
        DEEP_BLUE = (18, 45, 95)

        temp_f = str(game.get('home_abbr', '--')).replace('°', '').strip()
        try:
            tv = int(float(temp_f))
            if tv >= 90:   temp_color = (255, 90, 35)
            elif tv >= 75: temp_color = (255, 185, 40)
            elif tv >= 55: temp_color = (95, 225, 105)
            elif tv >= 35: temp_color = (95, 190, 255)
            else:          temp_color = (190, 230, 255)
        except:
            temp_color = (240, 240, 245)

        d.rectangle((0, 0, PANEL_W - 1, PANEL_H - 1), fill=(0, 0, 0))
        d.line((0, 0, PANEL_W - 1, 0), fill=DEEP_BLUE)

        left_w = 124
        d.rectangle((0, 0, left_w, 31), fill=(0, 0, 0))
        d.line((left_w, 0, left_w, 31), fill=DEEP_BLUE)

        location_name = normalize_special_chars(str(game.get('away_abbr', 'CITY')).upper()).strip()
        if len(location_name) > 15:
            location_name = location_name[:15]
        draw_tiny_text(d, 4, 2, location_name, (125, 170, 230))

        self.draw_weather_pixel_art(d, cur_icon, 3, 11)

        temp_disp = "--" if not temp_f else temp_f
        d.text((24, 10), f"{temp_disp}\u00b0F", font=self.big_font, fill=temp_color)

        cond = normalize_special_chars(str(game.get('status', '')).upper()).strip()
        replacements = {
            'PARTLY CLOUDY': 'PARTLY CLDY',
            'MOSTLY CLOUDY': 'MOSTLY CLDY',
            'SCATTERED SHOWERS': 'SCT SHOWERS',
            'THUNDERSTORMS': 'T-STORMS',
            'THUNDERSTORM': 'T-STORM',
            'LIGHT RAIN': 'LGT RAIN'
        }
        cond = replacements.get(cond, cond)
        if len(cond) > 19:
            cond = cond[:19]
        if cond:
            draw_tiny_text(d, 24, 25, cond, (105, 145, 190))

        aqi_val = str(stats.get('aqi', '--')).strip() or '--'
        uv_val = str(stats.get('uv', '--')).strip() or '--'
        aqi_col = self.get_aqi_color(aqi_val)

        aqi_box = (74, 3, 121, 11)
        uv_box = (74, 13, 121, 21)
        d.rectangle(aqi_box, fill=(2, 6, 14), outline=DEEP_BLUE)
        d.rectangle(uv_box, fill=(2, 6, 14), outline=DEEP_BLUE)

        aqi_label = "AQI"; aqi_value = aqi_val[:4]
        uv_label = "UV";   uv_value  = uv_val[:4]
        tiny_h = 5

        aqi_mid = (aqi_box[0] + aqi_box[2]) // 2
        aqi_label_w = len(aqi_label) * 5; aqi_value_w = len(aqi_value) * 5
        aqi_label_x = aqi_box[0] + ((aqi_mid - aqi_box[0]) - aqi_label_w) // 2
        aqi_value_x = aqi_mid + ((aqi_box[2] - aqi_mid + 1) - aqi_value_w) // 2
        aqi_y = aqi_box[1] + ((aqi_box[3] - aqi_box[1] + 1) - tiny_h) // 2
        draw_tiny_text(d, aqi_label_x, aqi_y, aqi_label, (95, 120, 160))
        draw_tiny_text(d, aqi_value_x, aqi_y, aqi_value, aqi_col)

        uv_mid = (uv_box[0] + uv_box[2]) // 2
        uv_label_w = len(uv_label) * 5; uv_value_w = len(uv_value) * 5
        uv_label_x = uv_box[0] + ((uv_mid - uv_box[0]) - uv_label_w) // 2
        uv_value_x = uv_mid + ((uv_box[2] - uv_mid + 1) - uv_value_w) // 2
        uv_y = uv_box[1] + ((uv_box[3] - uv_box[1] + 1) - tiny_h) // 2
        draw_tiny_text(d, uv_label_x, uv_y, uv_label, (95, 120, 160))
        draw_tiny_text(d, uv_value_x, uv_y, uv_value, (210, 155, 255))

        if not forecast:
            forecast = [
                {'day': 'MON', 'icon': 'sun',   'high': 80, 'low': 70},
                {'day': 'TUE', 'icon': 'rain',  'high': 75, 'low': 65},
                {'day': 'WED', 'icon': 'cloud', 'high': 78, 'low': 68},
                {'day': 'THU', 'icon': 'storm', 'high': 72, 'low': 60},
                {'day': 'FRI', 'icon': 'sun',   'high': 82, 'low': 72},
            ]

        right_start = left_w + 1
        right_w = PANEL_W - right_start
        col_w = right_w // 5

        for i, day in enumerate(forecast[:5]):
            cx = right_start + (i * col_w)
            col_right = cx + col_w - 1
            if i == 4: col_right = PANEL_W - 1

            bg = (0, 0, 0) if i % 2 == 0 else (1, 3, 8)
            d.rectangle((cx, 0, col_right, 31), fill=bg)
            if i < 4: d.line((col_right, 3, col_right, 29), fill=DEEP_BLUE)

            day_str = normalize_special_chars(str(day.get('day', '???'))[:3].upper())
            day_w = len(day_str) * 5
            day_x = cx + max(0, ((col_right - cx + 1) - day_w) // 2)
            draw_tiny_text(d, day_x, 2, day_str, (110, 160, 220))
            d.line((cx + 4, 8, col_right - 4, 8), fill=DEEP_BLUE)

            icon_x = cx + max(0, ((col_right - cx + 1) - 16) // 2)
            self.draw_weather_pixel_art(d, day.get('icon', 'cloud'), icon_x, 9)

            hi = str(day.get('high', '--')).replace('°', '')
            lo = str(day.get('low', '--')).replace('°', '')
            hi_w = len(hi) * 5; lo_w = len(lo) * 5
            total_w = hi_w + 5 + lo_w
            tx = cx + max(0, ((col_right - cx + 1) - total_w) // 2)
            temp_y = 26
            draw_tiny_text(d, tx,           temp_y, hi,  (255, 115, 75))
            draw_tiny_text(d, tx + hi_w,    temp_y, "/", (70, 88, 120))
            draw_tiny_text(d, tx + hi_w + 5, temp_y, lo, (90, 165, 255))

        return img

    def draw_clock_modern(self):
        img = Image.new("RGBA", (PANEL_W, 32), (0, 0, 0, 255))
        d = ImageDraw.Draw(img)
        now = datetime.now()
        date_str = now.strftime("%A %B %d").upper()
        w_date = d.textlength(date_str, font=self.tiny)
        d.text(((PANEL_W - w_date)/2, -1), date_str, font=self.tiny, fill=(200, 200, 200))
        time_str = now.strftime("%I:%M:%S").lstrip('0')
        w_time = d.textlength(time_str, font=self.clock_giant)
        d.text(((PANEL_W - w_time)/2, 4), time_str, font=self.clock_giant, fill=(255, 255, 255))
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
        d.text((PANEL_W - d.textlength(rem_str, font=self.tiny) - 5, 10), rem_str, font=self.tiny, fill="white")
        return img

    def draw_flight_visitor(self, game):
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

    def draw_single_game(self, game):
        game_hash = self.get_game_hash(game)
        
        if game.get('sport') == 'clock':
            return self.draw_clock_modern()

        if game.get('type') == 'music' or game.get('sport') == 'music':
            return self.draw_music_card(game)

        if game.get('type') != 'weather':
            if game_hash in self.game_render_cache:
                return self.game_render_cache[game_hash]

        if game.get('type') == 'weather':
            img = self.draw_weather_detailed(game)
            self.game_render_cache[game_hash] = img
            return img

        if self.mode == 'sports_full' and game.get('type') not in ['leaderboard', 'stock_ticker'] and 'flight' not in str(game.get('type','')):
            img = self.draw_sport_full_bleed(game)
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

        # --- DEFAULT SCROLLING SPORTS SCOREBOARD ---
        img = Image.new("RGBA", (64, 32), (0, 0, 0, 0))
        if not isinstance(game, dict):
            return img
        try:
            d = ImageDraw.Draw(img)
            sport = str(game.get('sport', '')).lower()
            is_football = 'football' in sport or 'nfl' in sport or 'ncf' in sport
            is_hockey = 'hockey' in sport or 'nhl' in sport
            is_baseball = 'baseball' in sport or 'mlb' in sport or 'wbc' in sport
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
            w_sc = d.textlength(score, font=self.score_default_font)
            d.text(((64-w_sc)/2, score_y), score, font=self.score_default_font, fill=(255,255,255))

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
                        w = d.textlength("EN", font=self.tiny)
                        d.text(((64-w)/2, -1), "EN", font=self.tiny, fill=(255,255,0))
                    elif sit.get('powerPlay'):
                        w = d.textlength("PP", font=self.tiny)
                        d.text(((64-w)/2, -1), "PP", font=self.tiny, fill=(255,255,0))
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
                        o_x = (64 - 10) // 2
                        self.draw_baseball_hud(d, o_x, 23, o_count)
                        is_bot = 'BOT' in raw_st or 'BOTTOM' in raw_st
                        sb_x = 44 if is_bot else 5
                        draw_tiny_text(d, sb_x,      26, str(b_count), (  0, 200,   0))
                        draw_tiny_text(d, sb_x +  5, 26, '-',          (100, 100, 100))
                        draw_tiny_text(d, sb_x + 10, 26, str(s_count), (255, 100,   0))
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
        s = (
            f"{self.mode}_"
            f"{game.get('id')}_{game.get('home_score')}_{game.get('away_score')}_"
            f"{game.get('situation', {}).get('change')}_{game.get('status')}"
        )
        return hashlib.md5(s.encode()).hexdigest()

    def get_item_width(self, game):
        t = game.get('type')
        s = game.get('sport', '')
        if self.mode == 'sports_full' and t not in ['music', 'weather', 'leaderboard', 'stock_ticker'] and 'flight' not in str(t):
            return PANEL_W
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
                if self.is_pairing:
                    frame = self.draw_pairing_screen()
                    self.update_display(frame)
                    time.sleep(0.1)
                    continue

                if self.brightness <= 0.001:
                    self.matrix.Fill(0, 0, 0)
                    time.sleep(0.5)
                    continue

                spotify_data = next((g for g in self.static_items if g.get('id') == 'spotify_now'), None)
                music_is_playing = False
                if spotify_data:
                    music_is_playing = spotify_data.get('situation', {}).get('is_playing', False)
                if self.mode != 'music':
                    music_is_playing = False

                if self.showing_static:
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

                content = data.get('content', {})
                new_games = content.get('sports', [])

                current_payload = {'games': new_games, 'config': local_conf, 'status': server_status}
                current_hash = hashlib.md5(json.dumps(current_payload, sort_keys=True).encode()).hexdigest()
                self.current_data_hash = current_hash

                if current_hash != last_hash:
                    static_items = []
                    scrolling_items = []
                    logos_to_fetch = []

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
                        elif self.mode == 'sports_full' and g_type not in ['leaderboard', 'stock_ticker'] and 'flight' not in str(g_type):
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
