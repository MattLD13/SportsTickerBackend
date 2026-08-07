"""Read real trades from the league feeds.

Only MLB is here, and that is a coverage fact rather than an omission. The
league publishes its own transaction feed, free and without a key, and it gives
the four fields the banner needs already separated: what kind of move, which
player, which club he left, which club he joined. Nothing has to be read out of
a sentence.

No other league offers that today. See docs/news-banner.md for what each of the
others would need.
"""

import time

import requests

from ..services.news_alerts import build_item, make_id

MLB_API = 'https://statsapi.mlb.com/api/v1'
HEADERS = {'User-Agent': 'Mozilla/5.0'}
TIMEOUT = 12

# The kinds worth a banner. The feed also carries assignments to the minors,
# status changes, and outright releases, which are not news on a home ticker.
WANTED_TYPES = {
    'Trade': 'TRADE',
    'Signed as Free Agent': 'SIGNS',
    'Free Agent Signing': 'SIGNS',
}

# Team colours are already in the ticker's own lookup, so this only has to map
# an MLB team id onto the abbreviation the rest of the app uses.
_TEAM_CACHE = {'ts': 0.0, 'by_id': {}, 'by_name': {}}
_TEAM_TTL = 86400.0


def _team_maps(session=None):
    """MLB team ids and full names to abbreviations. Cached for a day.

    The names are needed as well as the ids: a trade's direction is only
    readable from the club named at the start of the sentence.
    """
    now = time.time()
    if _TEAM_CACHE['by_id'] and (now - _TEAM_CACHE['ts']) < _TEAM_TTL:
        return _TEAM_CACHE['by_id'], _TEAM_CACHE['by_name']
    try:
        get = (session or requests).get
        r = get(f'{MLB_API}/teams?sportId=1', headers=HEADERS, timeout=TIMEOUT)
        if r.status_code == 200:
            by_id, by_name = {}, {}
            for team in r.json().get('teams', []):
                abbr = str(team.get('abbreviation') or '').upper()
                name = str(team.get('name') or '').lower()
                if abbr:
                    by_id[team.get('id')] = abbr
                    if name:
                        by_name[name] = abbr
            if by_id:
                _TEAM_CACHE.update({'by_id': by_id, 'by_name': by_name, 'ts': now})
    except Exception as exc:
        print(f"[TRANSACTIONS] MLB team map failed: {exc}")
    return _TEAM_CACHE['by_id'], _TEAM_CACHE['by_name']


def _acting_team(description, by_name):
    """The club that made the move, which the feed names first.

    Direction cannot be taken from the rows. One trade writes a row per player
    and they run both ways: the Tigers and Padres deal carries Mize going out
    and Mayfield coming back. Whichever row is read first decides the arrow, and
    half the time it points against the sentence being displayed underneath.
    """
    low = str(description or '').lower()
    # Longest name first, so "Chicago White Sox" is not matched as "Chicago".
    for name in sorted(by_name, key=len, reverse=True):
        if low.startswith(name):
            return by_name[name]
    return ''


def _shorten(description, player, club_names=()):
    """Cut the league's sentence down to what fits two lines of the banner.

    The feed writes the whole deal from the acting club's side: "Detroit Tigers
    traded RHP Casey Mize and 3B Gage Workman to San Diego Padres for LHP Kash
    Mayfield." Both clubs are already in the header, so naming them again here
    spends characters the banner does not have.
    """
    text = str(description or '').strip()
    if not text:
        return player

    # Everything after the verb is the part that names players and pieces.
    lower = text.lower()
    for verb in (' traded ', ' signed ', ' claimed ', ' selected '):
        if verb in lower:
            text = text[lower.index(verb) + len(verb):]
            break

    # Drop "to San Diego Padres", leaving "... and 3B Gage Workman for LHP ...".
    for name in club_names:
        if not name:
            continue
        for phrase in (f' to {name}', f' from {name}', f' {name}'):
            idx = text.lower().find(phrase.lower())
            if idx >= 0:
                text = text[:idx] + text[idx + len(phrase):]

    return ' '.join(text.split()).rstrip('.').strip() or player


def fetch_mlb_transactions(days_back=2, session=None, lookup_color=None):
    """Return banner items for recent MLB trades and signings.

    One trade produces one row per player moved, so the Angels and Rangers deal
    above arrives three times over. Rows are grouped by their description, which
    is identical across a deal, and each group becomes a single banner.
    """
    end = time.strftime('%Y-%m-%d')
    start = time.strftime('%Y-%m-%d', time.localtime(time.time() - days_back * 86400))

    try:
        get = (session or requests).get
        r = get(f'{MLB_API}/transactions',
                params={'startDate': start, 'endDate': end},
                headers=HEADERS, timeout=TIMEOUT)
        if r.status_code != 200:
            return []
        rows = r.json().get('transactions', []) or []
    except Exception as exc:
        print(f"[TRANSACTIONS] MLB fetch failed: {exc}")
        return []

    by_id, by_name = _team_maps(session)
    abbr_to_name = {v: k for k, v in by_name.items()}

    # Group by the sentence. Every row of one deal carries the same one.
    grouped = {}
    for row in rows:
        kind = WANTED_TYPES.get(str(row.get('typeDesc') or ''))
        if not kind:
            continue
        key = (kind, str(row.get('description') or ''), str(row.get('date') or ''))
        grouped.setdefault(key, []).append(row)

    items = []
    for (kind, description, date), group in grouped.items():
        # Direction follows the sentence, not the rows. The acting club is
        # named first, and the detail underneath describes what it sent away,
        # so the arrow has to leave that club or the two disagree on screen.
        from_abbr = _acting_team(description, by_name)

        involved = set()
        for row in group:
            for side in ('fromTeam', 'toTeam'):
                abbr = by_id.get((row.get(side) or {}).get('id'))
                if abbr:
                    involved.add(abbr)
        involved.discard(from_abbr)
        to_abbr = sorted(involved)[0] if involved else ''

        if not from_abbr or not to_abbr:
            continue

        player = str((group[0].get('person') or {}).get('fullName') or '')
        from_color = to_color = ''
        if lookup_color:
            from_color = lookup_color('mlb', from_abbr)
            to_color = lookup_color('mlb', to_abbr)

        items.append(build_item(
            kind=kind,
            text=_shorten(description, player,
                          (abbr_to_name.get(from_abbr), abbr_to_name.get(to_abbr))),
            sport='mlb',
            from_abbr=from_abbr,
            to_abbr=to_abbr,
            from_color=from_color,
            to_color=to_color,
            teams=[from_abbr, to_abbr],
            item_id=make_id('mlb', date, description),
            source='mlb-statsapi',
        ))

    items.sort(key=lambda i: i['id'])
    return items
