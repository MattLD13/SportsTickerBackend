#!/usr/bin/env python3
"""Render alternative full-bleed sport layouts as 384x32 concept frames.

Exploration only — nothing here is wired into the controller. Every concept
keeps the real playing surface as the motif; they differ in how the surface
carries the data and how text is made readable on top of it.

Three techniques replace the current full-height side scrims:
  * halo text   — a tight dark halo hugging each glyph, so the field shows
                  through everywhere else instead of 65% of it being blacked out
  * field zoom  — show the 30 yards / one zone / one half that actually matters,
                  so the markings are large enough to read at 32px tall
  * perspective — a shallow broadcast camera angle, which yields a natural
                  crowd band for the score bug without covering the field

  python tools/render_fullbleed_concepts.py
  python tools/render_fullbleed_concepts.py --sport nfl
"""

from __future__ import annotations

import argparse
import os
import sys

from PIL import Image, ImageDraw, ImageFilter

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from ticker_controller.config import PANEL_H, PANEL_W  # noqa: E402
from ticker_controller.fonts import draw_hybrid_text  # noqa: E402
from tools.fetch_and_render import make_renderer  # noqa: E402

W, H = PANEL_W, PANEL_H
OUT_DIR = "previews/fullbleed_concepts"

BLACK = (0, 0, 0)
WHITE = (255, 255, 255)


# ── colour helpers ──────────────────────────────────────────────────────────

def hexc(s):
    s = str(s).lstrip("#")
    return tuple(int(s[i:i + 2], 16) for i in (0, 2, 4))


def mix(c1, c2, t):
    return tuple(int(a + (b - a) * t) for a, b in zip(c1, c2))


def dim(c, f):
    return tuple(max(0, min(255, int(v * f))) for v in c)


def lerp(a, b, t):
    return a + (b - a) * t


# ── frame + text ────────────────────────────────────────────────────────────

def new_frame(bg=BLACK):
    img = Image.new("RGBA", (W, H), bg + (255,))
    return img, ImageDraw.Draw(img, "RGBA")


def _halo(img, mask, spread=2, alpha=225):
    """Composite a dark halo shaped like the given text mask."""
    grown = mask.filter(ImageFilter.MaxFilter(spread * 2 + 1))
    grown = grown.filter(ImageFilter.GaussianBlur(0.8))
    shadow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    shadow.putalpha(grown.point(lambda v: int(v * alpha / 255)))
    img.alpha_composite(shadow)


def halo_text(img, d, x, y, text, font, fill, anchor="mm", spread=2, alpha=230):
    """Big TTF text that stays readable on top of the field without a scrim."""
    mask = Image.new("L", (W, H), 0)
    ImageDraw.Draw(mask).text((x, y), str(text), font=font, fill=255, anchor=anchor)
    _halo(img, mask, spread, alpha)
    d.text((x, y), str(text), font=font, fill=fill, anchor=anchor)


def halo_hyb(img, d, x, y, text, fill, spread=1, alpha=235):
    """4x6 bitmap text with the same halo treatment."""
    mask = Image.new("L", (W, H), 0)
    draw_hybrid_text(ImageDraw.Draw(mask), int(x), int(y), str(text), 255)
    _halo(img, mask, spread, alpha)
    draw_hybrid_text(d, int(x), int(y), str(text), fill)


def hyb_w(text):
    return 5 * len(str(text))


def halo_hyb_c(img, d, cx, y, text, fill, **kw):
    halo_hyb(img, d, int(cx - hyb_w(text) / 2), y, text, fill, **kw)


def hyb(d, x, y, text, color):
    return draw_hybrid_text(d, int(x), int(y), str(text), color)


def hyb_c(d, cx, y, text, color):
    return hyb(d, int(cx - hyb_w(text) / 2), y, text, color)


def tint_sweep(img, color, alpha_fn, x0=0, x1=W, y0=0, y1=H):
    """Horizontal alpha gradient, composited properly.

    PIL's ImageDraw replaces pixels rather than blending when the ink carries an
    alpha channel, so every gradient has to go through its own overlay.
    """
    ov = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    od = ImageDraw.Draw(ov)
    x0, x1 = int(x0), int(x1)
    for x in range(x0, x1):
        a = int(alpha_fn((x - x0) / max(1, x1 - x0 - 1)))
        if a > 0:
            od.line([(x, y0), (x, y1)], fill=color + (max(0, min(255, a)),))
    img.alpha_composite(ov)


def pips(d, x, y, count, total, on_color, off_color=(58, 58, 58), w=3, gap=2, h=3):
    for i in range(total):
        px = x + i * (w + gap)
        d.rectangle([px, y, px + w - 1, y + h - 1],
                    fill=on_color if i < count else off_color)
    return x + total * (w + gap) - gap


def paste_logo(img, r, url, size, x, y):
    logo = r.get_logo(url, (size, size))
    if logo:
        if logo.size != (size, size):
            logo = logo.resize((size, size), Image.LANCZOS)
        img.paste(logo, (int(x), int(y)), logo)


# ═══════════════════════════════════════════════════════════════════════════
# Playing-surface backgrounds
# ═══════════════════════════════════════════════════════════════════════════

GRASS_A, GRASS_B = (20, 50, 18), (26, 62, 23)


def bg_gridiron(d, ez_w, left_c, right_c, rz_side=None, y0=0, y1=H):
    """Plan-view 100 yard field, end zones in team colour."""
    play_w = W - 2 * ez_w
    for i in range(10):
        bx = ez_w + i * play_w / 10
        d.rectangle([bx, y0, bx + play_w / 10, y1], fill=GRASS_A if i % 2 == 0 else GRASS_B)
    for i in range(11):
        lx = ez_w + i * play_w / 10
        d.line([(lx, y0), (lx, y1)], fill=(255, 255, 255, 130 if i == 5 else 65))
    hy1, hy2 = y0 + (y1 - y0) * 0.34, y0 + (y1 - y0) * 0.66
    for k in range(1, 100):
        hx = ez_w + k / 100 * play_w
        big = k % 5 == 0
        hl = 2 if big else 1
        for hy in (hy1, hy2):
            d.line([(hx, hy - hl), (hx, hy + hl)], fill=(255, 255, 255, 115 if big else 55))
    d.rectangle([0, y0, ez_w, y1], fill=left_c)
    d.rectangle([W - ez_w, y0, W, y1], fill=right_c)
    d.line([(ez_w, y0), (ez_w, y1)], fill=(255, 255, 255, 225))
    d.line([(W - ez_w, y0), (W - ez_w, y1)], fill=(255, 255, 255, 225))
    if rz_side:
        ov = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        od = ImageDraw.Draw(ov, "RGBA")
        if rz_side == "right":
            x0 = ez_w + int(play_w * 0.8)
            for x in range(x0, W - ez_w):
                od.line([(x, y0), (x, y1)],
                        fill=(205, 30, 20, int(155 * (x - x0) / max(1, W - ez_w - x0))))
        else:
            x1 = ez_w + int(play_w * 0.2)
            for x in range(ez_w, x1):
                od.line([(x, y0), (x, y1)],
                        fill=(205, 30, 20, int(155 * (x1 - x) / max(1, x1 - ez_w))))
        return ov
    return None


