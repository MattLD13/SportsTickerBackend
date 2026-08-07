"""Read real trades from the league feeds.

MLB and the NFL are here. Neither the NHL nor the NBA publishes anything, so
those reach the banner through POST /api/news. See docs/news-banner.md.

The two leagues need different handling:

* MLB gives every field separated. Kind, player, old club and new club all
  arrive as data, and nothing is read out of a sentence.
* The NFL gives the acting club as data and the rest as English. The other club
  is named in the description, and that is safe to read only because club names
  are a closed set of 32. Matching "Philadelphia" against a known list is a
  lookup. It is not the same as guessing at a word, which is how every
  touchdown pass thrown by Kenny Pickett once became a PICK SIX.
"""

import re
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


# ── NFL ──────────────────────────────────────────────────────────────────────

ESPN_CORE = 'http://sports.core.api.espn.com/v2/sports/football/leagues/nfl'
ESPN_SITE = 'https://site.api.espn.com/apis/site/v2/sports/football/nfl'

_NFL_CACHE = {'ts': 0.0, 'by_id': {}, 'needles': []}


def _nfl_teams(session=None):
    """ESPN team id to abbreviation, plus the names to search a sentence for.

    Needles are sorted longest first so "New York Jets" wins over "New York",
    and both Giants and Jets stay distinguishable.
    """
    now = time.time()
    if _NFL_CACHE['by_id'] and (now - _NFL_CACHE['ts']) < _TEAM_TTL:
        return _NFL_CACHE['by_id'], _NFL_CACHE['needles']
    try:
        get = (session or requests).get
        r = get(f'{ESPN_SITE}/teams', headers=HEADERS, timeout=TIMEOUT)
        if r.status_code == 200:
            by_id, needles = {}, []
            for entry in r.json()['sports'][0]['leagues'][0]['teams']:
                team = entry.get('team') or {}
                abbr = str(team.get('abbreviation') or '').upper()
                if not abbr:
                    continue
                by_id[str(team.get('id'))] = abbr
                for field in ('displayName', 'location', 'name'):
                    value = str(team.get(field) or '').strip()
                    if value:
                        needles.append((value.lower(), abbr))
            if by_id:
                needles.sort(key=lambda n: len(n[0]), reverse=True)
                _NFL_CACHE.update({'by_id': by_id, 'needles': needles, 'ts': now})
    except Exception as exc:
        print(f"[TRANSACTIONS] NFL team map failed: {exc}")
    return _NFL_CACHE['by_id'], _NFL_CACHE['needles']


def _counterparty(description, needles, acting):
    """The other club in the sentence, matched against the closed set of 32."""
    low = str(description or '').lower()
    for needle, abbr in needles:
        if abbr != acting and needle in low:
            return abbr
    return ''


def _nfl_text(description):
    """Keep the traded piece, drop the club and anything bundled after it.

    ESPN writes unrelated moves into the same field: "Traded S Kyle Dugger to
    the Pittsburgh Steelers. Signed S John Saunders Jr. to the active roster."
    Only the first sentence is the trade.
    """
    text = str(description or '').split('.')[0]
    text = re.sub(r'^\s*traded\s+', '', text, flags=re.I)
    text = re.split(r'\s+to\s+(?:the\s+)?', text, maxsplit=1, flags=re.I)[0]
    return ' '.join(text.split()).strip()


def fetch_nfl_transactions(season=None, session=None, lookup_color=None,
                           days_back=2, pages=1, limit=500):
    """Return banner items for NFL trades.

    Trades are rare. A whole season carried seven, against 1276 transactions in
    total, so everything else here is a signing or a release and is roster churn
    rather than news.

    Both clubs file their own entry for one trade. Only the sending side is
    kept, which reads "Traded X to Y", because the receiving side reads
    "Received X from a trade with Y" and would draw the same deal backwards.

    ESPN returns newest first, so one page covers about seven weeks. Rows older
    than ``days_back`` are dropped: without that, the first run after a restart
    would put every trade of the season on the panel at once.
    """
    season = season or time.strftime('%Y')
    cutoff = ('' if days_back is None
              else time.strftime('%Y-%m-%d', time.localtime(time.time() - days_back * 86400)))

    rows = []
    try:
        get = (session or requests).get
        for page in range(1, max(1, pages) + 1):
            r = get(f'{ESPN_CORE}/seasons/{season}/transactions',
                    params={'limit': limit, 'page': page},
                    headers=HEADERS, timeout=TIMEOUT)
            if r.status_code != 200:
                break
            body = r.json()
            rows += body.get('items', []) or []
            if page >= int(body.get('pageCount') or 1):
                break
    except Exception as exc:
        print(f"[TRANSACTIONS] NFL fetch failed: {exc}")
        return []

    by_id, needles = _nfl_teams(session)
    items = []
    for row in rows:
        description = str(row.get('description') or '')
        if not re.match(r'\s*traded\b', description, re.I):
            continue
        if days_back is not None and str(row.get('date') or '')[:10] < cutoff:
            continue

        ref = str((row.get('team') or {}).get('$ref') or '')
        match = re.search(r'/teams/(\d+)', ref)
        acting = by_id.get(match.group(1)) if match else ''
        if not acting:
            continue

        other = _counterparty(description, needles, acting)
        if not other:
            continue

        from_color = to_color = ''
        if lookup_color:
            from_color = lookup_color('nfl', acting)
            to_color = lookup_color('nfl', other)

        items.append(build_item(
            kind='TRADE',
            text=_nfl_text(description),
            sport='nfl',
            from_abbr=acting,
            to_abbr=other,
            from_color=from_color,
            to_color=to_color,
            teams=[acting, other],
            item_id=make_id('nfl', row.get('date'), description),
            source='espn-core',
        ))
    return items
