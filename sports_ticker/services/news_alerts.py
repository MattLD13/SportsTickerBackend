"""Breaking news items for the half-width banner.

A score alert takes the whole panel. News does not. It takes the left half and
lets the strip keep scrolling in the right half, so a trade never costs you the
scores you turned the board on for.

Two things write here. The MLB transaction fetcher writes trades it reads from
the league feed. The push route writes whatever a person sends it, which is how
the leagues with no feed get onto the board at all. Both produce the same item,
so the renderer never needs to know where one came from.

Items are held in a short ring buffer and handed out by age, the same way
``score_alerts`` works. A ticker de-duplicates by ``id``, so the same item can
be served to several boards, and to one board several times, without it showing
twice.
"""

import hashlib
import threading
import time

# News is not a score. It stays available far longer, because a trade is still
# worth reading ten minutes after it lands, and a run is not.
DEFAULT_MAX_AGE = 900.0

_MAX_ITEMS = 48

SPORTS = 'sports'
STOCKS = 'stocks'


def make_id(*parts):
    """A stable id for an item, so the same trade never fires twice."""
    raw = '|'.join(str(p) for p in parts)
    return hashlib.md5(raw.encode('utf-8')).hexdigest()[:16]


def pick_team_color(info, fallback='#8B93A3'):
    """A club colour the banner can actually draw.

    Some primaries are black. Pittsburgh's is. The banner lifts a dark colour by
    scaling its channels, and scaling black leaves black, so a black chip on a
    black banner is invisible. The alternate is tried first, which gives the
    Pirates their gold, and neutral grey is the last resort.
    """
    for key in ('color', 'alt_color'):
        c = str((info or {}).get(key) or '').strip().lstrip('#')
        if c and set(c) != {'0'}:
            return f"#{c}"
    return fallback


def build_item(kind, text, domain=SPORTS, sport='', from_abbr='', to_abbr='',
               from_color='', to_color='', teams=(), item_id=None, source=''):
    """Assemble one banner item.

    ``teams`` is what the followed-teams filter reads. A trade concerns two
    clubs, and a board that follows either one wants to see it, so both go in.
    """
    return {
        'id': item_id or make_id(kind, sport, from_abbr, to_abbr, text),
        'kind': str(kind or 'NEWS').upper()[:6],
        'domain': domain,
        'sport': str(sport or '').lower(),
        'from_abbr': str(from_abbr or '').upper()[:4],
        'to_abbr': str(to_abbr or '').upper()[:4],
        'from_color': from_color or '#8B93A3',
        'to_color': to_color or '#8B93A3',
        'text': str(text or '').strip(),
        'teams': [str(t).upper() for t in teams if t],
        'source': source,
        'ts': time.time(),
    }


class NewsAlertTracker:
    """Holds recent news items and hands them out by age."""

    def __init__(self):
        self._lock = threading.Lock()
        self._items = []
        self._seen = set()

    def add(self, item):
        """Store an item. Returns None when it has been seen before."""
        with self._lock:
            if item['id'] in self._seen:
                return None
            self._seen.add(item['id'])
            self._items.append(item)
            if len(self._items) > _MAX_ITEMS:
                dropped = self._items[:-_MAX_ITEMS]
                self._items = self._items[-_MAX_ITEMS:]
                # Forget the ids of items that aged out, or the set grows for
                # the life of the process.
                for old in dropped:
                    self._seen.discard(old['id'])
        return item

    def add_many(self, items):
        return [x for x in (self.add(i) for i in items) if x]

    def recent(self, domain=None, max_age=DEFAULT_MAX_AGE, delay=0.0):
        """Items released within ``max_age`` seconds, oldest first.

        ``delay`` matches the live-delay handling in ``score_alerts``: an item
        is held back by the same amount as the content it sits beside.
        """
        delay = max(0.0, float(delay or 0.0))
        now = time.time()
        released_after = now - delay
        expires_before = released_after - max_age
        with self._lock:
            return [
                dict(i) for i in self._items
                if expires_before <= i['ts'] <= released_after
                and (domain is None or i['domain'] == domain)
            ]

    def clear(self):
        with self._lock:
            self._items = []
            self._seen = set()


news_alerts = NewsAlertTracker()
