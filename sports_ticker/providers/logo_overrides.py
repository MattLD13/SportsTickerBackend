"""Correct known upstream team logo mappings."""

from __future__ import annotations

from types import MappingProxyType


LOGO_OVERRIDES = MappingProxyType({
    "NFL:HOU": "https://a.espncdn.com/i/teamlogos/nfl/500/hou.png",
    "NBA:HOU": "https://a.espncdn.com/i/teamlogos/nba/500/hou.png",
    "MLB:HOU": "https://a.espncdn.com/i/teamlogos/mlb/500/hou.png",
    "NCF_FBS:HOU": "https://a.espncdn.com/i/teamlogos/ncaa/500/248.png",
    "NFL:MIA": "https://a.espncdn.com/i/teamlogos/nfl/500/mia.png",
    "NBA:MIA": "https://a.espncdn.com/i/teamlogos/nba/500/mia.png",
    "MLB:MIA": "https://a.espncdn.com/i/teamlogos/mlb/500/mia.png",
    "NCF_FBS:MIA": "https://a.espncdn.com/i/teamlogos/ncaa/500/2390.png",
    "NCF_FBS:MIAMI": "https://a.espncdn.com/i/teamlogos/ncaa/500/2390.png",
    "NFL:IND": "https://a.espncdn.com/i/teamlogos/nfl/500/ind.png",
    "NBA:IND": "https://a.espncdn.com/i/teamlogos/nba/500/ind.png",
    "NCF_FBS:IND": "https://a.espncdn.com/i/teamlogos/ncaa/500/84.png",
    "NHL:WSH": "https://a.espncdn.com/guid/cbe677ee-361e-91b4-5cae-6c4c30044743/logos/secondary_logo_on_black_color.png",
    "NHL:WAS": "https://a.espncdn.com/guid/cbe677ee-361e-91b4-5cae-6c4c30044743/logos/secondary_logo_on_black_color.png",
    "NFL:WSH": "https://a.espncdn.com/i/teamlogos/nfl/500/wsh.png",
    "NFL:WAS": "https://a.espncdn.com/i/teamlogos/nfl/500/wsh.png",
    "NBA:WSH": "https://a.espncdn.com/i/teamlogos/nba/500/was.png",
    "NBA:WAS": "https://a.espncdn.com/i/teamlogos/nba/500/was.png",
    "MLB:WSH": "https://a.espncdn.com/i/teamlogos/mlb/500/wsh.png",
    "MLB:WAS": "https://a.espncdn.com/i/teamlogos/mlb/500/wsh.png",
    "NCF_FBS:WASH": "https://a.espncdn.com/i/teamlogos/ncaa/500/264.png",
    "NHL:SJS": "https://a.espncdn.com/i/teamlogos/nhl/500/sj.png",
    "NHL:NJD": "https://a.espncdn.com/i/teamlogos/nhl/500/nj.png",
    "NHL:TBL": "https://a.espncdn.com/i/teamlogos/nhl/500/tb.png",
    "NHL:LAK": "https://a.espncdn.com/i/teamlogos/nhl/500/la.png",
    "NHL:VGK": "https://a.espncdn.com/i/teamlogos/nhl/500/vgs.png",
    "NHL:VEG": "https://a.espncdn.com/i/teamlogos/nhl/500/vgs.png",
    "NHL:UTA": "https://a.espncdn.com/i/teamlogos/nhl/500/utah.png",
    "NCF_FBS:CAL": "https://a.espncdn.com/i/teamlogos/ncaa/500/25.png",
    "NCF_FBS:OSU": "https://a.espncdn.com/i/teamlogos/ncaa/500/194.png",
    "NCF_FBS:ORST": "https://a.espncdn.com/i/teamlogos/ncaa/500/204.png",
    "NCF_FCS:LIN": "https://a.espncdn.com/i/teamlogos/ncaa/500/2815.png",
    "NCF_FCS:LEH": "https://a.espncdn.com/i/teamlogos/ncaa/500/2329.png",
    "MLB:SD": "https://a.espncdn.com/guid/4dec648c-3eb9-055c-aebc-2711f30975a0/logos/primary_logo_on_primary_color.png",
    "MARCH_MADNESS:IOWA": "https://a.espncdn.com/guid/b7840e2f-6236-e764-2cae-20286a0829e7/logos/primary_logo_on_black_color.png",
    "MLB:NYY": "https://raw.githubusercontent.com/MattLD13/PoopTracker/refs/heads/main/New_York_Yankees_logo.svg.png",
    "MLB:COL": "https://raw.githubusercontent.com/MattLD13/PoopTracker/refs/heads/main/Colorado_Rockies_logo.svg.png",
})


def corrected_logo(league: str, abbreviation: str, source_url: str | None) -> str | None:
    """Return the approved logo URL for one league and team."""

    key = f"{str(league).strip().upper()}:{str(abbreviation).strip().upper()}"
    return LOGO_OVERRIDES.get(key, source_url)


__all__ = ["LOGO_OVERRIDES", "corrected_logo"]
