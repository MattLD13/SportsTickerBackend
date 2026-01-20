import os

# ================= SERVER VERSION TAG =================
SERVER_VERSION = "v5"

# ================= CONFIGURATION & STORAGE =================
TICKER_DATA_DIR = "ticker_data"
GLOBAL_CONFIG_FILE = "global_config.json"
STOCK_CACHE_FILE = "stock_cache.json"

# === MICRO INSTANCE TUNING (SMART-5) ===
SPORTS_UPDATE_INTERVAL = 5.0   # Keep this fast
STOCKS_UPDATE_INTERVAL = 30    # Slow down stocks to save CPU
WORKER_THREAD_COUNT = 10       # LIMIT THIS to 10 to save RAM (Critical)
API_TIMEOUT = 3.0              # New constant for hard timeouts

# Headers for FotMob/ESPN
HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Accept": "application/json",
    "Accept-Language": "en",
    "Referer": "https://www.fotmob.com/"
}

# ================= FOTMOB MAPPING =================
FOTMOB_LEAGUE_MAP = {
    'soccer_epl': 47,
    'soccer_fa_cup': 132,
    'soccer_champ': 48,
    'soccer_l1': 108,
    'soccer_l2': 109,
    'soccer_wc': 77,
    'soccer_champions_league': 42,
    'soccer_europa_league': 73,
    'soccer_mls': 130
}

# ================= AHL CONFIGURATION =================
AHL_API_KEYS = [
    "ccb91f29d6744675", "694cfeed58c932ee", "50c2cd9b5e18e390"
]

TZ_OFFSETS = {
    "EST": -5, "EDT": -4, "CST": -6, "CDT": -5,
    "MST": -7, "MDT": -6, "PST": -8, "PDT": -7, "AST": -4, "ADT": -3
}

# ================= AHL TEAMS (Official LeagueStat IDs) =================
AHL_TEAMS = {
    "BRI": {"name": "Bridgeport Islanders", "color": "00539B", "id": "317"},
    "CLT": {"name": "Charlotte Checkers", "color": "C8102E", "id": "384"},
    "CHA": {"name": "Charlotte Checkers", "color": "C8102E", "id": "384"},
    "HFD": {"name": "Hartford Wolf Pack", "color": "0D2240", "id": "307"},
    "HER": {"name": "Hershey Bears", "color": "4F2C1D", "id": "319"},
    "LV":  {"name": "Lehigh Valley Phantoms", "color": "000000", "id": "313"},
    "PRO": {"name": "Providence Bruins", "color": "000000", "id": "309"},
    "SPR": {"name": "Springfield Thunderbirds", "color": "003087", "id": "411"},
    "WBS": {"name": "W-B/Scranton", "color": "000000", "id": "316"},
    "BEL": {"name": "Belleville Senators", "color": "C52032", "id": "413"},
    "CLE": {"name": "Cleveland Monsters", "color": "041E42", "id": "373"},
    "LAV": {"name": "Laval Rocket", "color": "00205B", "id": "415"},
    "ROC": {"name": "Rochester Americans", "color": "00539B", "id": "323"},
    "SYR": {"name": "Syracuse Crunch", "color": "003087", "id": "324"},
    "TOR": {"name": "Toronto Marlies", "color": "00205B", "id": "335"},
    "UTC": {"name": "Utica Comets", "color": "006341", "id": "390"},
    "UTI": {"name": "Utica Comets", "color": "006341", "id": "390"},
    "CHI": {"name": "Chicago Wolves", "color": "7C2529", "id": "330"},
    "GR":  {"name": "Grand Rapids Griffins", "color": "BE1E2D", "id": "328"},
    "IA":  {"name": "Iowa Wild", "color": "154734", "id": "389"},
    "MB":  {"name": "Manitoba Moose", "color": "003E7E", "id": "321"},
    "MIL": {"name": "Milwaukee Admirals", "color": "041E42", "id": "327"},
    "RFD": {"name": "Rockford IceHogs", "color": "CE1126", "id": "372"},
    "TEX": {"name": "Texas Stars", "color": "154734", "id": "380"},
    "ABB": {"name": "Abbotsford Canucks", "color": "00744F", "id": "440"},
    "BAK": {"name": "Bakersfield Condors", "color": "F47A38", "id": "402"},
    "CGY": {"name": "Calgary Wranglers", "color": "C8102E", "id": "444"},
    "CAL": {"name": "Calgary Wranglers", "color": "C8102E", "id": "444"},
    "CV":  {"name": "Coachella Valley", "color": "D32027", "id": "445"},
    "CVF": {"name": "Coachella Valley", "color": "D32027", "id": "445"},
    "COL": {"name": "Colorado Eagles", "color": "003087", "id": "419"},
    "HSK": {"name": "Henderson Silver Knights", "color": "111111", "id": "437"},
    "ONT": {"name": "Ontario Reign", "color": "111111", "id": "403"},
    "SD":  {"name": "San Diego Gulls", "color": "041E42", "id": "404"},
    "SJ":  {"name": "San Jose Barracuda", "color": "006D75", "id": "405"},
    "SJS": {"name": "San Jose Barracuda", "color": "006D75", "id": "405"},
    "TUC": {"name": "Tucson Roadrunners", "color": "8C2633", "id": "412"},
}

