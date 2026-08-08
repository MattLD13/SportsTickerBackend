"""Company headlines for the stocks-mode banner.

Two sources, chosen by whether a Finnhub key is configured.

* **Finnhub** is the primary, because the quote fetcher already runs on those
  keys and its company-news endpoint is filtered by symbol at the source.
* **Yahoo's RSS** is the fallback and needs no key, which matches the way the
  quote fetcher already drops into simulation mode without one.

The fallback needs filtering that Finnhub does not. Yahoo's per-symbol feed is
sector-wide: a query for NVDA returns Cloudflare and Calumet headlines, and only
about a third of the feed names the company at all.

Naming a company is also not the same as being about it, so relevance is judged
twice. A cheap word rule runs always, and an optional model reads what survives.
See services/headline_filter.py.

One headline per symbol per poll. The feed carries twenty, and a board that
showed all of them would be a news ticker rather than a stock ticker.
"""

import email.utils
import re
import time

import requests

from ..services.headline_filter import keep_relevant
from ..services.news_alerts import STOCKS, build_item, make_id

FINNHUB_NEWS = 'https://finnhub.io/api/v1/company-news'
YAHOO_RSS = 'https://feeds.finance.yahoo.com/rss/2.0/headline?s={symbol}&region=US&lang=en-US'
YAHOO_SEARCH = 'https://query2.finance.yahoo.com/v1/finance/search?q={symbol}&quotesCount=1&newsCount=0'

HEADERS = {'User-Agent': 'Mozilla/5.0'}
TIMEOUT = 12

# Words that name a company in the abstract rather than this company.
_NAME_NOISE = {'corporation', 'corp', 'inc', 'incorporated', 'company', 'co',
               'holdings', 'group', 'the', 'plc', 'ltd', 'limited', 'class'}

_NAME_CACHE = {}          # symbol -> (timestamp, lowercase name words)
_NAME_TTL = 86400.0


def _company_words(symbol, session=None):
    """The distinctive words of a company's name, for matching a headline.

    "NVIDIA Corporation" reduces to {"nvidia"}. Without dropping the generic
    half, every headline holding the word "corporation" would match.
    """
    cached = _NAME_CACHE.get(symbol)
    if cached and (time.time() - cached[0]) < _NAME_TTL:
        return cached[1]
    words = set()
    try:
        get = (session or requests).get
        r = get(YAHOO_SEARCH.format(symbol=symbol), headers=HEADERS, timeout=TIMEOUT)
        if r.status_code == 200:
            quotes = r.json().get('quotes') or []
            name = str(quotes[0].get('shortname') or '') if quotes else ''
            words = {w for w in re.findall(r"[a-z']+", name.lower())
                     if len(w) > 2 and w not in _NAME_NOISE}
    except Exception:
        pass
    _NAME_CACHE[symbol] = (time.time(), words)
    return words


# How far into a headline the company may appear and still be its subject.
SUBJECT_WORDS = 4


def _is_about(headline, symbol, words):
    """True when the headline names the ticker or the company anywhere."""
    low = str(headline or '').lower()
    if re.search(rf'\b{re.escape(symbol.lower())}\b', low):
        return True
    return any(w in low for w in words)


def _is_subject(headline, symbol, words, limit=SUBJECT_WORDS):
    """True when the company sits near the front, where a subject sits.

    "AEye to Participate in J.P. Morgan Auto Conference" names the bank five
    words in and is about AEye. Naming a company is not the same as being about
    it, and position is the cheapest signal that tells the two apart.

    This is a rule and not comprehension, so it also drops a good headline such
    as "Tim Cook Says There's No Better Person to Take Over at Apple". The model
    layer recovers those. This is what runs when no model key is set.
    """
    head = ' '.join(str(headline or '').split()[:limit]).lower()
    if re.search(rf'\b{re.escape(symbol.lower())}\b', head):
        return True
    return any(w in head for w in words)


