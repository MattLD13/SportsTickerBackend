import math
import time
from datetime import datetime
from PIL import Image, ImageDraw
from ..config import PANEL_W, PANEL_H
from ..fonts import draw_tiny_text, draw_hybrid_text, normalize_special_chars


class WeatherMixin:

    def draw_weather_pixel_art(self, d, icon_name, x, y, t=None):
        if t is None:
            t = time.time()
        icon = str(icon_name).lower()
        SUN_Y = (255, 200, 0); CLOUD_W = (205, 210, 220); RAIN_B = (60, 130, 255); SNOW_W = (210, 235, 255)
        if 'sun' in icon or 'clear' in icon:
            d.ellipse((x+3, y+3, x+11, y+11), fill=SUN_Y)
            cx_s = x + 7; cy_s = y + 7
            for i in range(8):
                angle = i * math.pi / 4 + t * 0.5
                x1 = round(cx_s + math.cos(angle) * 5.5)
                y1 = round(cy_s + math.sin(angle) * 5.5)
                x2 = round(cx_s + math.cos(angle) * 7.5)
                y2 = round(cy_s + math.sin(angle) * 7.5)
                d.line([(x1, y1), (x2, y2)], fill=SUN_Y)
        elif 'fog' in icon or 'mist' in icon or 'haze' in icon:
            for i, fy in enumerate([y+3, y+6, y+9, y+12]):
                off = int(math.sin(t * 0.6 + i * 1.1) * 2)
                d.line([(x + max(2, 2 + off), fy), (x + min(13, 13 + off), fy)], fill=(170, 175, 195))
        elif 'rain' in icon or 'drizzle' in icon or 'shower' in icon:
            d.ellipse((x+1, y+1, x+14, y+9), fill=CLOUD_W)
            for i, rx in enumerate([x+3, x+7, x+11, x+5, x+9]):
                ry = y + 10 + int((t * 5 + i * 0.8) % 6)
                d.line([(rx, ry), (rx - 1, ry + 2)], fill=RAIN_B)
        elif 'snow' in icon or 'blizzard' in icon:
            d.ellipse((x+1, y+1, x+14, y+9), fill=(185, 195, 210))
            for i, rx_base in enumerate([x+3, x+7, x+11, x+5, x+9]):
                ry = y + 10 + int((t * 2 + i * 1.3) % 7)
                rx = rx_base + int(math.sin(t * 1.5 + i * 0.9))
                d.point((rx, ry), fill=SNOW_W)
                d.point((rx, ry + 1), fill=SNOW_W)
        elif 'storm' in icon or 'thunder' in icon or 'lightning' in icon:
            d.ellipse((x+1, y+1, x+14, y+9), fill=(75, 80, 100))
            bolt_clr = (255, 220, 0) if (t % 1.4) < 0.9 else (60, 50, 0)
            d.line([(x+8, y+9), (x+6, y+13)], fill=bolt_clr, width=1)
            d.line([(x+6, y+13), (x+9, y+13)], fill=bolt_clr, width=1)
            d.line([(x+9, y+13), (x+7, y+16)], fill=bolt_clr, width=1)
        elif 'cloud' in icon or 'overcast' in icon:
            d.ellipse((x+0, y+6, x+11, y+13), fill=(100, 105, 122))
            d.ellipse((x+4, y+5, x+15, y+13), fill=(165, 170, 185))
            d.ellipse((x+3, y+3, x+13, y+11), fill=(215, 218, 230))
        else:
            d.ellipse((x+5, y+1, x+12, y+8), fill=SUN_Y)
            d.point((x+11, y+1), fill=SUN_Y)
            d.ellipse((x+1, y+5, x+13, y+13), fill=(140, 145, 162))
            d.ellipse((x+7, y+4, x+17, y+12), fill=CLOUD_W)

    def get_aqi_color(self, aqi):
        try:
            val = int(aqi)
            if val <= 50: return (0, 255, 0)
            if val <= 100: return (255, 255, 0)
            if val <= 150: return (255, 126, 0)
            return (255, 0, 0)
        except:
            return (100, 100, 100)

    def draw_weather_detailed(self, game):
        img = Image.new("RGBA", (PANEL_W, PANEL_H), (0, 0, 0, 255))
        d = ImageDraw.Draw(img)
        sit = game.get('situation', {}) or {}
        stats = sit.get('stats', {}) or {}
        forecast = sit.get('forecast', []) or []
        cur_icon = sit.get('icon', 'cloud')
        anim_t = time.time()
        DEEP_BLUE = (18, 45, 95)

        def sky_tint(icon):
            ic = icon.lower()
            if 'sun'   in ic: return (8, 4, 0)
            if 'storm' in ic: return (6, 0, 12)
            if 'snow'  in ic: return (1, 3, 10)
            if 'rain'  in ic: return (0, 4, 14)
            return (2, 2, 7)

        def draw_amb(icon, rx, ry, rw, rh, t):
            ic = icon.lower()
            n = max(2, rw // 20)
            if 'sun' in ic:
                _sx = [8,19,31,44,52,63,71,83,94,107,115,14,37,58,76,99,119,25,68,89,103,42,57,112,33]
                _sy = [3,11,5,18,8,25,13,3,21,7, 28, 27,14,2, 23,16,10,20,29,5, 18, 9, 25,19,2 ]
                _sp = [2.1,1.7,2.5,1.9,2.3,1.5,2.0,1.8,2.4,1.6,2.2,2.7,1.4,2.9,1.3,2.6,1.8,2.0,1.5,2.3,1.9,2.4,1.7,2.1,2.8]
                _ph = [0.0,1.3,2.8,0.7,4.2,5.1,3.3,1.9,2.1,4.7,0.5,2.9,0.3,3.6,1.1,5.8,4.4,2.2,0.9,3.1,1.6,5.3,2.5,0.8,4.0]
                n_stars = min(len(_sx), max(14, rw // 8))
                for j in range(n_stars):
                    sx = rx + int(_sx[j] * rw / 124)
                    sy = ry + int(_sy[j] * rh / 32)
                    bv = int(max(0, math.sin(t * _sp[j] + _ph[j])) ** 2 * 230)
                    if bv > 15 and not (74 <= sx <= 121):
                        d.point((sx, sy), fill=(bv, bv, int(bv * 0.88)))
            elif 'storm' in ic:
                fp = t % 6.0
                if fp < 0.07:
                    glow = int((1.0 - fp / 0.07) * 35)
                    d.rectangle((rx, ry, rx + rw - 1, ry + rh - 1), fill=(glow, glow // 2, glow + 12))
                elif 3.2 < fp < 3.27:
                    glow = int((1.0 - (fp - 3.2) / 0.07) * 22)
                    d.rectangle((rx, ry, rx + rw - 1, ry + rh - 1), fill=(glow, glow // 2, glow + 12))
            elif 'snow' in ic:
                _sfx = [0.06, 0.22, 0.38, 0.55, 0.72, 0.88, 0.14]
                _ssp = [1.7,  1.4,  1.9,  1.5,  1.8,  1.6,  2.0]
                _sph = [0.0,  2.1,  1.4,  3.5,  4.8,  0.9,  2.7]
                for j in range(min(n + 1, len(_sfx))):
                    bx = rx + int(_sfx[j] * rw) + int(math.sin(t * 0.7 + _sph[j]) * 2)
                    by = ry + int((t * _ssp[j] + _sph[j] * 4) % (rh + 2))
                    if rx <= bx < rx + rw and ry <= by < ry + rh:
                        d.point((bx, by), fill=(40, 60, 100))

        def sky_tint_main(icon, h):
            ic = icon.lower()
            if 'storm' in ic: return (5,  0, 10)
            if 'rain'  in ic: return (0,  3, 12)
            if 'snow'  in ic: return (2,  4, 14)
            if h < 5  or h >= 22: return (0,  1, 10)  # night
            if h < 6:             return (4,  1,  8)  # pre-dawn
            if h < 8:             return (14, 5,  1)  # sunrise
            if h < 11:            return (2,  5, 16)  # morning
            if h < 14:            return (1,  7, 20)  # midday
            if h < 17:            return (2,  6, 15)  # afternoon
            if h < 20:            return (16, 5,  1)  # sunset
            return                       (7,  1,  9)  # dusk

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

        tint = sky_tint(cur_icon)
        d.rectangle((0, 0, PANEL_W - 1, PANEL_H - 1), fill=tint)
        d.line((0, 0, PANEL_W - 1, 0), fill=DEEP_BLUE)

        now_h      = datetime.now().hour
        main_tint  = sky_tint_main(cur_icon, now_h)
        is_night   = now_h < 6 or now_h >= 20
        is_sunrise = 6 <= now_h < 8
        is_sunset  = 17 <= now_h < 20

        left_w = 124
        d.rectangle((0, 0, left_w, 31), fill=main_tint)

        if is_sunrise or is_sunset:
            warm = (22, 7, 0) if is_sunrise else (20, 6, 1)
            for row in range(8):
                intensity = max(0.0, 1.0 - row * 0.13)
                c = tuple(int(v * intensity) for v in warm)
                d.line((0, 31 - row, left_w, 31 - row), fill=c)

        if is_night:
            draw_amb('sun', 0, 0, left_w, 32, anim_t)  # stars always at night
        else:
            draw_amb(cur_icon, 0, 0, left_w, 32, anim_t)
        d.line((left_w, 0, left_w, 31), fill=DEEP_BLUE)

        location_name = normalize_special_chars(str(game.get('away_abbr', 'CITY')).upper()).strip()
        if len(location_name) > 15:
            location_name = location_name[:15]
        draw_tiny_text(d, 4, 2, location_name, (125, 170, 230))

        self.draw_weather_pixel_art(d, cur_icon, 3, 11, t=anim_t)

        temp_disp = "--" if not temp_f else temp_f
        d.text((24, 10), f"{temp_disp}°F", font=self.big_font, fill=temp_color)

        aqi_val   = str(stats.get('aqi',      '--')).strip() or '--'
        uv_val    = str(stats.get('uv',       '--')).strip() or '--'
        feels_val = str(stats.get('feels',    '--')).strip() or '--'
        wind_val  = str(stats.get('wind',     '--')).strip() or '--'
        hum_val   = str(stats.get('humidity', '--')).strip() or '--'
        aqi_col   = self.get_aqi_color(aqi_val)

        try:
            fv = int(float(feels_val))
            if fv >= 90:   feels_col = (255, 90,  35)
            elif fv >= 75: feels_col = (255, 185, 40)
            elif fv >= 55: feels_col = (95,  225, 105)
            elif fv >= 35: feels_col = (95,  190, 255)
            else:          feels_col = (190, 230, 255)
        except Exception:
            feels_col = (240, 240, 245)

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
        if feels_val and feels_val != '--':
            draw_tiny_text(d, 24, 25, f"FEELS {feels_val}F", feels_col)
        elif cond:
            draw_tiny_text(d, 24, 25, cond, (105, 145, 190))

        # 4 stat boxes, each 6px tall, stacked with 2px gaps, centered in the 32px column
        tiny_h = 5
        stat_boxes = [
            ((74, 1,  121, 7),  "AQI",  aqi_val[:4],       (95, 120, 160), aqi_col,           0),
            ((74, 9,  121, 15), "UV",   uv_val[:4],         (95, 120, 160), (210, 155, 255),   0),
            ((74, 17, 121, 23), "HUM",  hum_val[:3] + '%',  (95, 120, 160), (90, 200, 255),    0),
            ((74, 25, 121, 31), "WIND", wind_val[:3],        (95, 120, 160), (90, 200, 255),    2),
        ]
        for box, label, value, lbl_clr, val_clr, tx_off in stat_boxes:
            d.rectangle(box, fill=(2, 6, 14), outline=DEEP_BLUE)
            mid = (box[0] + box[2]) // 2
            lbl_x = box[0] + ((mid - box[0]) - len(label) * 5) // 2
            val_x = mid + ((box[2] - mid + 1) - len(value) * 5) // 2
            ty = box[1] + ((box[3] - box[1] + 1) - tiny_h) // 2
            draw_tiny_text(d, lbl_x + tx_off, ty, label, lbl_clr)
            draw_tiny_text(d, val_x + tx_off, ty, value, val_clr)

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

            col_icon = day.get('icon', 'cloud')
            col_t = sky_tint(col_icon)
            bg = col_t if i % 2 == 0 else tuple(max(0, c - 1) for c in col_t)
            d.rectangle((cx, 0, col_right, 31), fill=bg)
            draw_amb(col_icon, cx, 0, col_right - cx + 1, 32, anim_t + i * 1.7)
            if i < 4: d.line((col_right, 3, col_right, 29), fill=DEEP_BLUE)

            if i == 0:
                day_str = 'TODAY'
            else:
                day_str = time.strftime('%a', time.localtime(time.time() + i * 86400)).upper()
            day_w = len(day_str) * 5
            day_x = cx + max(0, ((col_right - cx + 1) - day_w) // 2)
            lbl_col = (255, 255, 255) if i == 0 else (110, 160, 220)
            draw_tiny_text(d, day_x, 2, day_str, lbl_col)
            d.line((cx + 4, 8, col_right - 4, 8), fill=DEEP_BLUE)

            icon_x = cx + max(0, ((col_right - cx + 1) - 16) // 2)
            self.draw_weather_pixel_art(d, day.get('icon', 'cloud'), icon_x, 9, t=anim_t + i * 1.7)

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
