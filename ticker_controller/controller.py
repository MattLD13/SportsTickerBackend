"""Core TickerStreamer class — inherits all display-mode mixins."""

import concurrent.futures
import hashlib
import io
import json
import os
import random
import subprocess
import sys
import threading
import time

import requests
import requests.adapters
from PIL import Image, ImageDraw, ImageFont, ImageStat

try:
    from rgbmatrix import RGBMatrix, RGBMatrixOptions
except ImportError:
    RGBMatrix = RGBMatrixOptions = None

from .config import (
    BACKEND_URL, PANEL_W, PANEL_H,
    GAME_SEPARATOR_W, GAME_SEPARATOR_COLOR,
    ASSETS_DIR, PAGE_HOLD_TIME,
)
from .fonts import load_monospace_font, load_display_font, normalize_special_chars
from .matrix import NullMatrix, WifiPortal, get_device_id
from .stadium import StadiumRenderer, calc_card_width, _enhance_logo_visibility
from .modes.sports import SportsMixin
from .modes.weather import WeatherMixin
from .modes.golf import GolfMixin
from .modes.music import MusicMixin
from .modes.flight import FlightMixin
from .modes.misc import MiscMixin
from .modes.racing import RacingMixin


class TickerStreamer(SportsMixin, WeatherMixin, GolfMixin, MusicMixin, FlightMixin, MiscMixin, RacingMixin):
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
        self.scratch_layer = Image.new("RGBA", (self.VINYL_SIZE, self.VINYL_SIZE), (0, 0, 0, 0))
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

        self.is_updating = False
        self._update_step = "Updating..."
        self._update_version = ""

        threading.Thread(target=self.poll_backend, daemon=True).start()

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
    def download_and_process_logo(self, url, size=(24, 24)):
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
                final = Image.new("RGBA", size, (0, 0, 0, 0))
                final.paste(img, ((size[0] - img.width) // 2, (size[1] - img.height) // 2))
                final = _enhance_logo_visibility(final)
                self.logo_cache[tuple_key] = final
                self.logo_cache[dim_key] = final
                try:
                    os.makedirs(ASSETS_DIR, exist_ok=True)
                    final.save(local, "PNG")
                except Exception:
                    pass
        except Exception:
            pass

    def get_logo(self, url, size=(24, 24)):
        if not url:
            return None
        return self.logo_cache.get(f"{url}_{size}") or self.logo_cache.get(f"{url}_{size[0]}x{size[1]}")

    # ================= DRAWING HELPERS =================
    def draw_arrow(self, d, x, y, is_up, color):
        if is_up:
            d.polygon([(x + 2, y), (x, y + 4), (x + 4, y + 4)], fill=color)
        else:
            d.polygon([(x, y), (x + 4, y), (x + 2, y + 4)], fill=color)

    def draw_side_arrow(self, draw, x, y, is_left, color):
        if is_left:
            draw.polygon([(x + 4, y), (x, y + 3), (x + 4, y + 6)], fill=color)
        else:
            draw.polygon([(x, y), (x + 4, y + 3), (x, y + 6)], fill=color)

    def draw_bat(self, draw, cx, by):
        bc = (220, 180, 120)
        hc = (180, 135, 65)
        kc = (150, 105, 40)
        draw.rectangle([cx - 2, by + 0,  cx + 1, by + 7],  fill=bc)
        draw.rectangle([cx - 1, by + 8,  cx + 0, by + 9],  fill=bc)
        draw.rectangle([cx - 1, by + 10, cx + 0, by + 15], fill=hc)
        draw.rectangle([cx - 2, by + 16, cx + 1, by + 17], fill=kc)

    def draw_outlined_text(self, d, x, y, text, font, fill, outline, anchor="mm"):
        for dx in [-1, 0, 1]:
            for dy in [-1, 0, 1]:
                if dx == 0 and dy == 0:
                    continue
                d.text((x + dx, y + dy), text, font=font, fill=outline, anchor=anchor)
        d.text((x, y), text, font=font, fill=fill, anchor=anchor)

    def get_team_color(self, game, side='home'):
        c = game.get(f'{side}_color')
        if c:
            try:
                c = c.lstrip('#')
                return tuple(int(c[i:i + 2], 16) for i in (0, 2, 4))
            except Exception:
                pass
        logo = self.get_logo(game.get(f'{side}_logo'), (24, 24))
        if logo:
            stat = ImageStat.Stat(logo)
            return tuple(int(x) for x in stat.mean[:3])
        return (60, 60, 60)

    def _parse_hex_color(self, value):
        try:
            c = str(value or '').strip().lstrip('#')
            if len(c) == 6:
                return tuple(int(c[i:i + 2], 16) for i in (0, 2, 4))
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

    def shorten_status(self, status, sport=''):
        if not status:
            return ""
        _susp = ("delay", "delayed", "suspended", "postponed", "canceled", "ppd")
        if any(k in str(status).lower() for k in _susp):
            return str(status).title()
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

    # ================= SINGLE GAME RENDERER =================
    def draw_single_game(self, game):
        game_hash = self.get_game_hash(game)

        if game.get('sport') == 'clock':
            return self.draw_clock_modern()

        if game.get('type') in ('golf', 'masters') or str(game.get('sport', '')).lower() in ('golf', 'masters'):
            if self.mode in ('golf', 'masters'):
                return self.draw_golf_mode(game)
            return self.draw_golf_scroll_card(game)

        if game.get('type') == 'music' or game.get('sport') == 'music':
            return self.draw_music_card(game)

        if game.get('type') != 'weather':
            if game_hash in self.game_render_cache:
                return self.game_render_cache[game_hash]

        if game.get('type') == 'weather':
            img = self.draw_weather_detailed(game)
            self.game_render_cache[game_hash] = img
            return img

        if self.mode in ('sports_full', 'soccer_full') and game.get('type') not in ['leaderboard', 'stock_ticker'] and 'flight' not in str(game.get('type', '')):
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

        if game.get('type') == 'n24_car' or game.get('sport') == 'n24':
            img = self.draw_n24_car_compact(game) if game.get('compact') else self.draw_n24_car_card(game)
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
        if self.mode in ('sports_full', 'soccer_full') and t not in ['music', 'weather', 'leaderboard', 'stock_ticker', 'n24_car'] and 'flight' not in str(t):
            return PANEL_W
        if t in ('golf', 'masters') or str(s).lower() in ('golf', 'masters'):
            return PANEL_W if self.mode in ('golf', 'sports_full') else 128 + GAME_SEPARATOR_W
        if t == 'music' or s == 'music':
            return PANEL_W
        if t == 'n24_car' or s == 'n24':
            return 96 if game.get('compact') else 128
        if t == 'stock_ticker' or (s and str(s).startswith('stock')):
            return 128
        if t == 'weather':
            return PANEL_W
        if t == 'flight_visitor':
            return PANEL_W
        if t == 'flight_airport_hud':
            return PANEL_W
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
        strip = Image.new("RGBA", (total_w + PANEL_W, PANEL_H), (0, 0, 0, 255))
        sd = ImageDraw.Draw(strip)

        x = 0
        for i, card in enumerate(cards):
            sd.line([(x, 0), (x, PANEL_H - 1)], fill=GAME_SEPARATOR_COLOR)
            x += GAME_SEPARATOR_W
            strip.paste(card, (x, 0), card)
            x += card.width

        bx = x
        i = 0
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

    # ================= OTA UPDATE =================
    def _run_update(self):
        """Pull latest code and restart. Runs in a background thread."""
        updater_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "updater.py")
        self._update_step = "Pulling..."
        try:
            subprocess.run(
                [sys.executable, updater_path, "--no-display"],
                timeout=120,
            )
        except Exception as e:
            print(f"Updater error: {e}")
        # updater.py exits the process after restarting the service; if we reach
        # here it means something failed — just clear the flag and carry on.
        self.is_updating = False

    # ================= RENDER LOOP =================
    def render_loop(self):
        strip_offset = 0.0

        while self.running:
            try:
                if self.is_updating:
                    frame = self.draw_update_screen(self._update_step, version=self._update_version)
                    self.update_display(frame)
                    time.sleep(0.033)
                    continue

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

                        if sport.startswith('clock') or game_type in ('music', 'golf', 'masters', 'weather') or sport in ('music', 'golf', 'masters'):
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
                    if total_w <= 0:
                        total_w = 1
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
        _backoff = 1.0
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

                g_config = data.get('global_config') or {}
                if g_config.get('update') and not self.is_updating:
                    self._update_version = g_config.get('update_version', '')
                    print(f"OTA update requested by server. Target: {self._update_version or 'unknown'}")
                    self.is_updating = True
                    threading.Thread(target=self._run_update, daemon=True).start()

                if g_config.get('reboot'):
                    print("Reboot requested by server.")
                    subprocess.Popen(['sudo', 'reboot'])

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
                            if g.get('home_logo'):
                                logos_to_fetch.append((g.get('home_logo'), (42, 42)))
                            for nurl in g.get('next_logos', []):
                                if nurl:
                                    logos_to_fetch.append((nurl, (42, 42)))
                        else:
                            if g.get('home_logo'):
                                logos_to_fetch.append((g.get('home_logo'), (22, 22)))
                                logos_to_fetch.append((g.get('home_logo'), (24, 24)))
                                logos_to_fetch.append((g.get('home_logo'), (16, 16)))
                            if g.get('away_logo'):
                                logos_to_fetch.append((g.get('away_logo'), (22, 22)))
                                logos_to_fetch.append((g.get('away_logo'), (24, 24)))
                                logos_to_fetch.append((g.get('away_logo'), (16, 16)))

                        is_golf = g_type in ('golf', 'masters') or sport in ('golf', 'masters')
                        is_golf_fullscreen = is_golf and self.mode in ('golf', 'masters')
                        if g_type == 'weather' or sport.startswith('clock') or is_golf_fullscreen or is_music or g_type == 'flight_visitor' or g_type == 'flight_airport_hud':
                            static_items.append(g)
                        elif self.mode in ('sports_full', 'soccer_full') and g_type not in ['leaderboard', 'stock_ticker'] and 'flight' not in str(g_type) and not is_golf:
                            static_items.append(g)
                        else:
                            scrolling_items.append(g)

                    unique_logos = list(set(logos_to_fetch))
                    if unique_logos:
                        fs = [self.executor.submit(self.download_and_process_logo, u, s) for u, s in unique_logos]
                        concurrent.futures.wait(fs, timeout=2.0)

                    self.new_games_list = scrolling_items
                    self.static_items = static_items
                    self.static_index = 0

                    if scrolling_items:
                        try:
                            self.bg_strip = self.build_seamless_strip(scrolling_items)
                        except Exception as strip_err:
                            print(f"Strip build error: {strip_err}")
                            self.bg_strip = None
                    else:
                        self.bg_strip = None

                    self.game_render_cache.clear()
                    self.bg_strip_ready = True
                    last_hash = current_hash

                _backoff = 1.0
                time.sleep(0.5)

            except Exception as e:
                print(f"Poll Error: {e}")
                time.sleep(_backoff)
                _backoff = min(_backoff * 2, 30.0)
