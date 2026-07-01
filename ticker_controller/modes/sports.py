import math
import time
from PIL import Image, ImageDraw
from ..config import PANEL_W, PANEL_H
from ..fonts import draw_tiny_text, draw_hybrid_text, normalize_special_chars


class SportsMixin:

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

    def draw_baseball_hud(self, draw, x, y, o):
        for i in range(3): draw.rectangle((x+(i*4), y, x+(i*4)+1, y+1), fill=((255, 0, 0) if i < o else (40, 40, 40)))

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
        poss_ab  = str(sit.get('possession', '')).upper()

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

            # 5 · Parse LOS and yards-to-go from situation
            los, ytg = -1, 10
            dd_text  = sit.get('downDist', '')
            at_team = ''
            is_goal_to_go = False
            drive_to_right = None  # True => offense driving toward right endzone
            parsed_yard = None
            if ' at ' in dd_text:
                after = dd_text.split(' at ', 1)[1].strip().split()
                if len(after) >= 2:
                    team, yard_s = after[0].upper(), after[1]
                    at_team = team
                    try:
                        yard = int(yard_s)
                        parsed_yard = yard
                        los = yard if team == home_ab else (100 - yard if team == away_ab else 50)
                    except ValueError:
                        pass
            if '&' in dd_text and los >= 0:
                ytg_raw = dd_text.split('&', 1)[1].strip().split()[0].lower()
                if ytg_raw in ('goal', 'gl'):
                    is_goal_to_go = True
                else:
                    try: ytg = int(ytg_raw)
                    except ValueError: ytg = 10
            elif ' and ' in dd_text.lower() and los >= 0:
                # ESPN downDistanceText uses "and" (e.g. "3rd and 7 at KC 48")
                before_at = dd_text.split(' at ')[0] if ' at ' in dd_text else dd_text
                parts = before_at.lower().split(' and ')
                if len(parts) >= 2:
                    ytg_raw = parts[1].strip().split()[0].rstrip('.,')
                    if ytg_raw in ('goal', 'gl', 'goal:'):
                        is_goal_to_go = True
                    else:
                        try: ytg = int(ytg_raw)
                        except ValueError: pass

            # Fallback: use numeric yardLine/yardsToGo fields if text parsing gave no LOS
            if los < 0 and sit.get('yardLine') is not None:
                raw_yl = int(sit.get('yardLine', 50))
                pos_team = str(sit.get('possessionTeam', sit.get('yardLineTeam', ''))).upper()
                if pos_team == home_ab:
                    los = raw_yl
                elif pos_team == away_ab:
                    los = 100 - raw_yl
                else:
                    los = raw_yl if raw_yl <= 50 else 100 - raw_yl
                if sit.get('yardsToGo') is not None:
                    ytg = max(1, int(sit.get('yardsToGo', 10)))

            # Infer drive direction once and use it everywhere (FD line + red-zone).
            if poss_ab == home_ab:
                drive_to_right = True
            elif poss_ab == away_ab:
                drive_to_right = False

            # Goal-to-go marker is most reliable for direction when possession is noisy.
            if is_goal_to_go and at_team:
                if poss_ab in (home_ab, away_ab):
                    if at_team == poss_ab:
                        # Offense on its own side: attacking opposite endzone.
                        drive_to_right = (poss_ab == home_ab)
                    else:
                        # Offense in opponent territory: attacking that side's endzone.
                        drive_to_right = (at_team == away_ab)
                elif at_team == home_ab:
                    drive_to_right = False
                elif at_team == away_ab:
                    drive_to_right = True

            if drive_to_right is None:
                drive_to_right = True

            if is_goal_to_go and los >= 0:
                if parsed_yard is not None:
                    ytg = max(1, parsed_yard)
                    los = max(0, min(100, 100 - parsed_yard if drive_to_right else parsed_yard))
                else:
                    goal_line = 100 if drive_to_right else 0
                    ytg = max(1, abs(goal_line - los))
                    # For goal-to-go visuals, place LOS near the attacking goal line
                    # so the ball/FD/red-zone all live on the scoring side.
                    los = max(0, min(100, 100 - ytg if drive_to_right else ytg))

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
            ctx     = dd_text.split(' at ')[0].strip() if ' at ' in dd_text else dd_text
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
            score_y   = int(H * 0.82)
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
            score_box_top = score_y - (11 // 2)          # top edge of score badge
            logo_top_up   = max(0, score_box_top - LOGO_SZ - 1)  # just above the badge
            h_logo_top = logo_top_up if h_sc_cx == h_logo_cx else logo_top_center
            a_logo_top = logo_top_up if a_sc_cx == a_logo_cx else logo_top_center

            def _black_ring_logo(logo):
                """Convert the artificial white enhancement ring to black (copy only)."""
                ls = logo.resize((LOGO_SZ, LOGO_SZ), Image.LANCZOS)
                px = ls.load()
                for yy in range(ls.height):
                    for xx in range(ls.width):
                        r, g, b, a = px[xx, yy]
                        # Target the white ring added by _enhance_logo_visibility:
                        # alpha ~230, RGB all very white (>220). Fully-opaque white
                        # pixels inside the logo (a==255) are intentional — skip those.
                        if 180 < a < 252 and r > 220 and g > 220 and b > 220:
                            px[xx, yy] = (0, 0, 0, a)
                return ls

            hl = self.get_logo(game.get('home_logo'), (24, 24))
            al = self.get_logo(game.get('away_logo'), (24, 24))
            if hl:
                ls = _black_ring_logo(hl)
                img.paste(ls, (h_logo_cx - LOGO_SZ // 2, h_logo_top), ls)
            if al:
                ls = _black_ring_logo(al)
                img.paste(ls, (a_logo_cx - LOGO_SZ // 2, a_logo_top), ls)

            for scx, sc in [(h_sc_cx, h_score), (a_sc_cx, a_score)]:
                if not sc: continue
                sw = (len(str(sc)) * 5) + 6
                sh = 11
                box_left = scx - (sw // 2)
                box_top = score_y - (sh // 2)
                text_w = len(str(sc)) * 5
                text_h = 6
                text_x = box_left + ((sw - text_w) // 2)
                text_y = box_top + ((sh - text_h + 1) // 2)
                # Conforming black outline: draw text shifted in 4 directions, then white on top
                for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                    draw_hybrid_text(d, text_x + dx, text_y + dy, str(sc), (0, 0, 0))
                draw_hybrid_text(d, text_x, text_y, str(sc), (255, 255, 255))

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

            status_text = str(game.get('status', '')).strip().title()
            if status_text:
                self.draw_outlined_text(d, W // 2, 7, status_text[:16], self.tiny, (255, 240, 150), (0, 0, 0, 220), anchor='ma')

            if sit.get('shootout'):
                so_a = sit.get('shootout', {}).get('away', [])
                so_h = sit.get('shootout', {}).get('home', [])
                self._draw_soccer_so_col(d, a_logo_x + LOGO_SZ + 2, 8, so_h)
                self._draw_soccer_so_col(d, h_logo_x - 5, 8, so_a)

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

            # ── Step 1: side scrims via alpha_composite (correct blending) ──
            # Drawing alpha lines directly on RGBA replaces pixels instead of blending.
            # Use a separate overlay and alpha_composite onto the base image.
            scrim = Image.new("RGBA", (W, H), (0, 0, 0, 0))
            sd = ImageDraw.Draw(scrim)
            SOLID, FADE = 45, 80
            for x in range(SOLID + FADE):
                a = 250 if x < SOLID else max(0, int(250 * (SOLID + FADE - x) / FADE))
                sd.line([(x, 0),         (x, H)],         fill=(0, 0, 0, a))
                sd.line([(W - 1 - x, 0), (W - 1 - x, H)], fill=(0, 0, 0, a))
            img.alpha_composite(scrim)
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

            def _compact_pitch_name(full_type, abbr_type):
                txt = str(full_type or '').strip()
                if txt:
                    txt = txt.split('(', 1)[0].strip()
                    txt = txt.split('/', 1)[0].strip()
                if not txt:
                    return str(abbr_type or '').strip().upper()[:10]
                if len(txt) > 12:
                    words = txt.replace('-', ' ').split()
                    if words:
                        txt = words[-1]
                return txt.title()[:12]

            def _draw_info_block(cx, lines, y0=None):
                non_empty = sum(1 for l in lines if str(l or '').strip())
                if non_empty >= 4:
                    start = 4 if y0 is None else y0
                    spacing = 8
                else:
                    start = 7 if y0 is None else y0
                    spacing = 9
                y = start
                for line in lines:
                    line_txt = _trim_line(line)
                    if line_txt:
                        self.draw_outlined_text(
                            d,
                            int(cx),
                            y,
                            line_txt,
                            self.tiny_small,
                            (255, 255, 255),
                            (0, 0, 0, 220),
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
            last_abbr    = sit.get('last_pitch_type_abbr', '') or sit.get('last_pitch_type', '')
            last_full    = sit.get('last_pitch_type_full', '')

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

            pitch_type_line = _compact_pitch_name(last_full, last_abbr)
            if str(last_spd).strip() and str(last_spd).strip() != '0' and pitch_type_line:
                pitch_info_line = f"{last_spd} {pitch_type_line}"
            elif str(last_spd).strip() and str(last_spd).strip() != '0':
                pitch_info_line = f"{last_spd} MPH"
            else:
                pitch_info_line = pitch_type_line

            # Prefer backend possession marker; fall back to inning state.
            # home_ab is now the visual-left (actual away) team after the home/away swap.
            home_batting = bool(home_ab and poss_ab and poss_ab == home_ab)
            away_batting = bool(away_ab and poss_ab and poss_ab == away_ab)
            if not home_batting and not away_batting:
                home_batting = is_top_inn and not is_mid_inn
                away_batting = is_bot_inn and not is_mid_inn
            if home_batting and away_batting:
                home_batting = is_top_inn and not is_mid_inn
                away_batting = is_bot_inn and not is_mid_inn

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
            # If home has possession (extra skater), home net is empty
            if poss_ab == home_ab:
                h_badge = 'EN'
            elif poss_ab == away_ab:
                a_badge = 'EN'
            else:
                a_badge = 'EN' # Fallback
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
        Port of HTML baseballDiamond().
        cx=W/2, cy=H*0.55, r=H*0.42, bs=H*0.16 (half-diagonal of rotated base).
        Base positions:  home=(cx,cy+r)  1B=(cx+r,cy)  2B=(cx,cy-r)  3B=(cx-r,cy)

        Key fix: the HTML dirt is an SVG arc path that bows UPWARD from below the canvas.
        Best PIL approximation is a filled ellipse centered at (cx, cy+r*0.1) with
        rx=r*1.4, ry=r*1.1 — this produces the correct kidney/infield-skin shape.
        """
        cx = W / 2
        cy = H * 0.55
        r  = H * 0.42
        bs = H * 0.16     # half-diagonal — bases are rotated squares drawn as diamonds

        home  = (cx,     cy + r)
        first = (cx + r, cy)
        sec   = (cx,     cy - r)
        third = (cx - r, cy)

        # 1 · Alternating grass bands (full width)
        for i in range(10):
            bx = i * W / 10
            d.rectangle([bx, 0, bx + W / 10, H],
                        fill=(17, 41, 17) if i % 2 == 0 else (21, 50, 21))

        # 2 · Dirt infield — ellipse centered just below diamond midpoint.
        #     The HTML uses an SVG arc path whose bottom goes off-canvas (y=home+3=~34)
        #     and whose curve bows upward; this ellipse replicates that visible shape.
        dc   = cy + r * 0.1     # ellipse centre y  (~19.0 for H=32)
        drx  = r * 1.4          # horizontal radius (~18.8)
        dry  = r * 1.1          # vertical radius   (~14.8)
        d.ellipse([cx - drx, dc - dry, cx + drx, dc + dry], fill=(158, 105, 68))

        # 3 · Inner grass diamond  (HTML: polygon with 2-px inset at each vertex)
        # The top vertex (2nd base) needs a larger inset so the grass doesn't
        # overlap the base: sec_y=4.2, bs=5.1, so base bottom=9.3 — inset by bs+1
        d.polygon([
            (cx,           home[1]  - 2),
            (first[0] - 2, first[1]),
            (cx,           sec[1]   + bs + 1),   # clear the base footprint
            (third[0] + 2, third[1]),
        ], fill=(17, 41, 17), outline=(158, 105, 68))

        # 4 · Pitcher's mound + rubber
        pr = r * 0.22
        d.ellipse([cx - pr, cy - pr, cx + pr, cy + pr], fill=(158, 105, 68))
        d.rectangle([cx - 1.5, cy - 0.5, cx + 1.5, cy + 0.5], fill=(255, 255, 255))

        # 5 · Home-plate dirt circle
        hpr = r * 0.28
        d.ellipse([home[0] - hpr, home[1] - hpr,
                   home[0] + hpr, home[1] + hpr], fill=(158, 105, 68))

        # 6 · Base lines
        for p1, p2 in [(home, first), (first, sec), (sec, third), (third, home)]:
            d.line([p1, p2], fill=(255, 255, 255, 204), width=1)

        # 7 · Bases — rotated squares (diamond polygons)
        # Note: 2nd base (sec) is at y=cy-r = H*0.13 ≈ 4px from top.
        # With bs=H*0.16≈5px the top point goes to y≈-1 (off screen).
        # Clip the top point of 2nd base to y=1 so it stays visible.
        def draw_base(pt, on):
            x, y = pt
            c = (255, 204, 0) if on else (255, 255, 255)
            top_y = max(1, y - bs)   # clamp top so it never goes off-canvas
            d.polygon([
                (x,      top_y),    # top  (clamped)
                (x + bs, y),        # right
                (x,      y + bs),   # bottom
                (x - bs, y),        # left
            ], fill=c, outline=(0, 0, 0))

        draw_base(third, sit.get('onThird',  False))
        draw_base(first, sit.get('onFirst',  False))
        draw_base(sec,   sit.get('onSecond', False))   # draw 2nd last — it's closest to top edge

        # 8 · Home plate — pentagon
        hp_s = r * 0.12
        d.polygon([
            (home[0],         home[1] + hp_s),
            (home[0] + hp_s,  home[1]),
            (home[0] + hp_s,  home[1] - hp_s),
            (home[0] - hp_s,  home[1] - hp_s),
            (home[0] - hp_s,  home[1]),
        ], fill=(255, 255, 255), outline=(0, 0, 0))

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
