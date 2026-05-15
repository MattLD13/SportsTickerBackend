import math
import time
from datetime import datetime
from PIL import Image, ImageDraw
from ..config import PANEL_W, PANEL_H
from ..fonts import draw_tiny_text


class MiscMixin:

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

    def draw_update_screen(self, step="Updating...", progress=None):
        """LED display shown while the ticker is pulling a code update."""
        img = Image.new("RGBA", (PANEL_W, PANEL_H), (0, 0, 0, 255))
        d = ImageDraw.Draw(img)
        t = time.time()

        # Scrolling cyan highlight bar across top row
        bar_x = int((t * 80) % (PANEL_W + 60)) - 30
        for bx in range(bar_x, bar_x + 60):
            if 0 <= bx < PANEL_W:
                alpha = 1.0 - abs(bx - (bar_x + 30)) / 30.0
                c = int(alpha * 80)
                d.point((bx, 0), fill=(0, c, c))

        # Spinning gear-like dots on the left
        cx, cy = 10, 16
        for i in range(8):
            angle = i * math.pi / 4 + t * 3
            dot_x = int(cx + math.cos(angle) * 7)
            dot_y = int(cy + math.sin(angle) * 7)
            brightness = int(100 + 155 * ((math.sin(angle - t * 3) + 1) / 2))
            d.point((dot_x, dot_y), fill=(0, brightness, brightness))
        # Inner dot
        d.ellipse((cx - 2, cy - 2, cx + 2, cy + 2), fill=(0, 180, 180))

        # Step label
        label = str(step).upper()
        lw = d.textlength(label, font=self.font)
        lx = int((PANEL_W - lw) / 2)
        d.text((lx, 1), label, font=self.font, fill=(200, 220, 220))

        # Animated bouncing dots below text
        dots_y = 20
        for i in range(5):
            phase = t * 4 + i * 0.6
            dy = int(math.sin(phase) * 3)
            bx = PANEL_W // 2 - 12 + i * 6
            d.ellipse((bx, dots_y + dy, bx + 2, dots_y + dy + 2), fill=(0, 200, 255))

        # Progress bar at bottom (if provided)
        d.rectangle((0, 31, PANEL_W - 1, 31), fill=(20, 20, 20))
        if progress is not None:
            fill_w = int(max(0, min(1.0, progress)) * PANEL_W)
            d.rectangle((0, 31, fill_w, 31), fill=(0, 200, 100))
        else:
            # Indeterminate pulse
            pulse_w = 80
            px = int((t * 100) % (PANEL_W + pulse_w)) - pulse_w
            for bx in range(px, px + pulse_w):
                if 0 <= bx < PANEL_W:
                    d.point((bx, 31), fill=(0, 180, 80))

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
