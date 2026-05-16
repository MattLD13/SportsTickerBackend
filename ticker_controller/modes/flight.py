from PIL import Image, ImageDraw
from ..config import PANEL_W, PANEL_H
from ..fonts import draw_tiny_text


class FlightMixin:

    def _pixel(self, draw, x, y, color):
        if 0 <= x < PANEL_W and 0 <= y < PANEL_H:
            draw.point((x, y), fill=color)

    def _icon_plane(self, draw, x, y, color):
        pts = [(x+2,y),(x+1,y+1),(x+2,y+1),(x+3,y+1),(x,y+2),(x+1,y+2),(x+2,y+2),
               (x+3,y+2),(x+4,y+2),(x+2,y+3),(x+1,y+4),(x+2,y+4),(x+3,y+4)]
        for px, py in pts:
            self._pixel(draw, px, py, color)

    def draw_flight_visitor(self, game):
        img = Image.new("RGBA", (PANEL_W, PANEL_H), self.C_BG + (255,))
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
        draw_tiny_text(d, 18, 2, guest_name, self.C_AMBER)
        if guest_name.upper() != flight_id.upper() and flight_id.lower() != 'flight_tracker_blank':
            id_w = len(flight_id) * 5
            draw_tiny_text(d, PANEL_W - id_w - 8, 2, flight_id, self.C_GRY)

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
        img = Image.new("RGBA", (PANEL_W, PANEL_H), self.C_BG + (255,))
        d = ImageDraw.Draw(img)

        d.rectangle((0, 0, PANEL_W, 6), fill=(20, 30, 45))
        d.rectangle((0, 7, PANEL_W, 7), fill=(40, 90, 160))

        airport_name = str(weather_item.get('home_abbr', 'AIRPORT')) if weather_item else 'AIRPORT'
        draw_tiny_text(d, 3, 1, airport_name, self.C_BLUE_TXT)

        weather_temp = str(weather_item.get('away_abbr', '--')) if weather_item else '--'
        weather_cond = str(weather_item.get('status', '')) if weather_item else ''
        weather_str = f"{weather_temp} {weather_cond}"
        wx_w = len(weather_str) * 5
        draw_tiny_text(d, PANEL_W - wx_w - 3, 1, weather_str, self.C_WHT)

        d.rectangle((2, 9, 189, 30), fill=(25, 35, 50))
        draw_tiny_text(d, 5, 10, "NEXT ARRIVAL", self.C_GRY)
        for i, arr in enumerate(arrivals[:2]):
            flight_id = str(arr.get('away_abbr', '???'))
            from_city = str(arr.get('home_abbr', '???'))
            text_str = f"{flight_id} FROM {from_city}"[:36]
            draw_tiny_text(d, 5, 18 + i * 7, text_str, self.C_GRN)
        if not arrivals:
            draw_tiny_text(d, 5, 18, "--", self.C_GRY)

        d.rectangle((194, 9, 381, 30), fill=(25, 35, 50))
        draw_tiny_text(d, 197, 10, "NEXT DEPARTURE", self.C_GRY)
        for i, dep in enumerate(departures[:2]):
            flight_id = str(dep.get('away_abbr', '???'))
            to_city = str(dep.get('home_abbr', '???'))
            text_str = f"{flight_id} TO {to_city}"[:36]
            draw_tiny_text(d, 197, 18 + i * 7, text_str, self.C_RED)
        if not departures:
            draw_tiny_text(d, 197, 18, "--", self.C_GRY)

        return img
