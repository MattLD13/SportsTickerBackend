"""Full-screen takeover shown when a followed team scores.

The strip is built to be glanceable at a distance and to answer three questions
in the order a fan asks them: *who* (logo and colours), *what* (the headline —
"GRAND SLAM", "POWER PLAY GOAL"), and *where does that leave us* (the score).

Everything is drawn from the team's own colours, scaled down hard. The panels
are current-limited, so a 384x32 field at full saturation browns out the whites
elsewhere in the frame; the background sits at a third of the team colour and
only the headline and the accent rails are allowed to be bright.
"""

import math
import random
import re

from PIL import Image, ImageDraw, ImageFont

from ticker_core.rendering.pixels import draw_hybrid_text, draw_tiny_text

PANEL_W = 384
PANEL_H = 32


def load_monospace_font(size, bold=False):
    """Load the deployed monospace alert face."""
    import os

    names = ["DejaVuSansMono-Bold.ttf", "UbuntuMono-Bold.ttf", "consolab.ttf", "courbd.ttf", "DejaVuSansMono.ttf"] if bold else ["DejaVuSansMono.ttf", "UbuntuMono-Regular.ttf", "consola.ttf", "cour.ttf"]
    for name in names:
        for path in (name, os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "Fonts", name)):
            try:
                font = ImageFont.truetype(path, size)
                if "Aileron" not in font.getname()[0]:
                    return font
            except OSError:
                continue
    return ImageFont.load_default()

# Phase lengths in seconds. The wipes are short enough to read as a slam rather
# than a transition; the hold is what the viewer actually looks at.
WIPE_IN = 0.40
WIPE_OUT = 0.35
HOLD_NORMAL = 3.4
HOLD_BIG = 5.4

# Split-flap headline. Letters land left to right as the shutters finish
# opening, which buys a second of motion in the part of the frame the eye is
# already on. Monospace is not a style choice here: a proportional face changes
# width as the scrambled letters cycle, and the headline visibly wobbles.
FLAP_STEP = 0.055
_FLAP_CHARS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
_FLAP_SIZES = (20, 16, 13)

# Right-hand score panel. Wide enough for a 3-letter abbreviation, a 3-digit
# basketball score at 12px, and a status like "P3 11:47" underneath.
SCORE_PANEL_W = 96
LOGO_PANEL_W = 38

_DIM_GREY = (110, 110, 118)


def _scale(color, factor):
    return tuple(max(0, min(255, int(c * factor))) for c in color[:3])


