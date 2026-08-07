"""Detect scoring plays and describe what actually happened.

The scoreboard feeds never say "grand slam" — they say the score went from 3 to
7 and, separately, carry a sentence about the last play. Neither half is enough
on its own: the play text is missing or stale as often as it is present, and a
bare +4 could be two homers in a poll gap. Reading them together is what turns
a number change into "GRAND SLAM".

Detection lives here rather than in the fetchers because it needs memory across
polls, and the sports buffer is rebuilt from scratch every five seconds. The
tracker keeps the previous score per game id and emits one alert per increase.

Alerts are held in a short ring buffer and handed out by age. ``/data`` filters
them to a ticker's followed teams; the ticker de-duplicates by ``id``, so the
same alert can be served to several devices, and to one device several times,
without it firing twice.
"""

import re
import threading
import time

# How many alerts to keep. A busy Sunday slate produces a few dozen scores an
# hour across all leagues, and consumers only ever ask for the last minute.
_MAX_ALERTS = 64

# An alert older than this is never served. It has to outlast a ticker's poll
# interval and a brief network outage, but stay short enough that a board which
# was unplugged doesn't celebrate a touchdown from ten minutes ago on boot.
DEFAULT_MAX_AGE = 45.0

# States in which a score change is a real scoring play. Corrections and stat
# fixes land on finished games, and a pre-game 0-0 is not a shutout in progress.
_LIVE_STATES = frozenset({'in', 'half', 'crit'})

# Sports where a 1-point change is almost always the conversion that follows a
# touchdown rather than an event worth its own full-screen takeover.
_CONVERSION_WINDOW = 90.0


def _int_or_none(value):
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def normalize_last_play(raw, home_abbr='', away_abbr='', home_id=None, away_id=None):
    """Flatten ESPN's ``situation.lastPlay`` into the fields the describer uses."""
    if not isinstance(raw, dict):
        return {}

    type_obj = raw.get('type') if isinstance(raw.get('type'), dict) else {}
    team_obj = raw.get('team') if isinstance(raw.get('team'), dict) else {}
    team_id = str(team_obj.get('id', '') or '')

    team_abbr = ''
    if team_id and str(home_id or '') == team_id:
        team_abbr = str(home_abbr).upper()
    elif team_id and str(away_id or '') == team_id:
        team_abbr = str(away_abbr).upper()

    athlete = ''
    for entry in (raw.get('athletesInvolved') or []):
        if isinstance(entry, dict):
            athlete = str(entry.get('shortName') or entry.get('displayName') or '').strip()
            if athlete:
                break

    return {
        'text': str(raw.get('text') or '').strip(),
        'type': str(type_obj.get('text') or type_obj.get('abbreviation') or '').strip(),
        'team': team_abbr,
        'athlete': athlete,
        'score_value': _int_or_none(raw.get('scoreValue')),
    }


def _last_name(full_name):
    """"Aaron Judge" -> "JUDGE". The panel has room for one word, not two."""
    parts = [p for p in str(full_name or '').replace('.', ' ').split() if p]
    if not parts:
        return ''
    return parts[-1].upper()[:12]


