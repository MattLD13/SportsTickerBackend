"""Normalize ESPN's football down-and-distance block into ticker fields.

A live NFL competition's ``situation`` looks like this::

    {"down": 3, "distance": 2, "yardLine": 67,
     "downDistanceText": "3rd & 2 at CAR 33",
     "shortDownDistanceText": "3rd & 2",
     "possessionText": "CAR 33",
     "isRedZone": false, "possession": "29"}

Two details drive everything here:

* ``yardLine`` is absolute field position measured from the *home* team's goal
  line (0-100) — "CAR 33" with ARI at home is 67. It is not side-relative, so
  it must never be flipped by who has the ball.
* ``possessionText`` is the ball spot ("CAR 33"), not a team abbreviation.
  ``possession`` is the team id; the caller resolves it to an abbreviation.
"""

import time

from ..core import prune_cache

_ORDINALS = {1: '1st', 2: '2nd', 3: '3rd', 4: '4th'}

_SITUATION_CACHE_MAX = 512

_BLANK = {
    'downDist': '', 'downDistFull': '', 'ballOn': '',
    'down': None, 'yardsToGo': None, 'yardLine': None,
    'isGoalToGo': False, 'isRedZone': False, 'possessionTeam': '',
}


def _int_or_none(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def yard_line_from_text(text, home_abbr, away_abbr):
    """Absolute yard line (0 = home goal line) out of "... at CAR 33"."""
    text = str(text or '')
    if ' at ' not in text:
        return None
    tail = text.split(' at ', 1)[1].strip().split()
    if not tail:
        return None
    if len(tail) == 1:
        # Midfield is written without a side: "1st & 10 at 50".
        return 50 if _int_or_none(tail[0]) == 50 else None
    side, yard = tail[0].upper(), _int_or_none(tail[1])
    if yard is None:
        return None
    if side == str(home_abbr).upper():
        return yard
    if side == str(away_abbr).upper():
        return 100 - yard
    if side in ('MID', '50'):
        return 50
    return None


def normalize_football_situation(sit, poss_abbr='', home_abbr='', away_abbr='', halftime=False):
    """Return the situation fields the ticker renders, from ESPN's raw block."""
    sit = sit or {}
    home_abbr = str(home_abbr or '').upper()
    away_abbr = str(away_abbr or '').upper()
    poss_abbr = str(poss_abbr or '').upper()

    full_text = str(sit.get('downDistanceText') or '').strip()
    short_text = str(sit.get('shortDownDistanceText') or '').strip()
    down = _int_or_none(sit.get('down'))
    distance = _int_or_none(sit.get('distance'))

    yard_line = _int_or_none(sit.get('yardLine'))
    if yard_line is None:
        yard_line = yard_line_from_text(full_text, home_abbr, away_abbr)
    if yard_line is not None:
        yard_line = max(0, min(100, yard_line))

    # The offense attacks the far end zone: home drives toward 100, away toward 0.
    to_home_goal = None
    if poss_abbr and poss_abbr == away_abbr:
        to_home_goal = True
    elif poss_abbr and poss_abbr == home_abbr:
        to_home_goal = False

    yards_to_goal = None
    if yard_line is not None and to_home_goal is not None:
        yards_to_goal = yard_line if to_home_goal else 100 - yard_line

    goal_to_go = 'goal' in short_text.lower() or 'goal' in full_text.lower()
    if not goal_to_go and distance is not None and yards_to_goal is not None:
        goal_to_go = distance >= yards_to_goal

    # Derive the red zone rather than trusting the flag: the summary feed the
    # pinned/mode fetchers fall back on carries a drive object with no
    # isRedZone at all, and the flag disappears along with the rest of the
    # block between plays.
    red_zone = bool(sit.get('isRedZone'))
    if yards_to_goal is not None and yards_to_goal <= 20:
        red_zone = True

    if not short_text:
        if full_text:
            short_text = full_text.split(' at ')[0].strip()
        elif down in _ORDINALS and distance is not None:
            short_text = f"{_ORDINALS[down]} & {'Goal' if goal_to_go else distance}"

    ball_on = str(sit.get('possessionText') or '').strip()
    if not ball_on and ' at ' in full_text:
        ball_on = full_text.split(' at ', 1)[1].strip()

    if halftime:
        return dict(_BLANK, possessionTeam=poss_abbr)

    return {
        'downDist': short_text,        # "3rd & 2" — what the ticker shows
        'downDistFull': full_text,     # "3rd & 2 at CAR 33"
        'ballOn': ball_on,             # "CAR 33"
        'down': down,
        'yardsToGo': distance,
        'yardLine': yard_line,         # 0 = home goal line, 100 = away goal line
        'isGoalToGo': bool(goal_to_go),
        'isRedZone': red_zone,
        'possessionTeam': poss_abbr,
    }


def sticky_football_situation(cache, game_id, sit, state='', halftime=False):
    """Hold the last real down & distance so the ticker doesn't blink.

    ESPN drops the situation block between plays — timeouts, reviews, change of
    possession, the gap after a score — and the card would otherwise go blank
    for a poll or two. The last known value stands in until a new one arrives.
    It is only cleared where there genuinely is no down & distance: before
    kickoff, at halftime, and once the game is over.
    """
    key = str(game_id)
    if halftime or str(state).lower() in ('pre', 'post', 'final'):
        cache.pop(key, None)
        return dict(_BLANK, possessionTeam=sit.get('possessionTeam', ''))

    if sit.get('downDist'):
        cache.pop(key, None)   # re-insert so insertion order stays newest-last
        cache[key] = dict(sit, ts=time.time())
        prune_cache(cache, _SITUATION_CACHE_MAX)
        return sit

    cached = cache.get(key)
    if cached:
        return {k: v for k, v in cached.items() if k != 'ts'}
    return sit
