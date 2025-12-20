import time
import threading
import io
import requests
import traceback
import sys
import subprocess
import socket
from datetime import datetime
from PIL import Image, ImageDraw, ImageFont
import random

# Import Matrix Library
from rgbmatrix import RGBMatrix, RGBMatrixOptions

from flask import Flask, request, render_template_string

# ================= CONFIGURATION =================
# UPDATE THIS IP TO YOUR SERVER IP IF NOT HOSTED ON RAILWAY
BACKEND_URL = "https://sportstickerbackend-production.up.railway.app/api/ticker"
PANEL_W = 128        
PANEL_H = 32
SETUP_SSID = "SportsTicker_Setup"

PAGE_SCROLL_SPEED = 0.04
PAGE_HOLD_TIME = 5.0    
SEAMLESS_SPEED = 0.05 
REFRESH_RATE = 3   

# --- WIFI MANAGER CLASS ---
class WifiPortal:
    def __init__(self, matrix, font):
        self.matrix = matrix
        self.font = font
        self.app = Flask(__name__)
        
        self.html_template = """
        <html><body>
            <h2>Connect Ticker</h2>
            <form action="/connect" method="POST">
                <input type="text" name="ssid" placeholder="SSID"><br>
                <input type="password" name="password" placeholder="Password"><br>
                <button type="submit">Connect</button>
            </form>
        </body></html>
        """

        @self.app.route('/')
        def home(): return render_template_string(self.html_template)

        @self.app.route('/connect', methods=['POST'])
        def connect():
            ssid = request.form['ssid']
            pw = request.form['password']
            self.draw_status(f"CONNECTING:\n{ssid}")
            try:
                subprocess.run(['nmcli', 'dev', 'wifi', 'connect', ssid, 'password', pw], check=True)
                return "Rebooting..."
            except: return "Failed"
            finally:
                time.sleep(2)
                subprocess.run(['reboot'])

    def check_internet(self):
        try:
            socket.gethostbyname("google.com")
            return True
        except: return False

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
        self.app.run(host='0.0.0.0', port=80) 