def _describe_baseball(delta, play):
    text = f"{play.get('text', '')} {play.get('type', '')}".lower()
    if 'grand slam' in text or ('home run' in text and delta >= 4) or ('homer' in text and delta >= 4):
        return 'grand_slam', 'GRAND SLAM'
    if 'home run' in text or 'homer' in text or 'homered' in text:
        if delta >= 3:
            return 'three_run_hr', '3-RUN HOMER'
        if delta == 2:
            return 'two_run_hr', '2-RUN HOMER'
        return 'solo_hr', 'SOLO HOMER'
    if 'sacrifice fly' in text or 'sac fly' in text:
        return 'sac_fly', 'SAC FLY'
    if 'sacrifice bunt' in text or 'sac bunt' in text:
        return 'sac_bunt', 'SAC BUNT'

    # Hits come before the error and wild-pitch checks. ESPN writes the whole
    # play in one sentence, so a clean RBI single reads "Dingler singled to
    # right, Torres scored on throwing error by right fielder Ward" when a
    # second runner takes an extra base. An 'error' test placed first calls
    # that play RUN ON ERROR, which is the wrong name for a single.
    #
    # The patterns need word boundaries. "grounded into double play" contains
    # "double", and "to second" appears in almost every line.
    for pattern, kind, noun in (
        (r'\btripled\b|\btriple to\b', 'rbi_triple', 'TRIPLE'),
        (r'\bdoubled\b|\bdouble to\b', 'rbi_double', 'DOUBLE'),
        (r'\bsingled\b|\bsingle to\b', 'rbi_single', 'SINGLE'),
    ):
        if re.search(pattern, text):
            return kind, (f"{delta}-RUN {noun}" if delta > 1 else f"RBI {noun}")

    if 'wild pitch' in text:
        return 'wild_pitch', 'WILD PITCH'
    if 'passed ball' in text:
        return 'passed_ball', 'PASSED BALL'
    if 'balk' in text:
        return 'balk', 'BALK'
    if 'walked' in text:
        return 'walk_in', 'WALKED IN'

    # Only when the run itself is charged to the error. A runner who takes an
    # extra base on a throw ("Jarvis safe at second on error") did not score
    # on it, and that play is a plain run.
    if re.search(r'scored on [^,]*\berror\b', text):
        return 'error', 'RUN ON ERROR'

    if delta >= 2:
        return 'runs', f"{delta} RUNS SCORE"
    return 'run', 'RUN SCORES'


def _describe_football(delta, play):
    text = f"{play.get('type', '')} {play.get('text', '')}".lower()
    if 'safety' in text:
        return 'safety', 'SAFETY'
    if 'interception return touchdown' in text or 'pick' in text and 'touchdown' in text:
        return 'pick_six', 'PICK SIX'
    if 'fumble return touchdown' in text or 'fumble recovery touchdown' in text:
        return 'fumble_td', 'FUMBLE RETURN TD'
    if 'kickoff return touchdown' in text:
        return 'kick_return_td', 'KICK RETURN TD'
    if 'punt return touchdown' in text:
        return 'punt_return_td', 'PUNT RETURN TD'
    if 'rushing touchdown' in text or ('touchdown' in text and 'rush' in text):
        return 'rushing_td', 'RUSHING TD'
    if 'passing touchdown' in text or ('touchdown' in text and ('pass' in text or 'reception' in text)):
        return 'passing_td', 'PASSING TD'
    if delta >= 6:
        return 'touchdown', 'TOUCHDOWN'
    if delta == 3:
        return 'field_goal', 'FIELD GOAL'
    if delta == 2:
        if 'two-point' in text or 'two point' in text:
            return 'two_point', '2-PT CONVERSION'
        return 'safety', 'SAFETY'
    return 'extra_point', 'EXTRA POINT'


def _describe_hockey(delta, play):
    strength = str(play.get('strength', '')).lower()
    modifier = str(play.get('modifier', '')).lower()
    text = f"{play.get('type', '')} {play.get('text', '')}".lower()
    goals_to_date = _int_or_none(play.get('goals_to_date'))

    if goals_to_date == 3:
        return 'hat_trick', 'HAT TRICK'
    if 'empty-net' in modifier or 'empty net' in text:
        return 'empty_net', 'EMPTY NET GOAL'
    if strength == 'pp' or 'power play' in text or 'powerplay' in text:
        return 'power_play', 'POWER PLAY GOAL'
    if strength == 'sh' or 'shorthanded' in text or 'short-handed' in text:
        return 'shorthanded', 'SHORTHANDED GOAL'
    if 'penalty shot' in text:
        return 'penalty_shot', 'PENALTY SHOT GOAL'
    return 'goal', 'GOAL'


def _describe_basketball(delta, play):
    text = f"{play.get('type', '')} {play.get('text', '')}".lower()
    if delta >= 3:
        return 'three', '3-POINTER'
    if delta == 2:
        if 'dunk' in text:
            return 'dunk', 'SLAM DUNK'
        if 'layup' in text:
            return 'layup', 'LAYUP'
        return 'bucket', 'BUCKET'
    return 'free_throw', 'FREE THROW'


