"""Draw the animated weather icons and the sky behind them. The Six and the Mini share this artwork.

Every animation repeats each ANIMATION_PERIOD seconds, so the Mini can store one loop of frames.
"""
from __future__ import annotations

import math

from PIL import Image, ImageChops, ImageDraw

ANIMATION_PERIOD = 12.6

SUN_YELLOW = (255, 200, 0)
CLOUD_WHITE = (205, 210, 220)
RAIN_BLUE = (60, 130, 255)
SNOW_WHITE = (210, 235, 255)
DEEP_BLUE = (18, 45, 95)

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


def loop_time(t):
    """Keep one microsecond clock precision after the loop wraps."""
    return round(t % ANIMATION_PERIOD, 6) % ANIMATION_PERIOD


def loop_angle(t, cycles):
    """Return a periodic angle for one weather loop."""
    return math.tau * cycles * loop_time(t) / ANIMATION_PERIOD


def loop_travel(t, speed, span, offset=0.0):
    """Keep particle speed close to its target and close the weather loop."""
    cycles = max(1, round(speed * ANIMATION_PERIOD / span))
    distance = (loop_time(t) * cycles / ANIMATION_PERIOD + offset / span) % 1.0 * span
    return round(distance, 9) % span


def loop_flash(t, center, width):
    """Fade a lightning flash across both sides of its cycle boundary."""
    period = ANIMATION_PERIOD / 2.0
    distance = abs((t - center + period / 2.0) % period - period / 2.0)
    return (0.5 + 0.5 * math.cos(math.pi * distance / width)) if distance < width else 0.0


def minutes(iso):
    """Minutes past midnight from an Open-Meteo local ISO timestamp."""
    try:
        return int(iso[11:13]) * 60 + int(iso[14:16])
    except (TypeError, ValueError, IndexError):
        return None


def sun_elevation(now_m, sunrise_m, sunset_m):
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


def mix(a, b, f):
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


def sky_colors(icon, elevation, cloud):
    """Return the final zenith and horizon pair: sun height, then cloud, then precipitation."""
    top, bottom = _sky_gradient(elevation)
    key = next((k for k in PRECIP_MOOD if k in icon.lower()), None)
    if key:
        # Precipitation already implies a full deck of cloud, so the grey wash
        # would only flatten it. Dim by daylight instead.
        lit = 0.30 + 0.70 * max(0.0, elevation)
        mood = tuple(c * lit for c in PRECIP_MOOD[key])
        return mix(top, mood, 0.8), mix(bottom, mood, 0.8)
    return _overcast(top, cloud), _overcast(bottom, cloud)


def sky_tint(icon):
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


def draw_moon(d, x, y):
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


