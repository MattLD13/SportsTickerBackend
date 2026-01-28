import time
import threading
import io
import requests
import traceback
import sys
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
from datetime import datetime
from PIL import Image, ImageDraw, ImageFont, ImageOps, ImageStat
from rgbmatrix import RGBMatrix, RGBMatrixOptions
from flask import Flask, request, render_template_string

# ================= CONFIGURATION =================
BACKEND_URL = "https://ticker.mattdicks.org" 

# 6 Panels wide (64 * 6 = 384)
PANEL_W = 384 
PANEL_H = 32
SETUP_SSID = "SportsTicker_Setup"
SETUP_PASS = "setup1234"
PAGE_HOLD_TIME = 8.0 
REFRESH_RATE = 0 # ZERO delay for maximum speed
ID_FILE_PATH = "/boot/ticker_id.txt"
ID_FILE_FALLBACK = "ticker_id.txt"
ASSETS_DIR = os.path.expanduser("~/ticker/assets")

# Disable SSL Warnings
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

# --- FONTS & BITMAPS ---
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
    '^': [0x4, 0xA, 0x0, 0x0, 0x0], '▲': [0x4, 0xE, 0x1F, 0x0, 0x0], '▼': [0x1F, 0xE, 0x4, 0x0, 0x0],
    '(': [0x2, 0x4, 0x4, 0x4, 0x2], ')': [0x4, 0x2, 0x2, 0x2, 0x4]
}

# HYBRID FONT (4x6) FOR STATUS
HYBRID_FONT_MAP = {
    'A': [0x6, 0x9, 0x9, 0xF, 0x9, 0x9], 'B': [0xE, 0x9, 0xE, 0x9, 0x9, 0xE], 'C': [0x6, 0x9, 0x8, 0x8, 0x9, 0x6],
    'D': [0xE, 0x9, 0x9, 0x9, 0x9, 0xE], 'E': [0xF, 0x8, 0xE, 0x8, 0x8, 0xF], 'F': [0xF, 0x8, 0xE, 0x8, 0x8, 0x8],
    'G': [0x6, 0x9, 0x8, 0xB, 0x9, 0x6], 'H': [0x9, 0x9, 0x9, 0xF, 0x9, 0x9], 'I': [0xE, 0x4, 0x4, 0x4, 0x4, 0xE],
    'J': [0x7, 0x2, 0x2, 0x2, 0xA, 0x4], 'K': [0x9, 0xA, 0xC, 0xC, 0xA, 0x9], 'L': [0x8, 0x8, 0x8, 0x8, 0x8, 0xF],
    'M': [0x9, 0xF, 0xF, 0x9, 0x9, 0x9], 'N': [0x9, 0xD, 0xF, 0xB, 0x9, 0x9], 'O': [0x6, 0x9, 0x9, 0x9, 0x9, 0x6],
    'P': [0xE, 0x9, 0x9, 0xE, 0x8, 0x8], 'Q': [0x6, 0x9, 0x9, 0x9, 0xA, 0x5], 'R': [0xE, 0x9, 0x9, 0xE, 0xA, 0x9],
    'S': [0x7, 0x8, 0x6, 0x1, 0x1, 0xE], 'T': [0xF, 0x4, 0x4, 0x4, 0x4, 0x4], 'U': [0x9, 0x9, 0x9, 0x9, 0x9, 0x6],
    'V': [0x9, 0x9, 0x9, 0x9, 0xA, 0x4], 'W': [0x9, 0x9, 0x9, 0xF, 0xF, 0x9], 'X': [0x9, 0x9, 0x6, 0x6, 0x9, 0x9],
    'Y': [0x9, 0x9, 0x9, 0x6, 0x2, 0x2], 'Z': [0xF, 0x1, 0x2, 0x4, 0x8, 0xF], 
    '0': [0x6, 0x9, 0x9, 0x9, 0x9, 0x6], '1': [0x4, 0xC, 0x4, 0x4, 0x4, 0xE], '2': [0xE, 0x9, 0x2, 0x4, 0x8, 0xF],
    '3': [0xE, 0x9, 0x2, 0x1, 0x9, 0xE], '4': [0x9, 0x9, 0xF, 0x1, 0x1, 0x1], '5': [0xF, 0x8, 0xE, 0x1, 0x9, 0xE],
    '6': [0x6, 0x8, 0xE, 0x9, 0x9, 0x6], '7': [0xF, 0x1, 0x2, 0x4, 0x8, 0x8], '8': [0x6, 0x9, 0x6, 0x9, 0x9, 0x6],
    '9': [0x6, 0x9, 0x9, 0x7, 0x1, 0x6], '+': [0x0, 0x0, 0x4, 0xE, 0x4, 0x0], '-': [0x0, 0x0, 0x0, 0xE, 0x0, 0x0],
    '.': [0x0, 0x0, 0x0, 0x0, 0x0, 0x4], ' ': [0x0, 0x0, 0x0, 0x0, 0x0, 0x0], ':': [0x0, 0x6, 0x6, 0x0, 0x6, 0x6],
    '~': [0x0, 0x0, 0x0, 0x0, 0x0, 0x0], '/': [0x1, 0x2, 0x2, 0x4, 0x4, 0x8], "'": [0x4, 0x4, 0x0, 0x0, 0x0, 0x0]
}

def draw_tiny_text(draw, x, y, text, color):
    text = str(text).upper()
    x_cursor = x
    for char in text:
        bitmap = TINY_FONT_MAP.get(char, TINY_FONT_MAP[' '])
        for r, row_byte in enumerate(bitmap):
            if row_byte & 0x8: draw.point((x_cursor+0, y+r), fill=color)
            if row_byte & 0x4: draw.point((x_cursor+1, y+r), fill=color)
            if row_byte & 0x2: draw.point((x_cursor+2, y+r), fill=color)
            if row_byte & 0x1: draw.point((x_cursor+3, y+r), fill=color)
            if len(bitmap) > 4 and (row_byte & 0x10): draw.point((x_cursor+4, y+r), fill=color)
        x_cursor += 4 
    return x_cursor - x

