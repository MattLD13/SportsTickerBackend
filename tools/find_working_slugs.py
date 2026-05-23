import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from sports_ticker.fetchers.sports_f1 import _F1_CAR_URL
import requests

candidates = {
    'red-bull': ['red-bull-racing', 'oracle-red-bull-racing', 'redbullracing', 'red-bull', 'redbull', 'oracle-red-bull', 'redbull-racing', 'rbr', 'racing-bulls'],
    'racing-bulls': ['racing-bulls', 'red-bull-racing', 'redbullracing', 'redbull'],
    'aston-martin': ['aston-martin', 'aston-martin-cognizant', 'astonmartin', 'aston-martin-aramco', 'aston-martin-aramco-mercedes', 'aston-martin-mercedes', 'astonmartincognizant'],
    'kick-sauber': ['kick-sauber', 'sauber', 'sauber-f1-team', 'alfa-romeo', 'alfa-romeo-f1-team', 'alfa-romeo-racing']
}

for team, slugs in candidates.items():
    print('\nTEAM:', team)
    for slug in slugs:
        url = _F1_CAR_URL.format(slug=slug)
        try:
            r = requests.head(url, timeout=10)
            print(slug.ljust(30), r.status_code, url)
            if r.status_code == 200:
                break
        except Exception as e:
            print(slug.ljust(30), 'ERR', e)