def draw_icon(d, icon_name, x, y, t):
    """Draw one animated 16 pixel weather icon at loop time t."""
    t = loop_time(t)
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
            angle = phase + loop_angle(t, 1)
            # Blend ray lengths instead of switching them at a sign change.
            blend = 0.5 + 0.5 * math.sin(loop_angle(t, 2) + i * math.pi)
            long_length = 4.5 + 0.5 * math.sin(loop_angle(t, 6) + i * 0.4)
            short_length = 2.5 + 0.5 * math.sin(loop_angle(t, 7) + i * 0.4)
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
            off = int(math.sin(loop_angle(t, 1) + i * 1.1) * 2)
            d.line([(x + max(2, 2 + off), fy), (x + min(13, 13 + off), fy)], fill=(170, 175, 195))
    elif 'rain' in icon or 'drizzle' in icon or 'shower' in icon:
        d.ellipse((x + 1, y + 1, x + 14, y + 9), fill=CLOUD_WHITE)
        for i, rx in enumerate([x + 3, x + 7, x + 11, x + 5, x + 9]):
            head = y + 8 + int(loop_travel(t, 5, 10, i * 0.8))
            for k in range(3):
                if y + 10 <= head + k < y + 18:
                    d.point((rx - int(round(k / 2.0)), head + k), fill=RAIN_BLUE)
    elif 'snow' in icon or 'blizzard' in icon:
        d.ellipse((x + 1, y + 1, x + 14, y + 9), fill=(185, 195, 210))
        for i, rx_base in enumerate([x + 3, x + 7, x + 11, x + 5, x + 9]):
            head = y + 9 + int(loop_travel(t, 2, 9, i * 1.3))
            rx = rx_base + int(math.sin(loop_angle(t, 3) + i * 0.9))
            for k in range(2):
                if y + 10 <= head + k < y + 18:
                    d.point((rx, head + k), fill=SNOW_WHITE)
    elif 'storm' in icon or 'thunder' in icon or 'lightning' in icon:
        d.ellipse((x + 1, y + 1, x + 14, y + 9), fill=(75, 80, 100))
        pulse = 0.5 + 0.5 * math.tanh(4 * math.sin(loop_angle(t, 9)))
        bolt_clr = (int(60 + 195 * pulse), int(50 + 170 * pulse), 0)
        d.line([(x + 8, y + 9), (x + 6, y + 13)], fill=bolt_clr, width=1)
        d.line([(x + 6, y + 13), (x + 9, y + 13)], fill=bolt_clr, width=1)
        d.line([(x + 9, y + 13), (x + 7, y + 16)], fill=bolt_clr, width=1)
    elif 'cloud' in icon or 'overcast' in icon:
        d.ellipse((x + 0, y + 6, x + 11, y + 13), fill=(100, 105, 122))
        d.ellipse((x + 4, y + 5, x + 15, y + 13), fill=(165, 170, 185))
        d.ellipse((x + 3, y + 3, x + 13, y + 11), fill=(215, 218, 230))
    elif 'moon' in icon:
        draw_moon(d, x, y)
    else:
        d.ellipse((x + 5, y + 1, x + 12, y + 8), fill=SUN_YELLOW)
        d.point((x + 11, y + 1), fill=SUN_YELLOW)
        d.ellipse((x + 1, y + 5, x + 13, y + 13), fill=(140, 145, 162))
        d.ellipse((x + 7, y + 4, x + 17, y + 12), fill=CLOUD_WHITE)


def draw_sky_motion(img, d, icon, rx, ry, rw, rh, t, dim=1.0, density=1.0, wind=0.0, mask_moon=False):
    """Animate stars, storm glow, rain, and snow inside one sky region."""
    t = loop_time(t)
    text = icon.lower()
    if 'sun' in text and dim > 0.05:
        for star_x, star_y, speed, phase in STARS[:min(len(STARS), max(14, rw // 8))]:
            sx = rx + int(star_x * rw / 124)
            sy = ry + int(star_y * rh / 32)
            cycles = round(speed * ANIMATION_PERIOD / math.tau)
            brightness = int(max(0, math.sin(loop_angle(t, cycles) + phase)) ** 2 * 230 * dim)
            if brightness > 15 and not (74 <= sx <= 121):
                if mask_moon and 0 <= sx <= 23 and 5 <= sy <= 31:
                    continue
                d.point((sx, sy), fill=(brightness, brightness, int(brightness * 0.88)))
    if 'storm' in text:
        glow = int(35 * loop_flash(t, 0.0, 0.07) + 22 * loop_flash(t, ANIMATION_PERIOD * 4 / 15, 0.07))
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
            head = ry - length + 1 + int(loop_travel(t, speed, span, phase * 7))
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
            by = ry - 1 + int(loop_travel(t, speed, rh + 1, phase * 4))
            bx = (rx + int(fraction * rw) + int(math.sin(loop_angle(t, 1) + phase) * 2)
                  + int(round((by - ry - rh / 2.0) * wind)))
            if rx <= bx < rx + rw and ry <= by < ry + rh:
                d.point((bx, by), fill=(40, 60, 100))
