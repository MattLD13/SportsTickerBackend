"""Static lookup tables with no runtime logic or local imports."""

# ── Network request headers (used by fetchers) ──
HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Accept": "application/json",
    "Accept-Language": "en",
    "Referer": "https://www.fotmob.com/"
}

FOTMOB_LEAGUE_MAP = {
    'soccer_epl': 47, 'soccer_fa_cup': 132, 'soccer_champ': 48,
    'soccer_l1': 108, 'soccer_l2': 109, 'soccer_wc': 77,
    'soccer_champions_league': 42, 'soccer_europa_league': 73, 'soccer_mls': 130
}

TZ_OFFSETS = {
    "EST": -5, "EDT": -4, "CST": -6, "CDT": -5,
    "MST": -7, "MDT": -6, "PST": -8, "PDT": -7, "AST": -4, "ADT": -3
}

KNOTS_TO_MPH = 1.15078

# ── ICAO aircraft type code → human-readable name ──
_AIRCRAFT_TYPE_NAMES = {
    # Boeing 737
    'B731': 'Boeing 737-100', 'B732': 'Boeing 737-200', 'B733': 'Boeing 737-300',
    'B734': 'Boeing 737-400', 'B735': 'Boeing 737-500', 'B736': 'Boeing 737-600',
    'B737': 'Boeing 737-700', 'B738': 'Boeing 737-800', 'B739': 'Boeing 737-900',
    'B37M': 'Boeing 737 MAX 7', 'B38M': 'Boeing 737 MAX 8', 'B39M': 'Boeing 737 MAX 9',
    'B3XM': 'Boeing 737 MAX 10',
    # Boeing 747
    'B741': 'Boeing 747-100', 'B742': 'Boeing 747-200', 'B743': 'Boeing 747-300',
    'B744': 'Boeing 747-400', 'B748': 'Boeing 747-8', 'B74S': 'Boeing 747SP',
    # Boeing 757 / 767
    'B752': 'Boeing 757-200', 'B753': 'Boeing 757-300',
    'B762': 'Boeing 767-200', 'B763': 'Boeing 767-300', 'B764': 'Boeing 767-400',
    # Boeing 777
    'B772': 'Boeing 777-200', 'B77L': 'Boeing 777-200LR', 'B77W': 'Boeing 777-300ER',
    'B773': 'Boeing 777-300', 'B778': 'Boeing 777-8', 'B779': 'Boeing 777-9',
    # Boeing 787
    'B788': 'Boeing 787-8', 'B789': 'Boeing 787-9', 'B78X': 'Boeing 787-10',
    # Airbus A220
    'BCS1': 'Airbus A220-100', 'BCS3': 'Airbus A220-300',
    # Airbus A300 / A310
    'A30B': 'Airbus A300', 'A306': 'Airbus A300-600', 'A310': 'Airbus A310',
    # Airbus A318-A321
    'A318': 'Airbus A318', 'A319': 'Airbus A319', 'A320': 'Airbus A320',
    'A321': 'Airbus A321', 'A19N': 'Airbus A319neo', 'A20N': 'Airbus A320neo',
    'A21N': 'Airbus A321neo',
    # Airbus A330
    'A332': 'Airbus A330-200', 'A333': 'Airbus A330-300',
    'A338': 'Airbus A330-800neo', 'A339': 'Airbus A330-900neo',
    # Airbus A340
    'A342': 'Airbus A340-200', 'A343': 'Airbus A340-300',
    'A345': 'Airbus A340-500', 'A346': 'Airbus A340-600',
    # Airbus A350
    'A359': 'Airbus A350-900', 'A35K': 'Airbus A350-1000',
    # Airbus A380
    'A388': 'Airbus A380',
    # Embraer
    'E170': 'Embraer 170', 'E75L': 'Embraer 175', 'E75S': 'Embraer 175',
    'E190': 'Embraer 190', 'E195': 'Embraer 195',
    'E290': 'Embraer E190-E2', 'E295': 'Embraer E195-E2',
    # Bombardier / CRJ
    'CRJ1': 'CRJ-100', 'CRJ2': 'CRJ-200', 'CRJ7': 'CRJ-700', 'CRJ9': 'CRJ-900',
    'CRJX': 'CRJ-1000',
    # ATR / Turboprops
    'AT43': 'ATR 42-300', 'AT45': 'ATR 42-500', 'AT46': 'ATR 42-600',
    'AT72': 'ATR 72', 'AT76': 'ATR 72-600',
    'DH8A': 'Dash 8-100', 'DH8B': 'Dash 8-200', 'DH8C': 'Dash 8-300', 'DH8D': 'Dash 8-400',
    # Other common types
    'MD80': 'McDonnell Douglas MD-80', 'MD82': 'MD-82', 'MD83': 'MD-83',
    'MD88': 'MD-88', 'MD90': 'MD-90', 'MD11': 'MD-11',
    'DC10': 'DC-10', 'L101': 'Lockheed L-1011',
    'A225': 'Antonov An-225', 'A124': 'Antonov An-124',
    'C130': 'C-130 Hercules', 'C17': 'C-17 Globemaster',
    'GLF5': 'Gulfstream V', 'GLF6': 'Gulfstream G650', 'GLEX': 'Global Express',
    'LJ35': 'Learjet 35', 'LJ45': 'Learjet 45', 'LJ60': 'Learjet 60',
    'C560': 'Citation V', 'C680': 'Citation Sovereign', 'C750': 'Citation X',
    'E545': 'Embraer Legacy 450', 'E550': 'Embraer Praetor 600',
    'PC12': 'Pilatus PC-12', 'PC24': 'Pilatus PC-24',
    'BE20': 'Beechcraft King Air 200', 'BE30': 'Beechcraft King Air 350',
}


