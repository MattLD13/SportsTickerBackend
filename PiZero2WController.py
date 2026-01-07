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
PANEL_W = 128
PANEL_H = 32
SETUP_SSID = "SportsTicker_Setup"
PAGE_HOLD_TIME = 8.0 
REFRESH_RATE = 3
ID_FILE_PATH = "/boot/ticker_id.txt"
ID_FILE_FALLBACK = "ticker_id.txt"
ASSETS_DIR = os.path.expanduser("~/ticker/assets")

# --- TINY PIXEL FONT (4x5) - USED FOR MOTORSPORTS ---
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
    "'": [0x4, 0x4, 0x0, 0x0, 0x0]
}

# --- HYBRID PIXEL FONT (4x6) - USED FOR GAME STATUS ---
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
        x_cursor += 4 
    return x_cursor - x

def draw_hybrid_text(draw, x, y, text, color):
    text = str(text).upper()
    x_cursor = x
    for char in text:
        if char == '~':
            x_cursor += 2
            continue
            
        bitmap = HYBRID_FONT_MAP.get(char, HYBRID_FONT_MAP[' '])
        for r, row_byte in enumerate(bitmap):
            if row_byte & 0x8: draw.point((x_cursor+0, y+r), fill=color)
            if row_byte & 0x4: draw.point((x_cursor+1, y+r), fill=color)
            if row_byte & 0x2: draw.point((x_cursor+2, y+r), fill=color)
            if row_byte & 0x1: draw.point((x_cursor+3, y+r), fill=color)
        x_cursor += 5 
    return x_cursor - x

def get_device_id():
    path_to_use = ID_FILE_PATH
    if not os.path.isfile(ID_FILE_PATH):
        try:
            test_uuid = str(uuid.uuid4())
            with open(ID_FILE_PATH, 'w') as f:
                f.write(test_uuid)
        except PermissionError:
            print(f"Warning: Cannot write to {ID_FILE_PATH}. Using local fallback.")
            path_to_use = ID_FILE_FALLBACK

    if os.path.exists(path_to_use):
        with open(path_to_use, 'r') as f:
            return f.read().strip()
    else:
        new_id = str(uuid.uuid4())
        try:
            with open(path_to_use, 'w') as f:
                f.write(new_id)
            print(f"Generated new ID: {new_id}")
            return new_id
        except Exception as e:
            print(f"CRITICAL: Could not save ID. {e}")
            return new_id

class WifiPortal:
    def __init__(self, matrix, font):
        self.matrix = matrix
        self.font = font
        self.app = Flask(__name__)
        self.html_template = """<html><body><h2>Connect Ticker</h2><form action="/connect" method="POST"><input type="text" name="ssid" placeholder="SSID"><br><input type="password" name="password" placeholder="Password"><br><button type="submit">Connect</button></form></body></html>"""
        
        @self.app.route('/')
        def home(): return render_template_string(self.html_template)
        
        @self.app.route('/connect', methods=['POST'])
        def connect():
            ssid = request.form['ssid']; pw = request.form['password']
            self.draw_status(f"CONNECTING:\n{ssid}")
            try: 
                subprocess.run(['nmcli', 'dev', 'wifi', 'connect', ssid, 'password', pw], check=True)
                return "Rebooting..."
            except: 
                return "Failed"
            finally: 
                time.sleep(2)
                subprocess.run(['reboot'])

    def check_internet(self):
        try: 
            socket.create_connection(("8.8.8.8", 53), timeout=3)
            return True
        except OSError: 
            return False

    def start_hotspot(self):
        subprocess.run(['nmcli', 'con', 'up', SETUP_SSID], capture_output=True)

    def draw_status(self, text):
        img = Image.new("RGB", (PANEL_W, PANEL_H), (0,0,0))
        d = ImageDraw.Draw(img)
        d.text((2, 2), text, font=self.font, fill=(255, 255, 0))
        self.matrix.SetImage(img.convert("RGB"))

    def run(self):
        if self.check_internet(): return True 
        self.draw_status(f"SETUP WIFI\n{SETUP_SSID}")
        self.start_hotspot()
        try:
            self.app.run(host='0.0.0.0', port=80) 
        except:
            pass

