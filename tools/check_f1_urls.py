import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sports_ticker.fetchers.sports_f1 import _F1_TEAM_SLUGS, _F1_CAR_URL
import requests

for key, slug in _F1_TEAM_SLUGS.items():
    url = _F1_CAR_URL.format(slug=slug)
    try:
        r = requests.head(url, timeout=10)
        print(key.ljust(30), slug.ljust(20), r.status_code, url)
    except Exception as e:
        print(key.ljust(30), slug.ljust(20), 'ERR', e)