def normalize_aircraft_type(icao_code, fr24_model=None):
    """Return human-readable aircraft name. Prefers FR24 detail model, falls back to local table."""
    if fr24_model:
        return fr24_model
    if icao_code:
        return _AIRCRAFT_TYPE_NAMES.get(icao_code.upper(), icao_code.upper())
    return ''


FBS_TEAMS = {"AF", "AKR", "ALA", "APP", "ARIZ", "ASU", "ARK", "ARST", "ARMY", "AUB", "BALL", "BAY", "BOIS", "BC", "BGSU", "BUF", "BYU", "CAL", "CMU", "CLT", "CIN", "CLEM", "CCU", "COLO", "CSU", "CONN", "DEL", "DUKE", "ECU", "EMU", "FAU", "FIU", "FLA", "FSU", "FRES", "GASO", "GAST", "GT", "UGA", "HAW", "HOU", "ILL", "IND", "IOWA", "ISU", "JXST", "JMU", "KAN", "KSU", "KENN", "KENT", "UK", "LIB", "ULL", "LT", "LOU", "LSU", "MAR", "MD", "MASS", "MEM", "MIA", "M-OH", "MICH", "MSU", "MTSU", "MINN", "MSST", "MIZ", "MOST", "NAVY", "NCST", "NEB", "NEV", "UNM", "NMSU", "UNC", "UNT", "NIU", "NU", "ND", "OHIO", "OSU", "OU", "OKST", "ODU", "MISS", "ORE", "ORST", "PSU", "PITT", "PUR", "RICE", "RUTG", "SAM", "SDSU", "SJSU", "SMU", "USA", "SC", "USF", "USM", "STAN", "SYR", "TCU", "TEM", "TENN", "TEX", "TA&M", "TXST", "TTU", "TOL", "TROY", "TULN", "TLSA", "UAB", "UCF", "UCLA", "ULM", "UMASS", "UNLV", "USC", "UTAH", "USU", "UTEP", "UTSA", "VAN", "UVA", "VT", "WAKE", "WASH", "WSU", "WVU", "WKU", "WMU", "WIS", "WYO"}
FCS_TEAMS = {"ACU", "AAMU", "ALST", "UALB", "ALCN", "UAPB", "APSU", "BCU", "BRWN", "BRY", "BUCK", "BUT", "CP", "CAM", "CARK", "CCSU", "CHSO", "UTC", "CIT", "COLG", "COLU", "COR", "DART", "DAV", "DAY", "DSU", "DRKE", "DUQ", "EIU", "EKU", "ETAM", "EWU", "ETSU", "ELON", "FAMU", "FOR", "FUR", "GWEB", "GTWN", "GRAM", "HAMP", "HARV", "HC", "HCU", "HOW", "IDHO", "IDST", "ILST", "UIW", "INST", "JKST", "LAF", "LAM", "LEH", "LIN", "LIU", "ME", "MRST", "MCN", "MER", "MERC", "MRMK", "MVSU", "MONM", "MONT", "MTST", "MORE", "MORG", "MUR", "UNH", "NHVN", "NICH", "NORF", "UNA", "NCAT", "NCCU", "UND", "NDSU", "NAU", "UNCO", "UNI", "NWST", "PENN", "PRST", "PV", "PRES", "PRIN", "URI", "RICH", "RMU", "SAC", "SHU", "SFPA", "SAM", "USD", "SELA", "SEMO", "SDAK", "SDST", "SCST", "SOU", "SIU", "SUU", "STMN", "SFA", "STET", "STO", "STBK", "TAR", "TNST", "TNTC", "TXSO", "TOW", "UCD", "UTM", "UTM", "UTRGV", "VAL", "VILL", "VMI", "WAG", "WEB", "WGA", "WCU", "WIU", "W&M", "WOF", "YALE", "YSU"}

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
    "Tranmere": "TRA", "Tranmere Rovers": "TRA", "Walsall": "WAL",
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
    "NCF_FBS:CAL": "https://a.espncdn.com/i/teamlogos/ncaa/500/25.png", "NCF_FBS:OSU": "https://a.espncdn.com/i/teamlogos/ncaa/500/194.png", "NCF_FBS:ORST": "https://a.espncdn.com/i/teamlogos/ncaa/500/204.png", "NCF_FCS:LIN": "https://a.espncdn.com/i/teamlogos/ncaa/500/2815.png", "NCF_FCS:LEH": "https://a.espncdn.com/i/teamlogos/ncaa/500/2329.png",
    "MLB:SD": "https://a.espncdn.com/guid/4dec648c-3eb9-055c-aebc-2711f30975a0/logos/primary_logo_on_primary_color.png", "MARCH_MADNESS:IOWA": "https://a.espncdn.com/guid/b7840e2f-6236-e764-2cae-20286a0829e7/logos/primary_logo_on_black_color.png",
    "MLB:NYY": "https://raw.githubusercontent.com/MattLD13/PoopTracker/refs/heads/main/New_York_Yankees_logo.svg.png", "MLB:COL": "https://raw.githubusercontent.com/MattLD13/PoopTracker/refs/heads/main/Colorado_Rockies_logo.svg.png",
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
    "sporting": "008000", "celtic": "008000", "rangers": "0000FF", "braga": "E03A3E", "sc braga": "E03A3E",
}

