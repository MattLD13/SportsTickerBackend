import math
import time
from PIL import Image, ImageDraw, ImageFilter, ImageStat

from ticker_core.rendering.pixels import draw_hybrid_text, draw_tiny_text, normalize_special_chars

PANEL_W = 384
PANEL_H = 32

# Width of the darkened band at each edge of a full-bleed card. Anything drawn
# underneath it has to reach the edge without introducing brightness of its own,
# so backgrounds taper their detail over the same span.
SIDE_SCRIM_SOLID = 8
SIDE_SCRIM_FADE = 92
SIDE_SCRIM_SPAN = SIDE_SCRIM_SOLID + SIDE_SCRIM_FADE


def _relative_luminance(color):
    """Return the standard relative luminance for one RGB color."""
    channels = []
    for value in color[:3]:
        channel = max(0.0, min(1.0, int(value) / 255.0))
        channels.append(channel / 12.92 if channel <= 0.04045 else ((channel + 0.055) / 1.055) ** 2.4)
    return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2]


def _contrast_ratio(first, second):
    """Return the WCAG contrast ratio between two RGB colors."""
    light = max(_relative_luminance(first), _relative_luminance(second))
    dark = min(_relative_luminance(first), _relative_luminance(second))
    return (light + 0.05) / (dark + 0.05)


def _logo_outline_color(background, alternate):
    """Choose the strongest available logo edge color."""
    if alternate and _contrast_ratio(background, alternate) >= 3.0:
        return alternate
    return max(((0, 0, 0), (255, 255, 255)), key=lambda color: _contrast_ratio(background, color))


def _logo_has_contrast(logo, background):
    """Return whether enough visible logo pixels contrast with its background."""
    visible = []
    for red, green, blue, alpha in logo.getdata():
        if alpha >= 96:
            visible.append((red, green, blue))
    if not visible:
        return False
    readable = sum(
        _contrast_ratio(background, color) >= 2.2
        or max(abs(color[index] - background[index]) for index in range(3)) >= 80
        for color in visible
    )
    return readable * 5 >= len(visible)


def _logo_with_contrast(logo, size, background, alternate):
    """Add a contrast halo around the visible shape of one logo."""
    base = logo.convert("RGBA").resize((size, size), Image.Resampling.LANCZOS)
    if _logo_has_contrast(base, background):
        result = Image.new("RGBA", (size + 4, size + 4), (0, 0, 0, 0))
        result.alpha_composite(base, (2, 2))
        return result
    edge = _logo_outline_color(background, alternate)
    alpha = base.getchannel("A")
    halo_alpha = alpha.filter(ImageFilter.MaxFilter(5))

    result = Image.new("RGBA", (size + 4, size + 4), (0, 0, 0, 0))
    halo = Image.new("RGBA", (size, size), (*edge, 0))
    halo.putalpha(halo_alpha)
    result.alpha_composite(halo, (2, 2))
    result.alpha_composite(base, (2, 2))
    return result