class TickerStreamer:
    def __init__(self):
        print("Starting Ticker System...")
        options = RGBMatrixOptions()
        options.rows = 32
        options.cols = 64
        options.chain_length = 2      
        options.parallel = 1
        options.hardware_mapping = 'regular'  
        options.gpio_slowdown = 4                   
        options.disable_hardware_pulsing = True
        options.drop_privileges = False 
        
        self.matrix = RGBMatrix(options=options)
        
        # Font Loading
        try: self.font = ImageFont.truetype("DejaVuSans-Bold.ttf", 10)
        except: 
            try: self.font = ImageFont.truetype("arialbd.ttf", 10)
            except: self.font = ImageFont.load_default()
            
        try: self.tiny = ImageFont.truetype("DejaVuSans.ttf", 9) 
        except: 
            try: self.tiny = ImageFont.truetype("arial.ttf", 9)
            except: self.tiny = ImageFont.load_default()
            
        try: self.micro = ImageFont.truetype("DejaVuSans.ttf", 7)
        except: 
            try: self.micro = ImageFont.truetype("arial.ttf", 7)
            except: self.micro = ImageFont.load_default()
            
        try: self.big_font = ImageFont.truetype("DejaVuSans-Bold.ttf", 16)
        except: 
            try: self.big_font = ImageFont.truetype("arialbd.ttf", 16)
            except: self.big_font = ImageFont.load_default()
            
        try: self.clock_font = ImageFont.truetype("DejaVuSans-Bold.ttf", 14)
        except: 
            try: self.clock_font = ImageFont.truetype("arialbd.ttf", 14)
            except: self.clock_font = ImageFont.load_default()

        self.portal = WifiPortal(self.matrix, self.font)
        if not self.portal.check_internet(): self.portal.run() 

        self.games = []
        self.seamless_mode = False
        self.brightness = 0.5
        self.inverted = False
        self.test_pattern = False
        self.running = True
        self.logo_cache = {}
        self.anim_tick = 0

        threading.Thread(target=self.poll_backend, daemon=True).start()
        threading.Thread(target=self.render_loop, daemon=True).start()

    def update_display(self, pil_image):
        if self.test_pattern: pil_image = self.generate_test_pattern()
        img = pil_image.resize((self.matrix.width, self.matrix.height)).convert("RGB")
        target_b = int(max(0, min(100, self.brightness * 100)))
        if self.matrix.brightness != target_b: self.matrix.brightness = target_b
        if self.inverted: img = img.rotate(180)
        self.matrix.SetImage(img)

    def generate_test_pattern(self):
        img = Image.new("RGB", (PANEL_W, PANEL_H), (0,0,0))
        d = ImageDraw.Draw(img)
        d.rectangle((0,0, PANEL_W-1, PANEL_H-1), outline=(255,0,0))
        d.text((10, 10), "TEST", font=self.font, fill=(0,0,255))
        return img

    def get_logo(self, url, size=(24,24)):
        if not url: return None
        cache_key = f"{url}_{size}"
        if cache_key in self.logo_cache: return self.logo_cache[cache_key]
        try:
            r = requests.get(url, timeout=2) 
            img = Image.open(io.BytesIO(r.content)).convert("RGBA")
            img = img.resize(size, Image.Resampling.LANCZOS)
            bg = Image.new("RGBA", size, (0,0,0,0))
            bg.alpha_composite(img)
            self.logo_cache[cache_key] = bg
            return bg
        except: return None

    def draw_hockey_stick(self, draw, cx, cy, size):
        WOOD = (150, 75, 0); TAPE = (255, 255, 255)
        pattern = [[0,0,0,0,0,1,1,0],[0,0,0,0,0,1,1,0],[0,0,0,0,0,1,1,0],[0,0,0,0,1,1,1,0],
                   [0,0,0,0,1,1,0,0],[1,2,2,1,1,1,0,0],[1,2,2,1,1,0,0,0],[0,0,0,0,0,0,0,0]]
        sx, sy = cx - 4, cy - 4
        for y in range(8):
            for x in range(8):
                if pattern[y][x] == 1: draw.point((sx+x, sy+y), fill=WOOD)
                elif pattern[y][x] == 2: draw.point((sx+x, sy+y), fill=TAPE)

    def shorten_status(self, status):
        s = status.upper()
        s = s.replace(" - ", " ")
        while "  " in s: s = s.replace("  ", " ")
        s = s.replace("FINAL", "FINAL").replace("/OT", " OT")
        s = s.replace("HALFTIME", "HALF").replace("DELAY", "DLY")
        s = s.replace("1ST", "P1").replace("2ND", "P2").replace("3RD", "P3").replace("4TH", "P4")
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
            if icon == 'partly_cloudy':
                d.ellipse((x+16, y-2, x+26, y+8), fill=(255,220,0))

    def draw_weather_scene_simple(self, game):
        img = Image.new("RGB", (128, 32), (0, 0, 0)) 
        d = ImageDraw.Draw(img)
        sit = game.get('situation', {}); stats = sit.get('stats', {})
        cur_icon = sit.get('icon', 'cloud')
        temp_str = game.get('home_abbr', '00').replace('°','')
        loc_str = game.get('away_abbr', 'CITY').upper()[:10]
        self.draw_weather_icon_large(d, cur_icon, 4, 4)
        d.text((36, -1), loc_str, font=self.micro, fill=(180,180,180))
        d.text((36, 9), temp_str + "°", font=self.big_font, fill=(255,255,255))
        high = stats.get('high', 0); low = stats.get('low', 0); uv = int(stats.get('uv', 0))
        d.text((92, 1), f"H:{high}", font=self.tiny, fill=(255,100,100))
        d.text((92, 11), f"L:{low}", font=self.tiny, fill=(100,100,255))
        d.text((92, 21), f"UV:{uv}", font=self.tiny, fill=(255,255,0))
        return img

    def draw_clock_scene(self):
        img = Image.new("RGB", (128, 32), (0, 0, 0))
        d = ImageDraw.Draw(img)
        now = datetime.now()
        t_str = now.strftime("%I:%M:%S"); 
        if t_str.startswith('0'): t_str = t_str[1:]
        ampm = now.strftime("%p")
        w = d.textlength(t_str, font=self.clock_font)
        x_pos = (128 - w) / 2
        d.text((x_pos, 4), t_str, font=self.clock_font, fill=(0, 41, 91)) 
        w_ap = d.textlength(ampm, font=self.font)
        d.text(((128-w_ap)/2, 22), ampm, font=self.font, fill=(100,100,100))
        return img

    def poll_backend(self):
        while self.running:
            try:
                r = requests.get(BACKEND_URL, timeout=5)
                data = r.json()
                self.games = data.get('games', [])
                if 'meta' in data:
                    self.seamless_mode = data['meta'].get('scroll_seamless', False)
                    self.brightness = float(data['meta'].get('brightness', 0.5))
                    self.inverted = bool(data['meta'].get('inverted', False))
                    self.test_pattern = bool(data['meta'].get('test_pattern', False))
                    if data['meta'].get('reboot_requested', False):
                        subprocess.run(['sudo', 'reboot'])
            except: pass
            time.sleep(REFRESH_RATE)

    def draw_single_game(self, game):
        img = Image.new("RGBA", (64, 32), (0, 0, 0, 0)) 
        d = ImageDraw.Draw(img)
        if not game: return img 

        sport = game.get('sport', '').lower()
        is_football = 'football' in sport or 'nfl' in sport or 'ncf' in sport
        is_hockey = 'hockey' in sport or 'nhl' in sport
        is_baseball = 'baseball' in sport or 'mlb' in sport
        is_active = game.get('state') == 'in'
        sit = game.get('situation', {}); poss = sit.get('possession')
        
        a_score = str(game['away_score']); h_score = str(game['home_score'])
        
        has_indicator = is_active and (poss or sit.get('powerPlay') or sit.get('emptyNet'))
        is_wide = ((is_football and is_active) or len(a_score) >= 2 or len(h_score) >= 2 or has_indicator)
        
        logo_size = (16, 16) if is_wide else (24, 24)
        logo_y = 5 if is_wide else 0
        l1_pos = (2, logo_y) if is_wide else (0, logo_y)
        l2_pos = (46, logo_y) if is_wide else (40, logo_y)
        score_y = 10 if is_wide else 12

        l1 = self.get_logo(game.get('away_logo'), logo_size)
        if l1: img.paste(l1, l1_pos, l1)
        else: d.text(l1_pos, game['away_abbr'][:3], font=self.micro, fill=(150,150,150))
        
        l2 = self.get_logo(game.get('home_logo'), logo_size)
        if l2: img.paste(l2, l2_pos, l2)
        else: d.text(l2_pos, game['home_abbr'][:3], font=self.micro, fill=(150,150,150))

        score = f"{a_score}-{h_score}"
        w_sc = d.textlength(score, font=self.font)
        d.text(((64-w_sc)/2, score_y), score, font=self.font, fill=(255,255,255), stroke_width=1, stroke_fill=(0,0,0))

        status = self.shorten_status(game.get('status', ''))
        w_st = d.textlength(status, font=self.micro)
        d.text(((64-w_st)/2, 22), status, font=self.micro, fill=(180,180,180))

        if is_active:
            icon_y = logo_y + logo_size[1] + 3
            tx = -1
            side = None
            if (is_football or is_baseball) and poss: side = poss
            elif is_hockey and (sit.get('powerPlay') or sit.get('emptyNet')) and poss: side = poss

            if side == game.get('away_abbr') or side == game.get('away_id'): 
                tx = l1_pos[0] + (logo_size[0]//2) - 2 
            elif side == game.get('home_abbr') or side == game.get('home_id'): 
                tx = l2_pos[0] + (logo_size[0]//2) + 2 
            
            if tx != -1:
                if is_football:
                    d.ellipse([tx-3, icon_y, tx+3, icon_y+4], fill=(170,85,0))
                    d.line([(tx, icon_y+1), (tx, icon_y+3)], fill='white', width=1)
                elif is_baseball:
                    d.ellipse((tx-2, icon_y, tx+2, icon_y+4), fill='white')
                    d.point((tx-1, icon_y+1), fill='red'); d.point((tx+1, icon_y+3), fill='red')
                elif is_hockey:
                    self.draw_hockey_stick(d, tx+2, icon_y+5, 3) 

            if is_hockey:
                 if sit.get('emptyNet'):
                     w = d.textlength("EN", font=self.micro)
                     d.text(((64-w)/2, -1), "EN", font=self.micro, fill=(255,255,0))
                 elif sit.get('powerPlay'):
                     w = d.textlength("PP", font=self.micro)
                     d.text(((64-w)/2, -1), "PP", font=self.micro, fill=(255,255,0))
            elif is_baseball:
                bases = [(32,2), (29,5), (35,5)] 
                active = [sit.get('onSecond'), sit.get('onThird'), sit.get('onFirst')]
                for i, p in enumerate(bases):
                    color = (255,255,0) if active[i] else (60,60,60)
                    d.rectangle((p[0], p[1], p[0]+2, p[1]+2), fill=color)
            elif is_football:
                dd = sit.get('downDist', '')
                if dd:
                    s_dd = dd.split(' at ')[0].replace("1st", "1st")
                    w = d.textlength(s_dd, font=self.micro)
                    d.text(((64-w)/2, -1), s_dd, font=self.micro, fill=(0,255,0))
            if is_football and sit.get('isRedZone'):
                d.rectangle((0, 0, 63, 31), outline=(255, 0, 0), width=1)
        return img

    def render_loop(self):
        last_frame = None
        strip_offset = 0.0
        
        while self.running:
            # === SLEEP MODE CHECK ===
            if self.brightness <= 0.01:
                self.matrix.Clear()
                time.sleep(1.0)
                continue
            
            self.anim_tick += 1
            playlist = list(self.games)
            
            if not playlist:
                img = Image.new("RGB", (PANEL_W, PANEL_H), (0,0,0))
                d = ImageDraw.Draw(img)
                t_str = time.strftime("%I:%M")
                w = d.textlength(t_str, font=self.font)
                d.text(((PANEL_W - w)/2, 10), t_str, font=self.font, fill=(50,50,50))
                self.update_display(img)
                time.sleep(1)
                continue

            if self.test_pattern:
                self.update_display(self.generate_test_pattern())
                time.sleep(0.1); continue

            # Detect Modes
            is_weather = (len(playlist) == 1 and playlist[0].get('sport') == 'weather')
            is_clock = (len(playlist) == 1 and playlist[0].get('sport') == 'clock')

            if is_clock:
                self.update_display(self.draw_clock_scene())
                time.sleep(1); continue

            if is_weather:
                self.update_display(self.draw_weather_scene_simple(playlist[0]))
                time.sleep(0.1); continue

            # --- SPORTS SCROLLING LOGIC ---
            if self.seamless_mode:
                total_w = len(playlist) * 64
                buffer = (PANEL_W // 64) + 1 
                film_w = total_w + (buffer * 64)
                strip = Image.new("RGB", (film_w, PANEL_H), (0,0,0))
                
                for i, g in enumerate(playlist):
                    g_img = self.draw_single_game(g)
                    strip.paste(g_img, (i * 64, 0), g_img)
                for i in range(buffer):
                    g_img = self.draw_single_game(playlist[i % len(playlist)])
                    strip.paste(g_img, (total_w + (i * 64), 0), g_img)

                for _ in range(64 * len(playlist)):
                    # Check conditions to break scroll loop
                    if not self.seamless_mode or self.test_pattern or self.brightness <= 0.01: break
                    if (len(self.games) == 1 and self.games[0].get('sport') in ['weather', 'clock']): break 
                    
                    x = int(strip_offset)
                    view = strip.crop((x, 0, x + PANEL_W, PANEL_H))
                    self.update_display(view)
                    strip_offset = (strip_offset + 1) % total_w
                    time.sleep(SEAMLESS_SPEED)
            
            else: # PAGED
                chunk = 2
                for i in range(0, len(playlist), chunk):
                    # Check conditions to break paged loop
                    if self.seamless_mode or self.test_pattern or self.brightness <= 0.01: break 
                    if (len(self.games) == 1 and self.games[0].get('sport') in ['weather', 'clock']): break

                    frame = Image.new("RGB", (PANEL_W, PANEL_H), (0,0,0))
                    g1 = self.draw_single_game(playlist[i])
                    frame.paste(g1, (0,0), g1)
                    if i + 1 < len(playlist):
                        g2 = self.draw_single_game(playlist[i+1])
                        frame.paste(g2, (64,0), g2)
                    
                    if last_frame:
                        for x in range(0, PANEL_W + 1, 4):
                            if self.brightness <= 0.01: break # Instant exit on sleep
                            c = Image.new("RGB", (PANEL_W, PANEL_H), (0,0,0))
                            c.paste(last_frame, (-x, 0))
                            c.paste(frame, (PANEL_W - x, 0))
                            self.update_display(c)
                            time.sleep(PAGE_SCROLL_SPEED)
                    else:
                        self.update_display(frame)
                    last_frame = frame
                    
                    for _ in range(int(PAGE_HOLD_TIME * 10)):
                        if self.seamless_mode or self.test_pattern or self.brightness <= 0.01: break
                        if (len(self.games) == 1 and self.games[0].get('sport') in ['weather', 'clock']): break
                        time.sleep(0.1)

if __name__ == "__main__":
    app = TickerStreamer()
    try:
        while True: time.sleep(1)
    except KeyboardInterrupt:
        print("Stopping...")