# ── Nürburgring 24h / endurance racing ──────────────────────────────────────
# Manufacturer livery palettes: primary, secondary, accent + Wikimedia logo URL.
# Logo URLs use the stable commons.wikimedia.org/wiki/Special:FilePath redirect
# with ?width=80 to get a rasterised PNG at a fixed size.
# Empty string = no logo (HTML falls back to the coloured abbreviation badge).
_W = 'https://commons.wikimedia.org/wiki/Special:FilePath/'
RACING_MANUFACTURER_COLORS = {
    'porsche':       {'primary': '#FFD100', 'secondary': '#000000', 'accent': '#FFFFFF',  'text': '#000000', 'logo': f'{_W}Porsche_logo.svg?width=80'},
    'bmw':           {'primary': '#1C69AD', 'secondary': '#FFFFFF', 'accent': '#E32221',  'text': '#FFFFFF', 'logo': f'{_W}BMW.svg?width=80'},
    'bmw m':         {'primary': '#1C69AD', 'secondary': '#FFFFFF', 'accent': '#E32221',  'text': '#FFFFFF', 'logo': f'{_W}BMW.svg?width=80'},
    'mercedes':      {'primary': '#00D2BE', 'secondary': '#000000', 'accent': '#FFFFFF',  'text': '#000000', 'logo': f'{_W}Mercedes-Benz_Logo_2010.svg?width=80'},
    'mercedes-amg':  {'primary': '#00D2BE', 'secondary': '#000000', 'accent': '#C8A951',  'text': '#000000', 'logo': f'{_W}Mercedes-Benz_Logo_2010.svg?width=80'},
    'amg':           {'primary': '#00D2BE', 'secondary': '#000000', 'accent': '#C8A951',  'text': '#000000', 'logo': f'{_W}Mercedes-Benz_Logo_2010.svg?width=80'},
    'ferrari':       {'primary': '#DC0000', 'secondary': '#FFFFFF', 'accent': '#FFD700',  'text': '#FFFFFF', 'logo': f'{_W}Ferrari-Logo.svg?width=80'},
    'lamborghini':   {'primary': '#B8960C', 'secondary': '#1A1A1A', 'accent': '#FFFFFF',  'text': '#FFFFFF', 'logo': f'{_W}Lamborghini_Logo.svg?width=80'},
    'audi':          {'primary': '#BB0000', 'secondary': '#FFFFFF', 'accent': '#888888',  'text': '#FFFFFF', 'logo': f'{_W}Audi-Logo_2016.svg?width=80'},
    'mclaren':       {'primary': '#FF8000', 'secondary': '#000000', 'accent': '#0090D4',  'text': '#FFFFFF', 'logo': ''},
    'aston martin':  {'primary': '#006F62', 'secondary': '#CEAE56', 'accent': '#FFFFFF',  'text': '#FFFFFF', 'logo': f'{_W}Aston_Martin_logo.svg?width=80'},
    'ford':          {'primary': '#003087', 'secondary': '#FFFFFF', 'accent': '#C41230',  'text': '#FFFFFF', 'logo': f'{_W}Ford_logo_flat.svg?width=80'},
    'mustang':       {'primary': '#003087', 'secondary': '#FFFFFF', 'accent': '#C41230',  'text': '#FFFFFF', 'logo': f'{_W}Ford_logo_flat.svg?width=80'},
    'corvette':      {'primary': '#FEC306', 'secondary': '#C41230', 'accent': '#000000',  'text': '#000000', 'logo': ''},
    'chevrolet':     {'primary': '#D4AF37', 'secondary': '#C41230', 'accent': '#000000',  'text': '#000000', 'logo': f'{_W}Chevrolet_logo.svg?width=80'},
    'nissan':        {'primary': '#C3122F', 'secondary': '#FFFFFF', 'accent': '#888888',  'text': '#FFFFFF', 'logo': f'{_W}Nissan_2020_logo.svg?width=80'},
    'toyota':        {'primary': '#EB0A1E', 'secondary': '#FFFFFF', 'accent': '#222222',  'text': '#FFFFFF', 'logo': f'{_W}Toyota_carlogo.svg?width=80'},
    'lexus':         {'primary': '#1A1A1A', 'secondary': '#C8A951', 'accent': '#FFFFFF',  'text': '#FFFFFF', 'logo': f'{_W}Lexus_division_emblem.svg?width=80'},
    'honda':         {'primary': '#CC0000', 'secondary': '#FFFFFF', 'accent': '#555555',  'text': '#FFFFFF', 'logo': f'{_W}Honda.svg?width=80'},
    'acura':         {'primary': '#CC0000', 'secondary': '#FFFFFF', 'accent': '#888888',  'text': '#FFFFFF', 'logo': f'{_W}Acura_logo.svg?width=80'},
    'hyundai':       {'primary': '#002C5F', 'secondary': '#FFFFFF', 'accent': '#00AAD4',  'text': '#FFFFFF', 'logo': f'{_W}Hyundai_Motor_Company_logo.svg?width=80'},
    'alpine':        {'primary': '#0067FF', 'secondary': '#FFFFFF', 'accent': '#FF0033',  'text': '#FFFFFF', 'logo': f'{_W}Alpine_cars_logo.svg?width=80'},
    'renault':       {'primary': '#FFCD00', 'secondary': '#000000', 'accent': '#C41230',  'text': '#000000', 'logo': f'{_W}Renault_2021_Text_Logo.svg?width=80'},
    'seat':          {'primary': '#FF0000', 'secondary': '#FFFFFF', 'accent': '#222222',  'text': '#FFFFFF', 'logo': f'{_W}SEAT_logo.svg?width=80'},
    'cupra':         {'primary': '#B37F17', 'secondary': '#000000', 'accent': '#FFFFFF',  'text': '#FFFFFF', 'logo': ''},
    'bentley':       {'primary': '#2D6030', 'secondary': '#CEAE56', 'accent': '#FFFFFF',  'text': '#FFFFFF', 'logo': f'{_W}Bentley_logo.svg?width=80'},
    'maserati':      {'primary': '#131F6B', 'secondary': '#FFFFFF', 'accent': '#C8A951',  'text': '#FFFFFF', 'logo': f'{_W}Maserati_logo.svg?width=80'},
    'cadillac':      {'primary': '#002654', 'secondary': '#B8960C', 'accent': '#FFFFFF',  'text': '#FFFFFF', 'logo': f'{_W}Cadillac_logo.svg?width=80'},
    'peugeot':       {'primary': '#0082C3', 'secondary': '#FFFFFF', 'accent': '#222222',  'text': '#FFFFFF', 'logo': f'{_W}Peugeot_logo.svg?width=80'},
    'mazda':         {'primary': '#910037', 'secondary': '#FFFFFF', 'accent': '#888888',  'text': '#FFFFFF', 'logo': f'{_W}Mazda_logo.svg?width=80'},
    'subaru':        {'primary': '#0033A0', 'secondary': '#FFD700', 'accent': '#FFFFFF',  'text': '#FFFFFF', 'logo': f'{_W}Subaru_logo.svg?width=80'},
    'volkswagen':    {'primary': '#001E50', 'secondary': '#FFFFFF', 'accent': '#6E9ECC',  'text': '#FFFFFF', 'logo': f'{_W}Volkswagen_logo_2019.svg?width=80'},
    'vw':            {'primary': '#001E50', 'secondary': '#FFFFFF', 'accent': '#6E9ECC',  'text': '#FFFFFF', 'logo': f'{_W}Volkswagen_logo_2019.svg?width=80'},
    'lotus':         {'primary': '#005C23', 'secondary': '#FFD700', 'accent': '#000000',  'text': '#FFFFFF', 'logo': f'{_W}Lotus_logo.svg?width=80'},
    'jaguar':        {'primary': '#005A2B', 'secondary': '#CEAE56', 'accent': '#FFFFFF',  'text': '#FFFFFF', 'logo': f'{_W}Jaguar_Cars_logo.svg?width=80'},
    'mini':          {'primary': '#EB0A1E', 'secondary': '#FFFFFF', 'accent': '#222222',  'text': '#FFFFFF', 'logo': f'{_W}Mini_logo.svg?width=80'},
    'opel':          {'primary': '#FFED00', 'secondary': '#000000', 'accent': '#C41230',  'text': '#000000', 'logo': f'{_W}Opel_logo_2017.svg?width=80'},
    'alfa romeo':    {'primary': '#CE2028', 'secondary': '#002F6C', 'accent': '#FFFFFF',  'text': '#FFFFFF', 'logo': f'{_W}Alfa_Romeo_logo.svg?width=80'},
    'alfa':          {'primary': '#CE2028', 'secondary': '#002F6C', 'accent': '#FFFFFF',  'text': '#FFFFFF', 'logo': f'{_W}Alfa_Romeo_logo.svg?width=80'},
    'glickenhaus':   {'primary': '#C8102E', 'secondary': '#FFFFFF', 'accent': '#003087',  'text': '#FFFFFF', 'logo': ''},
    'ginetta':       {'primary': '#D01F2A', 'secondary': '#FFFFFF', 'accent': '#222222',  'text': '#FFFFFF', 'logo': ''},
    'radical':       {'primary': '#FF4500', 'secondary': '#000000', 'accent': '#FFD700',  'text': '#FFFFFF', 'logo': ''},
    'dodge':         {'primary': '#D40000', 'secondary': '#000000', 'accent': '#AAAAAA',  'text': '#FFFFFF', 'logo': f'{_W}Dodge_logo.svg?width=80'},
    'ktm':           {'primary': '#FF6600', 'secondary': '#000000', 'accent': '#FFFFFF',  'text': '#FFFFFF', 'logo': f'{_W}KTM-logo.svg?width=80'},
    'skoda':         {'primary': '#4BA82E', 'secondary': '#FFFFFF', 'accent': '#000000',  'text': '#FFFFFF', 'logo': f'{_W}Škoda_Auto_logo_since_2016.svg?width=80'},
    'abarth':        {'primary': '#CC0000', 'secondary': '#FFDD00', 'accent': '#222222',  'text': '#FFFFFF', 'logo': f'{_W}Abarth_logo.svg?width=80'},
    'lancia':        {'primary': '#003087', 'secondary': '#FFFFFF', 'accent': '#C41230',  'text': '#FFFFFF', 'logo': f'{_W}Lancia_logo.svg?width=80'},
    'pagani':        {'primary': '#C8A951', 'secondary': '#000000', 'accent': '#FFFFFF',  'text': '#000000', 'logo': ''},
}

