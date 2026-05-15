import time
from datetime import datetime
from PIL import Image, ImageDraw
from ..config import PANEL_W, PANEL_H
from ..fonts import draw_tiny_text, draw_hybrid_text, normalize_special_chars


class GolfMixin:

    def draw_golf_scroll_card(self, game):
        """Compact top-3 golf card for sports/live mode scrolling strip. Matches stadium theme."""
        import re as _re
        W = 128
        img = Image.new("RGBA", (W, 32), (0, 0, 0, 255))
        d = ImageDraw.Draw(img)

        golf_payload = (game.get('golf') or game.get('masters') or {}) if isinstance(game, dict) else {}
        event_name = str(golf_payload.get('event_name') or game.get('away_abbr') or 'PGA TOUR').upper()
        round_label = str(golf_payload.get('round') or game.get('status') or '').upper()
        players = golf_payload.get('players', []) if isinstance(golf_payload.get('players'), list) else []
        pars_list = golf_payload.get('pars', []) if isinstance(golf_payload.get('pars'), list) else []

        # Header: full event name + round, centered (e.g. "PGA CHAMPIONSHIP R2")
        rnd_m = _re.search(r'\d+', round_label)
        rnd_short = f"R{rnd_m.group()}" if rnd_m else 'R-'
        header = f"{event_name} {rnd_short}"
        tw = len(header) * 5
        tx = max(1, (W - tw) // 2)
        draw_hybrid_text(d, tx + 1, 2, header, (8, 8, 8, 180))
        draw_hybrid_text(d, tx,     1, header, (255, 240, 150, 255))

        # Blue separator
        d.line([(0, 7), (W - 1, 7)], fill=(55, 76, 130))

        # Column layout (no logo — start at x=1)
        # POS: 3 chars (15px), NAME: 10 chars (50px), TODAY: 4 chars (20px), TOTAL: 4 chars (20px)
        POS_X    = 1
        NAME_X   = 18    # pos 15px + 2px gap
        TODAY_CX = 84    # center of today column; "TODAY" (25px) centered → label at 72
        TOTAL_CX = 112   # center of total column; "TOTAL" (25px) centered → label at 100, ends at 125

        # Column labels centered at column centers
        LABEL_COLOR = (80, 95, 130)
        draw_tiny_text(d, TODAY_CX - 12, 8, 'TODAY', LABEL_COLOR)
        draw_tiny_text(d, TOTAL_CX - 12, 8, 'TOTAL', LABEL_COLOR)

        def fmt_score(val):
            if val is None:
                return '--'
            try:
                v = int(val)
            except Exception:
                return str(val)
            if v == 0:
                return 'E'
            return f"+{v}" if v > 0 else str(v)

        def score_color(val):
            try:
                v = int(val)
                if v < 0:
                    return (100, 210, 100)
                if v > 0:
                    return (220, 80, 80)
            except Exception:
                pass
            return (255, 255, 255)

        top3 = [dict(p) for p in players if isinstance(p, dict) and str(p.get('pos', '')).upper() not in ('WD', 'DQ')][:3]
        if top3 and all(str(p.get('pos', '-')).strip() in ('-', '') for p in top3):
            totals = [p.get('total') for p in top3]
            rank = 1
            for idx, p in enumerate(top3):
                if idx > 0 and totals[idx] == totals[idx - 1]:
                    p['pos'] = top3[idx - 1]['pos']
                else:
                    rank = idx + 1
                    p['pos'] = ('T' + str(rank)) if totals.count(totals[idx]) > 1 else str(rank)
        row_ys = [14, 20, 26]

        if not top3:
            draw_tiny_text(d, NAME_X, 18, 'LOADING', (150, 150, 150))
        else:
            for i, p in enumerate(top3):
                y = row_ys[i]
                pos   = str(p.get('pos', '-')).upper()[:3]
                name  = str(p.get('name', '')).upper()[:10]
                total = p.get('total')
                try:
                    thru = int(p.get('thru', 0) or 0)
                except (TypeError, ValueError):
                    thru = 18 if str(p.get('thru', '')).upper() == 'F' else 0
                holes_data = p.get('holes', [])
                if not isinstance(holes_data, list):
                    holes_data = []
                holes_with_scores = sum(1 for h in holes_data if h is not None)
                in_round = thru > 0 or (0 < holes_with_scores < 18)
                today = p.get('today') if in_round else None
                if today is None and in_round and pars_list:
                    played = [(h, pars_list[j]) for j, h in enumerate(holes_data[:18]) if h is not None and j < len(pars_list)]
                    if played:
                        today = sum(h - par for h, par in played)

                if pos.replace('T', '') == '1':
                    pos_color = (255, 215, 0)
                elif pos == 'CUT':
                    pos_color = (220, 80, 80)
                else:
                    pos_color = (200, 200, 200)

                today_str = fmt_score(today)
                total_str = fmt_score(total)
                draw_tiny_text(d, POS_X,                          y, pos,       pos_color)
                draw_tiny_text(d, NAME_X,                         y, name,      (255, 255, 255))
                draw_tiny_text(d, TODAY_CX - len(today_str)*5//2, y, today_str, score_color(today))
                draw_tiny_text(d, TOTAL_CX - len(total_str)*5//2, y, total_str, score_color(total))

        return img

    def _golf_colors(self, game):
        def hex_rgba(h, fallback):
            try:
                h = str(h or '').lstrip('#')
                return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), 255)
            except Exception:
                return fallback
        primary = hex_rgba(game.get('away_color', ''), (200, 168, 75, 255))
        bg      = hex_rgba(game.get('away_alt_color', ''), (0, 76, 53, 255))
        return {
            'bg': bg,
            'gold': primary,
            'stripe_lead': primary,
            'dot_active': primary,
            'eagle': (250, 204, 21, 255),
            'birdie': (34, 197, 94, 255),
            'bogey': (239, 68, 68, 255),
            'double': (153, 27, 27, 255),
            'par_border': (245, 220, 130, 255),
            'white': (255, 255, 255, 255),
            'label_gray': (235, 245, 225, 255),
            'black': (0, 0, 0, 255),
            'dot_idle': (132, 132, 132, 255),
        }

    def draw_golf_mode(self, game):
        if not hasattr(self, 'golf_current_pair'):
            self.golf_current_pair = 0
            self.golf_last_switch = time.time()

        if not hasattr(self, 'M_FONT'):
            self.M_FONT = {
                'A': [2, 5, 7, 5, 5], 'B': [6, 5, 7, 5, 6], 'C': [7, 4, 4, 4, 7], 'D': [6, 5, 5, 5, 6],
                'E': [7, 4, 7, 4, 7], 'F': [7, 4, 7, 4, 4], 'G': [7, 4, 5, 5, 7], 'H': [5, 5, 7, 5, 5],
                'I': [7, 2, 2, 2, 7], 'J': [1, 1, 1, 5, 2], 'K': [5, 6, 4, 6, 5], 'L': [4, 4, 4, 4, 7],
                'M': [5, 7, 7, 5, 5], 'N': [5, 7, 5, 5, 5], 'O': [7, 5, 5, 5, 7], 'P': [7, 5, 7, 4, 4],
                'Q': [7, 5, 5, 7, 1], 'R': [7, 5, 6, 5, 5], 'S': [7, 4, 7, 1, 7], 'T': [7, 2, 2, 2, 2],
                'U': [5, 5, 5, 5, 7], 'V': [5, 5, 5, 2, 2], 'W': [5, 5, 7, 7, 5], 'X': [5, 5, 2, 5, 5],
                'Y': [5, 5, 2, 2, 2], 'Z': [7, 1, 2, 4, 7], '0': [7, 5, 5, 5, 7], '1': [2, 6, 2, 2, 7],
                '2': [7, 1, 7, 4, 7], '3': [7, 1, 7, 1, 7], '4': [5, 5, 7, 1, 1], '5': [7, 4, 7, 1, 7],
                '6': [7, 4, 7, 5, 7], '7': [7, 1, 1, 1, 1], '8': [7, 5, 7, 5, 7], '9': [7, 5, 7, 1, 7],
                '-': [0, 0, 7, 0, 0], '+': [0, 2, 7, 2, 0], '.': [0, 0, 0, 0, 2], ' ': [0, 0, 0, 0, 0]
            }

        M_COLORS = self._golf_colors(game)

        img = Image.new("RGBA", (PANEL_W, 32), M_COLORS['bg'])
        d = ImageDraw.Draw(img)

        golf_payload = (game.get('golf') or game.get('masters') or {}) if isinstance(game, dict) else {}
        event_name = str(golf_payload.get('event_name') or 'PGA TOUR').upper()
        year = str(golf_payload.get('year') or game.get('away_score') or datetime.now().year)
        brand_lines = golf_payload.get('brand') if isinstance(golf_payload.get('brand'), list) else []
        pars = golf_payload.get('pars', []) if isinstance(golf_payload.get('pars'), list) else []
        if len(pars) < 18:
            pars = [4, 5, 4, 3, 4, 3, 4, 5, 4, 4, 3, 4, 5, 4, 5, 3, 4, 4]
        else:
            pars = pars[:18]

        raw_players = golf_payload.get('players', []) if isinstance(golf_payload.get('players'), list) else []

        def _as_int(value, default=0):
            try:
                if value is None:
                    return default
                if isinstance(value, str):
                    txt = value.strip().upper()
                    if txt in ('', '--'):
                        return default
                    if txt in ('E', 'EVEN'):
                        return 0
                    return int(float(txt))
                return int(float(value))
            except Exception:
                return default

        players = []
        for p in raw_players:
            if not isinstance(p, dict):
                continue
            pos = str(p.get('pos', '-')).strip().upper() or '-'
            if pos in ('WD', 'DQ'):
                continue

            name = normalize_special_chars(str(p.get('name', 'UNKNOWN'))).upper()
            if len(name) > 11:
                name = name.split()[-1].upper()
            name = name[:11]

            total = _as_int(p.get('total'), 0)
            today = _as_int(p.get('today'), 0)
            thru = p.get('thru', 0)
            holes = p.get('holes', []) if isinstance(p.get('holes'), list) else []
            holes = (holes + [None] * 18)[:18]

            players.append({
                'pos': pos,
                'name': name,
                'total': total,
                'today': today,
                'thru': thru,
                'holes': holes,
            })

        if players and all(p['pos'] in ('-', '') for p in players):
            players.sort(key=lambda x: x['total'])
            totals_all = [p['total'] for p in players]
            rank = 1
            for idx, p in enumerate(players):
                if idx > 0 and totals_all[idx] == totals_all[idx - 1]:
                    p['pos'] = players[idx - 1]['pos']
                else:
                    rank = idx + 1
                    p['pos'] = ('T' + str(rank)) if totals_all.count(totals_all[idx]) > 1 else str(rank)

        players = players[:20]
        pairs = [(players[i], players[i + 1] if i + 1 < len(players) else None) for i in range(0, len(players), 2)]

        now_ts = time.time()
        p1 = p2 = None
        if pairs:
            p1, p2 = pairs[self.golf_current_pair % len(pairs)]
            is_cut_pair = (p1['pos'] == 'CUT') or (p2 is not None and p2['pos'] == 'CUT')
            current_interval = 2.0 if is_cut_pair else 4.0
            if now_ts - self.golf_last_switch > current_interval:
                self.golf_current_pair = (self.golf_current_pair + 1) % len(pairs)
                self.golf_last_switch = now_ts
                p1, p2 = pairs[self.golf_current_pair % len(pairs)]

        BRAND_W = 30
        POS_X = 34
        NAME_X = 47
        FRONT_X = 95
        FSUB_CX = 194
        BACK_X = 208
        BSUB_CX = 314
        TODAY_CX = 342
        TOTAL_CX = 368

        def draw_text(d_obj, text, x, y, color):
            curr_x = int(x)
            for char in str(text).upper():
                pattern = self.M_FONT.get(char)
                if pattern is None:
                    curr_x += 4
                    continue
                for r, row_val in enumerate(pattern):
                    for c in range(3):
                        if (row_val >> (2 - c)) & 1:
                            d_obj.point((curr_x + c, int(y) + r), fill=color)
                curr_x += 4
            return curr_x

        def draw_text_centered(d_obj, text, x_center, y, color):
            width = max(0, len(str(text)) * 4 - 1)
            start_x = int(x_center - width // 2)
            draw_text(d_obj, text, start_x, int(y), color)

        def format_score(val):
            if val is None:
                return '--'
            if val == 0:
                return 'E'
            if val > 0:
                return f"+{val}"
            return str(val)

        def draw_box(d_obj, x, y, score, par):
            try:
                score_val = int(score) if score is not None else None
            except Exception:
                score_val = None

            if score_val is None:
                d_obj.rectangle([x, y, x + 6, y + 6], outline=M_COLORS['par_border'])
                draw_text_centered(d_obj, '-', x + 3, y + 1, M_COLORS['label_gray'])
                return

            diff = score_val - int(par)
            if diff <= -2:
                d_obj.ellipse([x, y, x + 6, y + 6], fill=M_COLORS['eagle'])
                draw_text_centered(d_obj, str(score_val), x + 3, y + 1, M_COLORS['black'])
            elif diff == -1:
                d_obj.ellipse([x, y, x + 6, y + 6], fill=M_COLORS['birdie'])
                draw_text_centered(d_obj, str(score_val), x + 3, y + 1, M_COLORS['black'])
            elif diff == 0:
                d_obj.rectangle([x, y, x + 6, y + 6], outline=M_COLORS['par_border'])
                draw_text_centered(d_obj, str(score_val), x + 3, y + 1, M_COLORS['white'])
            elif diff == 1:
                d_obj.rectangle([x, y, x + 6, y + 6], fill=M_COLORS['bogey'])
                draw_text_centered(d_obj, str(score_val), x + 3, y + 1, M_COLORS['white'])
            else:
                d_obj.rectangle([x, y, x + 6, y + 6], fill=M_COLORS['double'])
                draw_text_centered(d_obj, str(score_val), x + 3, y + 1, M_COLORS['white'])

        def draw_player(d_obj, player, y_pos, par_vals):
            if str(player['pos']).replace('T', '') == '1':
                d_obj.rectangle([POS_X - 4, y_pos + 1, POS_X - 3, y_pos + 5], fill=M_COLORS['stripe_lead'])

            if player['pos'] == 'CUT':
                p_color = M_COLORS['bogey']
            elif str(player['pos']).replace('T', '') == '1':
                p_color = M_COLORS['gold']
            else:
                p_color = M_COLORS['white']

            draw_text(d_obj, player['pos'], POS_X, y_pos + 1, p_color)
            draw_text(d_obj, player['name'], NAME_X, y_pos + 1, M_COLORS['white'])

            try:
                thru_val = int(player.get('thru', 0) or 0)
            except (TypeError, ValueError):
                thru_val = 18 if str(player.get('thru', '')).upper() == 'F' else 0
            holes_with_scores = sum(1 for h in player['holes'] if h is not None)
            started_today = thru_val > 0 or (0 < holes_with_scores < 18)

            f_score = 0
            for i in range(9):
                bx = FRONT_X + i * 10
                score = player['holes'][i] if started_today else None
                draw_box(d_obj, bx, y_pos, score, par_vals[i])
                if score is not None:
                    f_score += (int(score) - int(par_vals[i]))
            draw_text_centered(d_obj, format_score(f_score), FSUB_CX, y_pos + 1, M_COLORS['white'])

            b_score = 0
            for i in range(9):
                bx = BACK_X + i * 11
                score = player['holes'][9 + i] if started_today else None
                draw_box(d_obj, bx, y_pos, score, par_vals[9 + i])
                if score is not None:
                    b_score += (int(score) - int(par_vals[9 + i]))
            draw_text_centered(d_obj, format_score(b_score), BSUB_CX, y_pos + 1, M_COLORS['white'])

            if started_today:
                draw_text_centered(d_obj, format_score(player['today']), TODAY_CX, y_pos + 1, M_COLORS['white'])
            else:
                draw_text_centered(d_obj, '-', TODAY_CX, y_pos + 1, M_COLORS['label_gray'])

            if player['total'] < 0:
                tot_color = M_COLORS['birdie']
            elif player['total'] > 0:
                tot_color = M_COLORS['bogey']
            else:
                tot_color = M_COLORS['white']
            draw_text_centered(d_obj, format_score(player['total']), TOTAL_CX, y_pos + 1, tot_color)

        # Brand panel: use tournament-specific lines (e.g. ['THE','MASTERS'] or ['PGA','CHAMP'])
        brand = brand_lines if len(brand_lines) >= 2 else [event_name[:7], '']
        d.line([(BRAND_W, 0), (BRAND_W, 31)], fill=M_COLORS['gold'])
        draw_text_centered(d, brand[0], BRAND_W // 2, 3, M_COLORS['gold'])
        draw_text_centered(d, brand[1], BRAND_W // 2, 11, M_COLORS['gold'])
        draw_text_centered(d, year, BRAND_W // 2, 20, M_COLORS['gold'])

        if pairs and p1:
            for i in range(1, 10):
                draw_text_centered(d, str(i), FRONT_X + (i - 1) * 10 + 3, 2, M_COLORS['label_gray'])
            draw_text_centered(d, 'FRONT', FSUB_CX, 2, M_COLORS['label_gray'])

            for i in range(10, 19):
                draw_text_centered(d, str(i), BACK_X + (i - 10) * 11 + 3, 2, M_COLORS['label_gray'])
            draw_text_centered(d, 'BACK', BSUB_CX, 2, M_COLORS['label_gray'])

            draw_text_centered(d, 'TODAY', TODAY_CX, 2, M_COLORS['label_gray'])
            draw_text_centered(d, 'TOTAL', TOTAL_CX, 2, M_COLORS['label_gray'])

            draw_player(d, p1, 9, pars)
            if p2:
                d.line([(POS_X, 19), (PANEL_W - 4, 19)], fill=M_COLORS['par_border'])
                draw_player(d, p2, 22, pars)

            num_dots = len(pairs)
            if num_dots > 0:
                active_idx = self.golf_current_pair % num_dots
                dot_size = 2
                if num_dots <= 1:
                    dot_step = 0
                else:
                    max_track_width = PANEL_W - 4
                    dot_step = max(2, min(4, (max_track_width - dot_size) // (num_dots - 1)))

                track_width = dot_size if num_dots == 1 else ((num_dots - 1) * dot_step) + dot_size
                dot_start_x = PANEL_W - track_width - 2
                dot_y = PANEL_H - 2

                for i in range(num_dots):
                    x = dot_start_x + (i * dot_step)
                    color = M_COLORS['dot_active'] if i == active_idx else M_COLORS['dot_idle']
                    d.rectangle([x, dot_y, x + 1, dot_y + 1], fill=color)
        else:
            draw_text_centered(d, event_name[:16], (PANEL_W + BRAND_W) // 2, 10, M_COLORS['white'])
            draw_text_centered(d, 'LOADING...', (PANEL_W + BRAND_W) // 2, 20, M_COLORS['gold'])

        return img