# ================= MASTER LEAGUE REGISTRY =================
LEAGUE_OPTIONS = [
    # --- PRO SPORTS ---
    {'id': 'nfl',           'label': 'NFL',                 'type': 'sport', 'default': True,  'fetch': {'path': 'football/nfl', 'team_params': {'limit': 100}, 'type': 'scoreboard'}},
    {'id': 'mlb',           'label': 'MLB',                 'type': 'sport', 'default': True,  'fetch': {'path': 'baseball/mlb', 'team_params': {'limit': 100}, 'type': 'scoreboard'}},
    {'id': 'nhl',           'label': 'NHL',                 'type': 'sport', 'default': True,  'fetch': {'path': 'hockey/nhl', 'team_params': {'limit': 100}, 'type': 'scoreboard'}},
    {'id': 'ahl',           'label': 'AHL',                 'type': 'sport', 'default': True,  'fetch': {'type': 'ahl_native'}},
    {'id': 'nba',           'label': 'NBA',                 'type': 'sport', 'default': True,  'fetch': {'path': 'basketball/nba', 'team_params': {'limit': 100}, 'type': 'scoreboard'}},
    # --- COLLEGE SPORTS ---
    {'id': 'ncf_fbs',       'label': 'NCAA (FBS)', 'type': 'sport', 'default': True,  'fetch': {'path': 'football/college-football', 'scoreboard_params': {'groups': '80'}, 'type': 'scoreboard'}},
    {'id': 'ncf_fcs',       'label': 'NCAA (FCS)', 'type': 'sport', 'default': True,  'fetch': {'path': 'football/college-football', 'scoreboard_params': {'groups': '81'}, 'type': 'scoreboard'}},

    # [NEW] March Madness (Group 100 isolates the Tournament)
    {'id': 'march_madness', 'label': 'March Madness', 'type': 'sport', 'default': True, 'fetch': {'path': 'basketball/mens-college-basketball', 'scoreboard_params': {'groups': '100', 'limit': '100'}, 'type': 'scoreboard'}},
    #{'id': 'ncaam',   'label': 'NCAA Basketball',   'type': 'sport', 'default': True, 'fetch': {'path': 'basketball/mens-college-basketball', 'scoreboard_params': {'limit': '100'}, 'type': 'scoreboard'}},

    # --- SOCCER ---
    {'id': 'soccer_epl',    'label': 'Premier League',       'type': 'sport', 'default': True, 'fetch': {'path': 'soccer/eng.1', 'team_params': {'limit': 50}, 'type': 'scoreboard'}},
    {'id': 'soccer_fa_cup','label': 'FA Cup',                 'type': 'sport', 'default': True, 'fetch': {'path': 'soccer/eng.fa', 'type': 'scoreboard'}},
    {'id': 'soccer_champ', 'label': 'Championship',             'type': 'sport', 'default': True, 'fetch': {'path': 'soccer/eng.2', 'team_params': {'limit': 50}, 'type': 'scoreboard'}},
    {'id': 'soccer_l1',     'label': 'League One',              'type': 'sport', 'default': True, 'fetch': {'path': 'soccer/eng.3', 'team_params': {'limit': 50}, 'type': 'scoreboard'}},
    {'id': 'soccer_l2',     'label': 'League Two',              'type': 'sport', 'default': True, 'fetch': {'path': 'soccer/eng.4', 'team_params': {'limit': 50}, 'type': 'scoreboard'}},
    {'id': 'soccer_wc',     'label': 'FIFA World Cup',         'type': 'sport', 'default': True, 'fetch': {'path': 'soccer/fifa.world', 'team_params': {'limit': 100}, 'type': 'scoreboard'}},
    {'id': 'soccer_champions_league', 'label': 'Champions League', 'type': 'sport', 'default': True, 'fetch': {'path': 'soccer/uefa.champions', 'team_params': {'limit': 50}, 'type': 'scoreboard'}},
    {'id': 'soccer_europa_league',    'label': 'Europa League',    'type': 'sport', 'default': True, 'fetch': {'path': 'soccer/uefa.europa', 'team_params': {'limit': 200}, 'type': 'scoreboard'}},
    {'id': 'soccer_mls',            'label': 'MLS',                 'type': 'sport', 'default': True, 'fetch': {'path': 'soccer/usa.1', 'team_params': {'limit': 100}, 'type': 'scoreboard'}},
    # --- OTHERS ---
    {'id': 'hockey_olympics', 'label': 'Olympic Hockey',   'type': 'sport', 'default': True,  'fetch': {'path': 'hockey/mens-olympic-hockey', 'type': 'scoreboard'}},
    # --- RACING ---
    {'id': 'f1',             'label': 'Formula 1',             'type': 'sport', 'default': True,  'fetch': {'path': 'racing/f1', 'type': 'leaderboard'}},
    {'id': 'nascar',         'label': 'NASCAR',                'type': 'sport', 'default': True,  'fetch': {'path': 'racing/nascar', 'type': 'leaderboard'}},
    # --- UTILITIES ---
    {'id': 'weather',       'label': 'Weather',                'type': 'util',  'default': True},
    {'id': 'clock',         'label': 'Clock',                 'type': 'util',  'default': True},
    # --- STOCKS ---
    {'id': 'stock_nasdaq_top50', 'label': 'NASDAQ Top 50', 'type': 'stock', 'default': False, 'stock_list': ["AAPL", "MSFT", "NVDA", "AMZN", "META", "GOOGL", "GOOG", "TSLA", "AVGO", "COST", "ADBE", "PEP", "CSCO", "AMD", "INTC", "TXN", "QCOM", "AMGN", "HON", "INTU", "CMCSA", "NFLX",
    "AMAT", "BKNG", "ADI", "LRCX", "MU", "PANW", "VRTX", "MDLZ", "REGN", "KLAC", "SNPS", "CDNS", "ABNB", "PYPL", "MAR", "ORLY", "MNST", "CTAS", "NXPI", "MRVL", "FTNT", "ROST", "IDXX", "MELI", "WDAY", "PCAR", "ODFL"]},
    {'id': 'stock_momentum',   'label': 'Momentum Stocks',         'type': 'stock', 'default': False, 'stock_list': ["TSLA", "COIN", "PLTR", "RBLX", "GME", "AMC", "SPCE", "LCID", "RIVN", "SNAP", "UAL", "UBER", "DASH", "SHOP", "DNUT", "GPRO", "CVNA", "AFRM", "UPST", "CVNA"]},
    {'id': 'stock_tech_ai',    'label': 'Tech / AI Stocks',        'type': 'stock', 'default': True,  'stock_list': ["AAPL", "MSFT", "NVDA", "GOOGL", "AMZN", "META", "TSM", "AVGO", "ORCL", "CRM", "AMD", "IBM", "INTC", "QCOM", "CSCO", "ADBE", "TXN", "AMAT", "INTU", "NOW", "MU"]},
    {'id': 'stock_energy',          'label': 'Energy Stocks',         'type': 'stock', 'default': False, 'stock_list': ["XOM", "CVX", "COP", "EOG", "SLB", "MPC", "PSX", "VLO", "OXY", "KMI", "HAL", "BKR", "HES", "DVN", "OKE", "WMB", "CTRA", "FANG", "TTE", "BP"]},
    {'id': 'stock_finance',         'label': 'Financial Stocks',       'type': 'stock', 'default': False, 'stock_list': ["JPM", "BAC", "WFC", "C", "GS", "MS", "BLK", "AXP", "V", "MA", "SCHW", "USB", "PNC", "TFC", "BK", "COF", "SPGI", "MCO", "CB", "PGR"]},
    {'id': 'stock_consumer',        'label': 'Consumer Stocks',       'type': 'stock', 'default': False, 'stock_list': ["WMT", "COST", "TGT", "HD", "LOW", "MCD", "SBUX", "CMG", "NKE", "LULU", "KO", "PEP", "PG", "CL", "KMB", "DIS", "NFLX", "CMCSA", "HLT", "MAR"]},
    {'id': 'stock_automotive', 'label': 'Automotive Stocks', 'type': 'stock', 'default': False, 'stock_list': ["TSLA", "GM", "F", "TM", "HMC", "STLA", "VWAGY", "BMWYY", "RIVN", "LCID", "NIO", "XPEV", "LI", "PSNY", "FCAU", "HYMTF", "TTM", "NSANY", "RNLSY", "PAG"]},
    {'id': 'stock_industrial', 'label': 'Industrial Stocks', 'type': 'stock', 'default': False, 'stock_list': ["CAT", "DE", "GE", "HON", "RTX", "LMT", "BA", "NOC", "GD", "MMM", "EMR", "ETN", "ITW", "PH", "CMI", "ROK", "IR", "PCAR", "CSX", "UNP"]}

]

