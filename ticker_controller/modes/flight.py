from PIL import Image, ImageDraw
from ..config import PANEL_W, PANEL_H
from ..fonts import draw_tiny_text

# Airport board layout. Four rows a side on a 6px pitch, starting under the
# inline header — the filled panel boxes are gone, so structure comes from the
# divider rule and the inbound/outbound colours rather than from ~4000 dimly
# lit background pixels, which read as muddy grey on the panel.
BOARD_ROWS = 4
CITY_CHARS = 18
BOARD_RULE = (30, 60, 100)
BOARD_ALT = (70, 90, 120)
BOARD_WX = (90, 110, 140)
# "HEAVY SNOW SHOWERS" is the longest WMO description, so 24 clears every
# condition with the temperature prefix. It right-aligns to x=381 and the
# OUTBOUND caption ends at 236, leaving 28 characters of room.
BOARD_WX_CHARS = 24


class FlightMixin:

    def _pixel(self, draw, x, y, color):
        if 0 <= x < PANEL_W and 0 <= y < PANEL_H:
            draw.point((x, y), fill=color)

    def _icon_plane(self, draw, x, y, color):
        pts = [(x+2,y),(x+1,y+1),(x+2,y+1),(x+3,y+1),(x,y+2),(x+1,y+2),(x+2,y+2),
               (x+3,y+2),(x+4,y+2),(x+2,y+3),(x+1,y+4),(x+2,y+4),(x+3,y+4)]
        for px, py in pts:
            self._pixel(draw, px, py, color)

    def _flight_logo_url(self, item):
        if not isinstance(item, dict):
            return ''
        logo = str(item.get('airline_logo') or '').strip()
        if logo:
            return logo
        for key in ('airline_iata', 'airline_code', 'airline_icao', 'airline'):
            airline = str(item.get(key) or '').strip().upper().replace(' ', '')
            if len(airline) in (2, 3) and airline.isalnum():
                domain = self._airline_domain_for_code(airline)
                return f"https://www.google.com/s2/favicons?domain={domain}&sz=64"
        flight_id = str(item.get('away_abbr') or item.get('id') or '').strip().upper().replace(' ', '')
        if len(flight_id) >= 2 and flight_id[:2].isalpha():
            domain = self._airline_domain_for_code(flight_id[:2].upper())
            return f"https://www.google.com/s2/favicons?domain={domain}&sz=64"
        return ''

    @staticmethod
    def _airline_domain_for_code(code):
        return {
            'UA': 'united.com',
            'DL': 'delta.com',
            'AA': 'aa.com',
            'WN': 'southwest.com',
            'B6': 'jetblue.com',
            'AS': 'alaskaair.com',
            'AC': 'aircanada.com',
            'BA': 'britishairways.com',
            'LH': 'lufthansa.com',
            'AF': 'airfrance.us',
            'KL': 'klm.com',
            'EK': 'emirates.com',
        }.get(code, f"{code.lower()}.com")

    def draw_flight_visitor(self, game):
        img = Image.new("RGBA", (PANEL_W, PANEL_H), (0, 0, 0, 255))
        d = ImageDraw.Draw(img)

        guest_name = str(game.get('guest_name', game.get('id', '???')))
        flight_id = str(game.get('id', '???'))
        route_origin = str(game.get('origin_city', '???'))
        route_dest = str(game.get('dest_city', '???'))
        alt = int(game.get('alt', 0))
        dist = int(game.get('dist', 0))
        speed = int(game.get('speed', 0))
        eta_str = str(game.get('eta_str', '--'))
        progress = int(game.get('progress', 0))
        status = str(game.get('status', 'scheduled'))
        is_live = game.get('is_live', False)
        try:
            delay_min = int(float(game.get('delay_min', 0) or 0))
        except (TypeError, ValueError):
            delay_min = 0
        is_delayed = bool(game.get('is_delayed', False)) or delay_min > 0 or ('delay' in status.lower())
        plane_type = str(game.get('aircraft_type', '') or '').strip()
        if plane_type:
            plane_type = plane_type[:60]

        def with_plane_label(text):
            return f"{text}  {plane_type}" if plane_type else text

        if is_delayed:
            plane_color = self.C_RED
        else:
            plane_color = self.C_GRN if is_live else self.C_AMBER
        self._icon_plane(d, 6, 2, plane_color)

        logo_w = 22
        logo_x = PANEL_W - logo_w - 6
        logo_url = self._flight_logo_url(game)
        if logo_url:
            try:
                self.download_and_process_logo(logo_url, (logo_w, logo_w))
                logo = self.get_logo(logo_url, (logo_w, logo_w))
                if logo:
                    img.alpha_composite(logo, (logo_x, 1))
            except Exception:
                pass

        if guest_name.upper() != flight_id.upper() and flight_id.lower() != 'flight_tracker_blank':
            id_w = len(flight_id) * 5
            draw_tiny_text(d, logo_x - id_w - 5, 2, flight_id, self.C_GRY)

        draw_tiny_text(d, 14, 2, guest_name, self.C_AMBER)

        route_str = f"{route_origin} > {route_dest}"
        draw_tiny_text(d, 6, 10, route_str, self.C_BLUE_TXT)

        if is_live:
            stats = f"{dist} MI  {eta_str}  {speed} MPH  {alt:,} FT"
            draw_tiny_text(d, 6, 18, with_plane_label(stats), self.C_WHT)
        else:
            draw_tiny_text(d, 6, 18, with_plane_label(status.upper()), self.C_AMBER)

        bar_x, bar_y, bar_w, bar_h = 6, 27, 372, 3
        bar_bg = (15, 35, 15)
        bar_fill = self.C_GRN
        if is_delayed:
            bar_bg = (60, 10, 10)
            bar_fill = self.C_RED
        d.rectangle((bar_x, bar_y, bar_x + bar_w, bar_y + bar_h), fill=bar_bg)
        pct = progress / 100.0 if is_live else 0.02
        fill_w = int(bar_w * max(0.02, min(0.98, pct)))
        d.rectangle((bar_x, bar_y, bar_x + fill_w, bar_y + bar_h), fill=bar_fill)
        return img

    def draw_flight_airport(self, weather_item, arrivals, departures):
        img = Image.new("RGBA", (PANEL_W, PANEL_H), (0, 0, 0, 255))
        d = ImageDraw.Draw(img)

        code, city = '', ''
        if weather_item:
            code = str(weather_item.get('iata') or '').strip().upper()
            city = str(weather_item.get('city') or '').strip().upper()
            if not code:
                code = str(weather_item.get('home_abbr', '') or '').upper()[:10]
        # Airport identity in blue, kept distinct from the green/red captions so
        # the colours stay meaningful as direction rather than decoration.
        x = 3
        if code:
            draw_tiny_text(d, x, 0, code, self.C_BLUE_TXT)
            x += len(code) * 5 + 5
        if city:
            city = city[:12]
            draw_tiny_text(d, x, 0, city, self.C_BLUE_TXT)
            x += len(city) * 5 + 5
        # INBOUND and OUTBOUND rather than "NEXT ARRIVAL"/"NEXT DEPARTURE": these
        # are live aircraft positions, not a schedule, and a low-altitude
        # departure has already left. Each caption takes the colour of the rows
        # beneath it.
        draw_tiny_text(d, x, 0, "INBOUND", self.C_GRN)
        draw_tiny_text(d, 196, 0, "OUTBOUND", self.C_RED)

        if weather_item:
            wx = "{} {}".format(weather_item.get('away_abbr', '--'),
                                weather_item.get('status', '')).strip().upper()
            if len(wx) > BOARD_WX_CHARS:
                # Trim on a word boundary. A hard cut turned "84F CLEAR SKY"
                # into "84F CLEAR SK", which reads as a different field
                # entirely rather than as truncation.
                wx = wx[:BOARD_WX_CHARS].rsplit(' ', 1)[0]
            if wx:
                draw_tiny_text(d, PANEL_W - len(wx) * 5 - 3, 0, wx, BOARD_WX)

        d.rectangle((0, 6, PANEL_W, 6), fill=BOARD_RULE)
        d.rectangle((190, 8, 190, 31), fill=BOARD_RULE)

        def side(rows, x, edge, colour, empty):
            if not rows:
                draw_tiny_text(d, x, 9, empty, self.C_GRY)
                return
            for i, r in enumerate(rows[:BOARD_ROWS]):
                y = 9 + i * 6
                draw_tiny_text(d, x, y, str(r.get('away_abbr', '???'))[:6], colour)
                draw_tiny_text(d, x + 34, y, str(r.get('other_iata', '') or '')[:3], self.C_GRY)
                draw_tiny_text(d, x + 54, y,
                               str(r.get('home_abbr', '???')).upper()[:CITY_CHARS], self.C_WHT)
                # Altitude explains the ordering — the list is sorted by it — and
                # is the one honest "how close is it" the live feed can give.
                try:
                    alt = int(r.get('altitude') or 0)
                except (TypeError, ValueError):
                    alt = 0
                if alt > 0:
                    ft = "{:,}FT".format(alt)
                    draw_tiny_text(d, edge - len(ft) * 5, y, ft, BOARD_ALT)

        side(arrivals, 3, 188, self.C_GRN, "NO INBOUND")
        side(departures, 196, 381, self.C_RED, "NO OUTBOUND")
        return img
