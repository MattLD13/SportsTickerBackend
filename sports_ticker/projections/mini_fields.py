"""Own Mini wire fields shared by backend projection and generated C++ filtering."""

SPORTS_FIELDS = {'sport': True,
 'competition_stage': True,
 'league': True,
 'away_logo_asset': True,
 'home_logo_asset': True,
 'away_abbr': True,
 'home_abbr': True,
 'away_score': True,
 'home_score': True,
 'away_color': True,
 'home_color': True,
 'status': True,
 'state': True,
 'baseball_inning': True,
 'away_rank': True,
 'home_rank': True,
 'away_seed': True,
 'home_seed': True,
 'situation': {'downDist': True,
               'activeTeam': True,
               'possession': True,
               'balls': True,
               'strikes': True,
               'outs': True,
               'onFirst': True,
               'onSecond': True,
               'onThird': True,
               'powerPlay': True,
               'powerPlayTeam': True,
               'manpower': {'scrollLabel': True,
                            'powerPlayLabel': True,
                            'penalties': [{'timeRemaining': True, 'jerseyNumber': True}]},
               'shootout': True,
               'isRedZone': True,
               'emptyNet': True,
               'emptyNetSide': True,
               'red_cards': [{'is_home': True}]}}


ASSET_FIELDS = {key: True for key in ("state", "asset_id", "sha256", "length", "width", "height", "format", "pipeline_version")}
SPORTS_FIELDS["away_logo_asset"] = ASSET_FIELDS
SPORTS_FIELDS["home_logo_asset"] = ASSET_FIELDS


def payload_filter():
    sports_item = {"is_shown": True, "id": True, "identifier": True, "key": True, "data": SPORTS_FIELDS}
    content = {"sports": [sports_item]}
    for family in ("weather", "music", "flights", "airports", "stock", "clock", "racing"):
        content[family] = [{"is_shown": True, "id": True, "data": True}]
    return {"meta": {"pairing": {"paired": True, "code": True},
            "update": {"version": True, "id": True, "expires_at": True}},
            "settings": {key: True for key in ("mode", "timezone", "scroll_speed", "brightness")}, "content": content}
