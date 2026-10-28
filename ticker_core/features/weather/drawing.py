import math
from datetime import datetime, timedelta
from PIL import Image, ImageChops, ImageDraw
from ticker_core.rendering.pixels import draw_tiny_text, normalize_special_chars

PANEL_W = 384
PANEL_H = 32
ANIMATION_PERIOD = 12.6

SUN_YELLOW = (255, 200, 0)
CLOUD_WHITE = (205, 210, 220)
RAIN_BLUE = (60, 130, 255)
SNOW_WHITE = (210, 235, 255)
DEEP_BLUE = (18, 45, 95)
UNKNOWN_TEMPERATURE = (240, 240, 245)

# Left panel width. The forecast columns fill the rest of the panel.
CURRENT_W = 124
FORECAST_X = CURRENT_W + 1
FORECAST_COLUMN_W = (PANEL_W - FORECAST_X) // 5

# Zenith and horizon colours at each stage of the sun's travel. Every value
# stays dark: this is a backdrop for 5px text, not a photograph.
SKY_KEYS = (
    (-1.00, (0, 1, 9), (0, 1, 11)),     # deep night
    (-0.25, (1, 1, 10), (3, 2, 11)),    # nautical twilight
    (-0.08, (3, 2, 12), (14, 4, 8)),    # civil twilight, purple horizon
    (0.00, (5, 3, 12), (30, 9, 1)),     # sun on the horizon, peak fire
    (0.10, (6, 5, 14), (26, 10, 2)),    # golden hour
    (0.35, (2, 7, 20), (6, 11, 24)),    # mid morning / afternoon
    (1.00, (1, 8, 24), (3, 12, 30)),    # solar noon
)

# Precipitation moods, blended over the time-of-day colour rather than
# replacing it — so rain at midnight reads far darker than rain at noon,
# which a fixed tint could not express.
PRECIP_MOOD = {'storm': (7, 2, 12), 'rain': (4, 7, 16), 'snow': (9, 11, 20)}

# Night stars as (x of 124, y of 32, twinkle speed, phase).
STARS = tuple(zip(
    (8, 19, 31, 44, 52, 63, 71, 83, 94, 107, 115, 14, 37, 58, 76, 99, 119, 25, 68, 89, 103, 42, 57, 112, 33),
    (3, 11, 5, 18, 8, 25, 13, 3, 21, 7, 28, 27, 14, 2, 23, 16, 10, 20, 29, 5, 18, 9, 25, 19, 2),
    (2.1, 1.7, 2.5, 1.9, 2.3, 1.5, 2.0, 1.8, 2.4, 1.6, 2.2, 2.7, 1.4, 2.9, 1.3, 2.6, 1.8, 2.0, 1.5, 2.3, 1.9, 2.4, 1.7, 2.1, 2.8),
    (0.0, 1.3, 2.8, 0.7, 4.2, 5.1, 3.3, 1.9, 2.1, 4.7, 0.5, 2.9, 0.3, 3.6, 1.1, 5.8, 4.4, 2.2, 0.9, 3.1, 1.6, 5.3, 2.5, 0.8, 4.0),
))

# Rain streaks as (x fraction, fall speed, phase).
RAIN_STREAKS = tuple(zip(
    (0.05, 0.17, 0.28, 0.40, 0.51, 0.63, 0.74, 0.86, 0.95, 0.34, 0.68),
    (26.0, 31.0, 23.0, 29.0, 34.0, 25.0, 30.0, 27.0, 32.0, 28.0, 24.0),
    (0.0, 5.2, 2.7, 8.1, 3.4, 6.6, 1.2, 7.3, 4.5, 9.0, 2.0),
))

# Snowflakes as (x fraction, fall speed, phase).
SNOWFLAKES = tuple(zip(
    (0.06, 0.22, 0.38, 0.55, 0.72, 0.88, 0.14),
    (1.7, 1.4, 1.9, 1.5, 1.8, 1.6, 2.0),
    (0.0, 2.1, 1.4, 3.5, 4.8, 0.9, 2.7),
))