# ================= DEFAULT STATE =================
DEFAULT_STATE = {
    'active_sports': { item['id']: item['default'] for item in LEAGUE_OPTIONS },
    'mode': 'all',
    'layout_mode': 'schedule',
    'my_teams': [],
    'current_games': [],
    'buffer_sports': [],
    'buffer_stocks': [],
    'all_teams_data': {},
    'debug_mode': False,
    'custom_date': None,
    'weather_city': "New York",
    'weather_lat': 40.7128,
    'weather_lon': -74.0060,
    'utc_offset': -5,
    'show_debug_options': False
}

DEFAULT_TICKER_SETTINGS = {
    "brightness": 100,
    "scroll_speed": 0.03,
    "scroll_seamless": True,
    "inverted": False,
    "panel_count": 2,
    "live_delay_mode": False,
    "live_delay_seconds": 45
}

# ================= LISTS & OVERRIDES =================
FBS_TEAMS = ["AF", "AKR", "ALA", "APP", "ARIZ", "ASU", "ARK", "ARST", "ARMY", "AUB", "BALL", "BAY", "BOIS", "BC", "BGSU", "BUF", "BYU", "CAL", "CMU", "CLT", "CIN", "CLEM", "CCU", "COLO", "CSU", "CONN", "DEL", "DUKE", "ECU", "EMU", "FAU", "FIU", "FLA", "FSU", "FRES", "GASO", "GAST", "GT", "UGA", "HAW", "HOU", "ILL", "IND", "IOWA", "ISU", "JXST", "JMU", "KAN", "KSU", "KENN", "KENT", "UK", "LIB", "ULL", "LT", "LOU", "LSU", "MAR", "MD", "MASS", "MEM", "MIA", "M-OH", "MICH", "MSU", "MTSU", "MINN", "MSST", "MIZ", "MOST", "NAVY", "NCST", "NEB", "NEV", "UNM", "NMSU", "UNC", "UNT", "NIU", "NU", "ND", "OHIO", "OSU", "OU", "OKST", "ODU", "MISS", "ORE", "ORST", "PSU", "PITT", "PUR", "RICE", "RUTG", "SAM", "SDSU", "SJSU", "SMU", "USA", "SC", "USF", "USM", "STAN", "SYR", "TCU", "TEM", "TENN", "TEX", "TA&M", "TXST", "TTU", "TOL", "TROY", "TULN", "TLSA", "UAB", "UCF", "UCLA", "ULM", "UMASS", "UNLV", "USC", "UTAH", "USU", "UTEP", "UTSA", "VAN", "UVA", "VT", "WAKE", "WASH", "WSU", "WVU", "WKU", "WMU", "WIS", "WYO"]
FCS_TEAMS = ["ACU", "AAMU", "ALST", "UALB", "ALCN", "UAPB", "APSU", "BCU", "BRWN", "BRY", "BUCK", "BUT", "CP", "CAM", "CARK", "CCSU", "CHSO", "UTC", "CIT", "COLG", "COLU", "COR", "DART", "DAV", "DAY", "DSU", "DRKE", "DUQ", "EIU", "EKU", "ETAM", "EWU", "ETSU", "ELON", "FAMU", "FOR", "FUR", "GWEB", "GTWN", "GRAM", "HAMP", "HARV", "HC", "HCU", "HOW", "IDHO", "IDST", "ILST", "UIW", "INST", "JKST", "LAF", "LAM", "LEH", "LIN", "LIU", "ME", "MRST", "MCN", "MER", "MERC", "MRMK", "MVSU", "MONM", "MONT", "MTST", "MORE", "MORG", "MUR", "UNH", "NHVN", "NICH", "NORF", "UNA", "NCAT", "NCCU", "UND", "NDSU", "NAU", "UNCO", "UNI", "NWST", "PENN", "PRST", "PV", "PRES", "PRIN", "URI", "RICH", "RMU", "SAC", "SHU", "SFPA", "SAM", "USD", "SELA", "SEMO", "SDAK", "SDST", "SCST", "SOU", "SIU", "SUU", "STMN", "SFA", "STET", "STO", "STBK", "TAR", "TNST", "TNTC", "TXSO", "TOW", "UCD", "UTM", "UTM", "UTRGV", "VAL", "VILL", "VMI", "WAG", "WEB", "WGA", "WCU", "WIU", "W&M", "WOF", "YALE", "YSU"]
OLYMPIC_HOCKEY_TEAMS = [
    {"abbr": "CAN", "logo": "https://a.espncdn.com/i/teamlogos/countries/500/can.png"},
    {"abbr": "USA", "logo": "https://a.espncdn.com/i/teamlogos/countries/500/usa.png"},
    {"abbr": "SWE", "logo": "https://a.espncdn.com/i/teamlogos/countries/500/swe.png"},
    {"abbr": "FIN", "logo": "https://a.espncdn.com/i/teamlogos/countries/500/fin.png"},
    {"abbr": "RUS", "logo": "https://a.espncdn.com/i/teamlogos/countries/500/rus.png"},
    {"abbr": "CZE", "logo": "https://a.espncdn.com/i/teamlogos/countries/500/cze.png"},
    {"abbr": "GER", "logo": "https://a.espncdn.com/i/teamlogos/countries/500/ger.png"},
    {"abbr": "SUI", "logo": "https://a.espncdn.com/i/teamlogos/countries/500/sui.png"},
    {"abbr": "SVK", "logo": "https://a.espncdn.com/i/teamlogos/countries/500/svk.png"},
    {"abbr": "LAT", "logo": "https://a.espncdn.com/i/teamlogos/countries/500/lat.png"},
    {"abbr": "DEN", "logo": "https://a.espncdn.com/i/teamlogos/countries/500/den.png"},
    {"abbr": "CHN", "logo": "https://a.espncdn.com/i/teamlogos/countries/500/chn.png"}
]