def _describe_soccer(delta, play):
    text = f"{play.get('type', '')} {play.get('text', '')}".lower()
    if 'own goal' in text:
        return 'own_goal', 'OWN GOAL'
    if 'penalty' in text:
        return 'penalty_goal', 'PENALTY GOAL'
    return 'goal', 'GOAL'


def _sport_family(sport):
    s = str(sport or '').lower()
    if s in ('mlb', 'wbc') or 'baseball' in s:
        return 'baseball'
    if s in ('nfl',) or s.startswith('ncf') or 'football' in s:
        return 'football'
    if s in ('nhl',) or 'hockey' in s:
        return 'hockey'
    if s in ('nba', 'wnba') or s.startswith('ncb') or s.startswith('ncw') or 'basketball' in s or s == 'march_madness':
        return 'basketball'
    if s.startswith('soccer'):
        return 'soccer'
    return 'other'


_DESCRIBERS = {
    'baseball': _describe_baseball,
    'football': _describe_football,
    'hockey': _describe_hockey,
    'basketball': _describe_basketball,
    'soccer': _describe_soccer,
}

# Plays that earn a longer hold. These are the ones a fan wants to look up for,
# not the ones that scroll past while they're in the kitchen.
_BIG_KINDS = frozenset({
    'grand_slam', 'three_run_hr', 'hat_trick', 'pick_six', 'fumble_td',
    'kick_return_td', 'punt_return_td', 'shorthanded', 'empty_net',
    'penalty_shot', 'safety',
})


def describe_score(sport, delta, play):
    """Return ``(kind, headline)`` for a scoring change.

    ``delta`` carries the arithmetic — how many runs, points, or goals — and
    ``play`` carries the prose. A homer is a grand slam only when both agree.
    """
    play = play or {}
    describer = _DESCRIBERS.get(_sport_family(sport))
    if describer is None:
        return ('score', f"+{delta}" if delta else 'SCORE')
    return describer(max(1, int(delta)), play)


