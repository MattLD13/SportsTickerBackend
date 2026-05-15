import io
import math
import time
import random
import colorsys
import requests
from PIL import Image, ImageDraw, ImageOps, ImageStat
from ..config import PANEL_W, PANEL_H
from ..fonts import normalize_special_chars


class MusicMixin:

    def _init_vinyl_scratch(self):
        ds = ImageDraw.Draw(self.scratch_layer)
        ds.ellipse((0, 0, self.VINYL_SIZE-1, self.VINYL_SIZE-1), fill=(20, 20, 20), outline=(50,50,50))

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