# N24 / VLN race class colour palettes
RACING_CLASS_COLORS = {
    'SP9':       {'bg': '#CC2200', 'text': '#FFFFFF', 'label': 'GT3'},
    'SP9 GT3':   {'bg': '#CC2200', 'text': '#FFFFFF', 'label': 'GT3'},
    'SP9-GT3':   {'bg': '#CC2200', 'text': '#FFFFFF', 'label': 'GT3'},
    'LMGT3':     {'bg': '#CC2200', 'text': '#FFFFFF', 'label': 'LMGT3'},
    'SP8':       {'bg': '#C05000', 'text': '#FFFFFF', 'label': 'GTC'},
    'SP7':       {'bg': '#BB7700', 'text': '#FFFFFF', 'label': 'SP7'},
    'SP6':       {'bg': '#998800', 'text': '#FFFFFF', 'label': 'SP6'},
    'SPX':       {'bg': '#557700', 'text': '#FFFFFF', 'label': 'SPX'},
    'SP3T':      {'bg': '#007744', 'text': '#FFFFFF', 'label': 'SP3T'},
    'SP3':       {'bg': '#007744', 'text': '#FFFFFF', 'label': 'SP3'},
    'SP2T':      {'bg': '#005599', 'text': '#FFFFFF', 'label': 'SP2T'},
    'SP2':       {'bg': '#005599', 'text': '#FFFFFF', 'label': 'SP2'},
    'SP1':       {'bg': '#550099', 'text': '#FFFFFF', 'label': 'SP1'},
    'CUP5':      {'bg': '#880055', 'text': '#FFFFFF', 'label': 'CUP5'},
    'CUP3':      {'bg': '#775500', 'text': '#FFFFFF', 'label': 'CUP3'},
    'CUP2':      {'bg': '#335500', 'text': '#FFFFFF', 'label': 'CUP2'},
    'E1-XP':     {'bg': '#004488', 'text': '#FFFFFF', 'label': 'E1-XP'},
    'E2-SH':     {'bg': '#004455', 'text': '#FFFFFF', 'label': 'E2-SH'},
    'VT2':       {'bg': '#444444', 'text': '#FFFFFF', 'label': 'VT2'},
    'AT':        {'bg': '#334455', 'text': '#FFFFFF', 'label': 'AT'},
    'TCR':       {'bg': '#0055AA', 'text': '#FFFFFF', 'label': 'TCR'},
    'GT4':       {'bg': '#AA4400', 'text': '#FFFFFF', 'label': 'GT4'},
}

