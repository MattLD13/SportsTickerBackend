"""Helper data and lookup builders for the catalog."""

from .leagues import LEAGUE_OPTIONS

MASTERS_LOGO_URL = "https://upload.wikimedia.org/wikipedia/en/2/23/Masters_Logo.png"
PGA_CHAMPIONSHIP_LOGO_URL = "https://upload.wikimedia.org/wikipedia/en/thumb/3/3b/PGA_Championship_logo.svg/220px-PGA_Championship_logo.svg.png"
PGA_TOUR_LOGO_URL = "https://upload.wikimedia.org/wikipedia/en/thumb/2/27/PGA_Tour_logo.svg/220px-PGA_Tour_logo.svg.png"

GOLF_TOURNAMENT_COLORS = {
    'masters': {
        'primary': '#C8A84B',
        'alt': '#0B4F2A',
        'logo': MASTERS_LOGO_URL,
        'brand': ['THE', 'MASTERS'],
    },
    'pga championship': {
        'primary': '#C8A84B',
        'alt': '#00338D',
        'logo': PGA_CHAMPIONSHIP_LOGO_URL,
        'brand': ['PGA', 'CHAMP'],
    },
}

PGA_TOUR_COLORS = {
    'primary': '#FFFFFF',
    'alt': '#003087',
    'logo': PGA_TOUR_LOGO_URL,
    'brand': ['PGA', 'TOUR'],
}


def _golf_tournament_colors(event_name: str) -> dict:
    """Return tournament colors for the given ESPN event name."""
    lower = str(event_name or '').lower()
    for key, config in GOLF_TOURNAMENT_COLORS.items():
        if key in lower:
            return config
    return PGA_TOUR_COLORS


_LEAGUE_LABEL_MAP = {item['id']: item['label'] for item in LEAGUE_OPTIONS}
_VALID_LEAGUE_IDS = frozenset(item['id'] for item in LEAGUE_OPTIONS)
_STOCK_LISTS = {
    item['id']: item['stock_list']
    for item in LEAGUE_OPTIONS
    if item['type'] == 'stock' and 'stock_list' in item
}

_LEAGUE_CATEGORY_ORDER = {
    'football': 0,
    'basketball': 1,
    'baseball': 2,
    'hockey': 3,
    'soccer': 4,
    'other': 5,
    'util': 6,
    'stock': 7,
}


def _auto_category_for_option(item: dict) -> str:
    t = item.get('type')
    if t != 'sport':
        return str(t or 'other')
    league_id = str(item.get('id', ''))
    path = str((item.get('fetch') or {}).get('path', '')).lower()
    if league_id.startswith('soccer_') or path.startswith('soccer/'):
        return 'soccer'
    if path.startswith('football/'):
        return 'football'
    if path.startswith('basketball/'):
        return 'basketball'
    if path.startswith('baseball/'):
        return 'baseball'
    if path.startswith('hockey/'):
        return 'hockey'
    return 'other'


def _league_sort_key(item: dict):
    category = _auto_category_for_option(item)
    return (
        _LEAGUE_CATEGORY_ORDER.get(category, 99),
        str(item.get('label', '')).lower(),
    )

