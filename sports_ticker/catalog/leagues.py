"""Sports league and non-mode content group definitions."""

# Sports Leagues
# Disabling one of these globally stops background fetching for that league.
SPORTS_LEAGUES = [
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
    {'id': 'soccer_wc', 'label': 'FIFA World Cup', 'type': 'sport', 'default': True, 'fetch': {'path': 'soccer/fifa.world', 'team_params': {'limit': 100}, 'type': 'scoreboard'}},
    {'id': 'soccer_champions_league', 'label': 'Champions League', 'type': 'sport', 'default': True, 'fetch': {'path': 'soccer/uefa.champions', 'team_params': {'limit': 50}, 'type': 'scoreboard'}},
    {'id': 'soccer_europa_league', 'label': 'Europa League', 'type': 'sport', 'default': True, 'fetch': {'path': 'soccer/uefa.europa', 'team_params': {'limit': 200}, 'type': 'scoreboard'}},
    {'id': 'soccer_mls', 'label': 'MLS', 'type': 'sport', 'default': True, 'fetch': {'path': 'soccer/usa.1', 'team_params': {'limit': 100}, 'type': 'scoreboard'}},
    {'id': 'f1', 'label': 'Formula 1', 'type': 'sport', 'default': True, 'fetch': {'path': 'racing/f1', 'type': 'racing'}},
    {'id': 'indycar', 'label': 'IndyCar', 'type': 'sport', 'default': True, 'fetch': {'path': 'racing/irl', 'type': 'racing'}},
    {'id': 'nascar', 'label': 'NASCAR', 'type': 'sport', 'default': False, 'fetch': {'path': 'racing/nascar', 'type': 'racing'}},
]


# Non-Mode Content Groups
# These are still exposed through LEAGUE_OPTIONS for older dashboard/app clients.
UTILITY_OPTIONS = [
    {'id': 'weather', 'label': 'Weather', 'type': 'util', 'default': True},
    {'id': 'clock', 'label': 'Clock', 'type': 'util', 'default': True},
    {'id': 'music', 'label': 'Music', 'type': 'util', 'default': True},
    {'id': 'flight_tracker', 'label': 'Flight Tracker', 'type': 'util', 'default': False},
    {'id': 'flight_airport', 'label': 'Airport Activity', 'type': 'util', 'default': False},
]

STOCK_GROUPS = [
    {'id': 'stock_tech_ai', 'label': 'Tech / AI Stocks', 'type': 'stock', 'default': True, 'stock_list': ["AAPL", "MSFT", "NVDA", "GOOGL", "AMZN", "META", "TSM", "AVGO", "ORCL", "CRM", "AMD", "IBM", "INTC", "QCOM", "CSCO", "ADBE", "TXN", "AMAT", "INTU", "NOW", "MU"]},
    {'id': 'stock_momentum', 'label': 'Momentum Stocks', 'type': 'stock', 'default': False, 'stock_list': ["COIN", "HOOD", "DKNG", "RBLX", "GME", "AMC", "MARA", "RIOT", "CLSK", "SOFI", "OPEN", "UBER", "DASH", "SHOP", "NET", "SQ", "PYPL", "AFRM", "UPST", "CVNA"]},
    {'id': 'stock_energy', 'label': 'Energy Stocks', 'type': 'stock', 'default': False, 'stock_list': ["XOM", "CVX", "COP", "EOG", "SLB", "MPC", "PSX", "VLO", "OXY", "KMI", "HAL", "BKR", "HES", "DVN", "OKE", "WMB", "CTRA", "FANG", "TTE", "BP"]},
    {'id': 'stock_finance', 'label': 'Financial Stocks', 'type': 'stock', 'default': False, 'stock_list': ["JPM", "BAC", "WFC", "C", "GS", "MS", "BLK", "AXP", "V", "MA", "SCHW", "USB", "PNC", "TFC", "BK", "COF", "SPGI", "MCO", "CB", "PGR"]},
    {'id': 'stock_consumer', 'label': 'Consumer Stocks', 'type': 'stock', 'default': False, 'stock_list': ["WMT", "COST", "TGT", "HD", "LOW", "MCD", "SBUX", "CMG", "NKE", "LULU", "KO", "PEP", "PG", "CL", "KMB", "DIS", "NFLX", "CMCSA", "HLT", "MAR"]},
]

LEAGUE_OPTIONS = SPORTS_LEAGUES + UTILITY_OPTIONS + STOCK_GROUPS

