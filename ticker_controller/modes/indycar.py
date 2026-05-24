"""IndyCar display mode — thin adapter over the generic racing layout.

IndyCar game dicts already use 'indycar' as the payload key, so no
field remapping is needed; just delegate to the shared RacingMixin.

The NASCAR helper functions are re-exported here so that controller.py
can keep its existing import without changes.
"""

from .racing import (
    RacingMixin,
    _load_nascar_car,
    _nascar_purge_old_cars,
    nascar_submit_downloads,
    nascar_retry_pending,
    nascar_dl_progress,
)

__all__ = [
    'IndycarMixin',
    '_load_nascar_car',
    '_nascar_purge_old_cars',
    'nascar_submit_downloads',
    'nascar_retry_pending',
    'nascar_dl_progress',
]


class IndycarMixin(RacingMixin):
    """IndyCar adapter — payload is already at game['indycar'], no remapping needed."""

    def draw_indycar_scroll_card(self, game):
        return self.draw_racing_scroll_card(game)

    def draw_indycar_full(self, game):
        return self.draw_racing_full(game)
