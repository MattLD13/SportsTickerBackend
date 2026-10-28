"""Draw pinned full-panel sports layouts for Ticker Six."""

from PIL import Image, ImageDraw, ImageStat

from ticker_core.rendering.pixels import draw_tiny_text
from ticker_core.rendering.colors import is_near_black, is_near_white, parse_hex_color
from ticker_core.rendering.style import TOURNAMENT_SEED
from ticker_core.rendering.templates import ImageTemplates
from .logo_badge import draw_missing_team_badge
from .logo_visibility import LogoOutlineMode, paste_team_logo
from .logo_rendering import get_prepared_team_logo
from .stadium_port import draw_hockey_so_column

PANEL_W = 384
PANEL_H = 32

# Width of the darkened band at each edge of a full-bleed card. Anything drawn
# underneath it has to reach the edge without introducing brightness of its own,
# so backgrounds taper their detail over the same span.
SIDE_SCRIM_SOLID = 8
SIDE_SCRIM_FADE = 92
SIDE_SCRIM_SPAN = SIDE_SCRIM_SOLID + SIDE_SCRIM_FADE

# Soccer, hockey, and basketball use a wider linear fade behind their logos.
EDGE_FADE_SOLID = 45
EDGE_FADE_FADE = 80

# Football field geometry follows the HTML footballField() proportions.
END_ZONE_W = PANEL_W * (30 / 360)
PLAY_W = PANEL_W * (300 / 360)
HASH_TOP = PANEL_H * (70.75 / 160)
HASH_BOTTOM = PANEL_H * (89.25 / 160)

# Soccer, baseball, hockey, and basketball share one logo and score row.
MARK_SIZE = 24
MARK_Y = (PANEL_H - MARK_SIZE) // 2
AWAY_MARK_X = PANEL_W - 3 - MARK_SIZE - 5

WHITE = (255, 255, 255)
SCORE_OUTLINE = (0, 0, 0, 200)
STATUS_TEXT = (255, 240, 150)
EMPTY_NET_TEXT = (255, 90, 90)
POWER_PLAY_TEXT = (255, 204, 0)

_NAME_SUFFIXES = {'JR', 'SR', 'II', 'III', 'IV', 'V', 'VI'}
_MISSING_ERA = {'-', '-.--', 'N/A', 'n/a'}


def _display_sides(game):
    """Swap home and away fields: the full layout draws the away team on the left."""
    result = {}
    for key, value in game.items():
        if key.startswith('home_'):
            result['away_' + key[5:]] = value
        elif key.startswith('away_'):
            result['home_' + key[5:]] = value
        else:
            result[key] = value
    return result


def _draw_edge_fade(image):
    """Composite a linear black fade over both panel edges."""
    width, height = image.size
    scrim = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(scrim)
    span = EDGE_FADE_SOLID + EDGE_FADE_FADE
    for x in range(span):
        alpha = 250 if x < EDGE_FADE_SOLID else max(0, int(250 * (span - x) / EDGE_FADE_FADE))
        draw.line([(x, 0), (x, height)], fill=(0, 0, 0, alpha))
        draw.line([(width - 1 - x, 0), (width - 1 - x, height)], fill=(0, 0, 0, alpha))
    image.alpha_composite(scrim)


def _football_field(home_end_zone, away_end_zone):
    """Draw the static striped field with both team end zones."""
    W, H = PANEL_W, PANEL_H
    field = Image.new("RGBA", (W, H), (0, 0, 0, 255))
    draw = ImageDraw.Draw(field, "RGBA")
    for i in range(10):
        bx = END_ZONE_W + i * PLAY_W / 10
        draw.rectangle([bx, 0, bx + PLAY_W / 10, H],
                       fill=(22, 52, 18) if i % 2 == 0 else (27, 64, 24))
    draw.rectangle([0, 0, END_ZONE_W, H], fill=home_end_zone)
    draw.rectangle([W - END_ZONE_W, 0, W, H], fill=away_end_zone)
    draw.line([(END_ZONE_W, 0), (END_ZONE_W, H)], fill=(255, 255, 255, 230))
    draw.line([(W - END_ZONE_W, 0), (W - END_ZONE_W, H)], fill=(255, 255, 255, 230))
    for i in range(11):
        lx = END_ZONE_W + i * PLAY_W / 10
        opacity = 115 if i == 5 else 64
        draw.line([(lx, 0), (lx, H)], fill=(255, 255, 255, opacity))
    for y in range(1, 100):
        hx = END_ZONE_W + y / 100 * PLAY_W
        is_five = y % 5 == 0
        length = H * 0.042 if is_five else H * 0.022
        opacity = 128 if is_five else 66
        draw.line([(hx, HASH_TOP - length), (hx, HASH_TOP + length)], fill=(255, 255, 255, opacity))
        draw.line([(hx, HASH_BOTTOM - length), (hx, HASH_BOTTOM + length)], fill=(255, 255, 255, opacity))
    return field


