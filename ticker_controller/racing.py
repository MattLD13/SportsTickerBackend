"""Shared helpers for IndyCar / F1 / NASCAR racing display modes."""

RACING_SPORTS = frozenset({'indycar', 'f1', 'nascar'})


def is_racing_game(game) -> bool:
    if not isinstance(game, dict):
        return False
    if str(game.get('type') or '').lower() == 'racing':
        return True
    return str(game.get('sport') or '').lower() in RACING_SPORTS


def racing_sport(game) -> str:
    sport = str((game or {}).get('sport') or '').lower()
    if sport in RACING_SPORTS:
        return sport
    if str((game or {}).get('type') or '').lower() == 'racing':
        for key in RACING_SPORTS:
            if (game or {}).get(key):
                return key
    return 'indycar'


def racing_payload(game) -> dict:
    if not isinstance(game, dict):
        return {}
    sport = racing_sport(game)
    payload = game.get(sport)
    if isinstance(payload, dict) and payload:
        return payload
    return game.get('indycar') or {}