CONDITION_ABBREVIATIONS = {
    'PARTLY CLOUDY': 'PARTLY CLDY',
    'MOSTLY CLOUDY': 'MOSTLY CLDY',
    'SCATTERED SHOWERS': 'SCT SHOWERS',
    'THUNDERSTORMS': 'T-STORMS',
    'THUNDERSTORM': 'T-STORM',
    'LIGHT RAIN': 'LGT RAIN',
}

# The layout shows this week when the backend sends no forecast.
PLACEHOLDER_FORECAST = (
    {'day': 'MON', 'icon': 'sun', 'high': 80, 'low': 70},
    {'day': 'TUE', 'icon': 'rain', 'high': 75, 'low': 65},
    {'day': 'WED', 'icon': 'cloud', 'high': 78, 'low': 68},
    {'day': 'THU', 'icon': 'storm', 'high': 72, 'low': 60},
    {'day': 'FRI', 'icon': 'sun', 'high': 82, 'low': 72},
)


def _phase(t):
    """Keep one microsecond clock precision after the loop wraps."""
    return round(t % ANIMATION_PERIOD, 6) % ANIMATION_PERIOD


def _angle(t, cycles):
    """Return a periodic angle for one weather loop."""
    return math.tau * cycles * _phase(t) / ANIMATION_PERIOD


def _travel(t, speed, span, offset=0.0):
    """Keep particle speed close to its target and close the weather loop."""
    cycles = max(1, round(speed * ANIMATION_PERIOD / span))
    distance = (_phase(t) * cycles / ANIMATION_PERIOD + offset / span) % 1.0 * span
    return round(distance, 9) % span


def _flash(t, center, width):
    """Fade a lightning flash across both sides of its cycle boundary."""
    period = ANIMATION_PERIOD / 2.0
    distance = abs((t - center + period / 2.0) % period - period / 2.0)
    return (0.5 + 0.5 * math.cos(math.pi * distance / width)) if distance < width else 0.0


def _minutes(iso):
    """Minutes past midnight from an Open-Meteo local ISO timestamp."""
    try:
        return int(iso[11:13]) * 60 + int(iso[14:16])
    except (TypeError, ValueError, IndexError):
        return None


def _sun_elevation(now_m, sunrise_m, sunset_m):
    """Return the sun height: +1 at solar noon, 0 at the horizon, -1 at midnight.

    Driving the palette off this rather than off clock-hour buckets is what
    stops the sky stepping between states.
    """
    sr = sunrise_m if sunrise_m is not None else 6 * 60
    ss = sunset_m if sunset_m is not None else 18 * 60
    if ss <= sr:
        ss = sr + 720
    if sr <= now_m <= ss:
        return math.sin(math.pi * (now_m - sr) / float(ss - sr))
    night_len = max(1, 1440 - (ss - sr))
    return -math.sin(math.pi * ((now_m - ss) % 1440) / float(night_len))


def _sky_gradient(elevation):
    """Interpolate the zenith and horizon pair for a given sun height."""
    if elevation <= SKY_KEYS[0][0]:
        return SKY_KEYS[0][1], SKY_KEYS[0][2]
    if elevation >= SKY_KEYS[-1][0]:
        return SKY_KEYS[-1][1], SKY_KEYS[-1][2]
    for i in range(1, len(SKY_KEYS)):
        if elevation <= SKY_KEYS[i][0]:
            lo, hi = SKY_KEYS[i - 1], SKY_KEYS[i]
            f = (elevation - lo[0]) / (hi[0] - lo[0])
            return (
                tuple(a + (b - a) * f for a, b in zip(lo[1], hi[1])),
                tuple(a + (b - a) * f for a, b in zip(lo[2], hi[2])),
            )


def _mix(a, b, f):
    return tuple(x + (y - x) * f for x, y in zip(a, b))


def _overcast(base, cloud):
    """Wash a sky colour toward flat grey in proportion to cloud cover.

    Real overcast is desaturated and slightly brighter than clear air, since the
    cloud base reflects ground light back down.
    """
    if not cloud:
        return base
    grey = sum(base) / 3.0 + 4.0 * cloud
    return tuple(c + (grey - c) * cloud for c in base)


