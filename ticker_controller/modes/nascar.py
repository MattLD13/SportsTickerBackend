"""NASCAR display mode — same scroll/full layout as IndyCar and F1."""


class NascarMixin:
    def _nascar_as_indycar_game(self, game):
        """Map the nascar payload into the indycar slot so shared renderers work."""
        mapped = dict(game or {})
        nc = dict(mapped.get('nascar') or {})
        # Add laps info to header label support
        lap       = int(nc.get('lap') or 0)
        total     = int(nc.get('total_laps') or 0)
        remaining = int(nc.get('laps_remaining') or 0)
        track     = str(nc.get('track_name') or '').strip()
        short     = str(nc.get('short_name') or nc.get('event_name') or 'NASCAR').strip()

        # Build a compact session label: "Lap 142/200" or "FINAL" etc.
        if remaining == 0 and total > 0:
            session_label = 'FINAL'
        elif lap > 0 and total > 0:
            session_label = f"Lap {lap}/{total}"
        elif track:
            session_label = track
        else:
            session_label = str(nc.get('session_type') or 'Race').strip()

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
