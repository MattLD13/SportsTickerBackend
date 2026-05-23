import sys; sys.path.insert(0, '.')
from sports_ticker.fetchers.sports import SportsFetcher
import time
f = SportsFetcher('New York', 40.7128, -74.0060)
f._fetch_f1(force=True)
g = f._fetch_f1(force=True)
d = g.get('f1', {}) if g else {}
print('Session:', d.get('session_name'))
print('Drivers:')
for dr in d.get('drivers', [])[:5]:
    print(f"{dr['pos']}: {dr['name']} ({dr['gap']})")