def _soccer_field():
    """Draw the static striped pitch with its edge fade."""
    W, H = PANEL_W, PANEL_H
    image = Image.new("RGBA", (W, H), (0, 0, 0, 255))
    draw = ImageDraw.Draw(image, 'RGBA')
    draw.rectangle([0, 0, W, H], fill=(18, 96, 36))
    for i in range(8):
        x0, x1 = int(i * W / 8), int((i + 1) * W / 8)
        draw.rectangle([x0, 0, x1, H], fill=(22, 104, 40) if i % 2 == 0 else (18, 96, 36))
    draw.rectangle([1, 1, W - 2, H - 2], outline=(245, 245, 245, 210), width=1)
    draw.line([(W // 2, 0), (W // 2, H)], fill=(245, 245, 245, 180), width=1)
    draw.ellipse([W // 2 - 13, H // 2 - 13, W // 2 + 13, H // 2 + 13], outline=(245, 245, 245, 180), width=1)
    draw.rectangle([1, 8, 10, H - 8], fill=(245, 245, 245, 28))
    draw.rectangle([W - 11, 8, W - 2, H - 8], fill=(245, 245, 245, 28))
    _draw_edge_fade(image)
    return image


def _line_of_scrimmage(situation, spot_text, left_team, right_team):
    """Return the ball spot on the card axis: 0 is the left goal line, -1 is unknown.

    ESPN measures situation.yardLine from the host goal line, which sits at the
    right edge after the side swap, so the value is mirrored once.
    """
    yard_line = situation.get('yardLine')
    if yard_line is not None:
        return max(0, min(100, 100 - int(yard_line)))
    if ' at ' not in spot_text:
        return -1
    # Payloads without the numeric field still read "... at CAR 33".
    after = spot_text.split(' at ', 1)[1].strip().split()
    if len(after) == 1 and after[0] == '50':
        return 50
    if len(after) >= 2:
        team = after[0].upper()
        try:
            yard = int(after[1])
        except ValueError:
            return -1
        return yard if team == left_team else (100 - yard if team == right_team else 50)
    return -1


def _yards_to_go(situation, down_text):
    """Return the yards to the first-down marker."""
    if situation.get('yardsToGo') is not None:
        return max(1, int(situation['yardsToGo']))
    if '&' in down_text:
        raw = down_text.split('&', 1)[1].strip().split()[0].lower().rstrip('.,')
        try:
            return max(1, int(raw))
        except ValueError:
            return 10
    return 10


def _int_or_none(value):
    """Return an integer count, or None for a value that is not a number."""
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return None


def _ordinal(number):
    """Return an English ordinal such as 9th or 21st."""
    number = int(number)
    if 10 <= number % 100 <= 19:
        return f"{number}th"
    return f"{number}" + {1: 'st', 2: 'nd', 3: 'rd'}.get(number % 10, 'th')


def _short_last_name(raw, max_chars=24):
    """Return an upper-case family name and keep a generational suffix."""
    text = str(raw or '').strip()
    if not text:
        return ''
    parts = [part for part in text.replace('.', ' ').split() if part]
    if len(parts) >= 2 and parts[-1].upper() in _NAME_SUFFIXES:
        last = f"{parts[-2]} {parts[-1]}"
    else:
        last = parts[-1] if parts else text
    return last.upper()[:max_chars]


def _value_text(raw):
    """Return a stripped text value, or an empty string for None."""
    return '' if raw is None else str(raw).strip()


def _compact_pitch_name(full_type, abbreviation):
    """Return a short pitch name that fits the side lane."""
    text = str(full_type or '').strip()
    if text:
        text = text.split('(', 1)[0].strip()
        text = text.split('/', 1)[0].strip()
    if not text:
        return str(abbreviation or '').strip().upper()[:10]
    if len(text) > 12:
        words = text.replace('-', ' ').split()
        if words:
            text = words[-1]
    return text.title()[:12]


def _batter_lines(situation):
    """Return the batter name, hits per at-bat, and average lines."""
    average = _value_text(situation.get('batter_avg', ''))
    if average.startswith('0.'):
        average = average[1:]
    hits = _value_text(situation.get('batter_h', ''))
    at_bats = _value_text(situation.get('batter_ab', ''))
    if hits or at_bats:
        hits_line = f"{hits or '-'}/{at_bats or '-'}"
    else:
        hits_line = ''
    return [situation.get('batter_name', ''), hits_line, average]


def _pitcher_lines(situation):
    """Return the pitcher name, pitch count, and last pitch or ERA lines."""
    count = _value_text(situation.get('pitcher_pitches', ''))
    speed = str(situation.get('last_pitch_speed', 0)).strip()
    abbreviation = situation.get('last_pitch_type_abbr', '') or situation.get('last_pitch_type', '')
    pitch_type = _compact_pitch_name(situation.get('last_pitch_type_full', ''), abbreviation)
    if speed and speed != '0':
        pitch_line = f"{situation.get('last_pitch_speed', 0)} {pitch_type}" if pitch_type else f"{situation.get('last_pitch_speed', 0)} MPH"
    else:
        pitch_line = pitch_type
    era = _value_text(situation.get('pitcher_era'))
    if era in _MISSING_ERA:
        era = ''
    if not pitch_line and era:
        pitch_line = f"ERA:{era}"
    return [situation.get('pitcher_name', ''), f"P:{count}" if count else '', pitch_line]


class PreparedSportsFullRenderer:
    """Render 384 by 32 pinned sports layouts from prepared logos."""

    def __init__(self, fonts, logos):
        self.big_font = fonts.big
        self.clock_giant = fonts.clock
        self.tiny = fonts.tiny
        self.tiny_small = fonts.tiny_small
        self.micro = fonts.micro
        self.font = fonts.normal
        self._logos = logos
        self._field_templates = ImageTemplates(capacity=16, max_bytes=1024 * 1024)

    def draw_sport_full_bleed(self, game, page_tick=0):
        """Render one pinned game with the layout for its sport."""
        game = _display_sides(game)
        sport = str(game.get('sport', '')).lower()
        if 'football' in sport or 'nfl' in sport or 'ncf' in sport:
            return self._draw_football(game, sport)
        if 'soccer' in sport:
            return self._draw_soccer(game)
        if 'baseball' in sport or 'mlb' in sport:
            return self._draw_baseball(game)
        return self._draw_rink_or_court(game, sport, page_tick)

    # ── Shared layout ────────────────────────────────────────────────────────

    def _draw_marks_and_scores(self, img, d, game, home_mark_x, home_color, away_color):
        """Paste both team marks and draw both scores. Return the score anchors."""
        home_logo = self.get_logo(game.get('home_logo'), (MARK_SIZE, MARK_SIZE), game.get('home_logo_rendering'))
        away_logo = self.get_logo(game.get('away_logo'), (MARK_SIZE, MARK_SIZE), game.get('away_logo_rendering'))
        self._paste_team_mark(img, home_logo, (home_mark_x, MARK_Y), str(game.get('home_abbr', '')).upper(), MARK_SIZE, home_color)
        self._paste_team_mark(img, away_logo, (AWAY_MARK_X, MARK_Y), str(game.get('away_abbr', '')).upper(), MARK_SIZE, away_color)
        home_score_x = home_mark_x + MARK_SIZE + 4
        away_score_x = AWAY_MARK_X - 4
        self.draw_outlined_text(d, home_score_x, PANEL_H // 2, str(game.get('home_score', '')),
                                self.clock_giant, WHITE, SCORE_OUTLINE, anchor='lm')
        self.draw_outlined_text(d, away_score_x, PANEL_H // 2, str(game.get('away_score', '')),
                                self.clock_giant, WHITE, SCORE_OUTLINE, anchor='rm')
        return home_score_x, away_score_x

    # ── Football ─────────────────────────────────────────────────────────────

    def _end_zone_color(self, game, side, fallback):
        """Use a colorful alternate when the primary team color is effectively gray.

        ESPN supplies primary and alternate colors for FBS and FCS teams. The logo
        renderer then picks a contrasting keyline against this fill.
        """
        primary = self._parse_hex_color(game.get(f"{side}_color")) or fallback
        alternate = self._parse_hex_color(game.get(f"{side}_alt_color"))
        if max(primary) - min(primary) < 25 and alternate and max(alternate) - min(alternate) >= 25:
            return alternate
        return primary

    def _draw_football(self, game, sport):
        W, H = PANEL_W, PANEL_H
        sit = game.get('situation', {}) or {}
        home_ab = str(game.get('home_abbr', '')).upper()
        away_ab = str(game.get('away_abbr', '')).upper()
        poss_ab = str(sit.get('possession', '')).upper()
        home_ez = self._end_zone_color(game, 'home', self.get_team_color(game, 'home'))
        away_ez = self._end_zone_color(game, 'away', self.get_team_color(game, 'away'))
        img = self._field_templates.render(('football', W, H, home_ez, away_ez), lambda: _football_field(home_ez, away_ez))
        d = ImageDraw.Draw(img, 'RGBA')

        # Mark possession above the team badge in its end zone.
        active_team = str(sit.get('activeTeam', '')).strip().upper()
        possession_x = None
        if active_team and active_team == home_ab:
            possession_x = int(END_ZONE_W / 2)
        elif active_team and active_team == away_ab:
            possession_x = W - int(END_ZONE_W / 2)
        if possession_x is not None:
            d.polygon([(possession_x - 5, 1), (possession_x + 5, 1), (possession_x, 5)],
                      fill=(255, 235, 80), outline=(0, 0, 0, 255))

        dd_text = sit.get('downDist', '') or sit.get('downDistFull', '')
        spot_text = sit.get('downDistFull', '') or sit.get('ballOn', '') or dd_text
        los = _line_of_scrimmage(sit, spot_text, home_ab, away_ab)
        ytg = _yards_to_go(sit, dd_text)
        # The left team after the side swap drives to the right.
        drive_to_right = poss_ab != away_ab
        if (bool(sit.get('isGoalToGo')) or 'goal' in dd_text.lower()) and los >= 0:
            # First down is the goal line itself, however short the distance reads.
            ytg = max(1, (100 - los) if drive_to_right else los)

        is_rz = sit.get('isRedZone', False)
        if is_rz:
            overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
            overlay_draw = ImageDraw.Draw(overlay, "RGBA")
            zone_x = END_ZONE_W + (0.8 if drive_to_right else 0.2) * PLAY_W
            if drive_to_right:
                overlay_draw.rectangle([END_ZONE_W + int(0.8 * PLAY_W), 0, W - END_ZONE_W, H], fill=(220, 0, 0, 128))
            else:
                overlay_draw.rectangle([END_ZONE_W, 0, END_ZONE_W + int(0.2 * PLAY_W), H], fill=(220, 0, 0, 128))
            d.line([(zone_x, 0), (zone_x, H)], fill=(255, 34, 34, 200), width=2)
            img.alpha_composite(overlay)

        # The field has room for the spot ("1st & 10 at ARI 42"). The compact
        # ticker row shows only "1st & 10".
        period = self.shorten_status(game.get('status', ''), sport)
        context = sit.get('downDistFull', '') or dd_text
        if period or context:
            self.draw_outlined_text(d, W // 2, int(H * 0.32) if context else int(H * 0.5), period,
                                    self.big_font, WHITE, SCORE_OUTLINE)
            if context:
                self.draw_outlined_text(d, W // 2, int(H * 0.72), context, self.font,
                                        (255, 136, 0) if is_rz else (240, 216, 0), SCORE_OUTLINE)

        # Score positions come first so a logo can move above a score in its end zone.
        logo_size = min(int(END_ZONE_W * 0.85), int(H * 0.65))
        home_logo_cx = int(END_ZONE_W / 2)
        away_logo_cx = W - int(END_ZONE_W / 2)
        bbox = d.textbbox((0, 0), '00', font=self.big_font)
        score_h = max(11, bbox[3] - bbox[1])
        # Keep the taller glyphs off the bottom edge of the panel.
        score_y = min(int(H * 0.82), H - (score_h // 2) - 1)
        home_score_cx = int(END_ZONE_W + PLAY_W * 0.05)
        away_score_cx = int(W - END_ZONE_W - PLAY_W * 0.05)
        if is_rz:
            if poss_ab == home_ab:
                away_score_cx = away_logo_cx
            elif poss_ab == away_ab:
                home_score_cx = home_logo_cx
        centered_top = (H - logo_size) // 2
        raised_top = max(0, score_y - (score_h // 2) - logo_size - 1)
        home_logo = self.get_logo(game.get('home_logo'), (24, 24), game.get('home_logo_rendering'))
        away_logo = self.get_logo(game.get('away_logo'), (24, 24), game.get('away_logo_rendering'))
        self._paste_team_mark(img, home_logo, (home_logo_cx - logo_size // 2, raised_top if home_score_cx == home_logo_cx else centered_top),
                              home_ab, logo_size, home_ez)
        self._paste_team_mark(img, away_logo, (away_logo_cx - logo_size // 2, raised_top if away_score_cx == away_logo_cx else centered_top),
                              away_ab, logo_size, away_ez)
        for score_cx, score in ((home_score_cx, str(game.get('home_score', ''))), (away_score_cx, str(game.get('away_score', '')))):
            if score:
                self.draw_outlined_text(d, score_cx, score_y, score, self.big_font, WHITE, (0, 0, 0, 235))

        # First-down line, line of scrimmage, and ball.
        if 0 <= los <= 100:
            los_px = END_ZONE_W + los * PLAY_W / 100
            first_down = min(100, los + ytg) if drive_to_right else max(0, los - ytg)
            first_down_px = END_ZONE_W + first_down * PLAY_W / 100
            d.line([(first_down_px, 0), (first_down_px, H)], fill=(240, 216, 0, 245), width=2)
            d.line([(los_px, 0), (los_px, H)], fill=(30, 60, 180, 240), width=2)
            brx = max(4, int(H * 0.13))
            bry = max(2, int(H * 0.08))
            by = H // 2
            d.ellipse([los_px - brx, by - bry, los_px + brx, by + bry], fill=(139, 69, 19), outline=(61, 26, 6))
            d.line([(los_px - int(brx * 0.7), by), (los_px + int(brx * 0.7), by)], fill=(255, 255, 255, 165))
        return img

    # ── Soccer ───────────────────────────────────────────────────────────────

    def _draw_soccer(self, game):
        W, H = PANEL_W, PANEL_H
        sit = game.get('situation', {}) or {}
        home_clr = self.get_team_color(game, 'home')
        away_clr = self.get_team_color(game, 'away')
        img = self._field_templates.render(('soccer', W, H), _soccer_field)
        d = ImageDraw.Draw(img, 'RGBA')
        d.rectangle([0, 0, 3, H], fill=home_clr)
        d.rectangle([W - 4, 0, W, H], fill=away_clr)
        home_score_x, away_score_x = self._draw_marks_and_scores(img, d, game, 6, home_clr, away_clr)

        status_text = str(game.get('status', '')).strip()
        if status_text:
            self.draw_outlined_text(d, W // 2, H // 2, status_text[:12], self.big_font,
                                    STATUS_TEXT, (0, 0, 0, 220), anchor='mm')

        # Goals and red cards sit in the lane between each score and the centre time.
        # After the side swap, is_home=False is the left lane.
        goals = sit.get('goal_events') or []
        cards = sit.get('red_cards') or []
        lanes = {
            home: [(event, False) for event in goals if bool(event.get('is_home')) == home]
            + [(event, True) for event in cards if bool(event.get('is_home')) == home]
            for home in (False, True)
        }
        home_score_w = d.textlength(str(game.get('home_score', '')) or '0', font=self.clock_giant)
        away_score_w = d.textlength(str(game.get('away_score', '')) or '0', font=self.clock_giant)
        time_w = d.textlength(status_text[:12], font=self.big_font) if status_text else 0
        self._draw_event_lane(d, lanes[False], int(home_score_x + home_score_w), int(W // 2 - time_w / 2) - 4)
        self._draw_event_lane(d, lanes[True], int(W // 2 + time_w / 2) + 4, int(away_score_x - away_score_w))

        if sit.get('shootout'):
            shootout = sit.get('shootout', {})
            self._draw_soccer_so_col(d, AWAY_MARK_X + MARK_SIZE + 2, 8, shootout.get('home', []))
            self._draw_soccer_so_col(d, 6 - 5, 8, shootout.get('away', []))
        return img

    def _draw_event_lane(self, d, lane, gap_left, gap_right):
        """Center goal and card labels in one lane, in two columns when it is full."""
        if not lane:
            return
        gap_w = gap_right - gap_left
        if len(lane) <= 3:
            columns = [(lane, gap_left + gap_w // 2)]
            line_h, name_len = 9, 8
        else:
            # Earlier events go in the left column.
            half = (len(lane) + 1) // 2
            columns = [(lane[:half], gap_left + gap_w * 30 // 100), (lane[half:], gap_left + gap_w * 68 // 100)]
            line_h, name_len = 8, 6
        card_w, card_gap = 3, 4
        bright, dim = (235, 235, 235), (150, 150, 150)
        for column, cx in columns:
            y0 = PANEL_H // 2 - (len(column) - 1) * line_h // 2
            for i, (event, is_card) in enumerate(column):
                y = y0 + i * line_h
                own_goal = not is_card and event.get('own_goal')
                label = f"{str(event.get('player') or '')[:name_len]} {str(event.get('time') or '')}{'(og)' if own_goal else ''}".strip()
                if not label:
                    continue
                if is_card:
                    total_w = card_w + card_gap + d.textlength(label, font=self.micro)
                    rx = int(cx - total_w / 2)
                    d.rectangle([rx, y - 4, rx + card_w, y + 2], fill=(220, 30, 30))
                    self.draw_outlined_text(d, rx + card_w + card_gap, y, label, self.micro, bright, SCORE_OUTLINE, anchor='lm')
                else:
                    self.draw_outlined_text(d, cx, y, label, self.micro, dim if own_goal else bright, SCORE_OUTLINE, anchor='mm')

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

    # ── Baseball ─────────────────────────────────────────────────────────────

    def _draw_baseball(self, game):
        W, H = PANEL_W, PANEL_H
        sit = game.get('situation', {}) or {}
        home_clr = self.get_team_color(game, 'home')
        away_clr = self.get_team_color(game, 'away')
        bases = tuple(bool(sit.get(name, False)) for name in ('onFirst', 'onSecond', 'onThird'))

        def baseball_field():
            image = Image.new("RGBA", (W, H), (0, 0, 0, 255))
            self._draw_baseball_diamond(ImageDraw.Draw(image, 'RGBA'), W, H, sit)
            return image
        img = self._field_templates.render(('baseball', W, H, bases), baseball_field)
        d = ImageDraw.Draw(img, 'RGBA')
        self._draw_side_scrims(img, W, H)

        # Situation fields keep source-team ownership. The side swap means the
        # source away team owns the left challenge strip.
        self._draw_challenge_bar(d, 0, 3, sit.get('away_challenges'), sit.get('away_challenges_used'),
                                 self._resolve_challenge_strip_color(game, 'home', home_clr))
        self._draw_challenge_bar(d, W - 4, W - 1, sit.get('home_challenges'), sit.get('home_challenges_used'),
                                 self._resolve_challenge_strip_color(game, 'away', away_clr))
        home_score_x, away_score_x = self._draw_marks_and_scores(img, d, game, 6, home_clr, away_clr)

        inning = game.get('baseball_inning') or {}
        if inning.get('phase') in {'paused', 'inactive'}:
            label = str(game.get('status') or '')
            x0, y0, x1, y1 = d.textbbox((W // 2, H // 2), label, font=self.tiny_small, anchor='mm')
            d.rectangle((x0 - 3, y0 - 2, x1 + 3, y1 + 2), fill=(0, 0, 0, 235))
            self.draw_outlined_text(d, W // 2, H // 2, label, self.tiny_small, STATUS_TEXT, (0, 0, 0, 220))
            return img

        # The inning and count sit close to the diamond so the side lanes can hold
        # batter and pitcher details. The batting team's side holds the inning.
        is_top = inning.get('half') == 'top'
        is_bottom = inning.get('half') == 'bottom'
        left_x, right_x = W // 2 - 40, W // 2 + 40
        inning_cx, count_cx = (right_x, left_x) if is_bottom else (left_x, right_x)
        ordinal = _ordinal(str(inning['number'])) if inning.get('number') else ''
        self._draw_inning_indicator(d, inning_cx, H // 2, is_top, is_bottom, ordinal)
        if inning.get('phase') == 'break':
            return img
        count_rows = (('B', str(sit.get('balls', 0)), (74, 175, 255)),
                      ('S', str(sit.get('strikes', 0)), (255, 136, 0)),
                      ('O', str(sit.get('outs', 0)), (224, 48, 48)))
        for row, (label, value, color) in enumerate(count_rows):
            draw_tiny_text(d, count_cx - 8, 4 + row * 8, label, (180, 180, 180))
            draw_tiny_text(d, count_cx, 4 + row * 8, value, color)

        if is_top:
            home_score_w = d.textlength(str(game.get('home_score', '')), font=self.clock_giant)
            self.draw_bat(d, int(home_score_x + home_score_w + 8), 7)
        elif is_bottom:
            away_score_w = d.textlength(str(game.get('away_score', '')), font=self.clock_giant)
            self.draw_bat(d, int(away_score_x - away_score_w - 8), 7)

        # Use the explicit batting ownership from the backend.
        home_ab = str(game.get('home_abbr', '')).upper()
        away_ab = str(game.get('away_abbr', '')).upper()
        active_ab = str(sit.get('activeTeam', '')).upper()
        home_batting = bool(home_ab and active_ab and active_ab == home_ab)
        away_batting = bool(away_ab and active_ab and active_ab == away_ab)
        batter, pitcher = _batter_lines(sit), _pitcher_lines(sit)
        left_lines, right_lines = (batter, pitcher) if home_batting and not away_batting else (pitcher, batter)
        self._draw_info_block(d, W // 2 - 92, left_lines)
        self._draw_info_block(d, W // 2 + 92, right_lines)
        return img

    def _draw_challenge_bar(self, d, x0, x1, remaining, used, color):
        """Draw a full-height team strip and carve one open slot for each lost challenge."""
        d.rectangle([x0, 0, x1, PANEL_H - 1], fill=color)
        used_count = _int_or_none(used)
        remaining_count = _int_or_none(remaining)
        if used_count is None and remaining_count is not None:
            used_count = max(0, 2 - max(0, remaining_count))
        if used_count is None:
            return
        lost = min(2, max(0, used_count))
        box_w, box_h = 2, 14
        box_x0 = x0 + ((x1 - x0 + 1) - box_w) // 2
        box_x1 = box_x0 + box_w - 1
        # Lost slots are fixed at the top and the bottom, never centered.
        if lost >= 1:
            d.rectangle([box_x0, 1, box_x1, box_h], fill=(0, 0, 0, 0))
        if lost >= 2:
            d.rectangle([box_x0, PANEL_H - 2 - box_h + 1, box_x1, PANEL_H - 2], fill=(0, 0, 0, 0))

    def _draw_inning_indicator(self, d, cx, cy, is_top, is_bottom, ordinal):
        """Draw the half-inning arrow, the bold inning number, and its suffix inline."""
        if not ordinal:
            return
        number = ''.join(c for c in ordinal if c.isdigit())
        suffix = ''.join(c for c in ordinal if not c.isdigit())
        number_w = d.textlength(number, font=self.big_font)
        suffix_w = d.textlength(suffix, font=self.micro)
        arrow_w, gap, half_h = 8, 2, 4
        x = int(cx - (arrow_w + gap + number_w + suffix_w) / 2)
        mid_x = x + arrow_w // 2
        if is_top:
            d.polygon([(x - 1, cy + half_h + 1), (x + arrow_w + 1, cy + half_h + 1), (mid_x, cy - half_h - 1)], fill=(0, 0, 0))
            d.polygon([(x, cy + half_h), (x + arrow_w, cy + half_h), (mid_x, cy - half_h)], fill=WHITE)
        elif is_bottom:
            d.polygon([(x - 1, cy - half_h - 1), (x + arrow_w + 1, cy - half_h - 1), (mid_x, cy + half_h + 1)], fill=(0, 0, 0))
            d.polygon([(x, cy - half_h), (x + arrow_w, cy - half_h), (mid_x, cy + half_h)], fill=WHITE)
        else:
            d.rectangle([x, cy - 1, x + arrow_w, cy + 1], fill=(180, 180, 180))
        x += arrow_w + gap
        self.draw_outlined_text(d, x + int(number_w / 2), cy, number, self.big_font, WHITE, SCORE_OUTLINE)
        x += int(number_w)
        d.text((x, cy), suffix, font=self.micro, fill=(190, 190, 190), anchor='lm')

    def _fit_player_name(self, d, raw, max_width=64):
        """Use the small font for long names, then trim only as a last resort."""
        text = _short_last_name(raw)
        if not text:
            return '', self.tiny_small
        font = self.tiny_small
        if d.textlength(text, font=font) > max_width:
            font = self.micro
        while len(text) > 1 and d.textlength(text, font=font) > max_width:
            text = text[:-1].rstrip()
        return text, font

    def _draw_info_block(self, d, cx, lines):
        """Draw one batter or pitcher block. The first line holds the player name."""
        for index, line in enumerate(lines):
            if index == 0:
                text, font = self._fit_player_name(d, line)
            else:
                text, font = ('' if line is None else str(line).strip()[:15]), self.tiny_small
            if text:
                self.draw_outlined_text(d, int(cx), 7 + index * 9, text, font, WHITE, (0, 0, 0, 220), anchor='mm')

    # ── Hockey and basketball ────────────────────────────────────────────────

    def _draw_rink_or_court(self, game, sport, page_tick):
        W, H = PANEL_W, PANEL_H
        sit = game.get('situation', {}) or {}
        is_nhl = 'hockey' in sport or 'nhl' in sport
        home_clr = self.get_team_color(game, 'home')
        away_clr = self.get_team_color(game, 'away')
        img = Image.new("RGBA", (W, H), (0, 0, 0, 255))
        d = ImageDraw.Draw(img, "RGBA")
        if is_nhl:
            self._draw_hockey_rink(d, W, H)
        else:
            self._draw_basketball_court(d, W, H)
        _draw_edge_fade(img)

        period = self.shorten_status(game.get('status', ''), sport)
        if period:
            self.draw_outlined_text(d, W // 2, H // 2, period, self.big_font, WHITE, SCORE_OUTLINE)
        d.rectangle([0, 0, 2, H], fill=home_clr)
        d.rectangle([W - 3, 0, W, H], fill=away_clr)
        home_score_x, away_score_x = self._draw_marks_and_scores(img, d, game, 8, home_clr, away_clr)
        home_score_w = d.textlength(str(game.get('home_score', '')), font=self.clock_giant)
        away_score_w = d.textlength(str(game.get('away_score', '')), font=self.clock_giant)

        home_badge, away_badge = self._side_badges(game, sport, sit, is_nhl)
        if home_badge:
            self.draw_outlined_text(d, int(home_score_x + home_score_w + 9), 1, home_badge, self.tiny,
                                    self._badge_color(sport, home_badge), (0, 0, 0, 220), anchor='mt')
        if away_badge:
            self.draw_outlined_text(d, int(away_score_x - away_score_w - 9), 1, away_badge, self.tiny,
                                    self._badge_color(sport, away_badge), (0, 0, 0, 220), anchor='mt')

        if is_nhl:
            shootout = sit.get('shootout')
            if shootout:
                draw_hockey_so_column(d, int(home_score_x + home_score_w + 7), 6, shootout, 'away')
                draw_hockey_so_column(d, int(away_score_x - away_score_w - 12), 6, shootout, 'home')
                round_label = str(shootout.get('roundLabel') or '')
                draw_tiny_text(d, W // 2 - len(round_label) * 5 // 2, 1, round_label, (20, 25, 35))
            else:
                self._draw_hockey_context(d, sit, page_tick)
        return img

    @staticmethod
    def _side_badges(game, sport, sit, is_nhl):
        """Return tournament seeds, or the hockey empty-net or power-play labels."""
        home_badge = away_badge = ''
        home_ab = str(game.get('home_abbr', '')).upper()
        away_ab = str(game.get('away_abbr', '')).upper()
        if sport == 'march_madness':
            home_badge = str(game.get('home_seed') or '')
            away_badge = str(game.get('away_seed') or '')
        if is_nhl and sit.get('emptyNet'):
            side, label = str(sit.get('emptyNetSide') or '').upper(), 'EN'
        elif is_nhl and sit.get('powerPlay'):
            side = str(sit.get('powerPlayTeam') or '').upper()
            label = None
        else:
            return home_badge, away_badge
        if side == home_ab:
            home_badge = label if label is not None else str(sit.get('manpower', {}).get('powerPlayLabel') or '')
        elif side == away_ab:
            away_badge = label if label is not None else str(sit.get('manpower', {}).get('powerPlayLabel') or '')
        return home_badge, away_badge

    @staticmethod
    def _badge_color(sport, badge):
        if sport == 'march_madness':
            return TOURNAMENT_SEED
        return EMPTY_NET_TEXT if badge == 'EN' else POWER_PLAY_TEXT

    # ── Backgrounds and overlays ─────────────────────────────────────────────

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

    def _draw_hockey_context(self, draw, situation, page_tick):
        """Draw every backend goal label across aligned team pages."""
        goals = situation.get('hockeyGoals', ())
        sides = {side: [goal for goal in goals if goal.get('side') == side] for side in ('away', 'home')}
        pages = hockey_page_count(situation)
        page = page_tick % pages
        for side, cx in (('away', 108), ('home', 276)):
            if pages > 1:
                self.draw_outlined_text(draw, cx, 2, f'{page + 1}/{pages}', self.micro,
                                        (200, 210, 225), (0, 0, 0, 220))
            for row, goal in enumerate(sides[side][page * 3:page * 3 + 3]):
                self.draw_outlined_text(draw, cx, 8 + row * 8, str(goal.get('label') or ''), self.micro,
                                        (255, 255, 255), (0, 0, 0, 220))

    # ── Assets, text, and colors ─────────────────────────────────────────────

    def get_logo(self, url, size, rendering=None):
        """Return a prepared logo and never fetch from the renderer."""
        return get_prepared_team_logo(self._logos, str(url) if url else None, size, rendering)

    def _paste_team_mark(self, image, logo, xy, abbreviation, size, team_color):
        """Paste one prepared logo or a readable code when its asset is absent."""
        if logo is not None:
            mark = logo if logo.size == (size, size) else logo.resize((size, size), Image.LANCZOS)
            paste_team_logo(image, mark, xy, outline_mode=LogoOutlineMode.FULL)
            return
        draw_missing_team_badge(image, xy, size, team_color, abbreviation)

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
        logo = self.get_logo(game.get(f"{side}_logo"), (24, 24), game.get(f"{side}_logo_rendering"))
        if logo:
            return tuple(int(value) for value in ImageStat.Stat(logo).mean[:3])
        return (60, 60, 60)

    _parse_hex_color = staticmethod(parse_hex_color)
    _is_near_black = staticmethod(is_near_black)
    _is_near_white = staticmethod(is_near_white)

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
            text = text.replace(f"{period} ", f"{period}-")
        return text

    @staticmethod
    def draw_bat(draw, cx, by):
        """Draw the compact baseball bat marker."""
        draw.rectangle([cx - 2, by, cx + 1, by + 7], fill=(220, 180, 120))
        draw.rectangle([cx - 1, by + 8, cx, by + 9], fill=(220, 180, 120))
        draw.rectangle([cx - 1, by + 10, cx, by + 15], fill=(180, 135, 65))
        draw.rectangle([cx - 2, by + 16, cx + 1, by + 17], fill=(150, 105, 40))


def hockey_page_count(situation):
    """Return the number of full-screen hockey layout pages."""
    if situation.get('shootout'):
        return 1
    goals = situation.get('hockeyGoals', ())
    count = max(sum(goal.get('side') == side for goal in goals) for side in ('away', 'home'))
    return max(1, (count + 2) // 3)
