"""Replay recorded real provider results through the provider interface.

The old engine and the new engine both read these providers, so a test can
compare their V2 output. Set TICKER3_REPLAY_DIR to the fixture folder.
"""
import json
import os
import time
from pathlib import Path

from backend_ops.worker_contract import decode_result
from sports_ticker.providers.contracts import ProviderResult


class ReplayProvider:
    def __init__(self, name):
        self.name = name
        path = Path(os.environ.get("TICKER3_REPLAY_DIR", Path(__file__).resolve().parents[2] / "fixtures" / "ticker3")) / f"{name}_result.json"
        self.encoded = json.loads(path.read_text(encoding="utf-8"))["result"] if path.exists() else None
        self.calls = []

    def _result(self):
        if self.encoded is None:
            return ProviderResult()
        return decode_result(self.encoded)

    def fetch(self, settings):
        self.calls.append(("fetch", None))
        return self._result()

    def fetch_for_ticker(self, ticker_id, settings):
        self.calls.append(("fetch_for_ticker", ticker_id))
        return self._result()


class ReplayEspn(ReplayProvider):
    def fetch_live_for_ticker(self, ticker_id, settings):
        self.calls.append(("fetch_live_for_ticker", ticker_id))
        return self._result()

    def fetch_batch_for_tickers(self, settings_by_ticker, *, live_only=False):
        self.calls.append(("fetch_batch_for_tickers", tuple(sorted(settings_by_ticker)), live_only))
        return {ticker_id: self._result() for ticker_id in settings_by_ticker}

    def wait_for_changes(self, after, timeout):
        time.sleep(min(timeout, 0.5))
        return dict(after)


def create(name, database_path=None):
    return ReplayEspn(name) if name == "espn" else ReplayProvider(name)
