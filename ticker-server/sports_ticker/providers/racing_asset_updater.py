import logging
import re
import requests
from typing import Dict, Optional

logger = logging.getLogger(__name__)

IMSA_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
    'Accept': 'image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8',
    'Referer': 'https://www.imsa.com/'
}

WEC_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
    'Referer': 'https://www.fiawec.com/'
}

class RacingAssetUpdater:
    """
    Dynamic discovery and auto-update service for IMSA and FIA WEC car liveries.
    Ensures forward-compatibility for 2027+ seasons and new car/team entries.
    """

    def __init__(self):
        self._imsa_cache: Dict[str, str] = {}
        self._wec_cache: Dict[str, str] = {}

    def fetch_new_imsa_assets(self, year: Optional[int] = None) -> Dict[str, str]:
        """
        Discovers new IMSA car illustrations from the live WordPress REST API.
        Extracts both _WT_ competition cutouts and _IWSC_ entry livery vectors.
        """
        discovered = {}
        queries = ['443x113', '988x252', 'WT_GTP', 'WT_GTD', 'WT_P2', 'IWSC']
        if year:
            queries.extend([f'{year}_IWSC', f'{str(year)[2:]}_WT'])

        for q in queries:
            url = f'https://www.imsa.com/wp-json/wp/v2/media?search={q}&per_page=100'
            try:
                r = requests.get(url, headers=IMSA_HEADERS, timeout=6)
                if r.status_code == 200:
                    for item in r.json():
                        src = item.get('source_url', '')
                        if src.endswith('.png') and not any(ign in src.lower() for ign in ['driver', 'headshot', 'logo', 'crest', 'tunein']):
                            # Match car number
                            match = re.search(r'_(?:GTP|GTD|GTDPRO|P2|IWSC)_[A-Za-z]*_?(\d+)_', src, re.IGNORECASE) or re.search(r'_(\d+)_\d+x\d+', src)
                            if match:
                                car_num = match.group(1).lstrip('0') or '0'
                                discovered[car_num] = src
                                self._imsa_cache[car_num] = src
            except Exception as e:
                logger.debug("IMSA media auto-discovery error: %s", e)

        return discovered

    def fetch_new_wec_assets(self, year: Optional[int] = None) -> Dict[str, str]:
        """
        Discovers new WEC droit car illustrations from the live sitemap and news feed.
        """
        discovered = {}
        sitemap_url = 'https://www.fiawec.com/sitemap-articles.xml'
        try:
            r = requests.get(sitemap_url, headers=WEC_HEADERS, timeout=8)
            if r.status_code == 200:
                articles = re.findall(r'<loc>(https://www\.fiawec\.com/[^<]+)</loc>', r.text)
                relevant = [a for a in articles if any(k in a.lower() for k in ['livery', 'liveries', 'grid', 'hypercar', 'lmgt3'])]
                for art_url in relevant[:30]:
                    try:
                        res = requests.get(art_url, headers=WEC_HEADERS, timeout=4)
                        if res.status_code == 200:
                            matches = re.findall(r'https://www\.fiawec\.com/media/cache/[^"\'\s]+-(?:droit|droite)-[a-f0-9]+\.png(?:\.webp)?', res.text)
                            for m in matches:
                                clean = m.replace('/news_card/', '/resolve/news_card/').replace('.webp', '')
                                num_match = re.search(r'-wec-(\d+)-', clean)
                                if num_match:
                                    num = num_match.group(1).lstrip('0') or '0'
                                    discovered[num] = clean
                                    self._wec_cache[num] = clean
                    except Exception:
                        pass
        except Exception as e:
            logger.debug("WEC media auto-discovery error: %s", e)

        return discovered

    def resolve_imsa_car(self, car_num: str, team: str = "", model: str = "") -> Optional[str]:
        """
        Resolves car illustration URL for IMSA entry with dynamic discovery fallback.
        """
        num_clean = car_num.lstrip('0') or '0'
        if num_clean in self._imsa_cache:
            return self._imsa_cache[num_clean]

        # Trigger on-demand auto-discovery if unknown car
        self.fetch_new_imsa_assets()
        return self._imsa_cache.get(num_clean)

    def resolve_wec_car(self, car_num: str, team: str = "", model: str = "") -> Optional[str]:
        """
        Resolves car illustration URL for WEC entry with dynamic discovery fallback.
        """
        num_clean = car_num.lstrip('0') or '0'
        if num_clean in self._wec_cache:
            return self._wec_cache[num_clean]

        # Trigger on-demand auto-discovery if unknown car
        self.fetch_new_wec_assets()
        return self._wec_cache.get(num_clean)
