import time
import os
import json
import requests
from modules.config import STOCK_CACHE_FILE, STOCKS_UPDATE_INTERVAL, LEAGUE_OPTIONS
from modules.utils import save_json_atomically

class StockFetcher:
    def __init__(self):
        self.market_cache = {}
        self.last_fetch = 0
        self.update_interval = STOCKS_UPDATE_INTERVAL

        possible_keys = [
            os.getenv('FINNHUB_API_KEY'),
            os.getenv('FINNHUB_KEY_1'),
            os.getenv('FINNHUB_KEY_2'),
            os.getenv('FINNHUB_KEY_3'),
            os.getenv('FINNHUB_KEY_4'),
            os.getenv('FINNHUB_KEY_5')
        ]
        self.api_keys = list(set([k for k in possible_keys if k and len(k) > 10]))

        if not self.api_keys:
            print("⚠️ FATAL: No Finnhub API keys found! Check .env file.")
            self.safe_sleep_time = 60
        else:
            self.safe_sleep_time = 1.1 / len(self.api_keys)
            print(f"✅ Loaded {len(self.api_keys)} API Keys. Stock Speed: {self.safe_sleep_time:.2f}s per request.")

        self.current_key_index = 0
        self.session = requests.Session()
        self.lists = { item['id']: item['stock_list'] for item in LEAGUE_OPTIONS if item['type'] == 'stock' and 'stock_list' in item }
        self.ETF_DOMAINS = {"QQQ": "invesco.com", "SPY": "spdrs.com", "IWM": "ishares.com", "DIA": "statestreet.com"}
        self.load_cache()

    def load_cache(self):
        if os.path.exists(STOCK_CACHE_FILE):
            try:
                with open(STOCK_CACHE_FILE, 'r') as f: self.market_cache = json.load(f)
            except: pass

    def save_cache(self):
        try: save_json_atomically(STOCK_CACHE_FILE, self.market_cache)
        except: pass

    def get_logo_url(self, symbol):
        sym = symbol.upper()
        if sym in self.ETF_DOMAINS: return f"https://logo.clearbit.com/{self.ETF_DOMAINS[sym]}"
        clean_sym = sym.replace('.', '-')
        return f"https://financialmodelingprep.com/image-stock/{clean_sym}.png"

    def _get_next_key(self):
        if not self.api_keys: return None
        key = self.api_keys[self.current_key_index]
        self.current_key_index = (self.current_key_index + 1) % len(self.api_keys)
        return key

    def _fetch_single_stock(self, symbol):
        api_key = self._get_next_key()
        if not api_key: return None

        try:
            r = self.session.get("https://finnhub.io/api/v1/quote", params={'symbol': symbol, 'token': api_key}, timeout=5)
            if r.status_code == 429: time.sleep(2); return None
            r.raise_for_status()
            data = r.json()

            ts = data.get('t', 0)
            now_ts = time.time()
            is_stale = (now_ts - ts) > 600

            if not is_stale and data.get('c', 0) > 0:
                price = data.get('c', 0); change_raw = data.get('d', 0); change_pct = data.get('dp', 0)
                return {
                    'symbol': symbol,
                    'price': f"{price:.2f}",
                    'change_amt': f"{'+' if change_raw >= 0 else ''}{change_raw:.2f}",
                    'change_pct': f"{'+' if change_pct >= 0 else ''}{change_pct:.2f}%"
                }

            if is_stale:
                to_time = int(now_ts)
                from_time = to_time - 1800
                c_url = "https://finnhub.io/api/v1/stock/candle"
                c_params = {'symbol': symbol, 'resolution': '1', 'from': from_time, 'to': to_time, 'token': api_key}

                c_r = self.session.get(c_url, params=c_params, timeout=5)
                c_data = c_r.json()

                if c_data.get('s') == 'ok' and c_data.get('c'):
                    latest_close = c_data['c'][-1]
                    prev_close = data.get('pc', latest_close)
                    change_raw = latest_close - prev_close
                    change_pct = (change_raw / prev_close) * 100

                    return {
                        'symbol': symbol,
                        'price': f"{latest_close:.2f}",
                        'change_amt': f"{'+' if change_raw >= 0 else ''}{change_raw:.2f}",
                        'change_pct': f"{'+' if change_pct >= 0 else ''}{change_pct:.2f}%"
                    }

            if data.get('c', 0) > 0:
                price = data.get('c', 0); change_raw = data.get('d', 0); change_pct = data.get('dp', 0)
                return {
                    'symbol': symbol,
                    'price': f"{price:.2f}",
                    'change_amt': f"{'+' if change_raw >= 0 else ''}{change_raw:.2f}",
                    'change_pct': f"{'+' if change_pct >= 0 else ''}{change_pct:.2f}%"
                }

        except Exception as e:
            return None
        return None

    def update_market_data(self, active_lists):
        if time.time() - self.last_fetch < self.update_interval: return
        target_symbols = set()
        for list_key in active_lists:
            if list_key in self.lists: target_symbols.update(self.lists[list_key])
        if not target_symbols: return

        updated_count = 0
        for symbol in list(target_symbols):
            res = self._fetch_single_stock(symbol)
            if res:
                self.market_cache[res['symbol']] = {'price': res['price'], 'change_amt': res['change_amt'], 'change_pct': res['change_pct']}
                updated_count += 1
            time.sleep(self.safe_sleep_time)

        if updated_count > 0:
            self.last_fetch = time.time()
            self.save_cache()

    def get_stock_obj(self, symbol, label):
        data = self.market_cache.get(symbol)
        if not data: return None
        return {
            'type': 'stock_ticker', 'sport': 'stock', 'id': f"stk_{symbol}", 'status': label, 'tourney_name': label,
            'state': 'in', 'is_shown': True, 'home_abbr': symbol,
            'home_score': data['price'], 'away_score': data['change_pct'],
            'home_logo': self.get_logo_url(symbol), 'situation': {'change': data['change_amt']},
            'home_color': '#FFFFFF', 'away_color': '#FFFFFF'
        }

    def get_list(self, list_key):
        res = []
        label_item = next((item for item in LEAGUE_OPTIONS if item['id'] == list_key), None)
        label = label_item['label'] if label_item else "MARKET"
        for sym in self.lists.get(list_key, []):
            obj = self.get_stock_obj(sym, label)
            if obj: res.append(obj)
        return res