class TickerStreamer:
    def __init__(self):
        print("Starting Ticker System (Disk Cache Enabled)...")
        self.device_id = get_device_id()
        print(f"Device ID: {self.device_id}")

        # Ensure assets directory exists
        if not os.path.exists(ASSETS_DIR):
            try: os.makedirs(ASSETS_DIR)
            except Exception as e: print(f"Error creating asset dir: {e}")

        options = RGBMatrixOptions()
        options.rows = 32
        options.cols = 64
        options.chain_length = 2
        options.parallel = 1
        
        # === ZERO 2 W OPTIMIZATIONS ===
        options.hardware_mapping = 'regular'
        options.gpio_slowdown = 2  # <--- CHANGED TO 2
        
        # === ARTIFACT FIXES REMOVED ===
        options.show_refresh_rate = 0
        
        options.disable_hardware_pulsing = True
        options.drop_privileges = False 
        options.limit_refresh_rate_hz = 120
        
        self.matrix = RGBMatrix(options=options)

        # Cache font loading
        try: self.font = ImageFont.truetype("DejaVuSans-Bold.ttf", 10)
        except: self.font = ImageFont.load_default()
        
        try: self.tiny = ImageFont.truetype("DejaVuSans.ttf", 9) 
        except: self.tiny = ImageFont.load_default()
        
        try: self.micro = ImageFont.truetype("DejaVuSans.ttf", 7)
        except: self.micro = ImageFont.load_default()

        try: self.nano = ImageFont.truetype("DejaVuSans.ttf", 5)
        except: self.nano = ImageFont.load_default()
        
        try: self.big_font = ImageFont.truetype("DejaVuSans-Bold.ttf", 16)
        except: self.big_font = ImageFont.load_default()
        
        try: self.huge_font = ImageFont.truetype("DejaVuSans-Bold.ttf", 24)
        except: self.huge_font = self.big_font
        
        self.portal = WifiPortal(self.matrix, self.font)
        if not self.portal.check_internet(): self.portal.run() 
        
        self.games = []
        self.seamless_mode = False
        self.brightness = 0.5
        self.scroll_sleep = 0.05
        self.inverted = False
        self.test_pattern = False
        self.running = True
        self.logo_cache = {}
        self.game_render_cache = {} 
        self.anim_tick = 0
        
        self.is_pairing = False
        self.pairing_code = ""
        self.config_updated = False
        self.bg_strip = None
        self.active_strip = None
        self.bg_strip_ready = False
        
        self.executor = concurrent.futures.ThreadPoolExecutor(max_workers=2)

        threading.Thread(target=self.poll_backend, daemon=True).start()
        threading.Thread(target=self.render_loop, daemon=True).start()

    def update_display(self, pil_image):
        if self.test_pattern: pil_image = self.generate_test_pattern()
        if pil_image.mode != "RGB": img = pil_image.convert("RGB")
        else: img = pil_image

        val = self.brightness
        if val > 1.0: val = val / 100.0
        
        target_b = int(max(0, min(100, val * 100)))
        if self.matrix.brightness != target_b: self.matrix.brightness = target_b
        
        if self.inverted: img = img.rotate(180)
        self.matrix.SetImage(img)

    def generate_test_pattern(self):
        img = Image.new("RGB", (PANEL_W, PANEL_H), (0,0,0))
        d = ImageDraw.Draw(img)
        d.rectangle((0,0, PANEL_W-1, PANEL_H-1), outline=(255,0,0))
        d.text((10, 10), "TEST", font=self.font, fill=(0,0,255))
        return img
    
    def draw_pairing_screen(self):
        img = Image.new("RGB", (PANEL_W, PANEL_H), (0,0,0))
        d = ImageDraw.Draw(img)
        d.text((2, 2), "PAIR CODE:", font=self.font, fill=(255, 255, 0)) 
        code = self.pairing_code if self.pairing_code else "..."
        w = d.textlength(code, font=self.big_font)
        x = (PANEL_W - w) // 2
        d.text((x, 12), code, font=self.big_font, fill=(255, 255, 255))
        return img

    def download_and_process_logo(self, url, size=(24,24)):
        # === DISK CACHING LOGIC ===
        cache_key = f"{url}_{size}"
        if cache_key in self.logo_cache: return

        try:
            url_hash = hashlib.md5(url.encode()).hexdigest()
            filename = f"{url_hash}_{size[0]}x{size[1]}.png"
            local_path = os.path.join(ASSETS_DIR, filename)

            if os.path.exists(local_path):
                try:
                    loaded_img = Image.open(local_path).convert("RGBA")
                    self.logo_cache[cache_key] = loaded_img
                    return
                except:
                    pass

            r = requests.get(url, timeout=5)
            original = Image.open(io.BytesIO(r.content)).convert("RGBA")
            target_w, target_h = size
            check_img = original.resize((32, 32), Image.Resampling.NEAREST)
            rgb_img = check_img.convert("RGB")
            alpha = check_img.split()[-1]
            visible_pixels = 0; dark_pixels = 0
            
            width, height = check_img.size
            for y in range(height):
                for x in range(width):
                    if alpha.getpixel((x, y)) > 50:
                        visible_pixels += 1
                        r_val, g_val, b_val = rgb_img.getpixel((x, y))
                        if r_val < 60 and g_val < 60 and b_val < 60: dark_pixels += 1
            
            needs_outline = (visible_pixels > 0 and (dark_pixels / visible_pixels) > 0.40)
            final_img = Image.new("RGBA", size, (0,0,0,0))
            
            if needs_outline:
                icon_w, icon_h = target_w - 2, target_h - 2
                img_ratio = original.width / original.height
                target_ratio = icon_w / icon_h
                if img_ratio > target_ratio: new_w = icon_w; new_h = int(icon_w / img_ratio)
                else: new_h = icon_h; new_w = int(icon_h * img_ratio)
                
                resized_icon = original.resize((new_w, new_h), Image.Resampling.LANCZOS)
                center_x = (target_w - new_w) // 2
                center_y = (target_h - new_h) // 2
                
                _, _, _, alpha_ch = resized_icon.split()
                white_mask = Image.new("RGBA", (new_w, new_h), (255, 255, 255, 255))
                white_mask.putalpha(alpha_ch)
                
                offsets = [(-1, -1), (0, -1), (1, -1), (-1, 0), (1, 0), (-1, 1), (0, 1), (1, 1)]
                for ox, oy in offsets: 
                    final_img.paste(white_mask, (center_x + ox, center_y + oy), white_mask)
                final_img.paste(resized_icon, (center_x, center_y), resized_icon)
            else:
                img_w, img_h = original.size
                ratio = min(target_w / img_w, target_h / img_h)
                new_w = int(img_w * ratio)
                new_h = int(img_h * ratio)
                resized_img = original.resize((new_w, new_h), Image.Resampling.LANCZOS)
                offset_x = (target_w - new_w) // 2
                offset_y = (target_h - new_h) // 2
                final_img.paste(resized_img, (offset_x, offset_y))
            
            try:
                final_img.save(local_path, "PNG")
            except Exception as e:
                print(f"Failed to save cache: {e}")

            self.logo_cache[cache_key] = final_img

        except Exception as e: 
            print(f"Logo Error: {e}")

    def get_logo(self, url, size=(24,24)):
        if not url: return None
        cache_key = f"{url}_{size}"
        return self.logo_cache.get(cache_key)

    def draw_hockey_stick(self, draw, cx, cy, size):
        WOOD = (150, 75, 0); TAPE = (255, 255, 255)
        pattern = [
            (5,0),(6,0),(5,1),(6,1),(5,2),(6,2),(4,3),(5,3),(6,3),
            (4,4),(5,4),(0,5),(1,5),(2,5),(3,5),(4,5),(0,6),(1,6),(2,6),(3,6),(4,6)
        ]
        colors = {
            (5,0):1, (6,0):1, (5,1):1, (6,1):1, (5,2):1, (6,2):1, (4,3):1, (5,3):1, (6,3):1,
            (4,4):1, (5,4):1, (0,5):1, (1,5):2, (2,5):2, (3,5):1, (4,5):1, (0,6):1, (1,6):2, (2,6):2, (3,6):1, (4,6):1
        }
        sx, sy = cx - 4, cy - 4
        for x, y in pattern:
            if colors.get((x,y)) == 1: draw.point((sx+x, sy+y), fill=WOOD)
            elif colors.get((x,y)) == 2: draw.point((sx+x, sy+y), fill=TAPE)

    def draw_shootout_indicators(self, draw, results, start_x, y):
        display_results = results[-3:] if len(results) > 3 else results[:]
        while len(display_results) < 3: display_results.append('pending')
        x_off = start_x
        for res in display_results:
            if res == 'pending':
                draw.rectangle((x_off, y, x_off+3, y+3), outline=(80,80,80)) 
            elif res == 'miss':
                draw.line((x_off, y, x_off+3, y+3), fill=(255,0,0))
                draw.line((x_off, y+3, x_off+3, y), fill=(255,0,0))
            elif res == 'goal':
                draw.rectangle((x_off, y, x_off+3, y+3), fill=(0,255,0))
            x_off += 6 

    def draw_soccer_shootout(self, draw, results, start_x, y):
        display_results = results[-5:] if len(results) > 5 else results[:]
        while len(display_results) < 5: display_results.append('pending')
        x_off = start_x
        if len(results) > 0: x_off -= 2 
        for res in display_results:
            if res == 'pending':
                draw.rectangle((x_off, y, x_off+1, y+1), outline=(60,60,60))
            elif res == 'miss':
                draw.point((x_off, y), fill=(255,0,0))
                draw.point((x_off+1, y+1), fill=(255,0,0))
            elif res == 'goal':
                draw.rectangle((x_off, y, x_off+1, y+1), fill=(0,255,0))
            x_off += 4

    def draw_baseball_hud(self, draw, x, y, b, s, o):
        draw.point((x-4, y), fill=(150,150,150))
        draw.point((x-3, y), fill=(150,150,150))
        draw.point((x-4, y+1), fill=(150,150,150))
        draw.point((x-3, y+2), fill=(150,150,150))
        draw.point((x-4, y+2), fill=(150,150,150)) # S
        draw.line((x-4, y+3, x-4, y+5), fill=(150,150,150))
        draw.point((x-3, y+3), fill=(150,150,150))
        draw.point((x-3, y+4), fill=(150,150,150))
        draw.point((x-3, y+5), fill=(150,150,150)) # B
        draw.rectangle((x-4, y+6, x-3, y+7), outline=(150,150,150)) # O

        for i in range(2):
            color = (255, 0, 0) if i < s else (40, 40, 40)
            draw.rectangle((x + (i*4), y, x + (i*4)+1, y+1), fill=color)
        for i in range(3):
            color = (0, 255, 0) if i < b else (40, 40, 40)
            draw.rectangle((x + (i*4), y+3, x + (i*4)+1, y+4), fill=color)
        for i in range(2):
            color = (255, 100, 0) if i < o else (40, 40, 40)
            draw.rectangle((x + (i*4), y+6, x + (i*4)+1, y+7), fill=color)

    def shorten_status(self, status):
        if not status: return ""
        s = str(status).upper()
        s = s.replace(" - ", " ").replace("FINAL", "FINAL").replace("/OT", " OT").replace("HALFTIME", "HALF").replace("DELAY", "DLY")
        s = s.replace("1ST", "P1").replace("2ND", "P2").replace("3RD", "P3").replace("4TH", "P4").replace("FULL TIME", "FT")
        replacements = ["P1", "P2", "P3", "P4", "Q1", "Q2", "Q3", "Q4", "OT"]
        for r in replacements: s = s.replace(f"{r} ", f"{r}~")
        return s

    def draw_weather_icon_large(self, d, icon, x, y):
        offset = 0 if (self.anim_tick % 10 < 5) else 1
        if icon == 'sun':
            d.ellipse((x+4, y+4, x+20, y+20), fill=(255,220,0))
            d.line((x+12, y, x+12, y+3), fill=(255,220,0))
            d.line((x+12, y+21, x+12, y+24), fill=(255,220,0))
            d.line((x, y+12, x+3, y+12), fill=(255,220,0))
            d.line((x+21, y+12, x+24, y+12), fill=(255,220,0))
        elif icon == 'rain' or icon == 'storm':
            d.ellipse((x+2, y+4, x+22, y+14), fill=(100,100,100))
            d.ellipse((x+6, y, x+18, y+10), fill=(100,100,100))
            d.line((x+6, y+16+offset, x+6, y+18+offset), fill=(0,0,255))
            d.line((x+12, y+14-offset, x+12, y+16-offset), fill=(0,0,255))
            d.line((x+18, y+16+offset, x+18, y+18+offset), fill=(0,0,255))
            if icon == 'storm': 
                d.line((x+10, y+10, x+8, y+16), fill=(255,255,0))
                d.line((x+8, y+16, x+12, y+22), fill=(255,255,0))
        else: 
            color = (200,200,200)
            d.ellipse((x+2, y+6, x+22, y+18), fill=color)
            d.ellipse((x+6, y+2, x+18, y+14), fill=color)
            if icon == 'partly_cloudy': d.ellipse((x+16, y-2, x+26, y+8), fill=(255,220,0))

    def draw_weather_scene_simple(self, game):
        img = Image.new("RGBA", (128, 32), (0, 0, 0, 255))
        d = ImageDraw.Draw(img)
        
        sit = game.get('situation', {})
        stats = sit.get('stats', {})
        cur_icon = sit.get('icon', 'cloud')
        
        # 1. Animated Icon (Left: 0-32)
        self.draw_weather_icon_large(d, cur_icon, 4, 4)
        
        # 2. Main Temp (Huge, Center-Left: 34-80)
        temp_str = str(game.get('home_abbr', '00')).replace('°','') + "°"
        d.text((36, 0), temp_str, font=self.huge_font, fill=(255, 255, 255))
        
        # 3. Location/Condition (Tiny, Under Temp)
        cond_text = sit.get('condition', '')
        if not cond_text: cond_text = str(game.get('away_abbr', 'CITY')).upper()
        d.text((38, 25), cond_text[:12], font=self.micro, fill=(150, 150, 150))
        
        # 4. Detailed Stats (Right Stack: 85-128)
        high = stats.get('high', '-')
        low = stats.get('low', '-')
        pop = stats.get('pop', '0')
        x_stats = 90
        d.text((x_stats, 2), f"HI: {high}", font=self.tiny, fill=(255, 100, 100))
        d.text((x_stats, 11), f"LO: {low}", font=self.tiny, fill=(100, 100, 255))
        d.text((x_stats, 20), f"RAIN:{pop}%", font=self.tiny, fill=(0, 200, 255))
        return img

    def draw_clock_scene(self):
        img = Image.new("RGBA", (128, 32), (0, 0, 0, 255))
        d = ImageDraw.Draw(img)
        now = datetime.now()
        t_str = now.strftime("%I:%M:%S").lstrip('0')
        clock_color = (0, 50, 200) 
        w = d.textlength(t_str, font=self.huge_font)
        x_pos = (128 - w) / 2
        d.text((x_pos, 4), t_str, font=self.huge_font, fill=clock_color)
        return img

    def build_seamless_strip(self, playlist):
        if not playlist: return None
        safe_playlist = playlist[:30] if len(playlist) > 30 else playlist
        total_w = len(safe_playlist) * 64
        buffer = (PANEL_W // 64) + 1 
        film_w = total_w + (buffer * 64)
        strip = Image.new("RGBA", (film_w, PANEL_H), (0,0,0,255))
        for i, g in enumerate(safe_playlist):
            g_img = self.draw_single_game(g)
            strip.paste(g_img, (i * 64, 0), g_img)
        for i in range(buffer):
            g_img = self.draw_single_game(safe_playlist[i % len(safe_playlist)])
            strip.paste(g_img, (total_w + (i * 64), 0), g_img)
        return strip

    def poll_backend(self):
        last_data_hash = ""
        while self.running:
            try:
                url = f"{BACKEND_URL}/data?id={self.device_id}"
                r = requests.get(url, timeout=5)
                data = r.json()
                status = data.get('status')
                
                if status == 'pairing':
                    self.is_pairing = True
                    self.pairing_code = data.get('code', 'ERROR')
                    self.games = [] 
                    time.sleep(2) 
                    continue
                else:
                    self.is_pairing = False

                content_block = data.get('content', {})
                local_config = data.get('local_config', {})
                content_str = str(content_block) + str(local_config)
                if content_str == last_data_hash:
                    time.sleep(REFRESH_RATE)
                    continue
                
                last_data_hash = content_str
                new_games = content_block.get('sports', [])

                logos_to_fetch = []
                for g in new_games:
                    if g.get('home_logo'): logos_to_fetch.append((g['home_logo'], (24,24)))
                    if g.get('away_logo'): logos_to_fetch.append((g['away_logo'], (24,24)))
                    if g.get('home_logo'): logos_to_fetch.append((g['home_logo'], (16,16)))
                    if g.get('away_logo'): logos_to_fetch.append((g['away_logo'], (16,16)))
                
                logos_to_fetch = list(set(logos_to_fetch))

                if logos_to_fetch:
                    futures = [self.executor.submit(self.download_and_process_logo, url, size) for url, size in logos_to_fetch]
                    concurrent.futures.wait(futures)

                self.seamless_mode = bool(local_config.get('scroll_seamless', True))
                self.brightness = float(local_config.get('brightness', 100)) / 100.0
                self.inverted = bool(local_config.get('inverted', False))
                speed_val = float(local_config.get('scroll_speed', 0.03))
                self.scroll_sleep = max(0.005, speed_val)

                if self.seamless_mode and new_games and not (len(new_games) == 1 and new_games[0].get('sport') in ['weather', 'clock']):
                    new_strip = self.build_seamless_strip(new_games)
                    self.bg_strip = new_strip
                    self.bg_strip_ready = True
                else:
                    self.bg_strip_ready = False

                self.games = new_games
                self.config_updated = True
                self.game_render_cache.clear() 

            except Exception: 
                pass
            time.sleep(REFRESH_RATE)

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
            t_name = str(game.get('tourney_name', '')).upper()
            t_name = t_name.replace("GRAND PRIX", "GP").replace("TT", "").strip()
            full_header = t_name[:14] 
            header_w = len(full_header) * 4
            hx = (64 - header_w) // 2
            draw_tiny_text(d, hx, 1, full_header, (220, 220, 220))
            leaders = game.get('leaders', [])
            if not isinstance(leaders, list): leaders = []
            y_off = 10; row_step = 8 
            for i, p in enumerate(leaders[:3]):
                rank_color = (200, 200, 200)
                if i == 0: rank_color = (255, 215, 0)
                elif i == 1: rank_color = (192, 192, 192)
                elif i == 2: rank_color = (205, 127, 50)
                full_name = str(p.get('name', 'UNK'))
                acronym = full_name[:3].upper()
                raw_score = str(p.get('score', ''))
                if "LEADER" in raw_score.upper(): 
                    display_score = "LDR"; score_color = (255, 215, 0) 
                else:
                    display_score = raw_score
                    if not display_score.startswith('+') and not display_score.startswith('-'): display_score = "+" + display_score
                    score_color = (255, 100, 100) 
                draw_tiny_text(d, 1, y_off, str(i+1), rank_color)
                draw_tiny_text(d, 8, y_off, acronym, (255, 255, 255))
                score_width = len(display_score) * 4
                draw_tiny_text(d, 63 - score_width, y_off, display_score, score_color)
                y_off += row_step
        except Exception: return Image.new("RGBA", (64, 32), (0, 0, 0, 255))
        return img

    def get_game_hash(self, game):
        s = f"{game.get('id')}_{game.get('status')}_{game.get('away_score')}_{game.get('home_score')}"
        s += f"_{str(game.get('situation'))}"
        return hashlib.md5(s.encode()).hexdigest()

    def draw_single_game(self, game):
        game_hash = self.get_game_hash(game)
        if game_hash in self.game_render_cache:
            return self.game_render_cache[game_hash]

        img = Image.new("RGBA", (64, 32), (0, 0, 0, 0)) 
        if not isinstance(game, dict): return img
        if game.get('type') == 'leaderboard': return self.draw_leaderboard_card(game)
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
            st_width = 0
            for ch in status: st_width += 2 if ch == '~' else 5
            visual_width = st_width - 1 if st_width > 0 else 0
            st_x = (64 - visual_width) // 2
            draw_hybrid_text(d, st_x, 25, status, (180, 180, 180))

            if shootout:
                away_so = shootout.get('away', []) if isinstance(shootout, dict) else []
                home_so = shootout.get('home', []) if isinstance(shootout, dict) else []
                if is_soccer:
                    self.draw_soccer_shootout(d, away_so, 2, 26)
                    self.draw_soccer_shootout(d, home_so, 46, 26)
                else:
                    self.draw_shootout_indicators(d, away_so, 2, 26)
                    self.draw_shootout_indicators(d, home_so, 46, 26)

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
                        d.point((tx-1, icon_y+2), fill='red')
                        d.point((tx, icon_y+3), fill='red')
                        d.point((tx+1, icon_y+4), fill='red')
                    elif is_hockey: self.draw_hockey_stick(d, tx+2, icon_y+5, 3) 
                    elif is_soccer:
                        d.ellipse((tx-2, icon_y, tx+2, icon_y+4), fill='white')
                        d.point((tx, icon_y+2), fill='black')
                        
                if is_hockey:
                    if sit.get('emptyNet'): 
                        w = d.textlength("EN", font=self.micro)
                        d.text(((64-w)/2, -1), "EN", font=self.micro, fill=(255,255,0))
                    elif sit.get('powerPlay'): 
                        w = d.textlength("PP", font=self.micro)
                        d.text(((64-w)/2, -1), "PP", font=self.micro, fill=(255,255,0))
                elif is_baseball:
                    bases = [(31,2), (27,6), (35,6)]
                    active = [sit.get('onSecond'), sit.get('onThird'), sit.get('onFirst')]
                    for i, p in enumerate(bases): 
                        color = (255,255,150) if active[i] else (45,45,45)
                        d.rectangle((p[0], p[1], p[0]+3, p[1]+3), fill=color)
                    
                    b_count = int(sit.get('balls', 0))
                    s_count = int(sit.get('strikes', 0))
                    o_count = int(sit.get('outs', 0))
                    
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
        except Exception: return img 
        
        self.game_render_cache[game_hash] = img
        return img

    def render_loop(self):
        last_frame = None
        strip_offset = 0.0
        
        while self.running:
            if self.is_pairing:
                self.update_display(self.draw_pairing_screen())
                time.sleep(0.5)
                continue

            if self.brightness <= 0.01:
                self.matrix.Clear()
                time.sleep(1.0); continue
            
            self.anim_tick += 1
            playlist = list(self.games)
            
            if not playlist:
                img = Image.new("RGB", (PANEL_W, PANEL_H), (0,0,0))
                d = ImageDraw.Draw(img)
                t_str = time.strftime("%I:%M")
                w = d.textlength(t_str, font=self.font)
                d.text(((PANEL_W - w)/2, 10), t_str, font=self.font, fill=(50,50,50))
                self.update_display(img)
                time.sleep(1); continue

            if self.test_pattern:
                self.update_display(self.generate_test_pattern()); time.sleep(0.1); continue

            if len(playlist) == 1 and playlist[0].get('sport') == 'clock':
                self.update_display(self.draw_clock_scene())
                time.sleep(1) 
                continue
            
            if len(playlist) == 1 and playlist[0].get('type') == 'weather':
                self.update_display(self.draw_weather_scene_simple(playlist[0]))
                time.sleep(0.1) 
                continue

            if self.seamless_mode:
                if self.bg_strip_ready and self.bg_strip:
                    self.active_strip = self.bg_strip
                    self.bg_strip_ready = False 
                
                if not self.active_strip:
                    self.active_strip = self.build_seamless_strip(playlist)
                
                if self.active_strip:
                    total_w = self.active_strip.width - ( (PANEL_W // 64) + 1 ) * 64
                    if total_w <= 0: total_w = 1 
                    x = int(strip_offset)
                    view = self.active_strip.crop((x, 0, x + PANEL_W, PANEL_H))
                    self.update_display(view)
                    strip_offset = (strip_offset + 1) % total_w
                    time.sleep(self.scroll_sleep)
                else:
                    time.sleep(0.1)
            else: 
                chunk = 2
                for i in range(0, len(playlist), chunk):
                    if self.config_updated or self.seamless_mode or self.test_pattern or self.brightness <= 0.01: break 
                    if (len(self.games) == 1 and self.games[0].get('sport') in ['weather', 'clock']): break

                    frame = Image.new("RGBA", (PANEL_W, PANEL_H), (0,0,0,255))
                    g1 = self.draw_single_game(playlist[i])
                    frame.paste(g1, (0,0), g1)
                    if i + 1 < len(playlist):
                        g2 = self.draw_single_game(playlist[i+1])
                        frame.paste(g2, (64,0), g2)
                    
                    if last_frame:
                        for x in range(0, PANEL_W + 1, 4):
                            if self.config_updated or self.brightness <= 0.01: break
                            c = Image.new("RGBA", (PANEL_W, PANEL_H), (0,0,0,255))
                            c.paste(last_frame, (-x, 0))
                            c.paste(frame, (PANEL_W - x, 0))
                            self.update_display(c)
                            time.sleep(self.scroll_sleep) 
                    else:
                        self.update_display(frame)
                    last_frame = frame
                    
                    for _ in range(int(PAGE_HOLD_TIME * 10)):
                        if self.config_updated or self.seamless_mode or self.test_pattern or self.brightness <= 0.01: break
                        time.sleep(0.1)
                
                if self.config_updated: self.config_updated = False

if __name__ == "__main__":
    app = TickerStreamer()
    try:
        while True: time.sleep(1)
    except KeyboardInterrupt:
        print("Stopping...")
