"""League definitions and golf tournament configuration.

To add a new sport league: add an entry to LEAGUE_OPTIONS.
To add a new golf tournament's colors: add an entry to GOLF_TOURNAMENT_COLORS.
"""

# ── Golf tournament logo URLs ──
MASTERS_LOGO_URL = "https://upload.wikimedia.org/wikipedia/en/2/23/Masters_Logo.png"
PGA_CHAMPIONSHIP_LOGO_URL = "https://upload.wikimedia.org/wikipedia/en/thumb/3/3b/PGA_Championship_logo.svg/220px-PGA_Championship_logo.svg.png"
PGA_TOUR_LOGO_URL = "https://upload.wikimedia.org/wikipedia/en/thumb/2/27/PGA_Tour_logo.svg/220px-PGA_Tour_logo.svg.png"

# ── Golf tournament colors ──
# Keys are lowercase substrings matched against the ESPN event name.
GOLF_TOURNAMENT_COLORS = {
    'masters': {
        'primary': '#C8A84B',   # Masters gold
        'alt':     '#0B4F2A',   # Augusta green
        'logo':    MASTERS_LOGO_URL,
        'brand':   ['THE', 'MASTERS'],
    },
    'pga championship': {
        'primary': '#C8A84B',   # Gold
        'alt':     '#00338D',   # PGA navy
        'logo':    PGA_CHAMPIONSHIP_LOGO_URL,
        'brand':   ['PGA', 'CHAMP'],
    },
}

PGA_TOUR_COLORS = {             # Generic fallback for any other PGA event
    'primary': '#FFFFFF',
    'alt':     '#003087',       # PGA Tour navy
    'logo':    PGA_TOUR_LOGO_URL,
    'brand':   ['PGA', 'TOUR'],
}


def _golf_tournament_colors(event_name: str) -> dict:
    """Return tournament colors for the given ESPN event name."""
    lower = str(event_name or '').lower()
    for key, config in GOLF_TOURNAMENT_COLORS.items():
        if key in lower:
            return config
    return PGA_TOUR_COLORS