class ScoreAlertTracker:
    """Remembers scores between buffer builds and emits alerts on increases."""

    def __init__(self):
        self._lock = threading.Lock()
        self._scores = {}       # game_id -> (home_score, away_score)
        self._alerts = []       # newest last
        self._last_team_score = {}   # (game_id, side) -> monotonic ts

    def _suppress(self, game_id, side, sport, delta, now):
        """True for the extra point that trails a touchdown by a few seconds."""
        if _sport_family(sport) != 'football' or delta != 1:
            return False
        last = self._last_team_score.get((game_id, side))
        return last is not None and (now - last) <= _CONVERSION_WINDOW

    def ingest(self, games):
        """Compare a freshly built sports buffer against the previous one."""
        if not games:
            return []

        now = time.time()
        emitted = []

        with self._lock:
            for game in games:
                if not isinstance(game, dict):
                    continue
                if str(game.get('type', '')) != 'scoreboard':
                    continue

                gid = str(game.get('id', ''))
                if not gid:
                    continue

                home = _int_or_none(game.get('home_score'))
                away = _int_or_none(game.get('away_score'))
                if home is None or away is None:
                    continue

                previous = self._scores.get(gid)
                self._scores[gid] = (home, away)

                # A game seen for the first time has no "before" to compare
                # against — every live game would fire on the first poll after a
                # restart otherwise.
                if previous is None:
                    continue
                if str(game.get('state', '')).lower() not in _LIVE_STATES:
                    continue

                for side, new_score, old_score in (
                    ('home', home, previous[0]),
                    ('away', away, previous[1]),
                ):
                    delta = new_score - old_score
                    if delta <= 0:
                        continue

                    sport = str(game.get('sport', '')).lower()
                    if self._suppress(gid, side, sport, delta, now):
                        self._last_team_score[(gid, side)] = now
                        continue
                    self._last_team_score[(gid, side)] = now

                    alert = self._build_alert(game, side, delta, home, away, now)
                    self._alerts.append(alert)
                    emitted.append(alert)

            # Drop score memory for games no longer in the buffer, so a full
            # slate turnover doesn't grow the dict for the life of the process.
            live_ids = {str(g.get('id', '')) for g in games if isinstance(g, dict)}
            for stale in [k for k in self._scores if k not in live_ids]:
                del self._scores[stale]
            for stale in [k for k in self._last_team_score if k[0] not in live_ids]:
                del self._last_team_score[stale]

            if len(self._alerts) > _MAX_ALERTS:
                self._alerts = self._alerts[-_MAX_ALERTS:]

        return emitted

    def _build_alert(self, game, side, delta, home_score, away_score, now):
        other = 'away' if side == 'home' else 'home'
        sport = str(game.get('sport', '')).lower()
        play = game.get('last_play') if isinstance(game.get('last_play'), dict) else {}

        # The play block describes whichever team ran the last play, which after
        # a turnover is not the team that just scored. Only trust it when it
        # agrees, or when it does not name a team at all.
        play_team = str(play.get('team', '')).upper()
        scorer_abbr = str(game.get(f'{side}_abbr', '')).upper()
        if play_team and play_team != scorer_abbr:
            play = {}

        kind, headline = describe_score(sport, delta, play)
        athlete = _last_name(play.get('athlete') or play.get('scorer'))

        return {
            'id': f"{game.get('id')}:{home_score}-{away_score}:{side}",
            'game_id': str(game.get('id', '')),
            'sport': sport,
            'ts': now,
            'side': side,
            'kind': kind,
            'headline': headline,
            'detail': athlete,
            'points': delta,
            'big': kind in _BIG_KINDS,
            'team_abbr': scorer_abbr,
            'team_logo': game.get(f'{side}_logo', ''),
            'team_color': game.get(f'{side}_color', ''),
            'team_alt_color': game.get(f'{side}_alt_color', ''),
            'opp_abbr': str(game.get(f'{other}_abbr', '')).upper(),
            'opp_logo': game.get(f'{other}_logo', ''),
            'opp_color': game.get(f'{other}_color', ''),
            'home_abbr': str(game.get('home_abbr', '')).upper(),
            'away_abbr': str(game.get('away_abbr', '')).upper(),
            'home_score': home_score,
            'away_score': away_score,
            'status': str(game.get('status', '')),
        }

    def inject(self, alert):
        """Add a ready-made alert, as the debug route does.

        Scoring plays are rare and unschedulable, so the only other way to see
        the takeover on real panels is to wait for one. This puts a synthetic
        alert through the identical path — same buffer, same delivery, same
        gating — so what a test fires is what a real run scores.
        """
        alert = dict(alert)
        alert['ts'] = time.time()
        with self._lock:
            self._alerts.append(alert)
            if len(self._alerts) > _MAX_ALERTS:
                self._alerts = self._alerts[-_MAX_ALERTS:]
        return alert

    def recent(self, max_age=DEFAULT_MAX_AGE, delay=0.0):
        """Alerts released within ``max_age`` seconds, oldest first.

        ``delay`` is the ticker's live-delay setting, and it shifts *when* an
        alert is allowed out, not which ones exist. A board running 45 seconds
        behind the broadcast is showing a snapshot of the slate from 45 seconds
        ago; firing the takeover the instant the run scores would announce it
        before the viewer's stream got there, and would put a score on screen
        that disagrees with the ticker still visible underneath the wipe.

        Holding each alert for exactly the delay lines the two up: content
        served at time W is the buffer as it stood at W - delay, so an alert
        detected at T belongs on screen at T + delay, where the scores it
        carries are the scores being displayed.
        """
        delay = max(0.0, float(delay or 0.0))
        now = time.time()
        released_after = now - delay          # not yet due if ts is later
        expires_before = released_after - max_age
        with self._lock:
            return [
                dict(a) for a in self._alerts
                if expires_before <= a['ts'] <= released_after
            ]


score_alerts = ScoreAlertTracker()
