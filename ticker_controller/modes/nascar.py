"""NASCAR display mode — same scroll/full layout as IndyCar and F1."""


class NascarMixin:
    def _nascar_as_indycar_game(self, game):
        """Map the nascar payload into the indycar slot so shared renderers work."""
        mapped = dict(game or {})
        nc = dict(mapped.get('nascar') or {})
        total     = int(nc.get('total_laps') or 0)
        remaining = int(nc.get('laps_remaining') or 0)
        short     = str(nc.get('short_name') or nc.get('event_name') or 'NASCAR').strip()

        # Compact series label: "Race" for Cup, keep "Xfinity"/"Trucks" as-is.
        # This mirrors the away_abbr/home_abbr pattern used on other sport cards
        # so the header reads e.g. "Coca-Cola 600 Race" instead of "Lap 142/200".
        # Lap count is still rendered in the info-panel body via ic['lap']/ic['total_laps'].
        _raw_series = str(nc.get('session_type') or '').strip()
        if 'Xfinity' in _raw_series:
            series_short = 'Xfinity'
        elif 'Truck' in _raw_series:
            series_short = 'Trucks'
        else:
            series_short = 'Race'

        # FINAL when race is over; short series type while running
        if remaining == 0 and total > 0:
            session_label = 'FINAL'
        else:
            session_label = series_short

        nc['session_name'] = session_label
        nc['session_type'] = session_label
        nc['short_name']   = short
        nc['event_name']   = short
        mapped['indycar']  = nc
        return mapped

    def draw_nascar_scroll_card(self, game):
        return self.draw_racing_scroll_card(self._nascar_as_indycar_game(game))

    def draw_nascar_full(self, game):
        return self.draw_racing_full(self._nascar_as_indycar_game(game))
