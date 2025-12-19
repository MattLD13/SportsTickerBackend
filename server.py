import time
import threading
import io
import requests
import socket
import traceback
from PIL import Image, ImageDraw, ImageFont, ImageEnhance

# ================= CONFIGURATION =================
ESP32_IP = "192.168.1.90"   # <--- ESP32 IP Address
ESP32_PORT = 4210

# Pointing to your Railway Backend
BACKEND_URL = "https://sportstickerbackend-production.up.railway.app/api/ticker"

# Physical Hardware Resolution
PANEL_W = 128      
PANEL_H = 32

LOGO_OVERRIDES = {
    "SJS": "https://a.espncdn.com/i/teamlogos/nhl/500/sj.png",
    "NJD": "https://a.espncdn.com/i/teamlogos/nhl/500/nj.png",
    "TBL": "https://a.espncdn.com/i/teamlogos/nhl/500/tb.png",
    "LAK": "https://a.espncdn.com/i/teamlogos/nhl/500/la.png",
    "VGK": "https://a.espncdn.com/i/teamlogos/nhl/500/vgs.png", 
    "VEG": "https://a.espncdn.com/i/teamlogos/nhl/500/vgs.png",
    "WSH": "https://a.espncdn.com/guid/cbe677ee-361e-91b4-5cae-6c4c30044743/logos/secondary_logo_on_black_color.png",
    "WAS": "https://a.espncdn.com/guid/cbe677ee-361e-91b4-5cae-6c4c30044743/logos/secondary_logo_on_black_color.png",
    "LEH": "https://a.espncdn.com/i/teamlogos/ncaa/500/2329.png"
}

PAGE_SCROLL_SPEED = 0.04
PAGE_HOLD_TIME = 5.0    
SEAMLESS_SPEED = 0.05 
REFRESH_RATE = 3   