SOCCER_ABBR_OVERRIDES = {
    "Arsenal": "ARS", "Aston Villa": "AVL", "Bournemouth": "BOU", "Brentford": "BRE",
    "Brighton": "BHA", "Brighton & Hove Albion": "BHA", "Burnley": "BUR", "Chelsea": "CHE",
    "Crystal Palace": "CRY", "Everton": "EVE", "Fulham": "FUL", "Ipswich": "IPS", "Ipswich Town": "IPS",
    "Leeds": "LEE", "Leeds United": "LEE", "Leicester": "LEI", "Leicester City": "LEI",
    "Liverpool": "LIV", "Luton": "LUT", "Luton Town": "LUT", "Man City": "MCI", "Manchester City": "MCI",
    "Man Utd": "MUN", "Manchester United": "MUN", "Newcastle": "NEW", "Newcastle United": "NEW",
    "Nottm Forest": "NFO", "Nottingham Forest": "NFO", "Sheffield Utd": "SHU", "Sheffield United": "SHU",
    "Southampton": "SOU", "Spurs": "TOT", "Tottenham": "TOT", "Tottenham Hotspur": "TOT",
    "West Ham": "WHU", "West Ham United": "WHU", "Wolves": "WOL", "Wolverhampton": "WOL",
    "Blackburn": "BLA", "Blackburn Rovers": "BLA", "Bristol City": "BRC", "Cardiff": "CAR", "Cardiff City": "CAR",
    "Coventry": "COV", "Coventry City": "COV", "Derby": "DER", "Derby County": "DER",
    "Hull": "HUL", "Hull City": "HUL", "Middlesbrough": "MID", "Millwall": "MIL",
    "Norwich": "NOR", "Norwich City": "NOR", "Oxford": "OXF", "Oxford United": "OXF",
    "Plymouth": "PLY", "Plymouth Argyle": "PLY", "Portsmouth": "POR", "Preston": "PNE", "Preston North End": "PNE",
    "QPR": "QPR", "Queens Park Rangers": "QPR", "Sheffield Wed": "SHW", "Sheffield Wednesday": "SHW",
    "Stoke": "STK", "Stoke City": "STK", "Sunderland": "SUN", "Swansea": "SWA", "Swansea City": "SWA",
    "Watford": "WAT", "West Brom": "WBA", "West Bromwich Albion": "WBA",
    "Barnsley": "BAR", "Birmingham": "BIR", "Birmingham City": "BIR", "Blackpool": "BPL",
    "Bolton": "BOL", "Bolton Wanderers": "BOL", "Bristol Rovers": "BRR", "Burton": "BRT", "Burton Albion": "BRT",
    "Cambridge": "CAM", "Cambridge United": "CAM", "Charlton": "CHA", "Charlton Athletic": "CHA",
    "Crawley": "CRA", "Crawley Town": "CRA", "Exeter": "EXE", "Exeter City": "EXE",
    "Huddersfield": "HUD", "Huddersfield Town": "HUD", "Leyton Orient": "LEY", "Lincoln": "LIN", "Lincoln City": "LIN",
    "Mansfield": "MAN", "Mansfield Town": "MAN", "Northampton": "NOR", "Northampton Town": "NOR",
    "Peterborough": "PET", "Peterborough United": "PET", "Reading": "REA", "Rotherham": "ROT", "Rotherham United": "ROT",
    "Shrewsbury": "SHR", "Shrewsbury Town": "SHR", "Stevenage": "STE", "Stockport": "STO", "Stockport County": "STO",
    "Wigan": "WIG", "Wigan Athletic": "WIG", "Wrexham": "WRE", "Wycombe": "WYC", "Wycombe Wanderers": "WYC",
    "Accrington": "ACC", "Accrington Stanley": "ACC", "AFC Wimbledon": "WIM", "Barrow": "BRW",
    "Bradford": "BRA", "Bradford City": "BRA", "Bromley": "BRO", "Carlisle": "CAR", "Carlisle United": "CAR",
    "Cheltenham": "CHE", "Cheltenham Town": "CHE", "Chesterfield": "CHF", "Colchester": "COL", "Colchester United": "COL",
    "Crewe": "CRE", "Crewe Alexandra": "CRE", "Doncaster": "DON", "Doncaster Rovers": "DON",
    "Fleetwood": "FLE", "Fleetwood Town": "FLE", "Gillingham": "GIL", "Grimsby": "GRI", "Grimsby Town": "GRI",
    "Harrogate": "HAR", "Harrogate Town": "HAR", "MK Dons": "MKD", "Morecambe": "MOR",
    "Newport": "NEW", "Newport County": "NEW", "Notts Co": "NCO", "Notts County": "NCO",
    "Port Vale": "POR", "Salford": "SAL", "Salford City": "SAL", "Swindon": "SWI", "Swindon Town": "SWI",
    "Tranmere": "TRA", "Tranmere Rovers": "TRA", "Walsall": "WAL"
}