def draw_hybrid_text(draw, x, y, text, color):
    text = str(text).upper()
    x_cursor = x
    for char in text:
        if char == '~':
            x_cursor += 2; continue
        bitmap = HYBRID_FONT_MAP.get(char, HYBRID_FONT_MAP[' '])
        for r, row_byte in enumerate(bitmap):
            if row_byte & 0x8: draw.point((x_cursor+0, y+r), fill=color)
            if row_byte & 0x4: draw.point((x_cursor+1, y+r), fill=color)
            if row_byte & 0x2: draw.point((x_cursor+2, y+r), fill=color)
            if row_byte & 0x1: draw.point((x_cursor+3, y+r), fill=color)
        x_cursor += 5 
    return x_cursor

def get_device_id():
    path_to_use = ID_FILE_PATH
    if not os.path.isfile(ID_FILE_PATH):
        try:
            test_uuid = str(uuid.uuid4()); 
            with open(ID_FILE_PATH, 'w') as f: f.write(test_uuid)
        except: path_to_use = ID_FILE_FALLBACK
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

# --- MAIN CONTROLLER ---
class TickerStreamer:
    def __init__(self):
        print("Starting Ticker System...")
        self.device_id = get_device_id()
        if not os.path.exists(ASSETS_DIR): os.makedirs(ASSETS_DIR, exist_ok=True)
        
        options = RGBMatrixOptions()
        options.rows = 32
        options.cols = 64
        options.chain_length = 6 # 384px wide
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
        
        self.games = []; self.seamless_mode = True; self.brightness = 0.5; self.scroll_sleep = 0.05
        self.inverted = False; self.test_pattern = False; self.running = True; self.logo_cache = {}
        self.game_render_cache = {}; self.anim_tick = 0; self.is_pairing = False; self.pairing_code = ""
        self.config_updated = False; 
        
        # ACTIVE STATE MANAGEMENT
        self.active_strip = None
        self.bg_strip = None
        self.bg_strip_ready = False
        self.new_games_list = [] # Needed for mapping calculation
        self.static_items = []
        self.static_index = 0
        self.showing_static = False
        self.static_until = 0.0
        self.static_current_image = None
        self.static_current_game = None
        
        # [NEW] MUSIC UI STATE
        self.VINYL_SIZE = 51 # ODD NUMBER FIXES WOBBLE
        self.COVER_SIZE = 42
        self.vinyl_mask = Image.new("L", (self.COVER_SIZE, self.COVER_SIZE), 0)
        ImageDraw.Draw(self.vinyl_mask).ellipse((0, 0, self.COVER_SIZE, self.COVER_SIZE), fill=255)
        
        self.scratch_layer = Image.new("RGBA", (self.VINYL_SIZE, self.VINYL_SIZE), (0,0,0,0))
        self._init_vinyl_scratch()
        
        self.vinyl_rotation = 0.0
        self.text_scroll_pos = 0.0
        self.last_frame_time = time.time()
        self.local_music_progress = 0.0
        self.dominant_color = (29, 185, 84) # Default Green
        self.spindle_color = "black"
        self.last_cover_url = ""
        self.vinyl_cache = None
        self.viz_heights = [2.0] * 16 
        self.viz_phase = [random.random() * 10 for _ in range(16)]
        
        self.executor = concurrent.futures.ThreadPoolExecutor(max_workers=4)

        threading.Thread(target=self.poll_backend, daemon=True).start()
        threading.Thread(target=self.render_loop, daemon=True).start()

    def _init_vinyl_scratch(self):
        ds = ImageDraw.Draw(self.scratch_layer)
        # Record body
        ds.ellipse((0, 0, self.VINYL_SIZE-1, self.VINYL_SIZE-1), fill=(20, 20, 20), outline=(50,50,50))

    def update_display(self, pil_image):
        if self.test_pattern: pil_image = self.generate_test_pattern()
        img = pil_image.convert("RGB")
        if self.inverted: img = img.rotate(180)
        target_b = int(max(0, min(100, self.brightness * 100)))
        self.matrix.brightness = target_b
        self.matrix.SetImage(img)

    def generate_test_pattern(self):
        img = Image.new("RGB", (PANEL_W, PANEL_H), (0,0,0)); d = ImageDraw.Draw(img)
        d.rectangle((0,0, PANEL_W-1, PANEL_H-1), outline=(255,0,0))
        d.line((0,0, PANEL_W, PANEL_H), fill=(0,255,0))
        d.text((10, 10), "TEST PATTERN", font=self.font, fill=(0,0,255))
        return img
    
    def draw_pairing_screen(self):
        img = Image.new("RGB", (PANEL_W, PANEL_H), (0,0,0)); d = ImageDraw.Draw(img)
        d.text((2, 2), "PAIR CODE:", font=self.font, fill=(255, 255, 0))
        d.text(((PANEL_W - d.textlength(self.pairing_code, font=self.big_font)) // 2, 12), self.pairing_code, font=self.big_font, fill=(255, 255, 255))
        return img

    def download_and_process_logo(self, url, size=(24,24)):
        if not url: return
        cache_key = f"{url}_{size}"
        if cache_key in self.logo_cache: return
        try:
            filename = f"{hashlib.md5(url.encode()).hexdigest()}_{size[0]}x{size[1]}.png"
            local = os.path.join(ASSETS_DIR, filename)
            if os.path.exists(local):
                self.logo_cache[cache_key] = Image.open(local).convert("RGBA"); return
            
            r = requests.get(url, timeout=5)
            if r.status_code == 200:
                img = Image.open(io.BytesIO(r.content)).convert("RGBA")
                img.thumbnail(size, Image.Resampling.LANCZOS)
                final = Image.new("RGBA", size, (0,0,0,0))
                final.paste(img, ((size[0]-img.width)//2, (size[1]-img.height)//2))
                final.save(local, "PNG")
                self.logo_cache[cache_key] = final
        except: pass

    def get_logo(self, url, size=(24,24)):
        return self.logo_cache.get(f"{url}_{size}")

    def draw_arrow(self, d, x, y, is_up, color):
        if is_up: d.polygon([(x+2, y), (x, y+4), (x+4, y+4)], fill=color)
        else: d.polygon([(x, y), (x+4, y), (x+2, y+4)], fill=color)

    # --- MUSIC HELPERS ---
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
        bar_count = 16
        bar_w = 2
        gap = 3
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
                target_h = 2.0 # Flatline when paused

            self.viz_heights[i] += (target_h - self.viz_heights[i]) * 0.25
            
            h_int = int(self.viz_heights[i])
            start_y = center_y - (h_int // 2)
            bx = x + (i * (bar_w + gap))
            draw.rectangle((bx, start_y, bx+bar_w-1, start_y + h_int), fill=grad_colors[i])

    def draw_spotify_logo(self, d, x, y):
        d.ellipse((x, y, x+12, y+12), fill=self.dominant_color)
        d.arc((x+3, y+3, x+9, y+9), 190, 350, fill="black", width=1)
        d.arc((x+3, y+5, x+9, y+11), 190, 350, fill="black", width=1)
        d.arc((x+4, y+7, x+8, y+12), 190, 350, fill="black", width=1)

    def draw_scrolling_text(self, canvas, text, font, x, y, max_width, scroll_pos, color="white"):
        """Helper to draw scrolling text with taller buffer to prevent clipping"""
        text = str(text).strip() # Clean text of trailing spaces
        
        # Create a temp draw object just to measure text length
        temp_d = ImageDraw.Draw(canvas)
        text_w = temp_d.textlength(text, font=font)
        
        # Ensure strict integers for coordinates and dimensions
        max_width = int(max_width)
        x = int(x)
        y = int(y)

        # If text fits (add a 2px buffer to ensure it doesn't clip at the exact edge), draw static
        if text_w <= (max_width - 2):
            temp_d.text((x, y), text, font=font, fill=color)
            return

        # If scrolling needed
        GAP = 40
        total_loop = text_w + GAP
        current_offset = scroll_pos % total_loop
        
        # Create a temp image that is TALLER than font to catch descenders (32px to be safe)
        txt_img = Image.new("RGBA", (max_width, 32), (0,0,0,0))
        d_txt = ImageDraw.Draw(txt_img)
        
        # Draw first copy (Cast coordinates to int to prevent rendering errors)
        d_txt.text((int(-current_offset), 0), text, font=font, fill=color)
        
        # Draw second copy for seamless scrolling if the gap is visible
        if (-current_offset + text_w) < max_width:
             d_txt.text((int(-current_offset + total_loop), 0), text, font=font, fill=color)
        
        # Paste onto main image
        canvas.paste(txt_img, (x, y), txt_img)

    def draw_music_card(self, game):
        # 384px wide fixed canvas
        img = Image.new("RGBA", (PANEL_W, 32), (0, 0, 0, 255))
        d = ImageDraw.Draw(img)
        
        # Strip text to ensure accurate length measurement
        artist = str(game.get('home_abbr', 'Unknown')).strip()
        song = str(game.get('away_abbr', 'Unknown')).strip()
        cover_url = game.get('home_logo')
        
        # --- CONNECTION & PAUSE LOGIC ---
        # 1. Check if user manually paused
        is_playing = game.get('is_playing', True)
        if "paused" in str(game.get('status', '')).lower(): is_playing = False
        
        # 2. Check if connection is lost (stale data > 5 seconds)
        last_rx = game.get('_received_at', 0)
        time_since_rx = time.time() - last_rx
        if time_since_rx > 5.0: # [OPTIMIZED] Increased timeout from 5s to 30s
            is_playing = False 

        # Parse duration
        status_str = str(game.get('status', '0:00 / 0:00'))
        parts = status_str.split(' / ')
        curr_str = parts[0] if len(parts) > 0 else "0:00"
        dur_str = parts[1] if len(parts) > 1 else "0:00"
        
        def time_to_sec(s):
            try:
                m, sec = s.split(':')
                return int(m) * 60 + int(sec)
            except: return 1
        
        total_dur = time_to_sec(dur_str)
        curr_dur = time_to_sec(curr_str)
        
        # Physics Update using dt
        now = time.time()
        dt = now - self.last_frame_time
        self.last_frame_time = now
        
        # ONLY ANIMATE IF PLAYING AND CONNECTION GOOD
        if is_playing:
            self.vinyl_rotation = (self.vinyl_rotation - (100.0 * dt)) % 360
            self.text_scroll_pos += (15.0 * dt)
            # Reset scroll pos if it gets absurdly high to prevent float errors
            if self.text_scroll_pos > 1000000: self.text_scroll_pos = 0
        
        # 1. Update Cover
        if cover_url != self.last_cover_url:
            self.last_cover_url = cover_url
            self.vinyl_cache = None
            if cover_url:
                try:
                    r = requests.get(cover_url, timeout=1)
                    raw = Image.open(io.BytesIO(r.content)).convert("RGBA")
                    self.extract_colors_and_spindle(raw)
                    raw = raw.resize((self.COVER_SIZE, self.COVER_SIZE))
                    output = ImageOps.fit(raw, (self.COVER_SIZE, self.COVER_SIZE), centering=(0.5, 0.5))
                    output.putalpha(self.vinyl_mask)
                    self.vinyl_cache = output
                except: pass

        # 2. Draw Vinyl
        composite = self.scratch_layer.copy()
        if self.vinyl_cache: 
            offset = (self.VINYL_SIZE - self.COVER_SIZE) // 2
            composite.paste(self.vinyl_cache, (offset, offset), self.vinyl_cache)
        
        draw_comp = ImageDraw.Draw(composite)
        draw_comp.ellipse((22, 22, 28, 28), fill="#222")
        draw_comp.ellipse((23, 23, 27, 27), fill=self.spindle_color)

        rotated = composite.rotate(self.vinyl_rotation, resample=Image.Resampling.BICUBIC)
        img.paste(rotated, (4, -9), rotated)

        # 3. Text Section
        TEXT_START_X = 60
        # Safe text area width before hitting visualizer
        TEXT_AREA_W = 188 
        
        # Draw Song Name (y=0) - Pass 'img' (canvas), NOT 'd'
        self.draw_scrolling_text(img, song, self.medium_font, TEXT_START_X, 0, TEXT_AREA_W, self.text_scroll_pos, "white")
        
        # Draw Artist Name (y=16) - Pass 'img' (canvas), NOT 'd'
        self.draw_spotify_logo(d, TEXT_START_X, 15)
        self.draw_scrolling_text(img, artist, self.tiny, TEXT_START_X + 16, 17, 172, self.text_scroll_pos, (180, 180, 180))

        # 5. Viz (Pass is_playing status)
        self.render_visualizer(d, 248, 6, 80, 20, is_playing=is_playing)

        # 6. Time & Bar
        remaining_seconds = max(0, total_dur - curr_dur)
        rem_str = f"- {remaining_seconds//60}:{remaining_seconds%60:02}"
        w_time = d.textlength(rem_str, font=self.micro)
        d.text((PANEL_W - w_time - 5, 10), rem_str, font=self.micro, fill="white")
        
        pct = min(1.0, curr_dur / max(1, total_dur))
        d.rectangle((0, 31, int(PANEL_W * pct), 31), fill=self.dominant_color)
        
        return img

    # --- SPORTS HELPER DRAWING FUNCTIONS ---
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
        x_off = start_x; 
        if len(results) > 0: x_off -= 2 
        for res in display_results:
            if res == 'pending': draw.rectangle((x_off, y, x_off+1, y+1), outline=(60,60,60))
            elif res == 'miss': draw.point((x_off, y), fill=(255,0,0)); draw.point((x_off+1, y+1), fill=(255,0,0))
            elif res == 'goal': draw.rectangle((x_off, y, x_off+1, y+1), fill=(0,255,0))
            x_off += 4

    def draw_baseball_hud(self, draw, x, y, b, s, o):
        draw.point((x-4, y), fill=(150,150,150)); draw.point((x-3, y), fill=(150,150,150)); draw.point((x-4, y+1), fill=(150,150,150)); draw.point((x-3, y+2), fill=(150,150,150)); draw.point((x-4, y+2), fill=(150,150,150))
        draw.line((x-4, y+3, x-4, y+5), fill=(150,150,150)); draw.point((x-3, y+3), fill=(150,150,150)); draw.point((x-3, y+4), fill=(150,150,150)); draw.point((x-3, y+5), fill=(150,150,150))
        draw.rectangle((x-4, y+6, x-3, y+7), outline=(150,150,150))
        for i in range(2): draw.rectangle((x+(i*4), y, x+(i*4)+1, y+1), fill=((255, 0, 0) if i < s else (40, 40, 40)))
        for i in range(3): draw.rectangle((x+(i*4), y+3, x+(i*4)+1, y+4), fill=((0, 255, 0) if i < b else (40, 40, 40)))
        for i in range(2): draw.rectangle((x+(i*4), y+6, x+(i*4)+1, y+7), fill=((255, 100, 0) if i < o else (40, 40, 40)))

    def shorten_status(self, status):
        if not status: return ""
        s = str(status).upper().replace(" - ", " ").replace("FINAL", "FINAL").replace("/OT", " OT").replace("HALFTIME", "HALF")
        s = s.replace("1ST", "P1").replace("2ND", "P2").replace("3RD", "P3").replace("4TH", "P4").replace("FULL TIME", "FT")
        replacements = ["P1", "P2", "P3", "P4", "Q1", "Q2", "Q3", "Q4", "OT"]
        for r in replacements: s = s.replace(f"{r} ", f"{r}~")
        return s

    # --- DYNAMIC STOCK CARD RENDERER ---
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
            else: pass
        except Exception as e: print(f"Render Err: {e}")
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
            header_w = len(t_name) * 4
            hx = (64 - header_w) // 2
            draw_tiny_text(d, hx, 1, t_name, (220, 220, 220))
            leaders = game.get('leaders', [])
            if not isinstance(leaders, list): leaders = []
            y_off = 10; row_step = 8 
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
                score_w = len(display_score) * 4
                draw_tiny_text(d, 63 - score_w, y_off, display_score, (255, 100, 100))
                y_off += 8
        except Exception as e: return Image.new("RGBA", (64, 32), (0, 0, 0, 255))
        return img

    def draw_weather_pixel_art(self, d, icon_name, x, y):
        icon = str(icon_name).lower()
        SUN_Y = (255, 200, 0); CLOUD_W = (200, 200, 200); RAIN_B = (60, 100, 255); SNOW_W = (255, 255, 255)
        if 'sun' in icon or 'clear' in icon:
            d.ellipse((x+2, y+2, x+12, y+12), fill=SUN_Y)
            rays = [(x+7, y), (x+7, y+14), (x, y+7), (x+14, y+7), (x+2, y+2), (x+12, y+2), (x+2, y+12), (x+12, y+12)]
            for rx, ry in rays: d.point((rx, ry), fill=SUN_Y)
        elif 'rain' in icon or 'drizzle' in icon:
            d.ellipse((x+2, y+2, x+14, y+10), fill=CLOUD_W)
            d.line((x+4, y+11, x+3, y+14), fill=RAIN_B); d.line((x+8, y+11, x+7, y+14), fill=RAIN_B); d.line((x+12, y+11, x+11, y+14), fill=RAIN_B)
        elif 'snow' in icon:
            d.ellipse((x+2, y+2, x+14, y+10), fill=CLOUD_W)
            d.point((x+4, y+12), fill=SNOW_W); d.point((x+8, y+14), fill=SNOW_W); d.point((x+12, y+12), fill=SNOW_W); d.point((x+6, y+15), fill=SNOW_W)
        elif 'storm' in icon or 'thunder' in icon:
            d.ellipse((x+2, y+2, x+14, y+10), fill=(100, 100, 100))
            bolt = [(x+8, y+10), (x+6, y+13), (x+9, y+13), (x+7, y+16)]; d.line(bolt, fill=SUN_Y, width=1)
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
        except: return (100, 100, 100)

    def draw_weather_detailed(self, game):
        # 384px wide fixed canvas
        img = Image.new("RGBA", (384, 32), (0, 0, 0, 255))
        d = ImageDraw.Draw(img)
        
        sit = game.get('situation', {})
        stats = sit.get('stats', {})
        forecast = sit.get('forecast', []) 
        
        # --- LEFT SIDE: CURRENT CONDITIONS (0-120px) ---
        cur_icon = sit.get('icon', 'cloud')
        self.draw_weather_pixel_art(d, cur_icon, 4, 8) 
        
        location_name = str(game.get('away_abbr', 'CITY')).upper()
        d.text((28, -2), location_name, font=self.tiny, fill=(255, 255, 255))
        
        # Temp F (Moved to y=8)
        temp_f = str(game.get('home_abbr', '00')).replace('°', '')
        f_str = f"{temp_f}°F"
        d.text((28, 8), f_str, font=self.big_font, fill=(255, 255, 255))
        
        # AQI and UV (Moved to y=20)
        aqi_val = stats.get('aqi', '0')
        aqi_col = self.get_aqi_color(aqi_val)
        uv_val = str(stats.get('uv', '0'))
        
        # AQI Badge (Solid Box)
        d.rectangle((28, 20, 70, 27), fill=aqi_col)
        d.text((30, 19), f"AQI:{aqi_val}", font=self.micro, fill=(0,0,0))

        # UV Line
        d.text((75, 19), f"UV:{uv_val}", font=self.micro, fill=(255, 100, 255))

        # --- SEPARATOR ---
        d.line((115, 2, 115, 30), fill=(50, 50, 50))

        # --- RIGHT SIDE: FORECAST (120px - 384px) ---
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
            
            # Side-by-side Temps (Using NANO font)
            d.text((x_cursor, 22), f"{hi}", font=self.nano, fill=(255, 100, 100))
            d.text((x_cursor + 14, 22), "/", font=self.nano, fill=(100, 100, 100))
            d.text((x_cursor + 20, 22), f"{lo}", font=self.nano, fill=(100, 100, 255))
            
            x_cursor += 50 

        return img

    def draw_boot_clock(self):
        """Simple standby clock (Not the modern clock app)"""
        img = Image.new("RGB", (PANEL_W, PANEL_H), (0,0,0))
        d = ImageDraw.Draw(img)
        # Simple HH:MM:SS
        now = datetime.now().strftime("%I:%M:%S")
        # Draw using standard font, centered
        w = d.textlength(now, font=self.huge_font)
        d.text(((PANEL_W - w)/2, 4), now, font=self.huge_font, fill=(100, 100, 100))
        return img

    def draw_clock_modern(self):
        """Centered HUGE time with full date and bottom progress bar"""
        img = Image.new("RGBA", (PANEL_W, 32), (0, 0, 0, 255))
        d = ImageDraw.Draw(img)
        d.rectangle((0,0, PANEL_W, 32), fill=(0,0,0,255))
        
        now = datetime.now()
        
        # 1. Date: FULLY WRITTEN OUT (Top Center)
        date_str = now.strftime("%A %B %d").upper()
        w_date = d.textlength(date_str, font=self.tiny)
        d.text(((PANEL_W - w_date)/2, 0), date_str, font=self.tiny, fill=(200, 200, 200))

        # 2. Time: HH:MM:SS (Huge, Center) - Moved down to y=14
        time_str = now.strftime("%I:%M:%S").lstrip('0')
        w_time = d.textlength(time_str, font=self.clock_giant)
        d.text(((PANEL_W - w_time)/2, 14), time_str, font=self.clock_giant, fill=(255, 255, 255))
        
        # 3. Seconds Bar (Bottom, Edge to Edge)
        sec_val = now.second
        ms_val = now.microsecond
        total_seconds = sec_val + (ms_val / 1000000.0)
        bar_width = int((total_seconds / 60.0) * PANEL_W)
        
        d.rectangle((0, 31, PANEL_W, 31), fill=(30, 30, 30)) # Grey Background
        d.rectangle((0, 31, bar_width, 31), fill=(0, 200, 255)) # Blue Progress

        return img

    def get_game_hash(self, game):
        # Unique hash to cache rendered images
        s = f"{game.get('id')}_{game.get('home_score')}_{game.get('away_score')}_{game.get('situation', {}).get('change')}"
        return hashlib.md5(s.encode()).hexdigest()

    def draw_single_game(self, game):
        game_hash = self.get_game_hash(game)
        
        # [NEW] Check for Music Type first
        if game.get('type') == 'music' or game.get('sport') == 'music':
            # Note: Music is dynamic and high-frame-rate, so we generally 
            # don't cache it, or cache it very briefly.
            return self.draw_music_card(game)

        if game.get('type') != 'weather' and game.get('sport') != 'clock':
             if game_hash in self.game_render_cache: return self.game_render_cache[game_hash]
        
        if game.get('type') == 'weather':
            img = self.draw_weather_detailed(game)
            self.game_render_cache[game_hash] = img
            return img

        if game.get('sport') == 'clock':
            return self.draw_clock_modern()
        
        # Route to stock renderer
        if game.get('type') == 'stock_ticker' or game.get('sport', '').startswith('stock'): 
            img = self.draw_stock_card(game)
            self.game_render_cache[game_hash] = img
            return img
        
        if game.get('type') == 'leaderboard':
            img = self.draw_leaderboard_card(game)
            self.game_render_cache[game_hash] = img
            return img
        
        # --- MERGED SPORTS CARD RENDERER ---
        img = Image.new("RGBA", (64, 32), (0, 0, 0, 0)) 
        if not isinstance(game, dict): return img
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
            
            # Force small logos if football active or long score or indicators present
            is_wide = ((is_football and is_active) or len(a_score) >= 2 or len(h_score) >= 2 or has_indicator)
            
            # [MARCH MADNESS OVERRIDE]: Always use full size logos
            if is_march_madness:
                is_wide = False
            
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

            status = self.shorten_status(game.get('status', ''))
            st_x = (64 - len(status.replace('~', ''))*5) // 2
            draw_hybrid_text(d, st_x, 25, status, (180, 180, 180))

            # === MARCH MADNESS SEED INDICATORS ===
            if is_march_madness:
                h_seed = str(game.get('home_seed', ''))
                a_seed = str(game.get('away_seed', ''))
                
                # Draw Away Seed (Left - Centered under 24px logo)
                if a_seed:
                    # Center of 24px logo (starting at 0) is 12
                    # Font is 4px wide + 1px gap per char
                    w = (len(a_seed) * 4) + (max(0, len(a_seed) - 1))
                    sx = 12 - (w // 2)
                    draw_tiny_text(d, sx, 26, a_seed, (200, 200, 200))

                # Draw Home Seed (Right - Centered under 24px logo)
                if h_seed:
                    # Center of 24px logo (starting at 40) is 52
                    w = (len(h_seed) * 4) + (max(0, len(h_seed) - 1))
                    sx = 52 - (w // 2)
                    draw_tiny_text(d, sx, 26, h_seed, (200, 200, 200))

            # === SHOOTOUT INDICATORS ===
            elif shootout:
                away_so = shootout.get('away', []) if isinstance(shootout, dict) else []
                home_so = shootout.get('home', []) if isinstance(shootout, dict) else []
                if is_soccer:
                    self.draw_soccer_shootout(d, away_so, 2, 26)
                    self.draw_soccer_shootout(d, home_so, 46, 26)
                else:
                    self.draw_shootout_indicators(d, away_so, 2, 26)
                    self.draw_shootout_indicators(d, home_so, 46, 26)

            # === STANDARD INDICATORS ===
            elif is_active and not is_march_madness:
                icon_y = logo_y + logo_size[1] + 3; tx = -1; side = None
                if (is_football or is_baseball or is_soccer) and poss: side = poss
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
                    elif is_baseball:
                        d.ellipse((tx-3, icon_y, tx+3, icon_y+6), fill='white')
                        d.point((tx-1, icon_y+2), fill='red'); d.point((tx, icon_y+3), fill='red'); d.point((tx+1, icon_y+4), fill='red')
                    elif is_hockey: self.draw_hockey_stick(d, tx+2, icon_y+5, 3) 
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
                    bases = [(31,2), (27,6), (35,6)] # 2nd, 3rd, 1st
                    active = [sit.get('onSecond'), sit.get('onThird'), sit.get('onFirst')]
                    for i, p in enumerate(bases): 
                        color = (255,255,150) if active[i] else (45,45,45)
                        d.rectangle((p[0], p[1], p[0]+3, p[1]+3), fill=color)
                    b_count = int(sit.get('balls', 0)); s_count = int(sit.get('strikes', 0)); o_count = int(sit.get('outs', 0))
                    if poss_side == "away": self.draw_baseball_hud(d, 54, 22, b_count, s_count, o_count)
                    elif poss_side == "home": self.draw_baseball_hud(d, 2, 22, b_count, s_count, o_count)
                    else: self.draw_baseball_hud(d, 54, 22, b_count, s_count, o_count)

                elif is_football:
                    dd = sit.get('downDist', '')
                    if dd: 
                        s_dd = dd.split(' at ')[0].replace("1st", "1st")
                        w = d.textlength(s_dd, font=self.micro)
                        d.text(((64-w)/2, -1), s_dd, font=self.micro, fill=(0,255,0))
                if is_football and sit.get('isRedZone'): d.rectangle((0, 0, 63, 31), outline=(255, 0, 0), width=1)
        except Exception as e: return img 
        
        self.game_render_cache[game_hash] = img
        return img

    def get_item_width(self, game):
        # Helper to know how wide an item is in pixels
        t = game.get('type')
        s = game.get('sport')
        
        # [NEW] Music width is typically full panel
        if t == 'music' or s == 'music': return 384
        
        if t == 'stock_ticker' or (s and s.startswith('stock')): return 128
        if t == 'weather': return 384 # 6 panels
        return 64 # Standard scoreboard/leaderboard/clock

    def parse_time_guess(self, val):
        # Try several common formats; fallback None on failure
        try:
            if isinstance(val, (int, float)):
                return float(val)
            if not isinstance(val, str):
                return None
            s = val.strip()
            if not s:
                return None
            if s.isdigit():
                return float(s)
            # ISO-ish
            try:
                dt = datetime.fromisoformat(s.replace('Z', '+00:00'))
                return dt.timestamp()
            except: pass
            # Common AM/PM without date; assume today
            for fmt in ["%I:%M %p", "%I:%M:%S %p", "%H:%M", "%H:%M:%S"]:
                try:
                    dt = datetime.strptime(s, fmt)
                    today = datetime.now()
                    dt = dt.replace(year=today.year, month=today.month, day=today.day)
                    return dt.timestamp()
                except: pass
        except: return None
        return None

    def get_game_start_key(self, game):
        # Extract a sortable timestamp; fall back to a stable deterministic ordering
        ts_fields = ['start_time', 'start', 'time', 'ts', 'timestamp', 'date', 'startTime', 'start_time_utc', 'game_time', 'gameTime', 'kickoff', 'tipoff', 'puck_drop']
        for f in ts_fields:
            val = game.get(f)
            parsed = self.parse_time_guess(val)
            if parsed is not None:
                return parsed
        return float('inf')

    def start_static_display(self):
        # Show next static card (clock/weather/MUSIC) without scrolling
        if not self.static_items: return False
        game = self.static_items[self.static_index % len(self.static_items)]
        self.static_index += 1
        self.static_current_game = game
        self.static_current_image = self.draw_single_game(game)
        self.static_until = time.time() + PAGE_HOLD_TIME
        self.showing_static = True
        return True

    def build_seamless_strip(self, playlist):
        if not playlist: return None
        safe_playlist = playlist[:60]
        total_w = 0
        for g in safe_playlist:
            total_w += self.get_item_width(g)
        
        # Create strip with padding for seamless looping
        strip = Image.new("RGBA", (total_w + PANEL_W, PANEL_H), (0,0,0,255))
        
        x = 0
        for g in safe_playlist:
            img = self.draw_single_game(g)
            strip.paste(img, (x, 0), img)
            x += img.width
            
        bx = x; i = 0
        while bx < total_w + PANEL_W and len(safe_playlist) > 0:
            g = safe_playlist[i % len(safe_playlist)]
            img = self.draw_single_game(g)
            strip.paste(img, (bx, 0), img)
            bx += img.width
            i += 1
            
        return strip

    def perform_update(self):
        print("⬇️ STARTING SOFTWARE UPDATE...")
        # Show visual indicator
        img = Image.new("RGB", (PANEL_W, PANEL_H), (0,0,0))
        d = ImageDraw.Draw(img)
        d.text((2, 10), "UPDATING SYSTEM...", font=self.medium_font, fill=(0, 255, 0))
        self.update_display(img)
        
        try:
            # Run git pull. Ensure we are in the script's directory.
            repo_dir = os.path.dirname(os.path.abspath(__file__))
            result = subprocess.run(['git', 'pull'], cwd=repo_dir, capture_output=True, text=True)
            
            if result.returncode == 0:
                d.rectangle((0,0, PANEL_W, PANEL_H), fill=(0,0,0))
                d.text((2, 10), "UPDATE SUCCESS!", font=self.medium_font, fill=(0, 255, 0))
                d.text((2, 22), "REBOOTING...", font=self.tiny, fill=(100, 100, 100))
                self.update_display(img)
                time.sleep(3)
                subprocess.run(['reboot'])
            else:
                print(f"Update Failed: {result.stderr}")
                d.rectangle((0,0, PANEL_W, PANEL_H), fill=(0,0,0))
                d.text((2, 2), "UPDATE FAILED", font=self.medium_font, fill=(255, 0, 0))
                self.update_display(img)
                time.sleep(5)
                # Resume normal operation
                return
                
        except Exception as e:
            print(f"Update Exception: {e}")

    def render_loop(self):
        strip_offset = 0.0
        
        while self.running:
            try:
                if self.showing_static:
                    # Hold static pages (clock/weather) without movement
                    if self.static_current_game:
                        game_type = str(self.static_current_game.get('type', ''))
                        sport = str(self.static_current_game.get('sport','')).lower()
                        
                        # [NEW] ANIMATED STATIC ITEMS (Clock & Music)
                        # Need high refresh rate for these
                        if sport.startswith('clock') or game_type == 'music' or sport == 'music':
                            
                            # [OPTIMIZED] SMART SWITCHER LOGIC
                            # Efficiently check if music exists in the live list without full loop overhead
                            if game_type == 'music' or sport == 'music':
                                live_music_item = next((i for i in self.static_items if i.get('id') == 'spotify_now'), None)
                                
                                if live_music_item:
                                    self.static_current_game = live_music_item # Update with fresh data
                                    self.static_until = time.time() + 1.0      # Keep alive
                                else:
                                    # Music item is gone from the feed -> EXIT IMMEDIATELY
                                    self.showing_static = False
                                    self.static_current_image = None
                                    self.static_current_game = None
                                    continue

                            self.static_current_image = self.draw_single_game(self.static_current_game)
                            # Render faster for animation smoothness
                            if self.static_current_image:
                                self.update_display(self.static_current_image)
                            
                            if time.time() >= self.static_until:
                                self.showing_static = False
                                self.static_current_image = None
                                self.static_current_game = None
                            
                            # Fast sleep for animation
                            time.sleep(0.03) 
                            continue

                    # Standard Static items (Weather) - Slow refresh
                    if self.static_current_image:
                        self.update_display(self.static_current_image)
                    if time.time() >= self.static_until:
                        self.showing_static = False
                        self.static_current_image = None
                        self.static_current_game = None
                    time.sleep(0.1)
                    continue

                if self.is_pairing:
                    self.update_display(self.draw_pairing_screen()); time.sleep(0.5); continue
                    
                if self.brightness <= 0.01:
                    self.matrix.Clear(); time.sleep(1.0); continue
                
                # --- SEAMLESS UPDATE LOGIC ---
                if self.bg_strip_ready:
                    update_applied = False
                    
                    # SCENARIO A: We have actual data
                    if self.bg_strip is not None:
                        # Case 1: Startup (Transition from Idle Clock -> Data)
                        if self.active_strip is None:
                            self.active_strip = self.bg_strip
                            self.games = self.new_games_list 
                            strip_offset = 0
                            update_applied = True
                        else:
                            # Case 2: Mid-scroll update
                            current_x = int(strip_offset)
                            accum_w = 0
                            visible_item_id = None
                            pixel_delta = 0
                            
                            for g in self.games: # Uses old list
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
                            
                            if new_offset >= 0:
                                self.active_strip = self.bg_strip
                                self.games = self.new_games_list
                                strip_offset = float(new_offset)
                                update_applied = True
                            else:
                                # Fallback: Force update IMMEDIATELY if no seamless match
                                # (Removes delay if list changes significantly)
                                self.active_strip = self.bg_strip
                                self.games = self.new_games_list
                                strip_offset = 0.0 # Reset to start to show new list
                                update_applied = True

                    # SCENARIO B: We have NO data (Playlist empty)
                    else:
                        self.active_strip = None # This triggers the fallback below
                        update_applied = True
                    
                    # ONLY consume the update flag if we actually swapped the strip
                    if update_applied:
                        self.bg_strip_ready = False 

                if self.active_strip:
                    total_w = self.active_strip.width - PANEL_W
                    if total_w <= 0: total_w = 1
                    
                    if strip_offset >= total_w:
                        strip_offset = 0
                        if self.static_items:
                            if self.start_static_display(): continue
                        
                    x = int(strip_offset)
                    view = self.active_strip.crop((x, 0, x + PANEL_W, PANEL_H))
                    self.update_display(view)
                    
                    strip_offset += 1
                    time.sleep(self.scroll_sleep)
                else:
                    # === FALLBACK MODE: SHOW STATIC PAGES IF AVAILABLE, ELSE BOOT CLOCK ===
                    if self.static_items and self.start_static_display():
                        continue
                    boot_clock_img = self.draw_boot_clock()
                    self.update_display(boot_clock_img)
                    time.sleep(0.5) 
                    
            except Exception as e:
                print(f"Render Loop Crash Prevented: {e}")
                traceback.print_exc()
                time.sleep(1)

    def poll_backend(self):
        last_hash = ""
        # Fix for "Offline" status caused by SSL certs on devices with wrong dates
        requests.packages.urllib3.disable_warnings()
        
        # Use a Session to reuse TCP connections (Keep-Alive)
        session = requests.Session()

        while self.running:
            try:
                url = f"{BACKEND_URL}/data?id={self.device_id}"
                
                # Use session.get to reuse the connection
                r = session.get(url, timeout=10, verify=False)
                data = r.json()
                
                # ==========================================
                # COMMAND LISTENER
                # ==========================================
                global_conf = data.get('global_config', {})
                if global_conf.get('reboot') is True:
                    print("⚠️ REBOOT COMMAND RECEIVED")
                    self.matrix.Clear()
                    subprocess.run(['reboot'])
                    sys.exit(0)
                
                if global_conf.get('update') is True:
                    self.perform_update()
                # ==========================================

                if data.get('status') == 'pairing':
                    self.is_pairing = True
                    self.pairing_code = data.get('code')
                    self.games = []
                    time.sleep(2); continue
                else: self.is_pairing = False
                
                content = data.get('content', {})
                new_games = content.get('sports', [])

                for idx, g in enumerate(new_games):
                    if isinstance(g, dict): 
                        g['_orig_index'] = idx
                        # [NEW] Add reception timestamp for stale check
                        g['_received_at'] = time.time()

                new_games.sort(key=lambda x: (self.get_game_start_key(x), x.get('_orig_index', 0), x.get('sport', ''), x.get('id', '')))

                static_items = []
                scrolling_items = []
                for g in new_games:
                    sport = str(g.get('sport', '')).lower()
                    
                    # [NEW] Add 'music' to the list of static items
                    if g.get('type') == 'weather' or sport == 'clock' or sport.startswith('clock') or g.get('type') == 'music':
                        static_items.append(g)
                    else:
                        scrolling_items.append(g)
                
                # Create hash based on Content + Settings to detect changes
                current_hash = hashlib.md5(json.dumps({'g': new_games, 'c': data.get('local_config')}, sort_keys=True).encode()).hexdigest()
                
                if current_hash != last_hash:
                    print(f"Data Update: {len(scrolling_items)} sports")
                    logos = []
                    for g in scrolling_items:
                        if g.get('home_logo'): 
                            logos.append((g.get('home_logo'), (24, 24)))
                            logos.append((g.get('home_logo'), (16, 16)))
                        if g.get('away_logo'): 
                            logos.append((g.get('away_logo'), (24, 24)))
                            logos.append((g.get('away_logo'), (16, 16)))
                    
                    unique_logos = list(set(logos))
                    fs = [self.executor.submit(self.download_and_process_logo, u, s) for u, s in unique_logos]
                    concurrent.futures.wait(fs)
                    
                    self.brightness = float(data.get('local_config', {}).get('brightness', 100)) / 100.0
                    self.scroll_sleep = data.get('local_config', {}).get('scroll_speed', 0.05)
                    self.inverted = data.get('local_config', {}).get('inverted', False)
                    
                    self.new_games_list = scrolling_items 
                    self.static_items = static_items
                    self.static_index = 0
                    
                    if not scrolling_items:
                        self.bg_strip = None
                    else:
                        self.bg_strip = self.build_seamless_strip(scrolling_items)
                        
                    self.bg_strip_ready = True
                    last_hash = current_hash
                    self.game_render_cache.clear()
            
            except Exception as e:
                print(f"Poll Error: {e}")
                time.sleep(1)
            
            # Sleep removed to allow immediate polling

if __name__ == "__main__":
    app = TickerStreamer()
    try:
        while True: time.sleep(1)
    except KeyboardInterrupt:
        print("Stopping...")