def _mix(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def _luma(color):
    return 0.2126 * color[0] + 0.7152 * color[1] + 0.0722 * color[2]


def score_alert_duration(alert):
    """Total on-screen time for one alert, in seconds."""
    hold = HOLD_BIG if (alert or {}).get('big') else HOLD_NORMAL
    return WIPE_IN + hold + WIPE_OUT


class ScoreAlertMixin:

    # ── palette ──────────────────────────────────────────────────────────────
    def _score_alert_palette(self, alert):
        """Base and accent colours, guaranteed to be visible on a dark panel.

        Team primaries are frequently near-black (navy, deep green), which makes
        an unusable background, and alternates are frequently pure white, which
        makes an unusable accent on a power-limited panel. Each falls back to
        something derived rather than to a fixed default, so the alert still
        reads as the team's.
        """
        base = self._parse_hex_color(alert.get('team_color'))
        alt = self._parse_hex_color(alert.get('team_alt_color'))

        if not base or self._is_near_black(base):
            logo = self.get_logo(alert.get('team_logo'), (24, 24))
            dominant = self._logo_nonblack_dominant_colors(logo, limit=1)
            base = dominant[0] if dominant else (alt if alt and not self._is_near_black(alt) else (40, 90, 190))

        if _luma(base) > 150:
            # Golds and yellows light the whole 384px field at once, which is
            # both a current draw the panels can't hold and a background the
            # white headline stops standing out against.
            base = _scale(base, 150.0 / _luma(base))

        if _luma(base) < 55:
            # Too dark to survive the 30% background scaling. Lifted by scaling
            # the channels, not by mixing in white: Yankee navy mixed toward
            # white is grey, but the same navy scaled up is still navy.
            base = _scale(base, 55.0 / max(1.0, _luma(base)))

        if not alt or self._is_near_black(alt) or self._is_near_white(alt):
            alt = _mix(base, (255, 255, 255), 0.55)

        return base, alt

    # ── background ───────────────────────────────────────────────────────────
    def _draw_alert_background(self, img, base, accent, phase):
        """Team-colour field with chevrons sweeping across it."""
        W, H = img.size
        d = ImageDraw.Draw(img, "RGBA")
        d.rectangle([0, 0, W, H], fill=_scale(base, 0.30))

        stripe = _scale(base, 0.62)
        spacing = 26
        offset = int(phase * spacing) % spacing
        for x in range(-H - spacing, W + spacing, spacing):
            d.line([(x + offset, H), (x + offset + H, 0)], fill=stripe, width=7)

        # Accent rails. Held well under full brightness: two full-width rows of
        # a light colour is the single most expensive thing in this frame.
        pulse = 0.55 + 0.25 * math.sin(phase * 3.2)
        rail = _scale(accent, pulse)
        d.line([(0, 0), (W, 0)], fill=rail)
        d.line([(0, H - 1), (W, H - 1)], fill=rail)

    # ── panels ───────────────────────────────────────────────────────────────
    def _draw_alert_logo_panel(self, img, alert, base, accent):
        d = ImageDraw.Draw(img, "RGBA")
        d.rectangle([0, 1, LOGO_PANEL_W - 2, PANEL_H - 2], fill=_scale(base, 0.12))
        d.line([(LOGO_PANEL_W - 1, 1), (LOGO_PANEL_W - 1, PANEL_H - 2)], fill=accent)

        logo = self.get_logo(alert.get('team_logo'), (24, 24))
        if logo is not None:
            img.paste(logo, ((LOGO_PANEL_W - 1 - 24) // 2, 4), logo)
        else:
            draw_tiny_text(d, 5, 13, str(alert.get('team_abbr', ''))[:3], (235, 235, 235))

    def _draw_alert_score_panel(self, img, alert, accent):
        """Away/home rows plus the game status line, in their own column.

        The score is the one thing here read from across a room, so it gets a
        real 12px face rather than the 4x5 pixel font — the abbreviation beside
        it can afford to stay small, because context already tells you which
        two teams are playing. A colour tab marks the team that just scored;
        white-versus-grey alone is too subtle at this size.
        """
        d = ImageDraw.Draw(img, "RGBA")
        x0 = PANEL_W - SCORE_PANEL_W
        # The chevrons run the full width, and pixel text has no outline to
        # survive them — the column gets its own scrim instead.
        d.rectangle([x0 - 1, 1, PANEL_W, PANEL_H - 2], fill=(0, 0, 0, 190))
        d.line([(x0 - 2, 1), (x0 - 2, PANEL_H - 2)], fill=_scale(accent, 0.5))

        scorer = str(alert.get('team_abbr', '')).upper()
        rows = (
            (str(alert.get('away_abbr', '')), alert.get('away_score')),
            (str(alert.get('home_abbr', '')), alert.get('home_score')),
        )
        for i, (abbr, score) in enumerate(rows):
            top = 1 + i * 12
            is_scorer = abbr.upper() == scorer
            color = (255, 255, 255) if is_scorer else _DIM_GREY
            if is_scorer:
                d.rectangle([x0 + 1, top, x0 + 2, top + 10], fill=accent)
            draw_hybrid_text(d, x0 + 6, top + 2, abbr[:3], color)
            d.text((PANEL_W - 3, top + 5), str(score if score is not None else ''),
                   font=self.medium_font, fill=color, anchor="rm")

        # Neutral rather than team-coloured: a navy or maroon accent at 5px is
        # unreadable on the black scrim, and the clock is the one line here
        # that has to be legible for every team.
        arrow, status = self._alert_status_label(alert)
        x = x0 + 6
        if arrow:
            # A row lower than the text: the triangle is three rows tall and
            # would otherwise hang off the top of the five-row digits.
            draw_tiny_text(d, x, 26, arrow, (200, 200, 210))
            # The triangle fills all five columns of its cell, so the font's
            # own advance leaves the inning number touching the base.
            x += 7
        if status:
            draw_tiny_text(d, x, 25, status, (200, 200, 210))

    def _alert_status_label(self, alert):
        """Return ``(arrow, text)`` for the status line.

        Baseball gets the same ▲/▼ inning arrows the scroll cards draw, rather
        than the "^7"/"V7" letters ``shorten_status`` produces for the compact
        strip — this panel has the room, and two conventions for the same thing
        on one board is one too many.
        """
        sport = str(alert.get('sport', '')).lower()
        raw = str(alert.get('status', ''))
        if any(k in sport for k in ('mlb', 'baseball', 'wbc')):
            upper = raw.upper()
            # Between innings, and once the game is over, there is no half to
            # point at — those fall through to the normal label.
            if not any(k in upper for k in ('FINAL', 'END', 'MID', 'DELAY', 'SUSP', 'PPD')):
                inning = re.search(r'\d+', raw)
                if inning:
                    if 'TOP' in upper or '^' in upper:
                        return '▲', inning.group()
                    if 'BOT' in upper or 'V' in upper:
                        return '▼', inning.group()
        return '', self.shorten_status(raw, sport)[:16]

    # ── headline ─────────────────────────────────────────────────────────────
    def _flap_fonts(self):
        """Monospace faces for the flap headline, largest first.

        Built on demand and kept on the instance: the renderer's font set is
        constructed in two places (the controller's __init__ and the preview
        tool's stand-in), and adding a sixth face to both is a standing
        invitation for them to drift apart.
        """
        fonts = getattr(self, '_alert_flap_fonts', None)
        if fonts is None:
            fonts = [load_monospace_font(size, bold=True) for size in _FLAP_SIZES]
            self._alert_flap_fonts = fonts
        return fonts

    def _flap_headline(self, text, elapsed):
        """The headline mid-flip: settled on the left, still cycling on the right."""
        settled = int(max(0.0, elapsed - WIPE_IN) / FLAP_STEP)
        if settled >= len(text):
            return text
        # Seeded from the frame index so a given moment always draws the same
        # scramble — the preview tool renders some frames more than once.
        rng = random.Random(int(elapsed * 24))
        return ''.join(
            ch if (i < settled or not ch.isalnum()) else rng.choice(_FLAP_CHARS)
            for i, ch in enumerate(text)
        )

    def _draw_alert_headline(self, img, alert, accent, phase):
        """Headline (and scorer, when known) in the space between the panels."""
        d = ImageDraw.Draw(img, "RGBA")
        left = LOGO_PANEL_W + 4
        right = PANEL_W - SCORE_PANEL_W - 5
        width = right - left
        center = (left + right) // 2

        headline = str(alert.get('headline', 'SCORE')).upper()
        detail = str(alert.get('detail', '')).upper()

        font = self._flap_fonts()[-1]
        for candidate in self._flap_fonts():
            if d.textlength(headline, font=candidate) <= width:
                font = candidate
                break
        # Every headline in the vocabulary fits at one of these sizes; a longer
        # one from a future sport gets clipped rather than overrunning the logo.
        baseline_y = 11 if detail else PANEL_H // 2 - 1

        shown = self._flap_headline(headline, phase)
        self.draw_outlined_text(d, center, baseline_y, shown, font,
                                (255, 255, 255), (0, 0, 0), anchor="mm")

        # The name lands once the flaps have stopped, so the two reveals read as
        # one sequence rather than competing for attention.
        if detail and shown == headline:
            detail_w = len(detail) * 5
            x = center - detail_w // 2
            d.rectangle([x - 4, 23, x + detail_w + 2, 30], fill=(0, 0, 0, 190))
            draw_tiny_text(d, x, 24, detail, _mix(accent, (255, 255, 255), 0.4))

    # ── frame ────────────────────────────────────────────────────────────────
    def draw_score_alert(self, alert, elapsed, under=None):
        """Render one frame of the takeover at ``elapsed`` seconds in.

        ``under`` is whatever the panel was showing when the alert fired. The
        shutters open over it rather than over black, so the takeover reads as
        landing on top of the ticker instead of the ticker blinking out first.
        """
        base, accent = self._score_alert_palette(alert)
        img = Image.new("RGBA", (PANEL_W, PANEL_H), (0, 0, 0, 255))

        self._draw_alert_background(img, base, accent, elapsed)
        self._draw_alert_logo_panel(img, alert, base, accent)
        self._draw_alert_score_panel(img, alert, accent)
        self._draw_alert_headline(img, alert, accent, elapsed)

        return self._apply_alert_shutters(img, alert, elapsed, accent, under)

    def _apply_alert_shutters(self, img, alert, elapsed, accent, under=None):
        """Open the frame from the centre, and close it the same way.

        Masking a finished frame rather than animating the contents keeps the
        entrance independent of what is being drawn, so a long headline and a
        short one slam in identically.
        """
        total = score_alert_duration(alert)
        out_start = total - WIPE_OUT

        if elapsed < WIPE_IN:
            t = elapsed / WIPE_IN
            open_frac = t * t * (3 - 2 * t)      # smoothstep: fast, then settles
        elif elapsed >= out_start:
            t = min(1.0, (elapsed - out_start) / WIPE_OUT)
            open_frac = 1.0 - t * t
        else:
            open_frac = 1.0

        if open_frac >= 1.0:
            return img.convert("RGB")

        # Whatever the panel was showing fills the not-yet-covered edges. Falls
        # back to black when the alert fired over nothing (an idle board).
        backdrop = Image.new("RGB", (PANEL_W, PANEL_H), (0, 0, 0))
        if under is not None:
            backdrop.paste(under.convert("RGB"), (0, 0))

        half = int((PANEL_W / 2) * max(0.0, open_frac))
        if half <= 0:
            return backdrop

        center = PANEL_W // 2
        frame = img.convert("RGB")
        backdrop.paste(frame.crop((center - half, 0, center + half, PANEL_H)),
                       (center - half, 0))
        # Bright leading edges, so the shutters read as light travelling outward.
        d = ImageDraw.Draw(backdrop)
        d.line([(center - half, 0), (center - half, PANEL_H)], fill=accent)
        d.line([(center + half, 0), (center + half, PANEL_H)], fill=accent)
        return backdrop


class PreparedScoreAlertRenderer(ScoreAlertMixin):
    """Provide explicit resources for the ported score alert renderer."""

    def __init__(self, fonts, logos):
        self.medium_font = fonts.medium
        self._logos = logos

    def get_logo(self, url, size):
        """Return a prepared logo without network access."""
        return self._logos.get(str(url) if url else None, size)

    @staticmethod
    def _parse_hex_color(value):
        """Parse an RGB hex value."""
        try:
            value = str(value or "").strip().lstrip("#")
            if len(value) == 6:
                return tuple(int(value[index:index + 2], 16) for index in (0, 2, 4))
        except ValueError:
            pass
        return None

    @staticmethod
    def _is_near_black(color, lum_threshold=24, max_threshold=42, chroma_threshold=16):
        """Identify an unreadable dark colour."""
        if not color or len(color) < 3:
            return True
        red, green, blue = (int(value) for value in color[:3])
        luma = 0.2126 * red + 0.7152 * green + 0.0722 * blue
        return (max(red, green, blue) <= max_threshold and luma <= lum_threshold) or (max(red, green, blue) <= max_threshold + 6 and luma <= lum_threshold + 4 and max(red, green, blue) - min(red, green, blue) <= chroma_threshold)

    @staticmethod
    def _is_near_white(color, lum_threshold=236, min_channel_threshold=226):
        """Identify an unreadable light colour."""
        if not color or len(color) < 3:
            return False
        red, green, blue = (int(value) for value in color[:3])
        return 0.2126 * red + 0.7152 * green + 0.0722 * blue >= lum_threshold or min(red, green, blue) >= min_channel_threshold

    def _logo_nonblack_dominant_colors(self, logo, limit=2):
        """Return dominant readable logo colours."""
        if logo is None:
            return []
        colors = logo.convert("RGBA").resize((24, 24), Image.NEAREST).getcolors(576) or []
        result = []
        for _, color in sorted(colors, key=lambda item: item[0], reverse=True):
            if color[3] < 90 or self._is_near_black(color[:3]):
                continue
            rgb = tuple(int(value) for value in color[:3])
            if not any(sum(abs(rgb[index] - prior[index]) for index in range(3)) < 45 for prior in result):
                result.append(rgb)
            if len(result) >= limit:
                break
        return result

    @staticmethod
    def draw_outlined_text(draw, x, y, text, font, fill, outline, anchor="mm"):
        """Draw the controller one-pixel text outline."""
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                if dx or dy:
                    draw.text((x + dx, y + dy), text, font=font, fill=outline, anchor=anchor)
        draw.text((x, y), text, font=font, fill=fill, anchor=anchor)

    @staticmethod
    def shorten_status(status, sport=""):
        """Return the controller status abbreviation."""
        if not status:
            return ""
        text = str(status).upper()
        for old, new in (("TOP ", "^"), ("BOTTOM ", "V"), ("BOT ", "V")):
            text = text.replace(old, new)
        return text[:16]