LOGO_OVERRIDES = {
    "NFL:HOU": "https://a.espncdn.com/i/teamlogos/nfl/500/hou.png", "NBA:HOU": "https://a.espncdn.com/i/teamlogos/nba/500/hou.png", "MLB:HOU": "https://a.espncdn.com/i/teamlogos/mlb/500/hou.png", "NCF_FBS:HOU": "https://a.espncdn.com/i/teamlogos/ncaa/500/248.png",
    "NFL:MIA": "https://a.espncdn.com/i/teamlogos/nfl/500/mia.png", "NBA:MIA": "https://a.espncdn.com/i/teamlogos/nba/500/mia.png", "MLB:MIA": "https://a.espncdn.com/i/teamlogos/mlb/500/mia.png", "NCF_FBS:MIA": "https://a.espncdn.com/i/teamlogos/ncaa/500/2390.png", "NCF_FBS:MIAMI": "https://a.espncdn.com/i/teamlogos/ncaa/500/2390.png",
    "NFL:IND": "https://a.espncdn.com/i/teamlogos/nfl/500/ind.png", "NBA:IND": "https://a.espncdn.com/i/teamlogos/nba/500/ind.png", "NCF_FBS:IND": "https://a.espncdn.com/i/teamlogos/ncaa/500/84.png",
    "NHL:WSH": "https://a.espncdn.com/guid/cbe677ee-361e-91b4-5cae-6c4c30044743/logos/secondary_logo_on_black_color.png", "NHL:WAS": "https://a.espncdn.com/guid/cbe677ee-361e-91b4-5cae-6c4c30044743/logos/secondary_logo_on_black_color.png",
    "NFL:WSH": "https://a.espncdn.com/i/teamlogos/nfl/500/wsh.png", "NFL:WAS": "https://a.espncdn.com/i/teamlogos/nfl/500/wsh.png", "NBA:WSH": "https://a.espncdn.com/i/teamlogos/nba/500/was.png", "NBA:WAS": "https://a.espncdn.com/i/teamlogos/nba/500/was.png",
    "MLB:WSH": "https://a.espncdn.com/i/teamlogos/mlb/500/wsh.png", "MLB:WAS": "https://a.espncdn.com/i/teamlogos/mlb/500/wsh.png", "NCF_FBS:WASH": "https://a.espncdn.com/i/teamlogos/ncaa/500/264.png",
    "NHL:SJS": "https://a.espncdn.com/i/teamlogos/nhl/500/sj.png", "NHL:NJD": "https://a.espncdn.com/i/teamlogos/nhl/500/nj.png", "NHL:TBL": "https://a.espncdn.com/i/teamlogos/nhl/500/tb.png", "NHL:LAK": "https://a.espncdn.com/i/teamlogos/nhl/500/la.png",
    "NHL:VGK": "https://a.espncdn.com/i/teamlogos/nhl/500/vgs.png", "NHL:VEG": "https://a.espncdn.com/i/teamlogos/nhl/500/vgs.png", "NHL:UTA": "https://a.espncdn.com/i/teamlogos/nhl/500/utah.png",
    "NCF_FBS:CAL": "https://a.espncdn.com/i/teamlogos/ncaa/500/25.png", "NCF_FBS:OSU": "https://a.espncdn.com/i/teamlogos/ncaa/500/194.png", "NCF_FBS:ORST": "https://a.espncdn.com/i/teamlogos/ncaa/500/204.png", "NCF_FCS:LIN": "https://a.espncdn.com/i/teamlogos/ncaa/500/2815.png", "NCF_FCS:LEH": "https://a.espncdn.com/i/teamlogos/ncaa/500/2329.png"
}
ABBR_MAPPING = {
    'SJS': 'SJ', 'TBL': 'TB', 'LAK': 'LA', 'NJD': 'NJ', 'VGK': 'VEG', 'UTA': 'UTAH', 'WSH': 'WSH', 'MTL': 'MTL', 'CHI': 'CHI',
    'NY': 'NYK', 'NO': 'NOP', 'GS': 'GSW', 'SA': 'SAS'
}

