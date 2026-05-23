"""Compatibility facade for catalog definitions.

New catalog data lives in ``sports_ticker.catalog`` so this module can stay
small and easy to scan while older imports continue to work.
"""

from .catalog.leagues import LEAGUE_OPTIONS, SPORTS_LEAGUES, STOCK_GROUPS, UTILITY_OPTIONS
from .catalog.modes import MODE_MIGRATIONS, MODE_OPTIONS, VALID_MODES, _MODE_LABEL_MAP, _VALID_MODE_IDS
from .catalog.helpers import (
    MASTERS_LOGO_URL,
    PGA_CHAMPIONSHIP_LOGO_URL,
    PGA_TOUR_LOGO_URL,
    GOLF_TOURNAMENT_COLORS,
    PGA_TOUR_COLORS,
    _golf_tournament_colors,
    _LEAGUE_LABEL_MAP,
    _VALID_LEAGUE_IDS,
    _STOCK_LISTS,
    _LEAGUE_CATEGORY_ORDER,
    _auto_category_for_option,
    _league_sort_key,
)

