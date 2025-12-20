# valid_teams.py
# Updated for 2025 Season (including Delaware/Missouri State to FBS)

FBS_TEAMS = [
    # ACC
    "BC", "CAL", "CLEM", "DUKE", "FSU", "GT", "LOU", "MIA", "NCST", "UNC", 
    "PITT", "SMU", "STAN", "SYR", "UVA", "VT", "WAKE",
    # American (AAC)
    "ARMY", "UAB", "CLT", "ECU", "FAU", "MEM", "NAVY", "UNT", "RICE", 
    "USF", "TEM", "UTSA", "TUL", "TLSA", "WICH",
    # Big 12
    "ARIZ", "ASU", "BAY", "BYU", "CIN", "COLO", "HOU", "ISU", "KU", 
    "KSU", "OKST", "TCU", "TTU", "UCF", "UTAH", "WVU",
    # Big Ten
    "ILL", "IND", "IOWA", "MD", "MICH", "MSU", "MINN", "NEB", "NW", 
    "OSU", "ORE", "PSU", "PUR", "RUTG", "UCLA", "USC", "WASH", "WIS",
    # CUSA
    "DEL", "FIU", "JSU", "KENN", "LIB", "LT", "MTSU", "MSU", "NMSU", 
    "SHSU", "UTEP", "WKU", "MOST", 
    # MAC
    "AKR", "BALL", "BGSU", "BUF", "CMU", "EMU", "KENT", "M-OH", 
    "NIU", "OHIO", "TOL", "UMASS", "WMU",
    # Mountain West
    "AFA", "BOISE", "CSU", "FRES", "HAW", "NEV", "UNM", "SDSU", 
    "SJSU", "UNLV", "USU", "WYO", "ORST", "WSU", # Pac-12 leftovers usually grouped here or separate
    # SEC
    "ALA", "ARK", "AUB", "FLA", "UGA", "UK", "LSU", "MISS", "MSST", 
    "MIZ", "OU", "SC", "TENN", "TEX", "TAMU", "VAN",
    # Sun Belt
    "APP", "ARST", "CCU", "GASO", "GAST", "JM", "LA", "ULM", 
    "MRSH", "ODU", "USA", "USM", "TXST", "TROY",
    # Independents
    "ND", "UCONN",
    # Common ESPN Variations
    "WSH", "WSU", "ORST", "OSU", "MIA", "MISS", "MSST", "WKU", "ECU"
]

FCS_TEAMS = [
    # Big Sky
    "CP", "EWU", "IDHO", "IDST", "MONT", "MTST", "NAU", "UNCO", "PRST", 
    "SAC", "UCD", "WEB",
    # Big South-OVC
    "CHSO", "EIU", "GWEB", "LIN", "SEMO", "TNST", "TNTC", "UTM", "WIU",
    # CAA
    "ALB", "BRY", "CAMP", "DEL", "ELON", "HAMP", "ME", "MONM", "UNH", 
    "NCAT", "RICH", "URI", "SBU", "TOW", "VILL", "W&M",
    # Ivy League
    "BRWN", "CLMB", "CORN", "DART", "HARV", "PENN", "PRIN", "YALE",
    # MEAC
    "DSU", "HOW", "MORG", "NCCU", "NSU", "SCSU",
    # MVFC
    "ILST", "INST", "MOST", "MURR", "UND", "NDSU", "UNI", "USD", 
    "SDSU", "SIU", "YSU",
    # NEC
    "CCSU", "DUQ", "LIU", "MER", "RMU", "SHU", "SFU", "STO", "WAG", "MC",
    # Patriot
    "BUCK", "COLG", "FORD", "GTWN", "HC", "LAF", "LEH",
    # Pioneer
    "BUT", "DAV", "DAY", "DRKE", "MAR", "MORE", "PRES", "STTH", 
    "SAND", "STET", "VALP",
    # SoCon
    "CHAT", "CIT", "ETSU", "FUR", "MER", "SAM", "VMI", "WCU", "WOFF",
    # Southland
    "HCU", "UIW", "LAM", "MCNS", "NICH", "NSU", "SELA", "TAMC",
    # SWAC
    "AAMU", "ALST", "ALCN", "ARPB", "BCU", "FAMU", "GRAM", "JKST", 
    "MVSU", "PV", "SOU", "TSU",
    # UAC (ASUN-WAC)
    "ACU", "APSU", "UCA", "EKU", "UNA", "SUU", "TAR", "UTTC", "UWG"
]