def _finnhub_news(symbol, api_key, session, since):
    """Finnhub filters by symbol at the source, so nothing else is needed."""
    day = 86400
    params = {
        'symbol': symbol,
        'from': time.strftime('%Y-%m-%d', time.localtime(since - day)),
        'to': time.strftime('%Y-%m-%d'),
        'token': api_key,
    }
    get = (session or requests).get
    r = get(FINNHUB_NEWS, params=params, headers=HEADERS, timeout=TIMEOUT)
    if r.status_code != 200:
        return []
    out = []
    for row in (r.json() or []):
        if not isinstance(row, dict):
            continue
        headline = str(row.get('headline') or '').strip()
        stamp = row.get('datetime')
        if not headline or not isinstance(stamp, (int, float)) or stamp < since:
            continue
        out.append((float(stamp), headline))
    return out


def _yahoo_news(symbol, session, since):
    """Yahoo needs the filtering Finnhub does its own."""
    get = (session or requests).get
    r = get(YAHOO_RSS.format(symbol=symbol), headers=HEADERS, timeout=TIMEOUT)
    if r.status_code != 200:
        return []
    words = _company_words(symbol, session)
    out = []
    for block in re.findall(r'<item>(.*?)</item>', r.text, re.S):
        title = re.search(r'<title>(.*?)</title>', block, re.S)
        pub = re.search(r'<pubDate>(.*?)</pubDate>', block, re.S)
        if not title:
            continue
        headline = re.sub(r'<!\[CDATA\[|\]\]>', '', title.group(1)).strip()
        try:
            stamp = email.utils.parsedate_to_datetime(pub.group(1)).timestamp() if pub else 0
        except Exception:
            stamp = 0
        if not headline or stamp < since:
            continue
        if not _is_about(headline, symbol, words):
            continue
        out.append((stamp, headline))
    return out


def fetch_stock_news(symbols, session=None, api_key=None, quote=None,
                     max_age_hours=6, limit=6):
    """Return banner items for recent company news.

    ``quote`` is an optional callable that returns the day's percentage move
    for a symbol. The banner draws it beside the ticker, because a headline
    without the move only tells half the story.
    """
    since = time.time() - max_age_hours * 3600

    # 1. Gather. A few per symbol, so the relevance pass has something to
    #    choose between rather than one headline to accept or reject.
    candidates = []
    for symbol in symbols:
        symbol = str(symbol).upper()
        try:
            rows = (_finnhub_news(symbol, api_key, session, since) if api_key
                    else _yahoo_news(symbol, session, since))
        except Exception as exc:
            print(f"[STOCK NEWS] {symbol} failed: {exc}")
            continue
        for stamp, headline in sorted(rows, key=lambda r: r[0], reverse=True)[:3]:
            candidates.append((stamp, symbol, headline))

    # 2. Judge relevance, but only on the keyless path. Finnhub filters by
    #    symbol at the source, so its headlines are already about the company.
    if candidates and not api_key:
        kept = keep_relevant([(s, h) for _, s, h in candidates], session)
        if kept is None:
            # No model, or the call failed. The word rule stands in.
            kept = {i for i, (_, s, h) in enumerate(candidates)
                    if _is_subject(h, s, _company_words(s, session))}
        candidates = [c for i, c in enumerate(candidates) if i in kept]

    # 3. One per symbol, the freshest that survived.
    best = {}
    for stamp, symbol, headline in sorted(candidates, key=lambda c: c[0], reverse=True):
        best.setdefault(symbol, (stamp, headline))

    items = []
    for symbol, (stamp, headline) in best.items():
        pct = None
        if quote:
            try:
                pct = quote(symbol)
            except Exception:
                pct = None

        item = build_item(
            kind='NEWS',
            text=headline,
            domain=STOCKS,
            to_abbr=symbol,
            teams=[symbol],
            item_id=make_id('stock', symbol, headline),
            source='finnhub' if api_key else 'yahoo-rss',
        )
        item['pct'] = pct
        items.append((stamp, item))

    items.sort(key=lambda pair: pair[0], reverse=True)
    return [item for _, item in items[:limit]]