SOCCER_COLOR_FALLBACK = {
    "arsenal": "EF0107", "aston villa": "95BFE5", "bournemouth": "DA291C", "brentford": "E30613", "brighton": "0057B8",
    "chelsea": "034694", "crystal palace": "1B458F", "everton": "003399", "fulham": "FFFFFF", "ipswich": "3A64A3",
    "leicester": "0053A0", "liverpool": "C8102E", "manchester city": "6CABDD", "man city": "6CABDD",
    "manchester united": "DA291C", "man utd": "DA291C", "newcastle": "FFFFFF", "nottingham": "DD0000",
    "southampton": "D71920", "tottenham": "FFFFFF", "west ham": "7A263A", "whu": "7A263A", "wes": "7A263A", "wolves": "FDB913",
    "sunderland": "FF0000", "sheffield united": "EE2737", "burnley": "6C1D45", "luton": "F78F1E",
    "leeds": "FFCD00", "west brom": "122F67", "wba": "122F67", "watford": "FBEE23", "norwich": "FFF200", "hull": "F5A91D",
    "stoke": "E03A3E", "middlesbrough": "E03A3E", "coventry": "00AEEF", "preston": "FFFFFF", "bristol city": "E03A3E",
    "portsmouth": "001489", "derby": "FFFFFF", "blackburn": "009EE0", "sheffield wed": "0E00F0", "oxford": "F1C40F",
    "qpr": "0053A0", "swansea": "FFFFFF", "cardiff": "0070B5", "millwall": "001E4D", "plymouth": "003A26",
    "grimsby": "FFFFFF", "gri": "FFFFFF", "wrexham": "D71920", "birmingham": "0000FF", "huddersfield": "0072CE", "stockport": "005DA4",
    "lincoln": "D71920", "reading": "004494", "blackpool": "F68712", "peterborough": "005090",
    "charlton": "Dadd22", "bristol rovers": "003399", "shrewsbury": "0066CC", "leyton orient": "C70000",
    "mansfield": "F5A91D", "wycombe": "88D1F1", "bolton": "FFFFFF", "barnsley": "D71920", "rotherham": "D71920",
    "wigan": "0000FF", "exeter": "D71920", "crawley": "D71920", "northampton": "800000", "cambridge": "FDB913",
    "burton": "FDB913", "port vale": "FFFFFF", "walsall": "D71920", "doncaster": "D71920", "notts county": "FFFFFF",
    "gillingham": "0000FF", "mk dons": "FFFFFF", "chesterfield": "0000FF", "barrow": "FFFFFF", "bradford": "F5A91D",
    "afc wimbledon": "0000FF", "bromley": "000000", "colchester": "0000FF", "crewe": "D71920", "harrogate": "FDB913",
    "morecambe": "D71920", "newport": "F5A91D", "salford": "D71920", "swindon": "D71920", "tranmere": "FFFFFF",
    "barcelona": "A50044", "real madrid": "FEBE10", "atlético": "CB3524", "bayern": "DC052D", "dortmund": "FDE100",
    "psg": "004170", "juventus": "FFFFFF", "milan": "FB090B", "inter": "010E80", "napoli": "003B94",
    "ajax": "D2122E", "feyenoord": "FF0000", "psv": "FF0000", "benfica": "FF0000", "porto": "00529F",
    "sporting": "008000", "celtic": "008000", "rangers": "0000FF", "braga": "E03A3E", "sc braga": "E03A3E"
}

SPORT_DURATIONS = {
    'nfl': 195, 'ncf_fbs': 210, 'ncf_fcs': 195,
    'nba': 150, 'nhl': 150, 'mlb': 180, 'weather': 60, 'soccer': 115
}