def _sky_colors(icon, elevation, cloud):
    """Return the final zenith and horizon pair: sun height, then cloud, then precipitation."""
    top, bottom = _sky_gradient(elevation)
    key = next((k for k in PRECIP_MOOD if k in icon.lower()), None)
    if key:
        # Precipitation already implies a full deck of cloud, so the grey wash
        # would only flatten it. Dim by daylight instead.
        lit = 0.30 + 0.70 * max(0.0, elevation)
        mood = tuple(c * lit for c in PRECIP_MOOD[key])
        return _mix(top, mood, 0.8), _mix(bottom, mood, 0.8)
    return _overcast(top, cloud), _overcast(bottom, cloud)


def _sky_tint(icon):
    text = icon.lower()
    if 'sun' in text:
        return (8, 4, 0)
    if 'storm' in text:
        return (6, 0, 12)
    if 'snow' in text:
        return (1, 3, 10)
    if 'rain' in text:
        return (0, 4, 14)
    return (2, 2, 7)


def _temperature_color(text):
    """Return the colour for a Fahrenheit reading, or a neutral colour for no number."""
    try:
        value = int(float(text))
    except (TypeError, ValueError, OverflowError):
        return UNKNOWN_TEMPERATURE
    if value >= 90:
        return (255, 90, 35)
    if value >= 75:
        return (255, 185, 40)
    if value >= 55:
        return (95, 225, 105)
    if value >= 35:
        return (95, 190, 255)
    return (190, 230, 255)


def _stat(stats, key):
    return str(stats.get(key, '--')).strip() or '--'


def _forecast_column(index):
    """Return the left and right x of one of the five forecast columns."""
    left = FORECAST_X + index * FORECAST_COLUMN_W
    return left, (PANEL_W - 1 if index == 4 else left + FORECAST_COLUMN_W - 1)


