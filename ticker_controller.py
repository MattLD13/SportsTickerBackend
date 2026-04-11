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
try:
    from rgbmatrix import RGBMatrix, RGBMatrixOptions
except ImportError:
    RGBMatrix = RGBMatrixOptions = None   # test / non-Pi environment
from flask import Flask, request, render_template_string

# ================= CONFIGURATION =================
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


def load_display_font(size, bold=False):
    # Prefer non-monospace display fonts to avoid dotted-zero glyphs in large number rendering.
    font_candidates = ["DejaVuSans-Bold.ttf", "DejaVuSans.ttf"] if bold else ["DejaVuSans.ttf"]
    for font_name in font_candidates:
        try:
            return ImageFont.truetype(font_name, size)
        except:
            continue
    return load_monospace_font(size, bold=bold)


class NullMatrix:
    """No-op RGB matrix fallback so the app can run off-device (e.g., Windows dev)."""

    def __init__(self, width=PANEL_W, height=PANEL_H):
        self.width = width
        self.height = height
        self.brightness = 100
        self._last_image = None

    def SetImage(self, img):
        self._last_image = img

    def Fill(self, r, g, b):
        self._last_image = Image.new("RGB", (self.width, self.height), (int(r), int(g), int(b)))

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

        if RGBMatrix is not None and RGBMatrixOptions is not None:
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
        else:
            print("  rgbmatrix not available; using NullMatrix fallback.")
            self.matrix = NullMatrix()

        self.logo_cache = {}
        self.stadium = StadiumRenderer(logo_cache=self.logo_cache)

        self.font = load_monospace_font(10, bold=True)
        self.medium_font = load_monospace_font(12, bold=True)
        self.big_font = load_monospace_font(14, bold=True)
        self.huge_font = load_display_font(20, bold=True)
        self.clock_giant = load_display_font(28, bold=True)
        self.tiny = load_monospace_font(9)
        self.tiny_small = load_monospace_font(8)
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
        tuple_key = f"{url}_{size}"
        dim_key = f"{url}_{size[0]}x{size[1]}"
        if tuple_key in self.logo_cache or dim_key in self.logo_cache:
            return
        try:
            filename = f"{hashlib.md5(url.encode()).hexdigest()}_{size[0]}x{size[1]}.png"
            local = os.path.join(ASSETS_DIR, filename)
            if os.path.exists(local):
                cached = Image.open(local).convert("RGBA")
                cached = _enhance_logo_visibility(cached)
                self.logo_cache[tuple_key] = cached
                self.logo_cache[dim_key] = cached
                return
            r = requests.get(url, timeout=5)
            if r.status_code == 200:
                img = Image.open(io.BytesIO(r.content)).convert("RGBA")
                img = img.convert("RGBa")
                img.thumbnail(size, Image.Resampling.LANCZOS)
                img = img.convert("RGBA")
                final = Image.new("RGBA", size, (0,0,0,0))
                final.paste(img, ((size[0]-img.width)//2, (size[1]-img.height)//2))
                final = _enhance_logo_visibility(final)
                final.save(local, "PNG")
                self.logo_cache[tuple_key] = final
                self.logo_cache[dim_key] = final
        except:
            pass

    def get_logo(self, url, size=(24,24)):
        if not url:
            return None
        return self.logo_cache.get(f"{url}_{size}") or self.logo_cache.get(f"{url}_{size[0]}x{size[1]}")

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

    def _parse_hex_color(self, value):
        try:
            c = str(value or '').strip().lstrip('#')
            if len(c) == 6:
                return tuple(int(c[i:i+2], 16) for i in (0, 2, 4))
        except Exception:
            pass
        return None

    def _is_near_black(self, color, lum_threshold=24, max_threshold=42, chroma_threshold=16):
        if not color or len(color) < 3:
            return True
        r, g, b = int(color[0]), int(color[1]), int(color[2])
        lum = 0.2126 * r + 0.7152 * g + 0.0722 * b
        mx = max(r, g, b)
        mn = min(r, g, b)
        chroma = mx - mn
        # Treat only truly dark/near-neutral tones as near-black.
        return (mx <= max_threshold and lum <= lum_threshold) or (
            mx <= (max_threshold + 6)
            and lum <= (lum_threshold + 4)
            and chroma <= chroma_threshold
        )

    def _is_near_white(self, color, lum_threshold=236, min_channel_threshold=226):
        if not color or len(color) < 3:
            return False
        r, g, b = int(color[0]), int(color[1]), int(color[2])
        lum = 0.2126 * r + 0.7152 * g + 0.0722 * b
        return lum >= lum_threshold or min(r, g, b) >= min_channel_threshold

    def _logo_nonblack_dominant_colors(self, logo, limit=2):
        if not logo:
            return []
        try:
            rgba = logo.convert('RGBA').resize((24, 24), Image.NEAREST)
            colors = rgba.getcolors(24 * 24) or []
            ranked = sorted(colors, key=lambda x: x[0], reverse=True)
            picks = []
            for _, col in ranked:
                if len(col) == 4:
                    r, g, b, a = col
                    if a < 90:
                        continue
                else:
                    r, g, b = col[:3]
                rgb = (int(r), int(g), int(b))
                if self._is_near_black(rgb):
                    continue
                if any(sum(abs(rgb[i] - p[i]) for i in range(3)) < 45 for p in picks):
                    continue
                picks.append(rgb)
                if len(picks) >= limit:
                    break
            return picks
        except Exception:
            return []

    def _resolve_challenge_strip_color(self, game, side, fallback):
        primary = self._parse_hex_color(game.get(f'{side}_color'))
        if primary and not self._is_near_black(primary):
            return primary

        alt = self._parse_hex_color(game.get(f'{side}_alt_color'))
        if alt and not self._is_near_black(alt) and not self._is_near_white(alt):
            return alt

        logo = self.get_logo(game.get(f'{side}_logo'), (24, 24))
        dom = self._logo_nonblack_dominant_colors(logo, limit=2)
        if dom:
            return dom[0]

        if alt and not self._is_near_black(alt):
            return alt
        if alt:
            return alt
        if primary:
            return primary
        return fallback

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

    def _draw_soccer_so_col(self, draw, x, y, results):
        n_show = 5
        for i in range(n_show):
            res = results[i] if i < len(results) else 'pending'
            dy = y + i * 5
            if res == 'goal':
                draw.rectangle((x, dy, x+2, dy+2), fill=(50, 200, 70))
            elif res == 'miss':
                draw.rectangle((x, dy, x+2, dy+2), fill=(220, 55, 55))
            else:
                draw.rectangle((x, dy, x+2, dy+2), fill=(80, 80, 80))

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
        is_soc   = 'soccer' in sport
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
            elif ' and ' in dd_text.lower() and los >= 0:
                # ESPN downDistanceText uses "and" (e.g. "3rd and 7 at KC 48")
                before_at = dd_text.split(' at ')[0] if ' at ' in dd_text else dd_text
                parts = before_at.lower().split(' and ')
                if len(parts) >= 2:
                    ytg_raw = parts[1].strip().split()[0].rstrip('.,')
                    if ytg_raw in ('goal', 'gl', 'goal:'):
                        is_goal_to_go = True
                    else:
                        try: ytg = int(ytg_raw)
                        except ValueError: pass

            # Fallback: use numeric yardLine/yardsToGo fields if text parsing gave no LOS
            if los < 0 and sit.get('yardLine') is not None:
                raw_yl = int(sit.get('yardLine', 50))
                pos_team = str(sit.get('possessionTeam', sit.get('yardLineTeam', ''))).upper()
                if pos_team == home_ab:
                    los = raw_yl
                elif pos_team == away_ab:
                    los = 100 - raw_yl
                else:
                    los = raw_yl if raw_yl <= 50 else 100 - raw_yl
                if sit.get('yardsToGo') is not None:
                    ytg = max(1, int(sit.get('yardsToGo', 10)))

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
            logo_top_center = (H - LOGO_SZ) // 2   # vertically centred
            h_logo_cx = int(ezW / 2)
            a_logo_cx = W - int(ezW / 2)

            # 9 · Score badges — determine positions first so logos can dodge them
            score_y   = int(H * 0.82)
            slot_cx   = int(ezW + playW * 0.05)
            aslot_cx  = int(W - ezW - playW * 0.05)
            h_sc_cx   = slot_cx
            a_sc_cx   = aslot_cx
            if is_rz:
                if poss_ab == home_ab:
                    a_sc_cx = a_logo_cx   # away score moves into away endzone
                elif poss_ab == away_ab:
                    h_sc_cx = h_logo_cx   # home score moves into home endzone

            # Push logo up when its score badge sits below it in the endzone
            score_box_top = score_y - (11 // 2)          # top edge of score badge
            logo_top_up   = max(0, score_box_top - LOGO_SZ - 1)  # just above the badge
            h_logo_top = logo_top_up if h_sc_cx == h_logo_cx else logo_top_center
            a_logo_top = logo_top_up if a_sc_cx == a_logo_cx else logo_top_center

            def _black_ring_logo(logo):
                """Convert the artificial white enhancement ring to black (copy only)."""
                ls = logo.resize((LOGO_SZ, LOGO_SZ), Image.LANCZOS)
                px = ls.load()
                for yy in range(ls.height):
                    for xx in range(ls.width):
                        r, g, b, a = px[xx, yy]
                        # Target the white ring added by _enhance_logo_visibility:
                        # alpha ~230, RGB all very white (>220). Fully-opaque white
                        # pixels inside the logo (a==255) are intentional — skip those.
                        if 180 < a < 252 and r > 220 and g > 220 and b > 220:
                            px[xx, yy] = (0, 0, 0, a)
                return ls

            hl = self.get_logo(game.get('home_logo'), (24, 24))
            al = self.get_logo(game.get('away_logo'), (24, 24))
            if hl:
                ls = _black_ring_logo(hl)
                img.paste(ls, (h_logo_cx - LOGO_SZ // 2, h_logo_top), ls)
            if al:
                ls = _black_ring_logo(al)
                img.paste(ls, (a_logo_cx - LOGO_SZ // 2, a_logo_top), ls)

            for scx, sc in [(h_sc_cx, h_score), (a_sc_cx, a_score)]:
                if not sc: continue
                sw = (len(str(sc)) * 5) + 6
                sh = 11
                box_left = scx - (sw // 2)
                box_top = score_y - (sh // 2)
                text_w = len(str(sc)) * 5
                text_h = 6
                text_x = box_left + ((sw - text_w) // 2)
                text_y = box_top + ((sh - text_h + 1) // 2)
                # Conforming black outline: draw text shifted in 4 directions, then white on top
                for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                    draw_hybrid_text(d, text_x + dx, text_y + dy, str(sc), (0, 0, 0))
                draw_hybrid_text(d, text_x, text_y, str(sc), (255, 255, 255))

            # 10 · First-down line + LOS line + football
            if 0 <= los <= 100:
                los_px = ezW + los * playW / 100
                fd_pct = min(100, los + ytg) if drive_to_right else max(0, los - ytg)
                fd_px  = ezW + fd_pct * playW / 100
                d.line([(fd_px, 0), (fd_px, H)],   fill=(240, 216, 0, 245), width=2)
                d.line([(los_px, 0), (los_px, H)],  fill=(30, 60, 180, 240), width=2)
                brx = max(4, int(H * 0.13))
                bry = max(2, int(H * 0.08))
                by  = H // 2
                d.ellipse([los_px - brx, by - bry, los_px + brx, by + bry], fill=(139, 69, 19), outline=(61, 26, 6))
                d.line([(los_px - int(brx * 0.7), by), (los_px + int(brx * 0.7), by)], fill=(255, 255, 255, 165))

            return img

        # ── SOCCER: full-width pitch layout ─────────────────────────────────
        if is_soc:
            home_pitch = self.get_team_color(game, 'home')
            away_pitch = self.get_team_color(game, 'away')

            # Pitch background with subtle stripes and center circle.
            d.rectangle([0, 0, W, H], fill=(18, 96, 36))
            for i in range(8):
                x0 = int(i * W / 8)
                x1 = int((i + 1) * W / 8)
                shade = (22, 104, 40) if i % 2 == 0 else (18, 96, 36)
                d.rectangle([x0, 0, x1, H], fill=shade)
            d.rectangle([1, 1, W - 2, H - 2], outline=(245, 245, 245, 210), width=1)
            d.line([(W // 2, 0), (W // 2, H)], fill=(245, 245, 245, 180), width=1)
            d.ellipse([W // 2 - 13, H // 2 - 13, W // 2 + 13, H // 2 + 13], outline=(245, 245, 245, 180), width=1)
            d.rectangle([1, 8, 10, H - 8], fill=(245, 245, 245, 28))
            d.rectangle([W - 11, 8, W - 2, H - 8], fill=(245, 245, 245, 28))

            # Fade the edges like the basketball/hockey cards so text and logos stay readable.
            scrim = Image.new("RGBA", (W, H), (0, 0, 0, 0))
            sd = ImageDraw.Draw(scrim)
            SOLID, FADE = 45, 80
            for x in range(SOLID + FADE):
                a = 250 if x < SOLID else max(0, int(250 * (SOLID + FADE - x) / FADE))
                sd.line([(x, 0), (x, H)], fill=(0, 0, 0, a))
                sd.line([(W - 1 - x, 0), (W - 1 - x, H)], fill=(0, 0, 0, a))
            img.alpha_composite(scrim)

            # Team-colored side bars and score placements.
            d.rectangle([0, 0, 3, H], fill=home_pitch)
            d.rectangle([W - 4, 0, W, H], fill=away_pitch)

            LOGO_SZ = 24
            logo_y = (H - LOGO_SZ) // 2
            h_logo_x = 6
            a_logo_x = W - 3 - LOGO_SZ - 5
            hl = self.get_logo(game.get('home_logo'), (LOGO_SZ, LOGO_SZ))
            al = self.get_logo(game.get('away_logo'), (LOGO_SZ, LOGO_SZ))
            if hl: img.paste(hl, (h_logo_x, logo_y), hl)
            if al: img.paste(al, (a_logo_x, logo_y), al)

            h_sc_x = h_logo_x + LOGO_SZ + 4
            a_sc_x = a_logo_x - 4
            self.draw_outlined_text(d, h_sc_x, H // 2, h_score,
                                    self.clock_giant, (255, 255, 255), (0, 0, 0, 200), anchor='lm')
            self.draw_outlined_text(d, a_sc_x, H // 2, a_score,
                                    self.clock_giant, (255, 255, 255), (0, 0, 0, 200), anchor='rm')

            status_text = str(game.get('status', '')).strip()
            if status_text:
                self.draw_outlined_text(d, W // 2, 7, status_text[:16], self.tiny, (255, 240, 150), (0, 0, 0, 220), anchor='ma')

            if sit.get('shootout'):
                so_a = sit.get('shootout', {}).get('away', [])
                so_h = sit.get('shootout', {}).get('home', [])
                self._draw_soccer_so_col(d, a_logo_x + LOGO_SZ + 2, 8, so_a)
                self._draw_soccer_so_col(d, h_logo_x - 5, 8, so_h)

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
            # ── Step 2: challenge indicator bars ────────────────────────────────
            # Full-mode MLB spec:
            # - 4px-wide full-height connected team-color strip
            # - each lost challenge draws a 2x14 box inside that strip
            _h_rem  = game.get('home_challenges')
            _h_used = game.get('home_challenges_used')
            _a_rem  = game.get('away_challenges')
            _a_used = game.get('away_challenges_used')

            home_ch_clr = self._resolve_challenge_strip_color(game, 'home', home_clr)
            away_ch_clr = self._resolve_challenge_strip_color(game, 'away', away_clr)

            def _draw_challenge_bar(bx0, bx1, rem, used, team_clr):
                # Base: always draw a full-height connected strip.
                d.rectangle([bx0, 0, bx1, H - 1], fill=team_clr)

                def _to_int(v):
                    try:
                        return int(v)
                    except Exception:
                        return None

                rem_i = _to_int(rem)
                used_i = _to_int(used)
                if used_i is None and rem_i is not None:
                    used_i = max(0, 2 - max(0, rem_i))
                if used_i is None:
                    return

                lost_count = min(2, max(0, used_i))
                if lost_count <= 0:
                    return

                # Lost markers are fixed top/bottom slots (never centered).
                box_w = 2
                box_h = 14
                box_x0 = bx0 + ((bx1 - bx0 + 1) - box_w) // 2
                box_x1 = box_x0 + box_w - 1
                top_y0 = 1
                top_y1 = top_y0 + box_h - 1
                bot_y1 = H - 2
                bot_y0 = bot_y1 - box_h + 1

                # "Open" box = carved out from the strip so it's clearly not centered/filled.
                if lost_count >= 1:
                    d.rectangle([box_x0, top_y0, box_x1, top_y1], fill=(0, 0, 0, 0))
                if lost_count >= 2:
                    d.rectangle([box_x0, bot_y0, box_x1, bot_y1], fill=(0, 0, 0, 0))

            _draw_challenge_bar(0,     3,   _h_rem, _h_used, home_ch_clr)
            _draw_challenge_bar(W - 4, W - 1, _a_rem, _a_used, away_ch_clr)

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
            # Pull these closer to the center diamond so side lanes can hold
            # batter/pitcher detail blocks.
            center_spread = 40
            left_txt_x  = W // 2 - center_spread
            right_txt_x = W // 2 + center_spread

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

            # ── Step 7: batter / pitcher detail blocks in side lanes ────────
            def _short_last_name(raw, max_chars=10):
                txt = str(raw or '').strip()
                if not txt:
                    return ''
                parts = [p for p in txt.replace('.', ' ').split() if p]
                _SUFFIXES = {'JR', 'SR', 'II', 'III', 'IV', 'V', 'VI'}
                if len(parts) >= 2 and parts[-1].upper() in _SUFFIXES:
                    last = f"{parts[-2]} {parts[-1]}"
                else:
                    last = parts[-1] if parts else txt
                return last.upper()[:max_chars]

            def _trim_line(raw, max_chars=15):
                return str(raw or '').strip()[:max_chars]

            def _compact_pitch_name(full_type, abbr_type):
                txt = str(full_type or '').strip()
                if txt:
                    txt = txt.split('(', 1)[0].strip()
                    txt = txt.split('/', 1)[0].strip()
                if not txt:
                    return str(abbr_type or '').strip().upper()[:10]
                if len(txt) > 12:
                    words = txt.replace('-', ' ').split()
                    if words:
                        txt = words[-1]
                return txt.title()[:12]

            def _draw_info_block(cx, lines, y0=None):
                non_empty = sum(1 for l in lines if str(l or '').strip())
                if non_empty >= 4:
                    start = 4 if y0 is None else y0
                    spacing = 8
                else:
                    start = 7 if y0 is None else y0
                    spacing = 9
                y = start
                for line in lines:
                    line_txt = _trim_line(line)
                    if line_txt:
                        self.draw_outlined_text(
                            d,
                            int(cx),
                            y,
                            line_txt,
                            self.tiny_small,
                            (255, 255, 255),
                            (0, 0, 0, 220),
                            anchor='mm'
                        )
                    y += spacing

            batter_name  = _short_last_name(sit.get('batter_name', ''))
            pitcher_name = _short_last_name(sit.get('pitcher_name', ''))
            batter_avg   = sit.get('batter_avg', '')
            batter_h     = sit.get('batter_h', '')
            batter_ab    = sit.get('batter_ab', '')
            pit_pitches  = sit.get('pitcher_pitches', 0)
            last_spd     = sit.get('last_pitch_speed', 0)
            last_abbr    = sit.get('last_pitch_type_abbr', '') or sit.get('last_pitch_type', '')
            last_full    = sit.get('last_pitch_type_full', '')

            batter_avg_txt = str(batter_avg or '').strip()
            if batter_avg_txt.startswith('0.'):
                batter_avg_txt = batter_avg_txt[1:]

            batter_h_txt = str(batter_h or '').strip()
            batter_ab_txt = str(batter_ab or '').strip()
            if batter_h_txt and batter_ab_txt:
                batter_hits_ab_line = f"{batter_h_txt}/{batter_ab_txt}"
            elif batter_h_txt:
                batter_hits_ab_line = f"{batter_h_txt}/-"
            elif batter_ab_txt:
                batter_hits_ab_line = f"-/{batter_ab_txt}"
            else:
                batter_hits_ab_line = ''

            if batter_avg_txt:
                batter_avg_line = batter_avg_txt
            else:
                batter_avg_line = ''

            pitch_count_line = ''
            if str(pit_pitches).strip() and str(pit_pitches).strip() != '0':
                pitch_count_line = f"P:{pit_pitches}"

            pitch_type_line = _compact_pitch_name(last_full, last_abbr)
            if str(last_spd).strip() and str(last_spd).strip() != '0' and pitch_type_line:
                pitch_info_line = f"{last_spd} {pitch_type_line}"
            elif str(last_spd).strip() and str(last_spd).strip() != '0':
                pitch_info_line = f"{last_spd} MPH"
            else:
                pitch_info_line = pitch_type_line

            # Prefer backend possession marker; fall back to inning state.
            home_batting = bool(home_ab and poss_ab and poss_ab == home_ab)
            away_batting = bool(away_ab and poss_ab and poss_ab == away_ab)
            if not home_batting and not away_batting:
                home_batting = is_bot_inn and not is_mid_inn
                away_batting = is_top_inn and not is_mid_inn
            if home_batting and away_batting:
                home_batting = is_bot_inn and not is_mid_inn
                away_batting = is_top_inn and not is_mid_inn

            info_lane_spread = 92
            info_left_cx  = W // 2 - info_lane_spread
            info_right_cx = W // 2 + info_lane_spread

            bat_lines = [batter_name, batter_hits_ab_line, batter_avg_line]
            pit_lines = [pitcher_name, pitch_count_line, pitch_info_line]

            if home_batting and not away_batting:
                _draw_info_block(info_left_cx, bat_lines)
                _draw_info_block(info_right_cx, pit_lines)
            elif away_batting and not home_batting:
                _draw_info_block(info_left_cx, pit_lines)
                _draw_info_block(info_right_cx, bat_lines)
            else:
                _draw_info_block(info_left_cx, pit_lines)
                _draw_info_block(info_right_cx, bat_lines)

            return img

        # ── NHL / NBA: side scrims (alpha_composite) then text on top ────────

        # Hockey PP / EN badges
        h_badge = a_badge = ''
        if is_nhl and sit.get('emptyNet'):
            # If home has possession (extra skater), home net is empty
            if poss_ab == home_ab:
                h_badge = 'EN'
            elif poss_ab == away_ab:
                a_badge = 'EN'
            else:
                a_badge = 'EN' # Fallback
        elif is_nhl and sit.get('powerPlay'):
            if poss_ab == home_ab:   h_badge = 'PP'
            elif poss_ab == away_ab: a_badge = 'PP'

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
        import time
        import threading
        import urllib.request
        import json
        import random
        
        # 1. Initialize Masters state and assets on first run
        if not hasattr(self, 'masters_data'):
            self.masters_data = None
            self.masters_last_fetch = 0
            self.masters_current_pair = 0
            self.masters_last_switch = time.time()
            self.masters_fetching = False
            
            self.M_COLORS = {
                'bg': (0, 103, 71, 255),
                'gold': (200, 168, 75, 255),
                'eagle': (250, 204, 21, 255),
                'birdie': (34, 197, 94, 255),
                'bogey': (239, 68, 68, 255),
                'double': (153, 27, 27, 255),
                    'par_border': (245, 220, 130, 255),
                'white': (255, 255, 255, 255),
                    'label_gray': (235, 245, 225, 255),
                'black': (0, 0, 0, 255),
                'stripe_lead': (200, 168, 75, 255),
            }
            
            self.M_FONT = {
                'A': [2, 5, 7, 5, 5], 'B': [6, 5, 7, 5, 6], 'C': [7, 4, 4, 4, 7], 'D': [6, 5, 5, 5, 6],
                'E': [7, 4, 7, 4, 7], 'F': [7, 4, 7, 4, 4], 'G': [7, 4, 5, 5, 7], 'H': [5, 5, 7, 5, 5],
                'I': [7, 2, 2, 2, 7], 'J': [1, 1, 1, 5, 2], 'K': [5, 6, 4, 6, 5], 'L': [4, 4, 4, 4, 7],
                'M': [5, 7, 7, 5, 5], 'N': [5, 7, 5, 5, 5], 'O': [7, 5, 5, 5, 7], 'P': [7, 5, 7, 4, 4],
                'Q': [7, 5, 5, 7, 1], 'R': [7, 5, 6, 5, 5], 'S': [7, 4, 7, 1, 7], 'T': [7, 2, 2, 2, 2],
                'U': [5, 5, 5, 5, 7], 'V': [5, 5, 5, 2, 2], 'W': [5, 5, 7, 7, 5], 'X': [5, 5, 2, 5, 5],
                'Y': [5, 5, 2, 2, 2], 'Z': [7, 1, 2, 4, 7], '0': [7, 5, 5, 5, 7], '1': [2, 6, 2, 2, 7],
                '2': [7, 1, 7, 4, 7], '3': [7, 1, 7, 1, 7], '4': [5, 5, 7, 1, 1], '5': [7, 4, 7, 1, 7],
                '6': [7, 4, 7, 5, 7], '7': [7, 1, 1, 1, 1], '8': [7, 5, 7, 5, 7], '9': [7, 5, 7, 1, 7],
                '-': [0, 0, 7, 0, 0], '+': [0, 2, 7, 2, 0], '.': [0, 0, 0, 0, 2], ' ': [0, 0, 0, 0, 0]
            }

        # 2. Async Data Fetching (Every 60 seconds)
        now = time.time()
        if now - self.masters_last_fetch > 60 and not self.masters_fetching:
            self.masters_fetching = True
            def fetch_task():
                def generate_holes(par_list, today_score, thru):
                    played = 18 if thru == 'F' else int(thru) if str(thru).isdigit() else 0
                    played = min(18, max(0, played))
                    diffs = [0] * played
                    current = 0
                    loops = 0
                    while current < today_score and played > 0 and loops < 1000:
                        idx = random.randint(0, played-1)
                        if diffs[idx] < 3:
                            diffs[idx] += 1
                            current += 1
                        loops += 1
                    loops = 0
                    while current > today_score and played > 0 and loops < 1000:
                        idx = random.randint(0, played-1)
                        if diffs[idx] > (1 - par_list[idx]):
                            diffs[idx] -= 1
                            current -= 1
                        loops += 1
                    holes = []
                    for i in range(18):
                        if i < played: holes.append(par_list[i] + diffs[i])
                        else: holes.append(None)
                    return holes

                def get_mock_data():
                    pars = [4,5,4,3,4,3,4,5,4, 4,3,4,5,4,5,3,4,4]
                    players = [
                        {'pos': '1', 'name': 'SCHEFFLER', 'total': -18, 'today': -5, 'thru': 'F', 'holes': [3,5,3,3,5,2,4,3,3, 4,3,3,4,4,5,3,4,3]},
                        {'pos': 'T2', 'name': 'LOWRY', 'total': -14, 'today': -4, 'thru': 'F', 'holes': [4,4,4,3,4,3,4,4,4, 4,3,4,4,3,5,4,4,3]},
                        {'pos': 'T2', 'name': 'BURNS', 'total': -14, 'today': -5, 'thru': 16, 'holes': [4,4,4,2,3,3,5,3,4, 3,4,4,3,4,4,3,None,None]},
                        {'pos': '4', 'name': 'MACINTYRE', 'total': -13, 'today': -3, 'thru': 'F', 'holes': [4,5,3,3,4,3,4,4,4, 4,3,4,5,4,5,3,4,3]},
                        {'pos': 'CUT', 'name': 'WOODS', 'total': 5, 'today': 2, 'thru': 'F', 'holes': [5,5,5,4,5,3,5,5,4, 4,4,4,6,4,5,3,4,4]},
                        {'pos': 'CUT', 'name': 'MCILROY', 'total': 3, 'today': 1, 'thru': 'F', 'holes': [4,6,4,3,4,3,5,5,4, 4,3,4,5,4,5,3,4,4]}
                    ]
                    return "THE MASTERS", pars, players

                try:
                    url = "https://site.api.espn.com/apis/site/v2/sports/golf/pga/scoreboard"
                    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
                    with urllib.request.urlopen(req, timeout=5) as response:
                        data = json.loads(response.read().decode())
                        
                    event_name = data['events'][0]['name'].upper()
                    comp = data['events'][0]['competitions'][0]
                    
                    try:
                        course = comp['course']
                        if isinstance(course, list): course = course[0]
                        pars = [h['par'] for h in course['holes']]
                    except:
                        pars = [4,5,4,3,4,3,4,5,4, 4,3,4,5,4,5,3,4,4]

                    players = []
                    for c in comp['competitors']:
                        pos = c.get('status', {}).get('position', {}).get('displayName', '-')
                        
                        if pos in ['WD', 'DQ']:
                            continue
                        
                        display_name = c.get('athlete', {}).get('displayName', 'Unknown')
                        short_name = c.get('athlete', {}).get('shortName', '')
                        if not short_name: 
                            short_name = display_name.split()[-1]
                            
                        short_name = short_name.upper()
                        if len(short_name) > 11:
                            short_name = display_name.split()[-1].upper()
                            
                        name_str = short_name[:11]
                        score_str = c.get('score', 'E')
                        total = 0 if score_str in ['E', 'EVEN'] else int(score_str.replace('+','')) if score_str.replace('+','').replace('-','').isdigit() else 0

                        today = 0
                        for stat in c.get('statistics', []):
                            if stat.get('name') == 'today':
                                tv = stat.get('displayValue', '0')
                                today = 0 if tv in ['E', 'EVEN'] else int(tv.replace('+','')) if tv.replace('+','').replace('-','').isdigit() else 0

                        thru = c.get('status', {}).get('thru', 0)
                        if c.get('status', {}).get('playActivity', {}).get('description') == 'Finished':
                            thru = 'F'

                        if thru == 0 or str(thru) == '0':
                            valid_linescores = [ls for ls in c.get('linescores', []) if 'value' in ls]
                            if valid_linescores:
                                last_round_val = valid_linescores[-1]['value']
                                today = int(last_round_val) - sum(pars)
                                thru = 'F'

                        holes = generate_holes(pars, today, thru)
                        players.append({
                            'pos': pos, 'name': name_str,
                            'total': total, 'today': today, 'thru': thru,
                            'holes': holes
                        })

                    if all(p['pos'] == '-' for p in players):
                        players.sort(key=lambda x: x['total'])
                        current_rank = 1
                        for i in range(len(players)):
                            if i > 0 and players[i]['total'] == players[i-1]['total']:
                                players[i]['pos'] = f"T{current_rank}"
                                if 'T' not in players[i-1]['pos']:
                                    players[i-1]['pos'] = f"T{current_rank}"
                            else:
                                current_rank = i + 1
                                players[i]['pos'] = str(current_rank)
                        
                    for p in players:
                        if p['pos'] not in ['CUT', 'WD', 'DQ', '-']:
                            nums = ''.join(filter(str.isdigit, p['pos']))
                            if nums and int(nums) > 50:
                                p['pos'] = 'CUT'

                    final_players = []
                    cut_count = 0
                    for p in players:
                        if p['pos'] == 'CUT':
                            if cut_count < 8:
                                final_players.append(p)
                                cut_count += 1
                        else:
                            final_players.append(p)
                    players = final_players

                    if sum(abs(p['total']) for p in players) == 0:
                        print("API returned all 0s. Falling back to Concept 7 Mock Data to show styling.")
                        self.masters_data = get_mock_data()
                    else:
                        self.masters_data = (event_name, pars, players)
                except Exception as e:
                    print(f"Failed to load real API ({e}). Loading Concept 7 Default Data.")
                    self.masters_data = get_mock_data()
                finally:
                    self.masters_last_fetch = time.time()
                    self.masters_fetching = False

            threading.Thread(target=fetch_task, daemon=True).start()

        # 3. Setup Canvas
        img = Image.new("RGBA", (PANEL_W, 32), self.M_COLORS['bg'])
        d = ImageDraw.Draw(img)

        if not self.masters_data:
            d.text((140, 10), "LOADING MASTERS...", font=self.font, fill=self.M_COLORS['gold'])
            return img

        event_name, pars, players = self.masters_data
        pairs = [(players[i], players[i+1] if i+1 < len(players) else None) for i in range(0, len(players), 2)]

        # 4. Handle Timings
        if len(pairs) > 0:
            p1, p2 = pairs[self.masters_current_pair % len(pairs)]
            is_cut_pair = (p1['pos'] == 'CUT') or (p2 is not None and p2['pos'] == 'CUT')
            current_interval = 2.0 if is_cut_pair else 4.0
            
            if now - self.masters_last_switch > current_interval:
                self.masters_current_pair = (self.masters_current_pair + 1) % len(pairs)
                self.masters_last_switch = now
                p1, p2 = pairs[self.masters_current_pair % len(pairs)]
        else:
            p1, p2 = None, None

        # 5. Drawing Helpers
        BRAND_W = 30
        POS_X = 34
        NAME_X = 47
        FRONT_X = 95
        FSUB_CX = 194
        BACK_X = 208
        BSUB_CX = 314
        TODAY_CX = 342
        TOTAL_CX = 368

        def draw_text(d_obj, text, x, y, color):
            curr_x = int(x)
            for char in str(text).upper():
                if char in self.M_FONT:
                    pattern = self.M_FONT[char]
                    for r, row_val in enumerate(pattern):
                        for c in range(3):
                            if (row_val >> (2 - c)) & 1:
                                d_obj.point((curr_x + c, int(y) + r), fill=color)
                    curr_x += 4
                else:
                    curr_x += 4
            return curr_x

        def draw_text_centered(d_obj, text, x_center, y, color):
            width = len(str(text)) * 4 - 1
            start_x = x_center - width // 2
            draw_text(d_obj, text, start_x, y, color)

        def format_score(val):
            if val == 0: return "E"
            if val > 0: return f"+{val}"
            return str(val)

        def draw_box(d_obj, x, y, score, par):
            if score is None:
                d_obj.rectangle([x, y, x+6, y+6], outline=self.M_COLORS['par_border'])
                draw_text_centered(d_obj, "-", x+3, y+1, self.M_COLORS['label_gray'])
                return

            diff = score - par
            if diff <= -2:
                d_obj.ellipse([x, y, x+6, y+6], fill=self.M_COLORS['eagle'])
                draw_text_centered(d_obj, str(score), x+3, y+1, self.M_COLORS['black'])
            elif diff == -1:
                d_obj.ellipse([x, y, x+6, y+6], fill=self.M_COLORS['birdie'])
                draw_text_centered(d_obj, str(score), x+3, y+1, self.M_COLORS['black'])
            elif diff == 0:
                d_obj.rectangle([x, y, x+6, y+6], outline=self.M_COLORS['par_border'])
                draw_text_centered(d_obj, str(score), x+3, y+1, self.M_COLORS['white'])
            elif diff == 1:
                d_obj.rectangle([x, y, x+6, y+6], fill=self.M_COLORS['bogey'])
                draw_text_centered(d_obj, str(score), x+3, y+1, self.M_COLORS['white'])
            else:
                d_obj.rectangle([x, y, x+6, y+6], fill=self.M_COLORS['double'])
                draw_text_centered(d_obj, str(score), x+3, y+1, self.M_COLORS['white'])

        def draw_player(d_obj, player, y_pos, pars):
            if player['pos'] == '1':
                d_obj.rectangle([POS_X - 4, y_pos + 1, POS_X - 3, y_pos + 5], fill=self.M_COLORS['stripe_lead'])

            if player['pos'] == 'CUT': p_color = self.M_COLORS['bogey']
            elif player['pos'] == '1': p_color = self.M_COLORS['gold']
            else: p_color = self.M_COLORS['white']
                
            draw_text(d_obj, player['pos'], POS_X, y_pos+1, p_color)
            draw_text(d_obj, player['name'], NAME_X, y_pos+1, self.M_COLORS['white'])

            f_score = 0
            for i in range(9):
                bx = FRONT_X + i*10
                score = player['holes'][i]
                draw_box(d_obj, bx, y_pos, score, pars[i])
                if score is not None: f_score += (score - pars[i])
            draw_text_centered(d_obj, format_score(f_score), FSUB_CX, y_pos+1, self.M_COLORS['white'])

            b_score = 0
            for i in range(9):
                bx = BACK_X + i*11
                score = player['holes'][9+i]
                draw_box(d_obj, bx, y_pos, score, pars[9+i])
                if score is not None: b_score += (score - pars[9+i])
            draw_text_centered(d_obj, format_score(b_score), BSUB_CX, y_pos+1, self.M_COLORS['white'])

            draw_text_centered(d_obj, format_score(player['today']), TODAY_CX, y_pos+1, self.M_COLORS['white'])
            
            tot_color = self.M_COLORS['white']
            if player['total'] < 0: tot_color = self.M_COLORS['birdie']
            elif player['total'] > 0: tot_color = self.M_COLORS['bogey']
                
            draw_text_centered(d_obj, format_score(player['total']), TOTAL_CX, y_pos+1, tot_color)

        # 6. Render Current State
        d.line([(BRAND_W, 0), (BRAND_W, 31)], fill=self.M_COLORS['gold'])
        draw_text_centered(d, "THE", BRAND_W // 2, 4, self.M_COLORS['gold'])
        draw_text_centered(d, "MASTERS", BRAND_W // 2, 12, self.M_COLORS['gold'])
        draw_text_centered(d, "2025", BRAND_W // 2, 20, self.M_COLORS['gold'])

        if pairs and p1:
            for i in range(1, 10):
                draw_text_centered(d, str(i), FRONT_X + (i-1)*10 + 3, 2, self.M_COLORS['label_gray'])
            draw_text_centered(d, "FRONT", FSUB_CX, 2, self.M_COLORS['label_gray'])

            for i in range(10, 19):
                draw_text_centered(d, str(i), BACK_X + (i-10)*11 + 3, 2, self.M_COLORS['label_gray'])
            draw_text_centered(d, "BACK", BSUB_CX, 2, self.M_COLORS['label_gray'])

            draw_text_centered(d, "TODAY", TODAY_CX, 2, self.M_COLORS['label_gray'])
            draw_text_centered(d, "TOTAL", TOTAL_CX, 2, self.M_COLORS['label_gray'])

            draw_player(d, p1, 9, pars)
            if p2:
                d.line([(POS_X, 19), (PANEL_W - 4, 19)], fill=self.M_COLORS['par_border'])
                draw_player(d, p2, 22, pars)

            num_dots = min(len(pairs), 10)
            dot_start_x = PANEL_W - (num_dots * 5) - 2
            for i in range(num_dots):
                color = self.M_COLORS['gold'] if i == (self.masters_current_pair % num_dots) else self.M_COLORS['par_border']
                d.rectangle([dot_start_x + i*5, 32 - 3, dot_start_x + i*5 + 1, 32 - 2], fill=color)

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

        if self.mode in ('sports_full', 'soccer_full') and game.get('type') not in ['leaderboard', 'stock_ticker'] and 'flight' not in str(game.get('type','')):
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
            img, _ = self.stadium.render(game)
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
        if self.mode in ('sports_full', 'soccer_full') and t not in ['music', 'weather', 'leaderboard', 'stock_ticker'] and 'flight' not in str(t):
            return PANEL_W
        if t == 'music' or s == 'music': return PANEL_W
        if t == 'stock_ticker' or (s and str(s).startswith('stock')): return 128
        if t == 'weather': return PANEL_W
        if t == 'flight_visitor': return PANEL_W
        if t == 'flight_airport_hud': return PANEL_W
        try:
            return calc_card_width(game) + GAME_SEPARATOR_W
        except Exception:
            return 64

    # ================= STRIP BUILDER =================
    def build_seamless_strip(self, playlist):
        if not playlist:
            return None
        safe_playlist = playlist[:60]
        cards = []
        for g in safe_playlist:
            card = self.draw_single_game(g)
            if card is not None:
                cards.append(card)

        if not cards:
            return None

        total_w = sum(card.width for card in cards) + len(cards) * GAME_SEPARATOR_W
        strip = Image.new("RGBA", (total_w + PANEL_W, PANEL_H), (0,0,0,255))
        sd = ImageDraw.Draw(strip)

        x = 0
        for i, card in enumerate(cards):
            sd.line([(x, 0), (x, PANEL_H - 1)], fill=GAME_SEPARATOR_COLOR)
            x += GAME_SEPARATOR_W
            strip.paste(card, (x, 0), card)
            x += card.width

        bx = x; i = 0
        while bx < total_w + PANEL_W and len(cards) > 0:
            sd.line([(bx, 0), (bx, PANEL_H - 1)], fill=GAME_SEPARATOR_COLOR)
            bx += GAME_SEPARATOR_W
            card = cards[i % len(cards)]
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
                                logos_to_fetch.append((g.get('home_logo'), (22, 22)))
                                logos_to_fetch.append((g.get('home_logo'), (24, 24)))
                                logos_to_fetch.append((g.get('home_logo'), (16, 16)))
                            if g.get('away_logo'):
                                logos_to_fetch.append((g.get('away_logo'), (22, 22)))
                                logos_to_fetch.append((g.get('away_logo'), (24, 24)))
                                logos_to_fetch.append((g.get('away_logo'), (16, 16)))

                        if g_type == 'weather' or sport.startswith('clock') or is_music or g_type == 'flight_visitor' or g_type == 'flight_airport_hud':
                            static_items.append(g)
                        elif self.mode in ('sports_full', 'soccer_full') and g_type not in ['leaderboard', 'stock_ticker'] and 'flight' not in str(g_type):
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
if False and __name__ == "__main__":
    ticker = TickerStreamer()
    try:
        ticker.render_loop()
    except KeyboardInterrupt:
        print("Stopping...")
        ticker.running = False

# ===== Embedded from stadium.py =====

"""
stadium_renderer.py
===================
Python port of the Stadium ticker layout from ticker_playground.html.

Drop-in replacement for draw_single_game() in ticker_streamer.py.
Uses the real logo cache from TickerStreamer (logo_cache dict of PIL RGBA images).

Usage
-----
    from stadium_renderer import StadiumRenderer
    renderer = StadiumRenderer(logo_cache=self.logo_cache)
    img, card_width = renderer.render(game_dict)
    # img  : PIL Image, mode="RGBA", size=(card_width, 32)

The game_dict is exactly what ticker_streamer.py receives from the backend:
{
    "sport": "nfl",
    "home_abbr": "SF", "away_abbr": "KC",
    "home_score": 17,   "away_score": 24,
    "home_logo": "https://...",   "away_logo": "https://...",
    "home_color": "#AA0000",      "away_color": "#E31837",
    "status": "Q3 8:22",
    "state": "in",           # "in" | "post" | "pre"
    "situation": {
        "possession": "KC",
        "downDist": "3RD & 7",
        "isRedZone": False,
        "powerPlay": False,
        "emptyNet": False,
        "emptyNetSide": "",
        "shootout": {"away": ["goal","miss"], "home": ["goal","goal"]},
        "onFirst": True, "onSecond": False, "onThird": False,
        "balls": 2, "strikes": 1, "outs": 1,
    }
}
"""

import io
import re
import hashlib
import requests
from PIL import Image, ImageDraw, ImageStat, ImageFilter, ImageChops, ImageEnhance

# ── Canvas constants ──────────────────────────────────────────────────────────
H = 32          # card height, always 32px (LED panel height)
LOGO_SZ = 22    # logo square size in pixels
LOGO_PAD = 2    # gap between logo edge and center content zone
ZONE = LOGO_SZ + LOGO_PAD  # space each side takes = 24px

# ── 3×5 pixel font ────────────────────────────────────────────────────────────
PF = {
    '0':[[1,1,1],[1,0,1],[1,0,1],[1,0,1],[1,1,1]],
    '1':[[0,1,0],[1,1,0],[0,1,0],[0,1,0],[1,1,1]],
    '2':[[1,1,1],[0,0,1],[1,1,1],[1,0,0],[1,1,1]],
    '3':[[1,1,1],[0,0,1],[0,1,1],[0,0,1],[1,1,1]],
    '4':[[1,0,1],[1,0,1],[1,1,1],[0,0,1],[0,0,1]],
    '5':[[1,1,1],[1,0,0],[1,1,1],[0,0,1],[1,1,1]],
    '6':[[1,1,1],[1,0,0],[1,1,1],[1,0,1],[1,1,1]],
    '7':[[1,1,1],[0,0,1],[0,1,0],[0,1,0],[0,1,0]],
    '8':[[1,1,1],[1,0,1],[1,1,1],[1,0,1],[1,1,1]],
    '9':[[1,1,1],[1,0,1],[1,1,1],[0,0,1],[1,1,1]],
    'A':[[0,1,0],[1,0,1],[1,1,1],[1,0,1],[1,0,1]],
    'B':[[1,1,0],[1,0,1],[1,1,0],[1,0,1],[1,1,0]],
    'C':[[0,1,1],[1,0,0],[1,0,0],[1,0,0],[0,1,1]],
    'D':[[1,1,0],[1,0,1],[1,0,1],[1,0,1],[1,1,0]],
    'E':[[1,1,1],[1,0,0],[1,1,0],[1,0,0],[1,1,1]],
    'F':[[1,1,1],[1,0,0],[1,1,0],[1,0,0],[1,0,0]],
    'G':[[0,1,1],[1,0,0],[1,0,1],[1,0,1],[0,1,1]],
    'H':[[1,0,1],[1,0,1],[1,1,1],[1,0,1],[1,0,1]],
    'I':[[1,1,1],[0,1,0],[0,1,0],[0,1,0],[1,1,1]],
    'J':[[0,0,1],[0,0,1],[0,0,1],[1,0,1],[0,1,1]],
    'K':[[1,0,1],[1,1,0],[1,0,0],[1,1,0],[1,0,1]],
    'L':[[1,0,0],[1,0,0],[1,0,0],[1,0,0],[1,1,1]],
    'M':[[1,0,1],[1,1,1],[1,0,1],[1,0,1],[1,0,1]],
    'N':[[1,0,1],[1,1,1],[1,1,1],[1,0,1],[1,0,1]],
    'O':[[0,1,0],[1,0,1],[1,0,1],[1,0,1],[0,1,0]],
    'P':[[1,1,0],[1,0,1],[1,1,0],[1,0,0],[1,0,0]],
    'Q':[[0,1,0],[1,0,1],[1,0,1],[1,1,1],[0,1,1]],
    'R':[[1,1,0],[1,0,1],[1,1,0],[1,0,1],[1,0,1]],
    'S':[[0,1,1],[1,0,0],[0,1,0],[0,0,1],[1,1,0]],
    'T':[[1,1,1],[0,1,0],[0,1,0],[0,1,0],[0,1,0]],
    'U':[[1,0,1],[1,0,1],[1,0,1],[1,0,1],[0,1,1]],
    'V':[[1,0,1],[1,0,1],[1,0,1],[1,0,1],[0,1,0]],
    'W':[[1,0,1],[1,0,1],[1,0,1],[1,1,1],[1,0,1]],
    'X':[[1,0,1],[1,0,1],[0,1,0],[1,0,1],[1,0,1]],
    'Y':[[1,0,1],[1,0,1],[0,1,0],[0,1,0],[0,1,0]],
    'Z':[[1,1,1],[0,0,1],[0,1,0],[1,0,0],[1,1,1]],
    '-':[[0,0,0],[0,0,0],[1,1,1],[0,0,0],[0,0,0]],
    ':':[[0,0,0],[0,1,0],[0,0,0],[0,1,0],[0,0,0]],
    '.':[[0,0,0],[0,0,0],[0,0,0],[0,0,0],[0,1,0]],
    "'":[[0,1,0],[0,1,0],[0,0,0],[0,0,0],[0,0,0]],
    '/':[[0,0,1],[0,0,1],[0,1,0],[1,0,0],[1,0,0]],
    '+':[[0,0,0],[0,1,0],[1,1,1],[0,1,0],[0,0,0]],
    '&':[[0,1,0],[1,0,1],[0,1,0],[1,0,1],[0,1,1]],
    '#':[[1,0,1],[1,1,1],[1,0,1],[1,1,1],[1,0,1]],
    '▲':[[0,1,0],[1,1,1],[1,1,1],[0,0,0],[0,0,0]],
    '▼':[[0,0,0],[0,0,0],[1,1,1],[1,1,1],[0,1,0]],
    ' ':[[0,0,0],[0,0,0],[0,0,0],[0,0,0],[0,0,0]],
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
    '/': [0x1, 0x2, 0x2, 0x4, 0x4, 0x8], ',': [0x0, 0x0, 0x0, 0x0, 0x4, 0x8], '!': [0x4, 0x4, 0x4, 0x4, 0x0, 0x4],
    '?': [0x6, 0x9, 0x2, 0x4, 0x0, 0x4], '(': [0x2, 0x4, 0x4, 0x4, 0x4, 0x2], ')': [0x4, 0x2, 0x2, 0x2, 0x2, 0x4],
    '▲': [0x0, 0x4, 0xA, 0x1F, 0x0, 0x0], '▼': [0x0, 0x0, 0x1F, 0xA, 0x4, 0x0],
}
# ── Low-level drawing helpers ─────────────────────────────────────────────────

def _clamp(v): return max(0, min(255, int(v)))

def fi(d, x, y, w, h, r, g, b, a=255):
    """Fill integer rectangle."""
    if w <= 0 or h <= 0:
        return
    x, y, w, h = int(round(x)), int(round(y)), int(round(w)), int(round(h))
    d.rectangle([x, y, x + w - 1, y + h - 1], fill=(_clamp(r), _clamp(g), _clamp(b), _clamp(a)))

def li(c, f=0.4):
    """Lighten colour tuple."""
    return tuple(min(255, int(v + (255 - v) * f)) for v in c)

def da(c, f=0.5):
    """Darken colour tuple."""
    return tuple(int(v * (1 - f)) for v in c)

def hex_to_rgb(hex_str):
    """Convert '#RRGGBB' or 'RRGGBB' to (r, g, b)."""
    h = (hex_str or '').strip().lstrip('#')
    if len(h) == 6:
        try:
            return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))
        except ValueError:
            pass
    return (80, 80, 80)


# ── Pixel font ────────────────────────────────────────────────────────────────

def pf_char(d, ch, x, y, r, g, b, sc=1):
    """Draw one pixel-font glyph; returns width consumed."""
    bm = PF.get(ch.upper(), PF[' '])
    col = (_clamp(r), _clamp(g), _clamp(b), 255)
    for row in range(5):
        for col_idx in range(3):
            if bm[row][col_idx]:
                fx, fy = x + col_idx * sc, y + row * sc
                d.rectangle([fx, fy, fx + sc - 1, fy + sc - 1], fill=col)
    return 4 * sc

def pf_text(d, text, x, y, r, g, b, sc=1):
    """Draw pixel-font string; returns total width."""
    cx = x
    for ch in str(text).upper():
        cx += pf_char(d, ch, cx, y, r, g, b, sc)
    return cx - x

def pf_w(text, sc=1):
    """Width of pixel-font string."""
    return len(str(text)) * 4 * sc


def draw_hybrid_text(draw, x, y, text_str, color):
    """Old renderer style from flights.py: 4px glyph width, 6 rows high."""
    text_str = str(text_str).upper()
    x_cursor = x
    for char in text_str:
        bitmap = HYBRID_FONT_MAP.get(char, HYBRID_FONT_MAP.get(' ', [0x0] * 6))
        for r, row_byte in enumerate(bitmap):
            if row_byte & 0x8:
                draw.point((x_cursor + 0, y + r), fill=color)
            if row_byte & 0x4:
                draw.point((x_cursor + 1, y + r), fill=color)
            if row_byte & 0x2:
                draw.point((x_cursor + 2, y + r), fill=color)
            if row_byte & 0x1:
                draw.point((x_cursor + 3, y + r), fill=color)
        x_cursor += 5
    return x_cursor - x


# ── Sprite helpers ────────────────────────────────────────────────────────────

def draw_football(d, cx, cy):
    """Tiny football icon (7×3 px)."""
    brown = (139, 69, 19, 255)
    white = (255, 255, 255, 255)
    fi(d, cx - 2, cy,     5, 1, *brown[:3])
    fi(d, cx - 3, cy + 1, 7, 1, *brown[:3])
    fi(d, cx - 2, cy + 2, 5, 1, *brown[:3])
    fi(d, cx - 1, cy + 1, 1, 1, 255, 255, 255)
    fi(d, cx,     cy + 1, 1, 1, 255, 255, 255)
    fi(d, cx + 1, cy + 1, 1, 1, 255, 255, 255)

def draw_base_diamond(d, cx, ty, on1, on2, on3):
    """
    Baseball base diamond.
    cx=center x, ty=top y.
    on2=2B(top), on1=1B(right), on3=3B(left).
    """
    bases = [
        (cx,     ty,     on2),   # 2B top
        (cx + 4, ty + 4, on1),   # 1B right
        (cx - 4, ty + 4, on3),   # 3B left
    ]
    for bx, by, on in bases:
        c = (255, 200, 0) if on else (55, 55, 55)
        fi(d, bx - 2, by,     5, 1, *c)
        fi(d, bx - 1, by + 1, 3, 1, *c)
        fi(d, bx,     by + 2, 1, 1, *c)
        fi(d, bx - 2, by,     1, 1, *c)
        fi(d, bx + 2, by,     1, 1, *c)

def draw_shootout_dot(d, x, y, result, size=5, stride=7):
    """
    Draw one shootout indicator at pixel position (x, y).
    result: 'goal' | 'miss' | 'pending'
    size:   dot pixel size (5 for NHL, 3 for soccer)
    """
    if result == 'goal':
        fi(d, x, y, size, size, 50, 200, 70)
    elif result == 'miss':
        # Red X scaled to size
        if size >= 4:
            fi(d, x,          y,          2, 2, 220, 55, 55)
            fi(d, x + size-2, y,          2, 2, 220, 55, 55)
            fi(d, x + 1,      y + size//2, size - 2, 1, 220, 55, 55)
            fi(d, x,          y + size-2, 2, 2, 220, 55, 55)
            fi(d, x + size-2, y + size-2, 2, 2, 220, 55, 55)
        else:  # 3px version
            fi(d, x,     y,     2, 1, 220, 55, 55)
            fi(d, x + 1, y + 1, 1, 1, 220, 55, 55)
            fi(d, x,     y + 2, 2, 1, 220, 55, 55)
            fi(d, x + 2, y,     1, 1, 220, 55, 55)
            fi(d, x + 2, y + 2, 1, 1, 220, 55, 55)
    else:
        # Pending: grey filled square with dark inner
        fi(d, x, y, size, size, 55, 55, 55)
        fi(d, x + 1, y + 1, size - 2, size - 2, 10, 10, 14)

def draw_so_column(d, x, y, results, vertical=True, size=5, stride=7, max_show=5):
    """Draw a column (or row) of shootout dots, always showing at least 3 slots."""
    n_show = min(max(len(results), 3), max_show)
    for i in range(n_show):
        r = results[i] if i < len(results) else 'pending'
        dx = x if vertical else x + i * stride
        dy = y + i * stride if vertical else y
        draw_shootout_dot(d, dx, dy, r, size=size, stride=stride)


# ── Logo loading ──────────────────────────────────────────────────────────────

def _download_logo(url, size=(22, 22)):
    """Fetch and resize a logo from URL; returns RGBA PIL Image or None."""
    try:
        r = requests.get(url, timeout=5)
        if r.status_code == 200:
            img = Image.open(io.BytesIO(r.content)).convert('RGBA')
            img.thumbnail(size, Image.Resampling.LANCZOS)
            out = Image.new('RGBA', size, (0, 0, 0, 0))
            out.paste(img, ((size[0] - img.width) // 2, (size[1] - img.height) // 2))
            return _enhance_logo_visibility(out)
    except Exception:
        pass
    return None


def _enhance_logo_visibility(img):
    """Only outline logos that are overwhelmingly dark."""
    try:
        if not img or img.mode != 'RGBA':
            return img

        rgba = img.copy()
        alpha = rgba.split()[3]
        px = list(rgba.getdata())

        # Only sample fully opaque pixels to ignore dark anti-aliased edges
        core_pixels = [p for p in px if p[3] > 200]
        if not core_pixels:
            core_pixels = [p for p in px if p[3] > 20]
            if not core_pixels:
                return rgba

        dark = 0
        for r, g, b, _ in core_pixels:
            # Stricter luminance check: only true black or very dark navy/brown
            lum = 0.2126 * r + 0.7152 * g + 0.0722 * b
            if lum < 40: 
                dark += 1

        dark_ratio = dark / len(core_pixels)
        
        # If the logo isn't at least 92% very dark, SKIP the outline.
        if dark_ratio < 0.92:
            return rgba

        # It's a dark logo, add the white stroke
        edge = alpha.filter(ImageFilter.MaxFilter(3))
        ring = ImageChops.subtract(edge, alpha)
        ring_layer = Image.new('RGBA', rgba.size, (245, 245, 245, 230))
        outlined = Image.new('RGBA', rgba.size, (0, 0, 0, 0))
        outlined.paste(ring_layer, (0, 0), ring)
        outlined.alpha_composite(rgba)
        return outlined
    except Exception:
        return img

def _fallback_logo(color, size=(22, 22)):
    """Coloured square with highlight border when no real logo available."""
    img = Image.new('RGBA', size, (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    r, g, b = color
    dc = da(color)
    d.rectangle([0, 0, size[0]-1, size[1]-1], fill=(*dc, 255))
    d.rectangle([2, 2, size[0]-3, size[1]-3], fill=(*da(color, 0.1), 255))
    d.rectangle([0, 0, size[0]-1, 0], fill=(r, g, b, 255))
    d.rectangle([0, size[1]-1, size[0]-1, size[1]-1], fill=(r, g, b, 255))
    d.rectangle([0, 0, 0, size[1]-1], fill=(r, g, b, 255))
    d.rectangle([size[0]-1, 0, size[0]-1, size[1]-1], fill=(r, g, b, 255))
    li_c = li(color, 0.25)
    d.rectangle([1, 1, size[0]-2, 1], fill=(*li_c, 255))
    d.rectangle([1, 1, 1, size[1]-2], fill=(*li_c, 255))
    return img


# ── Card width calculator ─────────────────────────────────────────────────────

def calc_card_width(g):
    """
    Returns the minimum canvas width (px) so content never overlaps logos.
    Mirrors calcCardWidth() in the JS playground exactly.
    """
    sport = g.get('sport', '').lower()
    state = g.get('state', '')
    is_active = state == 'in'
    is_mlb = 'baseball' in sport or 'mlb' in sport
    is_nfl = 'football' in sport or 'nfl' in sport
    is_nhl = 'hockey'   in sport or 'nhl' in sport
    sit = g.get('situation', {}) or {}
    shootout = sit.get('shootout') or (g.get('so') if 'so' in g else None)
    is_so = bool(shootout)
    dd = sit.get('downDist', '') or g.get('dd', '') or ''

    a_score = str(g.get('away_score', g.get('as', 0)))
    h_score = str(g.get('home_score', g.get('hs', 0)))
    status = str(g.get('status', ''))

    # Per-side width: each score side only takes the width it needs.
    a_score_w = pf_w(a_score, sc=2)
    h_score_w = pf_w(h_score, sc=2)
    score_w = a_score_w + pf_w('-', sc=2) + h_score_w
    center = score_w

    if is_mlb and is_active:
        center = max(center, score_w + 2)
    else:
        center = max(center, pf_w(status))

    if is_nfl and is_active and dd:
        center = max(center, pf_w(dd))

    # Shootout: vertical SO columns (7px each) flank the score on both sides
    if (is_nhl or sport == 'soccer') and is_so:
        center = max(center, score_w + 14)

    total = ZONE + 4 + center + 4 + ZONE
    return min(160, int((total + 1) // 2 * 2))


# ── Main renderer ─────────────────────────────────────────────────────────────

class StadiumRenderer:
    """
    Renders a single game card in the Stadium style.

    Parameters
    ----------
    logo_cache : dict
        Shared logo cache dict (same one TickerStreamer uses).
        Key format: "{url}_{w}x{h}.png" or however you key it.
        Values are PIL RGBA images already sized to (20, 20).
        If the logo is not in cache, this renderer will try to fetch it.
    """

    LOGO_SIZE = (LOGO_SZ, LOGO_SZ)

    def __init__(self, logo_cache=None):
        self._cache = logo_cache if logo_cache is not None else {}

    # ── Logo management ───────────────────────────────────────────────────────

    def _get_logo(self, url):
        """Return RGBA PIL image at LOGO_SIZE, or None."""
        if not url:
            return None
        key = f"{url}_{LOGO_SZ}x{LOGO_SZ}"
        if key not in self._cache:
            img = _download_logo(url, self.LOGO_SIZE)
            if img:
                self._cache[key] = img
        return self._cache.get(key)

    def _paste_logo(self, img, logo, x, y):
        """Paste RGBA logo onto img at (x, y), using alpha as mask."""
        if logo:
            img.paste(logo, (int(x), int(y)), logo)

    # ── Public API ────────────────────────────────────────────────────────────

    def render(self, g):
        """
        Render game dict g.  Returns (PIL.Image RGBA, card_width_px).

        Accepts both the original ticker_streamer field names
        (home_score, away_score, home_logo, away_logo, home_color, away_color,
         situation dict) and the compact playground field names
        (hs, as, ac, hc).
        """
        # Normalise field names so both formats work
        g = self._normalise(g)

        CW = calc_card_width(g)
        img = Image.new('RGBA', (CW, H), (0, 0, 0, 255))
        d = ImageDraw.Draw(img, 'RGBA')

        sport = g['sport'].lower()
        is_active = g['state'] == 'in'
        is_mlb  = 'baseball' in sport or 'mlb'    in sport
        is_nfl  = 'football' in sport or 'nfl'    in sport
        is_nhl  = 'hockey'   in sport or 'nhl'    in sport
        is_soc  = 'soccer'   in sport
        is_march = 'march' in sport
        sit     = g.get('sit', {})
        shootout = sit.get('shootout')
        is_so   = bool(shootout)

        ac = g['ac']   # away colour (r,g,b)
        hc = g['hc']   # home colour
        a_score = str(g['as'])
        h_score = str(g['hs'])
        status = g['status']

        def _side_from_value(val):
            if val is None:
                return None
            s = str(val).strip().upper()
            if not s:
                return None

            home_tokens = {
                str(g.get('home', '')).strip().upper(),
                str(g.get('home_abbr', '')).strip().upper(),
                str(g.get('home_id', '')).strip().upper(),
                'HOME',
                'H',
            }
            away_tokens = {
                str(g.get('away', '')).strip().upper(),
                str(g.get('away_abbr', '')).strip().upper(),
                str(g.get('away_id', '')).strip().upper(),
                'AWAY',
                'A',
            }
            home_tokens.discard('')
            away_tokens.discard('')

            if s in home_tokens:
                return 'home'
            if s in away_tokens:
                return 'away'
            return None

        # ── Background + amber header ─────────────────────────────────────────
        fi(d, 0, 0, CW, H,  0, 0, 0)
        fi(d, 0, 7, CW, 1,  55, 76, 130)

        # Status centered in header (overwritten by sport-specific blocks below)
        st = status[:12]
        if not (is_mlb and is_active):
            self._draw_header_text(img, CW, st)
            # Keep separator line crisp when glyph descenders touch y=7.
            fi(d, 0, 7, CW, 1, 55, 76, 130)

        # ── Logos ─────────────────────────────────────────────────────────────
        a_logo_x = 1
        h_logo_x = CW - LOGO_SZ - 1
        logo_y   = H - LOGO_SZ - 1

        a_logo = self._get_logo(g.get('away_logo'))
        h_logo = self._get_logo(g.get('home_logo'))

        if a_logo:
            self._paste_logo(img, a_logo, a_logo_x, logo_y)
        else:
            self._draw_fallback_logo(d, a_logo_x, logo_y, ac)

        if h_logo:
            self._paste_logo(img, h_logo, h_logo_x, logo_y)
        else:
            self._draw_fallback_logo(d, h_logo_x, logo_y, hc)

        # ── Content safe zone ─────────────────────────────────────────────────
        cL  = a_logo_x + LOGO_SZ + LOGO_PAD
        cR  = h_logo_x - LOGO_PAD
        cCX = (cL + cR) // 2
        center_x = (cL + cR) / 2.0

        # ── Score (skipped for active MLB — drawn in MLB block) ───────────────
        if not (is_mlb and is_active):
            a_sw = pf_w(a_score, sc=2)
            h_sw = pf_w(h_score, sc=2)
            dash_sw = pf_w('-', sc=2)
            total_sw = a_sw + dash_sw + h_sw
            # Render using true per-side widths so only the lopsided side expands.
            score_layer = Image.new('RGBA', (total_sw, 10), (0, 0, 0, 0))
            score_draw = ImageDraw.Draw(score_layer, 'RGBA')
            pf_text(score_draw, a_score, 0,           0, 255, 255, 255, sc=2)
            pf_text(score_draw, '-',     a_sw,        0, 255, 255, 255, sc=2)
            pf_text(score_draw, h_score, a_sw + dash_sw, 0, 255, 255, 255, sc=2)
            score_layer = score_layer.resize((total_sw, 11), Image.Resampling.NEAREST)
            layer_x = int(round(center_x - total_sw / 2.0))
            img.alpha_composite(score_layer, (layer_x, 9))

        # ══ NFL ══════════════════════════════════════════════════════════════
        if is_nfl and is_active:
            poss    = sit.get('possession', '') or g.get('poss', '')
            dd      = sit.get('downDist',   '') or g.get('dd',   '')
            rz      = sit.get('isRedZone',  False) or g.get('rz', False)
            poss_side = _side_from_value(poss)
            is_poss_home = poss_side == 'home'
            is_poss_away = poss_side == 'away'

            if is_poss_home or is_poss_away:
                if is_poss_home:
                    hdr_cx = h_logo_x + LOGO_SZ // 2 - 1
                else:
                    hdr_cx = a_logo_x + LOGO_SZ // 2 - 1
                draw_football(d, hdr_cx, 2)

            if rz:
                d.rectangle([0, 0, CW - 1, H - 1],
                            outline=(255, 40, 40, 153), width=1)

            if dd:
                dd_color = (235, 70, 70) if rz else (0, 200, 60)
                pf_text(d, dd, cCX - pf_w(dd) // 2, 23, *dd_color)

        # ══ NHL ══════════════════════════════════════════════════════════════
        if is_nhl and is_active and not is_so:
            poss        = sit.get('possession', '') or g.get('poss', '')
            is_pp       = sit.get('powerPlay',  False) or g.get('pp', False)
            is_en       = sit.get('emptyNet',   False) or g.get('en', False)
            en_team     = sit.get('emptyNetSide', '') or g.get('enTeam', '')
            poss_side = _side_from_value(poss)
            is_poss_home = poss_side == 'home'
            is_poss_away = poss_side == 'away'

            poss_hdr_x = (h_logo_x + LOGO_SZ // 2) if is_poss_home \
                         else (a_logo_x + LOGO_SZ // 2)

            if is_en:
                # Fallback to possession to figure out who pulled their goalie
                en_is_home = (poss_side == 'home')
                en_hdr_x = (h_logo_x + LOGO_SZ // 2) if en_is_home \
                           else (a_logo_x + LOGO_SZ // 2)
                pf_text(d, 'EN', en_hdr_x - pf_w('EN') // 2, 2, 255, 100, 100)
            elif is_pp and (is_poss_home or is_poss_away):
                pf_text(d, 'PP', poss_hdr_x - pf_w('PP') // 2, 2, 255, 220, 0)

        # NHL shootout — vertical columns just inside the logos; card width
        # is expanded by calc_card_width to keep them clear of the score.
        if is_nhl and is_so:
            so_a = shootout.get('away', [])
            so_h = shootout.get('home', [])
            draw_so_column(d, a_logo_x + LOGO_SZ + 2, 9, so_a,
                           vertical=True, size=5, stride=7, max_show=3)
            draw_so_column(d, h_logo_x - 7, 9, so_h,
                           vertical=True, size=5, stride=7, max_show=3)

        # ══ MLB ══════════════════════════════════════════════════════════════
        if is_mlb and is_active:
            balls   = int(sit.get('balls',   g.get('balls',   0)) or 0)
            strikes = int(sit.get('strikes', g.get('strikes', 0)) or 0)
            outs    = int(sit.get('outs',    g.get('outs',    0)) or 0)
            on1     = bool(sit.get('onFirst',  g.get('on1', False)))
            on2     = bool(sit.get('onSecond', g.get('on2', False)))
            on3     = bool(sit.get('onThird',  g.get('on3', False)))

            # Determine top/bottom from status
            status_up = status.upper()
            is_top = 'TOP' in status_up or 'T ' in status_up
            # Also accept explicit field
            if 'isTop' in g:
                is_top = bool(g['isTop'])

            # Re-draw header
            fi(d, 0, 0, CW, 8, 0, 0, 0)
            fi(d, 0, 7, CW, 1, 55, 76, 130)

            # Inning arrow + number, amber always (pixel glyph keeps clear ▲/▼ shape)
            inn_match = re.search(r'\d+', status)
            inn_num = inn_match.group() if inn_match else ''
            arrow_glyph = '▲' if is_top else '▼'
            arrow_w = pf_w(arrow_glyph)
            num_w = pf_w(inn_num)
            total_w = arrow_w + num_w
            hx = max(1, (CW - total_w) // 2)
            # Shadow pass
            pf_text(d, arrow_glyph, hx + 1, 2, 8, 8, 8)
            pf_text(d, inn_num, hx + arrow_w + 1, 2, 8, 8, 8)
            # Foreground pass
            pf_text(d, arrow_glyph, hx, 1, 255, 220, 105)
            pf_text(d, inn_num, hx + arrow_w, 1, 255, 240, 150)

            # B-S count above batting team's logo
            b_glyph, s_glyph = str(balls), str(strikes)
            bs_w = pf_w(b_glyph) + pf_w('-') + pf_w(s_glyph)
            batting_side = _side_from_value(sit.get('possession', '') or g.get('poss', ''))
            if batting_side is None:
                batting_side = 'away' if is_top else 'home'
            bs_hdr_x = (h_logo_x + LOGO_SZ // 2 - bs_w // 2) if batting_side == 'home' \
                       else (a_logo_x + LOGO_SZ // 2 - bs_w // 2)
            bsx = bs_hdr_x
            bsx += pf_text(d, b_glyph, bsx, 2,  60, 200,  60)   # green
            bsx += pf_text(d, '-',     bsx, 2, 160, 160, 160)
            pf_text(d,     s_glyph, bsx, 2, 255, 140,  40)       # orange

            # Score – true per-side widths, centered as one block.
            a_sw   = pf_w(a_score, sc=2)
            h_sw   = pf_w(h_score, sc=2)
            dash_sw = pf_w('-', sc=2)
            total_sw = a_sw + dash_sw + h_sw
            score_x = int(round(center_x - total_sw / 2.0))
            dash_x = score_x + a_sw
            pf_text(d, a_score, score_x,            8, 255, 255, 255, sc=2)
            pf_text(d, '-',     dash_x,             8, 255, 255, 255, sc=2)
            pf_text(d, h_score, dash_x + dash_sw,   8, 255, 255, 255, sc=2)

            # Base diamond centred under the dash glyph (dash_x + 3 = visual centre)
            draw_base_diamond(d, dash_x + 3, 19, on1, on2, on3)

            # Outs — 3 red pips centered under the diamond.
            out_y = 28
            out_total_w = 3 * 5 - 1
            ox = (dash_x + 3) - out_total_w // 2
            for i in range(3):
                col = (210, 70, 70) if i < outs else (45, 45, 45)
                fi(d, ox + i * 5, out_y, 4, 3, *col)

        # ══ Soccer shootout ══════════════════════════════════════════════════
        if is_soc and is_so:
            so_a = shootout.get('away', [])
            so_h = shootout.get('home', [])
            # 3x3 dots, 5px stride -> top at y=8, last box ends at y=30.
            self._draw_soccer_so_col(d, a_logo_x + LOGO_SZ + 2, 8, so_a)
            self._draw_soccer_so_col(d, h_logo_x - 5, 8, so_h)

        # ══ March Madness ════════════════════════════════════════════════════
        if is_march:
            seed_a = g.get('seed_a', g.get('away_seed', ''))
            seed_h = g.get('seed_h', g.get('home_seed', ''))
            won_a  = g['state'] == 'post' and g['as'] > g['hs']
            won_h  = g['state'] == 'post' and g['hs'] > g['as']
            sa, sh = str(seed_a), str(seed_h)
            a_col = (100, 210, 100) if won_a else (170, 70, 70) if won_h else (66, 117, 199)
            h_col = (100, 210, 100) if won_h else (170, 70, 70) if won_a else (66, 117, 199)
            pf_text(d, sa, 2,                    2, *a_col)
            pf_text(d, sh, CW - pf_w(sh) - 2,   2, *h_col)
            # No center half label for March Madness cards.

        return img, CW

    def _draw_header_text(self, img, card_w, text):
        """Draw header with the old hybrid bitmap renderer style."""
        label = str(text or '')[:9].upper()
        if not label:
            return
        d = ImageDraw.Draw(img, 'RGBA')
        tw = len(label) * 5
        tx = max(1, (card_w - tw) // 2)
        ty = 1
        draw_hybrid_text(d, tx + 1, ty + 1, label, (8, 8, 8, 180))
        draw_hybrid_text(d, tx, ty, label, (255, 240, 150, 255))

    # ── Soccer SO column (3x3 dots, 5px stride) ───────────────────────────────
    def _draw_soccer_so_col(self, d, x, y, results):
        n_show = 5
        for i in range(n_show):
            r = results[i] if i < len(results) else 'pending'
            dy = y + i * 5
            if r == 'goal':
                fi(d, x, dy, 3, 3, 50, 200, 70)
            elif r == 'miss':
                fi(d, x, dy, 3, 3, 220, 55, 55)
            else:
                fi(d, x, dy, 3, 3, 80, 80, 80)

    # ── Fallback logo (coloured block) ────────────────────────────────────────
    def _draw_fallback_logo(self, d, x, y, color):
        r, g, b = color
        dc = da(color)
        fi(d, x, y, LOGO_SZ, LOGO_SZ, *dc)
        fi(d, x + 2, y + 2, LOGO_SZ - 4, LOGO_SZ - 4, *da(color, 0.1))
        fi(d, x, y, LOGO_SZ, 1, r, g, b)
        fi(d, x, y + LOGO_SZ - 1, LOGO_SZ, 1, r, g, b)
        fi(d, x, y, 1, LOGO_SZ, r, g, b)
        fi(d, x + LOGO_SZ - 1, y, 1, LOGO_SZ, r, g, b)
        lc = li(color, 0.25)
        fi(d, x + 1, y + 1, LOGO_SZ - 2, 1, *lc)
        fi(d, x + 1, y + 1, 1, LOGO_SZ - 2, *lc)

    # ── Field normaliser ──────────────────────────────────────────────────────
    @staticmethod
    def _normalise(g):
        """
        Accept both ticker_streamer field names and compact playground names.
        Always returns the compact form internally.
        """
        out = dict(g)

        # Scores
        if 'as' not in out:
            out['as'] = int(out.get('away_score', 0) or 0)
        if 'hs' not in out:
            out['hs'] = int(out.get('home_score', 0) or 0)
        else:
            out['as'] = int(out['as'])
            out['hs'] = int(out['hs'])

        # Abbrs
        if 'away' not in out:
            out['away'] = out.get('away_abbr', '???')
        if 'home' not in out:
            out['home'] = out.get('home_abbr', '???')

        # Sport
        if 'sport' not in out:
            out['sport'] = 'unknown'

        # Team colours from hex strings
        def _col(key_hex, key_rgb, fallback):
            if key_rgb in out and isinstance(out[key_rgb], (list, tuple)):
                return tuple(int(v) for v in out[key_rgb][:3])
            return hex_to_rgb(out.get(key_hex, '')) or fallback

        out['ac'] = _col('away_color', 'ac', (80, 80, 80))
        out['hc'] = _col('home_color', 'hc', (80, 80, 80))

        # State
        if 'state' not in out:
            s = str(out.get('game_state', out.get('status', ''))).lower()
            if 'final' in s or 'post' in s:
                out['state'] = 'post'
            elif any(x in s for x in ('q', 'p', 'h', 'inning', 'top', 'bot', "'", 'live')):
                out['state'] = 'in'
            else:
                out['state'] = 'pre'

        # Situation dict normalisation
        sit = out.get('situation', {}) or {}
        out['sit'] = sit

        # Shootout lives in situation.shootout
        so = sit.get('shootout')
        if so and isinstance(so, dict):
            # ticker_streamer uses 'away'/'home' keys already
            out.setdefault('so', so)

        return out


# ── Convenience: render strip of all games ────────────────────────────────────

def build_strip(games, logo_cache=None, repeat=1):
    """
    Render a horizontal strip of game cards (optionally repeated for looping).
    Returns a single PIL RGBA image.
    """
    renderer = StadiumRenderer(logo_cache=logo_cache)
    cards = []
    for g in games:
        img, _ = renderer.render(g)
        cards.append(img)

    if not cards:
        return Image.new('RGBA', (1, H), (0, 0, 0, 255))

    # Tile for seamless looping
    all_cards = cards * repeat
    total_w = sum(c.width for c in all_cards)
    strip = Image.new('RGBA', (total_w, H), (0, 0, 0, 255))
    x = 0
    for c in all_cards:
        strip.paste(c, (x, 0), c)
        x += c.width
    return strip


# ── One-file entry point ─────────────────────────────────────────────────────
if __name__ == '__main__':
    ticker = TickerStreamer()
    try:
      ticker.render_loop()
    except KeyboardInterrupt:
      print("Stopping...")
      ticker.running = False