_RACING_DEFAULT_MFR   = {'primary': '#2A3A4A', 'secondary': '#4A6A8A', 'accent': '#AABBCC', 'text': '#FFFFFF', 'logo': ''}
_RACING_DEFAULT_CLASS = {'bg': '#333344', 'text': '#CCCCDD', 'label': '?'}

SPORT_DURATIONS = {
    'nfl': 195, 'ncf_fbs': 210, 'ncf_fcs': 195,
    'nba': 150, 'nhl': 150, 'mlb': 180, 'weather': 60, 'soccer': 115
}

# WMO weather condition codes → human-readable labels (used by FlightTracker.fetch_airport_weather)
WMO_DESCRIPTIONS = {
    0: "CLEAR SKY", 1: "MAINLY CLEAR", 2: "PARTLY CLOUDY", 3: "OVERCAST",
    45: "FOG", 48: "RIME FOG",
    51: "LIGHT DRIZZLE", 53: "DRIZZLE", 55: "HEAVY DRIZZLE",
    56: "FREEZING DRIZZLE", 57: "FREEZING DRIZZLE",
    61: "LIGHT RAIN", 63: "RAIN", 65: "HEAVY RAIN",
    66: "FREEZING RAIN", 67: "FREEZING RAIN",
    71: "LIGHT SNOW", 73: "SNOW", 75: "HEAVY SNOW",
    77: "SNOW GRAINS",
    80: "LIGHT SHOWERS", 81: "SHOWERS", 82: "HEAVY SHOWERS",
    85: "SNOW SHOWERS", 86: "HEAVY SNOW SHOWERS",
    95: "THUNDERSTORM", 96: "THUNDERSTORM/HAIL", 99: "THUNDERSTORM/HAIL",
}