class PreparedWeatherRenderer:
    """Render the deployed weather layout with explicit render time."""

    def __init__(self, fonts, now: datetime):
        self.big_font = fonts.big
        self.tiny = fonts.tiny
        self._now = now

    def _time(self) -> float:
        """Return the supplied animation clock."""
        return _phase(self._now.timestamp())

    def draw_moon_pixel_art(self, d, x, y):
        """Draw a large stepped grayscale pixel moon with crater detail."""
        cx, cy, radius = x + 7, y + 7, 10
        lit = (184, 184, 184)
        highlight = (232, 232, 232)
        crater_dark = (88, 88, 88)
        crater = (112, 112, 112)
        crater_light = (150, 150, 150)

        crater_patches = (
            (-6, -5, 2), (-2, -6, 1), (2, -6, 2), (6, -4, 1),
            (-7, -1, 1), (-4, -1, 2), (-1, -2, 1), (3, -2, 2),
            (7, 1, 1), (-6, 3, 2), (-2, 4, 1), (2, 3, 2),
            (6, 5, 2), (-2, 7, 1), (1, 6, 1),
        )

        for py in range(cy - radius, cy + radius + 1):
            for px in range(cx - radius, cx + radius + 1):
                nx = (px - cx) / float(radius)
                ny = (py - cy) / float(radius)
                if nx * nx + ny * ny > 1.0:
                    continue
                # Flatten the four diagonal corners so no isolated pixel sticks
                # out of the stepped lunar silhouette.
                if abs(px - cx) >= radius - 3 and abs(py - cy) >= radius - 3:
                    continue
                color = lit
                for crater_x, crater_y, crater_r in crater_patches:
                    distance = (px - cx - crater_x) ** 2 + (py - cy - crater_y) ** 2
                    if distance <= crater_r * crater_r:
                        if distance == crater_r * crater_r:
                            color = crater_dark
                        elif distance <= max(1, (crater_r - 1) ** 2):
                            color = crater_light if distance % 2 else crater
                        else:
                            color = crater
                        break
                if color == lit and (px + 2 * py) % 13 == 0:
                    color = highlight
                d.point((px, py), fill=color)

    def draw_weather_pixel_art(self, d, icon_name, x, y, t):
        """Draw one animated 16 pixel weather icon at loop time t."""
        t = _phase(t)
        icon = str(icon_name).lower()
        if 'sun' in icon or 'clear' in icon:
            # Static core with rotating rays that blend between long and short.
            cx_s, cy_s = x + 7, y + 7
            core_r = 5
            d.ellipse((cx_s - core_r, cy_s - core_r, cx_s + core_r, cy_s + core_r), fill=SUN_YELLOW)
            rays = 12
            gap = 3  # gap between core and start of rays
            for i in range(rays):
                phase = (i / float(rays)) * (2 * math.pi)
                angle = phase + _angle(t, 1)
                # Blend ray lengths instead of switching them at a sign change.
                blend = 0.5 + 0.5 * math.sin(_angle(t, 2) + i * math.pi)
                long_length = 4.5 + 0.5 * math.sin(_angle(t, 6) + i * 0.4)
                short_length = 2.5 + 0.5 * math.sin(_angle(t, 7) + i * 0.4)
                length_f = short_length + (long_length - short_length) * blend
                length = int(round(length_f))
                r1 = core_r + gap
                r2 = core_r + length
                x1 = round(cx_s + math.cos(angle) * r1)
                y1 = round(cy_s + math.sin(angle) * r1)
                x2 = round(cx_s + math.cos(angle) * r2)
                y2 = round(cy_s + math.sin(angle) * r2)
                # Long rays are slightly brighter.
                base_int = 170 + 40 * blend
                pulse_col_factor = 0.6 + 0.4 * (length_f - 2.0)
                intensity = int(min(255, base_int * pulse_col_factor))
                col = (intensity, int(intensity * 0.9), int(intensity * 0.35))
                d.line([(x1, y1), (x2, y2)], fill=col, width=1)
        elif 'fog' in icon or 'mist' in icon or 'haze' in icon:
            for i, fy in enumerate([y + 3, y + 6, y + 9, y + 12]):
                off = int(math.sin(_angle(t, 1) + i * 1.1) * 2)
                d.line([(x + max(2, 2 + off), fy), (x + min(13, 13 + off), fy)], fill=(170, 175, 195))
        elif 'rain' in icon or 'drizzle' in icon or 'shower' in icon:
            d.ellipse((x + 1, y + 1, x + 14, y + 9), fill=CLOUD_WHITE)
            for i, rx in enumerate([x + 3, x + 7, x + 11, x + 5, x + 9]):
                head = y + 8 + int(_travel(t, 5, 10, i * 0.8))
                for k in range(3):
                    if y + 10 <= head + k < y + 18:
                        d.point((rx - int(round(k / 2.0)), head + k), fill=RAIN_BLUE)
        elif 'snow' in icon or 'blizzard' in icon:
            d.ellipse((x + 1, y + 1, x + 14, y + 9), fill=(185, 195, 210))
            for i, rx_base in enumerate([x + 3, x + 7, x + 11, x + 5, x + 9]):
                head = y + 9 + int(_travel(t, 2, 9, i * 1.3))
                rx = rx_base + int(math.sin(_angle(t, 3) + i * 0.9))
                for k in range(2):
                    if y + 10 <= head + k < y + 18:
                        d.point((rx, head + k), fill=SNOW_WHITE)
        elif 'storm' in icon or 'thunder' in icon or 'lightning' in icon:
            d.ellipse((x + 1, y + 1, x + 14, y + 9), fill=(75, 80, 100))
            pulse = 0.5 + 0.5 * math.tanh(4 * math.sin(_angle(t, 9)))
            bolt_clr = (int(60 + 195 * pulse), int(50 + 170 * pulse), 0)
            d.line([(x + 8, y + 9), (x + 6, y + 13)], fill=bolt_clr, width=1)
            d.line([(x + 6, y + 13), (x + 9, y + 13)], fill=bolt_clr, width=1)
            d.line([(x + 9, y + 13), (x + 7, y + 16)], fill=bolt_clr, width=1)
        elif 'cloud' in icon or 'overcast' in icon:
            d.ellipse((x + 0, y + 6, x + 11, y + 13), fill=(100, 105, 122))
            d.ellipse((x + 4, y + 5, x + 15, y + 13), fill=(165, 170, 185))
            d.ellipse((x + 3, y + 3, x + 13, y + 11), fill=(215, 218, 230))
        elif 'moon' in icon:
            self.draw_moon_pixel_art(d, x, y)
        else:
            d.ellipse((x + 5, y + 1, x + 12, y + 8), fill=SUN_YELLOW)
            d.point((x + 11, y + 1), fill=SUN_YELLOW)
            d.ellipse((x + 1, y + 5, x + 13, y + 13), fill=(140, 145, 162))
            d.ellipse((x + 7, y + 4, x + 17, y + 12), fill=CLOUD_WHITE)

    def get_aqi_color(self, aqi):
        try:
            value = int(aqi)
        except (TypeError, ValueError, OverflowError):
            return (100, 100, 100)
        if value <= 50:
            return (0, 255, 0)
        if value <= 100:
            return (255, 255, 0)
        if value <= 150:
            return (255, 126, 0)
        return (255, 0, 0)

    def _draw_ambient(self, img, d, icon, rx, ry, rw, rh, t, dim=1.0, density=1.0, wind=0.0, mask_moon=False):
        """Animate stars, storm glow, rain, and snow inside one sky region."""
        t = _phase(t)
        text = icon.lower()
        if 'sun' in text and dim > 0.05:
            for star_x, star_y, speed, phase in STARS[:min(len(STARS), max(14, rw // 8))]:
                sx = rx + int(star_x * rw / 124)
                sy = ry + int(star_y * rh / 32)
                cycles = round(speed * ANIMATION_PERIOD / math.tau)
                brightness = int(max(0, math.sin(_angle(t, cycles) + phase)) ** 2 * 230 * dim)
                if brightness > 15 and not (74 <= sx <= 121):
                    if mask_moon and 0 <= sx <= 23 and 5 <= sy <= 31:
                        continue
                    d.point((sx, sy), fill=(brightness, brightness, int(brightness * 0.88)))
        if 'storm' in text:
            glow = int(35 * _flash(t, 0.0, 0.07) + 22 * _flash(t, ANIMATION_PERIOD * 4 / 15, 0.07))
            if glow:
                # Fade over the existing sky instead of replacing its tint.
                sky = img.crop((rx, ry, rx + rw, ry + rh))
                light = Image.new("RGBA", (rw, rh), (glow, glow // 2, glow, 0))
                img.paste(ImageChops.add(sky, light), (rx, ry))
        if 'rain' in text or 'storm' in text:
            # Count alone is too coarse at 51px wide, so the streak length and
            # brightness also follow the chance of rain. Three cues moving
            # together make an 11-point difference in chance visible.
            available = min(len(RAIN_STREAKS), max(6, rw // 4))
            shade = 0.45 + 0.55 * density
            length = 2 + int(round(3 * density))
            for fraction, speed, phase in RAIN_STREAKS[:max(1, int(round(available * density)))]:
                bx0 = rx + int(fraction * rw)
                span = rh + length - 1
                head = ry - length + 1 + int(_travel(t, speed, span, phase * 7))
                for k in range(length):
                    yy = head + k
                    # Lean about the column's middle, so a strong tilt slants
                    # the field rather than shoving it off one edge.
                    bx = bx0 + int(round((yy - ry - rh / 2.0) * wind))
                    if ry <= yy < ry + rh and rx <= bx < rx + rw:
                        fade = shade * (1.0 - k / float(length + 1))
                        d.point((bx, yy), fill=tuple(int(c * fade) for c in (44, 80, 132)))
        if 'snow' in text:
            available = min(max(2, rw // 20) + 1, len(SNOWFLAKES))
            for fraction, speed, phase in SNOWFLAKES[:max(1, int(round(available * density)))]:
                by = ry - 1 + int(_travel(t, speed, rh + 1, phase * 4))
                bx = (rx + int(fraction * rw) + int(math.sin(_angle(t, 1) + phase) * 2)
                      + int(round((by - ry - rh / 2.0) * wind)))
                if rx <= bx < rx + rw and ry <= by < ry + rh:
                    d.point((bx, by), fill=(40, 60, 100))

    def draw_weather_detailed(self, game):
        """Render current conditions on the left and five forecast columns on the right."""
        img = Image.new("RGBA", (PANEL_W, PANEL_H), (0, 0, 0, 255))
        d = ImageDraw.Draw(img)
        sit = game.get('situation', {}) or {}
        stats = sit.get('stats', {}) or {}
        forecast = sit.get('forecast', []) or []
        cur_icon = sit.get('icon', 'cloud')
        anim_t = self._time()

        # Every sky field is optional: the backend and the Pi deploy
        # independently, so an older backend falls back to the clock.
        cloud_pct = sit.get('cloud_cover')
        cloud = None if cloud_pct is None else max(0.0, min(1.0, float(cloud_pct) / 100.0))
        precip = any(k in cur_icon.lower() for k in ('rain', 'snow', 'storm'))
        # The observation time is local to the weather location, so comparing it
        # against sunrise and sunset avoids reconciling the Pi's timezone.
        obs_m = _minutes(sit.get('obs_time'))
        now_m = obs_m if obs_m is not None else self._now.hour * 60 + self._now.minute
        is_day_flag = sit.get('is_day')
        if is_day_flag is not None:
            is_night = not int(is_day_flag)
        else:
            is_night = self._now.hour < 6 or self._now.hour >= 20
        elevation = _sun_elevation(now_m, _minutes(sit.get('sunrise')), _minutes(sit.get('sunset')))
        if is_day_flag is not None and ((is_night and elevation > 0) or (not is_night and elevation < 0)):
            # Keep the sign honest if the backend disagrees with the arithmetic.
            elevation = -elevation
        icon_for_render = str(cur_icon).lower()
        if is_night and ('sun' in icon_for_render or 'clear' in icon_for_render):
            icon_for_render = 'moon'

        temp_f = str(game.get('home_abbr', '--')).replace('°', '').strip()
        temp_color = _temperature_color(temp_f)

        d.rectangle((0, 0, PANEL_W - 1, PANEL_H - 1), fill=_sky_tint(cur_icon))
        d.line((0, 0, PANEL_W - 1, 0), fill=DEEP_BLUE)
        # Flat fill, not a vertical ramp. Sky values live in the bottom tenth of
        # the range, so a 32-row ramp resolves to only a few 8-bit steps, and the
        # panel PWM showed them as hard bands. The horizon weight still lets
        # sunrise and sunset warm the whole sky.
        top_c, bot_c = _sky_colors(cur_icon, elevation, cloud)
        sky_c = tuple(int(round(max(0.0, min(255.0, v)))) for v in _mix(top_c, bot_c, 0.55))
        d.rectangle((0, 0, CURRENT_W, PANEL_H - 1), fill=sky_c)
        if precip:
            self._draw_ambient(img, d, cur_icon, 0, 0, CURRENT_W, 32, anim_t)
        elif is_night:
            # Stars only at night, thinned by cloud. Against a bright sky the
            # twinkle reads as speckle.
            self._draw_ambient(img, d, 'sun', 0, 0, CURRENT_W, 32, anim_t,
                               dim=1.0 - (cloud or 0.0), mask_moon=icon_for_render == 'moon')
        d.line((CURRENT_W, 0, CURRENT_W, 31), fill=DEEP_BLUE)

        location_name = normalize_special_chars(str(game.get('away_abbr', 'CITY')).upper()).strip()
        draw_tiny_text(d, 4, 2, location_name[:15], (125, 170, 230))
        self.draw_weather_pixel_art(d, icon_for_render, 3, 11, t=anim_t)
        d.text((24, 10), f"{temp_f or '--'}°F", font=self.big_font, fill=temp_color)

        aqi_val = _stat(stats, 'aqi')
        uv_val = _stat(stats, 'uv')
        feels_val = _stat(stats, 'feels')
        wind_val = _stat(stats, 'wind')
        hum_val = _stat(stats, 'humidity')
        condition = normalize_special_chars(str(game.get('status', '')).upper()).strip()
        condition = CONDITION_ABBREVIATIONS.get(condition, condition)[:19]
        if feels_val != '--':
            draw_tiny_text(d, 24, 25, f"FEELS {feels_val}F", _temperature_color(feels_val))
        elif condition:
            draw_tiny_text(d, 24, 25, condition, (105, 145, 190))
        self._draw_stat_boxes(d, (
            ((74, 1, 121, 7), "AQI", aqi_val[:4], self.get_aqi_color(aqi_val), 0),
            ((74, 9, 121, 15), "UV", uv_val[:4], (210, 155, 255), 0),
            ((74, 17, 121, 23), "HUM", hum_val[:3] + '%', (90, 200, 255), 0),
            ((74, 25, 121, 31), "WIND", wind_val[:3], (90, 200, 255), 2),
        ))

        days = (forecast or PLACEHOLDER_FORECAST)[:5]
        # Draw every column background first, then the labels on top.
        for i, day in enumerate(days):
            self._draw_forecast_background(img, d, i, day, anim_t + i * 1.7)
        for i, day in enumerate(days):
            self._draw_forecast_labels(d, i, day, anim_t + i * 1.7)
        return img

    @staticmethod
    def _draw_stat_boxes(d, boxes):
        """Draw stacked label and value boxes. Each box is 6px tall with a 2px gap."""
        tiny_h = 5
        for box, label, value, value_color, x_offset in boxes:
            d.rectangle(box, fill=(2, 6, 14), outline=DEEP_BLUE)
            mid = (box[0] + box[2]) // 2
            label_x = box[0] + ((mid - box[0]) - len(label) * 5) // 2
            value_x = mid + ((box[2] - mid + 1) - len(value) * 5) // 2
            ty = box[1] + ((box[3] - box[1] + 1) - tiny_h) // 2
            draw_tiny_text(d, label_x + x_offset, ty, label, (95, 120, 160))
            draw_tiny_text(d, value_x + x_offset, ty, value, value_color)

    def _draw_forecast_background(self, img, d, index, day, t):
        left, right = _forecast_column(index)
        icon = day.get('icon', 'cloud')
        tint = _sky_tint(icon)
        d.rectangle((left, 0, right, 31), fill=tint if index % 2 == 0 else tuple(max(0, c - 1) for c in tint))
        # Both fields are optional. Without them a column animates at full density.
        density, wind = 1.0, 0.0
        pop = day.get('pop')
        if pop is not None:
            # The icon maps a 20% chance and a certainty both to 'rain', so the
            # density carries the difference. The sigmoid is centred on 40%,
            # where forecast chances cluster, and steep through the middle so
            # neighbouring days separate.
            density = 1.0 / (1.0 + math.exp(-(float(pop) / 100.0 - 0.40) / 0.16))
        gust = day.get('wind')
        if gust is not None:
            # Lean the streaks with the day's peak wind. Daily maxima cluster
            # around 5-15mph.
            wind = max(-0.9, min(0.9, (float(gust) - 3.0) / 12.0))
        # dim=0 suppresses the twinkle: a column is a whole day, not a night sky.
        self._draw_ambient(img, d, icon, left, 0, right - left + 1, 32, t, dim=0.0, density=density, wind=wind)
        if index < 4:
            d.line((right, 3, right, 29), fill=DEEP_BLUE)

    def _draw_forecast_labels(self, d, index, day, t):
        left, right = _forecast_column(index)
        width = right - left + 1
        day_text = 'TODAY' if index == 0 else (self._now + timedelta(days=index)).strftime('%a').upper()
        draw_tiny_text(d, left + max(0, (width - len(day_text) * 5) // 2), 2, day_text,
                       (255, 255, 255) if index == 0 else (110, 160, 220))
        d.line((left + 4, 8, right - 4, 8), fill=DEEP_BLUE)
        self.draw_weather_pixel_art(d, day.get('icon', 'cloud'), left + max(0, (width - 16) // 2), 9, t=t)
        high = str(day.get('high', '--')).replace('°', '')
        low = str(day.get('low', '--')).replace('°', '')
        tx = left + max(0, (width - (len(high) * 5 + 5 + len(low) * 5)) // 2)
        draw_tiny_text(d, tx, 26, high, (255, 115, 75))
        draw_tiny_text(d, tx + len(high) * 5, 26, "/", (70, 88, 120))
        draw_tiny_text(d, tx + len(high) * 5 + 5, 26, low, (90, 165, 255))
