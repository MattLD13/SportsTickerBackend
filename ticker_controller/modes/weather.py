import math
import time
from datetime import datetime
from PIL import Image, ImageDraw
from ..config import PANEL_W, PANEL_H
from ..fonts import draw_tiny_text, draw_hybrid_text, normalize_special_chars


# Forecast temperature trend. `gain` scales the edge brightness, `step` draws
# every Nth pixel for a dashed look, and top/bot set how much vertical travel
# the week's temperature range is allowed.
TREND_STYLE = 'off'
TREND_STYLES = {
    'area': dict(top=11, bot=29, gain=1.00, step=1, fill=True),
    'line': dict(top=11, bot=29, gain=1.00, step=1, fill=False),
    'dim':  dict(top=12, bot=29, gain=0.42, step=1, fill=False),
    'dots': dict(top=12, bot=29, gain=0.60, step=3, fill=False),
    'band': dict(top=19, bot=29, gain=0.45, step=1, fill=False),
    'whisper': dict(top=13, bot=28, gain=0.26, step=1, fill=False),
}


class WeatherMixin:

    def draw_weather_pixel_art(self, d, icon_name, x, y, t=None):
        if t is None:
            t = time.time()
        icon = str(icon_name).lower()
        SUN_Y = (255, 200, 0); CLOUD_W = (205, 210, 220); RAIN_B = (60, 130, 255); SNOW_W = (210, 235, 255)
        if 'sun' in icon or 'clear' in icon:
            # Larger static core (no pulsing)
            cx_s = x + 7; cy_s = y + 7
            core_r = 5
            d.ellipse((cx_s-core_r, cy_s-core_r, cx_s+core_r, cy_s+core_r), fill=SUN_Y)

            # Rotating outer rays: alternate rays swap between "long" and "short" lengths
            rays = 12
            rot_speed = 0.5  # slower rotation
            swap_speed = 1.0
            long_pulse_speed = 3.0
            short_pulse_speed = 3.4
            gap = 3  # gap between core and start of rays
            for i in range(rays):
                phase = (i / float(rays)) * (2 * math.pi)
                angle = phase + t * rot_speed
                # determine current assignment (alternating rays swap over time)
                is_long_now = math.sin(t * swap_speed + i * math.pi) > 0
                # per-category pulsing within desired ranges
                if is_long_now:
                    # long rays pulse between 4 and 5 pixels
                    length_f = 4.0 + 0.5 * (1.0 + math.sin(t * long_pulse_speed + i * 0.4))
                else:
                    # short rays pulse between 2 and 3 pixels
                    length_f = 2.0 + 0.5 * (1.0 + math.sin(t * short_pulse_speed + i * 0.4))
                length = int(round(length_f))
                r1 = core_r + gap
                r2 = core_r + length
                x1 = round(cx_s + math.cos(angle) * r1)
                y1 = round(cy_s + math.sin(angle) * r1)
                x2 = round(cx_s + math.cos(angle) * r2)
                y2 = round(cy_s + math.sin(angle) * r2)
                # color slightly brighter for long rays
                base_int = 210 if is_long_now else 170
                pulse_col_factor = 0.6 + 0.4 * (length_f - 2.0)
                intensity = int(min(255, base_int * pulse_col_factor))
                col = (intensity, int(intensity * 0.9), int(intensity * 0.35))
                d.line([(x1, y1), (x2, y2)], fill=col, width=1)

            # (removed small rotating highlight blobs per request)
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

        # Sky conditions. Every field is optional: the backend and the Pi deploy
        # independently, so an older backend must still render — it just falls
        # back to guessing day/night from the clock the way this always did.
        cloud_pct = sit.get('cloud_cover')
        cloud = None if cloud_pct is None else max(0.0, min(1.0, float(cloud_pct) / 100.0))
        precip = any(k in cur_icon.lower() for k in ('rain', 'snow', 'storm'))

        def _minutes(iso):
            """Minutes past midnight from an Open-Meteo local ISO timestamp."""
            try:
                return int(iso[11:13]) * 60 + int(iso[14:16])
            except (TypeError, ValueError, IndexError):
                return None

        now_h = datetime.now().hour
        obs_m = _minutes(sit.get('obs_time'))
        # The observation timestamp is local to the weather location, so comparing
        # it against sunrise/sunset avoids reconciling the Pi's timezone.
        now_m = obs_m if obs_m is not None else now_h * 60 + datetime.now().minute
        sunrise_m = _minutes(sit.get('sunrise'))
        sunset_m = _minutes(sit.get('sunset'))

        is_day_flag = sit.get('is_day')
        if is_day_flag is not None:
            is_night = not int(is_day_flag)
        else:
            is_night = now_h < 6 or now_h >= 20

        # Where the sun is, as a normalised height: +1 at solar noon, 0 at the
        # horizon, -1 in the dead of night. Driving the palette off this rather
        # than off clock-hour buckets is what stops the sky stepping between
        # states — it now slides through dawn and dusk continuously.
        sr = sunrise_m if sunrise_m is not None else 6 * 60
        ss = sunset_m if sunset_m is not None else 18 * 60
        if ss <= sr:
            ss = sr + 720
        if sr <= now_m <= ss:
            elev = math.sin(math.pi * (now_m - sr) / float(ss - sr))
        else:
            night_len = max(1, 1440 - (ss - sr))
            elev = -math.sin(math.pi * ((now_m - ss) % 1440) / float(night_len))
        if is_day_flag is not None:
            # Keep the sign honest if the backend disagrees with the arithmetic.
            if is_night and elev > 0:
                elev = -elev
            elif not is_night and elev < 0:
                elev = -elev

        # Zenith and horizon colours at each stage of the sun's travel. Every
        # value stays dark: this is a backdrop for 5px text, not a photograph.
        SKY_KEYS = (
            (-1.00, (0, 1,  9), (0,  1, 11)),   # deep night
            (-0.25, (1, 1, 10), (3,  2, 11)),   # nautical twilight
            (-0.08, (3, 2, 12), (14, 4,  8)),   # civil twilight, purple horizon
            ( 0.00, (5, 3, 12), (30, 9,  1)),   # sun on the horizon, peak fire
            ( 0.10, (6, 5, 14), (26, 10, 2)),   # golden hour
            ( 0.35, (2, 7, 20), (6,  11, 24)),  # mid morning / afternoon
            ( 1.00, (1, 8, 24), (3,  12, 30)),  # solar noon
        )

        def sky_gradient(e):
            """Interpolate the zenith/horizon pair for a given sun height."""
            if e <= SKY_KEYS[0][0]:
                return SKY_KEYS[0][1], SKY_KEYS[0][2]
            if e >= SKY_KEYS[-1][0]:
                return SKY_KEYS[-1][1], SKY_KEYS[-1][2]
            for i in range(1, len(SKY_KEYS)):
                if e <= SKY_KEYS[i][0]:
                    lo, hi = SKY_KEYS[i - 1], SKY_KEYS[i]
                    f = (e - lo[0]) / (hi[0] - lo[0])
                    return (
                        tuple(a + (b - a) * f for a, b in zip(lo[1], hi[1])),
                        tuple(a + (b - a) * f for a, b in zip(lo[2], hi[2])),
                    )

        # Precipitation moods, blended over the time-of-day colour rather than
        # replacing it — so rain at midnight reads far darker than rain at noon,
        # which a fixed tint could not express.
        PRECIP_MOOD = {'storm': (7, 2, 12), 'rain': (4, 7, 16), 'snow': (9, 11, 20)}

        def mix(a, b, f):
            return tuple(x + (y - x) * f for x, y in zip(a, b))

        def overcast(base):
            """Wash a sky colour toward flat grey in proportion to cloud cover.

            Without this an solid deck of cloud renders identically to a clear
            sky — the palette only ever varied by precipitation and time of day.
            Real overcast is desaturated and slightly brighter than clear air,
            since the cloud base reflects ground light back down.
            """
            if not cloud:
                return base
            grey = sum(base) / 3.0 + 4.0 * cloud
            return tuple(c + (grey - c) * cloud for c in base)

        def sky_tint(icon):
            ic = icon.lower()
            if 'sun'   in ic: return (8, 4, 0)
            if 'storm' in ic: return (6, 0, 12)
            if 'snow'  in ic: return (1, 3, 10)
            if 'rain'  in ic: return (0, 4, 14)
            return (2, 2, 7)

        def draw_amb(icon, rx, ry, rw, rh, t, dim=1.0):
            ic = icon.lower()
            n = max(2, rw // 20)
            if 'sun' in ic and dim > 0.05:
                _sx = [8,19,31,44,52,63,71,83,94,107,115,14,37,58,76,99,119,25,68,89,103,42,57,112,33]
                _sy = [3,11,5,18,8,25,13,3,21,7, 28, 27,14,2, 23,16,10,20,29,5, 18, 9, 25,19,2 ]
                _sp = [2.1,1.7,2.5,1.9,2.3,1.5,2.0,1.8,2.4,1.6,2.2,2.7,1.4,2.9,1.3,2.6,1.8,2.0,1.5,2.3,1.9,2.4,1.7,2.1,2.8]
                _ph = [0.0,1.3,2.8,0.7,4.2,5.1,3.3,1.9,2.1,4.7,0.5,2.9,0.3,3.6,1.1,5.8,4.4,2.2,0.9,3.1,1.6,5.3,2.5,0.8,4.0]
                n_stars = min(len(_sx), max(14, rw // 8))
                for j in range(n_stars):
                    sx = rx + int(_sx[j] * rw / 124)
                    sy = ry + int(_sy[j] * rh / 32)
                    bv = int(max(0, math.sin(t * _sp[j] + _ph[j])) ** 2 * 230 * dim)
                    if bv > 15 and not (74 <= sx <= 121):
                        d.point((sx, sy), fill=(bv, bv, int(bv * 0.88)))
            if 'storm' in ic:
                fp = t % 6.0
                if fp < 0.07:
                    glow = int((1.0 - fp / 0.07) * 35)
                    d.rectangle((rx, ry, rx + rw - 1, ry + rh - 1), fill=(glow, glow // 2, glow + 12))
                elif 3.2 < fp < 3.27:
                    glow = int((1.0 - (fp - 3.2) / 0.07) * 22)
                    d.rectangle((rx, ry, rx + rw - 1, ry + rh - 1), fill=(glow, glow // 2, glow + 12))
            if 'rain' in ic or 'storm' in ic:
                # Rain was the one common condition with no ambient motion at
                # all — a flat blue field. Short streaks falling fast enough to
                # read as rain rather than snow, and a storm gets them under
                # its lightning too.
                _rfx = [0.05, 0.17, 0.28, 0.40, 0.51, 0.63, 0.74, 0.86, 0.95, 0.34, 0.68]
                _rsp = [26.0, 31.0, 23.0, 29.0, 34.0, 25.0, 30.0, 27.0, 32.0, 28.0, 24.0]
                _rph = [0.0,  5.2,  2.7,  8.1,  3.4,  6.6,  1.2,  7.3,  4.5,  9.0,  2.0]
                for j in range(min(len(_rfx), max(5, rw // 12))):
                    bx = rx + int(_rfx[j] * rw)
                    if not (rx <= bx < rx + rw):
                        continue
                    head = ry + int((t * _rsp[j] + _rph[j] * 7) % (rh + 4)) - 2
                    for k, col in enumerate(((34, 62, 105), (18, 34, 62))):
                        yy = head + k
                        if ry <= yy < ry + rh:
                            d.point((bx, yy), fill=col)
            if 'snow' in ic:
                _sfx = [0.06, 0.22, 0.38, 0.55, 0.72, 0.88, 0.14]
                _ssp = [1.7,  1.4,  1.9,  1.5,  1.8,  1.6,  2.0]
                _sph = [0.0,  2.1,  1.4,  3.5,  4.8,  0.9,  2.7]
                for j in range(min(n + 1, len(_sfx))):
                    bx = rx + int(_sfx[j] * rw) + int(math.sin(t * 0.7 + _sph[j]) * 2)
                    by = ry + int((t * _ssp[j] + _sph[j] * 4) % (rh + 2))
                    if rx <= bx < rx + rw and ry <= by < ry + rh:
                        d.point((bx, by), fill=(40, 60, 100))

        def sky_colors():
            """Final zenith/horizon pair: sun height, then cloud, then precip."""
            top, bot = sky_gradient(elev)
            key = next((k for k in PRECIP_MOOD if k in cur_icon.lower()), None)
            if key:
                # Precipitation already implies a full deck of cloud, so the grey
                # wash would only flatten it. Dim by daylight instead.
                lit = 0.30 + 0.70 * max(0.0, elev)
                mood = tuple(c * lit for c in PRECIP_MOOD[key])
                return mix(top, mood, 0.8), mix(bot, mood, 0.8)
            return overcast(top), overcast(bot)

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

        left_w = 124
        # Flat fill, not a vertical ramp. Sky values live in the bottom tenth of
        # the range, so 32 rows of interpolation only ever resolve to a handful
        # of distinct 8-bit steps — four of them at night — and the panel's PWM
        # quantises those further. On the real hardware it read as three hard
        # bands rather than a gradient. Weighted toward the horizon so sunrise
        # and sunset still warm the whole sky.
        top_c, bot_c = sky_colors()
        sky_c = tuple(int(round(max(0.0, min(255.0, v)))) for v in mix(top_c, bot_c, 0.55))
        d.rectangle((0, 0, left_w, PANEL_H - 1), fill=sky_c)

        if precip:
            draw_amb(cur_icon, 0, 0, left_w, 32, anim_t)
        elif is_night or 'sun' in cur_icon.lower():
            # The same twinkle reads as stars at night and as sunny shimmer by
            # day, which is why it was drawn in daylight too — it is deliberate,
            # not a stray starfield. Cloud thins it either way.
            draw_amb('sun', 0, 0, left_w, 32, anim_t, dim=1.0 - (cloud or 0.0))
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

        def col_bounds(i):
            cx = right_start + (i * col_w)
            return cx, (PANEL_W - 1 if i == 4 else cx + col_w - 1)

        # Pass 1: column backgrounds, so the trend can span all five of them.
        for i, day in enumerate(forecast[:5]):
            cx, col_right = col_bounds(i)
            col_icon = day.get('icon', 'cloud')
            col_t = sky_tint(col_icon)
            bg = col_t if i % 2 == 0 else tuple(max(0, c - 1) for c in col_t)
            d.rectangle((cx, 0, col_right, 31), fill=bg)
            draw_amb(col_icon, cx, 0, col_right - cx + 1, 32, anim_t + i * 1.7)
            if i < 4: d.line((col_right, 3, col_right, 29), fill=DEEP_BLUE)

        # Pass 2: the week's temperature shape, drawn across the whole forecast
        # region. Five independent numbers do not show whether the week is
        # warming or which day is the outlier; an edge following each day's high
        # makes that readable without reading any of them.
        highs = []
        for day in forecast[:5]:
            try:
                highs.append(float(str(day.get('high', '')).replace('°', '')))
            except (TypeError, ValueError):
                highs.append(None)
        pts = [((sum(col_bounds(i)) / 2.0), h) for i, h in enumerate(highs) if h is not None]
        cfg = TREND_STYLES.get(TREND_STYLE)
        if cfg and len(pts) >= 2:
            lo_t = min(h for _, h in pts)
            span = max(1.0, max(h for _, h in pts) - lo_t)
            TOP, BOT = cfg['top'], cfg['bot']

            def trend_at(x):
                if x <= pts[0][0]:
                    t = pts[0][1]
                elif x >= pts[-1][0]:
                    t = pts[-1][1]
                else:
                    for j in range(1, len(pts)):
                        if x <= pts[j][0]:
                            x0, t0 = pts[j - 1]
                            x1, t1 = pts[j]
                            t = t0 + (t1 - t0) * ((x - x0) / (x1 - x0))
                            break
                n = (t - lo_t) / span
                return int(round(TOP + (1.0 - n) * (BOT - TOP))), n

            for x in range(right_start, PANEL_W):
                yv, n = trend_at(x)
                if cfg['fill']:
                    fill = tuple(int(round(a + (b - a) * n))
                                 for a, b in zip((5, 12, 24), (28, 12, 5)))
                    d.line((x, yv + 1, x, 31), fill=fill)
                if (x - right_start) % cfg['step']:
                    continue
                edge = tuple(int(round((a + (b - a) * n) * cfg['gain']))
                             for a, b in zip((70, 120, 190), (255, 140, 70)))
                d.point((x, yv), fill=edge)

        # Pass 3: labels, icons and temperatures on top.
        for i, day in enumerate(forecast[:5]):
            cx, col_right = col_bounds(i)
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
