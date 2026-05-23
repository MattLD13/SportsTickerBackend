"""Display mode definitions."""

# Modes
# Modes are content choices. Full-screen rendering is presentation state, not a mode.
MODE_OPTIONS = [
    {'id': 'sports', 'label': 'Sports', 'default': True, 'family': 'sports'},
    {'id': 'live', 'label': 'Live Sports', 'default': True, 'family': 'sports'},
    {'id': 'my_teams', 'label': 'My Teams', 'default': True, 'family': 'sports'},
    {'id': 'soccer', 'label': 'Soccer', 'default': True, 'family': 'sports'},
    {'id': 'stocks', 'label': 'Stocks', 'default': True, 'family': 'market'},
    {'id': 'weather', 'label': 'Weather', 'default': True, 'family': 'utility'},
    {'id': 'music', 'label': 'Music', 'default': True, 'family': 'utility'},
    {'id': 'clock', 'label': 'Clock', 'default': True, 'family': 'utility'},
    {'id': 'golf', 'label': 'Golf', 'default': True, 'family': 'sport'},
    {'id': 'masters', 'label': 'Masters', 'default': True, 'family': 'legacy'},
    {'id': 'flights', 'label': 'Airport Activity', 'default': True, 'family': 'flight'},
    {'id': 'flight_tracker', 'label': 'Flight Tracker', 'default': True, 'family': 'flight'},
    {'id': 'indycar', 'label': 'IndyCar', 'default': True, 'family': 'racing'},
    {'id': 'f1', 'label': 'Formula 1', 'default': True, 'family': 'racing'},
    {'id': 'nascar', 'label': 'NASCAR', 'default': False, 'family': 'racing'},
]

VALID_MODES = frozenset(item['id'] for item in MODE_OPTIONS)
_VALID_MODE_IDS = VALID_MODES
_MODE_LABEL_MAP = {item['id']: item['label'] for item in MODE_OPTIONS}

MODE_MIGRATIONS = {
    'all': 'sports',
    'flight2': 'flight_tracker',
    'poop_fetcher': 'sports',
    'masters': 'golf',
    'sports_full': 'sports',
    'soccer_full': 'soccer',
    'indycar_full': 'indycar',
    'f1_full': 'f1',
    'nascar_full': 'nascar',
}