class TickerStreamer:
    def __init__(self):
        print(f"Starting Glitch-Proof Streamer -> {ESP32_IP}:{ESP32_PORT}")
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.frame_id = 0 
        self.games = []
        self.seamless_mode = False
        
        # --- DYNAMIC HARDWARE SETTINGS ---
        self.brightness = 0.5
        self.inverted = False
        self.test_pattern = False
        self.panel_count = 2 
        
        self.logo_cache = {}
        self.running = True
        
        try: self.font = ImageFont.truetype("arialbd.ttf", 10)
        except: self.font = ImageFont.load_default()
        try: self.tiny = ImageFont.truetype("arial.ttf", 9) 
        except: self.tiny = ImageFont.load_default()
        try: self.micro = ImageFont.truetype("arial.ttf", 8)
        except: self.micro = ImageFont.load_default()
        
        threading.Thread(target=self.poll_backend, daemon=True).start()
        threading.Thread(target=self.render_loop, daemon=True).start()

    def send_to_esp32(self, pil_image):
        if self.test_pattern:
            pil_image = self.generate_test_pattern()

        img = pil_image.resize((PANEL_W, PANEL_H)).convert("RGB")
        
        if self.brightness < 1.0:
            enhancer = ImageEnhance.Brightness(img)
            img = enhancer.enhance(self.brightness)

        if self.inverted:
            img = img.rotate(180)

        raw_data = img.tobytes() 
        self.frame_id = (self.frame_id + 1) % 256
        
        rows_per_packet = 3  
        bytes_per_row = PANEL_W * 3
        chunk_size = bytes_per_row * rows_per_packet
        
        for i in range(0, PANEL_H, rows_per_packet):
            start_byte = i * bytes_per_row
            end_byte = min(start_byte + chunk_size, len(raw_data))
            header = bytes([self.frame_id, i]) 
            payload = raw_data[start_byte:end_byte]
            self.sock.sendto(header + payload, (ESP32_IP, ESP32_PORT))
            time.sleep(0.002) 

    def generate_test_pattern(self):
        img = Image.new("RGB", (PANEL_W, PANEL_H), (0,0,0))
        d = ImageDraw.Draw(img)
        d.rectangle((0,0, PANEL_W-1, PANEL_H-1), outline=(255,0,0))
        d.line((0,0, PANEL_W, PANEL_H), fill=(0,255,0))
        d.line((0,PANEL_H, PANEL_W, 0), fill=(0,255,0))
        d.text((10, 10), "TEST MODE", font=self.font, fill=(0,0,255))
        return img

    def process_logo(self, img):
        img = img.convert("RGBA")
        pixels = img.getdata()
        total_opaque = 0
        dark_count = 0
        for r, g, b, a in pixels:
            if a > 50: 
                total_opaque += 1
                if ((0.299 * r) + (0.587 * g) + (0.114 * b)) < 90: dark_count += 1
        
        if total_opaque > 0 and (dark_count / total_opaque) > 0.30:
            white = Image.new("RGBA", img.size, (255, 255, 255, 255))
            alpha = img.getchannel('A')
            mask = Image.new("L", img.size, 0)
            mask.paste(alpha, (1, 0), alpha)
            mask.paste(alpha, (-1, 0), alpha)
            mask.paste(alpha, (0, 1), alpha)
            mask.paste(alpha, (0, -1), alpha)
            mask.paste(alpha, (0, 0), alpha) 
            final = Image.new("RGBA", img.size, (0,0,0,0))
            final.paste(white, (0,0), mask)
            final.paste(img, (0,0), img)
            return final
        return img

    def get_logo(self, url, team_abbr, sport, size=(24,24)):
        if team_abbr in LOGO_OVERRIDES:
            if team_abbr in ["WAS", "WSH"]:
                if "nhl" in sport.lower() or "hockey" in sport.lower():
                    url = LOGO_OVERRIDES[team_abbr]
            else:
                url = LOGO_OVERRIDES[team_abbr]

        cache_key = f"{url}_{size}"
        if not url: return None
        if cache_key in self.logo_cache: return self.logo_cache[cache_key]
        try:
            r = requests.get(url, timeout=1)
            img = Image.open(io.BytesIO(r.content)).convert("RGBA")
            img = img.resize(size, Image.Resampling.LANCZOS)
            img = self.process_logo(img)
            self.logo_cache[cache_key] = img
            return img
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

    def shorten_status(self, status, sport, is_playoff):
        """
        Robustly replaces Period/Quarter labels with OT/SO.
        Performs string replacement directly on the status string to ensure
        'Q5' is caught even if period number parsing fails.
        """
        s = status.upper()

        # --- BASKETBALL / NBA ---
        if "basketball" in sport or "nba" in sport:
            if "Q5" in s: s = s.replace("Q5", "OT")
            if "Q6" in s: s = s.replace("Q6", "2OT")
            if "Q7" in s: s = s.replace("Q7", "3OT")
            if "Q8" in s: s = s.replace("Q8", "4OT")

        # --- FOOTBALL / NFL ---
        elif "football" in sport or "nfl" in sport:
            if "Q5" in s: s = s.replace("Q5", "OT")
            if "Q6" in s: s = s.replace("Q6", "2OT")

        # --- HOCKEY / NHL ---
        elif "hockey" in sport or "nhl" in sport:
            if "P4" in s: 
                s = s.replace("P4", "OT")
            if "P5" in s: 
                s = s.replace("P5", "2OT" if is_playoff else "SO")
            if "P6" in s: 
                s = s.replace("P6", "3OT" if is_playoff else "SO")

        # --- STANDARD CLEANUP ---
        s = s.replace("FINAL", "FINAL").replace("/OT", " OT")
        s = s.replace("HALFTIME", "HALF").replace("DELAY", "DLY")
        s = s.replace("1ST", "P1").replace("2ND", "P2").replace("3RD", "P3").replace("4TH", "P4")
        
        return s

    def draw_single_game(self, game):
        img = Image.new("RGBA", (64, 32), (0, 0, 0, 0)) 
        d = ImageDraw.Draw(img)
        if not game: return img 

        sport = game.get('sport', '').lower()
        is_playoff = game.get('is_playoff', False)

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

        l1 = self.get_logo(game.get('away_logo'), game.get('away_abbr'), sport, logo_size)
        if l1: img.paste(l1, l1_pos, l1)
        else: d.text(l1_pos, game['away_abbr'][:3], font=self.micro, fill=(150,150,150))
        
        l2 = self.get_logo(game.get('home_logo'), game.get('home_abbr'), sport, logo_size)
        if l2: img.paste(l2, l2_pos, l2)
        else: d.text(l2_pos, game['home_abbr'][:3], font=self.micro, fill=(150,150,150))

        score = f"{a_score}-{h_score}"
        w_sc = d.textlength(score, font=self.font)
        d.text(((64-w_sc)/2, score_y), score, font=self.font, fill=(255,255,255))

        # --- STATUS FORMATTING ---
        raw_status = game.get('status', '')
        status = self.shorten_status(raw_status, sport, is_playoff)
        
        w_st = d.textlength(status, font=self.micro)
        d.text(((64-w_st)/2, 23), status, font=self.micro, fill=(180,180,180))

        if is_active:
            icon_y = logo_y + logo_size[1] + 3
            tx = -1
            side = None
            if (is_football or is_baseball) and poss: side = poss
            elif is_hockey and (sit.get('powerPlay') or sit.get('emptyNet')) and poss: side = poss

            if side == game.get('away_abbr') or side == game.get('away_id'): 
                tx = l1_pos[0] + (logo_size[0]//2)
            elif side == game.get('home_abbr') or side == game.get('home_id'): 
                tx = l2_pos[0] + (logo_size[0]//2)
            
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

    def poll_backend(self):
        while self.running:
            try:
                r = requests.get(BACKEND_URL, timeout=2)
                data = r.json()
                self.games = data.get('games', [])
                if 'meta' in data:
                    self.seamless_mode = data['meta'].get('scroll_seamless', False)
                    self.brightness = float(data['meta'].get('brightness', 0.5))
                    self.inverted = bool(data['meta'].get('inverted', False))
                    self.test_pattern = bool(data['meta'].get('test_pattern', False))
                    self.panel_count = int(data['meta'].get('panel_count', 2))
            except: pass
            time.sleep(REFRESH_RATE)

    def render_loop(self):
        last_frame = None
        strip_offset = 0.0
        
        while self.running:
            try:
                playlist = list(self.games)
                
                if not playlist and not self.test_pattern:
                    img = Image.new("RGB", (PANEL_W, PANEL_H), (0,0,0))
                    d = ImageDraw.Draw(img)
                    t_str = time.strftime("%I:%M")
                    w = d.textlength(t_str, font=self.font)
                    d.text(((PANEL_W - w)/2, 10), t_str, font=self.font, fill=(50,50,50))
                    self.send_to_esp32(img)
                    time.sleep(1)
                    continue

                if self.test_pattern:
                    img = self.generate_test_pattern()
                    self.send_to_esp32(img)
                    time.sleep(0.1)
                    continue

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
                        if not self.seamless_mode or self.test_pattern: break
                        x = int(strip_offset)
                        view = strip.crop((x, 0, x + PANEL_W, PANEL_H))
                        self.send_to_esp32(view)
                        strip_offset = (strip_offset + 1) % total_w
                        time.sleep(SEAMLESS_SPEED)
                
                else:
                    chunk = 2
                    for i in range(0, len(playlist), chunk):
                        if self.seamless_mode or self.test_pattern: break 
                        frame = Image.new("RGB", (PANEL_W, PANEL_H), (0,0,0))
                        
                        g1 = self.draw_single_game(playlist[i])
                        frame.paste(g1, (0,0), g1)
                        if i + 1 < len(playlist):
                            g2 = self.draw_single_game(playlist[i+1])
                            frame.paste(g2, (64,0), g2)
                        
                        if last_frame:
                            for x in range(0, PANEL_W + 1, 4):
                                c = Image.new("RGB", (PANEL_W, PANEL_H), (0,0,0))
                                c.paste(last_frame, (-x, 0))
                                c.paste(frame, (PANEL_W - x, 0))
                                self.send_to_esp32(c)
                                time.sleep(PAGE_SCROLL_SPEED)
                        else:
                            self.send_to_esp32(frame)
                        last_frame = frame
                        
                        for _ in range(int(PAGE_HOLD_TIME * 10)):
                            if self.seamless_mode or self.test_pattern: break
                            time.sleep(0.1)
            except Exception as e:
                print(f"Error: {e}")
                traceback.print_exc()
                time.sleep(2)

if __name__ == "__main__":
    app = TickerStreamer()
    try:
        while True: time.sleep(1)
    except KeyboardInterrupt:
        print("Stopping...")
