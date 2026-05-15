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