class SportsMixin:

    def _missing_football_logo(self, label, size, background, alternate):
        """Render a readable abbreviation when a school has no image asset."""
        edge = _logo_outline_color(background, alternate)
        outline = (255, 255, 255, 225) if edge == (0, 0, 0) else (0, 0, 0, 225)
        result = Image.new("RGBA", (size + 4, size + 4), (0, 0, 0, 0))
        result_draw = ImageDraw.Draw(result, "RGBA")
        text = str(label or "?").upper()[:3]
        self.draw_outlined_text(
            result_draw,
            (size + 4) // 2,
            (size + 4) // 2,
            text,
            self.tiny,
            (*edge, 255),
            outline,
        )
        return result

    def draw_hockey_stick(self, draw, cx, cy, size):
        WOOD = (150, 75, 0); TAPE = (255, 255, 255)
        pattern = [[0,0,0,0,0,1,1,0],[0,0,0,0,0,1,1,0],[0,0,0,0,0,1,1,0],[0,0,0,0,1,1,1,0],
                   [0,0,0,0,1,1,0,0],[1,2,2,1,1,1,0,0],[1,2,2,1,1,0,0,0],[0,0,0,0,0,0,0,0]]
        sx, sy = cx - 4, cy - 4
        for y in range(8):
            for x in range(8):
                if pattern[y][x] == 1: draw.point((sx+x, sy+y), fill=WOOD)
                elif pattern[y][x] == 2: draw.point((sx+x, sy+y), fill=TAPE)

    def draw_shootout_indicators(self, draw, results, start_x, y):
        display_results = results[-3:]
        while len(display_results) < 3: display_results.append('pending')
        x_off = start_x
        for res in display_results:
            if res == 'pending': draw.rectangle((x_off, y, x_off+3, y+3), outline=(80,80,80))
            elif res == 'miss': draw.line((x_off, y, x_off+3, y+3), fill=(255,0,0)); draw.line((x_off, y+3, x_off+3, y), fill=(255,0,0))
            elif res == 'goal': draw.rectangle((x_off, y, x_off+3, y+3), fill=(0,255,0))
            x_off += 6

    def draw_soccer_shootout(self, draw, results, start_x, y):
        display_results = results[-5:]
        while len(display_results) < 5: display_results.append('pending')
        x_off = start_x
        if len(results) > 0: x_off -= 2
        for res in display_results:
            if res == 'pending': draw.rectangle((x_off, y, x_off+1, y+1), outline=(60,60,60))
            elif res == 'miss': draw.point((x_off, y), fill=(255,0,0)); draw.point((x_off+1, y+1), fill=(255,0,0))
            elif res == 'goal': draw.rectangle((x_off, y, x_off+1, y+1), fill=(0,255,0))
            x_off += 4

    def _draw_soccer_so_col(self, draw, x, y, results):
        n_show = 5
        for i in range(n_show):
            res = results[i] if i < len(results) else 'pending'
            dy = y + i * 5
            if res == 'goal':
                draw.rectangle((x, dy, x+2, dy+2), fill=(50, 200, 70))
            elif res == 'miss':
                draw.rectangle((x, dy, x+2, dy+2), fill=(220, 55, 55))
            else:
                draw.rectangle((x, dy, x+2, dy+2), fill=(80, 80, 80))

    def _draw_nhl_so_col(self, draw, x, y, results):
        n_show = 3
        for i in range(n_show):
            res = results[i] if i < len(results) else 'pending'
            dy = y + i * 7
            if res == 'goal':
                draw.rectangle((x, dy, x + 4, dy + 4), fill=(50, 200, 70))
            elif res == 'miss':
                draw.rectangle((x, dy, x + 1, dy + 1), fill=(220, 55, 55))
                draw.rectangle((x + 3, dy, x + 4, dy + 1), fill=(220, 55, 55))
                draw.rectangle((x + 1, dy + 2, x + 3, dy + 2), fill=(220, 55, 55))
                draw.rectangle((x, dy + 3, x + 1, dy + 4), fill=(220, 55, 55))
                draw.rectangle((x + 3, dy + 3, x + 4, dy + 4), fill=(220, 55, 55))
            else:
                draw.rectangle((x, dy, x + 4, dy + 4), fill=(55, 55, 55))
                draw.rectangle((x + 1, dy + 1, x + 3, dy + 3), fill=(10, 10, 14))


    def draw_baseball_hud(self, draw, x, y, o):
        for i in range(3): draw.rectangle((x+(i*4), y, x+(i*4)+1, y+1), fill=((255, 0, 0) if i < o else (40, 40, 40)))

    def _draw_side_scrims(self, img, W, H, solid=SIDE_SCRIM_SOLID,
                          fade=SIDE_SCRIM_FADE, peak=252):
        """Darken both edges so text and logos stay readable over the field.

        A flat block followed by a straight ramp is continuous in value but not
        in slope: it goes from level to -3/px in one pixel, which reads as a
        hard edge where the solid core ends, and the linear tail bands against
        the alternating grass stripes before stopping abruptly at zero.
        Smoothstep is flat at both ends, so the core joins the ramp seamlessly
        and the ramp dies into the field instead of ending on an edge.

        Composited as a separate overlay because drawing alpha ink straight
        onto an RGBA image replaces pixels rather than blending them.
        """
        scrim = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        sd = ImageDraw.Draw(scrim)
        for x in range(solid + fade):
            if x < solid:
                a = peak
            else:
                t = (x - solid) / fade
                a = int(round(peak * (1 - t * t * (3 - 2 * t))))
            sd.line([(x, 0), (x, H)], fill=(0, 0, 0, a))
            sd.line([(W - 1 - x, 0), (W - 1 - x, H)], fill=(0, 0, 0, a))
        img.alpha_composite(scrim)

    def draw_sport_full_bleed(self, game):
        W = PANEL_W; H = PANEL_H
        img = Image.new("RGBA", (W, H), (0, 0, 0, 255))
        d = ImageDraw.Draw(img, "RGBA")

        # Display convention: away on left, home on right.
        _g = {}
        for k, v in game.items():
            if k.startswith('home_'):
                _g['away_' + k[5:]] = v
            elif k.startswith('away_'):
                _g['home_' + k[5:]] = v
            else:
                _g[k] = v
        game = _g

        sport    = str(game.get('sport', '')).lower()
        is_nfl   = 'football' in sport or 'nfl' in sport or 'ncf' in sport
        is_nhl   = 'hockey' in sport or 'nhl' in sport
        is_mlb   = 'baseball' in sport or 'mlb' in sport
        is_soc   = 'soccer' in sport
        sit      = game.get('situation', {}) or {}
        home_clr = self.get_team_color(game, 'home')
        away_clr = self.get_team_color(game, 'away')
        h_score  = str(game.get('home_score', ''))
        a_score  = str(game.get('away_score', ''))
        home_ab  = str(game.get('home_abbr', '')).upper()
        away_ab  = str(game.get('away_abbr', '')).upper()
        poss_ab  = str(sit.get('activeTeam', '')).upper()

        # ── FOOTBALL: full field matching HTML footballField() ───────────────
        if is_nfl:
            def _parse_hex_color(value):
                try:
                    c = str(value or '').strip().lstrip('#')
                    if len(c) == 6:
                        return tuple(int(c[i:i+2], 16) for i in (0, 2, 4))
                except Exception:
                    pass
                return None

            # Prefer explicit team colors; if missing, fall back to a readable
            # default palette (instead of logo-average grays).
            home_ez = _parse_hex_color(game.get('home_color')) or home_clr
            away_ez = _parse_hex_color(game.get('away_color')) or away_clr

            def _is_dull(c):
                return max(c) - min(c) < 25

            if _is_dull(home_ez):
                home_ez = (155, 32, 32)
            if _is_dull(away_ez):
                away_ez = (32, 62, 155)

            EZ_RATIO = 30 / 360
            ezW    = W * EZ_RATIO          # ~32 px
            playW  = W * (300 / 360)       # ~320 px
            hT     = H * (70.75 / 160)     # upper hash row
            hB     = H * (89.25 / 160)     # lower hash row

            # 1 · Grass bands (10 alternating strips)
            for i in range(10):
                bx = ezW + i * playW / 10
                d.rectangle([bx, 0, bx + playW / 10, H],
                            fill=(22, 52, 18) if i % 2 == 0 else (27, 64, 24))

            # 2 · End zones  HOME=left  AWAY=right
            d.rectangle([0, 0, ezW, H], fill=home_ez)
            d.rectangle([W - ezW, 0, W, H], fill=away_ez)
            d.line([(ezW, 0), (ezW, H)],         fill=(255, 255, 255, 230))
            d.line([(W - ezW, 0), (W - ezW, H)], fill=(255, 255, 255, 230))

            # 3 · 10-yard stripe lines
            for i in range(11):
                lx = ezW + i * playW / 10
                op = 115 if i == 5 else 64
                d.line([(lx, 0), (lx, H)], fill=(255, 255, 255, op))

            # 4 · Hash marks
            for y in range(1, 100):
                hx = ezW + y / 100 * playW
                is5 = (y % 5 == 0)
                hl  = H * 0.042 if is5 else H * 0.022
                op  = 128 if is5 else 66
                d.line([(hx, hT - hl), (hx, hT + hl)], fill=(255, 255, 255, op))
                d.line([(hx, hB - hl), (hx, hB + hl)], fill=(255, 255, 255, op))

            # 5 · Line of scrimmage and yards-to-go.
            #     `los` is this card's own axis: 0 = left goal line, 100 = right.
            #     Note the home_/away_ key swap at the top of this method — home_ab
            #     here is the *visiting* team (drawn left), away_ab is the host.
            #     ESPN's situation.yardLine is measured from the host's goal line
            #     ("CAR 33" with ARI at home is 67), which sits at the right edge,
            #     so the ESPN value is mirrored onto this axis exactly once.
            dd_text = sit.get('downDist', '') or sit.get('downDistFull', '')
            spot_text = sit.get('downDistFull', '') or sit.get('ballOn', '') or dd_text

            los, ytg = -1, 10
            espn_yl = sit.get('yardLine')
            if espn_yl is not None:
                los = max(0, min(100, 100 - int(espn_yl)))
            elif ' at ' in spot_text:
                # Fallback for payloads without the numeric field: "... at CAR 33".
                after = spot_text.split(' at ', 1)[1].strip().split()
                if len(after) == 1 and after[0] == '50':
                    los = 50
                elif len(after) >= 2:
                    team = after[0].upper()
                    try:
                        yard = int(after[1])
                        los = yard if team == home_ab else (100 - yard if team == away_ab else 50)
                    except ValueError:
                        pass

            if sit.get('yardsToGo') is not None:
                ytg = max(1, int(sit['yardsToGo']))
            elif '&' in dd_text:
                ytg_raw = dd_text.split('&', 1)[1].strip().split()[0].lower().rstrip('.,')
                try: ytg = max(1, int(ytg_raw))
                except ValueError: ytg = 10

            # Each team attacks the opposite end zone, so the visiting team (home_ab
            # after the swap, drawn on the left) drives to the right.
            drive_to_right = poss_ab != away_ab

            is_goal_to_go = bool(sit.get('isGoalToGo')) or 'goal' in dd_text.lower()
            if is_goal_to_go and los >= 0:
                # First down is the goal line itself, however short the distance reads.
                ytg = max(1, (100 - los) if drive_to_right else los)

            # 6 · Red zone tint
            is_rz = sit.get('isRedZone', False)
            if is_rz:
                rz_overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
                rz_d = ImageDraw.Draw(rz_overlay, "RGBA")
                if drive_to_right:
                    rz_d.rectangle([ezW + int(0.8 * playW), 0, W - ezW, H], fill=(220, 0, 0, 128))
                    d.line([(ezW + 0.8 * playW, 0), (ezW + 0.8 * playW, H)], fill=(255, 34, 34, 200), width=2)
                else:
                    rz_d.rectangle([ezW, 0, ezW + int(0.2 * playW), H], fill=(220, 0, 0, 128))
                    d.line([(ezW + 0.2 * playW, 0), (ezW + 0.2 * playW, H)], fill=(255, 34, 34, 200), width=2)
                img.alpha_composite(rz_overlay)

            # 7 · Center text overlay (period + context, matching HTML getBgText)
            prd     = self.shorten_status(game.get('status', ''), sport)
            # The field card has room for the spot ("1st & 10 at ARI 42"); the
            # compact ticker row shows only the short "1st & 10".
            ctx     = sit.get('downDistFull', '') or dd_text
            if not ctx and dd_text and sit.get('ballOn'):
                ctx = f"{dd_text} at {sit['ballOn']}"
            ctx_clr = (255, 136, 0) if is_rz else (240, 216, 0)
            cx_mid  = W // 2
            if prd or ctx:
                y_prd = int(H * 0.32) if ctx else int(H * 0.5)
                self.draw_outlined_text(d, cx_mid, y_prd, prd, self.big_font, (255, 255, 255), (0, 0, 0, 200))
                if ctx:
                    self.draw_outlined_text(d, cx_mid, int(H * 0.72), ctx, self.font, ctx_clr, (0, 0, 0, 200))

            # 8 · Logos in end zones
            LOGO_SZ  = min(int(ezW * 0.85), int(H * 0.65))
            logo_top_center = (H - LOGO_SZ) // 2   # vertically centred
            h_logo_cx = int(ezW / 2)
            a_logo_cx = W - int(ezW / 2)

            # 9 · Score badges — determine positions first so logos can dodge them
            # Real 14pt font instead of the 5×6 bitmap — the score is the thing
            # you read from across the room, so it gets the height to earn that.
            score_font = self.big_font
            score_h    = 11
            try:
                _bb = d.textbbox((0, 0), '00', font=score_font)
                score_h = max(score_h, _bb[3] - _bb[1])
            except Exception:
                pass
            # Keep the taller glyphs off the bottom edge of the panel.
            score_y   = min(int(H * 0.82), H - (score_h // 2) - 1)
            slot_cx   = int(ezW + playW * 0.05)
            aslot_cx  = int(W - ezW - playW * 0.05)
            h_sc_cx   = slot_cx
            a_sc_cx   = aslot_cx
            if is_rz:
                if poss_ab == home_ab:
                    a_sc_cx = a_logo_cx   # away score moves into away endzone
                elif poss_ab == away_ab:
                    h_sc_cx = h_logo_cx   # home score moves into home endzone

            # Push logo up when its score badge sits below it in the endzone
            score_box_top = score_y - (score_h // 2)     # top edge of score badge
            logo_top_up   = max(0, score_box_top - LOGO_SZ - 1)  # just above the badge
            h_logo_top = logo_top_up if h_sc_cx == h_logo_cx else logo_top_center
            a_logo_top = logo_top_up if a_sc_cx == a_logo_cx else logo_top_center

            hl = self.get_logo(game.get('home_logo'), (24, 24))
            al = self.get_logo(game.get('away_logo'), (24, 24))
            home_alt = _parse_hex_color(game.get('home_alt_color'))
            away_alt = _parse_hex_color(game.get('away_alt_color'))
            if hl:
                ls = _logo_with_contrast(hl, LOGO_SZ, home_ez, home_alt)
                img.alpha_composite(ls, (h_logo_cx - ls.width // 2, max(0, h_logo_top - 2)))
            else:
                ls = self._missing_football_logo(home_ab, LOGO_SZ, home_ez, home_alt)
                img.alpha_composite(ls, (h_logo_cx - ls.width // 2, max(0, h_logo_top - 2)))
            if al:
                ls = _logo_with_contrast(al, LOGO_SZ, away_ez, away_alt)
                img.alpha_composite(ls, (a_logo_cx - ls.width // 2, max(0, a_logo_top - 2)))
            else:
                ls = self._missing_football_logo(away_ab, LOGO_SZ, away_ez, away_alt)
                img.alpha_composite(ls, (a_logo_cx - ls.width // 2, max(0, a_logo_top - 2)))

            for scx, sc in [(h_sc_cx, h_score), (a_sc_cx, a_score)]:
                if not sc: continue
                self.draw_outlined_text(d, scx, score_y, str(sc), score_font,
                                        (255, 255, 255), (0, 0, 0, 235))

            # 10 · First-down line + LOS line + football
            if 0 <= los <= 100:
                los_px = ezW + los * playW / 100
                fd_pct = min(100, los + ytg) if drive_to_right else max(0, los - ytg)
                fd_px  = ezW + fd_pct * playW / 100
                d.line([(fd_px, 0), (fd_px, H)],   fill=(240, 216, 0, 245), width=2)
                d.line([(los_px, 0), (los_px, H)],  fill=(30, 60, 180, 240), width=2)
                brx = max(4, int(H * 0.13))
                bry = max(2, int(H * 0.08))
                by  = H // 2
                d.ellipse([los_px - brx, by - bry, los_px + brx, by + bry], fill=(139, 69, 19), outline=(61, 26, 6))
                d.line([(los_px - int(brx * 0.7), by), (los_px + int(brx * 0.7), by)], fill=(255, 255, 255, 165))

            return img

        # ── SOCCER: full-width pitch layout ─────────────────────────────────
        if is_soc:
            home_pitch = self.get_team_color(game, 'home')
            away_pitch = self.get_team_color(game, 'away')

            # Pitch background with subtle stripes and center circle.
            d.rectangle([0, 0, W, H], fill=(18, 96, 36))
            for i in range(8):
                x0 = int(i * W / 8)
                x1 = int((i + 1) * W / 8)
                shade = (22, 104, 40) if i % 2 == 0 else (18, 96, 36)
                d.rectangle([x0, 0, x1, H], fill=shade)
            d.rectangle([1, 1, W - 2, H - 2], outline=(245, 245, 245, 210), width=1)
            d.line([(W // 2, 0), (W // 2, H)], fill=(245, 245, 245, 180), width=1)
            d.ellipse([W // 2 - 13, H // 2 - 13, W // 2 + 13, H // 2 + 13], outline=(245, 245, 245, 180), width=1)
            d.rectangle([1, 8, 10, H - 8], fill=(245, 245, 245, 28))
            d.rectangle([W - 11, 8, W - 2, H - 8], fill=(245, 245, 245, 28))

            # Fade the edges like the basketball/hockey cards so text and logos stay readable.
            scrim = Image.new("RGBA", (W, H), (0, 0, 0, 0))
            sd = ImageDraw.Draw(scrim)
            SOLID, FADE = 45, 80
            for x in range(SOLID + FADE):
                a = 250 if x < SOLID else max(0, int(250 * (SOLID + FADE - x) / FADE))
                sd.line([(x, 0), (x, H)], fill=(0, 0, 0, a))
                sd.line([(W - 1 - x, 0), (W - 1 - x, H)], fill=(0, 0, 0, a))
            img.alpha_composite(scrim)

            # Team-colored side bars and score placements.
            d.rectangle([0, 0, 3, H], fill=home_pitch)
            d.rectangle([W - 4, 0, W, H], fill=away_pitch)

            LOGO_SZ = 24
            logo_y = (H - LOGO_SZ) // 2
            h_logo_x = 6
            a_logo_x = W - 3 - LOGO_SZ - 5
            hl = self.get_logo(game.get('home_logo'), (LOGO_SZ, LOGO_SZ))
            al = self.get_logo(game.get('away_logo'), (LOGO_SZ, LOGO_SZ))
            if hl: img.paste(hl, (h_logo_x, logo_y), hl)
            if al: img.paste(al, (a_logo_x, logo_y), al)

            h_sc_x = h_logo_x + LOGO_SZ + 4
            a_sc_x = a_logo_x - 4
            self.draw_outlined_text(d, h_sc_x, H // 2, h_score,
                                    self.clock_giant, (255, 255, 255), (0, 0, 0, 200), anchor='lm')
            self.draw_outlined_text(d, a_sc_x, H // 2, a_score,
                                    self.clock_giant, (255, 255, 255), (0, 0, 0, 200), anchor='rm')

            # Status / match time — large and vertically centred, matching NHL/NBA
            status_text = str(game.get('status', '')).strip()
            if status_text:
                self.draw_outlined_text(d, W // 2, H // 2, status_text[:12], self.big_font,
                                        (255, 240, 150), (0, 0, 0, 220), anchor='mm')

            # Goal scorers and red cards sit in the lane between each score and the centre time.
            # After the home/away display swap: is_home=False → visual left; is_home=True → visual right.
            raw_goals = sit.get('goal_events') or []
            raw_cards = sit.get('red_cards') or []
            left_events  = [(e, False) for e in raw_goals if not e.get('is_home')] + \
                           [(e, True)  for e in raw_cards  if not e.get('is_home')]
            right_events = [(e, False) for e in raw_goals if e.get('is_home')] + \
                           [(e, True)  for e in raw_cards  if e.get('is_home')]

            # Measure how wide each score and the time text actually are so events
            # land in the true gap — not overlapping either element.
            h_sc_w    = d.textlength(str(h_score or '0'), font=self.clock_giant)
            a_sc_w    = d.textlength(str(a_score or '0'), font=self.clock_giant)
            time_w    = d.textlength(status_text[:12], font=self.big_font) if status_text else 0
            left_gap_end   = int(W // 2 - time_w / 2) - 4   # left edge of time text minus margin
            right_gap_start = int(W // 2 + time_w / 2) + 4  # right edge of time text plus margin
            left_lane_x  = (int(h_sc_x + h_sc_w) + left_gap_end)  // 2   # centre of left gap
            right_lane_x = (right_gap_start + int(a_sc_x - a_sc_w)) // 2  # centre of right gap

            CARD_W, CARD_GAP = 3, 4
            WHITE = (235, 235, 235)
            DIM   = (150, 150, 150)

            left_gap_start  = int(h_sc_x + h_sc_w)
            right_gap_end   = int(a_sc_x - a_sc_w)

            for lane, gap_l, gap_r in [
                (left_events,  left_gap_start, left_gap_end),
                (right_events, right_gap_start, right_gap_end),
            ]:
                if not lane:
                    continue
                n = len(lane)
                gap_w = gap_r - gap_l

                if n <= 3:
                    # Single centred column
                    subcols = [(lane, gap_l + gap_w // 2)]
                    LINE_H, name_len = 9, 8
                else:
                    # Two sub-columns: earlier goals on left, later on right
                    half = (n + 1) // 2
                    subcols = [
                        (lane[:half], gap_l + gap_w * 30 // 100),
                        (lane[half:], gap_l + gap_w * 68 // 100),
                    ]
                    LINE_H, name_len = 8, 6

                for subcol, cx in subcols:
                    nc = len(subcol)
                    y0 = H // 2 - (nc - 1) * LINE_H // 2
                    for i, (ev, is_card) in enumerate(subcol):
                        y = y0 + i * LINE_H
                        player = str(ev.get('player') or '')[:name_len]
                        t = str(ev.get('time') or '')
                        is_og = not is_card and ev.get('own_goal')
                        label = f"{player} {t}{'(og)' if is_og else ''}".strip()
                        if not label:
                            continue
                        col = DIM if is_og else WHITE
                        if is_card:
                            tw = d.textlength(label, font=self.micro)
                            total_w = CARD_W + CARD_GAP + tw
                            rx = int(cx - total_w / 2)
                            d.rectangle([rx, y - 4, rx + CARD_W, y + 2], fill=(220, 30, 30))
                            self.draw_outlined_text(d, rx + CARD_W + CARD_GAP, y, label,
                                                    self.micro, WHITE, (0, 0, 0, 200), anchor='lm')
                        else:
                            self.draw_outlined_text(d, cx, y, label, self.micro,
                                                    col, (0, 0, 0, 200), anchor='mm')

            if sit.get('shootout'):
                so_a = sit.get('shootout', {}).get('away', [])
                so_h = sit.get('shootout', {}).get('home', [])
                so_h_x = int(h_sc_x + h_sc_w + 10)
                so_a_x = int(a_sc_x - a_sc_w - 13)
                self._draw_soccer_so_col(d, so_h_x, 5, so_h)
                self._draw_soccer_so_col(d, so_a_x, 5, so_a)

            return img

        # ── NON-FOOTBALL: sport background + side scrims ────────────────────
        if is_nhl:
            self._draw_hockey_rink(d, W, H)
        elif is_mlb:
            self._draw_baseball_diamond(d, W, H, sit)
        else:
            self._draw_basketball_court(d, W, H)

        # ── MLB: special full-width layout matching HTML L1 getBgText() ──────
        if is_mlb:
            # Parse inning from status string  e.g. "Top 7th" / "Bottom 3rd" / "Mid 8th"
            status_raw = str(game.get('status', '')).upper()
            is_top_inn = 'TOP' in status_raw
            is_bot_inn = 'BOT' in status_raw or 'BOTTOM' in status_raw
            is_mid_inn = not is_top_inn and not is_bot_inn  # MID / END

            # Extract inning number
            inn_num = ''
            for word in status_raw.split():
                clean = word.replace('TH','').replace('ST','').replace('ND','').replace('RD','')
                if clean.isdigit():
                    inn_num = clean
                    break

            def _ordinal(n):
                n = int(n)
                if 10 <= n % 100 <= 19: return f"{n}th"
                return f"{n}" + {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')

            inn_ordinal = _ordinal(inn_num) if inn_num else ''  # e.g. "9th"

            balls   = sit.get('balls',   0)
            strikes = sit.get('strikes', 0)
            outs    = sit.get('outs',    0)

            # ── Step 1: side scrims ─────────────────────────────────────────
            self._draw_side_scrims(img, W, H)
            # ── Step 2: challenge indicator bars ────────────────────────────────
            # Full-mode MLB spec:
            # - 4px-wide full-height connected team-color strip
            # - each lost challenge draws a 2x14 box inside that strip
            _h_rem  = game.get('home_challenges')
            _h_used = game.get('home_challenges_used')
            _a_rem  = game.get('away_challenges')
            _a_used = game.get('away_challenges_used')

            home_ch_clr = self._resolve_challenge_strip_color(game, 'home', home_clr)
            away_ch_clr = self._resolve_challenge_strip_color(game, 'away', away_clr)

            def _draw_challenge_bar(bx0, bx1, rem, used, team_clr):
                # Base: always draw a full-height connected strip.
                d.rectangle([bx0, 0, bx1, H - 1], fill=team_clr)

                def _to_int(v):
                    try:
                        return int(v)
                    except Exception:
                        return None

                rem_i = _to_int(rem)
                used_i = _to_int(used)
                if used_i is None and rem_i is not None:
                    used_i = max(0, 2 - max(0, rem_i))
                if used_i is None:
                    return

                lost_count = min(2, max(0, used_i))
                if lost_count <= 0:
                    return

                # Lost markers are fixed top/bottom slots (never centered).
                box_w = 2
                box_h = 14
                box_x0 = bx0 + ((bx1 - bx0 + 1) - box_w) // 2
                box_x1 = box_x0 + box_w - 1
                top_y0 = 1
                top_y1 = top_y0 + box_h - 1
                bot_y1 = H - 2
                bot_y0 = bot_y1 - box_h + 1

                # "Open" box = carved out from the strip so it's clearly not centered/filled.
                if lost_count >= 1:
                    d.rectangle([box_x0, top_y0, box_x1, top_y1], fill=(0, 0, 0, 0))
                if lost_count >= 2:
                    d.rectangle([box_x0, bot_y0, box_x1, bot_y1], fill=(0, 0, 0, 0))

            _draw_challenge_bar(0,     3,   _h_rem, _h_used, home_ch_clr)
            _draw_challenge_bar(W - 4, W - 1, _a_rem, _a_used, away_ch_clr)

            # ── Step 3: logos ────────────────────────────────────────────────
            LOGO_SZ  = 24
            logo_y   = (H - LOGO_SZ) // 2
            h_logo_x = 6
            a_logo_x = W - 3 - LOGO_SZ - 5
            hl = self.get_logo(game.get('home_logo'), (LOGO_SZ, LOGO_SZ))
            al = self.get_logo(game.get('away_logo'), (LOGO_SZ, LOGO_SZ))
            if hl: img.paste(hl, (h_logo_x, logo_y), hl)
            if al: img.paste(al, (a_logo_x, logo_y), al)

            # ── Step 4: scores ───────────────────────────────────────────────
            h_sc_x = h_logo_x + LOGO_SZ + 4
            a_sc_x = a_logo_x - 4
            self.draw_outlined_text(d, h_sc_x, H // 2, h_score,
                                    self.clock_giant, (255, 255, 255), (0, 0, 0, 200), anchor='lm')
            h_sc_w = d.textlength(h_score, font=self.clock_giant)
            self.draw_outlined_text(d, a_sc_x, H // 2, a_score,
                                    self.clock_giant, (255, 255, 255), (0, 0, 0, 200), anchor='rm')
            a_sc_w = d.textlength(a_score, font=self.clock_giant)

            # ── Step 5: inning text + BSO (drawn AFTER scrim so they're on top) ──
            # Pull these closer to the center diamond so side lanes can hold
            # batter/pitcher detail blocks.
            center_spread = 40
            left_txt_x  = W // 2 - center_spread
            right_txt_x = W // 2 + center_spread

            bso_rows = [
                ('B', str(balls),   (74,  175, 255)),
                ('S', str(strikes), (255, 136,   0)),
                ('O', str(outs),    (224,  48,  48)),
            ]

            if not is_mid_inn:
                inn_cx  = left_txt_x  if is_top_inn else right_txt_x
                bso_cx  = right_txt_x if is_top_inn else left_txt_x
            else:
                inn_cx  = left_txt_x
                bso_cx  = right_txt_x

            def draw_inning_indicator(cx, cy, is_top, is_bot, ordinal_str):
                """Draw inning indicator: [▲/▼ arrow] [bold number] [suffix], all inline and centered."""
                if not ordinal_str:
                    return
                f_num = self.big_font   # 14pt bold
                f_sup = self.micro      # 7pt small suffix

                num_part = ''.join(c for c in ordinal_str if c.isdigit())
                suf_part = ''.join(c for c in ordinal_str if not c.isdigit())

                num_w = d.textlength(num_part, font=f_num)
                suf_w = d.textlength(suf_part, font=f_sup)
                arrow_w = 8
                gap     = 2
                total_w = arrow_w + gap + num_w + suf_w
                x = int(cx - total_w / 2)

                # Arrow — vertically centered at cy with ±5px half-height
                ah    = 4
                mid_x = x + arrow_w // 2
                if is_top:
                    d.polygon([(x-1, cy+ah+1), (x+arrow_w+1, cy+ah+1), (mid_x, cy-ah-1)], fill=(0, 0, 0))
                    d.polygon([(x,   cy+ah),   (x+arrow_w,   cy+ah),   (mid_x, cy-ah)],   fill=(255, 255, 255))
                elif is_bot:
                    d.polygon([(x-1, cy-ah-1), (x+arrow_w+1, cy-ah-1), (mid_x, cy+ah+1)], fill=(0, 0, 0))
                    d.polygon([(x,   cy-ah),   (x+arrow_w,   cy-ah),   (mid_x, cy+ah)],   fill=(255, 255, 255))
                else:
                    d.rectangle([x, cy-1, x+arrow_w, cy+1], fill=(180, 180, 180))
                x += arrow_w + gap

                # Number — anchor='mm' truly centers it on cy
                nx = x + int(num_w / 2)
                for dx in [-1, 0, 1]:
                    for dy in [-1, 0, 1]:
                        if dx == 0 and dy == 0: continue
                        d.text((nx+dx, cy+dy), num_part, font=f_num, fill=(0, 0, 0, 200), anchor='mm')
                d.text((nx, cy), num_part, font=f_num, fill=(255, 255, 255), anchor='mm')
                x += int(num_w)

                # Suffix — inline with inning number (no superscript raise)
                d.text((x, cy), suf_part, font=f_sup, fill=(190, 190, 190), anchor='lm')

            draw_inning_indicator(inn_cx, H // 2, is_top_inn, is_bot_inn, inn_ordinal)
            y_start = 4
            for (lbl, val, col) in bso_rows:
                draw_tiny_text(d, bso_cx - 8, y_start, lbl, (180, 180, 180))
                draw_tiny_text(d, bso_cx,     y_start, val, col)
                y_start += 8

            # ── Step 6: bat icon ─────────────────────────────────────────────
            if is_top_inn:
                self.draw_bat(d, int(h_sc_x + h_sc_w + 8), 7)   # away (top) now on left
            elif is_bot_inn:
                self.draw_bat(d, int(a_sc_x - a_sc_w - 8), 7)   # home (bot) now on right

            # ── Step 7: batter / pitcher detail blocks in side lanes ────────
            def _short_last_name(raw, max_chars=10):
                txt = str(raw or '').strip()
                if not txt:
                    return ''
                parts = [p for p in txt.replace('.', ' ').split() if p]
                _SUFFIXES = {'JR', 'SR', 'II', 'III', 'IV', 'V', 'VI'}
                if len(parts) >= 2 and parts[-1].upper() in _SUFFIXES:
                    last = f"{parts[-2]} {parts[-1]}"
                else:
                    last = parts[-1] if parts else txt
                return last.upper()[:max_chars]

            def _trim_line(raw, max_chars=15):
                return str(raw or '').strip()[:max_chars]

            def _draw_info_block(cx, lines, y0=None):
                non_empty = sum(1 for l in lines if str(l or '').strip())
                if non_empty >= 4:
                    start = 4 if y0 is None else y0
                    spacing = 8
                else:
                    start = 7 if y0 is None else y0
                    spacing = 9
                y = start
                for index, line in enumerate(lines):
                    line_txt = _trim_line(line)
                    if line_txt:
                        self.draw_outlined_text(
                            d,
                            int(cx),
                            y,
                            line_txt,
                            self.font if index == 0 else self.tiny_small,
                            (255, 255, 255),
                            (0, 0, 0, 235),
                            anchor='mm'
                        )
                    y += spacing

            batter_name  = _short_last_name(sit.get('batter_name', ''))
            pitcher_name = _short_last_name(sit.get('pitcher_name', ''))
            batter_avg   = sit.get('batter_avg', '')
            batter_h     = sit.get('batter_h', '')
            batter_ab    = sit.get('batter_ab', '')
            pit_pitches  = sit.get('pitcher_pitches', 0)
            last_spd     = sit.get('last_pitch_speed', 0)
            last_pitch   = sit.get('last_pitch_type', '')

            batter_avg_txt = str(batter_avg or '').strip()
            if batter_avg_txt.startswith('0.'):
                batter_avg_txt = batter_avg_txt[1:]

            batter_h_txt = str(batter_h or '').strip()
            batter_ab_txt = str(batter_ab or '').strip()
            if batter_h_txt and batter_ab_txt:
                batter_hits_ab_line = f"{batter_h_txt}/{batter_ab_txt}"
            elif batter_h_txt:
                batter_hits_ab_line = f"{batter_h_txt}/-"
            elif batter_ab_txt:
                batter_hits_ab_line = f"-/{batter_ab_txt}"
            else:
                batter_hits_ab_line = ''

            if batter_avg_txt:
                batter_avg_line = batter_avg_txt
            else:
                batter_avg_line = ''

            pitch_count_line = ''
            if str(pit_pitches).strip() and str(pit_pitches).strip() != '0':
                pitch_count_line = f"P:{pit_pitches}"

            pitch_type_line = str(last_pitch or '').strip()
            if str(last_spd).strip() and str(last_spd).strip() != '0' and pitch_type_line:
                pitch_info_line = f"{last_spd} {pitch_type_line}"
            elif str(last_spd).strip() and str(last_spd).strip() != '0':
                pitch_info_line = f"{last_spd} MPH"
            else:
                pitch_info_line = pitch_type_line

            # The V2 projector owns the active-team marker.
            # home_ab is the visual-left team after the home/away swap.
            home_batting = bool(home_ab and poss_ab and poss_ab == home_ab)
            away_batting = bool(away_ab and poss_ab and poss_ab == away_ab)

            info_lane_spread = 92
            info_left_cx  = W // 2 - info_lane_spread
            info_right_cx = W // 2 + info_lane_spread

            bat_lines = [batter_name, batter_hits_ab_line, batter_avg_line]
            pit_lines = [pitcher_name, pitch_count_line, pitch_info_line]

            if home_batting and not away_batting:
                _draw_info_block(info_left_cx, bat_lines)
                _draw_info_block(info_right_cx, pit_lines)
            elif away_batting and not home_batting:
                _draw_info_block(info_left_cx, pit_lines)
                _draw_info_block(info_right_cx, bat_lines)
            else:
                _draw_info_block(info_left_cx, pit_lines)
                _draw_info_block(info_right_cx, bat_lines)

            return img

        # ── NHL / NBA: side scrims (alpha_composite) then text on top ────────

        # Hockey PP / EN badges
        h_badge = a_badge = ''
        if is_nhl and sit.get('emptyNet'):
            en_side = str(sit.get('emptyNetSide', '')).strip().upper()
            if en_side == home_ab or (not en_side and poss_ab == home_ab):
                h_badge = 'EN'
            elif en_side == away_ab or (not en_side and poss_ab == away_ab):
                a_badge = 'EN'
            else:
                h_badge = 'EN' if poss_ab == home_ab else 'EN'
        elif is_nhl and sit.get('powerPlay'):
            if poss_ab == home_ab:   h_badge = 'PP'
            elif poss_ab == away_ab: a_badge = 'PP'

        # Side scrims via alpha_composite (correct blending)
        scrim = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        sd = ImageDraw.Draw(scrim)
        SOLID, FADE = 45, 80
        for x in range(SOLID + FADE):
            a = 250 if x < SOLID else max(0, int(250 * (SOLID + FADE - x) / FADE))
            sd.line([(x, 0), (x, H)],             fill=(0, 0, 0, a))
            sd.line([(W - 1 - x, 0), (W - 1 - x, H)], fill=(0, 0, 0, a))
        img.alpha_composite(scrim)

        # Centre text (period + context) — drawn AFTER scrim so it's visible
        prd = self.shorten_status(game.get('status', ''), sport)
        cx  = W // 2
        if prd:
            self.draw_outlined_text(d, cx, H // 2, prd,
                                    self.big_font, (255, 255, 255), (0, 0, 0, 200))

        # Team-color borders
        d.rectangle([0, 0, 2, H],     fill=home_clr)
        d.rectangle([W - 3, 0, W, H], fill=away_clr)

        # Hockey badges: compact text-only labels (avoid full-height side blocks)
        l_used = 3; r_used = 3

        # Logos
        LOGO_SZ  = 24
        h_logo_x = l_used + 5
        a_logo_x = W - r_used - LOGO_SZ - 5
        logo_y   = (H - LOGO_SZ) // 2
        hl = self.get_logo(game.get('home_logo'), (LOGO_SZ, LOGO_SZ))
        al = self.get_logo(game.get('away_logo'), (LOGO_SZ, LOGO_SZ))
        if hl: img.paste(hl, (h_logo_x, logo_y), hl)
        if al: img.paste(al, (a_logo_x, logo_y), al)

        # Scores
        h_sc_x = h_logo_x + LOGO_SZ + 4
        a_sc_x = a_logo_x - 4
        self.draw_outlined_text(d, h_sc_x, H // 2, h_score,
                                self.clock_giant, (255, 255, 255), (0, 0, 0, 200), anchor='lm')
        h_sc_w = d.textlength(h_score, font=self.clock_giant)
        self.draw_outlined_text(d, a_sc_x, H // 2, a_score,
                                self.clock_giant, (255, 255, 255), (0, 0, 0, 200), anchor='rm')
        a_sc_w = d.textlength(a_score, font=self.clock_giant)

        if h_badge:
            h_col = (255, 204, 0) if h_badge == 'PP' else (255, 90, 90)
            h_badge_x = int(h_sc_x + h_sc_w + 9)
            self.draw_outlined_text(d, h_badge_x, H // 2, h_badge,
                                    self.tiny, h_col, (0, 0, 0, 220), anchor='mm')
        if a_badge:
            a_col = (255, 204, 0) if a_badge == 'PP' else (255, 90, 90)
            a_badge_x = int(a_sc_x - a_sc_w - 9)
            self.draw_outlined_text(d, a_badge_x, H // 2, a_badge,
                                    self.tiny, a_col, (0, 0, 0, 220), anchor='mm')

        if is_nhl and sit.get('shootout'):
            so_h = sit.get('shootout', {}).get('home', [])
            so_a = sit.get('shootout', {}).get('away', [])
            so_h_x = int(h_sc_x + h_sc_w + 10)
            so_a_x = int(a_sc_x - a_sc_w - 15)
            self._draw_nhl_so_col(d, so_h_x, 6, so_h)
            self._draw_nhl_so_col(d, so_a_x, 6, so_a)

        # No possession arrow for hockey/basketball full-bleed mode.

        return img

    # ── Sport background helpers — exact ports of the HTML JS functions ──────

    def _draw_hockey_rink(self, d, W, H):
        """
        Port of HTML hockeyRink() — ice blue surface, blue lines, red lines,
        face-off circles, goal creases, and nets.
        HTML uses rounded clipPath corners; we approximate with a rounded rectangle
        drawn on top at the end.
        """
        bl1 = W * 0.28
        bl2 = W * 0.72
        gl1 = W * 0.085
        gl2 = W * 0.915

        # Ice surface + lighter zone tints
        d.rectangle([0, 0, W, H], fill=(205, 228, 248))
        d.rectangle([0, 0, bl1, H],    fill=(196, 219, 244))
        d.rectangle([bl2, 0, W, H],    fill=(196, 219, 244))

        # Removed horizontal texture lines to avoid stray white-line artifacts
        # on the LED matrix/emulator rendering.

        # Blue lines (2.5px wide each)
        d.rectangle([bl1 - 1, 0, bl1 + 1.5, H], fill=(34, 85, 204))
        d.rectangle([bl2 - 1, 0, bl2 + 1.5, H], fill=(34, 85, 204))

        # Neutral-zone faceoff dots just inside the neutral zone near each blue line
        neutral_dot_r = 2
        neutral_dot_fill = (204, 26, 26, 210)
        neutral_dot_outline = (140, 12, 12, 220)
        neutral_x_off = max(4, int(W * 0.02))
        for fx, fy in [
            (bl1 + neutral_x_off, H * 0.28),
            (bl1 + neutral_x_off, H * 0.72),
            (bl2 - neutral_x_off, H * 0.28),
            (bl2 - neutral_x_off, H * 0.72),
        ]:
            d.ellipse([fx - neutral_dot_r, fy - neutral_dot_r, fx + neutral_dot_r, fy + neutral_dot_r],
                      fill=neutral_dot_fill, outline=neutral_dot_outline)

        # Center red line — dashed (6 segments)
        dash_h = int(H / 6 * 0.7)
        for i in range(6):
            ry = int(i * H / 6)
            d.rectangle([W / 2 - 0.6, ry, W / 2 + 0.6, ry + dash_h], fill=(204, 26, 26))

        # Goal lines
        d.line([(gl1, 0), (gl1, H)], fill=(204, 26, 26), width=1)
        d.line([(gl2, 0), (gl2, H)], fill=(204, 26, 26), width=1)

        # Center circle + dot
        cr = H * 0.40
        d.ellipse([W/2 - cr, H/2 - cr, W/2 + cr, H/2 + cr],
                  outline=(204, 26, 26, 128), width=1)
        d.ellipse([W/2 - 2, H/2 - 2, W/2 + 2, H/2 + 2], fill=(204, 26, 26, 179))

        # Zone face-off dots + circles
        fo_r = H * 0.25
        fo_dot = 2.5
        for fx, fy in [
            (bl1 * 0.5,            H * 0.28),
            (bl1 * 0.5,            H * 0.72),
            (bl2 + (W - bl2) * 0.5, H * 0.28),
            (bl2 + (W - bl2) * 0.5, H * 0.72),
        ]:
            d.ellipse([fx - fo_dot, fy - fo_dot, fx + fo_dot, fy + fo_dot],
                      fill=(204, 26, 26, 179))
            d.ellipse([fx - fo_r, fy - fo_r, fx + fo_r, fy + fo_r],
                      outline=(204, 26, 26, 89), width=1)

        # Goal creases — arcs opening inward from each goal line
        cr2 = H * 0.32
        # Left crease opens rightward (arc from 270° to 90°, i.e. right half of circle)
        d.arc([gl1 - cr2, H/2 - cr2, gl1 + cr2, H/2 + cr2],
              start=270, end=90, fill=(68, 136, 238), width=1)
        # Right crease opens leftward
        d.arc([gl2 - cr2, H/2 - cr2, gl2 + cr2, H/2 + cr2],
              start=90, end=270, fill=(68, 136, 238), width=1)

        # Goalie nets (small rectangles just outside goal lines)
        nh = int(H * 0.28)
        ny = (H - nh) // 2
        d.rectangle([gl1,     ny, gl1 + 4, ny + nh], fill=(221, 221, 221), outline=(153, 153, 153))
        d.rectangle([gl2 - 4, ny, gl2,     ny + nh], fill=(221, 221, 221), outline=(153, 153, 153))

        # Rounded corner overlay (simulate HTML clipPath rx)
        cr_r = H * 0.45
        d.rounded_rectangle([0, 0, W - 1, H - 1], radius=int(cr_r),
                             outline=(122, 173, 206), width=1)

    def _draw_baseball_diamond(self, d, W, H, sit):
        """
        Infield drawn on an integer lattice: the diamond centre and its radius are
        both whole pixels, so every base path is exactly r across and r down and
        rasterises as a clean 45° run.

        The previous fractional geometry (cy=H*0.55, r=H*0.42) rounded to base
        centres of home(192,31) first(205,18) 2nd(192,4) third(179,18) — home->1st
        and 3rd->home came out 13x13, but 1st->2nd and 2nd->3rd came out 13x14, so
        those two paths rasterised with a doubled step and read as squiggles.
        Bases are scan-converted for the same reason: a polygon with fractional
        vertices produces lopsided rows instead of a square on point.
        """
        # Blue stays near zero because a colour carrying equal red and blue sits
        # too close to neutral to survive the panel — that is what made the old
        # grass read teal and the old dirt pale pink. Red sits above blue so the
        # grass lands olive rather than a pure saturated green, and the two
        # stripes are only six levels apart so the mow reads as texture instead
        # of banding. Preview renders will not show this — verify on hardware.
        #
        # The dirt carries real blue, which is what keeps it off yellow — a warm
        # colour starved of blue has nowhere to sit but yellow, and at 4% of red
        # the old value did not have enough to stay brown. Green is the lever if
        # it ever drifts yellow again, not red: green relative to red is what
        # reads as yellow, and this sits at about half. It is also the largest
        # bright area on the card, so it is the first thing to pull the chain
        # past its current limit — but at 44% total emitted duty it now asks for
        # slightly less than the value it replaced.
        GRASS_A = (8, 28, 4)
        GRASS_B = (11, 34, 6)
        DIRT    = (153, 111, 49)   # #996F31
        CHALK   = (232, 232, 232)

        cx = W // 2
        r  = int(round(H * 0.41))   # centre -> base: 13 at H=32
        cy = int(round(H * 0.53))   # 17 at H=32, so 2nd lands at y=4, home at y=30
        bk = max(2, int(round(H * 0.13)))   # base half-diagonal: 4 at H=32

        home  = (cx,     cy + r)
        first = (cx + r, cy)
        sec   = (cx,     cy - r)
        third = (cx - r, cy)

        def pixel_diamond(x, y, k, color):
            """Filled diamond: row i spans exactly k-|i| pixels either side."""
            for i in range(-k, k + 1):
                half = k - abs(i)
                d.line([(x - half, y + i), (x + half, y + i)], fill=color)

        def diagonal(p0, p1, color):
            """Exact 45° pixel run, stepping one pixel on both axes per step."""
            x0, y0 = p0
            x1, y1 = p1
            sx = 1 if x1 > x0 else -1
            sy = 1 if y1 > y0 else -1
            for i in range(abs(x1 - x0) + 1):
                d.point((x0 + i * sx, y0 + i * sy), fill=color)

        # 1 · Outfield grass, mown in stripes that only start once the scrim has
        #     let go. A stripe boundary inside the scrim span breaks the fade:
        #     the light stripe running x=38..77 climbed brighter than the field
        #     beyond the fade, then dropped 12 levels at its edge, so instead of
        #     a ramp to black you saw a bright band floating in the gradient.
        #     Holding stripe contrast at zero for the whole span and easing it in
        #     over the next 40px leaves the fade strictly monotonic.
        STRIPE_EASE = 40
        for x in range(W):
            t = (min(x, W - 1 - x) - SIDE_SCRIM_SPAN) / STRIPE_EASE
            t = max(0.0, min(1.0, t))
            if t > 0 and int(x * 10 / W) % 2:
                col = tuple(int(round(a + (b - a) * t))
                            for a, b in zip(GRASS_A, GRASS_B))
            else:
                col = GRASS_A
            d.line([(x, 0), (x, H)], fill=col)

        # 2 · Infield skin — bows up from below the panel, wide enough that all
        #     three bags sit on dirt rather than poking out into the grass.
        d.ellipse([cx - r - 7, cy + 3 - r - 8, cx + r + 7, cy + 3 + r + 8], fill=DIRT)

        # 3 · Infield grass, inset far enough that the base paths read as a dirt
        #     strip and the grass corners stay clear of the bags
        pixel_diamond(cx, cy, r - 4, GRASS_A)

        # 4 · Base paths
        for p0, p1 in ((home, first), (first, sec), (sec, third), (third, home)):
            diagonal(p0, p1, CHALK)

        # 5 · Pitcher's mound + rubber
        d.ellipse([cx - 3, cy - 2, cx + 3, cy + 2], fill=DIRT)
        d.line([(cx - 1, cy), (cx + 1, cy)], fill=CHALK)

        # 6 · Home-plate dirt circle
        d.ellipse([home[0] - 5, home[1] - 4, home[0] + 5, home[1] + 4], fill=DIRT)

        # 7 · Bases
        def draw_base(pt, on):
            pixel_diamond(pt[0], pt[1], bk, (0, 0, 0))
            pixel_diamond(pt[0], pt[1], bk - 1,
                          (255, 204, 0) if on else (255, 255, 255))

        draw_base(third, sit.get('onThird',  False))
        draw_base(first, sit.get('onFirst',  False))
        draw_base(sec,   sit.get('onSecond', False))

        # 8 · Home plate — pentagon, pointing down toward the backstop
        hx, hy = home
        d.rectangle([hx - 2, hy - 2, hx + 2, hy - 1], fill=(255, 255, 255))
        d.line([(hx - 1, hy), (hx + 1, hy)], fill=(255, 255, 255))
        d.point((hx, hy + 1), fill=(255, 255, 255))

    def _draw_basketball_court(self, d, W, H):
        """
        Exact port of HTML basketballCourt().
        lW=W*0.18  lH=H*0.62  lY=(H-lH)/2  thR=H*0.54
        """
        lW  = W * 0.18
        lH  = H * 0.62
        lY  = (H - lH) / 2
        thR = H * 0.54

        # 1 · Floor (hardwood orange)
        d.rectangle([0, 0, W, H], fill=(200, 120, 58))

          # 2 · Court boundary
        d.rectangle([1, 1, W - 2, H - 2], outline=(255, 255, 255, 128))

          # 3 · Half-court line + centre circle
        d.line([(W / 2, 0), (W / 2, H)], fill=(255, 255, 255, 115))
        cr = H * 0.33
        d.ellipse([W/2 - cr, H/2 - cr, W/2 + cr, H/2 + cr], outline=(255, 255, 255, 97))

          # 4 · Paint lanes (left and right)
        d.rectangle([0,      lY, lW,     lY + lH], fill=(160, 80, 32), outline=(255, 255, 255, 140))
        d.rectangle([W - lW, lY, W,      lY + lH], fill=(160, 80, 32), outline=(255, 255, 255, 140))

          # 5 · Free-throw circles
        ftc_r = lH * 0.26
        d.ellipse([lW - ftc_r, H/2 - ftc_r, lW + ftc_r, H/2 + ftc_r],
                  outline=(255, 255, 255, 97))
        d.ellipse([W - lW - ftc_r, H/2 - ftc_r, W - lW + ftc_r, H/2 + ftc_r],
                  outline=(255, 255, 255, 97))

          # 6 · Three-point arcs
        d.arc([0 - thR, lY - 4, thR,     lY + lH + 4], start=270, end=90,
              fill=(255, 255, 255, 97))
        d.arc([W - thR, lY - 4, W + thR, lY + lH + 4], start=90,  end=270,
              fill=(255, 255, 255, 97))

          # 7 · Basket posts (vertical lines at ~45% of lane width from edge)
        px_l = lW * 0.45
        px_r = W - px_l
        d.line([(px_l, H * 0.33), (px_l, H * 0.67)], fill=(220, 220, 220, 165), width=1)
        d.line([(px_r, H * 0.33), (px_r, H * 0.67)], fill=(220, 220, 220, 165), width=1)


class PreparedSportsFullRenderer(SportsMixin):
    """Provide the explicit dependencies for full sports rendering."""

    def __init__(self, fonts, logos):
        self.big_font = fonts.big
        self.clock_giant = fonts.clock
        self.tiny = fonts.tiny
        self.tiny_small = fonts.tiny_small
        self.micro = fonts.micro
        self.font = fonts.normal
        self._logos = logos

    def get_logo(self, url, size):
        """Return a prepared logo and never fetch from the renderer."""
        return self._logos.get(str(url) if url else None, size)

    def draw_outlined_text(self, draw, x, y, text, font, fill, outline, anchor="mm"):
        """Draw a deterministic one-pixel text outline."""
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                if dx or dy:
                    draw.text((x + dx, y + dy), text, font=font, fill=outline, anchor=anchor)
        draw.text((x, y), text, font=font, fill=fill, anchor=anchor)

    def get_team_color(self, game, side="home"):
        """Return the configured team colour or a logo average."""
        value = game.get(f"{side}_color")
        if value:
            try:
                value = str(value).lstrip("#")
                return tuple(int(value[index:index + 2], 16) for index in (0, 2, 4))
            except (TypeError, ValueError):
                pass
        logo = self.get_logo(game.get(f"{side}_logo"), (24, 24))
        if logo:
            return tuple(int(value) for value in ImageStat.Stat(logo).mean[:3])
        return (60, 60, 60)

    @staticmethod
    def _parse_hex_color(value):
        """Parse one RGB hex value."""
        try:
            value = str(value or "").strip().lstrip("#")
            if len(value) == 6:
                return tuple(int(value[index:index + 2], 16) for index in (0, 2, 4))
        except ValueError:
            pass
        return None

    @staticmethod
    def _is_near_black(color, lum_threshold=24, max_threshold=42, chroma_threshold=16):
        """Identify colours that disappear on the panel."""
        if not color or len(color) < 3:
            return True
        red, green, blue = (int(value) for value in color[:3])
        luma = 0.2126 * red + 0.7152 * green + 0.0722 * blue
        return (max(red, green, blue) <= max_threshold and luma <= lum_threshold) or (max(red, green, blue) <= max_threshold + 6 and luma <= lum_threshold + 4 and max(red, green, blue) - min(red, green, blue) <= chroma_threshold)

    @staticmethod
    def _is_near_white(color, lum_threshold=236, min_channel_threshold=226):
        """Identify colours that remove contrast."""
        if not color or len(color) < 3:
            return False
        red, green, blue = (int(value) for value in color[:3])
        return 0.2126 * red + 0.7152 * green + 0.0722 * blue >= lum_threshold or min(red, green, blue) >= min_channel_threshold

    def _resolve_challenge_strip_color(self, game, side, fallback):
        """Resolve one readable challenge strip colour."""
        primary = self._parse_hex_color(game.get(f"{side}_color"))
        if primary and not self._is_near_black(primary):
            return primary
        alternate = self._parse_hex_color(game.get(f"{side}_alt_color"))
        if alternate and not self._is_near_black(alternate) and not self._is_near_white(alternate):
            return alternate
        return alternate or primary or fallback

    @staticmethod
    def shorten_status(status, sport=""):
        """Return the controller status abbreviation."""
        if not status:
            return ""
        if any(word in str(status).lower() for word in ("delay", "delayed", "suspended", "postponed", "canceled", "ppd")):
            return str(status).title()
        text = str(status).upper().replace(" - ", " ").replace("/OT", " OT").replace("HALFTIME", "HALF")
        for old, new in (("TOP ", "^"), ("BOTTOM ", "V"), ("BOT ", "V")):
            text = text.replace(old, new)
        if text.startswith("END "):
            return text
        for number in ("10", "11", "12", "1", "2", "3", "4", "5", "6", "7", "8", "9"):
            for suffix in ("TH", "ST", "ND", "RD"):
                text = text.replace(f"{number}{suffix}", number)
        text = text.replace("1ST", "P1").replace("2ND", "P2").replace("3RD", "P3").replace("4TH", "P4").replace("FULL TIME", "FT")
        for period in ("P1", "P2", "P3", "P4", "Q1", "Q2", "Q3", "Q4", "OT"):
            text = text.replace(f"{period} ", f"{period}~")
        return text

    @staticmethod
    def draw_bat(draw, cx, by):
        """Draw the compact baseball bat marker."""
        draw.rectangle([cx - 2, by, cx + 1, by + 7], fill=(220, 180, 120))
        draw.rectangle([cx - 1, by + 8, cx, by + 9], fill=(220, 180, 120))
        draw.rectangle([cx - 1, by + 10, cx, by + 15], fill=(180, 135, 65))
        draw.rectangle([cx - 2, by + 16, cx + 1, by + 17], fill=(150, 105, 40))
