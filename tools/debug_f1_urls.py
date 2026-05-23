import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sports_ticker.fetchers import sports_f1
from sports_ticker.fetchers.sports_f1 import _F1_TEAM_SLUGS, _F1_CAR_URL

seen = set()
print('Team key'.ljust(40), 'slug'.ljust(20), ' -> URL')
for key, slug in _F1_TEAM_SLUGS.items():
    if (slug, key) in seen:
        continue
    seen.add((slug, key))
    url = _F1_CAR_URL.format(slug=slug)
    print(key.ljust(40), slug.ljust(20), '->', url)