# ── All available leagues / utilities / stock groups ──
LEAGUE_OPTIONS = [
    {'id': 'nfl', 'label': 'NFL', 'type': 'sport', 'default': True, 'fetch': {'path': 'football/nfl', 'team_params': {'limit': 100}, 'type': 'scoreboard'}},
    {'id': 'mlb', 'label': 'MLB', 'type': 'sport', 'default': True, 'fetch': {'path': 'baseball/mlb', 'team_params': {'limit': 100}, 'type': 'scoreboard'}},
    {'id': 'nhl', 'label': 'NHL', 'type': 'sport', 'default': True, 'fetch': {'path': 'hockey/nhl', 'team_params': {'limit': 100}, 'type': 'scoreboard'}},
    {'id': 'nba', 'label': 'NBA', 'type': 'sport', 'default': True, 'fetch': {'path': 'basketball/nba', 'team_params': {'limit': 100}, 'type': 'scoreboard'}},
    {'id': 'ncf_fbs', 'label': 'NCAA (FBS)', 'type': 'sport', 'default': True, 'fetch': {'path': 'football/college-football', 'scoreboard_params': {'groups': '80'}, 'type': 'scoreboard'}},
    {'id': 'ncf_fcs', 'label': 'NCAA (FCS)', 'type': 'sport', 'default': True, 'fetch': {'path': 'football/college-football', 'scoreboard_params': {'groups': '81'}, 'type': 'scoreboard'}},
    {'id': 'march_madness', 'label': 'March Madness', 'type': 'sport', 'default': True, 'fetch': {'path': 'basketball/mens-college-basketball', 'scoreboard_params': {'groups': '100', 'limit': '100'}, 'type': 'scoreboard'}},
    {'id': 'golf', 'label': 'Golf (PGA)', 'type': 'sport', 'default': True, 'fetch': {'path': 'golf/pga', 'type': 'leaderboard'}},
    {'id': 'soccer_epl', 'label': 'Premier League', 'type': 'sport', 'default': True, 'fetch': {'path': 'soccer/eng.1', 'team_params': {'limit': 50}, 'type': 'scoreboard'}},
    {'id': 'soccer_fa_cup', 'label': 'FA Cup', 'type': 'sport', 'default': True, 'fetch': {'path': 'soccer/eng.fa', 'type': 'scoreboard'}},
    {'id': 'soccer_champ', 'label': 'Championship', 'type': 'sport', 'default': True, 'fetch': {'path': 'soccer/eng.2', 'team_params': {'limit': 50}, 'type': 'scoreboard'}},
    #{'id': 'soccer_l1', 'label': 'League One', 'type': 'sport', 'default': True, 'fetch': {'path': 'soccer/eng.3', 'team_params': {'limit': 50}, 'type': 'scoreboard'}},
    #{'id': 'soccer_l2', 'label': 'League Two', 'type': 'sport', 'default': True, 'fetch': {'path': 'soccer/eng.4', 'team_params': {'limit': 50}, 'type': 'scoreboard'}},
    {'id': 'soccer_wc', 'label': 'FIFA World Cup', 'type': 'sport', 'default': True, 'fetch': {'path': 'soccer/fifa.world', 'team_params': {'limit': 100}, 'type': 'scoreboard'}},
    {'id': 'soccer_champions_league', 'label': 'Champions League', 'type': 'sport', 'default': True, 'fetch': {'path': 'soccer/uefa.champions', 'team_params': {'limit': 50}, 'type': 'scoreboard'}},
    {'id': 'soccer_europa_league', 'label': 'Europa League', 'type': 'sport', 'default': True, 'fetch': {'path': 'soccer/uefa.europa', 'team_params': {'limit': 200}, 'type': 'scoreboard'}},
    {'id': 'soccer_mls', 'label': 'MLS', 'type': 'sport', 'default': True, 'fetch': {'path': 'soccer/usa.1', 'team_params': {'limit': 100}, 'type': 'scoreboard'}},
    #{'id': 'wbc', 'label': 'WBC', 'type': 'sport', 'default': True, 'fetch': {'path': 'baseball/world-baseball-classic', 'type': 'scoreboard'}},
    #{'id': 'f1', 'label': 'Formula 1', 'type': 'sport', 'default': True, 'fetch': {'path': 'racing/f1', 'type': 'leaderboard'}},
    #{'id': 'nascar', 'label': 'NASCAR', 'type': 'sport', 'default': True, 'fetch': {'path': 'racing/nascar', 'type': 'leaderboard'}},
    {'id': 'indycar', 'label': 'IndyCar', 'type': 'sport', 'default': True, 'fetch': {'path': 'racing/irl', 'type': 'racing'}},
    {'id': 'weather', 'label': 'Weather', 'type': 'util', 'default': True},
    {'id': 'clock', 'label': 'Clock', 'type': 'util', 'default': True},
    {'id': 'music', 'label': 'Music', 'type': 'util', 'default': True},
    {'id': 'flight_tracker', 'label': 'Flight Tracker', 'type': 'util', 'default': False},
    {'id': 'flight_airport', 'label': 'Airport Activity', 'type': 'util', 'default': False},
    {'id': 'stock_tech_ai', 'label': 'Tech / AI Stocks', 'type': 'stock', 'default': True, 'stock_list': ["AAPL", "MSFT", "NVDA", "GOOGL", "AMZN", "META", "TSM", "AVGO", "ORCL", "CRM", "AMD", "IBM", "INTC", "QCOM", "CSCO", "ADBE", "TXN", "AMAT", "INTU", "NOW", "MU"]},
    {'id': 'stock_momentum', 'label': 'Momentum Stocks', 'type': 'stock', 'default': False, 'stock_list': ["COIN", "HOOD", "DKNG", "RBLX", "GME", "AMC", "MARA", "RIOT", "CLSK", "SOFI", "OPEN", "UBER", "DASH", "SHOP", "NET", "SQ", "PYPL", "AFRM", "UPST", "CVNA"]},
    {'id': 'stock_energy', 'label': 'Energy Stocks', 'type': 'stock', 'default': False, 'stock_list': ["XOM", "CVX", "COP", "EOG", "SLB", "MPC", "PSX", "VLO", "OXY", "KMI", "HAL", "BKR", "HES", "DVN", "OKE", "WMB", "CTRA", "FANG", "TTE", "BP"]},
    {'id': 'stock_finance', 'label': 'Financial Stocks', 'type': 'stock', 'default': False, 'stock_list': ["JPM", "BAC", "WFC", "C", "GS", "MS", "BLK", "AXP", "V", "MA", "SCHW", "USB", "PNC", "TFC", "BK", "COF", "SPGI", "MCO", "CB", "PGR"]},
    {'id': 'stock_consumer', 'label': 'Consumer Stocks', 'type': 'stock', 'default': False, 'stock_list': ["WMT", "COST", "TGT", "HD", "LOW", "MCD", "SBUX", "CMG", "NKE", "LULU", "KO", "PEP", "PG", "CL", "KMB", "DIS", "NFLX", "CMCSA", "HLT", "MAR"]},
]

# ── Derived lookup structures ──
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

# ── Modes ──
VALID_MODES = {
    'sports', 'sports_full', 'soccer_full', 'live', 'my_teams',
    'stocks', 'weather', 'music', 'clock',
    'golf', 'masters',  # 'masters' kept as recognized alias (migrated → 'golf')
    'flights', 'flight_tracker',
    'indycar', 'indycar_full',
}

# Legacy mode migration applied at load time and on /api/config writes
MODE_MIGRATIONS = {
    'all': 'sports',
    'flight2': 'flight_tracker',
    'poop_fetcher': 'sports',
    'masters': 'golf',
}
