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
from datetime import datetime
from PIL import Image, ImageDraw, ImageFont
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
REFRESH_RATE = 3
ID_FILE_PATH = "/boot/ticker_id.txt"
ID_FILE_FALLBACK = "ticker_id.txt"
ASSETS_DIR = os.path.expanduser("~/ticker/assets")

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
        
        # Clock Font: 32px
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
        
        self.executor = concurrent.futures.ThreadPoolExecutor(max_workers=4)

        threading.Thread(target=self.poll_backend, daemon=True).start()
        threading.Thread(target=self.render_loop, daemon=True).start()

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
            is_active = (game.get('state') == 'in')
            sit = game.get('situation', {}) or {} 
            poss = sit.get('possession')
            shootout = sit.get('shootout')
            
            a_score = str(game.get('away_score', ''))
            h_score = str(game.get('home_score', ''))
            has_indicator = is_active and (poss or sit.get('powerPlay') or sit.get('emptyNet'))
            # Force small logos if football active or long score or indicators present
            is_wide = ((is_football and is_active) or len(a_score) >= 2 or len(h_score) >= 2 or has_indicator)
            
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

            # === SHOOTOUT INDICATORS ===
            if shootout:
                away_so = shootout.get('away', []) if isinstance(shootout, dict) else []
                home_so = shootout.get('home', []) if isinstance(shootout, dict) else []
                if is_soccer:
                    self.draw_soccer_shootout(d, away_so, 2, 26)
                    self.draw_soccer_shootout(d, home_so, 46, 26)
                else:
                    self.draw_shootout_indicators(d, away_so, 2, 26)
                    self.draw_shootout_indicators(d, home_so, 46, 26)

            # === STANDARD INDICATORS ===
            elif is_active:
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
        if t == 'stock_ticker' or (s and s.startswith('stock')): return 128
        if t == 'weather': return 384 # 6 panels
        return 64 # Standard scoreboard/leaderboard/clock

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

    def render_loop(self):
        strip_offset = 0.0
        
        while self.running:
            try:
                if self.is_pairing:
                    self.update_display(self.draw_pairing_screen()); time.sleep(0.5); continue
                    
                if self.brightness <= 0.01:
                    self.matrix.Clear(); time.sleep(1.0); continue
                
                # --- SEAMLESS UPDATE LOGIC ---
                if self.bg_strip_ready:
                    # Case 1: Startup (no active strip) - Just take it
                    if self.active_strip is None:
                        self.active_strip = self.bg_strip
                        self.games = self.new_games_list # Update reference
                        self.bg_strip_ready = False
                        strip_offset = 0
                    
                    else:
                        # Case 2: Mid-scroll update
                        # Goal: Find the item currently at x=0 (left edge)
                        # and map it to the new list to find the new offset.
                        
                        current_x = int(strip_offset)
                        accum_w = 0
                        visible_item_id = None
                        pixel_delta = 0
                        
                        # 2a. Find visible item in CURRENT list
                        for g in self.games: # Uses old list
                            w = self.get_item_width(g)
                            if accum_w + w > current_x:
                                # Found the item spanning the left edge
                                visible_item_id = g.get('id')
                                pixel_delta = current_x - accum_w
                                break
                            accum_w += w
                        
                        # 2b. Find that item in NEW list
                        new_offset = -1
                        new_accum_w = 0
                        if visible_item_id:
                            for g in self.new_games_list:
                                w = self.get_item_width(g)
                                if g.get('id') == visible_item_id:
                                    new_offset = new_accum_w + pixel_delta
                                    break
                                new_accum_w += w
                        
                        # 2c. Execute Swap
                        if new_offset >= 0:
                            # Match found! Seamless transition.
                            self.active_strip = self.bg_strip
                            self.games = self.new_games_list
                            strip_offset = float(new_offset)
                            self.bg_strip_ready = False
                        else:
                            # Item removed or not found.
                            # Fallback: Wait for reset (standard logic)
                            if int(strip_offset) == 0:
                                self.active_strip = self.bg_strip
                                self.games = self.new_games_list
                                self.bg_strip_ready = False
                                strip_offset = 0

                if self.active_strip:
                    total_w = self.active_strip.width - PANEL_W
                    if total_w <= 0: total_w = 1
                    
                    # Wrap around logic for offset
                    if strip_offset >= total_w:
                        strip_offset = 0
                        
                    x = int(strip_offset)
                    view = self.active_strip.crop((x, 0, x + PANEL_W, PANEL_H))
                    self.update_display(view)
                    
                    strip_offset += 1
                    time.sleep(self.scroll_sleep)
                else:
                    time.sleep(0.1)
                    
            except Exception as e:
                print(f"Render Loop Crash Prevented: {e}")
                time.sleep(1)

    def poll_backend(self):
        last_hash = ""
        while self.running:
            try:
                url = f"{BACKEND_URL}/data?id={self.device_id}"
                r = requests.get(url, timeout=5)
                data = r.json()
                
                if data.get('status') == 'pairing':
                    self.is_pairing = True
                    self.pairing_code = data.get('code')
                    self.games = []
                    time.sleep(2); continue
                else: self.is_pairing = False
                
                content = data.get('content', {})
                new_games = content.get('sports', [])
                
                current_hash = str(new_games) + str(data.get('local_config'))
                if current_hash != last_hash:
                    logos = []
                    for g in new_games:
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
                    
                    # Prepare new data for the render thread
                    self.new_games_list = new_games # Store for mapping logic
                    self.bg_strip = self.build_seamless_strip(new_games)
                    self.bg_strip_ready = True
                    
                    last_hash = current_hash
                    self.game_render_cache.clear()
                    
            except Exception as e:
                print(f"Poll Error: {e}")
            time.sleep(REFRESH_RATE)

if __name__ == "__main__":
    app = TickerStreamer()
    try:
        while True: time.sleep(1)
    except KeyboardInterrupt:
        print("Stopping...")
