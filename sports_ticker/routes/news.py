"""Push a news banner onto the board by hand.

Only MLB publishes a transaction feed that names both clubs. The NHL, the NBA,
and the NFL do not, so for those leagues there is nothing to read and nothing to
detect. This route is the answer for them: you send the four fields the banner
draws, and it appears. See docs/news-banner.md.

It is also how anything the fetchers will never know about gets on screen, such
as a signing reported before the league posts it.
"""

from flask import jsonify, request

from ..routes_runtime import app
from ..core import state, tickers, team_is_followed
from ..services.news_alerts import SPORTS, STOCKS, build_item, news_alerts, pick_team_color
from ..workers import fetcher

_ALLOWED_DOMAINS = (SPORTS, STOCKS)


def _team_color(sport, abbr, fallback='#8B93A3'):
    """The club's own colour, from the same lookup the scoreboard cards use."""
    if not abbr:
        return fallback
    try:
        info = fetcher.lookup_team_info_from_cache(str(sport).lower(), str(abbr).upper())
        return pick_team_color(info, fallback)
    except Exception:
        return fallback


@app.route('/api/news', methods=['GET', 'POST'])
def api_news():
    """GET lists the recent banners. POST adds one.

    POST body (JSON):
      kind    TRADE, SIGNS, or NEWS. Drawn in the header tab.
      text    The detail. Two lines for a trade, three for stock news.
      sport   League key, such as nhl. Sets which teams the filter matches.
      from    Abbreviation the player left. Use FA for a free agent.
      to      Abbreviation the player joined. Required for a trade.
      domain  sports (default) or stocks. Decides which mode shows it.
      symbol  Stocks only. Drawn instead of the two clubs.

    Colours are resolved from the ticker's own team lookup, so a caller only
    sends abbreviations.
    """
    if request.method == 'GET':
        domain = request.args.get('domain')
        return jsonify({'status': 'ok', 'news': news_alerts.recent(domain=domain)})

    body = request.json or {}
    text = str(body.get('text') or '').strip()
    if not text:
        return jsonify({'status': 'error', 'message': 'text is required'}), 400

    domain = str(body.get('domain') or SPORTS).lower()
    if domain not in _ALLOWED_DOMAINS:
        return jsonify({
            'status': 'error',
            'message': f"domain must be one of {list(_ALLOWED_DOMAINS)}",
        }), 400

    sport = str(body.get('sport') or '').lower()
    from_abbr = str(body.get('from') or '').upper()
    to_abbr = str(body.get('to') or '').upper()
    symbol = str(body.get('symbol') or '').upper()

    if domain == SPORTS and not to_abbr:
        return jsonify({'status': 'error', 'message': 'to is required for a sports item'}), 400
    if domain == STOCKS and not symbol:
        return jsonify({'status': 'error', 'message': 'symbol is required for a stocks item'}), 400

    item = build_item(
        kind=body.get('kind') or ('NEWS' if domain == STOCKS else 'TRADE'),
        text=text,
        domain=domain,
        sport=sport,
        from_abbr=from_abbr,
        to_abbr=to_abbr or symbol,
        from_color=_team_color(sport, from_abbr),
        to_color=_team_color(sport, to_abbr),
        teams=[a for a in (from_abbr, to_abbr, symbol) if a and a != 'FA'],
        source='push',
    )
    stored = news_alerts.add(item)
    if stored is None:
        return jsonify({'status': 'duplicate', 'item': item}), 200

    # Say which boards will show it, rather than leaving the caller to guess
    # why nothing happened.
    targets = []
    for tid, rec in tickers.items():
        followed = rec.get('my_teams')
        followed = set(state.get('my_teams', []) if followed is None else followed)
        if domain == SPORTS and not any(
                team_is_followed(followed, sport, a) for a in item['teams']):
            continue
        targets.append(tid)

    return jsonify({
        'status': 'ok',
        'item': stored,
        'tickers_following': targets,
        'note': 'Shown only while the ticker is in a matching mode.',
    })