def bg_gridiron_zoom(d, y_lo, y_hi, los, fd, ez_side=None, ez_color=None):
    """Zoomed field: only the yards between y_lo and y_hi, so the markings are
    large enough to actually read at 32px tall."""
    span = y_hi - y_lo

    def yx(yard):
        return (yard - y_lo) / span * W

    for band in range(int(y_lo // 5) * 5, int(y_hi) + 5, 5):
        d.rectangle([yx(band), 0, yx(band + 5), H],
                    fill=GRASS_A if (band // 5) % 2 == 0 else GRASS_B)
    if ez_side == "right" and ez_color and yx(100) < W:
        d.rectangle([yx(100), 0, W, H], fill=ez_color)
        d.line([(yx(100), 0), (yx(100), H)], fill=WHITE, width=2)
    # Pre-mixed markings: alpha ink would replace the grass, not blend with it.
    line_major = mix(GRASS_B, WHITE, 0.72)
    line_minor = mix(GRASS_B, WHITE, 0.42)
    hash_col = mix(GRASS_B, WHITE, 0.5)
    num_col = mix(GRASS_B, WHITE, 0.62)
    for yard in range(int(y_lo), int(y_hi) + 1):
        x = yx(yard)
        if yard % 5 == 0:
            d.line([(x, 0), (x, H)], fill=line_major if yard % 10 == 0 else line_minor)
            if yard % 10 == 0 and 0 < yard < 100:
                num = yard if yard <= 50 else 100 - yard
                hyb_c(d, x, 2, str(num), num_col)
                hyb_c(d, x, H - 8, str(num), num_col)
        else:
            for hy in (12, 20):
                d.line([(x, hy - 1), (x, hy + 1)], fill=hash_col)
    return yx


def bg_gridiron_persp(d, left_c, right_c, horizon=7):
    """Shallow sideline camera: yard lines converge, the crowd band above the
    field is the natural home for the score bug."""
    FAR_L, FAR_R, NEAR_L, NEAR_R = 46.0, W - 46.0, -70.0, W + 70.0

    def px(t, y):
        f = (y - horizon) / (H - horizon)
        return lerp(lerp(FAR_L, NEAR_L, f), lerp(FAR_R, NEAR_R, f), t)

    def quad(t0, t1):
        return [(px(t0, horizon), horizon), (px(t1, horizon), horizon),
                (px(t1, H), H), (px(t0, H), H)]

    # Crowd band.
    for y in range(horizon):
        d.line([(0, y), (W, y)], fill=(16, 16, 22))
    for i in range(0, W, 3):
        for y in (1, 3, 5):
            d.point((i + (y % 3), y), fill=(48, 48, 62))
    ez = 0.09
    for i in range(10):
        t0 = ez + (1 - 2 * ez) * i / 10
        t1 = ez + (1 - 2 * ez) * (i + 1) / 10
        d.polygon(quad(t0, t1), fill=GRASS_A if i % 2 == 0 else GRASS_B)
    d.polygon(quad(0, ez), fill=left_c)
    d.polygon(quad(1 - ez, 1), fill=right_c)
    line_major = mix(GRASS_B, WHITE, 0.75)
    line_minor = mix(GRASS_B, WHITE, 0.4)
    hash_major = mix(GRASS_B, WHITE, 0.5)
    hash_minor = mix(GRASS_B, WHITE, 0.26)
    for i in range(11):
        t = ez + (1 - 2 * ez) * i / 10
        d.line([(px(t, horizon), horizon), (px(t, H), H)],
               fill=line_major if i in (0, 5, 10) else line_minor)
    for hy in (int(horizon + (H - horizon) * 0.42), int(horizon + (H - horizon) * 0.72)):
        for k in range(1, 100):
            t = ez + (1 - 2 * ez) * k / 100
            d.line([(px(t, hy), hy - 1), (px(t, hy), hy + 1)],
                   fill=hash_major if k % 5 == 0 else hash_minor)
    return px


def bg_rink(d, y0=0, y1=H):
    d.rectangle([0, y0, W, y1], fill=(200, 224, 247))
    bl1, bl2 = W * 0.30, W * 0.70
    gl1, gl2 = W * 0.085, W * 0.915
    d.rectangle([0, y0, bl1, y1], fill=(190, 215, 243))
    d.rectangle([bl2, y0, W, y1], fill=(190, 215, 243))
    d.rectangle([bl1 - 1, y0, bl1 + 1, y1], fill=(34, 85, 204))
    d.rectangle([bl2 - 1, y0, bl2 + 1, y1], fill=(34, 85, 204))
    mid = (y0 + y1) / 2
    for i in range(6):
        ry = y0 + i * (y1 - y0) / 6
        d.rectangle([W / 2 - 0.5, ry, W / 2 + 0.5, ry + (y1 - y0) / 6 * 0.7], fill=(204, 26, 26))
    d.line([(gl1, y0), (gl1, y1)], fill=(204, 26, 26))
    d.line([(gl2, y0), (gl2, y1)], fill=(204, 26, 26))
    fy1, fy2 = y0 + (y1 - y0) * 0.28, y0 + (y1 - y0) * 0.72
    for fx, fy in [(bl1 * 0.5, fy1), (bl1 * 0.5, fy2),
                   (bl2 + (W - bl2) * 0.5, fy1), (bl2 + (W - bl2) * 0.5, fy2)]:
        d.ellipse([fx - 7, fy - 7, fx + 7, fy + 7], outline=(204, 26, 26, 95))
        d.ellipse([fx - 2, fy - 2, fx + 2, fy + 2], fill=(204, 26, 26, 190))
    d.ellipse([W / 2 - 12, mid - 12, W / 2 + 12, mid + 12], outline=(204, 26, 26, 125))
    nh = 9
    ny = mid - nh / 2
    d.rectangle([gl1, ny, gl1 + 4, ny + nh], fill=(228, 228, 228), outline=(150, 150, 150))
    d.rectangle([gl2 - 4, ny, gl2, ny + nh], fill=(228, 228, 228), outline=(150, 150, 150))
    return bl1, bl2, gl1, gl2


def bg_rink_zone_zoom(img, d, attack_c):
    """One offensive zone, blue line to end boards, at readable scale."""
    d.rectangle([0, 0, W, H], fill=(202, 226, 248))
    blue = 24
    # Attacking-team tint stays light so the ice still reads as ice.
    tint_sweep(img, attack_c, lambda t: 60 * t ** 1.2, x0=blue, x1=W)
    d.rectangle([blue - 2, 0, blue + 2, H], fill=(34, 85, 204))
    gl = W - 54
    d.line([(gl, 0), (gl, H)], fill=(204, 26, 26), width=2)
    for fy in (7, H - 8):
        d.ellipse([120 - 26, fy - 13, 120 + 26, fy + 13], outline=(204, 26, 26, 150))
        d.ellipse([120 - 2, fy - 2, 120 + 2, fy + 2], fill=(204, 26, 26))
        d.ellipse([236 - 26, fy - 13, 236 + 26, fy + 13], outline=(204, 26, 26, 150))
        d.ellipse([236 - 2, fy - 2, 236 + 2, fy + 2], fill=(204, 26, 26))
    d.arc([gl - 20, H / 2 - 15, gl + 20, H / 2 + 15], start=90, end=270, fill=(70, 140, 240), width=2)
    d.rectangle([gl - 1, H / 2 - 7, gl + 7, H / 2 + 7], fill=(232, 232, 232), outline=(140, 140, 140))
    for gy in range(int(H / 2 - 7), int(H / 2 + 8), 3):
        d.line([(gl, gy), (gl + 7, gy)], fill=(170, 170, 170))
    d.rectangle([W - 3, 0, W - 1, H], fill=(215, 225, 238))
    return blue, gl


def bg_court(d, y0=0, y1=H):
    d.rectangle([0, y0, W, y1], fill=(188, 114, 55))
    lw = W * 0.16
    lh = (y1 - y0) * 0.62
    ly = y0 + ((y1 - y0) - lh) / 2
    mid = (y0 + y1) / 2
    d.rectangle([1, y0 + 1, W - 2, y1 - 2], outline=(255, 255, 255, 130))
    d.line([(W / 2, y0), (W / 2, y1)], fill=(255, 255, 255, 120))
    d.ellipse([W / 2 - 10, mid - 10, W / 2 + 10, mid + 10], outline=(255, 255, 255, 110))
    d.rectangle([0, ly, lw, ly + lh], fill=(152, 78, 32), outline=(255, 255, 255, 140))
    d.rectangle([W - lw, ly, W, ly + lh], fill=(152, 78, 32), outline=(255, 255, 255, 140))
    thr = (y1 - y0) * 0.54
    d.arc([-thr, ly - 4, thr, ly + lh + 4], start=270, end=90, fill=(255, 255, 255, 110))
    d.arc([W - thr, ly - 4, W + thr, ly + lh + 4], start=90, end=270, fill=(255, 255, 255, 110))
    return lw, lh, ly


def bg_court_halfzoom(img, d, tint):
    """Attacking half-court, baseline on the right, at readable scale."""
    d.rectangle([0, 0, W, H], fill=(190, 116, 56))
    tint_sweep(img, tint, lambda t: 58 * t ** 2)  # subtle pull toward the basket
    d.line([(2, 0), (2, H)], fill=(255, 255, 255, 150), width=1)   # half-court line
    d.arc([2 - 22, H / 2 - 22, 2 + 22, H / 2 + 22], start=270, end=90, fill=(255, 255, 255, 120))
    base = W - 6
    d.line([(base, 0), (base, H)], fill=(255, 255, 255, 190), width=1)
    lw = 120
    d.rectangle([base - lw, 4, base, H - 5], fill=(150, 76, 30), outline=(255, 255, 255, 175))
    d.ellipse([base - lw - 13, H / 2 - 13, base - lw + 13, H / 2 + 13], outline=(255, 255, 255, 150))
    d.arc([base - 250, -22, base + 30, H + 22], start=100, end=260, fill=(255, 255, 255, 150))
    d.line([(base - 16, H / 2 - 7), (base - 16, H / 2 + 7)], fill=(235, 235, 235))
    d.ellipse([base - 24, H / 2 - 4, base - 16, H / 2 + 4], outline=(240, 120, 40), width=1)
    return base, lw


def bg_diamond_field(d, big=False):
    """Plan-view infield. `big` scales the diamond to nearly the panel height."""
    cx, cy = W / 2, H * (0.52 if big else 0.55)
    r = H * (0.46 if big else 0.42)
    for i in range(12):
        bx = i * W / 12
        d.rectangle([bx, 0, bx + W / 12, H], fill=(16, 40, 16) if i % 2 == 0 else (21, 50, 21))
    d.ellipse([cx - r * 1.45, cy + r * 0.1 - r * 1.15, cx + r * 1.45, cy + r * 0.1 + r * 1.15],
              fill=(156, 104, 67))
    bs = H * (0.17 if big else 0.16)
    d.polygon([(cx, cy + r - 2), (cx + r - 2, cy), (cx, cy - r + bs + 1), (cx - r + 2, cy)],
              fill=(16, 40, 16), outline=(156, 104, 67))
    pr = r * 0.22
    d.ellipse([cx - pr, cy - pr, cx + pr, cy + pr], fill=(156, 104, 67))
    d.rectangle([cx - 1.5, cy - 0.5, cx + 1.5, cy + 0.5], fill=WHITE)
    hpr = r * 0.3
    d.ellipse([cx - hpr, cy + r - hpr, cx + hpr, cy + r + hpr], fill=(156, 104, 67))
    return cx, cy, r, bs


def bases_on(d, cx, cy, r, bs, on1, on2, on3):
    pts = {"1": (cx + r, cy), "2": (cx, cy - r), "3": (cx - r, cy), "H": (cx, cy + r)}
    for a, b in (("H", "1"), ("1", "2"), ("2", "3"), ("3", "H")):
        d.line([pts[a], pts[b]], fill=(255, 255, 255, 205))
    for key, on in (("3", on3), ("1", on1), ("2", on2)):
        x, y = pts[key]
        top = max(1, y - bs)
        d.polygon([(x, top), (x + bs, y), (x, y + bs), (x - bs, y)],
                  fill=(255, 205, 0) if on else WHITE, outline=BLACK)
    x, y = pts["H"]
    s = r * 0.13
    d.polygon([(x, y + s), (x + s, y), (x + s, y - s), (x - s, y - s), (x - s, y)],
              fill=WHITE, outline=BLACK)


def bg_ballpark_wide(d):
    """Whole park from behind home plate: foul lines out to an outfield arc."""
    d.rectangle([0, 0, W, H], fill=(14, 36, 14))
    for i in range(14):
        bx = i * W / 14
        d.rectangle([bx, 0, bx + W / 14, H], fill=(16, 42, 16) if i % 2 == 0 else (21, 51, 21))
    hx, hy = W / 2, H - 2
    d.pieslice([hx - 300, hy - 300, hx + 300, hy + 300], start=222, end=318, fill=(19, 47, 19))
    d.arc([hx - 300, hy - 300, hx + 300, hy + 300], start=222, end=318,
          fill=(150, 100, 64), width=2)
    d.line([(hx, hy), (hx - 210, 0)], fill=(255, 255, 255, 190))
    d.line([(hx, hy), (hx + 210, 0)], fill=(255, 255, 255, 190))
    d.ellipse([hx - 62, hy - 46, hx + 62, hy + 46], fill=(156, 104, 67))
    d.polygon([(hx, hy - 4), (hx + 30, hy - 22), (hx, hy - 40), (hx - 30, hy - 22)],
              fill=(19, 47, 19), outline=(156, 104, 67))
    for bx, by in ((hx + 30, hy - 22), (hx, hy - 40), (hx - 30, hy - 22)):
        d.polygon([(bx, by - 3), (bx + 3, by), (bx, by + 3), (bx - 3, by)], fill=WHITE)
    d.ellipse([hx - 7, hy - 27, hx + 7, hy - 17], fill=(156, 104, 67))
    return hx, hy


def bg_pitch(d, y0=0, y1=H):
    for i in range(12):
        x0, x1 = int(i * W / 12), int((i + 1) * W / 12)
        d.rectangle([x0, y0, x1, y1], fill=(19, 98, 37) if i % 2 == 0 else (15, 86, 32))
    mid = (y0 + y1) / 2
    d.rectangle([1, y0 + 1, W - 2, y1 - 2], outline=(235, 235, 235, 180))
    d.line([(W / 2, y0), (W / 2, y1)], fill=(235, 235, 235, 160))
    d.ellipse([W / 2 - 11, mid - 11, W / 2 + 11, mid + 11], outline=(235, 235, 235, 160))
    for bx0, bx1 in ((1, 13), (W - 14, W - 2)):
        d.rectangle([bx0, y0 + 6, bx1, y1 - 7], outline=(235, 235, 235, 140))
    for gx0, gx1 in ((1, 5), (W - 6, W - 2)):
        d.rectangle([gx0, mid - 5, gx1, mid + 5], outline=(235, 235, 235, 150))


def bg_pitch_boxzoom(img, d, attack_c):
    """Penalty area at readable scale — set pieces, penalties, shootouts."""
    for i in range(10):
        x0, x1 = int(i * W / 10), int((i + 1) * W / 10)
        d.rectangle([x0, 0, x1, H], fill=(19, 98, 37) if i % 2 == 0 else (15, 86, 32))
    tint_sweep(img, attack_c, lambda t: 55 * t ** 2)
    goal_x = W - 14
    box_x = 168
    d.rectangle([box_x, 1, goal_x, H - 2], outline=(242, 242, 242))            # 18-yard box
    d.rectangle([goal_x - 62, 9, goal_x, H - 10], outline=(228, 228, 228))     # 6-yard box
    spot = goal_x - 104
    d.ellipse([spot - 2, H / 2 - 2, spot + 2, H / 2 + 2], fill=(245, 245, 245))
    d.arc([box_x - 22, H / 2 - 13, box_x + 22, H / 2 + 13], start=272, end=88,
          fill=(228, 228, 228))                                               # D, opening left
    d.rectangle([goal_x, H / 2 - 10, W - 3, H / 2 + 10], fill=(226, 230, 238),
                outline=(255, 255, 255))                                      # goal + net
    for gy in range(int(H / 2 - 10), int(H / 2 + 11), 3):
        d.line([(goal_x + 1, gy), (W - 4, gy)], fill=(158, 166, 180))
    for gx in range(int(goal_x) + 3, W - 3, 4):
        d.line([(gx, H / 2 - 10), (gx, H / 2 + 10)], fill=(158, 166, 180))
    return goal_x


# ═══════════════════════════════════════════════════════════════════════════
# NFL — BUF 24 @ KC 27, Q4 1:47, 3rd & 6 at BUF 22, KC ball, red zone
# ═══════════════════════════════════════════════════════════════════════════

NFL = dict(
    left_ab="BUF", right_ab="KC",
    left_c=hexc("00338D"), right_c=hexc("E31837"),
    left_logo="https://a.espncdn.com/i/teamlogos/nfl/500/buf.png",
    right_logo="https://a.espncdn.com/i/teamlogos/nfl/500/kc.png",
    left_score=24, right_score=27,
    clock="1:47", quarter="Q4", down="3RD & 6", spot="BUF 22",
    los=78, fd=84, to_left=2, to_right=1,
)


def nfl_1_live_field(r):
    """Full field kept edge to edge; halo text instead of side scrims."""
    g = NFL
    img, d = new_frame()
    ez = 46
    ov = bg_gridiron(d, ez, g["left_c"], g["right_c"], rz_side="right")
    if ov:
        img.alpha_composite(ov)
    play_w = W - 2 * ez
    los_x = ez + play_w * g["los"] / 100
    fd_x = ez + play_w * g["fd"] / 100
    d.line([(fd_x, 0), (fd_x, H)], fill=(245, 220, 0), width=2)
    d.line([(los_x, 0), (los_x, H)], fill=(40, 90, 235), width=2)
    d.ellipse([los_x - 4, H / 2 - 3, los_x + 4, H / 2 + 3], fill=(150, 78, 24), outline=(60, 26, 6))
    d.line([(los_x - 2, H // 2), (los_x + 2, H // 2)], fill=(255, 255, 255, 210))
    for k in range(3):
        cx = los_x + 8 + k * 4
        d.polygon([(cx, 3), (cx + 3, 5), (cx, 7)], fill=(255, 255, 255, 110))

    for cx, sc, logo in ((ez // 2, g["left_score"], g["left_logo"]),
                         (W - ez // 2, g["right_score"], g["right_logo"])):
        paste_logo(img, r, logo, 14, cx - 7, 1)
        halo_text(img, d, cx, 23, sc, r.huge_font, WHITE)
    halo_hyb_c(img, d, W // 2, 1, g["down"], (255, 165, 55))
    halo_hyb_c(img, d, W // 2, H - 8, f"{g['quarter']} {g['clock']}   {g['spot']}", WHITE)
    return img


def nfl_2_field_zoom(r):
    """Zoom to the 30 yards around the ball: the markings finally read."""
    g = NFL
    img, d = new_frame()
    lo, hi = g["los"] - 14, g["los"] + 16
    yx = bg_gridiron_zoom(d, lo, hi, g["los"], g["fd"],
                          ez_side="right", ez_color=g["right_c"])
    rz0 = yx(80)
    ov = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    od = ImageDraw.Draw(ov, "RGBA")
    for x in range(int(max(0, rz0)), int(yx(100))):
        od.line([(x, 0), (x, H)], fill=(205, 30, 20, int(120 * (x - rz0) / max(1, yx(100) - rz0))))
    img.alpha_composite(ov)
    d.line([(yx(g["fd"]), 0), (yx(g["fd"]), H)], fill=(245, 220, 0), width=3)
    d.line([(yx(g["los"]), 0), (yx(g["los"]), H)], fill=(40, 95, 240), width=3)
    bx = yx(g["los"])
    d.ellipse([bx - 7, H / 2 - 5, bx + 7, H / 2 + 5], fill=(150, 78, 24), outline=(55, 24, 6))
    d.line([(bx - 4, H // 2), (bx + 4, H // 2)], fill=(255, 255, 255, 225))
    for k in range(3):
        d.polygon([(bx + 12 + k * 5, H // 2 - 3), (bx + 16 + k * 5, H // 2), (bx + 12 + k * 5, H // 2 + 3)],
                  fill=(255, 255, 255, 120 - k * 30))

    # Whole-field mini-map so the zoom never loses context.
    d.rectangle([0, 0, W - 1, 3], fill=(6, 6, 8))
    d.rectangle([2, 0, W - 3, 3], fill=(24, 56, 21))
    d.rectangle([2, 0, 8, 3], fill=g["left_c"])
    d.rectangle([W - 9, 0, W - 3, 3], fill=g["right_c"])
    mmx = lambda p: 2 + (W - 11) * p / 100
    d.rectangle([mmx(lo), 0, mmx(hi), 3], fill=mix((24, 56, 21), WHITE, 0.28))
    d.line([(mmx(g["fd"]), 0), (mmx(g["fd"]), 3)], fill=(245, 220, 0))
    d.line([(mmx(g["los"]), 0), (mmx(g["los"]), 3)], fill=(90, 150, 255))

    halo_hyb(img, d, 5, 6, f"{g['left_ab']} {g['left_score']}", WHITE)
    halo_text(img, d, 5, 19, g["down"], r.big_font, (255, 175, 60), anchor="lm")
    halo_hyb(img, d, 5, 26, f"{g['quarter']} {g['clock']}", (225, 225, 225))
    t = f"{g['right_score']} {g['right_ab']}"
    halo_hyb(img, d, W - 6 - hyb_w(t), 6, t, WHITE)
    halo_hyb(img, d, W - 6 - hyb_w("RED ZONE"), 25, "RED ZONE", (255, 225, 120))
    return img


def nfl_3_field_perspective(r):
    """Broadcast camera angle — the crowd band carries the bug, field untouched."""
    g = NFL
    img, d = new_frame()
    px = bg_gridiron_persp(d, g["left_c"], g["right_c"], horizon=8)
    for t, col, wdt in ((g["fd"] / 100 * 0.82 + 0.09, (245, 220, 0), 2),
                        (g["los"] / 100 * 0.82 + 0.09, (40, 95, 240), 2)):
        d.line([(px(t, 8), 8), (px(t, H), H)], fill=col, width=wdt)
    bt = g["los"] / 100 * 0.82 + 0.09
    by = 22
    d.ellipse([px(bt, by) - 5, by - 3, px(bt, by) + 5, by + 3],
              fill=(150, 78, 24), outline=(55, 24, 6))
    d.rectangle([0, 0, W - 1, 7], fill=(14, 14, 20))
    paste_logo(img, r, g["left_logo"], 7, 3, 0)
    paste_logo(img, r, g["right_logo"], 7, W - 10, 0)
    hyb(d, 12, 1, f"{g['left_ab']} {g['left_score']}", WHITE)
    t2 = f"{g['right_score']} {g['right_ab']}"
    hyb(d, W - 12 - hyb_w(t2), 1, t2, WHITE)
    hyb_c(d, W // 2, 1, f"{g['quarter']}  {g['clock']}", (255, 225, 120))
    halo_text(img, d, W // 2, 19, g["down"], r.big_font, WHITE)
    halo_hyb_c(img, d, W // 2, 26, g["spot"], (255, 175, 60))
    return img


def nfl_4_redzone_zoom(r):
    """Goal-line camera: the end zone becomes a third of the panel."""
    g = NFL
    img, d = new_frame()
    lo, hi = 70, 106
    yx = bg_gridiron_zoom(d, lo, hi, g["los"], g["fd"],
                          ez_side="right", ez_color=g["right_c"])
    ov = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    od = ImageDraw.Draw(ov, "RGBA")
    for x in range(int(yx(80)), int(yx(100))):
        od.line([(x, 0), (x, H)], fill=(215, 25, 15, int(135 * (x - yx(80)) / (yx(100) - yx(80)))))
    img.alpha_composite(ov)
    d.line([(yx(80), 0), (yx(80), H)], fill=(255, 80, 60), width=2)
    ezc = (yx(100) + W) / 2
    d.rectangle([yx(100) + 1, 0, W, H], fill=g["right_c"])   # clean end zone, no hashes
    hyb(d, ezc - hyb_w(g["right_ab"]) / 2, H // 2 - 3, g["right_ab"], (245, 245, 245))
    d.line([(yx(g["fd"]), 0), (yx(g["fd"]), H)], fill=(245, 220, 0), width=3)
    d.line([(yx(g["los"]), 0), (yx(g["los"]), H)], fill=(40, 95, 240), width=3)
    bx = yx(g["los"])
    d.ellipse([bx - 7, H / 2 - 5, bx + 7, H / 2 + 5], fill=(150, 78, 24), outline=(55, 24, 6))
    halo_hyb(img, d, 4, 2, f"{g['left_ab']} {g['left_score']}", WHITE)
    halo_hyb(img, d, 4, 25, f"{g['right_ab']} {g['right_score']}", WHITE)
    halo_text(img, d, 58, 16, g["clock"], r.big_font, (255, 105, 85), anchor="lm")
    halo_hyb(img, d, 118, 4, "RED ZONE", (255, 235, 140))
    halo_hyb(img, d, 118, 23, g["down"], WHITE)
    return img


# ═══════════════════════════════════════════════════════════════════════════
# NHL — TOR 1 @ DET 3, 3rd 10:15, DET on the power play
# ═══════════════════════════════════════════════════════════════════════════

NHL = dict(
    left_ab="TOR", right_ab="DET",
    left_c=hexc("003E7E"), right_c=hexc("CE1126"),
    left_logo="https://a.espncdn.com/i/teamlogos/nhl/500/tor.png",
    right_logo="https://a.espncdn.com/i/teamlogos/nhl/500/det.png",
    left_score=1, right_score=3, sog_left=18, sog_right=28,
    period="3RD", clock="10:15", pp_left="1:22",
    left_shots=[(0.13, 0.30), (0.19, 0.62), (0.09, 0.48), (0.22, 0.22), (0.16, 0.78),
                (0.11, 0.66), (0.24, 0.55), (0.07, 0.40)],
    right_shots=[(0.88, 0.30), (0.82, 0.55), (0.91, 0.45), (0.78, 0.70), (0.85, 0.20),
                 (0.93, 0.62), (0.80, 0.38), (0.87, 0.75), (0.76, 0.50)],
)


def nhl_1_live_rink(r):
    """Ice edge to edge; only the glyphs get a halo."""
    g = NHL
    img, d = new_frame()
    bg_rink(d)
    paste_logo(img, r, g["left_logo"], 18, 4, 2)
    paste_logo(img, r, g["right_logo"], 18, W - 22, 2)
    halo_text(img, d, 26, 14, g["left_score"], r.clock_giant, WHITE, anchor="lm")
    halo_text(img, d, W - 26, 14, g["right_score"], r.clock_giant, WHITE, anchor="rm")
    halo_hyb(img, d, 4, 24, f"SOG {g['sog_left']}", (235, 240, 250))
    t = f"SOG {g['sog_right']}"
    halo_hyb(img, d, W - 5 - hyb_w(t), 24, t, (235, 240, 250))
    halo_text(img, d, W // 2, 13, g["clock"], r.big_font, WHITE)
    halo_hyb_c(img, d, W // 2, 21, g["period"], (240, 245, 255))
    d.rectangle([W // 2, 0, W - 1, 2], fill=(210, 220, 235))
    d.rectangle([W // 2, 0, W // 2 + int((W / 2) * 0.61), 2], fill=g["right_c"])
    halo_hyb(img, d, W // 2 + 44, 4, f"PP {g['pp_left']}", (255, 205, 60))
    return img


def nhl_2_shot_map(r):
    """The rink stops being wallpaper and starts plotting shots on goal."""
    g = NHL
    img, d = new_frame()
    bg_rink(d)
    for shots, col in ((g["left_shots"], g["left_c"]), (g["right_shots"], g["right_c"])):
        for i, (fx, fy) in enumerate(shots):
            x, y = fx * W, fy * H
            rad = 2 if i % 3 else 3
            d.ellipse([x - rad, y - rad, x + rad, y + rad],
                      fill=col + (240,), outline=(255, 255, 255, 160))
    halo_text(img, d, W // 2 - 26, 14, g["left_score"], r.clock_giant, WHITE)
    halo_text(img, d, W // 2 + 26, 14, g["right_score"], r.clock_giant, WHITE)
    halo_hyb_c(img, d, W // 2, 24, f"{g['period']} {g['clock']}", WHITE)
    halo_hyb(img, d, 4, 2, f"{g['left_ab']} {g['sog_left']} SOG", WHITE)
    t = f"{g['sog_right']} SOG {g['right_ab']}"
    halo_hyb(img, d, W - 5 - hyb_w(t), 2, t, WHITE)
    return img


def nhl_3_zone_tint(r):
    """Ice kept; each attacking zone is tinted with the team attacking it, so
    team identity comes from the surface instead of a 3px edge stripe."""
    g = NHL
    img, d = new_frame()
    bl1, bl2, gl1, gl2 = bg_rink(d)
    ov = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    od = ImageDraw.Draw(ov, "RGBA")
    for x in range(int(bl1)):
        od.line([(x, 0), (x, H)], fill=g["right_c"] + (int(150 * (1 - x / bl1) ** 1.3),))
    for x in range(int(bl2), W):
        t = max(0.0, (x - bl2) / (W - bl2))
        od.line([(x, 0), (x, H)], fill=g["left_c"] + (int(150 * t ** 1.3),))
    img.alpha_composite(ov)
    paste_logo(img, r, g["right_logo"], 16, 4, 2)
    paste_logo(img, r, g["left_logo"], 16, W - 20, 2)
    halo_text(img, d, 24, 16, g["right_score"], r.clock_giant, WHITE, anchor="lm")
    halo_text(img, d, W - 24, 16, g["left_score"], r.clock_giant, WHITE, anchor="rm")
    halo_hyb(img, d, 4, 24, f"{g['right_ab']} ATTACKING", (255, 220, 220))
    t = f"{g['left_ab']} ATTACKING"
    halo_hyb(img, d, W - 5 - hyb_w(t), 24, t, (215, 228, 255))
    halo_text(img, d, W // 2, 12, g["clock"], r.big_font, WHITE)
    halo_hyb_c(img, d, W // 2, 20, f"{g['period']}  {g['sog_right']}-{g['sog_left']} SOG", WHITE)
    return img


def nhl_4_zone_zoom(r):
    """Power play: zoom the ice to the offensive zone that actually matters."""
    g = NHL
    img, d = new_frame()
    blue, gl = bg_rink_zone_zoom(img, d, g["right_c"])
    for i, (fx, fy) in enumerate(g["right_shots"]):
        x = blue + (fx - 0.70) / 0.30 * (W - blue)
        y = 4 + fy * (H - 11)
        if x < blue:
            continue
        rad = 2 if i % 3 else 3
        d.ellipse([x - rad, y - rad, x + rad, y + rad],
                  fill=g["right_c"], outline=(255, 255, 255))
    d.rectangle([0, 0, blue - 3, H], fill=(12, 14, 20))
    paste_logo(img, r, g["right_logo"], 14, 3, 1)
    hyb(d, 3, 17, str(g["right_score"]), WHITE)
    hyb(d, 3, 25, f"{g['sog_right']}SH", (200, 200, 210))
    halo_hyb(img, d, blue + 6, 2, f"{g['right_ab']} POWER PLAY", (255, 210, 70))
    halo_text(img, d, blue + 8, 16, g["pp_left"], r.big_font, (255, 210, 70), anchor="lm")
    halo_hyb(img, d, blue + 10, 24, "5v4", WHITE)
    halo_hyb(img, d, 150, 2, f"{g['period']} {g['clock']}", WHITE)
    halo_text(img, d, 150, 18, f"{g['right_score']}-{g['left_score']}", r.big_font, WHITE, anchor="lm")
    d.rectangle([blue, H - 3, W - 1, H - 1], fill=(40, 40, 48))
    d.rectangle([blue, H - 3, blue + int((W - blue) * 0.61), H - 1], fill=(255, 210, 70))
    return img


# ═══════════════════════════════════════════════════════════════════════════
# NBA — BOS 108 @ LAL 110, Q4 1:12
# ═══════════════════════════════════════════════════════════════════════════

NBA = dict(
    left_ab="BOS", right_ab="LAL",
    left_c=hexc("007A33"), right_c=hexc("552583"),
    left_logo="https://a.espncdn.com/i/teamlogos/nba/500/bos.png",
    right_logo="https://a.espncdn.com/i/teamlogos/nba/500/lal.png",
    left_score=108, right_score=110,
    quarter="Q4", clock="1:12", shot_clock=14,
    fouls_left=4, fouls_right=5, to_left=1, to_right=2,
    run_left=2, run_right=9,
    shots=[(0.62, 0.30, 1), (0.70, 0.62, 1), (0.55, 0.45, 0), (0.80, 0.25, 1),
           (0.74, 0.75, 0), (0.88, 0.50, 1), (0.66, 0.18, 0), (0.58, 0.80, 1)],
)


def nba_1_live_court(r):
    """Court kept; markings now carry state (bonus, shot clock, possession)."""
    g = NBA
    img, d = new_frame()
    bg_court(d)
    paste_logo(img, r, g["left_logo"], 16, 3, 2)
    paste_logo(img, r, g["right_logo"], 16, W - 19, 2)
    halo_text(img, d, 22, 15, g["left_score"], r.clock_giant, WHITE, anchor="lm")
    halo_text(img, d, W - 22, 15, g["right_score"], r.clock_giant, WHITE, anchor="rm")
    halo_hyb(img, d, 3, 25, f"{g['left_ab']}  FLS {g['fouls_left']}", (255, 235, 190))
    t = f"FLS {g['fouls_right']} BONUS  {g['right_ab']}"
    halo_hyb(img, d, W - 4 - hyb_w(t), 25, t, (255, 150, 120))
    sweep = int(360 * g["shot_clock"] / 24)
    d.arc([W / 2 - 15, H / 2 - 15, W / 2 + 15, H / 2 + 15], start=-90, end=-90 + sweep,
          fill=(255, 195, 65), width=2)
    halo_text(img, d, W // 2, 13, g["clock"], r.big_font, WHITE)
    halo_hyb_c(img, d, W // 2, 21, f"{g['quarter']}  :{g['shot_clock']}", (255, 235, 190))
    d.polygon([(W // 2 + 34, 4), (W // 2 + 40, 7), (W // 2 + 34, 10)], fill=g["right_c"])
    return img


def nba_2_court_run(r):
    """The hardwood itself is the run meter — the floor stains toward whoever is
    on a run, and every court marking survives on top of it."""
    g = NBA
    img, d = new_frame()
    bg_court(d)
    total = g["run_left"] + g["run_right"]
    split = int(W * (g["run_left"] / total)) if total else W // 2
    ov = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    od = ImageDraw.Draw(ov, "RGBA")
    for x in range(split):
        od.line([(x, 0), (x, H)], fill=g["left_c"] + (int(165 * (1 - x / max(1, split)) ** 0.8),))
    for x in range(split, W):
        od.line([(x, 0), (x, H)],
                fill=g["right_c"] + (int(165 * ((x - split) / max(1, W - split)) ** 0.8),))
    img.alpha_composite(ov)
    d.line([(split, 0), (split, H)], fill=(255, 255, 255, 210), width=1)
    paste_logo(img, r, g["left_logo"], 16, 3, 2)
    paste_logo(img, r, g["right_logo"], 16, W - 19, 2)
    halo_text(img, d, 22, 15, g["left_score"], r.clock_giant, WHITE, anchor="lm")
    halo_text(img, d, W - 22, 15, g["right_score"], r.clock_giant, WHITE, anchor="rm")
    halo_hyb_c(img, d, W // 2, 2, f"{g['quarter']}  {g['clock']}", WHITE)
    halo_hyb_c(img, d, W // 2, 25, f"{g['right_ab']} ON A {g['run_right']}-{g['run_left']} RUN",
               (255, 225, 120))
    return img


def nba_3_halfcourt_zoom(r):
    """Zoom the court to the attacking half so the paint and arc read properly."""
    g = NBA
    img, d = new_frame()
    base, lw = bg_court_halfzoom(img, d, g["right_c"])
    for fx, fy, made in g["shots"]:
        x, y = fx * W, fy * H
        if made:
            d.ellipse([x - 3, y - 3, x + 3, y + 3], fill=g["right_c"], outline=WHITE)
        else:
            d.line([(x - 3, y - 3), (x + 3, y + 3)], fill=(240, 240, 240, 200))
            d.line([(x - 3, y + 3), (x + 3, y - 3)], fill=(240, 240, 240, 200))
    paste_logo(img, r, g["right_logo"], 16, 3, 2)
    halo_hyb(img, d, 3, 21, f"{g['right_ab']} BALL", (240, 220, 255))
    halo_text(img, d, 44, 11, f"{g['right_score']}", r.clock_giant, WHITE, anchor="lm")
    halo_hyb(img, d, 44, 25, f"{g['left_ab']} {g['left_score']}", (215, 240, 220))
    halo_text(img, d, 168, 12, g["clock"], r.big_font, WHITE, anchor="lm")
    halo_hyb(img, d, 168, 22, f"{g['quarter']}  SHOT :{g['shot_clock']}", (255, 235, 190))
    sweep = int(360 * g["shot_clock"] / 24)
    d.arc([base - 34, H / 2 - 15, base - 4, H / 2 + 15], start=-90, end=-90 + sweep,
          fill=(255, 195, 65), width=2)
    return img


def nba_4_court_perspective(r):
    """Baseline camera: converging sidelines, scorer's-table band for the bug."""
    g = NBA
    img, d = new_frame()
    horizon = 7
    FAR_L, FAR_R, NEAR_L, NEAR_R = 60.0, W - 60.0, -60.0, W + 60.0

    def px(t, y):
        f = (y - horizon) / (H - horizon)
        return lerp(lerp(FAR_L, NEAR_L, f), lerp(FAR_R, NEAR_R, f), t)

    for y in range(horizon):
        d.line([(0, y), (W, y)], fill=(16, 16, 22))
    for i in range(0, W, 3):
        d.point((i, 2), fill=(46, 46, 60))
        d.point((i + 1, 4), fill=(40, 40, 54))
    for y in range(horizon, H):
        f = (y - horizon) / (H - horizon)
        d.line([(px(0, y), y), (px(1, y), y)], fill=mix((150, 92, 44), (206, 128, 62), f))
    # Painted lanes first, then the lines that sit on top of them.
    for t0, t1, c in ((0.0, 0.20, g["left_c"]), (0.80, 1.0, g["right_c"])):
        ov = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        od = ImageDraw.Draw(ov)
        for y in range(horizon, H):
            od.line([(px(t0, y), y), (px(t1, y), y)], fill=c + (135,))
        img.alpha_composite(ov)
    for t in (0.0, 0.20, 0.5, 0.80, 1.0):
        d.line([(px(t, horizon), horizon), (px(t, H), H)], fill=(238, 238, 238))
    for y in range(horizon, H):  # centre circle, two arms narrowing with depth
        f = (y - horizon) / (H - horizon)
        if 0.25 < f < 0.9:
            hw = 0.085 * (1 - ((f - 0.575) / 0.325) ** 2) ** 0.5
            for side in (-1, 1):
                cx_ = px(0.5 + side * hw, y)
                d.line([(cx_, y), (cx_ + 1, y)], fill=(232, 232, 232))
    d.rectangle([0, 0, W - 1, horizon - 1], fill=(14, 14, 20))
    paste_logo(img, r, g["left_logo"], 7, 2, 0)
    paste_logo(img, r, g["right_logo"], 7, W - 9, 0)
    hyb(d, 11, 1, f"{g['left_ab']} {g['left_score']}", WHITE)
    t = f"{g['right_score']} {g['right_ab']}"
    hyb(d, W - 11 - hyb_w(t), 1, t, WHITE)
    hyb_c(d, W // 2, 1, f"{g['quarter']} {g['clock']}", (255, 225, 120))
    halo_text(img, d, W // 2, 18, f"{g['left_score']}-{g['right_score']}", r.big_font, WHITE)
    halo_hyb_c(img, d, W // 2, 25, f"{g['right_ab']} BALL   SHOT :{g['shot_clock']}", (255, 235, 190))
    return img


# ═══════════════════════════════════════════════════════════════════════════
# MLB — CHC 4 @ STL 5, bottom 9th, bases loaded, 3-2, 2 out
# ═══════════════════════════════════════════════════════════════════════════

MLB = dict(
    left_ab="CHC", right_ab="STL",
    left_c=hexc("0E3386"), right_c=hexc("C41E3A"),
    left_logo="https://a.espncdn.com/i/teamlogos/mlb/500/chc.png",
    right_logo="https://a.espncdn.com/i/teamlogos/mlb/500/stl.png",
    left_score=4, right_score=5,
    inning=9, half="BOT", balls=3, strikes=2, outs=2,
    on1=True, on2=True, on3=True,
    pitcher="HELSLEY", p_count=14, p_last="98 FF", p_era="1.91",
    batter="SUZUKI", b_line="2-4", b_avg=".285",
    hits_left=9, hits_right=11,
    zone=[(0.30, 0.28, "B"), (0.62, 0.66, "S"), (0.16, 0.80, "B"),
          (0.55, 0.40, "S"), (0.80, 0.20, "B"), (0.48, 0.52, "F")],
    spray=[(-0.62, 0.72), (0.35, 0.55), (-0.18, 0.88), (0.70, 0.40),
           (0.10, 0.66), (-0.45, 0.35), (0.52, 0.80)],
)


def mlb_1_console(r):
    """Diamond kept centre; the side lanes become labelled stat cards on grass."""
    g = MLB
    img, d = new_frame()
    cx, cy, rad, bs = bg_diamond_field(d)
    bases_on(d, cx, cy, rad, bs, g["on1"], g["on2"], g["on3"])
    paste_logo(img, r, g["left_logo"], 16, 3, 1)
    paste_logo(img, r, g["right_logo"], 16, W - 19, 1)
    halo_text(img, d, 22, 9, g["left_score"], r.huge_font, WHITE, anchor="lm")
    halo_text(img, d, W - 22, 9, g["right_score"], r.huge_font, WHITE, anchor="rm")
    halo_hyb(img, d, 3, 22, g["left_ab"], (225, 225, 225))
    halo_hyb(img, d, W - 4 - hyb_w(g["right_ab"]), 22, g["right_ab"], (225, 225, 225))
    halo_hyb(img, d, 60, 3, "PITCHING", (150, 190, 255))
    halo_hyb(img, d, 60, 12, g["pitcher"], WHITE)
    halo_hyb(img, d, 60, 21, f"P{g['p_count']}  {g['p_last']}", (225, 225, 225))
    for txt, y, c in (("AT BAT", 3, (255, 165, 165)), (g["batter"], 12, WHITE),
                      (f"{g['b_line']}  {g['b_avg']}", 21, (225, 225, 225))):
        halo_hyb(img, d, W - 60 - hyb_w(txt), y, txt, c)
    halo_hyb_c(img, d, cx, 1, f"{'V' if g['half'] == 'BOT' else '^'}{g['inning']}", WHITE)
    x = pips(d, int(cx) - 22, H - 5, g["balls"], 3, (70, 175, 255))
    pips(d, int(cx) + 8, H - 5, g["outs"], 3, (240, 60, 60))
    return img


def mlb_2_big_diamond(r):
    """Diamond scaled to the full panel height — the surface is the layout."""
    g = MLB
    img, d = new_frame()
    cx, cy, rad, bs = bg_diamond_field(d, big=True)
    bases_on(d, cx, cy, rad, bs, g["on1"], g["on2"], g["on3"])
    paste_logo(img, r, g["left_logo"], 20, 4, 1)
    paste_logo(img, r, g["right_logo"], 20, W - 24, 1)
    halo_text(img, d, 28, 12, g["left_score"], r.clock_giant, WHITE, anchor="lm")
    halo_text(img, d, W - 28, 12, g["right_score"], r.clock_giant, WHITE, anchor="rm")
    halo_hyb(img, d, 4, 24, f"{g['left_ab']}  {g['hits_left']}H", (235, 235, 235))
    t = f"{g['hits_right']}H  {g['right_ab']}"
    halo_hyb(img, d, W - 5 - hyb_w(t), 24, t, (235, 235, 235))
    halo_hyb(img, d, 74, 2, f"P {g['pitcher']}  {g['p_last']}", (170, 200, 255))
    tb = f"AB {g['batter']}  {g['b_avg']}"
    halo_hyb(img, d, W - 74 - hyb_w(tb), 2, tb, (255, 175, 175))
    halo_hyb(img, d, 74, 24, f"{'V' if g['half'] == 'BOT' else '^'}{g['inning']}", (255, 225, 120))
    tc = f"{g['balls']}-{g['strikes']}  {g['outs']} OUT"
    halo_hyb(img, d, W - 74 - hyb_w(tc), 24, tc, (255, 225, 120))
    return img


def mlb_3_plate_view(r):
    """Catcher's view: the strike-zone plot sits in front of the live diamond."""
    g = MLB
    img, d = new_frame()
    cx, cy, rad, bs = bg_diamond_field(d)
    bases_on(d, cx, cy, rad, bs, g["on1"], g["on2"], g["on3"])
    img.alpha_composite(Image.new("RGBA", (W, H), (0, 0, 0, 60)))
    zx, zy, zw, zh = int(cx) - 12, 3, 24, 24
    # Smoked panel, not a black box — the diamond still reads through it.
    panel = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(panel).rectangle([zx - 6, zy - 3, zx + zw + 6, zy + zh + 3], fill=(0, 0, 0, 130))
    img.alpha_composite(panel)
    d.rectangle([zx, zy, zx + zw, zy + zh], outline=(240, 240, 240))
    for k in (1, 2):
        d.line([(zx + zw * k / 3, zy), (zx + zw * k / 3, zy + zh)], fill=(120, 120, 120))
        d.line([(zx, zy + zh * k / 3), (zx + zw, zy + zh * k / 3)], fill=(120, 120, 120))
    cols = {"S": (255, 150, 40), "B": (70, 175, 255), "F": (215, 215, 215)}
    for i, (fx, fy, kind) in enumerate(g["zone"]):
        px_, py = zx - 4 + fx * (zw + 8), zy - 2 + fy * (zh + 4)
        last = i == len(g["zone"]) - 1
        rr = 2 if last else 1
        d.ellipse([px_ - rr, py - rr, px_ + rr, py + rr],
                  fill=cols[kind], outline=WHITE if last else None)
    paste_logo(img, r, g["left_logo"], 16, 3, 1)
    paste_logo(img, r, g["right_logo"], 16, W - 19, 1)
    halo_text(img, d, 22, 10, g["left_score"], r.huge_font, WHITE, anchor="lm")
    halo_text(img, d, W - 22, 10, g["right_score"], r.huge_font, WHITE, anchor="rm")
    halo_hyb(img, d, 3, 23, g["left_ab"], (225, 225, 225))
    halo_hyb(img, d, W - 4 - hyb_w(g["right_ab"]), 23, g["right_ab"], (225, 225, 225))
    halo_hyb(img, d, 62, 4, g["pitcher"], (160, 195, 255))
    halo_hyb(img, d, 62, 13, g["p_last"], WHITE)
    halo_hyb(img, d, 62, 22, f"ERA {g['p_era']}", (215, 215, 215))
    for txt, y, c in ((g["batter"], 4, (255, 170, 170)), (g["b_avg"], 13, WHITE),
                      (g["b_line"], 22, (215, 215, 215))):
        halo_hyb(img, d, W - 62 - hyb_w(txt), y, txt, c)
    halo_hyb_c(img, d, cx, H - 6, f"{g['balls']}-{g['strikes']}  {g['outs']} OUT", (255, 225, 120))
    return img


def mlb_4_ballpark_wide(r):
    """The whole park from behind the plate; hits plotted where they landed."""
    g = MLB
    img, d = new_frame()
    hx, hy = bg_ballpark_wide(d)
    for fx, fy in g["spray"]:
        x = hx + fx * 200 * fy
        y = hy - fy * 34
        d.ellipse([x - 2, y - 2, x + 2, y + 2], fill=(255, 225, 110), outline=(90, 70, 20))
    paste_logo(img, r, g["left_logo"], 16, 3, 1)
    paste_logo(img, r, g["right_logo"], 16, W - 19, 1)
    halo_text(img, d, 22, 9, g["left_score"], r.huge_font, WHITE, anchor="lm")
    halo_text(img, d, W - 22, 9, g["right_score"], r.huge_font, WHITE, anchor="rm")
    halo_hyb(img, d, 3, 21, f"{g['left_ab']} {g['hits_left']}H", (225, 225, 225))
    t = f"{g['hits_right']}H {g['right_ab']}"
    halo_hyb(img, d, W - 4 - hyb_w(t), 21, t, (225, 225, 225))
    halo_hyb(img, d, 66, 2, f"P {g['pitcher']} {g['p_last']}", (170, 200, 255))
    tb = f"AB {g['batter']} {g['b_avg']}"
    halo_hyb(img, d, W - 66 - hyb_w(tb), 2, tb, (255, 175, 175))
    halo_hyb_c(img, d, hx, 2, f"{'V' if g['half'] == 'BOT' else '^'}{g['inning']}", WHITE)
    halo_hyb_c(img, d, hx, H - 8, f"{g['balls']}-{g['strikes']}  {g['outs']} OUT", (255, 225, 120))
    return img


# ═══════════════════════════════════════════════════════════════════════════
# SOCCER — BRA 1 - 7 GER, full time (goal-heavy stress case)
# ═══════════════════════════════════════════════════════════════════════════

SOC = dict(
    left_ab="GER", right_ab="BRA",
    left_c=hexc("2B2B2B"), right_c=hexc("009C3B"),
    left_logo="https://a.espncdn.com/i/teamlogos/countries/500/ger.png",
    right_logo="https://a.espncdn.com/i/teamlogos/countries/500/bra.png",
    left_score=7, right_score=1,
    status="FT", minute=90,
    goals=[("MULLER", 11, "l"), ("KLOSE", 23, "l"), ("KROOS", 24, "l"), ("KROOS", 26, "l"),
           ("KHEDIRA", 29, "l"), ("SCHURRLE", 69, "l"), ("SCHURRLE", 79, "l"), ("OSCAR", 90, "r")],
    cards=[(63, "r"), (88, "r")],
    poss_left=48, poss_right=52, shots_left=14, shots_right=18,
)


def _min_x(m, x0, x1):
    return x0 + (x1 - x0) * max(0, min(95, m)) / 95


def _cluster(goals, x0, x1, min_gap=13):
    """Group goals that land too close together to label individually."""
    out = []
    for name, m, side in sorted(goals, key=lambda t: t[1]):
        mx = _min_x(m, x0, x1)
        if out and out[-1]["side"] == side and mx - out[-1]["xs"][-1] < min_gap:
            out[-1]["xs"].append(mx)
            out[-1]["mins"].append(m)
        else:
            out.append({"side": side, "xs": [mx], "mins": [m]})
    return out


def soc_1_touchline_timeline(r):
    """The pitch stays; the touchlines become the 90-minute timeline, so goals
    sit at the minute they happened instead of piling up as a wall of text."""
    g = SOC
    img, d = new_frame()
    bg_pitch(d, y0=6, y1=H - 7)
    d.rectangle([0, 0, W - 1, 5], fill=(11, 11, 14))
    d.rectangle([0, H - 6, W - 1, H - 1], fill=(11, 11, 14))
    x0, x1 = 62, W - 62
    for band, y in ((0, 4), (1, H - 2)):
        d.line([(x0, y), (x1, y)], fill=(58, 58, 64))
    for m in (15, 30, 45, 60, 75):
        mx = _min_x(m, x0, x1)
        d.line([(mx, 3), (mx, 5)], fill=(95, 95, 102))
        d.line([(mx, H - 3), (mx, H - 1)], fill=(95, 95, 102))
    for grp in _cluster(g["goals"], x0, x1):
        up = grp["side"] == "l"
        c = (225, 228, 238) if up else mix(g["right_c"], WHITE, 0.35)
        y = 1 if up else H - 5
        gx0, gx1 = grp["xs"][0], grp["xs"][-1]
        if len(grp["xs"]) == 1:
            d.ellipse([gx0 - 2, y, gx0 + 2, y + 4], fill=c, outline=BLACK)
            hyb(d, gx0 + 4, y, f"{grp['mins'][0]}'", c)
        else:
            d.rectangle([gx0 - 2, y, gx1 + 2, y + 4], fill=mix(c, BLACK, 0.35), outline=c)
            hyb(d, gx1 + 5, y, f"x{len(grp['xs'])} {grp['mins'][0]}-{grp['mins'][-1]}'", c)
    for m, side in g["cards"]:
        mx = _min_x(m, x0, x1)
        d.rectangle([mx - 1, H - 5, mx + 1, H - 1], fill=(235, 45, 45))
    paste_logo(img, r, g["left_logo"], 18, 3, 7)
    paste_logo(img, r, g["right_logo"], 18, W - 21, 7)
    halo_text(img, d, 24, 16, g["left_score"], r.clock_giant, WHITE, anchor="lm")
    halo_text(img, d, W - 24, 16, g["right_score"], r.clock_giant, WHITE, anchor="rm")
    halo_text(img, d, W // 2, 16, g["status"], r.big_font, (255, 230, 130))
    return img


def soc_2_third_tint(r):
    """Pitch kept; each attacking third is tinted by the team attacking it and
    the halfway marker slides with possession."""
    g = SOC
    img, d = new_frame()
    bg_pitch(d)
    ov = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    od = ImageDraw.Draw(ov, "RGBA")
    third = W / 3
    for x in range(int(third)):
        od.line([(x, 0), (x, H)], fill=g["right_c"] + (int(140 * (1 - x / third) ** 1.2),))
    for x in range(int(2 * third), W):
        od.line([(x, 0), (x, H)],
                fill=g["left_c"] + (int(150 * ((x - 2 * third) / third) ** 1.2),))
    img.alpha_composite(ov)
    split = int(W * g["poss_left"] / 100)
    d.line([(split, 0), (split, H)], fill=(255, 230, 130), width=1)
    d.polygon([(split - 4, 0), (split + 4, 0), (split, 4)], fill=(255, 230, 130))
    paste_logo(img, r, g["right_logo"], 16, 3, 2)
    paste_logo(img, r, g["left_logo"], 16, W - 19, 2)
    halo_text(img, d, 22, 15, g["right_score"], r.clock_giant, WHITE, anchor="lm")
    halo_text(img, d, W - 22, 15, g["left_score"], r.clock_giant, WHITE, anchor="rm")
    halo_hyb(img, d, 3, 24, f"{g['right_ab']} {g['poss_right']}% {g['shots_right']}SH", WHITE)
    t = f"{g['shots_left']}SH {g['poss_left']}% {g['left_ab']}"
    halo_hyb(img, d, W - 4 - hyb_w(t), 24, t, WHITE)
    halo_text(img, d, W // 2, 14, g["status"], r.big_font, (255, 230, 130))
    return img


def soc_3_box_zoom(r):
    """Zoom the pitch to the penalty area — set pieces, penalties, shootouts."""
    g = SOC
    img, d = new_frame()
    goal_x = bg_pitch_boxzoom(img, d, g["left_c"])
    spot = goal_x - 104
    d.ellipse([spot - 3, H / 2 - 3, spot + 3, H / 2 + 3], fill=(255, 250, 250))
    paste_logo(img, r, g["left_logo"], 14, 4, 1)
    paste_logo(img, r, g["right_logo"], 14, 4, 17)
    for row_y, results in ((2, ["goal", "miss", "goal", "pending", "pending"]),
                           (H - 8, ["goal", "goal", "miss", "goal", "pending"])):
        for i, res in enumerate(results):
            bx = 22 + i * 8
            col = {"goal": (60, 210, 90), "miss": (230, 55, 55)}.get(res, (78, 78, 78))
            d.rectangle([bx, row_y, bx + 5, row_y + 5], fill=col, outline=(20, 20, 20))
    halo_text(img, d, 70, 15, f"{g['left_score']}-{g['right_score']}", r.big_font, WHITE, anchor="lm")
    halo_hyb(img, d, 112, 3, "PENALTIES 3-2", (255, 230, 130))
    halo_hyb(img, d, 112, 24, "5TH KICK", (240, 240, 240))
    return img


def soc_4_live_pitch(r):
    """Full pitch with halo text and goals as touchline ticks — the closest
    upgrade path from what ships today."""
    g = SOC
    img, d = new_frame()
    bg_pitch(d)
    for name, m, side in g["goals"]:
        mx = _min_x(m, 66, W - 66)
        c = (235, 238, 248) if side == "l" else mix(g["right_c"], WHITE, 0.4)
        y0, y1 = (0, 3) if side == "l" else (H - 4, H - 1)
        d.rectangle([mx - 1, y0, mx + 1, y1], fill=c)
    for m, side in g["cards"]:
        mx = _min_x(m, 66, W - 66)
        d.rectangle([mx - 1, H - 4, mx + 1, H - 1], fill=(235, 45, 45))
    paste_logo(img, r, g["left_logo"], 20, 4, 6)
    paste_logo(img, r, g["right_logo"], 20, W - 24, 6)
    halo_text(img, d, 28, 15, g["left_score"], r.clock_giant, WHITE, anchor="lm")
    halo_text(img, d, W - 28, 15, g["right_score"], r.clock_giant, WHITE, anchor="rm")
    halo_text(img, d, W // 2, 14, g["status"], r.big_font, (255, 230, 130))
    halo_hyb(img, d, 4, 25, f"{g['shots_left']} SH", (235, 240, 250))
    t = f"{g['shots_right']} SH"
    halo_hyb(img, d, W - 5 - hyb_w(t), 25, t, (235, 240, 250))
    halo_hyb_c(img, d, W // 2, 24, f"{g['left_ab']} 7 GOALS", (235, 235, 235))
    return img


# ═══════════════════════════════════════════════════════════════════════════

CONCEPTS = {
    "nfl": [
        ("live-field", "Full field, halo text replaces the side scrims", nfl_1_live_field),
        ("field-zoom", "Zoom to 30 yards around the ball + full-field mini-map", nfl_2_field_zoom),
        ("perspective", "Sideline camera; crowd band carries the bug", nfl_3_field_perspective),
        ("redzone-zoom", "Goal-line camera; end zone is a third of the panel", nfl_4_redzone_zoom),
    ],
    "nhl": [
        ("live-rink", "Ice edge to edge, halo text, PP drain rail", nhl_1_live_rink),
        ("shot-map", "Rink plots real shots instead of decorating", nhl_2_shot_map),
        ("zone-tint", "Attacking zones tinted by the team attacking them", nhl_3_zone_tint),
        ("zone-zoom", "Zoom to the offensive zone during a power play", nhl_4_zone_zoom),
    ],
    "nba": [
        ("live-court", "Court markings carry bonus, shot clock, possession", nba_1_live_court),
        ("court-run", "The hardwood itself stains toward the team on a run", nba_2_court_run),
        ("halfcourt-zoom", "Attacking half-court at readable scale + shot chart", nba_3_halfcourt_zoom),
        ("perspective", "Baseline camera; scorer's-table band for the bug", nba_4_court_perspective),
    ],
    "mlb": [
        ("console", "Diamond centre, labelled pitcher/batter cards on grass", mlb_1_console),
        ("big-diamond", "Diamond scaled to the full panel height", mlb_2_big_diamond),
        ("plate-view", "Strike-zone plot in front of the live diamond", mlb_3_plate_view),
        ("ballpark-wide", "Whole park from the plate; hits plotted where they fell", mlb_4_ballpark_wide),
    ],
    "soccer": [
        ("touchline-timeline", "Touchlines become the 90-minute timeline", soc_1_touchline_timeline),
        ("third-tint", "Attacking thirds tinted; halfway marker tracks possession", soc_2_third_tint),
        ("box-zoom", "Zoom to the penalty area for set pieces / shootouts", soc_3_box_zoom),
        ("live-pitch", "Full pitch, halo text, goals as touchline ticks", soc_4_live_pitch),
    ],
}

LOGOS = [g[k] for g in (NFL, NHL, NBA, MLB, SOC) for k in ("left_logo", "right_logo")]


def contact_sheet(entries, title, scale=3):
    cell_h = H * scale + 22
    sheet = Image.new("RGB", (W * scale, cell_h * len(entries) + 20), (14, 14, 14))
    sd = ImageDraw.Draw(sheet)
    sd.text((6, 5), title, fill=(255, 255, 255))
    for i, (slug, blurb, frame) in enumerate(entries):
        y = 20 + i * cell_h
        sheet.paste(frame.convert("RGB").resize((W * scale, H * scale), Image.NEAREST), (0, y))
        sd.text((4, y + H * scale + 4), f"{i + 1}. {slug} — {blurb}", fill=(190, 190, 190))
    return sheet


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sport", default="all", choices=["all", *CONCEPTS])
    ap.add_argument("--out-dir", default=OUT_DIR)
    ap.add_argument("--scale", type=int, default=3)
    args = ap.parse_args()

    os.makedirs(args.out_dir, exist_ok=True)
    r = make_renderer("sports_full")
    print("Prefetching logos...")
    for url in LOGOS:
        for sz in (7, 14, 16, 18, 20, 22, 24):
            r.download_and_process_logo(url, (sz, sz))

    sports = list(CONCEPTS) if args.sport == "all" else [args.sport]
    for sport in sports:
        entries = []
        for slug, blurb, fn in CONCEPTS[sport]:
            frame = fn(r).convert("RGB")
            path = os.path.join(args.out_dir, f"{sport}_{slug}.png")
            frame.save(path)
            print(f"  {path}")
            entries.append((slug, blurb, frame))
        sheet_path = os.path.join(args.out_dir, f"_sheet_{sport}.png")
        contact_sheet(entries, sport.upper(), args.scale).save(sheet_path)
        print(f"  {sheet_path}")


if __name__ == "__main__":
    main()
