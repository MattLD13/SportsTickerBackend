"""Read real trades from the league feeds.

All four leagues are here, and each publishes something different.

* MLB gives every field separated. Kind, player, old club and new club all
  arrive as data, and nothing is read out of a sentence.
* The NBA publishes a static file of every player movement since 2015. The kind
  of move, the receiving club, the player, and the date are all fields.
* The NFL gives the acting club as data and the rest as English.
* The NHL gives no transaction feed at all, but it tags its own stories. A
  `transactions` tag says a move happened and a `teamid` tag says who acted.

Where a club has to be read out of English, it is matched against the league's
own list of clubs. That is a lookup against a closed set, not a guess at a
word, which is what turned every touchdown pass thrown by Kenny Pickett into a
PICK SIX. A headline that does not resolve is skipped, so the failure is a
missing banner rather than a wrong one.
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


# ── NHL ──────────────────────────────────────────────────────────────────────

FORGE = 'https://forge-dapi.d3.nhle.com/v2/content/en-us/stories'
NHL_STANDINGS = 'https://api-web.nhle.com/v1/standings/now'
NHL_TEAMS = 'https://api.nhle.com/stats/rest/en/team'

_NHL_CACHE = {'ts': 0.0, 'by_id': {}, 'names': {}}


def _nhl_teams(session=None):
    """NHL team ids and club names, restricted to the 32 clubs that exist now.

    The stats endpoint lists 62 franchises, including ones folded a century
    ago. Left unfiltered, "Toronto" matches the 1918 Arenas and a Maple Leafs
    trade is drawn as TAN.
    """
    now = time.time()
    if _NHL_CACHE['by_id'] and (now - _NHL_CACHE['ts']) < _TEAM_TTL:
        return _NHL_CACHE['by_id'], _NHL_CACHE['names']
    try:
        get = (session or requests).get
        current, names = set(), {}
        r = get(NHL_STANDINGS, headers=HEADERS, timeout=TIMEOUT)
        if r.status_code != 200:
            return _NHL_CACHE['by_id'], _NHL_CACHE['names']
        for row in r.json().get('standings', []):
            tri = (row.get('teamAbbrev') or {}).get('default')
            if not tri:
                continue
            current.add(tri)
            for key in ('teamName', 'teamCommonName', 'placeName'):
                value = (row.get(key) or {}).get('default')
                if value:
                    names[value.lower()] = tri

        r = get(NHL_TEAMS, headers=HEADERS, timeout=TIMEOUT)
        by_id = {t['id']: t['triCode'] for t in (r.json().get('data') or [])
                 if r.status_code == 200 and t.get('triCode') in current}
        if by_id and names:
            _NHL_CACHE.update({'by_id': by_id, 'names': names, 'ts': now})
    except Exception as exc:
        print(f"[TRANSACTIONS] NHL team map failed: {exc}")
    return _NHL_CACHE['by_id'], _NHL_CACHE['names']


def _nhl_other_club(text, acting, names):
    """The club named in the headline, matched against the 32 that exist."""
    low = str(text or '').lower()
    for name in sorted(names, key=len, reverse=True):
        # Three letters or fewer would match inside ordinary words.
        if len(name) > 3 and name in low and names[name] != acting:
            return names[name]
    return ''


def _nhl_parse(title, acting, names):
    """Return ``(from_abbr, to_abbr, detail)`` for a trade headline.

    Three forms cover the league. NHL.com writes "Schmid traded to Panthers by
    Golden Knights". A club writes either "Canadiens acquire Pastujov from the
    Anaheim Ducks" or "Canadiens trade Gallagher to the Vancouver Canucks".

    Reading a headline is only safe here because both halves are closed sets:
    the club is one of 32, and the verb is one of two. Anything that does not
    fit is skipped, so a headline this cannot read costs a missed banner and
    never a wrong one.
    """
    title = str(title or '')

    explicit = re.search(r'^(.*?)\s+trade[d]?\s+to\s+(.+?)\s+by\s+(.+?)(?:\s+for\b|$)',
                         title, re.I)
    if explicit:
        player, to_part, from_part = explicit.groups()
        return (_nhl_other_club(from_part, '', names),
                _nhl_other_club(to_part, '', names),
                player.strip())

    if not acting:
        return '', '', ''

    inbound = re.search(r'\bacquires?\b(.*?)(?:\s+from\b|$)', title, re.I)
    if inbound:
        return _nhl_other_club(title, acting, names), acting, inbound.group(1).strip()

    outbound = re.search(r'\btrades?\b(.*?)(?:\s+to\b|$)', title, re.I)
    if outbound:
        return acting, _nhl_other_club(title, acting, names), outbound.group(1).strip()

    return '', '', ''


def _nhl_text(detail, title):
    """Trim the headline down to the piece that moved."""
    text = re.sub(r'\s*\|.*$', '', str(detail or '')).strip(' ,')
    text = re.sub(r'^(forward|defenseman|defenceman|goaltender|goalie|centre|center)\s+',
                  '', text, flags=re.I)
    if not text:
        text = re.sub(r'\s*\|.*$', '', str(title or ''))
    return ' '.join(text.split())[:90]


def fetch_nhl_transactions(days_back=2, session=None, lookup_color=None, pages=2):
    """Return banner items for recent NHL trades.

    The league publishes no transaction feed. It does publish its stories
    through a content API, and it tags them itself: a story carries a
    ``transactions`` tag and a ``teamid-N`` tag. That tag is the authority on
    what a story is about, so nothing here has to decide from prose whether a
    move happened. Only the two clubs and the direction come from the headline.

    Both clubs often publish the same trade, so one deal is kept per pair of
    clubs per day.
    """
    cutoff = ('' if days_back is None
              else time.strftime('%Y-%m-%d', time.localtime(time.time() - days_back * 86400)))

    stories = []
    try:
        get = (session or requests).get
        for page in range(max(1, pages)):
            # The URL is built by hand. This API takes "$limit" and "$skip",
            # and requests percent-encodes the dollar sign, which the server
            # then ignores: every page comes back as the same default 25 rows.
            r = get(f'{FORGE}?tags.slug=transactions&$limit=100&$skip={page * 100}',
                    headers=HEADERS, timeout=TIMEOUT)
            if r.status_code != 200:
                break
            batch = r.json().get('items', []) or []
            if not batch:
                break
            stories += batch
    except Exception as exc:
        print(f"[TRANSACTIONS] NHL fetch failed: {exc}")
        return []

    by_id, names = _nhl_teams(session)
    if not by_id:
        return []

    items, seen_pairs = [], set()
    for story in stories:
        date = str(story.get('contentDate') or '')[:10]
        if cutoff and date < cutoff:
            continue
        title = str(story.get('headline') or story.get('title') or '')
        if not re.search(r'\btrade[sd]?\b|\bacquires?\b', title, re.I):
            continue

        tags = [str(t.get('slug') or '') for t in (story.get('tags') or [])]
        team_id = next((int(t.split('-')[1]) for t in tags
                        if t.startswith('teamid-') and t.split('-')[1].isdigit()), None)
        acting = by_id.get(team_id, '')

        from_abbr, to_abbr, detail = _nhl_parse(title, acting, names)
        if not from_abbr or not to_abbr or from_abbr == to_abbr:
            continue

        pair = (date, frozenset((from_abbr, to_abbr)))
        if pair in seen_pairs:
            continue
        seen_pairs.add(pair)

        from_color = to_color = ''
        if lookup_color:
            from_color = lookup_color('nhl', from_abbr)
            to_color = lookup_color('nhl', to_abbr)

        items.append(build_item(
            kind='TRADE',
            text=_nhl_text(detail, title),
            sport='nhl',
            from_abbr=from_abbr,
            to_abbr=to_abbr,
            from_color=from_color,
            to_color=to_color,
            teams=[from_abbr, to_abbr],
            item_id=make_id('nhl', date, from_abbr, to_abbr),
            source='nhl-forge',
        ))
    return items


# ── NBA ──────────────────────────────────────────────────────────────────────

NBA_MOVEMENT = 'https://stats.nba.com/js/data/playermovement/NBA_Player_Movement.json'
NBA_TEAMS = 'https://site.api.espn.com/apis/site/v2/sports/basketball/nba/teams'

# stats.nba.com refuses a plain request. These are the headers its own site
# sends, and without them the file comes back as a block page.
NBA_HEADERS = {
    'User-Agent': 'Mozilla/5.0',
    'Referer': 'https://www.nba.com/',
    'Origin': 'https://www.nba.com',
    'x-nba-stats-origin': 'stats',
    'x-nba-stats-token': 'true',
}

_NBA_CACHE = {'ts': 0.0, 'names': {}}


def _nba_names(session=None):
    """Every club name form to an abbreviation, for the 30 current clubs."""
    now = time.time()
    if _NBA_CACHE['names'] and (now - _NBA_CACHE['ts']) < _TEAM_TTL:
        return _NBA_CACHE['names']
    try:
        get = (session or requests).get
        r = get(NBA_TEAMS, headers=HEADERS, timeout=TIMEOUT)
        if r.status_code == 200:
            names = {}
            for entry in r.json()['sports'][0]['leagues'][0]['teams']:
                team = entry.get('team') or {}
                abbr = str(team.get('abbreviation') or '').upper()
                if not abbr:
                    continue
                for field in ('displayName', 'name', 'location'):
                    value = str(team.get(field) or '').strip().lower()
                    if value:
                        names[value] = abbr
            if names:
                _NBA_CACHE.update({'names': names, 'ts': now})
    except Exception as exc:
        print(f"[TRANSACTIONS] NBA team map failed: {exc}")
    return _NBA_CACHE['names']


def _nba_club(text, names, exclude=''):
    """Match a club name in free text against the 30 that exist."""
    low = str(text or '').lower()
    for name in sorted(names, key=len, reverse=True):
        if len(name) > 2 and name in low and names[name] != exclude:
            return names[name]
    return ''


def fetch_nba_transactions(days_back=2, session=None, lookup_color=None):
    """Return banner items for recent NBA trades.

    The league publishes a static file of every player movement since 2015,
    with the kind of move, the club, the player, and the date as fields. Each
    trade row reads "<Club> received <Player> from <Other Club>", so the club
    on the row is always the receiving side and direction never has to be
    guessed. Only the origin club is read from the sentence, against the closed
    set of 30.

    One trade writes a row per piece, including draft considerations with no
    player at all, so one deal is kept per pair of clubs per day. Rows that name
    a player are preferred, because "Johni Broome" is a better banner than
    "draft consideration".
    """
    cutoff = ('' if days_back is None
              else time.strftime('%Y-%m-%d', time.localtime(time.time() - days_back * 86400)))

    try:
        get = (session or requests).get
        r = get(NBA_MOVEMENT, headers=NBA_HEADERS, timeout=30)
        if r.status_code != 200:
            return []
        rows = (r.json().get('NBA_Player_Movement') or {}).get('rows') or []
    except Exception as exc:
        print(f"[TRANSACTIONS] NBA fetch failed: {exc}")
        return []

    names = _nba_names(session)
    if not names:
        return []

    trades = [r for r in rows
              if str(r.get('Transaction_Type', '')).lower() == 'trade'
              and (not cutoff or str(r.get('TRANSACTION_DATE') or '')[:10] >= cutoff)]
    # A row naming a player wins the deduplication over a bare draft pick.
    trades.sort(key=lambda r: (str(r.get('TRANSACTION_DATE')), bool(r.get('PLAYER_SLUG'))),
                reverse=True)

    items, seen = [], set()
    for row in trades:
        date = str(row.get('TRANSACTION_DATE') or '')[:10]
        description = str(row.get('TRANSACTION_DESCRIPTION') or '')
        to_abbr = _nba_club(str(row.get('TEAM_SLUG') or '').replace('-', ' '), names)
        if not to_abbr:
            continue
        from_abbr = _nba_club(description.split(' from ')[-1], names, exclude=to_abbr)
        if not from_abbr or from_abbr == to_abbr:
            continue

        pair = (date, frozenset((from_abbr, to_abbr)))
        if pair in seen:
            continue
        seen.add(pair)

        player = str(row.get('PLAYER_SLUG') or '').replace('-', ' ').title()
        from_color = to_color = ''
        if lookup_color:
            from_color = lookup_color('nba', from_abbr)
            to_color = lookup_color('nba', to_abbr)

        items.append(build_item(
            kind='TRADE',
            text=player or 'draft consideration',
            sport='nba',
            from_abbr=from_abbr,
            to_abbr=to_abbr,
            from_color=from_color,
            to_color=to_color,
            teams=[from_abbr, to_abbr],
            item_id=make_id('nba', date, from_abbr, to_abbr),
            source='nba-playermovement',
        ))
    return items
